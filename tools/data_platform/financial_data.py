from __future__ import annotations

"""PostgreSQL-authoritative read compatibility for ``financial_data``.

The cache is process-local and disposable.  It is rebuilt exclusively from a
formal PostgreSQL S3/S4 snapshot and the already-authoritative shared security
identity rows.  A PostgreSQL or authority failure aborts the read; the cache
never opens the old ``financial.db`` as a fallback.
"""

import hashlib
import json
import sqlite3
import threading
import time
from collections.abc import Callable
from typing import Any


FINANCIAL_TABLES = (
    "financial_schema_meta",
    "financial_security",
    "financial_security_company_link",
    "financial_source_snapshot",
    "financial_observation",
    "financial_observation_revision",
    "financial_model_run",
    "financial_model_input",
    "financial_model_output",
    "financial_reconciliation",
)


class FinancialDataError(RuntimeError):
    pass


class FinancialDataWriterFenced(FinancialDataError):
    pass


def _quote(identifier: str) -> str:
    if identifier not in FINANCIAL_TABLES and not identifier.replace("_", "").isalnum():
        raise FinancialDataError(f"unsafe financial identifier: {identifier}")
    return '"' + identifier.replace('"', '""') + '"'


def _sqlite_type(values: list[Any]) -> str:
    present = [value for value in values if value is not None]
    if not present:
        return "TEXT"
    if all(isinstance(value, (bool, int)) for value in present):
        return "INTEGER"
    if all(isinstance(value, (bool, int, float)) for value in present):
        return "REAL"
    if all(isinstance(value, bytes) for value in present):
        return "BLOB"
    return "TEXT"


def _sqlite_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


class FinancialDataReadCache:
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
        self._authority_token: str | None = None
        self._next_check = 0.0

    def _read_postgresql(self) -> tuple[str, dict[str, list[dict[str, Any]]] | None]:
        connection = self._connection_factory()
        try:
            authority = connection.execute(
                """
                SELECT a.state,a.authoritative_backend,a.state_revision,a.cutover_epoch,
                       s.source_snapshot_id,s.source_content_sha256,s.formal_business_data,
                       s.source_row_count
                  FROM operations.cutover_unit_authority a
                  JOIN financial_data.unit_snapshot s ON s.cutover_unit=a.cutover_unit
                 WHERE a.cutover_unit='financial_data'
                """
            ).fetchone()
            if authority is None:
                raise FinancialDataError("financial_data authority/snapshot row is missing")
            if str(authority[0]) not in {"S3", "S4"} or str(authority[1]) != "postgresql_production":
                raise FinancialDataError("financial_data PostgreSQL read route is not authoritative")
            if not bool(authority[6]):
                raise FinancialDataError("financial_data formal dataset is not enabled")
            token = hashlib.sha256(
                json.dumps(
                    [str(value) if value is not None else None for value in authority],
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if token == self._authority_token and self._uri is not None:
                return token, None
            rows = connection.execute(
                """
                SELECT source_table,payload,row_sha256,revision
                  FROM financial_data.legacy_record
                 WHERE formal_business_data=true
                 ORDER BY source_table,source_ordinal
                """
            ).fetchall()
            identity_rows = connection.execute(
                """
                SELECT source_table,payload,row_sha256,revision
                  FROM shared_identity.legacy_record
                 WHERE formal_business_data=true
                   AND source_database='financial.db'
                   AND source_table IN ('financial_security','financial_security_company_link')
                 ORDER BY source_table,source_ordinal
                """
            ).fetchall()
        finally:
            connection.close()
        grouped = {table: [] for table in FINANCIAL_TABLES}
        digest = hashlib.sha256(token.encode("ascii"))
        for table, raw_payload, row_sha, revision in [*identity_rows, *rows]:
            table_name = str(table)
            if table_name not in grouped:
                raise FinancialDataError(f"unapproved PostgreSQL financial table: {table_name}")
            payload = raw_payload if isinstance(raw_payload, dict) else json.loads(raw_payload)
            if not isinstance(payload, dict):
                raise FinancialDataError("financial payload is not an object")
            grouped[table_name].append(payload)
            digest.update(
                json.dumps([table_name, str(row_sha), int(revision)], separators=(",", ":")).encode(
                    "utf-8"
                )
            )
            digest.update(b"\n")
        expected = int(authority[7])
        owned_count = sum(
            len(grouped[table])
            for table in FINANCIAL_TABLES
            if table not in {"financial_security", "financial_security_company_link"}
        )
        if owned_count != expected:
            raise FinancialDataError("financial_data formal row count changed during refresh")
        return f"{token}_{digest.hexdigest()}", grouped

    def _build(self, version: str, grouped: dict[str, list[dict[str, Any]]]) -> None:
        uri = f"file:honghu_financial_data_{version}?mode=memory&cache=shared"
        keeper = sqlite3.connect(uri, uri=True, check_same_thread=False)
        try:
            for table in FINANCIAL_TABLES:
                rows = grouped[table]
                columns: list[str] = []
                seen: set[str] = set()
                for row in rows:
                    for name in row:
                        if name not in seen:
                            seen.add(name)
                            columns.append(name)
                if not columns:
                    raise FinancialDataError(f"formal financial table has no schema-bearing rows: {table}")
                definitions = [
                    f"{_quote(name)} {_sqlite_type([row.get(name) for row in rows])}"
                    for name in columns
                ]
                keeper.execute(f"CREATE TABLE {_quote(table)} ({','.join(definitions)})")
                keeper.executemany(
                    f"INSERT INTO {_quote(table)} ({','.join(_quote(name) for name in columns)}) "
                    f"VALUES ({','.join('?' for _ in columns)})",
                    [tuple(_sqlite_value(row.get(name)) for name in columns) for row in rows],
                )
            keeper.commit()
            keeper.execute("PRAGMA query_only=ON")
        except Exception:
            keeper.close()
            raise
        old = self._keeper
        self._keeper = keeper
        self._uri = uri
        self._authority_token = version
        if old is not None:
            old.close()

    def connect(self) -> sqlite3.Connection:
        now = time.monotonic()
        with self._lock:
            if self._uri is None or now >= self._next_check:
                version, grouped = self._read_postgresql()
                if grouped is not None:
                    self._build(version, grouped)
                self._next_check = now + self._refresh_check_seconds
            if self._uri is None:
                raise FinancialDataError("financial PostgreSQL compatibility cache is unavailable")
            connection = sqlite3.connect(self._uri, uri=True)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            return connection
