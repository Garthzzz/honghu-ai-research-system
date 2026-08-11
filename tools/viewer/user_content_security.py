from __future__ import annotations

import hmac
import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from flask import Flask, Request, session
from werkzeug.security import check_password_hash


class UserContentSecurityError(RuntimeError):
    def __init__(self, message: str, *, code: str, http_status: int):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


@dataclass(frozen=True)
class TrustedPrincipal:
    subject: str
    permissions: frozenset[str]


@dataclass(frozen=True)
class UserContentSecuritySettings:
    enabled: bool
    require_https: bool
    credential_service: str
    session_secret_service: str
    session_secret_account: str
    principals: dict[str, frozenset[str]]

    @classmethod
    def from_mapping(cls, payload: dict) -> "UserContentSecuritySettings":
        if payload.get("schema_version") != "honghu.user_content_security.v1":
            raise ValueError("unsupported user-content security schema")
        raw_principals = payload.get("principals") or {}
        if not isinstance(raw_principals, dict):
            raise ValueError("principals must be an object")
        principals = {
            str(subject): frozenset(str(item) for item in permissions)
            for subject, permissions in raw_principals.items()
        }
        return cls(
            enabled=bool(payload.get("enabled")),
            require_https=bool(payload.get("require_https", True)),
            credential_service=str(payload.get("credential_service") or ""),
            session_secret_service=str(payload.get("session_secret_service") or ""),
            session_secret_account=str(payload.get("session_secret_account") or ""),
            principals=principals,
        )

    def validate(self) -> None:
        if not self.enabled:
            return
        if not self.credential_service.strip():
            raise ValueError("credential_service is required")
        if not self.session_secret_service.strip() or not self.session_secret_account.strip():
            raise ValueError("session secret Credential Manager identity is required")
        if not self.principals:
            raise ValueError("at least one trusted principal is required")


PasswordVerifier = Callable[[str, str], bool]


class KeyringPasswordVerifier:
    def __init__(self, service: str):
        self.service = service

    def __call__(self, subject: str, password: str) -> bool:
        import keyring

        encoded_hash = keyring.get_password(self.service, subject)
        if not encoded_hash:
            return False
        return bool(check_password_hash(encoded_hash, password))


def keyring_session_secret(service: str, account: str) -> str | None:
    import keyring

    return keyring.get_password(service, account)


def load_security_settings(path: str | Path | None) -> UserContentSecuritySettings:
    if path is None:
        return UserContentSecuritySettings(
            enabled=False,
            require_https=True,
            credential_service="",
            session_secret_service="",
            session_secret_account="",
            principals={},
        )
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    settings = UserContentSecuritySettings.from_mapping(payload)
    settings.validate()
    return settings


def configure_user_content_security(
    app: Flask,
    settings: UserContentSecuritySettings,
    *,
    password_verifier: PasswordVerifier | None = None,
    session_secret: str | None = None,
) -> None:
    settings.validate()
    app.config["HONGHU_USER_CONTENT_SECURITY_SETTINGS"] = settings
    app.config["HONGHU_USER_CONTENT_PASSWORD_VERIFIER"] = password_verifier
    app.config["HONGHU_USER_CONTENT_SECURITY_READY"] = False
    if not settings.enabled:
        return
    verifier = password_verifier or KeyringPasswordVerifier(settings.credential_service)
    secret = session_secret or keyring_session_secret(
        settings.session_secret_service, settings.session_secret_account
    )
    if not secret or len(secret) < 32:
        return
    app.secret_key = secret
    app.config["HONGHU_USER_CONTENT_PASSWORD_VERIFIER"] = verifier
    app.config["HONGHU_USER_CONTENT_SECURITY_READY"] = True
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
    app.config["SESSION_COOKIE_SECURE"] = bool(settings.require_https)


def security_settings(app: Flask) -> UserContentSecuritySettings:
    return app.config.get("HONGHU_USER_CONTENT_SECURITY_SETTINGS") or load_security_settings(None)


def ensure_csrf_token(app: Flask) -> str:
    if not app.config.get("HONGHU_USER_CONTENT_SECURITY_READY"):
        raise UserContentSecurityError(
            "user-content security is not configured",
            code="security_not_ready",
            http_status=503,
        )
    token = session.get("honghu_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["honghu_csrf_token"] = token
    return str(token)


def _require_transport(request: Request, settings: UserContentSecuritySettings) -> None:
    if settings.require_https and not request.is_secure:
        raise UserContentSecurityError(
            "HTTPS is required for authenticated user-content operations",
            code="https_required",
            http_status=403,
        )


def authenticate(
    app: Flask,
    request: Request,
    *,
    subject: str,
    password: str,
    csrf_token: str,
) -> TrustedPrincipal:
    settings = security_settings(app)
    if not app.config.get("HONGHU_USER_CONTENT_SECURITY_READY"):
        raise UserContentSecurityError(
            "user-content security is not configured",
            code="security_not_ready",
            http_status=503,
        )
    _require_transport(request, settings)
    expected_csrf = ensure_csrf_token(app)
    if not hmac.compare_digest(expected_csrf, csrf_token or ""):
        raise UserContentSecurityError(
            "invalid CSRF token", code="csrf_invalid", http_status=403
        )
    permissions = settings.principals.get(subject)
    verifier = app.config.get("HONGHU_USER_CONTENT_PASSWORD_VERIFIER")
    if not permissions or verifier is None or not verifier(subject, password):
        raise UserContentSecurityError(
            "authentication failed", code="authentication_failed", http_status=401
        )
    session.clear()
    session["honghu_principal"] = subject
    session["honghu_permissions"] = sorted(permissions)
    session["honghu_csrf_token"] = secrets.token_urlsafe(32)
    return TrustedPrincipal(subject=subject, permissions=permissions)


def current_principal(app: Flask, request: Request) -> TrustedPrincipal | None:
    settings = security_settings(app)
    if not app.config.get("HONGHU_USER_CONTENT_SECURITY_READY"):
        return None
    _require_transport(request, settings)
    subject = session.get("honghu_principal")
    permissions = session.get("honghu_permissions")
    if not subject or not isinstance(permissions, list):
        return None
    configured = settings.principals.get(str(subject))
    if configured is None or configured != frozenset(str(item) for item in permissions):
        session.clear()
        return None
    return TrustedPrincipal(subject=str(subject), permissions=configured)


def require_principal(
    app: Flask,
    request: Request,
    *,
    permission: str,
    csrf: bool,
) -> TrustedPrincipal:
    if not app.config.get("HONGHU_USER_CONTENT_SECURITY_READY"):
        raise UserContentSecurityError(
            "user-content security is not configured",
            code="security_not_ready",
            http_status=503,
        )
    principal = current_principal(app, request)
    if principal is None:
        raise UserContentSecurityError(
            "authentication required", code="authentication_required", http_status=401
        )
    if permission not in principal.permissions:
        raise UserContentSecurityError(
            "permission denied", code="permission_denied", http_status=403
        )
    if csrf:
        supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
        expected = ensure_csrf_token(app)
        if not supplied or not hmac.compare_digest(expected, supplied):
            raise UserContentSecurityError(
                "invalid CSRF token", code="csrf_invalid", http_status=403
            )
    return principal


def clear_principal() -> None:
    session.clear()
