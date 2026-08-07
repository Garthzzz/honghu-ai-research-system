from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


TEST_DATABASE_PREFIX = "honghu_stage3_"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def live_sqlite_hashes(data_root: Path) -> dict[str, str]:
    return {
        name: sha256_file(data_root / name)
        for name in ("research.db", "financial.db", "opportunity_lens.db", "sentiment.db")
    }


def _run(command: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        input=input_text,
        text=True,
        capture_output=True,
        check=True,
        encoding="utf-8",
        errors="replace",
    )


def _tool(bin_dir: Path, name: str) -> str:
    path = (bin_dir / f"{name}.exe").resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return str(path)


def validate_test_target(host: str, port: int, database: str) -> None:
    if host not in LOOPBACK_HOSTS:
        raise ValueError("Stage 3 PostgreSQL must bind to loopback only")
    if port == 5432:
        raise ValueError("Stage 3 refuses the conventional production port 5432")
    if not database.startswith(TEST_DATABASE_PREFIX):
        raise ValueError(f"test database must start with {TEST_DATABASE_PREFIX!r}")


def cluster_init(bin_dir: Path, cluster_root: Path, port: int, username: str) -> dict[str, Any]:
    cluster_root = cluster_root.resolve()
    if (cluster_root / "PG_VERSION").exists():
        return {"status": "existing", "cluster_root": str(cluster_root), "port": port}
    cluster_root.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            _tool(bin_dir, "initdb"),
            "-D",
            str(cluster_root),
            "-U",
            username,
            "--encoding=UTF8",
            "--locale=C",
            "--auth-local=trust",
            "--auth-host=trust",
        ]
    )
    with (cluster_root / "postgresql.auto.conf").open("a", encoding="utf-8") as handle:
        handle.write("\nlisten_addresses = '127.0.0.1'\n")
        handle.write(f"port = {port}\n")
        handle.write("fsync = on\n")
    return {"status": "created", "cluster_root": str(cluster_root), "port": port}


def cluster_start(bin_dir: Path, cluster_root: Path, port: int) -> dict[str, Any]:
    result = _run(
        [
            _tool(bin_dir, "pg_ctl"),
            "-D",
            str(cluster_root.resolve()),
            "-o",
            f"-h 127.0.0.1 -p {port}",
            "-w",
            "start",
        ]
    )
    return {"status": "started", "stdout": result.stdout.strip()}


def cluster_stop(bin_dir: Path, cluster_root: Path) -> dict[str, Any]:
    result = _run(
        [_tool(bin_dir, "pg_ctl"), "-D", str(cluster_root.resolve()), "-m", "fast", "-w", "stop"]
    )
    return {"status": "stopped", "stdout": result.stdout.strip()}


def run_pilot(
    *,
    root: Path,
    bin_dir: Path,
    host: str,
    port: int,
    username: str,
    database: str,
    live_data_root: Path,
) -> dict[str, Any]:
    validate_test_target(host, port, database)
    restore_database = f"{database}_restore"
    psql = _tool(bin_dir, "psql")
    createdb = _tool(bin_dir, "createdb")
    dropdb = _tool(bin_dir, "dropdb")
    pg_dump = _tool(bin_dir, "pg_dump")
    pg_restore = _tool(bin_dir, "pg_restore")
    migration = root / "migrations/postgresql/0001_user_content_notes_expand.sql"
    pilot = root / "migrations/postgresql/0001_user_content_notes_pilot.sql"
    migration_sha = sha256_file(migration)
    before_hashes = live_sqlite_hashes(live_data_root)
    started = time.perf_counter()

    connection = ["-h", host, "-p", str(port), "-U", username]
    for name in (restore_database, database):
        _run([dropdb, *connection, "--if-exists", name])
    _run([createdb, *connection, database])
    try:
        apply_command = [
            psql,
            "-X",
            "--no-psqlrc",
            "-v",
            "ON_ERROR_STOP=1",
            "-v",
            f"migration_sha256={migration_sha}",
            *connection,
            "-d",
            database,
            "-f",
            str(migration),
        ]
        _run(apply_command)
        _run(apply_command)
        pilot_result = _run(
            [
                psql,
                "-X",
                "--no-psqlrc",
                "-v",
                "ON_ERROR_STOP=1",
                "-A",
                "-t",
                *connection,
                "-d",
                database,
                "-f",
                str(pilot),
            ]
        )
        with tempfile.TemporaryDirectory(prefix="honghu-stage3-pg-") as temporary:
            dump_path = Path(temporary) / "pilot.dump"
            _run([pg_dump, "-Fc", *connection, "-d", database, "-f", str(dump_path)])
            dump_sha = sha256_file(dump_path)
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
                    "SELECT jsonb_build_object('note_count',count(*),'max_revision',max(revision),'soft_deleted',bool_and(deleted_at IS NOT NULL)) FROM user_content.analyst_note;",
                ]
            ).stdout.strip()
        after_hashes = live_sqlite_hashes(live_data_root)
        if before_hashes != after_hashes:
            raise RuntimeError("live SQLite hashes changed during the isolated pilot")
        return {
            "schema_version": "honghu.postgresql_devtest_pilot_evidence.v1",
            "status": "pass",
            "backend": "postgresql_devtest",
            "host": host,
            "port": port,
            "database": database,
            "migration_sha256": migration_sha,
            "migration_applied_twice": True,
            "pilot_result": pilot_result.stdout.strip().splitlines()[-1],
            "restore_result": restored,
            "dump_sha256": dump_sha,
            "live_sqlite_hashes_unchanged": True,
            "live_sqlite_sha256": before_hashes,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
    finally:
        _run([dropdb, *connection, "--if-exists", restore_database])
        _run([dropdb, *connection, "--if-exists", database])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--bin-dir", type=Path, required=True)
    common.add_argument("--cluster-root", type=Path, required=True)
    common.add_argument("--port", type=int, default=55432)
    common.add_argument("--username", default="honghu_devtest")
    sub.add_parser("cluster-init", parents=[common])
    sub.add_parser("cluster-start", parents=[common])
    sub.add_parser("cluster-stop", parents=[common])
    pilot = sub.add_parser("pilot", parents=[common])
    pilot.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    pilot.add_argument("--host", default="127.0.0.1")
    pilot.add_argument("--database", default="honghu_stage3_user_content")
    pilot.add_argument("--live-data-root", type=Path, required=True)
    pilot.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "cluster-init":
        result = cluster_init(args.bin_dir, args.cluster_root, args.port, args.username)
    elif args.command == "cluster-start":
        result = cluster_start(args.bin_dir, args.cluster_root, args.port)
    elif args.command == "cluster-stop":
        result = cluster_stop(args.bin_dir, args.cluster_root)
    else:
        result = run_pilot(
            root=args.root.resolve(),
            bin_dir=args.bin_dir,
            host=args.host,
            port=args.port,
            username=args.username,
            database=args.database,
            live_data_root=args.live_data_root.resolve(),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
