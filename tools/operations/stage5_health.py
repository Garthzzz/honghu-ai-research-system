from __future__ import annotations

"""Fail-closed Stage 5 production health aggregator.

The individual probes remain owned by their existing subsystems. This module
only combines their machine-readable results and deliberately keeps service
reachability separate from task/data freshness. It does not deliver external
alerts: a blocked result is expressed as JSON plus exit status 2.
"""

import argparse
import hashlib
import json
import os
import shutil
import urllib.request
from urllib.parse import urlsplit
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from tools.data_platform.postgres_runtime import (
    build_catalog_connection_factory,
    load_postgres_runtime_catalog,
)
from tools.data_platform.routing import (
    Backend,
    PRODUCTION_CUTOVER_UNITS,
    load_authority_matrix,
)
from tools.migration.stage4_json_io import read_json
from tools.operations.recovery_health import evaluate_recovery_health
from tools.operations.task_manifest import load_task_manifest
from tools.operations.task_runner import health as task_health
from tools.release.manager import verify_release


class Stage5HealthError(ValueError):
    pass


def _canonical_evidence_value(value: Any) -> Any:
    """Normalize probe values without falling back to secret-prone ``str``."""

    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise Stage5HealthError("health evidence timestamp has no timezone")
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_evidence_value(child)
            for key, child in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_evidence_value(child) for child in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise Stage5HealthError(
        f"unsupported health evidence value: {type(value).__name__}"
    )


def _probe_failure(name: str, exc: BaseException) -> dict[str, Any]:
    # Exception text can contain host, account or filesystem details. The
    # machine-local operator can inspect subsystem logs without copying those
    # details into a reusable health/alert document.
    return {
        "component": name,
        "ok": False,
        "error_code": "probe_failed",
        "error_type": type(exc).__name__,
    }


def probe_viewer(url: str, *, expected_commit_sha: str, timeout_seconds: float) -> dict[str, Any]:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or (parsed.scheme, parsed.port) not in {("http", 8080), ("https", 8443)}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != "/api/health"
    ):
        raise Stage5HealthError(
            "Viewer health probe must use the reviewed loopback health endpoint"
        )
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        status_code = int(response.status)
        encoded = response.read(1024 * 1024 + 1)
        if len(encoded) > 1024 * 1024:
            raise Stage5HealthError("Viewer health payload exceeds one MiB")
        payload = json.loads(encoded.decode("utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise Stage5HealthError("Viewer health payload is not an object")
    release = payload.get("release") if isinstance(payload.get("release"), Mapping) else {}
    observed_commit = str(release.get("commit_sha") or "").lower()
    manifest_sha256 = str(release.get("manifest_sha256") or "").lower()
    reachable = 200 <= status_code < 300
    return {
        "component": "viewer",
        "ok": bool(
            reachable
            and payload.get("ok") is True
            and observed_commit == expected_commit_sha
            and len(manifest_sha256) == 64
            and all(character in "0123456789abcdef" for character in manifest_sha256)
        ),
        "reachable": reachable,
        "http_status": status_code,
        "application_ok": payload.get("ok") is True,
        "viewer_mode": payload.get("viewer_mode"),
        "observed_commit_sha": observed_commit or None,
        "expected_commit_sha": expected_commit_sha,
        "manifest_sha256": manifest_sha256 or None,
    }


def probe_postgres_authority(
    catalog_path: Path,
    registry_path: Path,
    *,
    expected_commit_sha: str,
) -> dict[str, Any]:
    catalog = load_postgres_runtime_catalog(catalog_path)
    connection_factory = build_catalog_connection_factory(catalog, role="reader")
    connection = connection_factory()
    try:
        database, current_user, ssl_active, in_recovery = connection.execute(
            "SELECT current_database(),current_user,"
            "coalesce((SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()),false),"
            "pg_is_in_recovery()"
        ).fetchone()
    finally:
        connection.close()
    registry, matrix = load_authority_matrix(registry_path, connection_factory)
    authority = matrix.health_payload()
    expected_units = set(PRODUCTION_CUTOVER_UNITS)
    observed_units = set(authority)
    safe_units = {
        unit
        for unit, route in matrix.routes.items()
        if route.backend is Backend.POSTGRESQL_PRODUCTION
        and route.authority_state.value in {"S3", "S4"}
        and not route.sqlite_writer_enabled
        and bool(route.writer_identity)
    }
    authority_ok = observed_units == expected_units and safe_units == expected_units
    runtime_commit = catalog.application_commit_sha.lower()
    return {
        "component": "postgresql_authority",
        "ok": bool(
            ssl_active is True
            and in_recovery is False
            and authority_ok
            and runtime_commit == expected_commit_sha
        ),
        "reachable": True,
        "database": str(database),
        "current_user": str(current_user),
        "tls_active": ssl_active is True,
        "primary_not_recovery": in_recovery is False,
        "expected_unit_count": len(expected_units),
        "observed_unit_count": len(observed_units),
        "safe_postgresql_authority_unit_count": len(safe_units),
        "missing_units": sorted(expected_units - observed_units),
        "unsafe_units": sorted(expected_units - safe_units),
        "registry_sha256": registry.registry_sha256,
        "authority": authority,
        "runtime_catalog_commit_sha": runtime_commit,
        "expected_application_commit_sha": expected_commit_sha,
        "runtime_catalog_commit_matches_release": runtime_commit == expected_commit_sha,
    }


def probe_task_freshness(
    manifest_path: Path,
    catalog_path: Path,
    *,
    expected_commit_sha: str,
) -> dict[str, Any]:
    manifest = load_task_manifest(manifest_path)
    payload = task_health(manifest, catalog_path)
    tasks = payload.get("tasks") if isinstance(payload.get("tasks"), list) else []
    exact_definition_identity = len(tasks) == 7 and all(
        isinstance(item, Mapping)
        and item.get("manifest_sha256") == manifest.sha256
        and str(item.get("application_commit_sha") or "").lower() == expected_commit_sha
        and str(item.get("runner_host") or "").upper() == manifest.runner_host
        for item in tasks
    )
    return {
        "component": "production_tasks",
        "ok": bool(
            payload["all_identity_ok"]
            and exact_definition_identity
            and payload["all_enabled_and_fresh"]
        ),
        # These jobs are short-lived ticks. Their absence between schedules is
        # not a failure; durable ledger/checkpoint freshness is the health gate.
        "process_model": "short_lived_scheduled_tick",
        "process_alive_required_between_ticks": False,
        "data_fresh": bool(payload["all_enabled_and_fresh"]),
        "exact_definition_identity_ok": exact_definition_identity,
        "expected_application_commit_sha": expected_commit_sha,
        **payload,
    }


def probe_recovery(
    evidence_path: Path,
    *,
    expected_commit_sha: str,
    max_wal_age_seconds: float,
    max_restore_age_seconds: float,
    max_full_scrub_age_seconds: float,
) -> dict[str, Any]:
    evidence = read_json(evidence_path)
    if not isinstance(evidence, Mapping):
        raise Stage5HealthError("recovery evidence root is not an object")
    evidence_sha256 = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    declared_identity = str(evidence.get("identity_sha256") or "").lower()
    identity_core = {
        str(key): value for key, value in evidence.items() if key != "identity_sha256"
    }
    calculated_identity = hashlib.sha256(
        json.dumps(
            identity_core,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if declared_identity != calculated_identity:
        raise Stage5HealthError("recovery evidence identity is invalid")
    recovery_commit = str(evidence.get("application_commit_sha") or "").lower()
    if recovery_commit != expected_commit_sha:
        raise Stage5HealthError("recovery evidence belongs to another release")
    payload = evaluate_recovery_health(
        evidence,
        max_wal_age_seconds=max_wal_age_seconds,
        max_restore_age_seconds=max_restore_age_seconds,
        max_full_scrub_age_seconds=max_full_scrub_age_seconds,
    )
    return {
        "component": "backup_recovery",
        "ok": payload["status"] == "pass",
        "input_evidence_sha256": evidence_sha256,
        "verified_evidence_identity_sha256": calculated_identity,
        "application_commit_sha": recovery_commit,
        **payload,
    }


def probe_release(release_dir: Path, *, expected_commit_sha: str) -> dict[str, Any]:
    manifest = verify_release(release_dir)
    observed_commit = str(manifest.get("commit_sha") or "").lower()
    result = {
        "component": "immutable_release",
        "ok": observed_commit == expected_commit_sha,
        "observed_commit_sha": observed_commit or None,
        "expected_commit_sha": expected_commit_sha,
        "manifest_sha256": manifest.get("manifest_sha256"),
        "file_count": manifest.get("file_count"),
        "content_bytes": manifest.get("content_bytes"),
    }
    return result


def probe_disk_capacity(
    paths: Sequence[Path],
    *,
    min_free_bytes: int,
    min_free_percent: float,
) -> dict[str, Any]:
    observed: list[dict[str, Any]] = []
    for path in paths:
        usage = shutil.disk_usage(path.resolve())
        free_percent = (usage.free / usage.total * 100.0) if usage.total else 0.0
        healthy = usage.free >= min_free_bytes and free_percent >= min_free_percent
        observed.append(
            {
                "path": str(path.resolve()),
                "total_bytes": usage.total,
                "free_bytes": usage.free,
                "free_percent": round(free_percent, 3),
                "healthy": healthy,
            }
        )
    result = {
        "component": "disk_capacity",
        "ok": bool(observed) and all(item["healthy"] for item in observed),
        "minimum_free_bytes": min_free_bytes,
        "minimum_free_percent": min_free_percent,
        "paths": observed,
    }
    return result


def aggregate_stage5_health(
    components: Mapping[str, Mapping[str, Any]],
    *,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    normalized = {
        str(name): _canonical_evidence_value(value)
        for name, value in components.items()
    }
    required = (
        "viewer",
        "postgresql_authority",
        "production_tasks",
        "backup_recovery",
        "immutable_release",
        "disk_capacity",
    )
    missing = [name for name in required if name not in normalized]
    blocked = missing + [
        name
        for name in required
        if name in normalized and normalized[name].get("ok") is not True
    ]
    now = checked_at or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise Stage5HealthError("checked_at must include a timezone")
    viewer = normalized.get("viewer", {})
    postgres = normalized.get("postgresql_authority", {})
    tasks = normalized.get("production_tasks", {})
    release = normalized.get("immutable_release", {})
    viewer_release_binding_ok = bool(
        viewer.get("observed_commit_sha")
        and viewer.get("observed_commit_sha") == release.get("observed_commit_sha")
        and viewer.get("manifest_sha256")
        and viewer.get("manifest_sha256") == release.get("manifest_sha256")
    )
    postgres_release_binding_ok = bool(
        postgres.get("runtime_catalog_commit_sha")
        and postgres.get("runtime_catalog_commit_sha")
        == release.get("observed_commit_sha")
    )
    task_release_binding_ok = bool(tasks.get("exact_definition_identity_ok"))
    recovery = normalized.get("backup_recovery", {})
    recovery_release_binding_ok = bool(
        recovery.get("application_commit_sha")
        and recovery.get("application_commit_sha")
        == release.get("observed_commit_sha")
        and recovery.get("verified_evidence_identity_sha256")
    )
    identity_binding_ok = bool(
        viewer_release_binding_ok
        and postgres_release_binding_ok
        and task_release_binding_ok
        and recovery_release_binding_ok
    )
    if not identity_binding_ok:
        blocked.append("runtime_release_identity_binding")
    result = {
        "schema_version": "honghu.stage5_system_health.v1",
        "checked_at_utc": now.astimezone(timezone.utc).isoformat(),
        "status": "pass" if not blocked else "blocked",
        "process_state": {
            "viewer_reachable": viewer.get("reachable") is True,
            "postgresql_reachable": postgres.get("reachable") is True,
            "task_process_model": tasks.get("process_model"),
            "process_alive_is_not_data_freshness": True,
        },
        "data_freshness": {
            "all_seven_tasks_fresh": tasks.get("data_fresh") is True,
            "task_count": tasks.get("task_count"),
            "gate_independent_of_process_alive": True,
        },
        "blocked_components": sorted(set(blocked)),
        "identity_binding": {
            "all_runtime_components_match_verified_release": identity_binding_ok,
            "viewer_matches_verified_release": viewer_release_binding_ok,
            "postgres_runtime_matches_verified_release": postgres_release_binding_ok,
            "task_definitions_match_verified_release": task_release_binding_ok,
            "recovery_evidence_matches_verified_release": recovery_release_binding_ok,
            "viewer_commit_sha": viewer.get("observed_commit_sha"),
            "release_commit_sha": release.get("observed_commit_sha"),
            "viewer_manifest_sha256": viewer.get("manifest_sha256"),
            "release_manifest_sha256": release.get("manifest_sha256"),
        },
        "components": normalized,
        "alert": {
            "triggered": bool(blocked),
            "delivery_mode": "local_machine_json_and_exit_status_only",
            "external_delivery_configured": False,
            "external_delivery_attempted": False,
        },
    }
    result["identity_sha256"] = hashlib.sha256(
        json.dumps(
            result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    return result


def collect_stage5_health(args: argparse.Namespace) -> dict[str, Any]:
    probes: dict[str, Callable[[], dict[str, Any]]] = {
        "viewer": lambda: probe_viewer(
            args.viewer_health_url,
            expected_commit_sha=args.expected_commit_sha,
            timeout_seconds=args.http_timeout_seconds,
        ),
        "postgresql_authority": lambda: probe_postgres_authority(
            args.postgres_runtime_catalog,
            args.cutover_unit_registry,
            expected_commit_sha=args.expected_commit_sha,
        ),
        "production_tasks": lambda: probe_task_freshness(
            args.task_manifest,
            args.postgres_runtime_catalog,
            expected_commit_sha=args.expected_commit_sha,
        ),
        "backup_recovery": lambda: probe_recovery(
            args.recovery_evidence,
            expected_commit_sha=args.expected_commit_sha,
            max_wal_age_seconds=args.max_wal_age_seconds,
            max_restore_age_seconds=args.max_restore_age_seconds,
            max_full_scrub_age_seconds=args.max_full_scrub_age_seconds,
        ),
        "immutable_release": lambda: probe_release(
            args.release_dir, expected_commit_sha=args.expected_commit_sha
        ),
        "disk_capacity": lambda: probe_disk_capacity(
            args.disk_path,
            min_free_bytes=args.min_free_bytes,
            min_free_percent=args.min_free_percent,
        ),
    }
    components: dict[str, Mapping[str, Any]] = {}
    for name, probe in probes.items():
        try:
            components[name] = probe()
        except Exception as exc:  # later probes still run and remain observable
            components[name] = _probe_failure(name, exc)
    return aggregate_stage5_health(components)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--viewer-health-url", required=True)
    parser.add_argument("--postgres-runtime-catalog", type=Path, required=True)
    parser.add_argument("--cutover-unit-registry", type=Path, required=True)
    parser.add_argument("--task-manifest", type=Path, required=True)
    parser.add_argument("--recovery-evidence", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--expected-commit-sha", required=True)
    parser.add_argument("--disk-path", type=Path, action="append", required=True)
    parser.add_argument("--http-timeout-seconds", type=float, default=5.0)
    parser.add_argument("--max-wal-age-seconds", type=float, required=True)
    parser.add_argument("--max-restore-age-seconds", type=float, required=True)
    parser.add_argument("--max-full-scrub-age-seconds", type=float, default=86400)
    parser.add_argument("--min-free-bytes", type=int, default=5 * 1024**3)
    parser.add_argument("--min-free-percent", type=float, default=10.0)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    expected = str(args.expected_commit_sha).strip().lower()
    if len(expected) != 40 or any(character not in "0123456789abcdef" for character in expected):
        raise Stage5HealthError("expected commit must be a full lowercase Git SHA")
    args.expected_commit_sha = expected
    if (
        args.min_free_bytes < 0
        or not 0 <= args.min_free_percent <= 100
        or not 0 < args.http_timeout_seconds <= 30
        or args.max_wal_age_seconds <= 0
        or args.max_restore_age_seconds <= 0
        or args.max_full_scrub_age_seconds <= 0
    ):
        raise Stage5HealthError("disk thresholds are outside valid bounds")
    release = args.release_dir.resolve()
    recovery_evidence = args.recovery_evidence.resolve()
    if recovery_evidence == release or release in recovery_evidence.parents:
        raise Stage5HealthError("runtime recovery evidence cannot come from the release")
    output = args.output.resolve() if args.output is not None else None
    if output is not None and (output == release or release in output.parents):
        raise Stage5HealthError("health evidence cannot be written into the release")
    result = collect_stage5_health(args)
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(encoded + "\n", encoding="utf-8")
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
    print(encoded)
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
