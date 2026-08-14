from __future__ import annotations

"""PostgreSQL-authoritative, process-memory compatibility for shared identity.

The compatibility cache is an ephemeral SQLite shared-memory database.  It is
rebuilt only from PostgreSQL and attached through TEMP views, so legacy joins
can continue during the mixed migration window without reading or mutating the
old SQLite identity tables.  PostgreSQL connection/authority failures abort;
there is deliberately no fallback to the SQLite baseline.
"""

import hashlib
import json
import sqlite3
import threading
import time
from collections.abc import Callable
from typing import Any


SHARED_IDENTITY_TABLES = (
    "company",
    "company_identity_alias",
    "company_identity_redirect",
    "company_industry",
    "company_profile",
    "company_sub_market_share",
    "industry",
    "industry_relation",
    "researcher",
    "theme",
    "theme_company",
    "theme_industry",
    "financial_security",
    "financial_security_company_link",
)

DEFAULT_COLUMNS = {
    "company": ("id", "name", "ticker", "market", "listing_status"),
    "company_identity_alias": ("id", "canonical_company_id", "alias", "alias_type", "source"),
    "company_identity_redirect": (
        "old_company_id",
        "canonical_company_id",
        "old_name",
        "canonical_name",
        "ticker",
        "reason",
        "verified_at",
    ),
    "company_industry": ("id", "company_id", "industry_id", "role", "revenue_share", "note"),
    "company_profile": ("id", "company_id", "industry_id", "period"),
    "company_sub_market_share": ("id", "company_id", "industry_id", "sub_market", "geo", "share"),
    "industry": ("id", "name", "parent_id", "level", "tier", "status"),
    "industry_relation": ("id", "upstream_id", "downstream_id", "relation_type"),
    "researcher": ("id", "name", "display_name", "is_active"),
    "theme": ("id", "name", "category", "summary", "status"),
    "theme_company": ("id", "theme_id", "company_id", "impact", "note"),
    "theme_industry": ("id", "theme_id", "industry_id", "impact", "note"),
    "financial_security": ("id", "research_company_id", "canonical_name", "ticker", "market"),
    "financial_security_company_link": ("research_company_id", "security_id", "link_role"),
}


class SharedIdentityError(RuntimeError):
    pass


def _quote(identifier: str) -> str:
    if identifier not in SHARED_IDENTITY_TABLES and not identifier.replace("_", "").isalnum():
        raise SharedIdentityError(f"unsafe identity identifier: {identifier}")
    return '"' + identifier.replace('"', '""') + '"'


def _sqlite_type(values: list[Any]) -> str:
    present = [value for value in values if value is not None]
    if not present:
        return "TEXT"
    if all(isinstance(value, bool | int) for value in present):
        return "INTEGER"
    if all(isinstance(value, bool | int | float) for value in present):
        return "REAL"
    if all(isinstance(value, bytes) for value in present):
        return "BLOB"
    return "TEXT"


def _sqlite_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


class SharedIdentityReadCache:
    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        refresh_check_seconds: float = 1.0,
    ) -> None:
        self._connection_factory = connection_factory
        self._refresh_check_seconds = refresh_check_seconds
        self._lock = threading.RLock()
        self._keeper: sqlite3.Connection | None = None
        self._uri: str | None = None
        self._version: str | None = None
        self._authority_token: str | None = None
        self._next_check = 0.0

    @staticmethod
    def _authority_version(connection: Any) -> tuple[str, tuple[Any, ...]]:
        """Return a small, authority-bound cache token before loading rows."""

        authority = connection.execute(
            """
            SELECT a.state,a.authoritative_backend,a.state_revision,a.cutover_epoch,
                   s.source_snapshot_id,s.target_content_sha256,s.formal_revision,
                   s.current_formal_row_count,s.formal_business_data
              FROM operations.cutover_unit_authority a
              JOIN shared_identity.unit_snapshot s
                ON s.cutover_unit=a.cutover_unit
             WHERE a.cutover_unit='shared_identity'
            """
        ).fetchone()
        if authority is None:
            raise SharedIdentityError("shared_identity authority/snapshot row is missing")
        if str(authority[0]) not in {"S3", "S4"} or str(authority[1]) != "postgresql_production":
            raise SharedIdentityError("shared_identity PostgreSQL read route is not authoritative")
        if not bool(authority[8]):
            raise SharedIdentityError("shared_identity formal dataset is not enabled")
        version = hashlib.sha256(
            json.dumps(
                [str(value) if value is not None else None for value in authority],
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return version, tuple(authority)

    def _read_postgresql(
        self,
    ) -> tuple[str, str | None, dict[str, list[dict[str, Any]]] | None]:
        connection = self._connection_factory()
        try:
            version, authority = self._authority_version(connection)
            if version == self._authority_token and self._uri is not None:
                return version, None, None
            rows = connection.execute(
                """
                SELECT source_table,payload,row_sha256,revision,source_snapshot_id
                  FROM shared_identity.legacy_record
                 WHERE formal_business_data=true
                 ORDER BY source_table,source_ordinal
                """
            ).fetchall()
        finally:
            connection.close()
        grouped = {table: [] for table in SHARED_IDENTITY_TABLES}
        digest = hashlib.sha256()
        digest.update(version.encode("ascii"))
        for table, raw_payload, row_sha, revision, snapshot_id in rows:
            table_name = str(table)
            if table_name not in grouped:
                raise SharedIdentityError(f"unapproved PostgreSQL identity table: {table_name}")
            payload = raw_payload if isinstance(raw_payload, dict) else json.loads(raw_payload)
            if not isinstance(payload, dict):
                raise SharedIdentityError("shared identity payload is not an object")
            grouped[table_name].append(payload)
            digest.update(
                json.dumps(
                    [table_name, str(row_sha), int(revision), str(snapshot_id)],
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            digest.update(b"\n")
        row_version = digest.hexdigest()
        expected_count = int(authority[7])
        if sum(len(table_rows) for table_rows in grouped.values()) != expected_count:
            raise SharedIdentityError("shared_identity formal row count changed during refresh")
        return version, f"{version}_{row_version}", grouped

    def _build(self, version: str, grouped: dict[str, list[dict[str, Any]]]) -> None:
        uri = f"file:honghu_shared_identity_{version}?mode=memory&cache=shared"
        keeper = sqlite3.connect(uri, uri=True, check_same_thread=False)
        try:
            for table in SHARED_IDENTITY_TABLES:
                rows = grouped.get(table) or []
                columns = list(DEFAULT_COLUMNS[table])
                seen: set[str] = set(columns)
                for row in rows:
                    for name in row:
                        if name not in seen:
                            seen.add(name)
                            columns.append(name)
                definitions = []
                for name in columns:
                    values = [row.get(name) for row in rows]
                    definitions.append(f'{_quote(name)} {_sqlite_type(values)}')
                keeper.execute(
                    f"CREATE TABLE {_quote(table)} ({','.join(definitions)})"
                )
                if rows:
                    marks = ",".join("?" for _ in columns)
                    keeper.executemany(
                        f"INSERT INTO {_quote(table)} VALUES ({marks})",
                        [tuple(_sqlite_value(row.get(name)) for name in columns) for row in rows],
                    )
            keeper.commit()
            keeper.execute("PRAGMA query_only=ON")
        except Exception:
            keeper.close()
            raise
        previous = self._keeper
        self._keeper = keeper
        self._uri = uri
        self._version = version
        if previous is not None:
            previous.close()

    def ensure_current(self) -> str:
        now = time.monotonic()
        with self._lock:
            if self._uri is not None and now < self._next_check:
                return self._uri
            authority_token, version, grouped = self._read_postgresql()
            if grouped is not None:
                assert version is not None
                self._build(version, grouped)
                self._authority_token = authority_token
            self._next_check = now + self._refresh_check_seconds
            assert self._uri is not None
            return self._uri

    def attach(self, connection: sqlite3.Connection) -> None:
        uri = self.ensure_current()
        connection.execute("ATTACH DATABASE ? AS pg_shared_identity", (uri,))
        for table in SHARED_IDENTITY_TABLES:
            quoted = _quote(table)
            connection.execute(
                f"CREATE TEMP VIEW {quoted} AS SELECT * FROM pg_shared_identity.{quoted}"
            )

    def close(self) -> None:
        with self._lock:
            if self._keeper is not None:
                self._keeper.close()
            self._keeper = None
            self._uri = None
            self._version = None
            self._authority_token = None
