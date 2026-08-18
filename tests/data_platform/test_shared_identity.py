from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from tools.data_platform.shared_identity import (
    PostgresSharedIdentityRepository,
    PostgresSharedIdentityResolver,
    SharedIdentityError,
    SharedIdentityReadCache,
    SharedIdentityWriterFenced,
    company_security_stable_key,
    connect_shared_identity_database,
)
from tools.data_platform.routing import AuthorityState, Backend, CutoverRoute


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


def test_identity_cache_attaches_to_readonly_file_connection(tmp_path: Path) -> None:
    database = tmp_path / "readonly-consumer.db"
    writable = sqlite3.connect(database)
    writable.execute("CREATE TABLE source(id integer,title text)")
    writable.execute("INSERT INTO source VALUES(1,'kept')")
    writable.commit()
    writable.close()
    consumer = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    cache = SharedIdentityReadCache(lambda: _Postgres(), refresh_check_seconds=60)
    try:
        cache.attach(consumer)
        assert consumer.execute("SELECT ticker FROM company WHERE id=1").fetchone()[0] == "PG.SH"
        assert consumer.execute("SELECT title FROM source WHERE id=1").fetchone()[0] == "kept"
        with pytest.raises(sqlite3.OperationalError, match="view"):
            consumer.execute("UPDATE company SET name='forbidden' WHERE id=1")
    finally:
        consumer.close()
        cache.close()


def test_independent_identity_caches_do_not_collide_on_same_authority_version(
    tmp_path: Path,
) -> None:
    first = SharedIdentityReadCache(lambda: _Postgres(), refresh_check_seconds=60)
    second = SharedIdentityReadCache(lambda: _Postgres(), refresh_check_seconds=60)
    first_consumer = sqlite3.connect(
        f"file:{(tmp_path / 'first.db').as_posix()}?mode=rwc", uri=True
    )
    second_consumer = sqlite3.connect(
        f"file:{(tmp_path / 'second.db').as_posix()}?mode=rwc", uri=True
    )
    try:
        first.attach(first_consumer)
        second.attach(second_consumer)
        first_row = first_consumer.execute(
            "SELECT id,name,ticker FROM company"
        ).fetchone()
        second_row = second_consumer.execute(
            "SELECT id,name,ticker FROM company"
        ).fetchone()
        assert first_row == second_row
        assert (first_row[0], first_row[2]) == (1, "PG.SH")
    finally:
        first_consumer.close()
        second_consumer.close()
        first.close()
        second.close()


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
        ("PRY.MI", "其他", "上市", "company:security:PRY.MI:venue:milan"),
    ],
)
def test_company_stable_identity_is_ticker_and_venue_qualified(
    ticker: str, market: str, status: str, expected: str
) -> None:
    assert company_security_stable_key(ticker, market, status) == expected


class _ResolverConnection:
    def __init__(self, *, authority=("S3", "postgresql_production"), keys=("stable:1",)):
        self.authority = authority
        self.keys = keys
        self.closed = False

    def execute(self, sql, _params=None):
        if "cutover_unit_authority" in sql:
            return _Cursor(one=self.authority)
        return _Cursor(rows=[(key,) for key in self.keys])

    def close(self):
        self.closed = True


def test_runtime_identity_resolution_uses_current_postgresql_authority() -> None:
    connection = _ResolverConnection(keys=("company:security:AAPL:venue:us",))
    resolver = PostgresSharedIdentityResolver(lambda: connection)
    assert resolver.resolve("company", 17) == "company:security:AAPL:venue:us"
    assert connection.closed is True


@pytest.mark.parametrize(
    "connection",
    [
        _ResolverConnection(authority=("S1", "sqlite_transition")),
        _ResolverConnection(keys=()),
        _ResolverConnection(keys=("stable:1", "stable:2")),
    ],
)
def test_runtime_identity_resolution_never_falls_back_to_frozen_mapping(connection) -> None:
    resolver = PostgresSharedIdentityResolver(lambda: connection)
    with pytest.raises(SharedIdentityError):
        resolver.resolve("company", 17)


def test_unqualified_company_identity_fails_closed() -> None:
    with pytest.raises(SharedIdentityError, match="supported venue"):
        company_security_stable_key("UNKNOWN", "其他", "listed")


class _RepositoryCursor:
    description = (("result",),)

    def __init__(self):
        self.calls = []
        self._result = None

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "shared_identity_authority_v1" in sql:
            self.description = (
                ("state",), ("authoritative_backend",), ("writer_identity",),
                ("approval_reference",), ("cutover_epoch",),
            )
            self._result = (
                "S3", "postgresql_production", "shared-writer", "approval", "epoch"
            )
        else:
            self.description = (("result",),)
            self._result = ({"industry_id": 50, "created": True},)

    def fetchone(self):
        return self._result

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class _RepositoryConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def test_industry_mutation_binds_full_authority_token() -> None:
    route = CutoverRoute(
        cutover_unit="shared_identity",
        backend=Backend.POSTGRESQL_PRODUCTION,
        writer_operation="ensure_industry",
        transaction_boundary="one industry identity mutation",
        authority_state=AuthorityState.S3,
        sqlite_writer_enabled=False,
        production_postgresql_enabled=True,
        writer_identity="shared-writer",
        cutover_epoch="epoch",
        approval_reference="approval",
        route_revision=7,
    )
    cursor = _RepositoryCursor()
    repository = PostgresSharedIdentityRepository(
        lambda: _RepositoryConnection(cursor),
        lambda: _RepositoryConnection(cursor),
        route,
    )
    result = repository.ensure_industry(
        industry={"id": 50, "name": "光纤", "parent_id": 6},
        stable_key="industry:path:通信/光纤",
        idempotency_key="fiber-industry:delta-sha",
        actor="principal:os:test",
    )
    assert result == {"industry_id": 50, "created": True}
    sql, params = cursor.calls[-1]
    assert "ensure_industry_v1" in sql
    assert params[3:8] == (
        "shared-writer", "S3", "epoch", "approval", 7
    )


def test_company_identity_completion_binds_precondition_and_authority_token() -> None:
    route = CutoverRoute(
        cutover_unit="shared_identity",
        backend=Backend.POSTGRESQL_PRODUCTION,
        writer_operation="apply_company_profile_batch",
        transaction_boundary="one audited optical-fiber company profile batch",
        authority_state=AuthorityState.S3,
        sqlite_writer_enabled=False,
        production_postgresql_enabled=True,
        writer_identity="shared-writer",
        cutover_epoch="epoch",
        approval_reference="approval",
        route_revision=7,
    )
    cursor = _RepositoryCursor()
    repository = PostgresSharedIdentityRepository(
        lambda: _RepositoryConnection(cursor),
        lambda: _RepositoryConnection(cursor),
        route,
    )
    repository.complete_company_identity_v2(
        expected_company_id=199,
        previous_name="legacy-name",
        canonical_name="长飞光纤",
        ticker="601869.SH",
        market="上海证券交易所",
        listing_status="a_share",
        verification_source_ref="research.db:source:1127",
        stable_key="company:security:601869.SH:venue:shanghai",
        idempotency_key="fiber-company-identity-complete:delta:199",
        actor="principal:os:test",
    )
    sql, params = cursor.calls[-1]
    assert "complete_company_identity_v2" in sql
    payload = __import__("json").loads(params[0])
    assert payload["previous_name"] == "legacy-name"
    assert payload["ticker"] == "601869.SH"
    assert params[3:8] == (
        "shared-writer", "S3", "epoch", "approval", 7
    )


def test_environment_identity_reader_uses_read_only_sqlite_before_cutover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "research.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE company(id integer primary key,name text)")
    connection.execute("INSERT INTO company VALUES(1,'legacy')")
    connection.commit()
    connection.close()
    monkeypatch.setattr(
        "tools.data_platform.routing.load_environment_authority_matrix", lambda: None
    )
    opened = connect_shared_identity_database(database)
    try:
        assert opened.execute("SELECT name FROM company").fetchone()[0] == "legacy"
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            opened.execute("UPDATE company SET name='forbidden'")
    finally:
        opened.close()


def test_environment_identity_reader_never_falls_back_after_postgresql_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Matrix:
        @staticmethod
        def route_for(*_args, **_kwargs):
            return CutoverRoute(
                cutover_unit="shared_identity",
                authority_state=AuthorityState.S3,
                backend=Backend.POSTGRESQL_PRODUCTION,
                writer_operation="shared_identity_read",
                transaction_boundary="one authoritative identity read transaction",
                sqlite_writer_enabled=False,
                production_postgresql_enabled=True,
                route_revision=3,
                writer_identity="honghu_writer_shared_identity",
                cutover_epoch="epoch",
                approval_reference="approval",
            )

    monkeypatch.setattr(
        "tools.data_platform.routing.load_environment_authority_matrix", lambda: _Matrix()
    )
    monkeypatch.delenv("HONGHU_POSTGRES_RUNTIME_CONFIG", raising=False)
    with pytest.raises(SharedIdentityWriterFenced, match="runtime catalog"):
        connect_shared_identity_database(tmp_path / "must-not-open.db")
    assert not (tmp_path / "must-not-open.db").exists()
