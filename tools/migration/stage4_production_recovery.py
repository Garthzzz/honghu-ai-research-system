from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.migration.stage4_recovery_set import (
    assert_restore_sources,
    build_recovery_set,
    measured_recovery,
    sha256_file,
    sha256_json,
    verify_recovery_set,
)
from tools.migration.stage4_json_io import read_json


class ProductionRecoveryError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ProductionRecoveryError(f"JSON object required: {path}")
    return payload


def _password(runtime: dict[str, Any], role: str) -> tuple[str, str]:
    config = (runtime.get("roles") or {}).get(role)
    if not isinstance(config, dict):
        raise ProductionRecoveryError(f"runtime role missing: {role}")
    import keyring

    password = keyring.get_password(
        str(config.get("credential_service") or ""),
        str(config.get("credential_account") or ""),
    )
    if not password:
        raise ProductionRecoveryError(f"runtime credential unavailable: {role}")
    return str(config["user"]), password


def _tool(bin_dir: Path, name: str) -> Path:
    path = (bin_dir / f"{name}.exe").resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _run(
    command: list[str],
    *,
    password: str | None = None,
    input_text: str | None = None,
    sslrootcert: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("PGSERVICE", None)
    env.pop("PGPASSFILE", None)
    env.pop("PYTHONPATH", None)
    env["PGCONNECT_TIMEOUT"] = "5"
    env["PGSSLMODE"] = "verify-full"
    if sslrootcert is not None:
        root = sslrootcert.resolve()
        if not root.is_file():
            raise ProductionRecoveryError("libpq TLS root certificate is missing")
        env["PGSSLROOTCERT"] = str(root)
    else:
        env.pop("PGSSLROOTCERT", None)
    if password is not None:
        env["PGPASSWORD"] = password
    result = subprocess.run(
        command,
        input=input_text,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    if result.returncode != 0:
        detail = "\n".join(
            value.strip() for value in (result.stdout, result.stderr) if value.strip()
        )
        raise ProductionRecoveryError(
            f"{Path(command[0]).name} exited with {result.returncode}"
            + (f": {detail}" if detail else "")
        )
    return result


def _connect(runtime: dict[str, Any], role: str, *, port: int | None = None) -> Any:
    import psycopg

    username, password = _password(runtime, role)
    return psycopg.connect(
        host=runtime["host"],
        port=int(port or runtime["port"]),
        dbname=runtime["dbname"],
        user=username,
        password=password,
        sslmode=runtime["sslmode"],
        sslrootcert=runtime["sslrootcert"],
        connect_timeout=5,
        autocommit=True,
    )


def _wait_for_wal(archive: Path, filename: str, timeout: float = 60.0) -> Path:
    deadline = time.monotonic() + timeout
    target = archive / filename
    while time.monotonic() < deadline:
        if target.is_file() and target.stat().st_size > 0:
            return target
        time.sleep(0.25)
    raise ProductionRecoveryError(f"required archived WAL did not appear: {filename}")


def _required_wal_names(
    start_name: str, end_name: str, wal_segment_size_bytes: int = 16 * 1024 * 1024
) -> list[str]:
    pattern = re.compile(r"^[0-9A-F]{24}$")
    start_name = start_name.upper()
    end_name = end_name.upper()
    if not pattern.fullmatch(start_name) or not pattern.fullmatch(end_name):
        raise ProductionRecoveryError("backup/target WAL filename is invalid")
    if start_name[:8] != end_name[:8]:
        raise ProductionRecoveryError("recovery crosses an unreviewed WAL timeline")
    if (
        wal_segment_size_bytes <= 0
        or (wal_segment_size_bytes & (wal_segment_size_bytes - 1)) != 0
        or (1 << 32) % wal_segment_size_bytes != 0
    ):
        raise ProductionRecoveryError("WAL segment size is invalid")
    segments_per_log = (1 << 32) // wal_segment_size_bytes
    start_log, start_segment = int(start_name[8:16], 16), int(start_name[16:], 16)
    end_log, end_segment = int(end_name[8:16], 16), int(end_name[16:], 16)
    if start_segment >= segments_per_log or end_segment >= segments_per_log:
        raise ProductionRecoveryError("WAL filename segment exceeds cluster geometry")
    start = start_log * segments_per_log + start_segment
    end = end_log * segments_per_log + end_segment
    if end < start or end - start > 4096:
        raise ProductionRecoveryError("required WAL range is reversed or unexpectedly large")
    return [
        f"{start_name[:8]}{value // segments_per_log:08X}{value % segments_per_log:08X}"
        for value in range(start, end + 1)
    ]


def _backup_start_wal(base_backup: Path) -> str:
    label = base_backup / "backup_label"
    if not label.is_file():
        raise ProductionRecoveryError("plain base backup has no backup_label")
    match = re.search(
        r"^START WAL LOCATION:.*\(file ([0-9A-F]{24})\)$",
        label.read_text(encoding="ascii", errors="strict"),
        flags=re.MULTILINE,
    )
    if not match:
        raise ProductionRecoveryError("backup_label has no verifiable START WAL file")
    return match.group(1)


def _pg_ctl(bin_dir: Path, data_dir: Path, action: str) -> None:
    command = [str(_tool(bin_dir, "pg_ctl")), "-D", str(data_dir), "-w"]
    if action == "start":
        command += ["-l", str(data_dir.parent / "restore-postgresql.log"), "start"]
    else:
        command += ["-m", "fast", "stop"]
    _run(command)


def _system_identifier(bin_dir: Path, data_dir: Path) -> str:
    output = _run([str(_tool(bin_dir, "pg_controldata")), str(data_dir)]).stdout
    for line in output.splitlines():
        if "Database system identifier" in line:
            return line.split(":", 1)[1].strip()
    raise ProductionRecoveryError("pg_controldata did not expose system identifier")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_production_recovery(
    *,
    repo_root: Path,
    runtime_path: Path,
    bin_dir: Path,
    install_root: Path,
    commit_sha: str,
    output_dir: Path,
    off_vm_root: Path | None,
    expected_off_vm_storage_identity: str | None,
) -> dict[str, Any]:
    runtime = _load_json(runtime_path)
    if runtime.get("schema_version") != "honghu.postgresql_production_runtime.v1":
        raise ProductionRecoveryError("unsupported production runtime schema")
    if runtime.get("environment_id") != "production":
        raise ProductionRecoveryError("recovery source is not production-scoped")
    if runtime.get("application_commit_sha") != commit_sha:
        raise ProductionRecoveryError("runtime belongs to another application commit")
    if runtime.get("application_route") != "sqlite_transition":
        raise ProductionRecoveryError("application authority is not SQLite")
    if len(commit_sha) != 40:
        raise ProductionRecoveryError("full application commit SHA is required")
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = install_root / "data"
    wal_archive = install_root / "wal-archive"
    local_backup_root = install_root / "backup"
    if not data_dir.is_dir() or not wal_archive.is_dir():
        raise ProductionRecoveryError("production PostgreSQL data/WAL archive is missing")
    system_identifier = _system_identifier(bin_dir, data_dir)
    run_id = f"stage4-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    source_base = local_backup_root / run_id / "base"
    source_base.parent.mkdir(parents=True, exist_ok=False)
    backup_user, backup_password = _password(runtime, "backup")

    base_started = _utc_now()
    _run(
        [
            str(_tool(bin_dir, "pg_basebackup")),
            "--host",
            str(runtime["host"]),
            "--port",
            str(runtime["port"]),
            "--username",
            backup_user,
            "--pgdata",
            str(source_base),
            "--format=plain",
            "--wal-method=none",
            "--checkpoint=fast",
            "--no-password",
        ],
        password=backup_password,
        sslrootcert=Path(str(runtime["sslrootcert"])),
    )
    base_completed = _utc_now()

    sentinel_id = f"stage4-production-recovery:{uuid.uuid4().hex}"
    with _connect(runtime, "migration") as connection:
        connection.execute(
            "INSERT INTO operations.bootstrap_recovery_sentinel(operation_id) VALUES (%s)",
            (sentinel_id,),
        )
        target_lsn, durable_at, required_wal, wal_segment_size = connection.execute(
            """
            SELECT pg_current_wal_flush_lsn()::text,
                   to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
                   pg_walfile_name(pg_current_wal_flush_lsn()),
                   pg_size_bytes(current_setting('wal_segment_size'))
            """
        ).fetchone()
        connection.execute("SELECT pg_switch_wal()")
    required_wal_files = _required_wal_names(
        _backup_start_wal(source_base),
        str(required_wal),
        int(wal_segment_size),
    )
    for wal_name in required_wal_files:
        _wait_for_wal(wal_archive, wal_name)

    source_identity = {
        "environment_id": "production",
        "host": socket.gethostname(),
        "service_name": runtime["service_name"],
        "system_identifier": system_identifier,
        "application_commit_sha": commit_sha,
        "runtime_config_sha256": sha256_file(runtime_path),
        "base_backup_started_at_utc": base_started,
        "base_backup_completed_at_utc": base_completed,
    }
    target = {
        "sentinel_operation_id": sentinel_id,
        "target_lsn": str(target_lsn),
        "durable_target_at_utc": str(durable_at),
        "required_wal_files": required_wal_files,
        "base_backup_started_at_utc": base_started,
        "base_backup_completed_at_utc": base_completed,
    }
    if off_vm_root is not None:
        destination = off_vm_root / "honghu-postgresql" / run_id
        require_off_vm = True
    else:
        destination = local_backup_root / run_id / "recovery-set"
        require_off_vm = False
    manifest = build_recovery_set(
        base_backup=source_base,
        wal_archive=wal_archive,
        destination=destination,
        source_identity=source_identity,
        target=target,
        expected_storage_identity=expected_off_vm_storage_identity,
        require_off_vm=require_off_vm,
    )
    verified = verify_recovery_set(
        destination,
        expected_identity=manifest["recovery_set_identity"],
        expected_storage_identity=manifest["storage_evidence"]["derived_storage_identity"],
        verify_storage_location=True,
    )

    restore_parent = install_root / "restore-tests" / run_id
    restore_data = restore_parent / "data"
    restore_parent.mkdir(parents=True, exist_ok=False)
    assert_restore_sources(destination, destination / "base_backup", destination / "wal")
    shutil.copytree(destination / "base_backup", restore_data)
    wal_source = (destination / "wal").resolve().as_posix()
    restore_lines = [
        "listen_addresses = '127.0.0.1'",
        f"port = {int(runtime['port']) + 1}",
        "archive_mode = off",
        f"restore_command = 'copy /Y \"{wal_source}/%f\" \"%p\"'",
        f"recovery_target_lsn = '{target_lsn}'",
        "recovery_target_action = 'promote'",
    ]
    with (restore_data / "postgresql.auto.conf").open("a", encoding="utf-8") as handle:
        handle.write("\n# Stage 4 exact recovery-set restore\n")
        handle.write("\n".join(restore_lines) + "\n")
    (restore_data / "recovery.signal").touch()
    started = time.monotonic()
    restore_started = False
    try:
        _pg_ctl(bin_dir, restore_data, "start")
        restore_started = True
        with _connect(runtime, "migration", port=int(runtime["port"]) + 1) as restored:
            row = restored.execute(
                """
                SELECT operation_id,
                       to_char(committed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
                       pg_last_wal_replay_lsn()::text,
                       coalesce(pg_last_wal_replay_lsn() >= %s::pg_lsn, false)
                  FROM operations.bootstrap_recovery_sentinel
                 WHERE operation_id=%s
                """,
                (str(target_lsn), sentinel_id),
            ).fetchone()
            if row is None:
                raise ProductionRecoveryError("target recovery sentinel was not restored")
            recovered = {
                "sentinel_operation_id": str(row[0]),
                "recovered_watermark_at_utc": str(row[1]),
                "recovered_lsn": str(row[2]),
                "target_lsn_reached": bool(row[3]),
            }
            authority = restored.execute(
                """
                SELECT state, authoritative_backend, writer_identity,
                       cutover_epoch, postgresql_first_formal_commit
                  FROM operations.cutover_unit_authority
                 WHERE cutover_unit='user_content_notes'
                """
            ).fetchone()
    finally:
        if restore_started:
            _pg_ctl(bin_dir, restore_data, "stop")
    elapsed = time.monotonic() - started
    measurement = measured_recovery(
        target=target, recovered=recovered, restore_elapsed_seconds=elapsed
    )
    if authority is not None and (
        authority[0] not in {"S0", "S1"}
        or authority[1] != "sqlite_transition"
        or any(value is not None for value in authority[2:])
    ):
        raise ProductionRecoveryError("restored authority control exceeds S0/S1")
    result_core = {
        "schema_version": "honghu.stage4_production_recovery.v1",
        "status": "pass" if require_off_vm else "engineering_partial",
        "environment_id": "production",
        "application_commit_sha": commit_sha,
        "runtime_config_sha256": sha256_file(runtime_path),
        "source_identity": source_identity,
        "target": target,
        "recovery_set_identity": manifest["recovery_set_identity"],
        "recovery_set_storage": manifest["storage_evidence"],
        "restore_source_contract": "recovery_set_only",
        "recovered": recovered,
        "measurement": measurement,
        "whole_database_restore": "pass",
        "authority_control_restore": "pass",
        "side_domain_restore": {
            "status": "pass",
            "method": "physical side instance; user_content/operations/audit queried without production mutation",
        },
        "off_vm_verified": bool(require_off_vm),
        "application_authority": "sqlite_transition",
        "formal_business_data_written": False,
    }
    result = {**result_core, "evidence_sha256": sha256_json(result_core)}
    _write_json(output_dir / "production_recovery.json", result)
    _write_json(output_dir / "recovery_set_manifest.copy.json", verified)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--bin-dir", type=Path, required=True)
    parser.add_argument("--install-root", type=Path, required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--off-vm-root", type=Path)
    parser.add_argument("--expected-off-vm-storage-identity")
    args = parser.parse_args(argv)
    result = run_production_recovery(
        repo_root=args.repo_root,
        runtime_path=args.runtime,
        bin_dir=args.bin_dir,
        install_root=args.install_root,
        commit_sha=args.commit_sha,
        output_dir=args.output_dir,
        off_vm_root=args.off_vm_root,
        expected_off_vm_storage_identity=args.expected_off_vm_storage_identity,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
