from __future__ import annotations

import sqlite3

import pytest

from tools.data_platform.routing import AuthorityState, Backend, CutoverRoute
from tools.viewer import app as viewer
from tools.viewer.user_content_security import (
    UserContentSecuritySettings,
    configure_user_content_security,
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    database = tmp_path / "research.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """CREATE TABLE analyst_note(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   entity_type TEXT NOT NULL,
                   entity_id INTEGER NOT NULL,
                   q_number TEXT,
                   note_type TEXT NOT NULL DEFAULT 'general',
                   title TEXT,
                   content TEXT NOT NULL,
                   author TEXT NOT NULL,
                   created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                   updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
               )"""
        )
    monkeypatch.setattr(viewer, "DB_PATH", database)
    monkeypatch.setattr(
        viewer,
        "USER_CONTENT_ROUTE",
        CutoverRoute(
            cutover_unit="user_content_notes",
            backend=Backend.SQLITE_TRANSITION,
            writer_operation="analyst_note_mutation",
            transaction_boundary="one note mutation",
            authority_state=AuthorityState.S0,
            sqlite_writer_enabled=True,
        ),
    )
    monkeypatch.setattr(viewer, "USER_CONTENT_POSTGRES_READ_FACTORY", None)
    monkeypatch.setattr(viewer, "USER_CONTENT_POSTGRES_WRITE_FACTORY", None)
    monkeypatch.setattr(viewer, "USER_CONTENT_IDENTITY_RESOLVER", None)
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
                "analyst-1": frozenset(
                    {"analyst_note:read", "analyst_note:write"}
                )
            },
        ),
        password_verifier=lambda subject, password: (
            subject == "analyst-1" and password == "secret"
        ),
        session_secret="s" * 64,
    )
    viewer.app.config["HONGHU_READ_ONLY_CANDIDATE"] = False
    viewer.app.testing = True
    try:
        yield viewer.app.test_client(), database
    finally:
        viewer.app.config.clear()
        viewer.app.config.update(old_config)
        viewer.app.secret_key = old_secret


def _login(client):
    session_payload = client.get("/api/user-content/session").get_json()
    response = client.post(
        "/api/user-content/login",
        json={"subject": "analyst-1", "password": "secret"},
        headers={"X-CSRF-Token": session_payload["csrf_token"]},
    )
    assert response.status_code == 200
    return response.get_json()["csrf_token"]


def test_api_requires_authentication_csrf_and_idempotency(client) -> None:
    http, _ = client
    unauthenticated = http.get("/api/analyst_note/company/7")
    assert unauthenticated.status_code == 401

    csrf = _login(http)
    missing_csrf = http.post(
        "/api/analyst_note",
        json={"entity_type": "company", "entity_id": 7, "content": "note"},
        headers={"X-Idempotency-Key": "operation-1"},
    )
    assert missing_csrf.status_code == 403
    missing_idempotency = http.post(
        "/api/analyst_note",
        json={"entity_type": "company", "entity_id": 7, "content": "note"},
        headers={"X-CSRF-Token": csrf},
    )
    assert missing_idempotency.status_code == 400


def test_api_uses_trusted_principal_and_preserves_s0_compatibility(client) -> None:
    http, database = client
    csrf = _login(http)
    created = http.post(
        "/api/analyst_note",
        json={
            "entity_type": "company",
            "entity_id": 7,
            "content": "server actor wins",
            "author": "forged-client-actor",
            "expected_revision": 0,
        },
        headers={
            "X-CSRF-Token": csrf,
            "X-Idempotency-Key": "operation-create-1",
        },
    )
    assert created.status_code == 200
    payload = created.get_json()["note"]
    assert payload["author"] == "analyst-1"
    assert payload["revision"] is None

    listed = http.get("/api/analyst_note/company/7")
    assert listed.status_code == 200
    assert listed.get_json()["notes"][0]["content"] == "server actor wins"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT author FROM analyst_note").fetchone()[0] == "analyst-1"

    deletion = http.delete(
        f"/api/analyst_note/key/{payload['note_key']}",
        json={"expected_revision": 1},
        headers={
            "X-CSRF-Token": csrf,
            "X-Idempotency-Key": "operation-delete-1",
        },
    )
    assert deletion.status_code == 409
    assert deletion.get_json()["code"] == "capability_unavailable"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM analyst_note").fetchone()[0] == 1


def test_plaintext_mutations_fail_transport_before_payload_or_lookup(client, monkeypatch) -> None:
    http, _ = client
    configure_user_content_security(
        viewer.app,
        UserContentSecuritySettings(
            enabled=True,
            require_https=True,
            credential_service="test",
            session_secret_service="test-session",
            session_secret_account="session",
            principals={
                "analyst-1": frozenset(
                    {"analyst_note:read", "analyst_note:write"}
                )
            },
        ),
        password_verifier=lambda subject, password: (
            subject == "analyst-1" and password == "secret"
        ),
        session_secret="s" * 64,
    )

    malformed_create = http.post(
        "/api/analyst_note",
        json={},
        base_url="http://localhost",
    )
    assert malformed_create.status_code == 403
    assert malformed_create.get_json()["code"] == "https_required"

    repository_called = False

    def unexpected_repository():
        nonlocal repository_called
        repository_called = True
        raise AssertionError("plaintext delete reached repository resolution")

    monkeypatch.setattr(viewer, "analyst_note_repository", unexpected_repository)
    malformed_delete = http.delete(
        "/api/analyst_note/1",
        json={},
        base_url="http://localhost",
    )
    assert malformed_delete.status_code == 403
    assert malformed_delete.get_json()["code"] == "https_required"
    assert repository_called is False


def test_https_mutation_still_applies_business_validation_after_security(client) -> None:
    http, _ = client
    configure_user_content_security(
        viewer.app,
        UserContentSecuritySettings(
            enabled=True,
            require_https=True,
            credential_service="test",
            session_secret_service="test-session",
            session_secret_account="session",
            principals={
                "analyst-1": frozenset(
                    {"analyst_note:read", "analyst_note:write"}
                )
            },
        ),
        password_verifier=lambda subject, password: (
            subject == "analyst-1" and password == "secret"
        ),
        session_secret="s" * 64,
    )
    session_payload = http.get(
        "/api/user-content/session", base_url="https://localhost"
    ).get_json()
    login = http.post(
        "/api/user-content/login",
        json={"subject": "analyst-1", "password": "secret"},
        headers={"X-CSRF-Token": session_payload["csrf_token"]},
        base_url="https://localhost",
    )
    assert login.status_code == 200
    malformed = http.post(
        "/api/analyst_note",
        json={},
        headers={"X-CSRF-Token": login.get_json()["csrf_token"]},
        base_url="https://localhost",
    )
    assert malformed.status_code == 400
    assert malformed.get_json()["error"] == "entity_type 非法或 content 为空"
