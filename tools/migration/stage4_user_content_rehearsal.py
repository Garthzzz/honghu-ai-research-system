from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from tools.data_platform.routing import AuthorityState, Backend, CutoverRoute
from tools.data_platform.user_content_notes import (
    AnalystNoteMutation,
    AnalystNoteWriterFenced,
    PostgresAnalystNoteRepository,
)
from tools.migration.sqlite_inventory import audit_live_schema


TEST_DATABASE_PREFIX = "honghu_stage4_"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
LIVE_DATABASES = ("research.db", "financial.db", "opportunity_lens.db", "sentiment.db")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_rehearsal_target(host: str, port: int, database: str) -> None:
    if host not in LOOPBACK_HOSTS:
        raise ValueError("Stage 4 rehearsal must bind to loopback only")
    if port == 5432:
        raise ValueError("Stage 4 rehearsal refuses the conventional production port 5432")
    if not database.startswith(TEST_DATABASE_PREFIX):
        raise ValueError(f"rehearsal database must start with {TEST_DATABASE_PREFIX!r}")


def _tool(bin_dir: Path, name: str) -> str:
    path = (bin_dir / f"{name}.exe").resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return str(path)


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        executable = Path(command[0]).name
        detail = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
        raise RuntimeError(
            f"{executable} exited with code {result.returncode}"
            + (f":\n{detail}" if detail else "")
        )
    return result


def _applied_migration_sha(
    psql: str,
    connection: list[str],
    database: str,
    migration_id: str,
) -> str | None:
    result = _run(
        [
            psql,
            "-X",
            "--no-psqlrc",
            "-A",
            "-t",
            *connection,
            "-d",
            database,
            "-c",
            (
                "SELECT migration_sha256 FROM operations.schema_migration "
                f"WHERE migration_id = '{migration_id}'"
            ),
        ]
    )
    value = result.stdout.strip()
    return value or None


def _apply_migration_or_verify(
    *,
    psql: str,
    connection: list[str],
    database: str,
    migration: Path,
    migration_sha256: str,
    ledger_exists: bool,
) -> None:
    migration_id = migration.stem
    if ledger_exists:
        applied = _applied_migration_sha(psql, connection, database, migration_id)
        if applied:
            if applied != migration_sha256:
                raise RuntimeError(
                    f"migration {migration_id} is recorded with a different SHA256"
                )
            return
    _run(
        [
            psql,
            "-X",
            "--no-psqlrc",
            "-v",
            "ON_ERROR_STOP=1",
            "-v",
            f"migration_sha256={migration_sha256}",
            *connection,
            "-d",
            database,
            "-f",
            str(migration),
        ]
    )


def _live_file_hashes(data_root: Path) -> dict[str, str]:
    return {name: sha256_file(data_root / name) for name in LIVE_DATABASES}


def _schema_identity(audit: dict[str, Any]) -> dict[str, Any]:
    return {
        database: {
            "user_version": detail["user_version"],
            "tables": {
                table["name"]: table["schema_sha256"] for table in detail["tables"]
            },
        }
        for database, detail in audit["databases"].items()
    }


def _run_adapter_rehearsal(
    *,
    host: str,
    port: int,
    database: str,
    username: str,
    reader_role: str,
    writer_role: str,
    writer_identity: str,
    sslmode: str = "disable",
    password: str | None = None,
) -> dict[str, Any]:
    """Exercise the real repository against the isolated PostgreSQL database."""

    import psycopg
    from psycopg import sql

    def connection_factory(role: str):
        def connect():
            connection = psycopg.connect(
                host=host,
                port=port,
                dbname=database,
                user=username,
                password=password,
                sslmode=sslmode,
            )
            connection.execute(
                sql.SQL("SET SESSION AUTHORIZATION {}").format(sql.Identifier(role))
            )
            return connection

        return connect

    common = dict(
        cutover_unit="user_content_notes",
        backend=Backend.POSTGRESQL_PRODUCTION,
        writer_operation="analyst_note_mutation",
        transaction_boundary="one note mutation plus revision, audit and idempotency",
        sqlite_writer_enabled=False,
        production_postgresql_enabled=True,
        writer_identity=writer_identity,
        cutover_epoch="epoch-user-content",
        approval_reference="stage4-s4-approved",
    )
    stale_route = CutoverRoute(authority_state=AuthorityState.S3, **common)
    stale_repository = PostgresAnalystNoteRepository(
        connection_factory(reader_role), connection_factory(writer_role), stale_route
    )
    stale_route_fenced = False
    try:
        stale_repository.list_notes(
            entity_type="theme",
            legacy_entity_id="ai_datacenter",
            entity_key="theme:ai_datacenter",
            q_label=None,
        )
    except AnalystNoteWriterFenced:
        stale_route_fenced = True
    if not stale_route_fenced:
        raise RuntimeError("stale adapter route was not fenced")

    route = CutoverRoute(authority_state=AuthorityState.S4, **common)
    repository = PostgresAnalystNoteRepository(
        connection_factory(reader_role), connection_factory(writer_role), route
    )
    note_key = "analyst-note:adapter-rehearsal"
    created = repository.put(
        AnalystNoteMutation(
            note_key=note_key,
            entity_type="theme",
            legacy_entity_id="ai_datacenter",
            entity_key="theme:ai_datacenter",
            q_label="Q6",
            note_type="thesis",
            title=None,
            content="adapter create",
            expected_revision=0,
            idempotency_key="adapter-create-1",
        ),
        actor="principal:adapter-rehearsal",
    )
    updated = repository.put(
        AnalystNoteMutation(
            note_key=note_key,
            entity_type="theme",
            legacy_entity_id="ai_datacenter",
            entity_key="theme:ai_datacenter",
            q_label="Q6",
            note_type="thesis",
            title=None,
            content="adapter update",
            expected_revision=1,
            idempotency_key="adapter-update-1",
        ),
        actor="principal:adapter-rehearsal",
    )
    visible_before_delete = repository.list_notes(
        entity_type="theme",
        legacy_entity_id="ai_datacenter",
        entity_key="theme:ai_datacenter",
        q_label="Q6",
    )
    deleted = repository.soft_delete(
        note_key=note_key,
        expected_revision=2,
        idempotency_key="adapter-delete-1",
        actor="principal:adapter-rehearsal",
    )
    replayed = repository.soft_delete(
        note_key=note_key,
        expected_revision=2,
        idempotency_key="adapter-delete-1",
        actor="principal:adapter-rehearsal",
    )
    visible_after_delete = repository.list_notes(
        entity_type="theme",
        legacy_entity_id="ai_datacenter",
        entity_key="theme:ai_datacenter",
        q_label="Q6",
    )

    with connection_factory(reader_role)() as connection:
        compatibility_row = connection.execute(
            """SELECT id, entity_type, entity_id, q_number, note_type,
                      title, content, author, created_at, updated_at
                 FROM user_content.analyst_note_read_v1
                ORDER BY id LIMIT 1"""
        ).fetchone()
    if compatibility_row is None:
        raise RuntimeError("schema-compatible reader rehearsal returned no row")
    if not any(row.note_key == note_key for row in visible_before_delete):
        raise RuntimeError("adapter-created note was not visible through the reader role")
    if any(row.note_key == note_key for row in visible_after_delete):
        raise RuntimeError("soft-deleted adapter note remained in the active read view")
    if not (
        created.revision == 1
        and updated.revision == 2
        and deleted.revision == 3
        and replayed.revision == 3
        and replayed.deleted
    ):
        raise RuntimeError("adapter revision or idempotent-delete contract failed")
    return {
        "status": "pass",
        "stale_route_fenced": stale_route_fenced,
        "reader_writer_roles_distinct": reader_role != writer_role,
        "create_revision": created.revision,
        "update_revision": updated.revision,
        "delete_revision": deleted.revision,
        "idempotent_delete_revision": replayed.revision,
        "active_before_delete": True,
        "active_after_delete": False,
        "schema_compatible_reader": True,
        "authority_state_after_adapter": "S4",
    }


def run_rehearsal(
    *,
    root: Path,
    bin_dir: Path,
    host: str,
    port: int,
    username: str,
    database: str,
    live_data_root: Path,
    sslmode: str = "disable",
    password: str | None = None,
) -> dict[str, Any]:
    validate_rehearsal_target(host, port, database)
    restore_database = f"{database}_restore"
    psql = _tool(bin_dir, "psql")
    createdb = _tool(bin_dir, "createdb")
    dropdb = _tool(bin_dir, "dropdb")
    pg_dump = _tool(bin_dir, "pg_dump")
    pg_restore = _tool(bin_dir, "pg_restore")
    writer_role = "honghu_stage4_writer_rehearsal"
    writer_identity = "honghu_user_content_writer_rehearsal"
    reader_role = "honghu_stage4_reader_rehearsal"
    controller_role = "honghu_stage4_controller_rehearsal"
    audit_reader_role = "honghu_stage4_audit_reader_rehearsal"
    rehearsal_roles = (writer_role, reader_role, controller_role, audit_reader_role)
    migration_paths = [
        root / "migrations/postgresql/0001_user_content_notes_expand.sql",
        root / "migrations/postgresql/0002_user_content_notes_cutover_expand.sql",
        root / "migrations/postgresql/0004_user_content_writer_identity_separation.sql",
    ]
    rehearsal_path = root / "migrations/postgresql/0002_user_content_notes_cutover_rehearsal.sql"
    role_grants_path = root / "migrations/postgresql/0002_user_content_notes_role_grants.sql"
    migration_sha256 = {path.name: sha256_file(path) for path in migration_paths}
    before_file_hashes = _live_file_hashes(live_data_root)
    before_schema = audit_live_schema(live_data_root)
    started = time.perf_counter()
    connection = ["-h", host, "-p", str(port), "-U", username]

    primary_error: BaseException | None = None
    try:
        for name in (restore_database, database):
            _run([dropdb, *connection, "--if-exists", name])
        for role in rehearsal_roles:
            _run(
                [
                    psql, "-X", "--no-psqlrc", *connection, "-d", "postgres",
                    "-c", f'DROP ROLE IF EXISTS "{role}"; CREATE ROLE "{role}" NOLOGIN;',
                ]
            )
        _run([createdb, *connection, database])
        ledger_exists = False
        for migration in migration_paths:
            for _ in range(2):
                _apply_migration_or_verify(
                    psql=psql,
                    connection=connection,
                    database=database,
                    migration=migration,
                    migration_sha256=migration_sha256[migration.name],
                    ledger_exists=ledger_exists,
                )
                ledger_exists = True

        _run(
            [
                psql,
                "-X",
                "--no-psqlrc",
                "-v",
                "ON_ERROR_STOP=1",
                "-v",
                f"writer_role={writer_role}",
                "-v",
                f"reader_role={reader_role}",
                "-v",
                f"controller_role={controller_role}",
                "-v",
                f"audit_reader_role={audit_reader_role}",
                *connection,
                "-d",
                database,
                "-f",
                str(role_grants_path),
            ]
        )
        acl = _run(
            [
                psql,
                "-X",
                "--no-psqlrc",
                "-A",
                "-t",
                *connection,
                "-d",
                database,
                "-c",
                "SELECT jsonb_build_object("
                f"'writer_direct_insert',has_table_privilege('{writer_role}',"
                "'user_content.analyst_note','INSERT'),"
                f"'writer_v2_execute',has_function_privilege('{writer_role}',"
                "'user_content.put_analyst_note_v2(text,text,text,text,text,text,text,text,text,bigint,text,text,text)','EXECUTE'),"
                f"'writer_soft_delete_execute',has_function_privilege('{writer_role}',"
                "'user_content.soft_delete_analyst_note_v2(text,text,bigint,text,text,text)','EXECUTE'),"
                f"'reader_base_select',has_table_privilege('{reader_role}',"
                "'user_content.analyst_note','SELECT'),"
                f"'reader_view_select',has_table_privilege('{reader_role}',"
                "'user_content.analyst_note_read_v1','SELECT'),"
                f"'reader_identity_view_select',has_table_privilege('{reader_role}',"
                "'user_content.analyst_note_identity_v1','SELECT'),"
                f"'reader_authority_view_select',has_table_privilege('{reader_role}',"
                "'operations.user_content_notes_authority_v1','SELECT'),"
                f"'writer_authority_view_select',has_table_privilege('{writer_role}',"
                "'operations.user_content_notes_authority_v1','SELECT'),"
                f"'controller_transition_execute',has_function_privilege('{controller_role}',"
                "'operations.transition_user_content_notes(text,bigint,text,text,text,jsonb,text,text,text)','EXECUTE'),"
                f"'controller_mapping_execute',has_function_privilege('{controller_role}',"
                "'operations.register_user_content_notes_dependency_mapping(bigint,text,text,text,text,text,jsonb,text,text,text,text)','EXECUTE'),"
                f"'controller_generic_transition_execute',has_function_privilege('{controller_role}',"
                "'operations.transition_cutover_unit(text,text,bigint,text,text,text,text,jsonb,text,text,text)','EXECUTE'));",
            ]
        )
        acl_result = json.loads(acl.stdout.strip())
        expected_acl = {
            "writer_direct_insert": False,
            "writer_v2_execute": True,
            "writer_soft_delete_execute": True,
            "reader_base_select": False,
            "reader_view_select": True,
            "reader_identity_view_select": True,
            "reader_authority_view_select": True,
            "writer_authority_view_select": True,
            "controller_transition_execute": True,
            "controller_mapping_execute": True,
            "controller_generic_transition_execute": False,
        }
        if acl_result != expected_acl:
            raise RuntimeError(f"least-privilege ACL rehearsal failed: {acl_result!r}")

        rehearsal = _run(
            [
                psql,
                "-X",
                "--no-psqlrc",
                "-v",
                "ON_ERROR_STOP=1",
                "-v",
                f"writer_role={writer_role}",
                "-v",
                f"writer_identity={writer_identity}",
                "-v",
                f"controller_role={controller_role}",
                "-A",
                "-t",
                *connection,
                "-d",
                database,
                "-f",
                str(rehearsal_path),
            ]
        )
        rehearsal_result = json.loads(rehearsal.stdout.strip().splitlines()[-1])
        adapter_result = _run_adapter_rehearsal(
            host=host,
            port=port,
            database=database,
            username=username,
            reader_role=reader_role,
            writer_role=writer_role,
            writer_identity=writer_identity,
            sslmode=sslmode,
            password=password,
        )

        with tempfile.TemporaryDirectory(prefix="honghu-stage4-pg-") as temporary:
            dump_path = Path(temporary) / "stage4-user-content.dump"
            _run([pg_dump, "-Fc", *connection, "-d", database, "-f", str(dump_path)])
            dump_sha256 = sha256_file(dump_path)
            _run([createdb, *connection, restore_database])
            _run([pg_restore, *connection, "-d", restore_database, str(dump_path)])
            restored = _run(
                [
                    psql,
                    "-X",
                    "--no-psqlrc",
                    "-A",
                    "-t",
                    *connection,
                    "-d",
                    restore_database,
                    "-c",
                    "SELECT jsonb_build_object("
                    "'authority_state',(SELECT state FROM operations.cutover_unit_authority "
                    "WHERE cutover_unit='user_content_notes'),"
                    "'authority_revision_count',(SELECT count(*) FROM audit.cutover_unit_authority_revision "
                    "WHERE cutover_unit='user_content_notes'),"
                    "'note_count',(SELECT count(*) FROM user_content.analyst_note),"
                    "'soft_deleted_count',(SELECT count(*) FROM user_content.analyst_note "
                    "WHERE deleted_at IS NOT NULL),"
                    "'first_formal_operation_scope',(SELECT postgresql_first_formal_commit->>"
                    "'operation_scope' FROM operations.cutover_unit_authority "
                    "WHERE cutover_unit='user_content_notes'),"
                    "'first_formal_object_key',(SELECT postgresql_first_formal_commit->>"
                    "'object_key' FROM operations.cutover_unit_authority "
                    "WHERE cutover_unit='user_content_notes'),"
                    "'dependency_mapping_audit_count',(SELECT count(*) "
                    "FROM audit.cutover_dependency_mapping_revision "
                    "WHERE cutover_unit='user_content_notes'),"
                    "'stable_alias_count',(SELECT count(*) "
                    "FROM operations.cutover_dependency_mapping "
                    "WHERE cutover_unit='user_content_notes' "
                    "AND stable_key='company:COHU:US-equity'),"
                    "'q6_legacy_count',(SELECT count(*) FROM user_content.analyst_note "
                    "WHERE q_label='Q6' AND legacy_note_id=42 AND title IS NULL));",
                ]
            )
            restore_result = json.loads(restored.stdout.strip())

        after_file_hashes = _live_file_hashes(live_data_root)
        after_schema = audit_live_schema(live_data_root)
        schema_unchanged = _schema_identity(before_schema) == _schema_identity(after_schema)
        if not schema_unchanged:
            raise RuntimeError("live SQLite schema changed during the isolated rehearsal")
        expected_first_formal = {
            "first_formal_operation_scope": "user_content.soft_delete_analyst_note_v2",
            "first_formal_object_key": "analyst-note:research.db:42",
        }
        if (
            rehearsal_result.get("status") != "pass"
            or restore_result.get("authority_state") != "S4"
            or any(rehearsal_result.get(key) != value for key, value in expected_first_formal.items())
            or any(restore_result.get(key) != value for key, value in expected_first_formal.items())
            or rehearsal_result.get("stable_alias_count") != 2
            or restore_result.get("stable_alias_count") != 2
        ):
            raise RuntimeError("Stage 4 rehearsal or side restore invariant failed")
        return {
            "schema_version": "honghu.stage4_user_content_rehearsal_evidence.v2",
            "status": "pass",
            "environment": "postgresql_devtest",
            "host": host,
            "port": port,
            "database": database,
            "production_cutover_authorized": False,
            "migration_sha256": migration_sha256,
            "migration_applied_twice": True,
            "rehearsal_result": rehearsal_result,
            "least_privilege_result": acl_result,
            "adapter_result": adapter_result,
            "side_restore_result": restore_result,
            "dump_sha256": dump_sha256,
            "live_sqlite_schema_unchanged": True,
            "live_sqlite_file_hashes_unchanged": before_file_hashes == after_file_hashes,
            "live_sqlite_before_sha256": before_file_hashes,
            "live_sqlite_after_sha256": after_file_hashes,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        cleanup_errors: list[str] = []
        for name in (restore_database, database):
            try:
                _run([dropdb, *connection, "--if-exists", name])
            except Exception as exc:
                cleanup_errors.append(f"drop database {name}: {exc}")
        for role in rehearsal_roles:
            try:
                _run(
                    [
                        psql, "-X", "--no-psqlrc", *connection, "-d", "postgres",
                        "-c", f'DROP ROLE IF EXISTS "{role}";',
                    ]
                )
            except Exception as exc:
                cleanup_errors.append(f"drop role {role}: {exc}")
        if cleanup_errors:
            message = "Stage 4 rehearsal cleanup failed: " + "; ".join(cleanup_errors)
            if primary_error is not None:
                primary_error.add_note(message)
            else:
                raise RuntimeError(message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--bin-dir", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=55432)
    parser.add_argument("--username", default="honghu_devtest")
    parser.add_argument("--database", default="honghu_stage4_user_content")
    parser.add_argument("--live-data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sslmode", choices=("disable", "require"), default="disable")
    args = parser.parse_args(argv)
    evidence = run_rehearsal(
        root=args.root.resolve(),
        bin_dir=args.bin_dir.resolve(),
        host=args.host,
        port=args.port,
        username=args.username,
        database=args.database,
        live_data_root=args.live_data_root.resolve(),
        sslmode=args.sslmode,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
