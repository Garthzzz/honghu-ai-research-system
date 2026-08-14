from __future__ import annotations

import sqlite3
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .constants import DB_PATH, SCHEMA_VERSION


_POSTGRES_READ_CACHE = None


def _postgres_route():
    from tools.data_platform.routing import Backend, load_cutover_route

    root = Path(__file__).resolve().parents[2]
    route = load_cutover_route(
        root / "config/migration/financial_data_backend_route.json",
        runtime_override=os.environ.get("HONGHU_FINANCIAL_DATA_ROUTE_CONFIG"),
    )
    return route, Backend


def _postgres_read_cache():
    global _POSTGRES_READ_CACHE
    if _POSTGRES_READ_CACHE is None:
        from tools.data_platform.financial_data import FinancialDataReadCache
        from tools.data_platform.postgres_runtime import (
            build_postgres_connection_factory,
            load_postgres_runtime_settings,
        )

        runtime_path = os.environ.get("HONGHU_FINANCIAL_DATA_POSTGRES_CONFIG")
        if not runtime_path:
            raise RuntimeError("PostgreSQL financial-data route requires runtime config")
        settings = load_postgres_runtime_settings(runtime_path)
        _POSTGRES_READ_CACHE = FinancialDataReadCache(
            build_postgres_connection_factory(settings, role="reader")
        )
    return _POSTGRES_READ_CACHE


REQUIRED_TABLES = {
    "financial_schema_meta",
    "financial_security",
    "financial_source_snapshot",
    "financial_observation",
    "financial_model_run",
    "financial_model_input",
    "financial_model_output",
    "financial_reconciliation",
}


def connect(db_path: str | Path = DB_PATH, *, readonly: bool = False) -> sqlite3.Connection:
    route, Backend = _postgres_route()
    if route.backend is Backend.POSTGRESQL_PRODUCTION:
        if not readonly:
            from tools.data_platform.financial_data import FinancialDataWriterFenced

            raise FinancialDataWriterFenced(
                "legacy financial SQLite writer is fenced; use the audited PostgreSQL writer adapter"
            )
        return _postgres_read_cache().connect()
    path = Path(db_path).resolve()
    if readonly:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=10)
        conn.execute("PRAGMA query_only=ON")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def initialize_database(db_path: str | Path = DB_PATH) -> None:
    route, Backend = _postgres_route()
    if route.backend is Backend.POSTGRESQL_PRODUCTION:
        raise RuntimeError("cannot initialize SQLite after financial_data PostgreSQL cutover")
    path = Path(db_path)
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    conn = connect(path)
    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()


def verify_database(db_path: str | Path = DB_PATH) -> dict[str, object]:
    path = Path(db_path).resolve()
    conn = connect(path, readonly=True)
    try:
        available = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        missing = sorted(REQUIRED_TABLES - available)
        version_row = conn.execute(
            "SELECT value FROM financial_schema_meta WHERE key='schema_version'"
        ).fetchone() if "financial_schema_meta" in available else None
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        fk_issues = [tuple(row) for row in conn.execute("PRAGMA foreign_key_check")]
        result = {
            "schema_version": str(version_row[0]) if version_row else None,
            "missing_tables": missing,
            "integrity_check": integrity,
            "foreign_key_issues": len(fk_issues),
            "table_count": len(available),
        }
        if missing or integrity != "ok" or fk_issues or result["schema_version"] != SCHEMA_VERSION:
            raise RuntimeError(f"financial DB 校验失败: {result}")
        return result
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
