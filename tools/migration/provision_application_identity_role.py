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
    password = secrets.token_urlsafe(48)
    import psycopg
    import keyring

    security = json.loads(security_config_path.read_text(encoding="utf-8-sig"))
    idempotency_service = str(security.get("password_idempotency_secret_service") or "")
    idempotency_account = str(security.get("password_idempotency_secret_account") or "")
    proof_service = str(security.get("authentication_proof_secret_service") or "")
    proof_account = str(security.get("authentication_proof_secret_account") or "")
    if (
        security.get("password_idempotency_secret_version") != 1
        or not idempotency_service
        or not idempotency_account
        or security.get("authentication_proof_secret_version") != 1
        or not proof_service
        or not proof_account
    ):
        raise RuntimeError("dedicated password-idempotency secret identity v1 is required")

    with psycopg.connect(
        host=runtime["host"], port=int(runtime["port"]), dbname=runtime["dbname"],
        user=str(admin.get("user") or ""), password=admin_password,
        sslmode=runtime["sslmode"], sslrootcert=runtime["sslrootcert"],
        connect_timeout=int(runtime.get("connect_timeout_seconds", 5)),
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """DO $$ BEGIN
                     IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='honghu_writer_application_identity') THEN
                       CREATE ROLE honghu_writer_application_identity LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
                     END IF;
                   END $$"""
            )
            cursor.execute(
                "ALTER ROLE honghu_writer_application_identity PASSWORD %s",
                (password,),
            )
            cursor.execute(
                """ALTER ROLE honghu_writer_application_identity
                     LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
                     NOBYPASSRLS NOINHERIT"""
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
    keyring.set_password(SERVICE, ROLE_NAME, password)
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
