from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from tools.data_platform.shared_identity import (
    SharedIdentityError,
    SharedIdentityReadCache,
    company_security_stable_key,
)


class _Cursor:
    def __init__(self, *, one: Any = None, rows: list[tuple[Any, ...]] | None = None):
        self.one = one
        self.rows = rows or []

    def fetchone(self) -> Any:
        return self.one

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


class _Postgres:
    def __init__(self, *, state: str = "S3", backend: str = "postgresql_production"):
        self.state = state
        self.backend = backend
        self.closed = False

    def execute(self, sql: str) -> _Cursor:
        if "cutover_unit_authority" in sql:
            return _Cursor(
                one=(
                    self.state,
                    self.backend,
                    3,
                    "epoch-1",
                    "snapshot-1",
                    "f" * 64,
                    1,
                    2,
                    True,
                )
            )
        assert "shared_identity.legacy_record" in sql
        return _Cursor(
            rows=[
                (
                    "company",
                    {"id": 1, "name": "PostgreSQL公司", "ticker": "PG.SH"},
                    "a" * 64,
                    1,
                    "snapshot-1",
                ),
                (
                    "industry",
                    {"id": 7, "name": "PostgreSQL行业", "tier": 1, "status": "深度跟踪"},
                    "b" * 64,
                    1,
                    "snapshot-1",
                ),
            ]
        )

    def close(self) -> None:
        self.closed = True


def test_postgresql_identity_temp_views_shadow_only_legacy_identity() -> None:
    connections: list[_Postgres] = []

    def factory() -> _Postgres:
        connection = _Postgres()
        connections.append(connection)
        return connection

    cache = SharedIdentityReadCache(factory, refresh_check_seconds=60)
    research = sqlite3.connect("file:shared-identity-test?mode=memory", uri=True)
    research.row_factory = sqlite3.Row
    research.execute("CREATE TABLE company(id integer,name text,ticker text)")
    research.execute("INSERT INTO company VALUES (1,'陈旧SQLite公司','OLD.SH')")
    research.execute("CREATE TABLE source(id integer,company_id integer,title text)")
    research.execute("INSERT INTO source VALUES (9,1,'仍由SQLite权威的数据')")

    cache.attach(research)
    company = dict(research.execute("SELECT id,name,ticker FROM company").fetchone())
    joined = dict(
        research.execute(
            "SELECT c.name,s.title FROM company c JOIN source s ON s.company_id=c.id"
        ).fetchone()
    )
    assert company == {"id": 1, "name": "PostgreSQL公司", "ticker": "PG.SH"}
    assert joined == {
        "name": "PostgreSQL公司",
        "title": "仍由SQLite权威的数据",
    }
    with pytest.raises(sqlite3.OperationalError, match="view"):
        research.execute("UPDATE company SET name='不得写入临时视图' WHERE id=1")
    assert connections[0].closed is True
    cache.close()


@pytest.mark.parametrize(
    ("state", "backend"),
    [("S1", "sqlite_transition"), ("S3", "sqlite_transition")],
)
def test_identity_cache_fails_closed_without_postgresql_authority(
    state: str, backend: str
) -> None:
    cache = SharedIdentityReadCache(lambda: _Postgres(state=state, backend=backend))
    with pytest.raises(SharedIdentityError, match="not authoritative"):
        cache.attach(sqlite3.connect(":memory:"))


@pytest.mark.parametrize(
    ("ticker", "market", "status", "expected"),
    [
        ("688041.SH", "A股", "listed", "company:security:688041.SH:venue:shanghai"),
        ("aapl", "美股", "us", "company:security:AAPL:venue:us"),
        ("0700.HK", "港股", "hk", "company:security:0700.HK:venue:hong-kong"),
    ],
)
def test_company_stable_identity_is_ticker_and_venue_qualified(
    ticker: str, market: str, status: str, expected: str
) -> None:
    assert company_security_stable_key(ticker, market, status) == expected


def test_unqualified_company_identity_fails_closed() -> None:
    with pytest.raises(SharedIdentityError, match="supported venue"):
        company_security_stable_key("UNKNOWN", "其他", "listed")
