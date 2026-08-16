from __future__ import annotations

"""PostgreSQL-authoritative compatibility views for remaining Stage 4 units.

The reconciled S1 baseline remains immutable in ``migration.source_row``.
Post-cutover mutations live in a small copy-on-write overlay.  This module
builds a disposable in-memory SQLite read projection so legacy SELECT paths can
survive the mixed window without reading the retired SQLite-owned tables.
Writes to the TEMP views fail; formal writes must use an audited domain adapter.
There is deliberately no PostgreSQL-to-SQLite fallback.
"""

import hashlib
import base64
import json
import math
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any


class DomainDataError(RuntimeError):
    pass


class DomainDataWriterFenced(DomainDataError):
    pass


# The compatibility adapter intentionally materializes one reviewed unit for
# legacy SQLite-shaped code.  It is safe for the six small/medium Stage 4
# units, but must never pull the multi-million-row sentiment domain into RAM.
# Sentiment requires its separately reviewed persistent projection/runner
# before authority may advance.
MAX_IN_MEMORY_COMPATIBILITY_ROWS = 250_000


def _json_value(value: Any) -> Any:
    """Encode SQLite values with the same contract as the S1 snapshot."""

    if isinstance(value, bytes):
        return {"$binary_base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, float) and not math.isfinite(value):
        return {"$nonfinite_float": repr(value)}
    return value


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _identifier(value: str) -> str:
    if not value or not value.replace("_", "").isalnum():
        raise DomainDataError(f"unsafe domain identifier: {value}")
    return '"' + value.replace('"', '""') + '"'


def _finalize_readonly(connection: sqlite3.Connection) -> None:
    """Apply the caller-visible read fence after internal view assembly."""

    connection.execute("PRAGMA query_only=ON")


def _sqlite_type(value: str | None) -> str:
    declared = str(value or "").upper()
    if "INT" in declared:
        return "INTEGER"
    if any(item in declared for item in ("REAL", "FLOA", "DOUB", "NUM", "DEC")):
        return "REAL"
    if "BLOB" in declared:
        return "BLOB"
    return "TEXT"


def _sqlite_value(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"$binary_base64"}:
        return base64.b64decode(str(value["$binary_base64"]), validate=True)
    if isinstance(value, dict) and set(value) == {"$nonfinite_float"}:
        raw = str(value["$nonfinite_float"])
        converted = {"nan": math.nan, "inf": math.inf, "-inf": -math.inf}.get(raw.lower())
        if converted is None:
            raise DomainDataError("invalid non-finite float encoding")
        return converted
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


class PostgresDomainReadCache:
    def __init__(
        self,
        unit: str,
        connection_factory: Callable[[], Any],
        *,
        refresh_check_seconds: float = 1.0,
    ) -> None:
        self.unit = unit
        self._connect = connection_factory
        self._refresh_check_seconds = refresh_check_seconds
        self._lock = threading.RLock()
        # Named shared-memory SQLite databases are process-global.  Two
        # independent caches for the same unit/version must not reuse the
        # same URI while either keeper is alive (the Viewer legitimately has
        # both route-local and dependency caches).
        self._cache_id = uuid.uuid4().hex
        self._keeper: sqlite3.Connection | None = None
        self._uri: str | None = None
        self._token: str | None = None
        self._tables: tuple[str, ...] = ()
        self._next_check = 0.0

    def _load(self) -> tuple[str, dict[str, list[dict[str, Any]]] | None, dict[str, list[dict[str, Any]]]]:
        connection = self._connect()
        try:
            authority = connection.execute(
                """SELECT state,authoritative_backend,state_revision,cutover_epoch,
                          source_snapshot_id,source_identity_sha256,
                          source_content_sha256,source_row_count,source_watermark,
                          formal_revision,overlay_count,overlay_revision_sum,
                          overlay_last_update
                     FROM domain_data.unit_runtime_contract_v1(%s)""",
                (self.unit,),
            ).fetchone()
            if authority is None:
                raise DomainDataError(f"formal PostgreSQL snapshot is absent: {self.unit}")
            if str(authority[0]) not in {"S3", "S4"} or str(authority[1]) != "postgresql_production":
                raise DomainDataError(f"PostgreSQL is not authoritative: {self.unit}")
            watermark = authority[8] if isinstance(authority[8], dict) else json.loads(authority[8])
            token = hashlib.sha256(
                json.dumps(
                    [str(value) if value is not None else None for value in authority[:8]]
                    + [int(authority[9]), int(authority[10]), str(authority[11])],
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            schemas: dict[str, list[dict[str, Any]]] = {}
            for table in (watermark.get("tables") or []):
                name = str(table.get("source_table") or "")
                columns = ((table.get("schema") or {}).get("columns") or [])
                if not name or not columns or name in schemas:
                    raise DomainDataError(f"invalid or duplicate schema contract: {self.unit}:{name}")
                schemas[name] = [dict(column) for column in columns]
            if not schemas:
                raise DomainDataError(f"schema contract is empty: {self.unit}")
            source_row_count = int(authority[7])
            if source_row_count > MAX_IN_MEMORY_COMPATIBILITY_ROWS:
                raise DomainDataError(
                    f"{self.unit} exceeds the reviewed in-memory read bound; "
                    "a persistent unit projection is required"
                )
            # ``self._token`` stores the complete materialized version
            # (authority token + row digest), while ``token`` is only the
            # inexpensive authority/overlay fingerprint.  Comparing them for
            # equality forced an identical shared-memory URI to be rebuilt on
            # every refresh check; the still-live keeper then correctly
            # rejected duplicate CREATE TABLE statements.  A fixed-width
            # authority-token prefix proves that the existing projection is
            # current without reopening retired SQLite or rematerializing it.
            if (
                self._token is not None
                and self._token.startswith(token + "_")
                and self._uri is not None
            ):
                return self._token, None, schemas
            rows = connection.execute(
                "SELECT * FROM domain_data.read_unit_records_v1(%s)", (self.unit,)
            ).fetchall()
        finally:
            connection.close()
        grouped = {table: [] for table in schemas}
        digest = hashlib.sha256(token.encode("ascii"))
        for database, table, ordinal, key, row_sha, raw_payload, revision, deleted in rows:
            name = str(table)
            if name not in grouped:
                raise DomainDataError(f"record is outside schema contract: {self.unit}:{name}")
            if bool(deleted):
                continue
            payload = raw_payload if isinstance(raw_payload, dict) else json.loads(raw_payload)
            if not isinstance(payload, dict):
                raise DomainDataError("domain payload is not an object")
            grouped[name].append(payload)
            digest.update(
                json.dumps(
                    [str(database), name, int(ordinal), str(key), str(row_sha), int(revision)],
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            digest.update(b"\n")
        return f"{token}_{digest.hexdigest()}", grouped, schemas

    def _build(
        self,
        version: str,
        grouped: dict[str, list[dict[str, Any]]],
        schemas: dict[str, list[dict[str, Any]]],
    ) -> None:
        uri = (
            f"file:honghu_domain_{self.unit}_{self._cache_id}_{version}"
            "?mode=memory&cache=shared"
        )
        keeper = sqlite3.connect(uri, uri=True, check_same_thread=False)
        try:
            for table, columns in schemas.items():
                definitions = []
                ordered_names = []
                for column in sorted(columns, key=lambda item: int(item.get("cid") or 0)):
                    name = str(column.get("name") or "")
                    ordered_names.append(name)
                    definitions.append(f"{_identifier(name)} {_sqlite_type(column.get('type'))}")
                keeper.execute(
                    f"CREATE TABLE {_identifier(table)} ({','.join(definitions)})"
                )
                rows = grouped.get(table) or []
                if rows:
                    keeper.executemany(
                        f"INSERT INTO {_identifier(table)} VALUES ({','.join('?' for _ in ordered_names)})",
                        [
                            tuple(_sqlite_value(row.get(name)) for name in ordered_names)
                            for row in rows
                        ],
                    )
            keeper.commit()
            keeper.execute("PRAGMA query_only=ON")
        except Exception:
            keeper.close()
            raise
        old = self._keeper
        self._keeper = keeper
        self._uri = uri
        self._token = version
        self._tables = tuple(schemas)
        if old is not None:
            old.close()

    def ensure_current(self) -> str:
        now = time.monotonic()
        with self._lock:
            if self._uri is None or now >= self._next_check:
                version, grouped, schemas = self._load()
                if grouped is not None:
                    self._build(version, grouped, schemas)
                self._next_check = now + self._refresh_check_seconds
            if self._uri is None:
                raise DomainDataError(f"PostgreSQL domain cache is unavailable: {self.unit}")
            return self._uri

    def connect(self, *, finalize_readonly: bool = True) -> sqlite3.Connection:
        uri = self.ensure_current()
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        if finalize_readonly:
            _finalize_readonly(connection)
        return connection

    def attach(self, connection: sqlite3.Connection) -> None:
        uri = self.ensure_current()
        alias = "pg_" + self.unit
        connection.execute(f"ATTACH DATABASE ? AS {_identifier(alias)}", (uri,))
        for table in self._tables:
            quoted = _identifier(table)
            connection.execute(
                f"CREATE TEMP VIEW {quoted} AS SELECT * FROM {_identifier(alias)}.{quoted}"
            )

    def close(self) -> None:
        with self._lock:
            if self._keeper is not None:
                self._keeper.close()
            self._keeper = None
            self._uri = None
            self._token = None
            self._tables = ()


class PostgresDomainCompatibilityConnection:
    """SQLite-shaped transaction surface backed by one PostgreSQL authority.

    Existing domain code may execute its established SQLite transaction against
    a private in-memory projection.  ``commit`` computes the row delta and sends
    the complete dependency cluster to PostgreSQL in one idempotent transaction.
    The old SQLite file is never opened in PostgreSQL-authoritative mode.

    This is an application-transition adapter, not a long-term dual-write or
    synchronization mechanism.  Every logical transaction requires a stable
    operation identity supplied by its trusted caller.
    """

    def __init__(
        self,
        unit: str,
        read_connection_factory: Callable[[], Any],
        write_connection_factory: Callable[[], Any],
        *,
        owned_objects: frozenset[tuple[str, str]],
        writer_identity: str,
        operation_scope: str,
        operation_id: str,
        actor: str,
    ) -> None:
        if not operation_id.strip() or not operation_scope.strip() or not actor.strip():
            raise DomainDataWriterFenced(
                "PostgreSQL mutation requires stable operation identity and trusted actor"
            )
        self.unit = unit
        self._read_connect = read_connection_factory
        self._write_connect = write_connection_factory
        self._owned_objects = owned_objects
        self._writer_identity = writer_identity
        self._operation_scope = operation_scope
        self._operation_id = operation_id
        self._actor = actor
        self._transaction_index = 0
        self._pending_batch_key: str | None = None
        self._pending_request_hash: str | None = None
        self._pending_mutations: list[dict[str, Any]] | None = None
        self._closed = False
        # URI mode is required so read-only dependency database URIs retain
        # ``mode=ro`` instead of being treated as literal filenames.
        self._connection = sqlite3.connect(
            f"file:honghu_compat_{uuid.uuid4().hex}?mode=memory&cache=private",
            uri=True,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._schema_by_table: dict[str, list[dict[str, Any]]] = {}
        self._database_by_table: dict[str, str] = {}
        self._before: dict[tuple[str, str, str], tuple[dict[str, Any], int]] = {}
        self._revisions: dict[tuple[str, str, str], int] = {}
        self._load()

    @staticmethod
    def _row_key(
        columns: list[dict[str, Any]], payload: dict[str, Any], ordinal: int
    ) -> str:
        primary = sorted(
            (item for item in columns if int(item.get("pk") or 0) > 0),
            key=lambda item: int(item["pk"]),
        )
        if not primary:
            raise DomainDataWriterFenced(
                "PostgreSQL compatibility writes require a stable primary key"
            )
        return _sha256_json(
            [[str(item["name"]), payload.get(str(item["name"]))] for item in primary]
        )

    def _load(self) -> None:
        connection = self._read_connect()
        try:
            authority = connection.execute(
                """SELECT state,authoritative_backend,writer_identity,
                          source_watermark,source_row_count
                     FROM domain_data.unit_runtime_contract_v1(%s)""",
                (self.unit,),
            ).fetchone()
            if authority is None:
                raise DomainDataWriterFenced("formal PostgreSQL authority is absent")
            if (
                str(authority[0]) not in {"S3", "S4"}
                or str(authority[1]) != "postgresql_production"
                or str(authority[2]) != self._writer_identity
            ):
                raise DomainDataWriterFenced("PostgreSQL writer authority is fenced")
            watermark = authority[3]
            if not isinstance(watermark, dict):
                watermark = json.loads(watermark)
            source_row_count = int(authority[4])
            if source_row_count > MAX_IN_MEMORY_COMPATIBILITY_ROWS:
                raise DomainDataWriterFenced(
                    f"{self.unit} exceeds the reviewed in-memory compatibility bound; "
                    "a persistent unit adapter is required"
                )
            for item in watermark.get("tables") or ():
                database = str(item.get("source_database") or "")
                table = str(item.get("source_table") or "")
                columns = [dict(value) for value in ((item.get("schema") or {}).get("columns") or ())]
                if (database, table) not in self._owned_objects:
                    raise DomainDataWriterFenced(
                        f"snapshot object is outside reviewed ownership: {database}.{table}"
                    )
                if not columns or table in self._database_by_table:
                    raise DomainDataWriterFenced(
                        f"ambiguous or empty writable schema: {database}.{table}"
                    )
                if not any(int(column.get("pk") or 0) > 0 for column in columns):
                    raise DomainDataWriterFenced(
                        f"writable table has no stable primary key: {database}.{table}"
                    )
                self._database_by_table[table] = database
                self._schema_by_table[table] = columns
                definitions = [
                    f"{_identifier(str(column['name']))} {_sqlite_type(column.get('type'))}"
                    + (" PRIMARY KEY" if int(column.get("pk") or 0) > 0 and sum(
                        int(value.get("pk") or 0) > 0 for value in columns
                    ) == 1 else "")
                    for column in sorted(columns, key=lambda value: int(value.get("cid") or 0))
                ]
                # Composite primary keys must retain their original order.
                primary = sorted(
                    (value for value in columns if int(value.get("pk") or 0) > 0),
                    key=lambda value: int(value["pk"]),
                )
                if len(primary) > 1:
                    definitions.append(
                        "PRIMARY KEY ("
                        + ",".join(_identifier(str(value["name"])) for value in primary)
                        + ")"
                    )
                self._connection.execute(
                    f"CREATE TABLE {_identifier(table)} ({','.join(definitions)})"
                )
            rows = connection.execute(
                "SELECT * FROM domain_data.read_unit_records_v1(%s)", (self.unit,)
            ).fetchall()
        finally:
            connection.close()
        grouped: dict[str, list[tuple[dict[str, Any], str, int, bool]]] = {
            table: [] for table in self._schema_by_table
        }
        for database, table, ordinal, key, _row_sha, raw, revision, deleted in rows:
            table = str(table)
            if table not in grouped or str(database) != self._database_by_table[table]:
                raise DomainDataWriterFenced("PostgreSQL record violates reviewed ownership")
            payload = raw if isinstance(raw, dict) else json.loads(raw)
            grouped[table].append((payload, str(key), int(revision), bool(deleted)))
            self._revisions[(str(database), table, str(key))] = int(revision)
            if not bool(deleted):
                self._before[(str(database), table, str(key))] = (payload, int(revision))
        for table, values in grouped.items():
            columns = [
                str(item["name"])
                for item in sorted(
                    self._schema_by_table[table], key=lambda item: int(item.get("cid") or 0)
                )
            ]
            active = [payload for payload, _key, _revision, deleted in values if not deleted]
            if active:
                self._connection.executemany(
                    f"INSERT INTO {_identifier(table)} ({','.join(_identifier(name) for name in columns)}) "
                    f"VALUES ({','.join('?' for _ in columns)})",
                    [tuple(_sqlite_value(payload.get(name)) for name in columns) for payload in active],
                )
        self._connection.commit()

    def _current(self) -> dict[tuple[str, str, str], dict[str, Any]]:
        current: dict[tuple[str, str, str], dict[str, Any]] = {}
        for table, columns in self._schema_by_table.items():
            names = [
                str(item["name"])
                for item in sorted(columns, key=lambda item: int(item.get("cid") or 0))
            ]
            order = [
                str(item["name"])
                for item in sorted(
                    (value for value in columns if int(value.get("pk") or 0) > 0),
                    key=lambda value: int(value["pk"]),
                )
            ]
            query = f"SELECT * FROM {_identifier(table)} ORDER BY " + ",".join(
                _identifier(name) for name in order
            )
            for ordinal, row in enumerate(self._connection.execute(query), start=1):
                payload = {name: _json_value(row[name]) for name in names}
                key = self._row_key(columns, payload, ordinal)
                current[(self._database_by_table[table], table, key)] = payload
        return current

    def _mutations(self) -> list[dict[str, Any]]:
        after = self._current()
        mutations: list[dict[str, Any]] = []
        for identity in sorted(set(self._before) | set(after)):
            previous = self._before.get(identity)
            replacement = after.get(identity)
            if previous is not None and replacement == previous[0]:
                continue
            database, table, key = identity
            payload = replacement if replacement is not None else previous[0]
            mutation = {
                "source_database": database,
                "source_table": table,
                "source_key": key,
                "payload": payload,
                "row_sha256": _sha256_json(payload),
                "expected_revision": self._revisions.get(identity, 0),
                "delete": replacement is None,
            }
            mutation["request_sha256"] = _sha256_json(mutation)
            mutations.append(mutation)
        return mutations

    def commit(self) -> None:
        mutations = self._mutations()
        if not mutations:
            if self._pending_batch_key is not None:
                raise DomainDataError(
                    "PostgreSQL mutation outcome is unresolved; reconcile or retry the "
                    "same logical mutation before committing different state"
                )
            self._connection.commit()
            return
        request_hash = _sha256_json(mutations)
        if self._pending_batch_key is None:
            self._transaction_index += 1
            self._pending_batch_key = (
                f"{self._operation_id}:{self._transaction_index:08d}"
            )
            self._pending_request_hash = request_hash
            self._pending_mutations = mutations
        elif (
            request_hash != self._pending_request_hash
            or mutations != self._pending_mutations
        ):
            raise DomainDataError(
                "PostgreSQL mutation outcome is unresolved and local transaction state "
                "changed; fail closed until the original operation is reconciled"
            )
        batch_key = self._pending_batch_key
        try:
            with self._write_connect() as connection:
                row = connection.execute(
                    """
                    SELECT domain_data.apply_mutation_batch_v1(
                        %s,%s,%s,%s,%s::jsonb,%s,%s
                    )
                    """,
                    (
                        self.unit,
                        self._operation_scope,
                        batch_key,
                        request_hash,
                        json.dumps(mutations, ensure_ascii=False, sort_keys=True),
                        self._writer_identity,
                        self._actor,
                    ),
                ).fetchone()
                if row is None:
                    raise DomainDataError("PostgreSQL mutation returned no result")
        except Exception as exc:
            raise DomainDataError(
                "PostgreSQL mutation result is uncertain; retry reuses the same operation identity"
            ) from exc
        self._connection.commit()
        for mutation in mutations:
            identity = (
                mutation["source_database"], mutation["source_table"], mutation["source_key"]
            )
            if mutation["delete"]:
                self._before.pop(identity, None)
            else:
                self._before[identity] = (
                    mutation["payload"], int(mutation["expected_revision"]) + 1
                )
            self._revisions[identity] = int(mutation["expected_revision"]) + 1
        self._pending_batch_key = None
        self._pending_request_hash = None
        self._pending_mutations = None

    def rollback(self) -> None:
        if self._pending_batch_key is not None:
            raise DomainDataError(
                "PostgreSQL mutation outcome is unresolved; local rollback cannot prove "
                "the authoritative transaction did not commit"
            )
        self._connection.rollback()

    def attach_read_dependency(self, cache: Any) -> None:
        """Attach a PostgreSQL-authoritative dependency as read-only TEMP views.

        Dependency tables are never included in the owned-table diff, and the
        cache exposes them as SQLite views, so an accidental cross-unit write
        fails at SQLite before any PostgreSQL mutation is attempted.
        """

        cache.attach(self._connection)

    def close(self) -> None:
        if not self._closed:
            self._connection.close()
            self._closed = True

    def __enter__(self) -> "PostgresDomainCompatibilityConnection":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()
        return False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


_READ_CACHES: dict[tuple[str, str], PostgresDomainReadCache] = {}
_SHARED_IDENTITY_CACHES: dict[str, Any] = {}
_SENTIMENT_PROJECTIONS: dict[str, Any] = {}


def _authority_writer_factory(
    catalog: Any,
    *,
    role_key: str,
    expected_writer_identity: str,
) -> Callable[[], Any]:
    """Create connections operating as the exact authority writer role.

    Dedicated task logins are accepted only when PostgreSQL proves membership
    in the authority-matrix writer role and the session successfully assumes
    that exact role.  Login-name similarity never grants write authority.
    """

    from tools.data_platform.postgres_runtime import build_catalog_connection_factory

    base_factory = build_catalog_connection_factory(catalog, role=role_key)

    def connect() -> Any:
        connection = base_factory()
        try:
            current_user = str(connection.execute("SELECT current_user").fetchone()[0])
            if current_user == expected_writer_identity:
                return connection
            allowed = bool(
                connection.execute(
                    "SELECT pg_has_role(current_user,%s,'USAGE')",
                    (expected_writer_identity,),
                ).fetchone()[0]
            )
            if not allowed:
                raise DomainDataWriterFenced(
                    "runtime login is not a reviewed member of the authority writer role"
                )
            connection.execute(f"SET ROLE {_identifier(expected_writer_identity)}")
            assumed = str(connection.execute("SELECT current_user").fetchone()[0])
            if assumed != expected_writer_identity:
                raise DomainDataWriterFenced(
                    "runtime connection did not assume the authority writer identity"
                )
            return connection
        except Exception:
            connection.close()
            raise

    return connect


def _sentiment_projection(catalog_path: str, reader: Callable[[], Any]) -> Any:
    from tools.data_platform.sentiment_projection import PersistentSentimentProjection
    from tools.runtime_paths import resolve_runtime_layout

    return _SENTIMENT_PROJECTIONS.setdefault(
        catalog_path,
        PersistentSentimentProjection(
            resolve_runtime_layout().cache_root / "postgresql_projection",
            reader,
        ),
    )


def connect_domain_database(
    unit: str,
    sqlite_path: str | Path,
    *,
    readonly: bool,
    operation_scope: str | None = None,
    operation_id: str | None = None,
    actor: str | None = None,
) -> Any:
    """Open the current authoritative backend for one reviewed unit."""

    import os

    from tools.data_platform.postgres_runtime import (
        build_catalog_connection_factory,
        load_postgres_runtime_catalog,
    )
    from tools.data_platform.routing import (
        Backend,
        CutoverUnitRegistry,
        load_environment_authority_matrix,
    )

    matrix = load_environment_authority_matrix()
    path = Path(sqlite_path).resolve()
    if matrix is None:
        if not readonly:
            from tools.data_platform.local_authority_fence import (
                assert_sqlite_write_allowed,
            )

            assert_sqlite_write_allowed(path.parent, unit)
        if readonly:
            connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            connection.execute("PRAGMA query_only=ON")
        else:
            connection = sqlite3.connect(str(path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection
    route = matrix.route_for(
        unit,
        writer_operation=operation_scope or f"{unit}_read",
        transaction_boundary="one reviewed domain transaction",
    )
    if route.backend is Backend.SQLITE_TRANSITION:
        if not readonly:
            from tools.data_platform.local_authority_fence import (
                assert_sqlite_write_allowed,
            )

            assert_sqlite_write_allowed(path.parent, unit)
        if readonly:
            connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            connection.execute("PRAGMA query_only=ON")
        else:
            connection = sqlite3.connect(str(path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection
    catalog_path = os.environ.get("HONGHU_POSTGRES_RUNTIME_CONFIG")
    registry_path = os.environ.get("HONGHU_CUTOVER_UNIT_REGISTRY")
    if not catalog_path or not registry_path:
        raise DomainDataWriterFenced("PostgreSQL route lacks runtime catalog/registry")
    catalog = load_postgres_runtime_catalog(catalog_path)
    reader = build_catalog_connection_factory(catalog, role="reader")
    registry = CutoverUnitRegistry.from_path(registry_path)
    definition = registry.definition(unit)
    cache_key = (unit, str(catalog_path))
    if unit == "sentiment_analytics":
        projection = _sentiment_projection(str(catalog_path), reader)
        cache = None
    else:
        projection = None
        cache = _READ_CACHES.setdefault(
            cache_key, PostgresDomainReadCache(unit, reader)
        )
    if readonly:
        read_connection = (
            projection.connect_readonly(finalize_readonly=False)
            if projection is not None
            else cache.connect(finalize_readonly=False)
        )
        try:
            for dependency in definition.dependencies:
                dependency_route = matrix.routes[dependency]
                if dependency_route.backend is not Backend.POSTGRESQL_PRODUCTION:
                    raise DomainDataWriterFenced(
                        f"read dependency is not PostgreSQL-authoritative: {dependency}"
                    )
                if dependency == "shared_identity":
                    from tools.data_platform.shared_identity import SharedIdentityReadCache

                    dependency_cache = _SHARED_IDENTITY_CACHES.setdefault(
                        str(catalog_path), SharedIdentityReadCache(reader)
                    )
                elif dependency in {
                    "financial_data",
                    "research_publication",
                    "dynamic_intelligence",
                    "operations_governance",
                    "investment_hypotheses",
                    "opportunity_lens",
                    "sentiment_analytics",
                }:
                    if dependency == "sentiment_analytics":
                        dependency_cache = _sentiment_projection(
                            str(catalog_path), reader
                        )
                    else:
                        dependency_key = (dependency, str(catalog_path))
                        dependency_cache = _READ_CACHES.setdefault(
                            dependency_key, PostgresDomainReadCache(dependency, reader)
                        )
                else:
                    raise DomainDataWriterFenced(
                        f"unsupported PostgreSQL read dependency: {dependency}"
                    )
                dependency_cache.attach(read_connection)
        except Exception:
            read_connection.close()
            raise
        # No caller can observe the compatibility connection before this
        # final fence.  The persistent sentiment main file is additionally
        # opened with mode=ro throughout dependency assembly.
        _finalize_readonly(read_connection)
        return read_connection
    if route.authority_state.value not in {"S3", "S4"}:
        raise DomainDataWriterFenced("formal PostgreSQL writes require S3/S4 authority")
    role_key = f"writer_{unit}"
    writer_identity = route.writer_identity
    writer = _authority_writer_factory(
        catalog,
        role_key=role_key,
        expected_writer_identity=writer_identity,
    )
    trusted_actor = actor or os.environ.get("HONGHU_AUDIT_ACTOR", "")
    if not trusted_actor:
        from tools.data_platform.run_domain_operation import trusted_os_principal

        trusted_actor = trusted_os_principal()
    if projection is not None:
        compatibility = projection.connect_writer(
            writer,
            writer_identity=writer_identity,
            operation_scope=operation_scope or f"{unit}_mutation",
            operation_id=operation_id or os.environ.get("HONGHU_OPERATION_ID", ""),
            actor=trusted_actor,
        )
    else:
        compatibility = PostgresDomainCompatibilityConnection(
            unit,
            reader,
            writer,
            owned_objects=definition.owned_objects,
            writer_identity=writer_identity,
            operation_scope=operation_scope or f"{unit}_mutation",
            operation_id=operation_id or os.environ.get("HONGHU_OPERATION_ID", ""),
            actor=trusted_actor,
        )
    for dependency in definition.dependencies:
        dependency_route = matrix.routes[dependency]
        if dependency_route.backend is not Backend.POSTGRESQL_PRODUCTION:
            raise DomainDataWriterFenced(
                f"write dependency is not PostgreSQL-authoritative: {dependency}"
            )
        if dependency == "shared_identity":
            from tools.data_platform.shared_identity import SharedIdentityReadCache

            shared_cache = _SHARED_IDENTITY_CACHES.setdefault(
                str(catalog_path), SharedIdentityReadCache(reader)
            )
            compatibility.attach_read_dependency(shared_cache)
        elif dependency in {
            "financial_data",
            "research_publication",
            "dynamic_intelligence",
            "operations_governance",
            "investment_hypotheses",
            "opportunity_lens",
            "sentiment_analytics",
        }:
            if dependency == "sentiment_analytics":
                dependency_cache = _sentiment_projection(str(catalog_path), reader)
            else:
                dependency_key = (dependency, str(catalog_path))
                dependency_cache = _READ_CACHES.setdefault(
                    dependency_key, PostgresDomainReadCache(dependency, reader)
                )
            compatibility.attach_read_dependency(dependency_cache)
        else:
            raise DomainDataWriterFenced(
                f"unsupported PostgreSQL write dependency: {dependency}"
            )
    return compatibility
