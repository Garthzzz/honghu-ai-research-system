from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

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
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=True,
        encoding="utf-8",
        errors="replace",
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


def run_rehearsal(
    *,
    root: Path,
    bin_dir: Path,
    host: str,
    port: int,
    username: str,
    database: str,
    live_data_root: Path,
) -> dict[str, Any]:
    validate_rehearsal_target(host, port, database)
    restore_database = f"{database}_restore"
    psql = _tool(bin_dir, "psql")
    createdb = _tool(bin_dir, "createdb")
    dropdb = _tool(bin_dir, "dropdb")
    pg_dump = _tool(bin_dir, "pg_dump")
    pg_restore = _tool(bin_dir, "pg_restore")
    writer_role = "honghu_stage4_writer_rehearsal"
    reader_role = "honghu_stage4_reader_rehearsal"
    controller_role = "honghu_stage4_controller_rehearsal"
    audit_reader_role = "honghu_stage4_audit_reader_rehearsal"
    rehearsal_roles = (writer_role, reader_role, controller_role, audit_reader_role)
    migration_paths = [
        root / "migrations/postgresql/0001_user_content_notes_expand.sql",
        root / "migrations/postgresql/0002_user_content_notes_cutover_expand.sql",
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
        for migration in migration_paths:
            apply_command = [
                psql,
                "-X",
                "--no-psqlrc",
                "-v",
                "ON_ERROR_STOP=1",
                "-v",
                f"migration_sha256={migration_sha256[migration.name]}",
                *connection,
                "-d",
                database,
                "-f",
                str(migration),
            ]
            _run(apply_command)
            _run(apply_command)

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
                f"'reader_base_select',has_table_privilege('{reader_role}',"
                "'user_content.analyst_note','SELECT'),"
                f"'reader_view_select',has_table_privilege('{reader_role}',"
                "'user_content.analyst_note_read_v1','SELECT'),"
                f"'controller_transition_execute',has_function_privilege('{controller_role}',"
                "'operations.transition_user_content_notes(text,bigint,text,text,text,text,jsonb,text,text,text)','EXECUTE'),"
                f"'controller_generic_transition_execute',has_function_privilege('{controller_role}',"
                "'operations.transition_cutover_unit(text,text,bigint,text,text,text,text,jsonb,text,text,text)','EXECUTE'));",
            ]
        )
        acl_result = json.loads(acl.stdout.strip())
        expected_acl = {
            "writer_direct_insert": False,
            "writer_v2_execute": True,
            "reader_base_select": False,
            "reader_view_select": True,
            "controller_transition_execute": True,
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
                f"writer_identity={writer_role}",
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
        if rehearsal_result.get("status") != "pass" or restore_result.get("authority_state") != "S3":
            raise RuntimeError("Stage 4 rehearsal or side restore invariant failed")
        return {
            "schema_version": "honghu.stage4_user_content_rehearsal_evidence.v1",
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
    args = parser.parse_args(argv)
    evidence = run_rehearsal(
        root=args.root.resolve(),
        bin_dir=args.bin_dir.resolve(),
        host=args.host,
        port=args.port,
        username=args.username,
        database=args.database,
        live_data_root=args.live_data_root.resolve(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
