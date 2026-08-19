from __future__ import annotations

"""Fail-closed verification for the unique-runner enable evidence."""

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from tools.operations.task_manifest import TaskManifest, load_task_manifest
from tools.operations.recovery_metrics import RecoveryMetricError, parse_utc


SHA256 = re.compile(r"^[0-9a-f]{64}$")
VALUATION_TASKS = {
    "IndustryDemo_ValuationMarket_1140",
    "IndustryDemo_ValuationMarket_1510",
    "IndustryDemo_ValuationAI_Monthly",
}
VALUATION_WORKBOOK_SHA256 = "453ded4b67ad53848ffd90ab27ddcad21ba3262d623e3946de613c414091e3e0"
VALUATION_WORKBOOK_SEED_SHA256 = "09907358d4e3ee9751e7196fcd9f27574553b434915bce38af3d7c4175f19e41"
VALUATION_IDENTITY_SEED_SHA256 = "a0f27b5ffd30bda0eddaeb2f39ef6a0e49e98ad9a618f49f378003e4d874fa8f"
VALUATION_MEMBER_CONTRACT = [
    ("紫金矿业", "601899.SH", "上海", "铜资源", "15379", "CNY"),
    ("洛阳钼业", "603993.SH", "上海", "铜资源", "4787", "CNY"),
    ("五矿资源", "1208.HK", "香港", "铜资源", "1085", "HKD"),
    ("藏格矿业", "000408.SZ", "深圳", "铜资源", "1197", "CNY"),
    ("锡业股份", "000960.SZ", "深圳", "锡", "538", "CNY"),
    ("华锡有色", "600301.SH", "上海", "锡", "294", "CNY"),
    ("兴业银锡", "000426.SZ", "深圳", "锡", "958", "CNY"),
]


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
        raise TaskEnableEvidenceError("local-disabled evidence has the wrong task count")
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
        is_new_absent = definition.legacy_principal == "not_applicable_new_task"
        valid_absence = (
            is_new_absent
            and item.get("present") is False
            and item.get("enabled") is False
            and item.get("state") == "Absent"
            and item.get("legacy_absence_expected") is True
            and expected_sha == definition.legacy_definition_sha256
            and item.get("definition_matches_manifest") is True
        )
        valid_disabled = (
            item.get("present") is True
            and item.get("enabled") is False
            and item.get("state") == "Disabled"
            and item.get("principal") == definition.legacy_principal
            and bool(SHA256.fullmatch(observed_sha))
            and observed_sha == definition.legacy_definition_sha256
            and expected_sha == definition.legacy_definition_sha256
            and item.get("definition_matches_manifest") is True
        )
        if not (valid_absence or valid_disabled):
            raise TaskEnableEvidenceError(
                f"legacy task is not the reviewed disabled definition: {task_id}"
            )
    if (
        evidence.get("all_legacy_tasks_safe", evidence.get("all_present")) is not True
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


def verify_valuation_setup_evidence(evidence_path: Path) -> dict[str, Any]:
    evidence = _json(evidence_path)
    if (
        evidence.get("schema_version")
        != "honghu.valuation_tracker.production_setup_evidence.v1"
        or evidence.get("status") != "pass"
        or evidence.get("contract_verified") is not True
        or evidence.get("migration_id") != "0021_valuation_tracker"
        or not SHA256.fullmatch(str(evidence.get("migration_sha256") or "").lower())
        or evidence.get("workbook_sha256") != VALUATION_WORKBOOK_SHA256
        or evidence.get("workbook_seed_sha256") != VALUATION_WORKBOOK_SEED_SHA256
        or evidence.get("identity_seed_sha256") != VALUATION_IDENTITY_SEED_SHA256
    ):
        raise TaskEnableEvidenceError("valuation setup evidence identity is invalid")
    members = evidence.get("members")
    if not isinstance(members, list) or len(members) != len(VALUATION_MEMBER_CONTRACT):
        raise TaskEnableEvidenceError("valuation setup member count is invalid")
    company_ids: set[int] = set()
    security_ids: set[int] = set()
    version_ids: set[int] = set()
    for order, (item, expected) in enumerate(
        zip(members, VALUATION_MEMBER_CONTRACT, strict=True), start=1
    ):
        if not isinstance(item, dict):
            raise TaskEnableEvidenceError("valuation setup member is malformed")
        observed_identity = (
            item.get("name"), item.get("ticker"), item.get("market"), item.get("board"),
            item.get("currency"),
        )
        expected_identity = (expected[0], expected[1], expected[2], expected[3], expected[5])
        try:
            company_id = int(item["company_id"])
            security_id = int(item["security_id"])
            version_id = int(item["researcher_version_id"])
            display_order = int(item["display_order"])
            ceiling = Decimal(str(item["ceiling_value"]))
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise TaskEnableEvidenceError("valuation setup identities are invalid") from exc
        if (
            observed_identity != expected_identity
            or ceiling != Decimal(expected[4])
            or display_order != order
            or min(company_id, security_id, version_id) <= 0
        ):
            raise TaskEnableEvidenceError("valuation setup exact member contract differs")
        company_ids.add(company_id)
        security_ids.add(security_id)
        version_ids.add(version_id)
    if min(len(company_ids), len(security_ids), len(version_ids)) != len(VALUATION_MEMBER_CONTRACT):
        raise TaskEnableEvidenceError("valuation setup identities or versions are duplicated")
    return {
        "workbook_sha256": VALUATION_WORKBOOK_SHA256,
        "workbook_seed_sha256": VALUATION_WORKBOOK_SEED_SHA256,
        "member_count": len(members),
        "verified": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--collector-script", type=Path, required=True)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--local-evidence", type=Path, required=True)
    parser.add_argument("--trial-evidence", type=Path, required=True)
    parser.add_argument("--valuation-setup-evidence", type=Path)
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
    setup = None
    if args.task in VALUATION_TASKS:
        if args.valuation_setup_evidence is None:
            raise TaskEnableEvidenceError("valuation task requires production setup evidence")
        setup = verify_valuation_setup_evidence(args.valuation_setup_evidence)
    print(json.dumps(
        {"verified": True, "local": local, "trial": trial, "valuation_setup": setup},
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
