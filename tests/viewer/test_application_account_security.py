from __future__ import annotations

from flask import Flask, jsonify, request

from tools.data_platform.application_accounts import AccountLogin, AccountPrincipal
from tools.viewer.user_content_security import (
    UserContentSecurityError,
    UserContentSecuritySettings,
    account_session_token,
    authenticate,
    clear_principal,
    configure_user_content_security,
    current_principal,
    ensure_csrf_token,
    require_principal,
)


class Store:
    def __init__(self):
        self.active = True
        self.revision = 3
        self.tokens: set[str] = set()

    def login(self, *, subject, password, user_agent, remote_address):
        assert user_agent and remote_address
        if subject != "admin" or password != "Strong-Research-2026!":
            from tools.data_platform.application_accounts import ApplicationAccountAuthenticationFailed
            raise ApplicationAccountAuthenticationFailed("denied")
        token = "opaque-session-token"
        self.tokens.add(token)
        return AccountLogin(self.principal(), token)

    def principal(self):
        return AccountPrincipal(
            "admin", frozenset({"account_admin:read", "account_admin:manage"}),
            self.revision, self.revision, False,
        )

    def resolve_session(self, token):
        return self.principal() if self.active and token in self.tokens else None

    def logout(self, token):
        self.tokens.discard(token)


def _app():
    app = Flask(__name__); store = Store()
    settings = UserContentSecuritySettings(
        True, False, "legacy", "session", "flask", {"legacy": frozenset({"analyst_note:read"})},
        "account-idem", "password-fingerprint", 1,
        "account-auth", "login-proof", 1,
    )
    configure_user_content_security(app, settings, session_secret="s" * 64, account_store=store)

    @app.get("/session")
    def info():
        principal = current_principal(app, request)
        return jsonify(csrf=ensure_csrf_token(app), subject=principal.subject if principal else None)

    @app.post("/login")
    def login():
        data = request.get_json()
        principal = authenticate(app, request, subject=data["subject"], password=data["password"], csrf_token=request.headers.get("X-CSRF-Token", ""))
        return jsonify(subject=principal.subject, csrf=ensure_csrf_token(app))

    @app.post("/manage")
    def manage():
        principal = require_principal(app, request, permission="account_admin:manage", csrf=True)
        return jsonify(subject=principal.subject, token_present=bool(account_session_token()))

    @app.post("/logout")
    def logout():
        require_principal(app, request, permission="account_admin:read", csrf=True)
        clear_principal(app); return jsonify(ok=True)

    @app.errorhandler(UserContentSecurityError)
    def error(exc):
        return jsonify(code=exc.code), exc.http_status
    return app, store


def test_server_session_is_checked_every_request_and_logout_revokes() -> None:
    app, store = _app(); client = app.test_client()
    csrf = client.get("/session").get_json()["csrf"]
    login = client.post("/login", json={"subject":"admin","password":"Strong-Research-2026!"}, headers={"X-CSRF-Token":csrf,"Origin":"http://localhost"})
    assert login.status_code == 200
    csrf = login.get_json()["csrf"]
    assert client.post("/manage", headers={"X-CSRF-Token":csrf}).get_json()["token_present"] is True
    store.active = False
    assert client.post("/manage", headers={"X-CSRF-Token":csrf}).status_code == 401


def test_cross_origin_login_and_mutation_are_rejected() -> None:
    app, _ = _app(); client = app.test_client()
    csrf = client.get("/session").get_json()["csrf"]
    denied = client.post("/login", json={"subject":"admin","password":"Strong-Research-2026!"}, headers={"X-CSRF-Token":csrf,"Origin":"https://evil.example"})
    assert denied.status_code == 403
    assert denied.get_json()["code"] == "origin_invalid"
