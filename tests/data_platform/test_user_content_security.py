from __future__ import annotations

from flask import Flask, jsonify, request

from tools.viewer.user_content_security import (
    UserContentSecurityError,
    UserContentSecuritySettings,
    authenticate,
    configure_user_content_security,
    ensure_csrf_token,
    require_principal,
)


def _app(*, enabled: bool = True, require_https: bool = False) -> Flask:
    app = Flask(__name__)
    settings = UserContentSecuritySettings(
        enabled=enabled,
        require_https=require_https,
        credential_service="test",
        session_secret_service="test-session",
        session_secret_account="session",
        principals={"analyst": frozenset({"analyst_note:read", "analyst_note:write"})},
    )
    configure_user_content_security(
        app,
        settings,
        password_verifier=lambda subject, password: subject == "analyst" and password == "secret",
        session_secret="x" * 64,
    )

    @app.get("/session")
    def session_info():
        try:
            return jsonify({"ok": True, "csrf": ensure_csrf_token(app)})
        except UserContentSecurityError as exc:
            return jsonify({"ok": False, "code": exc.code}), exc.http_status

    @app.post("/login")
    def login():
        data = request.get_json()
        try:
            principal = authenticate(
                app,
                request,
                subject=data["subject"],
                password=data["password"],
                csrf_token=request.headers.get("X-CSRF-Token", ""),
            )
            return jsonify({"ok": True, "subject": principal.subject, "csrf": ensure_csrf_token(app)})
        except UserContentSecurityError as exc:
            return jsonify({"ok": False, "code": exc.code}), exc.http_status

    @app.post("/write")
    def write():
        try:
            principal = require_principal(
                app, request, permission="analyst_note:write", csrf=True
            )
            return jsonify({"ok": True, "actor": principal.subject})
        except UserContentSecurityError as exc:
            return jsonify({"ok": False, "code": exc.code}), exc.http_status

    return app


def test_authenticated_principal_and_csrf() -> None:
    client = _app().test_client()
    csrf = client.get("/session").get_json()["csrf"]
    response = client.post(
        "/login",
        json={"subject": "analyst", "password": "secret", "actor": "forged"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    login_payload = response.get_json()
    write = client.post("/write", headers={"X-CSRF-Token": login_payload["csrf"]})
    assert write.get_json() == {"ok": True, "actor": "analyst"}


def test_missing_csrf_and_bad_password_fail_closed() -> None:
    client = _app().test_client()
    csrf = client.get("/session").get_json()["csrf"]
    denied = client.post(
        "/login",
        json={"subject": "analyst", "password": "wrong"},
        headers={"X-CSRF-Token": csrf},
    )
    assert denied.status_code == 401
    assert denied.get_json()["code"] == "authentication_failed"
    assert client.post("/write").status_code == 401


def test_disabled_security_and_http_transport_fail_closed() -> None:
    disabled = _app(enabled=False).test_client()
    assert disabled.get("/session").status_code == 503
    https_only = _app(require_https=True).test_client()
    assert https_only.get("/session").status_code == 200
    csrf = https_only.get("/session").get_json()["csrf"]
    response = https_only.post(
        "/login",
        json={"subject": "analyst", "password": "secret"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 403
    assert response.get_json()["code"] == "https_required"
