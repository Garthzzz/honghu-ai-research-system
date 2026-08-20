from __future__ import annotations

import argparse
import json
import os
import secrets
import tempfile
from pathlib import Path

from tools.data_platform.postgres_runtime import credential_manager_password


ROLE_KEY = "writer_application_identity"
ROLE_NAME = "honghu_writer_application_identity"
SERVICE = "honghu.postgresql.writer_application_identity.v1"


def provision(runtime_path: Path, security_config_path: Path) -> None:
    runtime = json.loads(runtime_path.read_text(encoding="utf-8-sig"))
    if runtime.get("schema_version") != "honghu.postgresql_production_runtime.v1" or runtime.get("environment_id") != "production":
        raise RuntimeError("production runtime catalog is required")
    admin = runtime.get("break_glass") or {}
    admin_password = credential_manager_password(
        str(admin.get("credential_service") or ""),
        str(admin.get("credential_account") or ""),
    )
    if not admin_password:
        raise RuntimeError("break-glass credential is unavailable")
    import psycopg
    from psycopg import sql
    import keyring

    security = json.loads(security_config_path.read_text(encoding="utf-8-sig"))
    idempotency_service = str(security.get("password_idempotency_secret_service") or "")
    idempotency_account = str(security.get("password_idempotency_secret_account") or "")
    proof_service = str(security.get("authentication_proof_secret_service") or "")
    proof_account = str(security.get("authentication_proof_secret_account") or "")
    session_service = str(security.get("session_secret_service") or "")
    session_account = str(security.get("session_secret_account") or "")
    if (
        security.get("password_idempotency_secret_version") != 1
        or not idempotency_service
        or not idempotency_account
        or security.get("authentication_proof_secret_version") != 1
        or not proof_service
        or not proof_account
        or not session_service
        or not session_account
    ):
        raise RuntimeError("dedicated password-idempotency secret identity v1 is required")
    if len(
        {
            (session_service.strip(), session_account.strip()),
            (idempotency_service.strip(), idempotency_account.strip()),
            (proof_service.strip(), proof_account.strip()),
        }
    ) != 3:
        raise RuntimeError(
            "session, password-idempotency, and authentication-proof secret identities must be distinct"
        )

    password = keyring.get_password(SERVICE, ROLE_NAME)

    with psycopg.connect(
        host=runtime["host"], port=int(runtime["port"]), dbname=runtime["dbname"],
        user=str(admin.get("user") or ""), password=admin_password,
        sslmode=runtime["sslmode"], sslrootcert=runtime["sslrootcert"],
        connect_timeout=int(runtime.get("connect_timeout_seconds", 5)),
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET log_statement='none'")
            cursor.execute("SET log_parameter_max_length='0'")
            cursor.execute("SET log_parameter_max_length_on_error='0'")
            cursor.execute(
                """SELECT current_setting('log_statement'),
                          current_setting('log_parameter_max_length'),
                          current_setting('log_parameter_max_length_on_error')"""
            )
            admin_log_settings = tuple(str(value) for value in cursor.fetchone())
            if admin_log_settings != ("none", "0", "0"):
                raise RuntimeError(
                    "break-glass connection does not suppress statement and parameter logging"
                )
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (ROLE_NAME,))
            role_exists = cursor.fetchone() is not None
            if role_exists and not password:
                raise RuntimeError(
                    "existing application-identity role has no matching VM credential; explicit recovery is required"
                )
            if not role_exists:
                if not password:
                    password = secrets.token_urlsafe(48)
                    keyring.set_password(SERVICE, ROLE_NAME, password)
                    if keyring.get_password(SERVICE, ROLE_NAME) != password:
                        raise RuntimeError(
                            "application-identity writer credential could not be persisted"
                        )
                cursor.execute(
                    """CREATE ROLE honghu_writer_application_identity LOGIN
                         NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
                         NOBYPASSRLS NOINHERIT"""
                )
                cursor.execute(
                    sql.SQL("ALTER ROLE honghu_writer_application_identity PASSWORD {}").format(
                        sql.Literal(password)
                    )
                )
            cursor.execute(
                """ALTER ROLE honghu_writer_application_identity
                     LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
                     NOBYPASSRLS NOINHERIT"""
            )
            # The authentication proof is intentionally never recorded in
            # PostgreSQL logs.  These role-local settings are verified below
            # and again by the production/rehearsal gates.
            cursor.execute(
                "ALTER ROLE honghu_writer_application_identity SET log_statement = 'none'"
            )
            cursor.execute(
                "ALTER ROLE honghu_writer_application_identity SET log_parameter_max_length = '0'"
            )
            cursor.execute(
                "ALTER ROLE honghu_writer_application_identity SET log_parameter_max_length_on_error = '0'"
            )
            cursor.execute(
                """SELECT r.rolsuper,r.rolcreatedb,r.rolcreaterole,r.rolreplication,
                          r.rolbypassrls,r.rolinherit,
                          (SELECT count(*) FROM pg_auth_members m WHERE m.member=r.oid),
                          has_database_privilege(r.rolname,current_database(),'CREATE')
                     FROM pg_roles r WHERE r.rolname=%s""",
                (ROLE_NAME,),
            )
            attributes = cursor.fetchone()
            if attributes is None or any(bool(value) for value in attributes):
                raise RuntimeError("application-identity role retained a dangerous attribute, membership, or database CREATE privilege")
            cursor.execute(
                """SELECT setconfig FROM pg_db_role_setting s
                     JOIN pg_roles r ON r.oid=s.setrole
                    WHERE r.rolname=%s AND s.setdatabase=0""",
                (ROLE_NAME,),
            )
            setting_row = cursor.fetchone()
            role_settings = set(setting_row[0] or []) if setting_row else set()
            expected_log_settings = {
                "log_statement=none",
                "log_parameter_max_length=0",
                "log_parameter_max_length_on_error=0",
            }
            if not expected_log_settings.issubset(role_settings):
                raise RuntimeError(
                    "application-identity role does not suppress SQL statement and parameter logging"
                )
    if not password:
        raise RuntimeError("application-identity writer credential is unavailable")
    # Verify the effective settings through the exact writer/database
    # connection. This catches a higher-priority role+database override that
    # cannot be seen by inspecting only setdatabase=0 catalog rows.
    with psycopg.connect(
        host=runtime["host"], port=int(runtime["port"]), dbname=runtime["dbname"],
        user=ROLE_NAME, password=password,
        sslmode=runtime["sslmode"], sslrootcert=runtime["sslrootcert"],
        connect_timeout=int(runtime.get("connect_timeout_seconds", 5)),
    ) as writer_connection:
        with writer_connection.cursor() as cursor:
            cursor.execute(
                """SELECT session_user,current_setting('log_statement'),
                          current_setting('log_parameter_max_length'),
                          current_setting('log_parameter_max_length_on_error')"""
            )
            effective = tuple(str(value) for value in cursor.fetchone())
            if effective != (ROLE_NAME, "none", "0", "0"):
                raise RuntimeError(
                    "application-identity writer effective parameter logging settings are unsafe"
                )
    if not keyring.get_password(idempotency_service, idempotency_account):
        keyring.set_password(
            idempotency_service, idempotency_account, secrets.token_urlsafe(64)
        )
    if not keyring.get_password(idempotency_service, idempotency_account):
        raise RuntimeError("password-idempotency secret could not be provisioned")
    if not keyring.get_password(proof_service, proof_account):
        keyring.set_password(proof_service, proof_account, secrets.token_urlsafe(64))
    if not keyring.get_password(proof_service, proof_account):
        raise RuntimeError("authentication-proof secret could not be provisioned")
    roles = runtime.setdefault("roles", {})
    roles[ROLE_KEY] = {
        "user": ROLE_NAME,
        "credential_service": SERVICE,
        "credential_account": ROLE_NAME,
    }
    raw = json.dumps(runtime, ensure_ascii=False, indent=2).encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=runtime_path.name + ".", suffix=".tmp", dir=runtime_path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, runtime_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision the application-identity writer without printing credentials")
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--security-config", required=True, type=Path)
    args = parser.parse_args()
    provision(args.runtime.resolve(), args.security_config.resolve())
    print("application identity role provisioned; no credential value was printed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
