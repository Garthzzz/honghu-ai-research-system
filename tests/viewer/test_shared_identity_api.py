from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from tools.data_platform.local_authority_fence import LocalAuthorityFenceError
from tools.data_platform.routing import AuthorityState, Backend, CutoverRoute
from tools.viewer import app as viewer
from tools.viewer.user_content_security import (
    UserContentSecuritySettings,
    configure_user_content_security,
)


class _Repository:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create_researcher(self, **payload):
        self.calls.append(payload)
        return {
            "researcher_id": 991,
            "stable_key": "researcher:name:rehearsal",
            "created": True,
        }


@pytest.fixture()
def shared_identity_client(monkeypatch):
    route = CutoverRoute(
        cutover_unit="shared_identity",
        backend=Backend.POSTGRESQL_PRODUCTION,
        writer_operation="shared_identity_mutation",
        transaction_boundary="one shared identity mutation",
        authority_state=AuthorityState.S3,
        sqlite_writer_enabled=False,
        production_postgresql_enabled=True,
        writer_identity="shared-writer",
        cutover_epoch="shared-epoch",
        approval_reference="approval:shared",
    )
    repository = _Repository()
    monkeypatch.setattr(viewer, "SHARED_IDENTITY_ROUTE", route)
    monkeypatch.setattr(viewer, "SHARED_IDENTITY_REPOSITORY", repository)
    old_config = dict(viewer.app.config)
    old_secret = viewer.app.secret_key
    configure_user_content_security(
        viewer.app,
        UserContentSecuritySettings(
            enabled=True,
            require_https=False,
            credential_service="test",
            session_secret_service="test-session",
            session_secret_account="session",
            principals={
                "operator-1": frozenset(
                    {"analyst_note:read", "shared_identity:write"}
                )
            },
        ),
        password_verifier=lambda subject, password: (
            subject == "operator-1" and password == "secret"
        ),
        session_secret="s" * 64,
    )
    viewer.app.config["HONGHU_READ_ONLY_CANDIDATE"] = False
    viewer.app.testing = True
    try:
        yield viewer.app.test_client(), repository
    finally:
        viewer.app.config.clear()
        viewer.app.config.update(old_config)
        viewer.app.secret_key = old_secret


def _login(client):
    session_payload = client.get("/api/user-content/session").get_json()
    response = client.post(
        "/api/user-content/login",
        json={"subject": "operator-1", "password": "secret"},
        headers={"X-CSRF-Token": session_payload["csrf_token"]},
    )
    assert response.status_code == 200
    return response.get_json()["csrf_token"]


def test_researcher_create_uses_trusted_actor_and_stable_operation_identity(
    shared_identity_client,
) -> None:
    client, repository = shared_identity_client
    unauthenticated = client.post(
        "/api/researcher",
        json={"name": "Researcher"},
        headers={"X-Idempotency-Key": "create-researcher-1"},
    )
    assert unauthenticated.status_code == 401
    csrf = _login(client)
    created = client.post(
        "/api/researcher",
        json={
            "name": "Researcher",
            "display_name": "研究员",
            "focus_industries": [1, 2],
            "actor": "forged-client-actor",
        },
        headers={
            "X-CSRF-Token": csrf,
            "X-Idempotency-Key": "create-researcher-1",
        },
    )
    assert created.status_code == 200
    assert created.get_json()["researcher_id"] == 991
    assert repository.calls == [
        {
            "name": "Researcher",
            "display_name": "研究员",
            "focus_summary": None,
            "focus_industries": [1, 2],
            "bio": None,
            "idempotency_key": "create-researcher-1",
            "actor": "operator-1",
        }
    ]


def test_hypothesis_inline_identity_creation_is_fenced_after_shared_cutover(
    shared_identity_client,
) -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE researcher(id integer primary key,name text unique)")
    connection.execute("INSERT INTO researcher VALUES(3,'Existing')")
    assert viewer._resolve_or_create_researcher(connection, 3, None) == (3, None)
    researcher_id, error = viewer._resolve_or_create_researcher(
        connection, "__other__", "New Researcher"
    )
    assert researcher_id is None
    assert "独立研究员创建接口" in error
    assert connection.execute("SELECT count(*) FROM researcher").fetchone()[0] == 1


def test_sqlite_researcher_create_fails_closed_on_live_authority_marker(
    monkeypatch, tmp_path
) -> None:
    route = CutoverRoute(
        cutover_unit="shared_identity",
        backend=Backend.SQLITE_TRANSITION,
        writer_operation="shared_identity_mutation",
        transaction_boundary="one shared identity mutation",
        authority_state=AuthorityState.S0,
        sqlite_writer_enabled=True,
        production_postgresql_enabled=False,
    )
    db_path = tmp_path / "research.db"
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE industry(id integer primary key)")
    connection.execute("CREATE TABLE researcher(id integer primary key,name text unique)")
    connection.commit()
    connection.close()
    monkeypatch.setattr(viewer, "SHARED_IDENTITY_ROUTE", route)
    monkeypatch.setattr(viewer, "get_db", lambda: sqlite3.connect(db_path))
    monkeypatch.setattr(
        viewer,
        "assert_sqlite_write_allowed",
        lambda *_a, **_k: (_ for _ in ()).throw(
            LocalAuthorityFenceError("shared_identity SQLite writer is retired")
        ),
    )
    old_testing = viewer.app.testing
    viewer.app.testing = True
    try:
        response = viewer.app.test_client().post(
            "/api/researcher", json={"name": "Blocked Researcher"}
        )
    finally:
        viewer.app.testing = old_testing

    assert response.status_code == 503
    assert response.get_json()["code"] == "writer_fenced"
    with sqlite3.connect(db_path) as check:
        assert check.execute("SELECT count(*) FROM researcher").fetchone()[0] == 0


def test_research_base_becomes_read_only_when_all_owning_units_are_postgresql(
    monkeypatch, tmp_path
) -> None:
    database = tmp_path / "research.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE legacy_probe(id integer primary key)")
        connection.execute("INSERT INTO legacy_probe VALUES(1)")
    routes = {
        unit: SimpleNamespace(backend=Backend.POSTGRESQL_PRODUCTION)
        for unit in (
            "research_publication",
            "dynamic_intelligence",
            "operations_governance",
            "investment_hypotheses",
        )
    }
    monkeypatch.setattr(viewer, "AUTHORITY_MATRIX", SimpleNamespace(routes=routes))
    monkeypatch.setattr(viewer, "DB_PATH", database)
    monkeypatch.setattr(viewer, "DOMAIN_READ_CACHES", {})
    monkeypatch.setattr(viewer, "SHARED_IDENTITY_READ_CACHE", None)
    viewer.app.config["HONGHU_READ_ONLY_CANDIDATE"] = False
    connection = viewer.get_db()
    try:
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM legacy_probe").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("INSERT INTO legacy_probe VALUES(2)")
    finally:
        connection.close()


def test_postgresql_sentiment_uses_persistent_projection_without_opening_legacy_db(
    monkeypatch, tmp_path
) -> None:
    sentiment = tmp_path / "sentiment.db"
    research = tmp_path / "research.db"
    with sqlite3.connect(sentiment) as connection:
        connection.execute("CREATE TABLE senti_probe(id integer primary key)")
    with sqlite3.connect(research) as connection:
        connection.execute("CREATE TABLE company(id integer primary key,name text,ticker text)")
        connection.execute("INSERT INTO company VALUES(1,'stale','OLD.SH')")

    monkeypatch.setattr(viewer, "SENTI_DB_PATH", sentiment)
    monkeypatch.setattr(viewer, "DB_PATH", research)
    calls = []

    def connect_projection(unit, path, *, readonly):
        calls.append((unit, type(sentiment)(path), readonly))
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute("CREATE TABLE company(id integer,name text,ticker text)")
        connection.execute("INSERT INTO company VALUES(1,'current','NEW.SH')")
        connection.execute("PRAGMA query_only=ON")
        return connection

    monkeypatch.setattr(viewer, "connect_domain_database", connect_projection)
    monkeypatch.setattr(
        viewer,
        "AUTHORITY_MATRIX",
        SimpleNamespace(
            routes={
                "sentiment_analytics": SimpleNamespace(
                    backend=Backend.POSTGRESQL_PRODUCTION
                )
            }
        ),
    )
    viewer.app.config["HONGHU_READ_ONLY_CANDIDATE"] = False
    connection = viewer.senti_conn()
    assert connection is not None
    try:
        assert tuple(connection.execute("SELECT name,ticker FROM company").fetchone()) == (
            "current",
            "NEW.SH",
        )
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        assert calls == [("sentiment_analytics", sentiment, True)]
    finally:
        connection.close()
