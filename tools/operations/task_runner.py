from __future__ import annotations

"""Run one exact-release production task with PostgreSQL ledger and locking."""

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tools.data_platform.postgres_runtime import (
    build_catalog_connection_factory,
    load_postgres_runtime_catalog,
)
from tools.data_platform.routing import Backend, load_environment_authority_matrix
from tools.data_platform.run_domain_operation import trusted_os_principal
from tools.operations.task_business_probe import probe as probe_business_checkpoint
from tools.operations.task_manifest import TaskDefinition, TaskManifest, load_task_manifest


BEIJING = ZoneInfo("Asia/Shanghai")


class TaskRunnerError(RuntimeError):
    pass


def _canonical_sha(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _release_commit(release_dir: Path) -> str:
    payload = json.loads((release_dir / "RELEASE_MANIFEST.json").read_text(encoding="utf-8-sig"))
    value = str(payload.get("commit_sha") or "").lower()
    if len(value) != 40:
        raise TaskRunnerError("immutable release commit identity is missing")
    return value


def logical_window(task: TaskDefinition, now: datetime | None = None) -> str:
    current = (now or datetime.now(BEIJING)).astimezone(BEIJING)
    kind = task.window["kind"]
    if kind == "quarter_hour":
        minutes = int(task.window["minutes"])
        current = current.replace(minute=current.minute - current.minute % minutes, second=0, microsecond=0)
        return current.isoformat(timespec="minutes")
    if kind == "iso_week":
        year, week, _ = current.isocalendar()
        return f"{year}-W{week:02d}"
    if kind == "business_date_slot":
        return f"{current.date().isoformat()}:{task.window['slot']}"
    return current.date().isoformat()


def _most_recent_scheduled_at(task: TaskDefinition, now: datetime) -> datetime:
    """Return the last reviewed trigger time, including overnight/weekend gaps."""

    current = now.astimezone(BEIJING)
    schedule = task.schedule
    kind = schedule["kind"]

    def at(day: datetime, text: str) -> datetime:
        hour, minute = (int(value) for value in text.split(":"))
        return day.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if kind == "weekday_interval":
        candidate = at(current, schedule["end"] if current.time() >= at(current, schedule["end"]).time() else schedule["start"])
        if current.weekday() < 5 and at(current, schedule["start"]) <= current <= at(current, schedule["end"]):
            minutes = int(schedule["minutes"])
            start = at(current, schedule["start"])
            elapsed = int((current - start).total_seconds() // 60)
            return start + timedelta(minutes=(elapsed // minutes) * minutes)
        if current.weekday() < 5 and current < at(current, schedule["start"]):
            candidate = at(current - timedelta(days=1), schedule["end"])
        while candidate.weekday() >= 5:
            candidate -= timedelta(days=1)
        return candidate
    if kind == "weekdays_at":
        candidate = at(current, schedule["at"])
        if current < candidate:
            candidate -= timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate -= timedelta(days=1)
        return candidate
    if kind == "weekly_at":
        weekdays = {"Monday": 0}
        wanted = weekdays[schedule["weekday"]]
        candidate = at(current - timedelta(days=(current.weekday() - wanted) % 7), schedule["at"])
        if candidate > current:
            candidate -= timedelta(days=7)
        return candidate
    raise TaskRunnerError(f"unsupported health schedule: {kind}")


def _validate_authority(task: TaskDefinition) -> None:
    matrix = load_environment_authority_matrix()
    if matrix is None:
        raise TaskRunnerError("production authority matrix is unavailable")
    for unit in task.writer_units:
        route = matrix.route_for(
            unit,
            writer_operation=f"stage5_task:{task.task_id}",
            transaction_boundary="one task-owned operation stream",
        )
        if (
            route.backend is not Backend.POSTGRESQL_PRODUCTION
            or route.authority_state.value not in {"S3", "S4"}
            or route.sqlite_writer_enabled
        ):
            raise TaskRunnerError(f"task writer authority is unsafe: {unit}")


def _operations_connection(catalog_path: Path) -> Any:
    catalog = load_postgres_runtime_catalog(catalog_path)
    return build_catalog_connection_factory(catalog, role="writer_operations_governance")()


def register_definitions(
    manifest: TaskManifest,
    *,
    catalog_path: Path,
    release_dir: Path,
    enabled: bool,
) -> dict[str, Any]:
    commit = _release_commit(release_dir)
    connection = _operations_connection(catalog_path)
    try:
        for task in manifest.tasks.values():
            connection.execute(
                """
                INSERT INTO operations.production_task_definition(
                    task_id,manifest_sha256,application_commit_sha,cutover_unit,
                    writer_units,runner_host,freshness_seconds,enabled
                ) VALUES(%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
                ON CONFLICT(task_id) DO UPDATE SET
                    manifest_sha256=excluded.manifest_sha256,
                    application_commit_sha=excluded.application_commit_sha,
                    cutover_unit=excluded.cutover_unit,
                    writer_units=excluded.writer_units,
                    runner_host=excluded.runner_host,
                    freshness_seconds=excluded.freshness_seconds,
                    enabled=excluded.enabled,
                    definition_revision=operations.production_task_definition.definition_revision+1,
                    updated_at=clock_timestamp()
                """,
                (
                    task.task_id,
                    manifest.sha256,
                    commit,
                    task.cutover_unit,
                    json.dumps(task.writer_units),
                    manifest.runner_host,
                    task.freshness_seconds,
                    enabled,
                ),
            )
        connection.commit()
    finally:
        connection.close()
    return {"task_count": len(manifest.tasks), "manifest_sha256": manifest.sha256, "commit_sha": commit}


def set_definition_enabled(
    manifest: TaskManifest,
    *,
    catalog_path: Path,
    release_dir: Path,
    task_id: str,
    enabled: bool,
) -> dict[str, Any]:
    if task_id not in manifest.tasks:
        raise TaskRunnerError("task definition state change requires a reviewed task")
    commit = _release_commit(release_dir)
    connection = _operations_connection(catalog_path)
    try:
        observed = connection.execute(
            "SELECT manifest_sha256,application_commit_sha,runner_host FROM operations.production_task_definition WHERE task_id=%s",
            (task_id,),
        ).fetchone()
        if observed != (manifest.sha256, commit, manifest.runner_host):
            raise TaskRunnerError("task definition identity does not match exact release")
        connection.execute(
            """UPDATE operations.production_task_definition
                  SET enabled=%s,definition_revision=definition_revision+1,
                      updated_at=clock_timestamp()
                WHERE task_id=%s""",
            (enabled, task_id),
        )
        connection.commit()
    finally:
        connection.close()
    return {
        "schema_version": "honghu.production_task_definition_control.v1",
        "task_id": task_id,
        "enabled": enabled,
        "manifest_sha256": manifest.sha256,
        "application_commit_sha": commit,
        "runner_host": manifest.runner_host,
    }


def _classify(returncode: int, timed_out: bool) -> tuple[str, str | None]:
    if timed_out:
        return "failed", "timeout"
    if returncode == 0:
        return "succeeded", None
    if returncode == 75:
        return "deferred", "resource_lock_deferred"
    if returncode == 2:
        return "failed", "producer_or_reconciliation_failure"
    if returncode in {70, 71, 72, 73, 74}:
        return "failed", "software_or_contract_failure"
    return "failed", "unclassified_nonzero_exit"


def _isolated_child_command(
    *,
    release_dir: Path,
    site_packages: Path,
    task: TaskDefinition,
) -> list[str]:
    """Build an import-isolated, bytecode-free command bound to one release.

    Scheduled tasks must not inherit a coincidental working-directory import or
    the bootstrap interpreter's ambient site-packages.  ``direct_candidate`` is
    the same narrow bootstrap already exercised by immutable Viewer releases.
    """
    bootstrap = (release_dir / "tools" / "release" / "direct_candidate.py").resolve()
    if not bootstrap.is_file():
        raise TaskRunnerError("immutable release bootstrap is missing")
    resolved_site_packages = site_packages.resolve()
    if not resolved_site_packages.is_dir():
        raise TaskRunnerError("locked site-packages directory is missing")
    if len(task.command) < 2 or task.command[0] != "-m":
        raise TaskRunnerError("task command is not a reviewed Python module invocation")
    return [
        sys.executable,
        "-I",
        "-B",
        "-S",
        str(bootstrap),
        "--site-packages",
        str(resolved_site_packages),
        "--module",
        "tools.operations.task_child",
        "--task-module",
        task.command[1],
        "--",
        *task.command[2:],
    ]


def run_task(
    manifest: TaskManifest,
    task: TaskDefinition,
    *,
    catalog_path: Path,
    registry_path: Path,
    release_dir: Path,
    runtime_dir: Path,
    data_root: Path,
    content_root: Path,
    site_packages: Path,
    logical_window_value: str | None = None,
    allow_disabled: bool = False,
) -> dict[str, Any]:
    host = socket.gethostname().upper()
    if host != manifest.runner_host:
        raise TaskRunnerError(f"task manifest is bound to {manifest.runner_host}, not {host}")
    commit = _release_commit(release_dir)
    os.environ.update({
        "HONGHU_POSTGRES_RUNTIME_CONFIG": str(catalog_path.resolve()),
        "HONGHU_CUTOVER_UNIT_REGISTRY": str(registry_path.resolve()),
        "HONGHU_DATA_ROOT": str(data_root.resolve()),
        "HONGHU_CONTENT_ROOT": str(content_root.resolve()),
        "HONGHU_STATE_ROOT": str(runtime_dir.resolve()),
    })
    _validate_authority(task)
    window = logical_window_value or logical_window(task)
    operation_id = f"stage5:{task.task_id}:{window}"
    operation_hash = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()
    principal = trusted_os_principal()
    connection = _operations_connection(catalog_path)
    lock_key = f"honghu:production-task:{task.task_id}"
    attempt = 0
    log_dir = runtime_dir.resolve() / "task_logs" / task.task_id
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        locked = connection.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s,0))", (lock_key,)
        ).fetchone()[0]
        if not locked:
            return {"status": "deferred", "reason": "another runner holds task lock", "returncode": 75}
        definition = connection.execute(
            "SELECT manifest_sha256,application_commit_sha,runner_host,enabled FROM operations.production_task_definition WHERE task_id=%s",
            (task.task_id,),
        ).fetchone()
        if definition is None:
            raise TaskRunnerError("task definition is not registered")
        if tuple(str(value) for value in definition[:3]) != (manifest.sha256, commit, manifest.runner_host):
            raise TaskRunnerError("task definition identity does not match exact release")
        if not bool(definition[3]) and not allow_disabled:
            raise TaskRunnerError("task definition is disabled")
        prior = connection.execute(
            """SELECT status,run_attempt,operation_id_sha256,manifest_sha256,
                      application_commit_sha,business_checkpoint_before,
                      business_checkpoint_after
                 FROM operations.production_task_run
                WHERE task_id=%s AND logical_window=%s
                ORDER BY run_attempt DESC LIMIT 1""",
            (task.task_id, window),
        ).fetchone()
        if prior and str(prior[0]) == "succeeded":
            before = dict(prior[5] or {})
            after = dict(prior[6] or {})
            return {
                "schema_version": "honghu.production_task_run.v1",
                "task_id": task.task_id,
                "logical_window": window,
                "attempt": int(prior[1]),
                "status": "skipped",
                "reason": "logical window already succeeded",
                "failure_classification": None,
                "returncode": 0,
                "operation_id_sha256": str(prior[2]),
                "manifest_sha256": str(prior[3]),
                # The envelope describes the exact release that performed
                # this idempotent verification.  Preserve the commit that
                # originally completed the window as separate audit data.
                "application_commit_sha": commit,
                "prior_success_application_commit_sha": str(prior[4]),
                "business_checkpoint_before_sha256": before.get("identity_sha256"),
                "business_checkpoint_after_sha256": after.get("identity_sha256"),
            }
        connection.execute(
            "UPDATE operations.production_task_run SET status='abandoned',failure_classification='advisory_lock_released_before_terminal_state',finished_at=clock_timestamp() WHERE task_id=%s AND logical_window=%s AND status='running'",
            (task.task_id, window),
        )
        attempt = int(connection.execute(
            "SELECT coalesce(max(run_attempt),0)+1 FROM operations.production_task_run WHERE task_id=%s AND logical_window=%s",
            (task.task_id, window),
        ).fetchone()[0])
        connection.execute(
            """INSERT INTO operations.production_task_run(
                task_id,logical_window,run_attempt,operation_id_sha256,manifest_sha256,
                application_commit_sha,runner_host,runner_principal,status
            ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'running')""",
            (task.task_id, window, attempt, operation_hash, manifest.sha256, commit, host, principal),
        )
        connection.commit()
        checkpoint_before = probe_business_checkpoint(
            task.task_id,
            window,
            data_root=data_root.resolve(),
        )
        connection.execute(
            """UPDATE operations.production_task_run
                  SET business_checkpoint_before=%s::jsonb
                WHERE task_id=%s AND logical_window=%s AND run_attempt=%s""",
            (
                json.dumps(checkpoint_before, ensure_ascii=False, sort_keys=True),
                task.task_id,
                window,
                attempt,
            ),
        )
        connection.commit()
        stdout_path = log_dir / f"{operation_hash}-{attempt}.stdout.log"
        stderr_path = log_dir / f"{operation_hash}-{attempt}.stderr.log"
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        environment.update({
            "PYTHONDONTWRITEBYTECODE": "1",
            "HONGHU_OPERATION_ID": operation_id,
            "HONGHU_AUDIT_ACTOR": principal,
            "HONGHU_POSTGRES_RUNTIME_CONFIG": str(catalog_path.resolve()),
            "HONGHU_CUTOVER_UNIT_REGISTRY": str(registry_path.resolve()),
            "HONGHU_DATA_ROOT": str(data_root.resolve()),
            "HONGHU_CONTENT_ROOT": str(content_root.resolve()),
            "HONGHU_STATE_ROOT": str(runtime_dir.resolve()),
            "HONGHU_RELEASE_BOOTSTRAP": str(
                (release_dir / "tools" / "release" / "direct_candidate.py").resolve()
            ),
            "HONGHU_LOCKED_SITE_PACKAGES": str(site_packages.resolve()),
        })
        timed_out = False
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                _isolated_child_command(
                    release_dir=release_dir,
                    site_packages=site_packages,
                    task=task,
                ),
                cwd=release_dir,
                env=environment,
                stdout=stdout,
                stderr=stderr,
            )
            deadline = time.monotonic() + task.execution_timeout_seconds
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    process.kill()
                    timed_out = True
                    break
                time.sleep(5)
                connection.execute(
                    "UPDATE operations.production_task_run SET heartbeat_at=clock_timestamp() WHERE task_id=%s AND logical_window=%s AND run_attempt=%s AND status='running'",
                    (task.task_id, window, attempt),
                )
                connection.commit()
            returncode = process.wait()
        status, failure = _classify(returncode, timed_out)
        checkpoint_after = probe_business_checkpoint(
            task.task_id,
            window,
            data_root=data_root.resolve(),
        )
        output_hash = _canonical_sha({
            "stdout": hashlib.sha256(stdout_path.read_bytes()).hexdigest(),
            "stderr": hashlib.sha256(stderr_path.read_bytes()).hexdigest(),
        })
        connection.execute(
            """UPDATE operations.production_task_run SET status=%s,
                failure_classification=%s,return_code=%s,output_tail_sha256=%s,
                business_checkpoint_after=%s::jsonb,
                heartbeat_at=clock_timestamp(),finished_at=clock_timestamp()
                WHERE task_id=%s AND logical_window=%s AND run_attempt=%s""",
            (
                status,
                failure,
                returncode,
                output_hash,
                json.dumps(checkpoint_after, ensure_ascii=False, sort_keys=True),
                task.task_id,
                window,
                attempt,
            ),
        )
        connection.commit()
        return {
            "schema_version": "honghu.production_task_run.v1",
            "task_id": task.task_id,
            "logical_window": window,
            "attempt": attempt,
            "status": status,
            "failure_classification": failure,
            "returncode": returncode,
            "operation_id_sha256": operation_hash,
            "manifest_sha256": manifest.sha256,
            "application_commit_sha": commit,
            "business_checkpoint_before_sha256": checkpoint_before["identity_sha256"],
            "business_checkpoint_after_sha256": checkpoint_after["identity_sha256"],
        }
    except Exception:
        if attempt:
            try:
                connection.execute(
                    "UPDATE operations.production_task_run SET status='uncertain',failure_classification='runner_control_plane_failure',heartbeat_at=clock_timestamp(),finished_at=clock_timestamp() WHERE task_id=%s AND logical_window=%s AND run_attempt=%s AND status='running'",
                    (task.task_id, window, attempt),
                )
                connection.commit()
            except Exception:
                pass
        raise
    finally:
        try:
            connection.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (lock_key,))
            connection.commit()
        except Exception:
            pass
        connection.close()


def health(
    manifest: TaskManifest,
    catalog_path: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    connection = _operations_connection(catalog_path)
    try:
        rows = connection.execute(
            """SELECT task_id,manifest_sha256,application_commit_sha,runner_host,
                      freshness_seconds,enabled,logical_window,status,failure_classification,
                      return_code,finished_at,business_checkpoint_before,
                      business_checkpoint_after,last_success_at,seconds_since_last_success
                 FROM operations.production_task_health_v1 ORDER BY task_id"""
        ).fetchall()
    finally:
        connection.close()
    observed = []
    observed_now = (now or datetime.now(timezone.utc)).astimezone(BEIJING)
    for row in rows:
        item = dict(zip(
            ("task_id","manifest_sha256","application_commit_sha","runner_host",
             "freshness_seconds","enabled","logical_window","status","failure_classification",
             "return_code","finished_at","business_checkpoint_before",
             "business_checkpoint_after","last_success_at","seconds_since_last_success"), row
        ))
        item["identity_ok"] = item["task_id"] in manifest.tasks and item["manifest_sha256"] == manifest.sha256
        last_success = item["last_success_at"]
        if isinstance(last_success, str):
            last_success = datetime.fromisoformat(last_success.replace("Z", "+00:00"))
        definition = manifest.tasks.get(item["task_id"])
        if definition is None:
            item["expected_trigger_at"] = None
            item["expected_completion_deadline"] = None
            item["seconds_since_last_success"] = None
            item["pipeline_healthy"] = False
            item["data_fresh"] = False
            item["business_checkpoint_observed"] = bool(item["business_checkpoint_after"])
            observed.append(item)
            continue
        expected_at = _most_recent_scheduled_at(definition, observed_now)
        age = (
            (observed_now - last_success.astimezone(BEIJING)).total_seconds()
            if last_success is not None
            else None
        )
        item["expected_trigger_at"] = expected_at.isoformat()
        item["expected_completion_deadline"] = (
            expected_at + timedelta(seconds=definition.execution_timeout_seconds)
        ).isoformat()
        item["seconds_since_last_success"] = int(age) if age is not None else None
        item["pipeline_healthy"] = item["status"] not in {
            "failed", "abandoned", "uncertain"
        }
        item["data_fresh"] = bool(
            item["enabled"] and item["pipeline_healthy"]
            and last_success is not None
            and (
                last_success.astimezone(BEIJING) >= expected_at
                or observed_now <= expected_at + timedelta(
                    seconds=definition.execution_timeout_seconds
                )
            )
        )
        item["business_checkpoint_observed"] = bool(item["business_checkpoint_after"])
        observed.append(item)
    return {
        "schema_version": "honghu.production_task_health.v1",
        "process_alive_is_not_data_freshness": True,
        "task_count": len(observed),
        "all_identity_ok": len(observed) == 7 and all(item["identity_ok"] for item in observed),
        "all_enabled_and_fresh": len(observed) == 7 and all(
            item["data_fresh"] and item["business_checkpoint_observed"]
            for item in observed
        ),
        "tasks": observed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("register", "set-definition", "run", "health"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--postgres-runtime-catalog", type=Path, required=True)
    parser.add_argument("--cutover-unit-registry", type=Path)
    parser.add_argument("--release-dir", type=Path)
    parser.add_argument("--runtime-dir", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--content-root", type=Path)
    parser.add_argument("--site-packages", type=Path)
    parser.add_argument("--task")
    parser.add_argument("--logical-window")
    parser.add_argument("--enabled", action="store_true")
    parser.add_argument("--allow-disabled", action="store_true")
    args = parser.parse_args(argv)
    manifest = load_task_manifest(args.manifest)
    if args.command == "health":
        result = health(manifest, args.postgres_runtime_catalog)
    elif args.command == "register":
        if args.release_dir is None:
            parser.error("register requires --release-dir")
        result = register_definitions(
            manifest, catalog_path=args.postgres_runtime_catalog,
            release_dir=args.release_dir, enabled=args.enabled,
        )
    elif args.command == "set-definition":
        if args.release_dir is None or not args.task:
            parser.error("set-definition requires --release-dir and --task")
        result = set_definition_enabled(
            manifest,
            catalog_path=args.postgres_runtime_catalog,
            release_dir=args.release_dir,
            task_id=args.task,
            enabled=args.enabled,
        )
    else:
        required = (
            args.cutover_unit_registry, args.release_dir, args.runtime_dir,
            args.data_root, args.content_root, args.site_packages,
        )
        if not args.task or args.task not in manifest.tasks or any(value is None for value in required):
            parser.error("run requires a known task and all runtime paths")
        result = run_task(
            manifest, manifest.tasks[args.task], catalog_path=args.postgres_runtime_catalog,
            registry_path=args.cutover_unit_registry, release_dir=args.release_dir,
            runtime_dir=args.runtime_dir, data_root=args.data_root, content_root=args.content_root,
            site_packages=args.site_packages,
            logical_window_value=args.logical_window, allow_disabled=args.allow_disabled,
        )
    print(json.dumps(result, ensure_ascii=False, default=str, sort_keys=True))
    return int(result.get("returncode") or 0)


if __name__ == "__main__":
    raise SystemExit(main())
