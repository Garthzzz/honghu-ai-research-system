from __future__ import annotations

import sqlite3
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .constants import DB_PATH, SCHEMA_VERSION


_POSTGRES_READ_CACHE = None


def _postgres_route():
    from tools.data_platform.routing import (
        Backend,
        load_cutover_route,
        load_environment_authority_matrix,
    )

    root = Path(__file__).resolve().parents[2]
    matrix = load_environment_authority_matrix()
    route = (
        matrix.route_for(
            "financial_data",
            writer_operation="financial_data_mutation",
            transaction_boundary="one financial-domain mutation",
        )
        if matrix is not None
        else load_cutover_route(
            root / "config/migration/financial_data_backend_route.json",
            runtime_override=os.environ.get("HONGHU_FINANCIAL_DATA_ROUTE_CONFIG"),
        )
    )
    return route, Backend


def _postgres_read_cache():
    global _POSTGRES_READ_CACHE
    if _POSTGRES_READ_CACHE is None:
        from tools.data_platform.financial_data import FinancialDataReadCache
        from tools.data_platform.postgres_runtime import (
            build_catalog_connection_factory,
            build_postgres_connection_factory,
            load_postgres_runtime_catalog,
            load_postgres_runtime_settings,
        )

        catalog_path = os.environ.get("HONGHU_POSTGRES_RUNTIME_CONFIG")
        runtime_path = os.environ.get("HONGHU_FINANCIAL_DATA_POSTGRES_CONFIG")
        if catalog_path:
            factory = build_catalog_connection_factory(
                load_postgres_runtime_catalog(catalog_path), role="reader"
            )
        elif runtime_path:
            factory = build_postgres_connection_factory(
                load_postgres_runtime_settings(runtime_path), role="reader"
            )
        else:
            raise RuntimeError("PostgreSQL financial-data route requires runtime config")
        _POSTGRES_READ_CACHE = FinancialDataReadCache(
            factory
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


def connect(
    db_path: str | Path = DB_PATH,
    *,
    readonly: bool = False,
    operation_scope: str | None = None,
    operation_id: str | None = None,
    actor: str | None = None,
) -> sqlite3.Connection:
    route, Backend = _postgres_route()
    if route.backend is Backend.POSTGRESQL_PRODUCTION:
        if readonly:
            if (
                os.environ.get("HONGHU_POSTGRES_RUNTIME_CONFIG")
                and os.environ.get("HONGHU_CUTOVER_UNIT_REGISTRY")
            ):
                from tools.data_platform.domain_data import connect_domain_database

                return connect_domain_database(
                    "financial_data", db_path, readonly=True
                )
            return _postgres_read_cache().connect()
        # Legacy per-unit S3 routes predate the common authority matrix and do
        # not carry the reviewed registry/role boundary required by the generic
        # writer adapter.  They must remain fenced; never reinterpret their
        # missing common runtime as permission to reopen SQLite.
        if not (
            os.environ.get("HONGHU_POSTGRES_RUNTIME_CONFIG")
            and os.environ.get("HONGHU_CUTOVER_UNIT_REGISTRY")
        ):
            from tools.data_platform.financial_data import FinancialDataWriterFenced

            raise FinancialDataWriterFenced(
                "legacy financial PostgreSQL route has no common authority matrix"
            )
        from tools.data_platform.domain_data import connect_domain_database

        return connect_domain_database(
            "financial_data",
            db_path,
            readonly=False,
            operation_scope=operation_scope or "financial_data_mutation",
            operation_id=operation_id,
            actor=actor,
        )
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
