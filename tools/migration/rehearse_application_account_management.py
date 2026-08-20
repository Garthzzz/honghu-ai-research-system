from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tools.data_platform.application_accounts import (
    ALLOWED_PERMISSIONS,
    ApplicationAccountError,
    PostgresApplicationAccountStore,
    password_hash,
)
from tools.data_platform.postgres_runtime import (
    build_catalog_connection_factory,
    credential_manager_password,
    load_postgres_runtime_catalog,
)
from tools.migration.finalize_application_identity_auth_proof import finalize
from tools.migration.stage4_apply_postgresql_migrations import (
    MIGRATION_IDENTIFIERS,
    render_schema_migration,
)


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def run(repo_root: Path, runtime_path: Path, security_path: Path, output: Path) -> dict[str, Any]:
    runtime = json.loads(runtime_path.read_text(encoding="utf-8-sig"))
    database = "honghu_account_rehearsal_" + secrets.token_hex(5)
    writer_role = "honghu_account_rehearsal_" + secrets.token_hex(5)
    writer_password = secrets.token_urlsafe(48)
    temp_runtime_path = output.with_suffix(".runtime.json")
    admin = runtime["break_glass"]
    admin_password = credential_manager_password(admin["credential_service"], admin["credential_account"])
    if not admin_password: raise RuntimeError("break-glass credential is unavailable")
    import psycopg
    from psycopg import sql

    def admin_connect(dbname: str, *, autocommit: bool = True):
        return psycopg.connect(
            host=runtime["host"],port=int(runtime["port"]),dbname=dbname,
            user=admin["user"],password=admin_password,sslmode=runtime["sslmode"],
            sslrootcert=runtime["sslrootcert"],connect_timeout=5,autocommit=autocommit,
        )

    database_created = False
    writer_role_created = False
    try:
        with admin_connect("postgres") as connection:
            connection.execute(
                sql.SQL(
                    """CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                       NOREPLICATION NOBYPASSRLS NOINHERIT"""
                ).format(sql.Identifier(writer_role))
            )
            writer_role_created = True
            connection.execute(
                sql.SQL("ALTER ROLE {} PASSWORD %s").format(
                    sql.Identifier(writer_role)
                ),
                (writer_password,),
            )
            connection.execute(
                sql.SQL("ALTER ROLE {} SET log_statement='none'").format(
                    sql.Identifier(writer_role)
                )
            )
            connection.execute(
                sql.SQL("ALTER ROLE {} SET log_parameter_max_length='0'").format(
                    sql.Identifier(writer_role)
                )
            )
            connection.execute(
                sql.SQL(
                    "ALTER ROLE {} SET log_parameter_max_length_on_error='0'"
                ).format(sql.Identifier(writer_role))
            )
            connection.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(
                    sql.Identifier(database)
                )
            )
            database_created = True
        temp_runtime = dict(runtime); temp_runtime["dbname"] = database
        temp_runtime["roles"] = dict(runtime["roles"])
        temp_runtime["roles"]["writer_application_identity"] = {
            "user": writer_role,
            "credential_service": "rehearsal.memory.only",
            "credential_account": writer_role,
        }
        _write_json_atomic(temp_runtime_path, temp_runtime)
        with admin_connect(database) as connection:
            connection.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
            connection.execute("CREATE SCHEMA operations")
            connection.execute("""CREATE TABLE operations.schema_migration(
              migration_id text PRIMARY KEY,migration_sha256 text NOT NULL,phase text NOT NULL,
              applied_at timestamptz NOT NULL DEFAULT clock_timestamp(),forward_only boolean NOT NULL
            )""")
            migration_path=repo_root/"migrations/postgresql/0026_application_account_management.sql"
            migration_sha=hashlib.sha256(migration_path.read_bytes()).hexdigest()
            rehearsal_sql = migration_path.read_text(encoding="utf-8").replace(
                "honghu_writer_application_identity", writer_role
            )
            rehearsal_identifiers = dict(MIGRATION_IDENTIFIERS[migration_path.name])
            rehearsal_identifiers["writer_role"] = writer_role
            connection.execute(
                render_schema_migration(
                    rehearsal_sql,migration_sha,identifiers=rehearsal_identifiers,
                )
            )
            recorded=connection.execute("SELECT migration_sha256 FROM operations.schema_migration WHERE migration_id='0026_application_account_management'").fetchone()
            if recorded is None or recorded[0]!=migration_sha: raise RuntimeError("migration ledger SHA differs")
        catalog = load_postgres_runtime_catalog(temp_runtime_path)
        migration_factory = build_catalog_connection_factory(catalog,role="migration")
        zero_proof_rejected = False
        with migration_factory() as connection:
            try:
                connection.execute(
                    "SELECT application_identity.local_set_authentication_proof_v1(%s,%s,%s)",
                    ("0" * 64, "zero-proof rehearsal", 1),
                )
            except Exception:
                zero_proof_rejected = True
                connection.rollback()
        if not zero_proof_rejected:
            raise RuntimeError("zero authentication proof was accepted")
        finalize(
            temp_runtime_path,
            security_path,
            reason="isolated rehearsal initialization",
        )
        with migration_factory() as connection:
            initial_authority_revision = int(
                connection.execute(
                    "SELECT authority_revision FROM application_identity.authority"
                ).fetchone()[0]
            )
            initial_audit_count = int(
                connection.execute(
                    "SELECT count(*) FROM application_identity.security_audit"
                ).fetchone()[0]
            )
        finalize(
            temp_runtime_path,
            security_path,
            reason="isolated rehearsal idempotent verification",
        )
        with migration_factory() as connection:
            repeated_authority_revision = int(
                connection.execute(
                    "SELECT authority_revision FROM application_identity.authority"
                ).fetchone()[0]
            )
            repeated_audit_count = int(
                connection.execute(
                    "SELECT count(*) FROM application_identity.security_audit"
                ).fetchone()[0]
            )
        if repeated_authority_revision != initial_authority_revision or repeated_audit_count != initial_audit_count + 1:
            raise RuntimeError("same authentication proof finalization was not idempotent and audited")
        operator_password = secrets.token_urlsafe(32) + "Aa1!"
        with migration_factory() as connection:
            connection.execute(
                "SELECT application_identity.local_reset_superadmin_v1(%s,%s,%s)",
                ("research-operator",password_hash("research-operator",operator_password),"isolated rehearsal"),
            )
        security = json.loads(security_path.read_text(encoding="utf-8-sig"))
        idem_secret = credential_manager_password(
            security["password_idempotency_secret_service"],security["password_idempotency_secret_account"]
        )
        proof_secret = credential_manager_password(
            security["authentication_proof_secret_service"],security["authentication_proof_secret_account"]
        )
        if not idem_secret or not proof_secret: raise RuntimeError("application secrets are unavailable")
        writer_factory = build_catalog_connection_factory(
            catalog,role="writer_application_identity",
            password_loader=lambda _service,_account: writer_password,
        )
        authentication_proof_denials: list[bool] = []
        with writer_factory() as connection:
            for supplied_proof in ("", "incorrect-proof-value-that-is-long-enough"):
                try:
                    connection.execute(
                        "SELECT * FROM application_identity.complete_login_v1(%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            "research-operator", True, 1, supplied_proof,
                            hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
                            datetime.now(timezone.utc) + timedelta(hours=1),
                            None, None,
                        ),
                    )
                    authentication_proof_denials.append(False)
                except Exception:
                    authentication_proof_denials.append(True)
                    connection.rollback()
        if authentication_proof_denials != [True, True]:
            raise RuntimeError("missing or incorrect authentication proof was accepted")
        store = PostgresApplicationAccountStore(
            writer_factory,legacy_password_verifier=lambda _s,_p: False,
            idempotency_secret=idem_secret,authentication_proof_secret=proof_secret,
            expected_writer_identity=writer_role,
        )
        operator = store.login(subject="research-operator",password=operator_password,user_agent="rehearsal",remote_address="127.0.0.1")
        admin_permissions = sorted(ALLOWED_PERMISSIONS)
        second_password = secrets.token_urlsafe(32) + "Aa1!"
        second = store.create_account(
            operator.session_token,subject="second-admin",display_name="Second Admin",
            password=second_password,permissions=admin_permissions,superadmin=True,
            reason="concurrency rehearsal",idempotency_key="create-second-admin",
        )
        second_login = store.login(subject="second-admin",password=second_password,user_agent="rehearsal",remote_address="127.0.0.2")
        normal_password = secrets.token_urlsafe(32) + "Aa1!"
        normal_permissions = ["analyst_note:read","valuation_tracker:read"]
        first = store.create_account(
            operator.session_token,subject="replay-user",display_name="Replay User",
            password=normal_password,permissions=normal_permissions,superadmin=False,
            reason="idempotency rehearsal",idempotency_key="create-replay-user",
        )
        replay = store.create_account(
            operator.session_token,subject="replay-user",display_name="Replay User",
            password=normal_password,permissions=normal_permissions,superadmin=False,
            reason="idempotency rehearsal",idempotency_key="create-replay-user",
        )
        if first != replay: raise RuntimeError("same idempotency replay changed result")
        different_payload_conflict=False
        try:
            store.create_account(
                operator.session_token,subject="replay-user",display_name="Replay User",
                password=secrets.token_urlsafe(32)+"Aa1!",permissions=normal_permissions,
                superadmin=False,reason="idempotency rehearsal",idempotency_key="create-replay-user",
            )
        except ApplicationAccountError:
            different_payload_conflict=True
        if not different_payload_conflict: raise RuntimeError("different password reused an idempotency key")
        null_fingerprint_rejected=False
        with writer_factory() as connection:
            try:
                connection.execute(
                    "SELECT application_identity.create_account_v1(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (hashlib.sha256(operator.session_token.encode()).hexdigest(),"null-fingerprint",
                     "Null Fingerprint",password_hash("null-fingerprint",secrets.token_urlsafe(32)+"Aa1!"),
                     None,normal_permissions,False,"null fingerprint rehearsal","null-fingerprint"),
                )
            except Exception:
                null_fingerprint_rejected=True; connection.rollback()
        if not null_fingerprint_rejected: raise RuntimeError("NULL password fingerprint was accepted")
        normal_login = store.login(subject="replay-user",password=normal_password,user_agent="rehearsal",remote_address="127.0.0.3")
        store.reset_password(
            operator.session_token,"replay-user",password=secrets.token_urlsafe(32)+"Aa1!",
            expected_revision=int(first["revision"]),reason="session revocation rehearsal",
            idempotency_key="reset-replay-user",
        )
        if store.resolve_session(normal_login.session_token) is not None:
            raise RuntimeError("password reset did not revoke the old session")
        barrier=threading.Barrier(2); outcomes:list[str]=[]; lock=threading.Lock()
        operator_public=next(x for x in store.list_accounts(operator.session_token) if x["subject"]=="research-operator")
        def demote(store_token:str,target:dict[str,Any],key:str)->None:
            barrier.wait()
            try:
                store.update_account(
                    store_token,target["subject"],display_name=target["display_name"],
                    permissions=normal_permissions,superadmin=False,active=True,
                    expected_revision=int(target["revision"]),reason="last-admin concurrency rehearsal",
                    idempotency_key=key,
                ); result="success"
            except ApplicationAccountError: result="rejected"
            with lock: outcomes.append(result)
        threads=[
            threading.Thread(target=demote,args=(operator.session_token,second,"demote-second")),
            threading.Thread(target=demote,args=(second_login.session_token,operator_public,"demote-operator")),
        ]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        if sorted(outcomes)!=["rejected","success"]: raise RuntimeError(f"last-admin concurrency invariant failed: {outcomes}")
        with migration_factory() as connection:
            before_rotation = connection.execute(
                "SELECT authority_revision,(SELECT count(*) FROM application_identity.session WHERE revoked_at IS NULL) FROM application_identity.authority"
            ).fetchone()
            rotation_probe_sha = hashlib.sha256(secrets.token_bytes(64)).hexdigest()
            connection.execute(
                "SELECT application_identity.local_set_authentication_proof_v1(%s,%s,%s)",
                (rotation_probe_sha, "isolated rehearsal rotation probe", 1),
            )
        finalize(
            temp_runtime_path,
            security_path,
            reason="isolated rehearsal proof restoration",
        )
        with migration_factory() as connection:
            after_rotation = connection.execute(
                "SELECT authority_revision,(SELECT count(*) FROM application_identity.session WHERE revoked_at IS NULL) FROM application_identity.authority"
            ).fetchone()
        if int(before_rotation[1]) < 1 or int(after_rotation[0]) != int(before_rotation[0]) + 2 or int(after_rotation[1]) != 0:
            raise RuntimeError("authentication proof rotation did not revoke sessions and restore authority")
        with admin_connect(database) as connection:
            active_admins=connection.execute("SELECT count(*) FROM application_identity.account WHERE status='active' AND is_superadmin").fetchone()[0]
            audit_text=json.dumps(connection.execute("SELECT before_payload,after_payload FROM application_identity.account_revision_audit").fetchall(),default=str)
            result_text=json.dumps(connection.execute("SELECT result_payload FROM application_identity.mutation_result").fetchall(),default=str)
            security_audit_text=json.dumps(connection.execute("SELECT action,actor,reason,key_version,authority_revision_before,authority_revision_after,sessions_revoked FROM application_identity.security_audit").fetchall(),default=str)
            if active_admins!=1: raise RuntimeError("last active superadmin count differs")
            if any(token in (audit_text+result_text+security_audit_text) for token in ("password_hash","password_fingerprint","authentication_proof_sha256",operator_password,normal_password,second_password,proof_secret)):
                raise RuntimeError("secret material reached audit or mutation result")
            functions=connection.execute("""SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
              WHERE n.nspname='application_identity' AND has_function_privilege(%s,p.oid,'EXECUTE') ORDER BY p.proname""",
              (writer_role,),
            ).fetchall()
            allowed={"login_verifier_v1","complete_login_v1","resolve_session_v1","logout_v1","list_accounts_v1","create_account_v1","update_account_v1","reset_password_v1","delete_account_v1"}
            if {row[0] for row in functions}!=allowed: raise RuntimeError(f"writer function allowlist differs: {functions}")
        direct_denials=[]
        with writer_factory() as connection:
            log_settings = connection.execute(
                "SELECT current_setting('log_statement'),current_setting('log_parameter_max_length'),current_setting('log_parameter_max_length_on_error')"
            ).fetchone()
            if tuple(str(value) for value in log_settings) != ("none", "0", "0"):
                raise RuntimeError(f"writer parameter logging is not suppressed: {log_settings}")
            for statement in ("SELECT * FROM application_identity.account","UPDATE application_identity.account SET revision=revision","CREATE SCHEMA forbidden_writer_schema"):
                try: connection.execute(statement); direct_denials.append(False)
                except Exception: direct_denials.append(True); connection.rollback()
        if not all(direct_denials): raise RuntimeError("writer direct SELECT/DML/CREATE boundary failed")
        core={
            "schema_version":"honghu.application_account_rehearsal.v1","status":"pass",
            "migration_sha256":migration_sha,
            "same_request_replay":True,"different_payload_conflict":different_payload_conflict,
            "null_fingerprint_rejected":null_fingerprint_rejected,"old_session_revoked":True,
            "zero_authentication_proof_rejected":zero_proof_rejected,
            "missing_and_wrong_authentication_proof_rejected":authentication_proof_denials,
            "same_authentication_proof_idempotent_and_audited":True,
            "authentication_proof_rotation_revoked_sessions":True,
            "writer_parameter_logging_suppressed":True,
            "last_superadmin_concurrency":outcomes,"active_superadmin_count":active_admins,
            "writer_direct_denials":direct_denials,"writer_function_allowlist":sorted(allowed),
            "dedicated_temporary_writer_role":True,
            "production_writer_credential_unchanged":True,
            "secret_material_recorded":False,"temporary_database_dropped":False,
        }
        core["evidence_sha256"]=hashlib.sha256(json.dumps(core,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        return core
    finally:
        with admin_connect("postgres") as connection:
            if database_created:
                connection.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s",(database,))
                connection.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database)))
            if writer_role_created:
                connection.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(writer_role)))
        if temp_runtime_path.exists(): temp_runtime_path.unlink()


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description="Isolated PG17 rehearsal for application account management")
    parser.add_argument("--repo-root",required=True,type=Path); parser.add_argument("--runtime",required=True,type=Path)
    parser.add_argument("--security-config",required=True,type=Path); parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args(argv); result=run(args.repo_root.resolve(),args.runtime.resolve(),args.security_config.resolve(),args.output.resolve())
    result["temporary_database_dropped"]=True
    _write_json_atomic(args.output.resolve(),result); print(json.dumps(result,ensure_ascii=False)); return 0


if __name__=="__main__": raise SystemExit(main())
