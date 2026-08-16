from __future__ import annotations

"""Persistent disposable SQLite projection for PostgreSQL sentiment authority.

The multi-process sentiment runners still execute their reviewed SQLite-shaped
queries, but the old live ``sentiment.db`` is never opened after S3.  A new
cache is built from the formal PostgreSQL record stream, then refreshed from
the small authoritative overlay.  One cross-process lock serializes projection
writes.  Formal mutations are committed to PostgreSQL first and the cache is
committed only after an idempotent authoritative response.
"""

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from tools.data_platform.domain_data import (
    DomainDataError,
    DomainDataWriterFenced,
    _identifier,
    _json_value,
    _sha256_json,
    _sqlite_type,
    _sqlite_value,
)


class SentimentProjectionError(DomainDataError):
    pass


class _InterprocessLock:
    def __init__(self, path: Path, *, timeout_seconds: float = 30.0) -> None:
        self.path = path
        self.timeout_seconds = timeout_seconds
        self._handle: Any = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.path.open("xb") as created:
                created.write(b"0")
                created.flush()
        except FileExistsError:
            pass
        handle = self.path.open("r+b")
        if self.path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._handle = handle
                return
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    handle.close()
                    raise SentimentProjectionError(
                        "timed out waiting for the unique sentiment projection writer"
                    )
                time.sleep(0.1)

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._handle = None


def _schema_contract(watermark: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in watermark.get("tables") or ():
        table = str(item.get("source_table") or "")
        database = str(item.get("source_database") or "")
        schema = dict(item.get("schema") or {})
        columns = [dict(value) for value in schema.get("columns") or ()]
        primary = sorted(
            (value for value in columns if int(value.get("pk") or 0) > 0),
            key=lambda value: int(value["pk"]),
        )
        if (
            not table
            or database != "sentiment.db"
            or not columns
            or not primary
            or table in result
        ):
            raise DomainDataWriterFenced(
                f"invalid persistent sentiment schema contract: {database}.{table}"
            )
        result[table] = {
            "database": database,
            "columns": columns,
            "primary": primary,
            "indexes": [dict(value) for value in schema.get("indexes") or ()],
        }
        _identifier(table)
    if not result:
        raise DomainDataWriterFenced("persistent sentiment schema contract is empty")
    return result


def _authority(reader: Callable[[], Any]) -> dict[str, Any]:
    connection = reader()
    try:
        row = connection.execute(
            """SELECT state,authoritative_backend,writer_identity,cutover_epoch,
                      state_revision,source_snapshot_id,source_identity_sha256,
                      source_content_sha256,source_row_count,source_watermark,
                      formal_revision,overlay_count,overlay_revision_sum,
                      overlay_last_update
                 FROM domain_data.unit_runtime_contract_v1('sentiment_analytics')"""
        ).fetchone()
    finally:
        connection.close()
    if row is None or str(row[0]) not in {"S3", "S4"} or str(row[1]) != (
        "postgresql_production"
    ):
        raise DomainDataWriterFenced("sentiment PostgreSQL authority is absent")
    watermark = row[9] if isinstance(row[9], dict) else json.loads(row[9])
    formal = {
        "state": str(row[0]),
        "backend": str(row[1]),
        "writer_identity": str(row[2]),
        "cutover_epoch": str(row[3]),
        "state_revision": int(row[4]),
        "source_snapshot_id": str(row[5]),
        "source_identity_sha256": str(row[6]),
        "source_content_sha256": str(row[7]),
        "source_row_count": int(row[8]),
        "formal_revision": int(row[10]),
    }
    overlay = {
        "count": int(row[11]),
        "revision_sum": int(row[12]),
        "last_update": str(row[13]),
    }
    return {
        "formal": formal,
        "formal_token": _sha256_json(formal),
        "overlay": overlay,
        "overlay_token": _sha256_json(overlay),
        "watermark": watermark,
        "schemas": _schema_contract(watermark),
    }


def _create_projection_schema(
    connection: sqlite3.Connection, schemas: dict[str, dict[str, Any]]
) -> None:
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA foreign_keys=OFF")
    for table, schema in schemas.items():
        columns = schema["columns"]
        definitions = [
            f"{_identifier(str(column['name']))} {_sqlite_type(column.get('type'))}"
            + (
                " PRIMARY KEY"
                if len(schema["primary"]) == 1 and int(column.get("pk") or 0) > 0
                else ""
            )
            for column in sorted(columns, key=lambda value: int(value.get("cid") or 0))
        ]
        if len(schema["primary"]) > 1:
            definitions.append(
                "PRIMARY KEY ("
                + ",".join(_identifier(str(value["name"])) for value in schema["primary"])
                + ")"
            )
        connection.execute(
            f"CREATE TABLE {_identifier(table)} ({','.join(definitions)})"
        )
        for ordinal, index in enumerate(schema["indexes"]):
            names = [str(value) for value in index.get("columns") or () if value]
            if not names or set(names) <= {
                str(value["name"]) for value in schema["primary"]
            }:
                continue
            unique = "UNIQUE " if bool(index.get("unique")) else ""
            index_name = f"__honghu_{table}_{ordinal:03d}"
            connection.execute(
                f"CREATE {unique}INDEX {_identifier(index_name)} ON "
                f"{_identifier(table)} ({','.join(_identifier(value) for value in names)})"
            )
    connection.executescript(
        """
        CREATE TABLE __honghu_projection_meta(
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            formal_token TEXT NOT NULL,
            overlay_token TEXT NOT NULL,
            formal_json TEXT NOT NULL,
            active_row_count INTEGER NOT NULL,
            built_at TEXT NOT NULL
        );
        CREATE TABLE __honghu_record_state(
            source_database TEXT NOT NULL,
            source_table TEXT NOT NULL,
            source_key TEXT NOT NULL,
            revision INTEGER NOT NULL,
            deleted INTEGER NOT NULL,
            row_sha256 TEXT NOT NULL,
            is_base INTEGER NOT NULL,
            PRIMARY KEY(source_database,source_table,source_key)
        ) WITHOUT ROWID;
        """
    )


def _ordered_names(schema: dict[str, Any]) -> list[str]:
    return [
        str(value["name"])
        for value in sorted(schema["columns"], key=lambda item: int(item.get("cid") or 0))
    ]


def _pk_payload(schema: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return {str(value["name"]): payload.get(str(value["name"])) for value in schema["primary"]}


def _apply_payload(
    connection: sqlite3.Connection,
    table: str,
    schema: dict[str, Any],
    payload: dict[str, Any],
    *,
    deleted: bool,
) -> None:
    primary = _pk_payload(schema, payload)
    if deleted:
        connection.execute(
            f"DELETE FROM {_identifier(table)} WHERE "
            + " AND ".join(f"{_identifier(name)}=?" for name in primary),
            tuple(_sqlite_value(value) for value in primary.values()),
        )
        return
    names = _ordered_names(schema)
    updates = [name for name in names if name not in primary]
    conflict = ",".join(_identifier(name) for name in primary)
    if updates:
        tail = " DO UPDATE SET " + ",".join(
            f"{_identifier(name)}=excluded.{_identifier(name)}" for name in updates
        )
    else:
        tail = " DO NOTHING"
    connection.execute(
        f"INSERT INTO {_identifier(table)} ({','.join(_identifier(name) for name in names)}) "
        f"VALUES ({','.join('?' for _ in names)}) ON CONFLICT({conflict}){tail}",
        tuple(_sqlite_value(payload.get(name)) for name in names),
    )


class PersistentSentimentProjection:
    def __init__(self, root: Path, reader: Callable[[], Any]) -> None:
        self.root = root.resolve()
        self.reader = reader
        self.database_path = self.root / "sentiment_analytics.pg_projection.db"
        self.lock_path = self.root / "sentiment_analytics.pg_projection.lock"

    def _read_meta(self) -> dict[str, Any] | None:
        if not self.database_path.is_file():
            return None
        connection = sqlite3.connect(
            f"file:{self.database_path.as_posix()}?mode=ro", uri=True, timeout=10
        )
        try:
            row = connection.execute(
                "SELECT formal_token,overlay_token,formal_json,active_row_count "
                "FROM __honghu_projection_meta WHERE singleton=1"
            ).fetchone()
            if row is None:
                raise SentimentProjectionError("persistent sentiment projection is invalid")
            return {
                "formal_token": str(row[0]),
                "overlay_token": str(row[1]),
                "formal": json.loads(row[2]),
                "active_row_count": int(row[3]),
            }
        finally:
            connection.close()

    def _rebuild(self, authority: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / f".sentiment_projection.{uuid.uuid4().hex}.db"
        connection = sqlite3.connect(temporary, timeout=30)
        source = self.reader()
        active = 0
        try:
            _create_projection_schema(connection, authority["schemas"])
            cursor = source.execute(
                "SELECT * FROM domain_data.read_unit_records_v1(%s)",
                ("sentiment_analytics",),
            )
            for database, table, ordinal, key, row_sha, raw, revision, deleted in cursor:
                table = str(table)
                schema = authority["schemas"].get(table)
                if schema is None or str(database) != schema["database"]:
                    raise SentimentProjectionError(
                        "PostgreSQL sentiment row is outside the reviewed schema"
                    )
                payload = raw if isinstance(raw, dict) else json.loads(raw)
                _apply_payload(connection, table, schema, payload, deleted=bool(deleted))
                if not bool(deleted):
                    active += 1
                connection.execute(
                    "INSERT INTO __honghu_record_state VALUES(?,?,?,?,?,?,?)",
                    (
                        str(database),table,str(key),int(revision),int(bool(deleted)),
                        str(row_sha),int(int(ordinal) > 0),
                    ),
                )
            connection.execute(
                "INSERT INTO __honghu_projection_meta VALUES(1,?,?,?,?,?)",
                (
                    authority["formal_token"],
                    authority["overlay_token"],
                    json.dumps(authority["formal"], sort_keys=True),
                    active,
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                ),
            )
            connection.commit()
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise SentimentProjectionError("rebuilt sentiment projection failed integrity")
        except Exception:
            connection.close()
            source.close()
            temporary.unlink(missing_ok=True)
            raise
        connection.close()
        source.close()
        os.replace(temporary, self.database_path)

    def _sync_overlay(self, authority: dict[str, Any]) -> None:
        connection = sqlite3.connect(self.database_path, timeout=30)
        source = self.reader()
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = source.execute(
                "SELECT * FROM domain_data.read_unit_overlay_v1(%s)",
                ("sentiment_analytics",),
            )
            for database, table, key, raw, _row_sha, revision, deleted in rows:
                table = str(table)
                schema = authority["schemas"].get(table)
                if schema is None or str(database) != schema["database"]:
                    raise SentimentProjectionError(
                        "PostgreSQL sentiment overlay is outside the reviewed schema"
                    )
                payload = raw if isinstance(raw, dict) else json.loads(raw)
                _apply_payload(connection, table, schema, payload, deleted=bool(deleted))
                connection.execute(
                    "INSERT INTO __honghu_record_state VALUES(?,?,?,?,?,?,?) "
                    "ON CONFLICT(source_database,source_table,source_key) DO UPDATE SET "
                    "revision=excluded.revision,deleted=excluded.deleted,"
                    "row_sha256=excluded.row_sha256,is_base=excluded.is_base",
                    (
                        str(database),table,str(key),int(revision),int(bool(deleted)),
                        str(_row_sha),0,
                    ),
                )
            active = sum(
                int(connection.execute(f"SELECT count(*) FROM {_identifier(table)}").fetchone()[0])
                for table in authority["schemas"]
            )
            connection.execute(
                "UPDATE __honghu_projection_meta SET overlay_token=?,active_row_count=? "
                "WHERE singleton=1",
                (authority["overlay_token"], active),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            source.close()
            connection.close()

    def ensure_current_locked(self) -> dict[str, Any]:
        authority = _authority(self.reader)
        meta = self._read_meta()
        if meta is None or meta["formal_token"] != authority["formal_token"]:
            self._rebuild(authority)
        elif meta["overlay_token"] != authority["overlay_token"]:
            self._sync_overlay(authority)
        return authority

    def connect_readonly(
        self, *, finalize_readonly: bool = True
    ) -> sqlite3.Connection:
        lock = _InterprocessLock(self.lock_path)
        lock.acquire()
        try:
            self.ensure_current_locked()
        finally:
            lock.release()
        connection = sqlite3.connect(
            f"file:{self.database_path.as_posix()}?mode=ro", uri=True, timeout=30
        )
        connection.row_factory = sqlite3.Row
        if finalize_readonly:
            connection.execute("PRAGMA query_only=ON")
        return connection

    def attach(self, connection: sqlite3.Connection) -> None:
        """Attach the PG-derived projection as a read-only dependency.

        The authoritative refresh is serialized before attachment.  The URI is
        explicitly read-only, and no path to the retired live sentiment.db is
        accepted by this adapter.
        """

        lock = _InterprocessLock(self.lock_path)
        lock.acquire()
        try:
            authority = self.ensure_current_locked()
        finally:
            lock.release()
        alias = "pg_sentiment_analytics"
        uri = f"file:{self.database_path.as_posix()}?mode=ro"
        connection.execute(f"ATTACH DATABASE ? AS {_identifier(alias)}", (uri,))
        for table in authority["schemas"]:
            quoted = _identifier(table)
            connection.execute(
                f"CREATE TEMP VIEW {quoted} AS SELECT * FROM {_identifier(alias)}.{quoted}"
            )

    def connect_writer(
        self,
        writer: Callable[[], Any],
        *,
        writer_identity: str,
        operation_scope: str,
        operation_id: str,
        actor: str,
    ) -> "PersistentSentimentConnection":
        lock = _InterprocessLock(self.lock_path)
        lock.acquire()
        try:
            authority = self.ensure_current_locked()
            if authority["formal"]["writer_identity"] != writer_identity:
                raise DomainDataWriterFenced(
                    "sentiment projection writer does not own PostgreSQL authority"
                )
            connection = sqlite3.connect(self.database_path, timeout=30)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            return PersistentSentimentConnection(
                connection,
                lock,
                writer,
                authority["schemas"],
                writer_identity=writer_identity,
                operation_scope=operation_scope,
                operation_id=operation_id,
                actor=actor,
            )
        except Exception:
            lock.release()
            raise


class PersistentSentimentConnection:
    unit = "sentiment_analytics"

    def __init__(
        self,
        connection: sqlite3.Connection,
        lock: _InterprocessLock,
        writer: Callable[[], Any],
        schemas: dict[str, dict[str, Any]],
        *,
        writer_identity: str,
        operation_scope: str,
        operation_id: str,
        actor: str,
    ) -> None:
        if not operation_scope or not operation_id or not actor:
            connection.close()
            lock.release()
            raise DomainDataWriterFenced(
                "persistent sentiment writes require stable operation identity and actor"
            )
        self._connection = connection
        self._lock = lock
        self._writer = writer
        self._schemas = schemas
        self._writer_identity = writer_identity
        self._operation_scope = operation_scope
        self._operation_id = operation_id
        self._actor = actor
        self._transaction_index = 0
        self._pending: tuple[str, str, list[dict[str, Any]]] | None = None
        self._closed = False
        self._install_change_tracking()

    @property
    def row_factory(self) -> Any:
        return self._connection.row_factory

    @row_factory.setter
    def row_factory(self, value: Any) -> None:
        self._connection.row_factory = value

    def _row_key(self, names_json: str, *values: Any) -> str:
        names = json.loads(names_json)
        return _sha256_json(
            [[str(name), _json_value(value)] for name, value in zip(names, values)]
        )

    @staticmethod
    def _pk_json(names_json: str, *values: Any) -> str:
        names = json.loads(names_json)
        return json.dumps(
            {str(name): _json_value(value) for name, value in zip(names, values)},
            ensure_ascii=False,
            sort_keys=True,
        )

    @staticmethod
    def _payload_json(names_json: str, *values: Any) -> str:
        names = json.loads(names_json)
        return json.dumps(
            {str(name): _json_value(value) for name, value in zip(names, values)},
            ensure_ascii=False,
            sort_keys=True,
        )

    def _install_change_tracking(self) -> None:
        self._connection.create_function("honghu_row_key", -1, self._row_key)
        self._connection.create_function("honghu_pk_json", -1, self._pk_json)
        self._connection.create_function("honghu_payload_json", -1, self._payload_json)
        self._connection.execute(
            """CREATE TEMP TABLE __honghu_changes(
                source_database TEXT NOT NULL,source_table TEXT NOT NULL,
                source_key TEXT NOT NULL,pk_json TEXT NOT NULL,
                action TEXT NOT NULL,expected_revision INTEGER NOT NULL,
                previous_payload_json TEXT,
                PRIMARY KEY(source_database,source_table,source_key)
            ) WITHOUT ROWID"""
        )
        for ordinal, (table, schema) in enumerate(sorted(self._schemas.items())):
            primary = [str(value["name"]) for value in schema["primary"]]
            names_json = json.dumps(primary, separators=(",", ":"))
            new_values = ",".join(f"NEW.{_identifier(name)}" for name in primary)
            old_values = ",".join(f"OLD.{_identifier(name)}" for name in primary)
            new_key = f"honghu_row_key('{names_json}',{new_values})"
            old_key = f"honghu_row_key('{names_json}',{old_values})"
            new_pk = f"honghu_pk_json('{names_json}',{new_values})"
            old_pk = f"honghu_pk_json('{names_json}',{old_values})"
            all_names = _ordered_names(schema)
            all_names_json = json.dumps(all_names, separators=(",", ":"))
            old_all_values = ",".join(
                f"OLD.{_identifier(name)}" for name in all_names
            )
            old_payload = (
                f"honghu_payload_json('{all_names_json}',{old_all_values})"
            )
            revision = (
                "coalesce((SELECT revision FROM __honghu_record_state "
                f"WHERE source_database='{schema['database']}' AND source_table='{table}' "
                f"AND source_key={new_key}),0)"
            )
            upsert = (
                " ON CONFLICT(source_database,source_table,source_key) DO UPDATE SET "
                "pk_json=excluded.pk_json,action=excluded.action,"
                "previous_payload_json=coalesce(__honghu_changes.previous_payload_json,"
                "excluded.previous_payload_json)"
            )
            self._connection.executescript(
                f"""
                CREATE TEMP TRIGGER __honghu_i_{ordinal} AFTER INSERT ON main.{_identifier(table)}
                BEGIN
                  INSERT INTO __honghu_changes VALUES(
                    '{schema['database']}','{table}',{new_key},{new_pk},'upsert',{revision},NULL
                  ){upsert};
                END;
                CREATE TEMP TRIGGER __honghu_u_guard_{ordinal} BEFORE UPDATE ON main.{_identifier(table)}
                WHEN {old_key}<>{new_key}
                BEGIN SELECT RAISE(ABORT,'primary-key mutation is not supported by the transition adapter'); END;
                CREATE TEMP TRIGGER __honghu_u_{ordinal} AFTER UPDATE ON main.{_identifier(table)}
                BEGIN
                  INSERT INTO __honghu_changes VALUES(
                    '{schema['database']}','{table}',{new_key},{new_pk},'upsert',
                    coalesce((SELECT revision FROM __honghu_record_state
                      WHERE source_database='{schema['database']}' AND source_table='{table}'
                        AND source_key={new_key}),1),{old_payload}
                  ){upsert};
                END;
                CREATE TEMP TRIGGER __honghu_d_{ordinal} BEFORE DELETE ON main.{_identifier(table)}
                BEGIN
                  INSERT INTO __honghu_changes VALUES(
                    '{schema['database']}','{table}',{old_key},{old_pk},'delete',
                    coalesce((SELECT revision FROM __honghu_record_state
                      WHERE source_database='{schema['database']}' AND source_table='{table}'
                        AND source_key={old_key}),1),{old_payload}
                  ){upsert};
                END;
                """
            )

    def _mutations(self) -> list[dict[str, Any]]:
        mutations: list[dict[str, Any]] = []
        rows = self._connection.execute(
            "SELECT source_database,source_table,source_key,pk_json,action,"
            "expected_revision,previous_payload_json "
            "FROM __honghu_changes ORDER BY source_database,source_table,source_key"
        ).fetchall()
        for database, table, key, raw_pk, action, expected, previous_payload in rows:
            schema = self._schemas[str(table)]
            primary = json.loads(raw_pk)
            current = self._connection.execute(
                f"SELECT * FROM {_identifier(str(table))} WHERE "
                + " AND ".join(f"{_identifier(name)}=?" for name in primary),
                tuple(_sqlite_value(value) for value in primary.values()),
            ).fetchone()
            deleted = str(action) == "delete" or current is None
            if deleted:
                payload = (
                    json.loads(previous_payload)
                    if previous_payload is not None
                    else dict(primary)
                )
                # PostgreSQL keeps a complete replacement payload for audit.
                prior = self._connection.execute(
                    "SELECT revision,deleted,row_sha256 FROM __honghu_record_state WHERE "
                    "source_database=? AND source_table=? AND source_key=?",
                    (database, table, key),
                ).fetchone()
                if prior is None and int(expected) < 1:
                    # A row inserted and then removed in the same local
                    # transaction has no authoritative before/after delta.
                    # A standalone DELETE of an absent row fires no trigger,
                    # so this branch is an audited no-op rather than a missing
                    # target being silently accepted.
                    continue
            else:
                names = _ordered_names(schema)
                payload = {name: _json_value(current[name]) for name in names}
                prior = self._connection.execute(
                    "SELECT revision,deleted,row_sha256 FROM __honghu_record_state WHERE "
                    "source_database=? AND source_table=? AND source_key=?",
                    (database, table, key),
                ).fetchone()
            row_sha = _sha256_json(payload)
            if (
                prior is not None
                and bool(prior[1]) == deleted
                and str(prior[2]) == row_sha
            ):
                continue
            mutation = {
                "source_database": str(database),
                "source_table": str(table),
                "source_key": str(key),
                "payload": payload,
                "row_sha256": row_sha,
                "expected_revision": int(expected),
                "delete": deleted,
            }
            mutation["request_sha256"] = _sha256_json(mutation)
            mutations.append(mutation)
        return mutations

    def commit(self) -> None:
        mutations = self._mutations()
        if not mutations:
            if self._pending is not None:
                raise SentimentProjectionError("unresolved PostgreSQL sentiment mutation")
            self._connection.execute("DELETE FROM __honghu_changes")
            self._connection.commit()
            return
        request_hash = _sha256_json(mutations)
        if self._pending is None:
            self._transaction_index += 1
            self._pending = (
                f"{self._operation_id}:{self._transaction_index:08d}",
                request_hash,
                mutations,
            )
        elif self._pending[1] != request_hash or self._pending[2] != mutations:
            raise SentimentProjectionError(
                "unresolved PostgreSQL sentiment mutation changed locally"
            )
        batch_key = self._pending[0]
        try:
            with self._writer() as connection:
                row = connection.execute(
                    "SELECT domain_data.apply_mutation_batch_v1(%s,%s,%s,%s,%s::jsonb,%s,%s)",
                    (
                        "sentiment_analytics",
                        self._operation_scope,
                        batch_key,
                        request_hash,
                        json.dumps(mutations, ensure_ascii=False, sort_keys=True),
                        self._writer_identity,
                        self._actor,
                    ),
                ).fetchone()
                if row is None:
                    raise SentimentProjectionError("PostgreSQL sentiment mutation returned no result")
        except Exception as exc:
            raise SentimentProjectionError(
                "PostgreSQL sentiment mutation result is uncertain; exact retry is required"
            ) from exc
        for mutation in mutations:
            self._connection.execute(
                "INSERT INTO __honghu_record_state VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(source_database,source_table,source_key) DO UPDATE SET "
                "revision=excluded.revision,deleted=excluded.deleted,"
                "row_sha256=excluded.row_sha256,is_base=excluded.is_base",
                (
                    mutation["source_database"],
                    mutation["source_table"],
                    mutation["source_key"],
                    int(mutation["expected_revision"]) + 1,
                    int(bool(mutation["delete"])),
                    mutation["row_sha256"],
                    0,
                ),
            )
        self._connection.execute("DELETE FROM __honghu_changes")
        self._connection.commit()
        self._pending = None

    def rollback(self) -> None:
        if self._pending is not None:
            raise SentimentProjectionError(
                "unresolved PostgreSQL sentiment mutation cannot be locally rolled back"
            )
        self._connection.rollback()

    def attach_read_dependency(self, cache: Any) -> None:
        cache.attach(self._connection)

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._connection.close()
        finally:
            self._lock.release()
            self._closed = True

    def __enter__(self) -> "PersistentSentimentConnection":
        return self

    def __exit__(self, exc_type: Any, _exc: Any, _traceback: Any) -> bool:
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()
        return False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)
