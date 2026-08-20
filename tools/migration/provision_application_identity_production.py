from __future__ import annotations

"""Apply the application-account production closure in a fixed safe order.

This command must run under the approved VM interactive token.  It provisions
the least-privilege writer and VM-only secrets, applies the exact reviewed
migration, finalizes the authentication proof, and then verifies the resulting
ACL/logging boundary.  No secret or secret hash is written to evidence.
"""

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.data_platform.postgres_runtime import (
    build_catalog_connection_factory,
    credential_manager_password,
    load_postgres_runtime_catalog,
)
from tools.migration.finalize_application_identity_auth_proof import finalize
from tools.migration.provision_application_identity_role import ROLE_NAME, provision
from tools.migration.stage4_apply_postgresql_migrations import (
    MIGRATION_IDENTIFIERS,
    _admin_connection,
    render_schema_migration,
)
from tools.migration.stage4_user_content_security_provision import _settings


MIGRATION_NAME = "0026_application_account_management.sql"
EXPECTED_FUNCTIONS = {
    "complete_login_v1",
    "create_account_v1",
    "delete_account_v1",
    "list_accounts_v1",
    "login_verifier_v1",
    "logout_v1",
    "reset_password_v1",
    "resolve_session_v1",
    "update_account_v1",
}
EXPECTED_LOG_SETTINGS = {
    "log_statement=none",
    "log_parameter_max_length=0",
    "log_parameter_max_length_on_error=0",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _verify(connection: Any) -> dict[str, Any]:
    role = connection.execute(
        """SELECT r.rolsuper,r.rolcreatedb,r.rolcreaterole,r.rolreplication,
                  r.rolbypassrls,r.rolinherit,
                  (SELECT count(*) FROM pg_auth_members m WHERE m.member=r.oid),
                  has_database_privilege(r.rolname,current_database(),'CREATE'),
                  EXISTS(
                    SELECT 1 FROM pg_namespace n
                     WHERE n.nspname NOT LIKE 'pg_%%'
                       AND n.nspname<>'information_schema'
                       AND has_schema_privilege(r.rolname,n.oid,'CREATE')
                  ),
                  EXISTS(
                    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                     WHERE c.relkind IN ('r','p') AND n.nspname NOT LIKE 'pg_%%'
                       AND n.nspname<>'information_schema'
                       AND has_table_privilege(r.rolname,c.oid,
                         'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                  )
             FROM pg_roles r WHERE r.rolname=%s""",
        (ROLE_NAME,),
    ).fetchone()
    if role is None or any(bool(value) for value in role):
        raise RuntimeError("application-identity writer retained a dangerous privilege")
    setting_row = connection.execute(
        """SELECT setconfig FROM pg_db_role_setting s
             JOIN pg_roles r ON r.oid=s.setrole
            WHERE r.rolname=%s AND s.setdatabase=0""",
        (ROLE_NAME,),
    ).fetchone()
    role_settings = set(setting_row[0] or []) if setting_row else set()
    if not EXPECTED_LOG_SETTINGS.issubset(role_settings):
        raise RuntimeError("application-identity writer parameter logging is not suppressed")
    functions = {
        str(row[0])
        for row in connection.execute(
            """SELECT p.proname FROM pg_proc p
                 JOIN pg_namespace n ON n.oid=p.pronamespace
                WHERE n.nspname='application_identity'
                  AND has_function_privilege(%s,p.oid,'EXECUTE')""",
            (ROLE_NAME,),
        ).fetchall()
    }
    if functions != EXPECTED_FUNCTIONS:
        raise RuntimeError(f"application-identity writer function allowlist differs: {functions}")
    authority = connection.execute(
        """SELECT authority_revision,
                  authentication_proof_sha256<>repeat('0',64)
             FROM application_identity.authority
            WHERE authority_key='application_accounts'"""
    ).fetchone()
    if authority is None or authority[1] is not True:
        raise RuntimeError("application authentication proof was not finalized")
    audit = connection.execute(
        """SELECT action,key_version,authority_revision_after,sessions_revoked
             FROM application_identity.security_audit
            ORDER BY security_audit_id DESC LIMIT 1"""
    ).fetchone()
    if audit is None or audit[1] != 1 or int(audit[2]) != int(authority[0]):
        raise RuntimeError("application authentication proof audit is incomplete")
    return {
        "writer_dangerous_privileges": False,
        "writer_function_allowlist": sorted(functions),
        "parameter_logging_suppressed": True,
        "authentication_proof_finalized": True,
        "authentication_proof_audit_action": str(audit[0]),
        "authority_revision": int(authority[0]),
        "sessions_revoked_by_latest_proof_action": bool(audit[3]),
        "secret_or_secret_hash_recorded": False,
    }


def _apply_exact(connection: Any, migration_path: Path, migration_sha: str) -> dict[str, Any]:
    migration_id = migration_path.stem
    existing = connection.execute(
        "SELECT migration_sha256 FROM operations.schema_migration WHERE migration_id=%s",
        (migration_id,),
    ).fetchone()
    if existing is not None:
        if str(existing[0]) != migration_sha:
            raise RuntimeError("application-account migration ledger SHA differs")
        return {
            "migration_id": migration_id,
            "sha256": migration_sha,
            "status": "already_exact",
        }
    connection.execute(
        render_schema_migration(
            migration_path.read_text(encoding="utf-8"),
            migration_sha,
            identifiers=MIGRATION_IDENTIFIERS[MIGRATION_NAME],
        )
    )
    recorded = connection.execute(
        "SELECT migration_sha256 FROM operations.schema_migration WHERE migration_id=%s",
        (migration_id,),
    ).fetchone()
    if recorded is None or str(recorded[0]) != migration_sha:
        raise RuntimeError("application-account migration was not recorded exactly")
    return {"migration_id": migration_id, "sha256": migration_sha, "status": "applied"}


def _preflight(
    connection: Any,
    *,
    migration_path: Path,
    migration_sha: str,
    security_config_path: Path,
) -> dict[str, Any]:
    security = _settings(security_config_path)
    existing = connection.execute(
        "SELECT migration_sha256 FROM operations.schema_migration WHERE migration_id=%s",
        (migration_path.stem,),
    ).fetchone()
    if existing is not None and str(existing[0]) != migration_sha:
        raise RuntimeError("application-account migration ledger SHA differs")
    proof = credential_manager_password(
        str(security["authentication_proof_secret_service"]),
        str(security["authentication_proof_secret_account"]),
    )
    # A missing proof is allowed only for the first deployment, where the
    # role provisioner creates it. A present proof must already be usable.
    if proof is not None and len(proof) < 32:
        raise RuntimeError("existing authentication-proof secret is invalid")
    return {
        "migration_ledger": "already_exact" if existing is not None else "absent",
        "security_contract_valid": True,
        "existing_authentication_proof_valid": proof is None or len(proof) >= 32,
    }


def _verify_writer_effective(runtime_path: Path) -> None:
    factory = build_catalog_connection_factory(
        load_postgres_runtime_catalog(runtime_path),
        role="writer_application_identity",
    )
    with factory() as connection:
        with connection.cursor() as cursor:
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


def run(
    *, repo_root: Path, runtime_path: Path, security_config_path: Path, output: Path
) -> dict[str, Any]:
    migration_path = repo_root / "migrations" / "postgresql" / MIGRATION_NAME
    if not migration_path.is_file():
        raise RuntimeError("reviewed application-account migration is missing")
    # Every prerequisite is checked before the first database mutation.
    security_sha = _sha(security_config_path)
    migration_sha = _sha(migration_path)
    with _admin_connection(runtime_path) as connection:
        preflight = _preflight(
            connection,
            migration_path=migration_path,
            migration_sha=migration_sha,
            security_config_path=security_config_path,
        )
    provision(runtime_path, security_config_path)
    with _admin_connection(runtime_path) as connection:
        migration_result = _apply_exact(connection, migration_path, migration_sha)
    finalize(
        runtime_path,
        security_config_path,
        reason="controlled production application-identity deployment",
    )
    _verify_writer_effective(runtime_path)
    with _admin_connection(runtime_path) as connection:
        verification = _verify(connection)
    verification["effective_writer_connection_verified"] = True
    core = {
        "schema_version": "honghu.application_identity_production_provision.v1",
        "status": "pass",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "security_config_sha256": security_sha,
        "migration_sha256": migration_sha,
        "preflight": preflight,
        "migration_result": migration_result,
        "verification": verification,
    }
    core["evidence_sha256"] = hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    _write_json_atomic(output, core)
    return core


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--security-config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    result = run(
        repo_root=args.repo_root.resolve(),
        runtime_path=args.runtime.resolve(),
        security_config_path=args.security_config.resolve(),
        output=args.output.resolve(),
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "evidence_sha256": result["evidence_sha256"],
                "secret_recorded": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
