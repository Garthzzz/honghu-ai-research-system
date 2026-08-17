from __future__ import annotations

"""Fail-closed verification for the unique-runner enable evidence."""

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.operations.task_manifest import TaskManifest, load_task_manifest
from tools.operations.recovery_metrics import RecoveryMetricError, parse_utc


SHA256 = re.compile(r"^[0-9a-f]{64}$")


class TaskEnableEvidenceError(RuntimeError):
    pass


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaskEnableEvidenceError(f"evidence is unreadable: {path.name}") from exc
    if not isinstance(value, dict):
        raise TaskEnableEvidenceError(f"evidence is not an object: {path.name}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalized_text_sha256(path: Path) -> str:
    """Hash script source independent of a Git checkout's CRLF policy."""
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _checked_at(value: Any) -> datetime:
    try:
        observed = parse_utc(str(value), field="local-disabled checked_at")
    except RecoveryMetricError as exc:
        raise TaskEnableEvidenceError("local-disabled checked_at is invalid") from exc
    return observed


def verify_local_disabled_evidence(
    manifest: TaskManifest,
    evidence_path: Path,
    *,
    collector_path: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    evidence = _json(evidence_path)
    if evidence.get("schema_version") != "honghu.local_task_disabled_evidence.v2":
        raise TaskEnableEvidenceError("local-disabled evidence schema is obsolete")
    observed_at = _checked_at(evidence.get("checked_at"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age = (current - observed_at).total_seconds()
    if age < -60 or age > manifest.local_disabled_evidence_max_age_seconds:
        raise TaskEnableEvidenceError("local-disabled evidence is stale or future-dated")
    if str(evidence.get("source_host") or "").upper() != manifest.legacy_runner_host:
        raise TaskEnableEvidenceError("local-disabled source host is not trusted")
    if (
        str(evidence.get("source_host_identity_sha256") or "").lower()
        != manifest.legacy_runner_host_identity_sha256
    ):
        raise TaskEnableEvidenceError("local-disabled source host identity differs")
    if evidence.get("machine_guid_recorded") is not False:
        raise TaskEnableEvidenceError("local-disabled evidence exposes host source material")
    if str(evidence.get("manifest_sha256") or "").lower() != manifest.sha256:
        raise TaskEnableEvidenceError("local-disabled evidence uses another task manifest")
    if (
        str(evidence.get("collector_sha256") or "").lower()
        != _normalized_text_sha256(collector_path)
    ):
        raise TaskEnableEvidenceError("local-disabled collector identity differs")
    if evidence.get("secrets_recorded") is not False:
        raise TaskEnableEvidenceError("local-disabled evidence secret boundary is invalid")

    tasks = evidence.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != len(manifest.tasks):
        raise TaskEnableEvidenceError("local-disabled evidence does not contain seven tasks")
    indexed: dict[str, dict[str, Any]] = {}
    for item in tasks:
        if not isinstance(item, dict):
            raise TaskEnableEvidenceError("local-disabled task evidence is malformed")
        task_id = str(item.get("task_id") or "")
        if task_id in indexed:
            raise TaskEnableEvidenceError("local-disabled task identity is duplicated")
        indexed[task_id] = item
    if set(indexed) != set(manifest.tasks):
        raise TaskEnableEvidenceError("local-disabled task identity set differs")
    for task_id, definition in manifest.tasks.items():
        item = indexed[task_id]
        observed_sha = str(item.get("definition_sha256") or "").lower()
        expected_sha = str(item.get("expected_definition_sha256") or "").lower()
        if (
            item.get("present") is not True
            or item.get("enabled") is not False
            or item.get("state") != "Disabled"
            or item.get("principal") != definition.legacy_principal
            or not SHA256.fullmatch(observed_sha)
            or observed_sha != definition.legacy_definition_sha256
            or expected_sha != definition.legacy_definition_sha256
            or item.get("definition_matches_manifest") is not True
        ):
            raise TaskEnableEvidenceError(
                f"legacy task is not the reviewed disabled definition: {task_id}"
            )
    if (
        evidence.get("all_present") is not True
        or evidence.get("all_disabled") is not True
        or evidence.get("all_definitions_match") is not True
    ):
        raise TaskEnableEvidenceError("local-disabled aggregate decision is not verified")
    process_count = evidence.get("legacy_runner_process_count")
    processes = evidence.get("legacy_runner_processes")
    if process_count != 0 or not isinstance(processes, list) or processes:
        raise TaskEnableEvidenceError("a legacy runner process may still be active")
    return {
        "source_host": manifest.legacy_runner_host,
        "checked_at": observed_at.isoformat(),
        "age_seconds": round(age, 3),
        "task_count": len(indexed),
        "legacy_runner_process_count": 0,
        "verified": True,
    }


def verify_trial_evidence(
    manifest: TaskManifest,
    evidence_path: Path,
    *,
    release_manifest_path: Path,
    task_id: str,
) -> dict[str, Any]:
    trial = _json(evidence_path)
    release = _json(release_manifest_path)
    commit = str(release.get("commit_sha") or "").lower()
    checkpoint = str(trial.get("business_checkpoint_after_sha256") or "").lower()
    if (
        trial.get("schema_version") != "honghu.production_task_run.v1"
        or trial.get("task_id") != task_id
        or trial.get("status") not in {"succeeded", "skipped"}
        or str(trial.get("application_commit_sha") or "").lower() != commit
        or str(trial.get("manifest_sha256") or "").lower() != manifest.sha256
        or not SHA256.fullmatch(checkpoint)
    ):
        raise TaskEnableEvidenceError("controlled production task trial evidence is invalid")
    return {
        "task_id": task_id,
        "application_commit_sha": commit,
        "manifest_sha256": manifest.sha256,
        "business_checkpoint_after_sha256": checkpoint,
        "verified": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--collector-script", type=Path, required=True)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--local-evidence", type=Path, required=True)
    parser.add_argument("--trial-evidence", type=Path, required=True)
    parser.add_argument("--task", required=True)
    args = parser.parse_args(argv)
    manifest = load_task_manifest(args.manifest)
    if args.task not in manifest.tasks:
        raise TaskEnableEvidenceError("task is not in the reviewed manifest")
    local = verify_local_disabled_evidence(
        manifest, args.local_evidence, collector_path=args.collector_script
    )
    trial = verify_trial_evidence(
        manifest,
        args.trial_evidence,
        release_manifest_path=args.release_manifest,
        task_id=args.task,
    )
    print(json.dumps({"verified": True, "local": local, "trial": trial}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
