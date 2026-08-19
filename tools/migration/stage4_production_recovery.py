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

from tools.migration.stage4_authority_control import (
    AuthorityControlError,
    authority_snapshot,
    read_authority_snapshots,
)
from tools.migration.stage4_runtime_contract import (
    RuntimeContractError,
    tracked_static_default_route,
)

from tools.migration.stage4_recovery_set import (
    assert_restore_sources,
    build_recovery_set,
    enforce_validated_recovery_retention,
    measured_recovery,
    sha256_file,
    sha256_json,
    verify_recovery_set,
)
from tools.migration.stage4_json_io import read_json


class ProductionRecoveryError(RuntimeError):
    pass


def _canonical_checkpoint_value(value: Any) -> Any:
    """Return a JSON-stable representation of PostgreSQL recovery evidence."""

    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ProductionRecoveryError(
                "task checkpoint timestamp has no timezone"
            )
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {
            str(key): _canonical_checkpoint_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_checkpoint_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ProductionRecoveryError(
        f"unsupported task checkpoint value: {type(value).__name__}"
    )


def read_task_checkpoint_snapshot(
    connection: Any, *, expected_task_ids: tuple[str, ...]
) -> dict[str, Any]:
    """Read the reviewed task definitions and latest durable checkpoint rows."""

    expected = tuple(sorted(dict.fromkeys(expected_task_ids)))
    if len(expected) != 10 or any(not task_id.strip() for task_id in expected):
        raise ProductionRecoveryError(
            "task checkpoint recovery requires the reviewed ten-task manifest"
        )
    rows = connection.execute(
        """
        SELECT d.task_id,d.manifest_sha256,d.application_commit_sha,
               d.cutover_unit,d.writer_units,d.runner_host,
               d.freshness_seconds,d.enabled,d.definition_revision,
               d.registered_at,d.updated_at,
               r.logical_window,r.run_attempt,r.operation_id_sha256,
               r.manifest_sha256,r.application_commit_sha,r.runner_host,
               r.runner_principal,r.status,r.failure_classification,
               r.return_code,r.started_at,r.heartbeat_at,r.finished_at,
               r.output_tail_sha256,r.business_checkpoint_before,
               r.business_checkpoint_after
          FROM operations.production_task_definition d
          LEFT JOIN LATERAL (
              SELECT x.*
                FROM operations.production_task_run x
               WHERE x.task_id=d.task_id
               ORDER BY x.started_at DESC,x.run_attempt DESC,
                        x.logical_window DESC
               LIMIT 1
          ) r ON true
         ORDER BY d.task_id
        """
    ).fetchall()
    observed = tuple(str(row[0]) for row in rows)
    if observed != expected:
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        raise ProductionRecoveryError(
            "task checkpoint definition set mismatch: "
            f"missing={missing}, extra={extra}"
        )

    tasks: list[dict[str, Any]] = []
    for row in rows:
        values = list(row)
        if len(values) != 27:
            raise ProductionRecoveryError(
                "task checkpoint query returned an unsupported row shape"
            )
        task_id = str(values[0])
        definition = {
            key: _canonical_checkpoint_value(value)
            for key, value in zip(
                (
                    "task_id",
                    "manifest_sha256",
                    "application_commit_sha",
                    "cutover_unit",
                    "writer_units",
                    "runner_host",
                    "freshness_seconds",
                    "enabled",
                    "definition_revision",
                    "registered_at_utc",
                    "updated_at_utc",
                ),
                values[:11],
            )
        }
        latest_values = values[11:]
        latest_run = None
        if latest_values[0] is not None:
            latest_run = {
                key: _canonical_checkpoint_value(value)
                for key, value in zip(
                    (
                        "logical_window",
                        "run_attempt",
                        "operation_id_sha256",
                        "manifest_sha256",
                        "application_commit_sha",
                        "runner_host",
                        "runner_principal",
                        "status",
                        "failure_classification",
                        "return_code",
                        "started_at_utc",
                        "heartbeat_at_utc",
                        "finished_at_utc",
                        "output_tail_sha256",
                        "business_checkpoint_before",
                        "business_checkpoint_after",
                    ),
                    latest_values,
                )
            }
        task = {
            "task_id": task_id,
            "definition": definition,
            "latest_run": latest_run,
        }
        task["identity_sha256"] = sha256_json(task)
        tasks.append(task)
    core = {
        "schema_version": "honghu.stage5_task_checkpoint_snapshot.v1",
        "task_count": len(tasks),
        "latest_run_count": sum(item["latest_run"] is not None for item in tasks),
        "tasks": tasks,
    }
    return {**core, "identity_sha256": sha256_json(core)}


def verify_task_checkpoint_restore(
    source: dict[str, Any], restored: dict[str, Any]
) -> dict[str, Any]:
    """Fail closed unless the restored task/checkpoint snapshot is identical."""

    for label, snapshot in (("source", source), ("restored", restored)):
        core = {
            key: value
            for key, value in snapshot.items()
            if key != "identity_sha256"
        }
        if sha256_json(core) != snapshot.get("identity_sha256"):
            raise ProductionRecoveryError(
                f"{label} task checkpoint snapshot identity is invalid"
            )
        tasks = snapshot.get("tasks")
        expected_count = int(snapshot.get("task_count") or 0)
        if not isinstance(tasks, list) or expected_count <= 0 or len(tasks) != expected_count:
            raise ProductionRecoveryError(
                f"{label} task checkpoint snapshot is incomplete"
            )
        for task in tasks:
            if not isinstance(task, dict):
                raise ProductionRecoveryError(
                    f"{label} task checkpoint entry is invalid"
                )
            task_core = {
                key: value for key, value in task.items() if key != "identity_sha256"
            }
            if sha256_json(task_core) != task.get("identity_sha256"):
                raise ProductionRecoveryError(
                    f"{label} task checkpoint entry identity is invalid"
                )
    source_identity = str(source.get("identity_sha256") or "")
    restored_identity = str(restored.get("identity_sha256") or "")
    if not source_identity or source_identity != restored_identity:
        raise ProductionRecoveryError(
            "restored production task definitions/checkpoints do not match source"
        )
    if (
        int(source.get("task_count") or 0) <= 0
        or source.get("task_count") != restored.get("task_count")
    ):
        raise ProductionRecoveryError(
            "restored production task checkpoint set is incomplete"
        )
    return {
        "status": "pass",
        "verified": True,
        "task_count": int(source["task_count"]),
        "latest_run_count": int(source.get("latest_run_count") or 0),
        "source_snapshot_identity_sha256": source_identity,
        "restored_snapshot_identity_sha256": restored_identity,
    }


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


def _connect(
    runtime: dict[str, Any],
    role: str,
    *,
    port: int | None = None,
    host: str | None = None,
    tls_required: bool = True,
) -> Any:
    import psycopg

    username, password = _password(runtime, role)
    connection_options: dict[str, Any] = {
        "host": host or runtime["host"],
        "port": int(port or runtime["port"]),
        "dbname": runtime["dbname"],
        "user": username,
        "password": password,
        "sslmode": runtime["sslmode"] if tls_required else "disable",
        "connect_timeout": 5,
        "autocommit": True,
    }
    if tls_required:
        connection_options["sslrootcert"] = runtime["sslrootcert"]
    return psycopg.connect(**connection_options)


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


def _verify_base_backup(bin_dir: Path, base_backup: Path) -> None:
    manifest = base_backup / "backup_manifest"
    if not manifest.is_file():
        raise ProductionRecoveryError("base backup has no PostgreSQL backup manifest")
    # Required WAL is copied, hashed, and replayed separately from the exact
    # recovery set.  Here PostgreSQL validates every base-backup file against
    # its native manifest without looking for WAL inside the plain backup.
    _run(
        [
            str(_tool(bin_dir, "pg_verifybackup")),
            "--exit-on-error",
            "--quiet",
            "--no-parse-wal",
            str(base_backup),
        ]
    )


def _pg_ctl(bin_dir: Path, data_dir: Path, action: str) -> None:
    command = [str(_tool(bin_dir, "pg_ctl")), "-D", str(data_dir), "-w"]
    log_path = data_dir.parent / "restore-postgresql.log"
    if action == "start":
        command += ["-l", str(log_path), "start"]
    else:
        command += ["-m", "fast", "stop"]
    env = os.environ.copy()
    env.pop("PGSERVICE", None)
    env.pop("PGPASSFILE", None)
    env.pop("PYTHONPATH", None)
    # pg_ctl on Windows launches postgres through cmd.exe.  Captured stdout or
    # stderr pipe handles can remain inherited by the server after pg_ctl has
    # exited, causing subprocess.run(..., capture_output=True) to wait forever.
    # The dedicated restore log is the evidence sink; child stdio is therefore
    # deliberately detached from Python pipes.
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            check=False,
            timeout=90,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProductionRecoveryError(
            f"pg_ctl.exe {action} timed out; restore log sha256="
            f"{sha256_file(log_path) if log_path.is_file() else 'missing'}"
        ) from exc
    if result.returncode != 0:
        raise ProductionRecoveryError(
            f"pg_ctl.exe {action} exited with {result.returncode}; restore log sha256="
            f"{sha256_file(log_path) if log_path.is_file() else 'missing'}"
        )


def _system_identifier(bin_dir: Path, data_dir: Path) -> str:
    output = _run([str(_tool(bin_dir, "pg_controldata")), str(data_dir)]).stdout
    # pg_controldata localizes field labels on Windows.  The cluster system
    # identifier itself is an unsigned 64-bit decimal value and is the only
    # colon-delimited 16--22 digit value in supported pg_controldata output.
    # Parse the stable value shape instead of assuming an English locale, but
    # fail closed if output is absent or unexpectedly ambiguous.
    candidates: list[str] = []
    for line in output.splitlines():
        if ":" not in line:
            continue
        value = line.rsplit(":", 1)[1].strip()
        if re.fullmatch(r"\d{16,22}", value):
            candidates.append(value)
    unique = sorted(set(candidates))
    if len(unique) == 1:
        return unique[0]
    if not unique:
        raise ProductionRecoveryError(
            "pg_controldata did not expose a locale-independent system identifier"
        )
    raise ProductionRecoveryError(
        "pg_controldata exposed ambiguous system identifier candidates"
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _configure_local_restore(
    *, restore_data: Path, wal_source: Path, port: int, target_lsn: str
) -> None:
    """Fence the disposable whole-restore instance to local, non-TLS access.

    A physical backup retains production TLS paths.  Reusing those paths makes
    the restore depend on the production private key and its NetworkService
    ACL.  The restore is an ephemeral loopback-only verification instance, so
    it receives an explicit local SCRAM HBA and never reads or copies the
    production private key.
    """

    # PostgreSQL substitutes %f/%p and then runs restore_command through the
    # Windows command processor.  cmd.exe's built-in ``copy`` does not accept
    # ``D:/...`` source paths reliably, so preserve native backslashes.  GUC
    # quoted strings require each backslash to be escaped in the config file;
    # the effective command therefore receives one native backslash.
    wal_template = str(wal_source.resolve() / "%f")
    restore_command = f'copy /Y "{wal_template}" "%p"'
    restore_command_config = restore_command.replace("\\", "\\\\").replace("'", "''")

    restore_lines = [
        "listen_addresses = '127.0.0.1'",
        f"port = {port}",
        "ssl = off",
        "archive_mode = off",
        # Do not let the disposable instance inherit the production absolute
        # log_directory.  pg_ctl's dedicated restore log remains the only
        # output sink for this isolated process.
        "logging_collector = off",
        f"restore_command = '{restore_command_config}'",
        f"recovery_target_lsn = '{target_lsn}'",
        "recovery_target_action = 'promote'",
    ]
    with (restore_data / "postgresql.auto.conf").open("a", encoding="utf-8") as handle:
        handle.write("\n# Stage 4 exact recovery-set restore\n")
        handle.write("\n".join(restore_lines) + "\n")
    (restore_data / "pg_hba.conf").write_text(
        "# Stage 4 disposable loopback restore only\n"
        "host all all 127.0.0.1/32 scram-sha-256\n",
        encoding="ascii",
    )


def _wait_for_recovery_target(
    connection: Any, target_lsn: str, timeout: float = 60.0
) -> dict[str, Any]:
    """Wait for target replay and promotion, not merely hot-standby readiness."""

    deadline = time.monotonic() + timeout
    last_status: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        row = connection.execute(
            """
            SELECT pg_is_in_recovery(),
                   pg_last_wal_replay_lsn()::text,
                   coalesce(pg_last_wal_replay_lsn() >= %s::pg_lsn, false)
            """,
            (target_lsn,),
        ).fetchone()
        last_status = {
            "in_recovery": bool(row[0]),
            "replayed_lsn": str(row[1]) if row[1] is not None else None,
            "target_lsn_reached": bool(row[2]),
        }
        if not last_status["in_recovery"]:
            if not last_status["target_lsn_reached"]:
                raise ProductionRecoveryError(
                    "restore promoted before reaching the approved target LSN"
                )
            return last_status
        time.sleep(0.25)
    raise ProductionRecoveryError(
        "restore did not reach and promote at the approved target LSN within "
        f"{timeout:.0f}s; last_status={last_status}"
    )


def _authority_snapshot(row: Any) -> dict[str, Any]:
    try:
        return authority_snapshot(row, cutover_unit="user_content_notes")
    except AuthorityControlError as exc:
        raise ProductionRecoveryError(str(exc)) from exc


def _read_authority_snapshot(connection: Any) -> dict[str, Any]:
    try:
        return read_authority_snapshots(
            connection, required_units=("user_content_notes",)
        )["user_content_notes"]
    except AuthorityControlError as exc:
        raise ProductionRecoveryError(str(exc)) from exc


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
    required_authority_units: tuple[str, ...] = ("user_content_notes",),
) -> dict[str, Any]:
    runtime = _load_json(runtime_path)
    if runtime.get("schema_version") != "honghu.postgresql_production_runtime.v1":
        raise ProductionRecoveryError("unsupported production runtime schema")
    if runtime.get("environment_id") != "production":
        raise ProductionRecoveryError("recovery source is not production-scoped")
    if runtime.get("application_commit_sha") != commit_sha:
        raise ProductionRecoveryError("runtime belongs to another application commit")
    try:
        static_default_route = tracked_static_default_route(runtime)
    except RuntimeContractError as exc:
        raise ProductionRecoveryError(str(exc)) from exc
    if len(commit_sha) != 40:
        raise ProductionRecoveryError("full application commit SHA is required")
    required_authority_units = tuple(dict.fromkeys(required_authority_units))
    if not required_authority_units or any(
        not str(unit).strip() for unit in required_authority_units
    ):
        raise ProductionRecoveryError("at least one authority unit is required")
    task_manifest = _load_json(
        repo_root / "config" / "operations" / "production_tasks.json"
    )
    expected_task_ids = tuple(
        sorted(
            str(item.get("task_id") or "")
            for item in (task_manifest.get("tasks") or ())
            if isinstance(item, dict)
        )
    )
    if (
        task_manifest.get("schema_version")
        != "honghu.production_task_manifest.v1"
        or len(expected_task_ids) != 10
        or len(set(expected_task_ids)) != 10
        or any(not value for value in expected_task_ids)
    ):
        raise ProductionRecoveryError(
            "exact release has no reviewed ten-task manifest"
        )
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
    _verify_base_backup(bin_dir, source_base)

    sentinel_id = f"stage4-production-recovery:{uuid.uuid4().hex}"
    with _connect(runtime, "migration") as connection:
        connection.execute(
            "INSERT INTO operations.bootstrap_recovery_sentinel(operation_id) VALUES (%s)",
            (sentinel_id,),
        )
        try:
            source_authorities = read_authority_snapshots(
                connection, required_units=required_authority_units
            )
        except AuthorityControlError as exc:
            raise ProductionRecoveryError(str(exc)) from exc
        source_task_checkpoints = read_task_checkpoint_snapshot(
            connection, expected_task_ids=expected_task_ids
        )
        target_lsn, durable_at, required_wal, wal_segment_size = connection.execute(
            """
            SELECT pg_current_wal_flush_lsn()::text,
                   to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
                   pg_walfile_name(pg_current_wal_flush_lsn()),
                   pg_size_bytes(current_setting('wal_segment_size'))
            """
        ).fetchone()
    # WAL rotation is an operational backup privilege, not a schema-migration
    # privilege.  Keeping it on the dedicated backup role prevents the
    # migration writer from acquiring a server-wide WAL control capability.
    with _connect(runtime, "backup") as backup_connection:
        backup_connection.execute("SELECT pg_switch_wal()")
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
    # build_recovery_set returns only after the off-VM copy has passed a full
    # exact-file, per-artifact hash and storage-identity verification.  Reuse
    # that verified manifest here; the physical restore below must still read
    # exclusively from this recovery set and prove the post-backup sentinel.
    verified = manifest

    restore_parent = install_root / "restore-tests" / run_id
    restore_data = restore_parent / "data"
    restore_parent.mkdir(parents=True, exist_ok=False)
    assert_restore_sources(destination, destination / "base_backup", destination / "wal")
    shutil.copytree(destination / "base_backup", restore_data)
    restore_port = int(runtime["port"]) + 1
    _configure_local_restore(
        restore_data=restore_data,
        wal_source=destination / "wal",
        port=restore_port,
        target_lsn=str(target_lsn),
    )
    (restore_data / "recovery.signal").touch()
    started = time.monotonic()
    restore_started = False
    try:
        _pg_ctl(bin_dir, restore_data, "start")
        restore_started = True
        with _connect(
            runtime,
            "migration",
            host="127.0.0.1",
            port=restore_port,
            tls_required=False,
        ) as restored:
            promotion = _wait_for_recovery_target(restored, str(target_lsn))
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
                "promotion": promotion,
            }
            try:
                restored_authorities = read_authority_snapshots(
                    restored, required_units=source_authorities
                )
            except AuthorityControlError as exc:
                raise ProductionRecoveryError(str(exc)) from exc
            restored_task_checkpoints = read_task_checkpoint_snapshot(
                restored, expected_task_ids=expected_task_ids
            )
    finally:
        if restore_started:
            _pg_ctl(bin_dir, restore_data, "stop")
    elapsed = time.monotonic() - started
    measurement = measured_recovery(
        target=target, recovered=recovered, restore_elapsed_seconds=elapsed
    )
    if restored_authorities != source_authorities:
        raise ProductionRecoveryError(
            "restored authority control does not match the durable source snapshot"
        )
    task_checkpoint_restore = verify_task_checkpoint_restore(
        source_task_checkpoints, restored_task_checkpoints
    )
    retention = (
        enforce_validated_recovery_retention(
            destination.parent,
            current=destination,
            keep=2,
            current_verified_manifest=verified,
        )
        if require_off_vm
        else {
            "policy": "engineering-local-no-off-vm-retention",
            "keep": None,
            "retained": [destination.name],
            "deleted": [],
            "unvalidated_not_counted_or_deleted": [],
        }
    )
    result_core = {
        "schema_version": "honghu.stage4_production_recovery.v2",
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
        "authority_snapshots": source_authorities,
        "task_checkpoint_restore": task_checkpoint_restore,
        "task_checkpoint_snapshot": source_task_checkpoints,
        "tracked_static_default_route": static_default_route,
        "live_authoritative_backends": {
            unit: snapshot["authoritative_backend"]
            for unit, snapshot in source_authorities.items()
        },
        "formal_business_units": sorted(
            unit
            for unit, snapshot in source_authorities.items()
            if snapshot["state"] in {"S3", "S4"}
        ),
        "side_domain_restore": {
            "status": "pass",
            "method": "physical side instance; user_content/operations/audit queried without production mutation",
        },
        "off_vm_verified": bool(require_off_vm),
        "validated_recovery_retention": retention,
        "formal_business_data_written": any(
            snapshot["state"] in {"S3", "S4"}
            for snapshot in source_authorities.values()
        ),
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
    parser.add_argument(
        "--required-authority-unit",
        action="append",
        dest="required_authority_units",
    )
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
        required_authority_units=tuple(
            args.required_authority_units or ("user_content_notes",)
        ),
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
