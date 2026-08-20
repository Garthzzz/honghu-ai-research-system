from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from werkzeug.security import check_password_hash, generate_password_hash


ALLOWED_PERMISSIONS = frozenset(
    {
        "analyst_note:read",
        "analyst_note:write",
        "shared_identity:write",
        "valuation_tracker:read",
        "valuation_tracker:write",
        "valuation_tracker:publish",
        "account_admin:read",
        "account_admin:manage",
    }
)
SUBJECT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
PASSWORD_METHOD = "scrypt:32768:8:1"
LOG = logging.getLogger(__name__)


class ApplicationAccountError(RuntimeError):
    code = "application_account_error"
    http_status = 500


class ApplicationAccountConflict(ApplicationAccountError):
    code = "application_account_conflict"
    http_status = 409


class ApplicationAccountForbidden(ApplicationAccountError):
    code = "application_account_forbidden"
    http_status = 403


class ApplicationAccountAuthenticationFailed(ApplicationAccountError):
    code = "authentication_failed"
    http_status = 401


class ApplicationAccountLocked(ApplicationAccountAuthenticationFailed):
    code = "authentication_failed"


@dataclass(frozen=True)
class AccountPrincipal:
    subject: str
    permissions: frozenset[str]
    account_revision: int
    auth_revision: int
    must_change_password: bool


@dataclass(frozen=True)
class AccountLogin:
    principal: AccountPrincipal
    session_token: str


class ApplicationAccountStore(Protocol):
    def login(self, *, subject: str, password: str, user_agent: str, remote_address: str) -> AccountLogin: ...
    def resolve_session(self, session_token: str) -> AccountPrincipal | None: ...
    def logout(self, session_token: str) -> None: ...


def normalize_subject(value: str) -> str:
    subject = value.strip().lower()
    if not SUBJECT_RE.fullmatch(subject):
        raise ValueError("账号需为 3—64 位小写字母、数字、点、横线或下划线")
    return subject


def validate_permissions(values: Any) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        raise ValueError("权限必须为列表")
    permissions = tuple(sorted({str(item) for item in values}))
    unknown = sorted(set(permissions) - ALLOWED_PERMISSIONS)
    if unknown:
        raise ValueError(f"存在未授权权限：{', '.join(unknown)}")
    if "account_admin:manage" in permissions and "account_admin:read" not in permissions:
        raise ValueError("账号管理写权限必须同时包含只读权限")
    return permissions


def validate_password(subject: str, password: str) -> None:
    if len(password) < 12 or len(password) > 256:
        raise ValueError("密码长度必须为 12—256 位")
    lowered = password.casefold()
    if subject.casefold() in lowered or lowered in {
        "password123",
        "password123!",
        "123456789012",
        "qwertyuiop12",
    }:
        raise ValueError("密码过于常见或包含账号名")
    kinds = sum(
        bool(test(password))
        for test in (
            lambda value: any(ch.islower() for ch in value),
            lambda value: any(ch.isupper() for ch in value),
            lambda value: any(ch.isdigit() for ch in value),
            lambda value: any(not ch.isalnum() for ch in value),
        )
    )
    if kinds < 3:
        raise ValueError("密码至少包含大小写字母、数字、符号中的三类")


def password_hash(subject: str, password: str) -> str:
    validate_password(subject, password)
    return generate_password_hash(password, method=PASSWORD_METHOD)


def _required_text(value: str, label: str, *, maximum: int = 500) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum:
        raise ValueError(f"{label}不能为空且不能超过 {maximum} 字")
    return cleaned


def _mapping(cursor: Any, row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    if hasattr(row, "keys"):
        return dict(row)
    return dict(zip((item[0] for item in cursor.description), row))


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _translate(exc: Exception) -> ApplicationAccountError:
    if isinstance(exc, ApplicationAccountError):
        return exc
    state = getattr(exc, "sqlstate", None)
    LOG.exception("application-account PostgreSQL operation failed")
    if state in {"23505", "40001"}:
        return ApplicationAccountConflict("账号已存在、版本已变化或幂等键冲突，请刷新后重试")
    if state == "42501":
        return ApplicationAccountForbidden("当前操作不允许；请确认超管状态并重新登录")
    return ApplicationAccountError("账号服务暂时不可用")


class PostgresApplicationAccountStore:
    """Application identities only; this role has no OS or PostgreSQL DDL capability."""

    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        legacy_password_verifier: Callable[[str, str], bool],
        idempotency_secret: str,
        authentication_proof_secret: str,
        expected_writer_identity: str = "honghu_writer_application_identity",
    ):
        self._connect = connection_factory
        self._legacy_verify = legacy_password_verifier
        if len(idempotency_secret) < 32:
            raise ValueError("application-account idempotency secret is too short")
        self._idempotency_secret = idempotency_secret.encode("utf-8")
        if len(authentication_proof_secret) < 32:
            raise ValueError("application-account authentication proof is too short")
        self._authentication_proof_secret = authentication_proof_secret
        if not re.fullmatch(r"[a-z_][a-z0-9_]{2,62}", expected_writer_identity):
            raise ValueError("application-account writer identity is invalid")
        self._expected_writer_identity = expected_writer_identity
        # Always spend a real scrypt verification on an unknown subject.
        self._dummy_hash = generate_password_hash(
            secrets.token_urlsafe(32), method=PASSWORD_METHOD
        )
        self._verify_runtime_security_boundary()

    def _verify_runtime_security_boundary(self) -> None:
        """Fail Viewer startup if proof-bearing SQL could enter PostgreSQL logs."""
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """SELECT session_user,current_setting('log_statement'),
                                  current_setting('log_parameter_max_length'),
                                  current_setting('log_parameter_max_length_on_error')"""
                    )
                    row = cursor.fetchone()
        except Exception as exc:
            raise ApplicationAccountError(
                "账号服务安全边界无法验证"
            ) from exc
        if row is None or tuple(str(value) for value in row) != (
            self._expected_writer_identity,
            "none",
            "0",
            "0",
        ):
            raise ApplicationAccountError(
                "账号服务数据库角色或参数日志策略不符合生产安全边界"
            )

    @staticmethod
    def _principal(row: dict[str, Any]) -> AccountPrincipal:
        return AccountPrincipal(
            subject=str(row["subject"]),
            permissions=frozenset(str(item) for item in (row.get("permissions") or [])),
            account_revision=int(row["revision"]),
            auth_revision=int(row["auth_revision"]),
            must_change_password=bool(row.get("must_change_password")),
        )

    def login(self, *, subject: str, password: str, user_agent: str, remote_address: str) -> AccountLogin:
        normalized = subject.strip().lower()
        session_token = secrets.token_urlsafe(48)
        session_hash = _sha(session_token)
        principal: AccountPrincipal | None = None
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT * FROM application_identity.login_verifier_v1(%s)",
                        (normalized,),
                    )
                    raw = cursor.fetchone()
                    row = _mapping(cursor, raw) if raw is not None else None
                    verified = False
                    if row is None:
                        check_password_hash(self._dummy_hash, password)
                    elif row["credential_backend"] == "windows_keyring":
                        verified = bool(self._legacy_verify(normalized, password))
                    elif row["credential_backend"] == "postgresql_hash":
                        encoded = str(row.get("password_hash") or "")
                        verified = bool(encoded and check_password_hash(encoded, password))
                    expires_at = datetime.now(timezone.utc) + timedelta(hours=8)
                    cursor.execute(
                        """SELECT * FROM application_identity.complete_login_v1(
                               %s,%s,%s,%s,%s,%s,%s,%s
                           )""",
                        (
                            normalized,
                            verified,
                            int(row["auth_revision"]) if row is not None else None,
                            self._authentication_proof_secret,
                            session_hash,
                            expires_at,
                            _sha(user_agent or "") if user_agent else None,
                            _sha(remote_address or "") if remote_address else None,
                        ),
                    )
                    result = cursor.fetchone()
                    if verified and result is not None:
                        principal = self._principal(_mapping(cursor, result))
        except Exception as exc:
            error = _translate(exc)
            if isinstance(error, ApplicationAccountAuthenticationFailed):
                raise error
            # Login never reveals whether the subject, status or lock caused failure.
            if getattr(exc, "sqlstate", None) in {"28000", "42501"}:
                raise ApplicationAccountAuthenticationFailed("账号或密码错误") from exc
            raise error from exc
        if principal is None:
            raise ApplicationAccountAuthenticationFailed("账号或密码错误")
        return AccountLogin(principal=principal, session_token=session_token)

    def resolve_session(self, session_token: str) -> AccountPrincipal | None:
        if not session_token:
            return None
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT * FROM application_identity.resolve_session_v1(%s)",
                        (_sha(session_token),),
                    )
                    row = cursor.fetchone()
                    return self._principal(_mapping(cursor, row)) if row else None
        except Exception as exc:
            raise _translate(exc) from exc

    def logout(self, session_token: str) -> None:
        if not session_token:
            return
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT application_identity.logout_v1(%s)",
                        (_sha(session_token),),
                    )
        except Exception as exc:
            raise _translate(exc) from exc

    def list_accounts(self, session_token: str) -> list[dict[str, Any]]:
        return self._call_rows("list_accounts_v1", (_sha(session_token),))

    def create_account(
        self,
        session_token: str,
        *,
        subject: str,
        display_name: str,
        password: str,
        permissions: Any,
        superadmin: bool,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        subject = normalize_subject(subject)
        allowed = validate_permissions(permissions)
        if bool(superadmin) != ("account_admin:manage" in allowed):
            raise ValueError("应用超管角色必须与账号管理权限一致")
        encoded = password_hash(subject, password)
        fingerprint = self._password_fingerprint(subject, password)
        display_name = _required_text(display_name, "显示名称", maximum=100)
        reason = _required_text(reason, "变更原因")
        return self._call_one(
            "create_account_v1",
            (
                _sha(session_token), subject, display_name, encoded, fingerprint,
                list(allowed), bool(superadmin), reason, idempotency_key,
            ),
        )

    def update_account(
        self,
        session_token: str,
        subject: str,
        *,
        display_name: str,
        permissions: Any,
        superadmin: bool,
        active: bool,
        expected_revision: int,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        allowed = validate_permissions(permissions)
        if bool(superadmin) != ("account_admin:manage" in allowed):
            raise ValueError("应用超管角色必须与账号管理权限一致")
        display_name = _required_text(display_name, "显示名称", maximum=100)
        reason = _required_text(reason, "变更原因")
        if int(expected_revision) < 1:
            raise ValueError("账号版本无效")
        return self._call_one(
            "update_account_v1",
            (
                _sha(session_token), normalize_subject(subject), display_name,
                list(allowed), bool(superadmin), bool(active), int(expected_revision),
                reason, idempotency_key,
            ),
        )

    def reset_password(
        self,
        session_token: str,
        subject: str,
        *,
        password: str,
        expected_revision: int,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        subject = normalize_subject(subject)
        encoded = password_hash(subject, password)
        fingerprint = self._password_fingerprint(subject, password)
        reason = _required_text(reason, "变更原因")
        if int(expected_revision) < 1:
            raise ValueError("账号版本无效")
        return self._call_one(
            "reset_password_v1",
            (
                _sha(session_token), subject, encoded, fingerprint, int(expected_revision),
                reason, idempotency_key,
            ),
        )

    def _password_fingerprint(self, subject: str, password: str) -> str:
        return hmac.new(
            self._idempotency_secret,
            ("v1\0" + subject + "\0" + password).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def delete_account(
        self,
        session_token: str,
        subject: str,
        *,
        expected_revision: int,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        reason = _required_text(reason, "变更原因")
        if int(expected_revision) < 1:
            raise ValueError("账号版本无效")
        return self._call_one(
            "delete_account_v1",
            (
                _sha(session_token), normalize_subject(subject), int(expected_revision),
                reason, idempotency_key,
            ),
        )

    def _call_one(self, function: str, params: tuple[Any, ...]) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    marks = ",".join("%s" for _ in params)
                    cursor.execute(
                        f"SELECT * FROM application_identity.{function}({marks})", params
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise ApplicationAccountError("账号操作未返回结果")
                    mapped = _mapping(cursor, row)
                    if len(mapped) == 1:
                        value = next(iter(mapped.values()))
                        if isinstance(value, dict):
                            return value
                    return mapped
        except Exception as exc:
            raise _translate(exc) from exc

    def _call_rows(self, function: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    marks = ",".join("%s" for _ in params)
                    cursor.execute(
                        f"SELECT * FROM application_identity.{function}({marks})", params
                    )
                    return [_mapping(cursor, row) for row in cursor.fetchall()]
        except Exception as exc:
            raise _translate(exc) from exc
