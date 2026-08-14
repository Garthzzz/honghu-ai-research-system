from __future__ import annotations

import sqlite3

import pytest

from tools.data_platform.financial_data import FinancialDataError, FinancialDataReadCache


class _Connection:
    def __init__(self, authority, identity_rows, financial_rows) -> None:
        self.authority = authority
        self.identity_rows = identity_rows
        self.financial_rows = financial_rows
        self.calls = 0

    def execute(self, query, _params=()):
        self.calls += 1
        if "operations.cutover_unit_authority" in query:
            return _Result([self.authority])
        if "shared_identity.legacy_record" in query:
            return _Result(self.identity_rows)
        return _Result(self.financial_rows)

    def close(self):
        return None


class _Result:
    def __init__(self, rows) -> None:
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


def _factory():
    authority = ("S3", "postgresql_production", 3, "epoch", "snap", "a" * 64, True, 8)
    identity = [
        ("financial_security", {"id": 1, "canonical_name": "A", "ticker": "AAPL"}, "1" * 64, 1),
        ("financial_security_company_link", {"research_company_id": 1, "security_id": 1}, "2" * 64, 1),
    ]
    tables = [
        "financial_schema_meta", "financial_source_snapshot", "financial_observation",
        "financial_observation_revision", "financial_model_run", "financial_model_input",
        "financial_model_output", "financial_reconciliation",
    ]
    rows = [(table, {"id": index + 1, "name": table}, f"{index + 3:064x}", 1) for index, table in enumerate(tables)]
    return _Connection(authority, identity, rows)


def test_financial_read_cache_is_built_only_from_postgresql_formal_rows() -> None:
    cache = FinancialDataReadCache(_factory, refresh_check_seconds=60)
    connection = cache.connect()
    try:
        assert connection.execute("SELECT count(*) FROM financial_security").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM financial_observation").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM financial_observation")
    finally:
        connection.close()


def test_financial_read_cache_rejects_non_authoritative_state() -> None:
    bad = _factory()
    bad.authority = ("S1", "sqlite_transition", 2, None, "snap", "a" * 64, False, 8)
    cache = FinancialDataReadCache(lambda: bad)
    with pytest.raises(FinancialDataError, match="not authoritative"):
        cache.connect()
