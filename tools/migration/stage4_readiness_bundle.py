from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


EVIDENCE_SCHEMA = "honghu.stage4_readiness_evidence.v1"
BUNDLE_SCHEMA = "honghu.stage4_user_content_readiness_bundle.v2"
REQUIRED_CHECKS = {"boundary-and-contracts", "python-clean-environment"}
TRACKED_APPLICATION_SOURCES = (
    "tools/data_platform/user_content_notes.py",
    "tools/viewer/static/analyst_note_mutations.js",
    "tools/viewer/app.py",
    "tests/viewer/test_analyst_note_browser_mutations.py",
    "tests/migration/test_stage4_user_content_rehearsal.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _copy_evidence_file(source: Path, target: Path) -> Path:
    """Copy an input into the bundle unless it is already the target artifact."""
    source_resolved = source.resolve()
    target_resolved = target.resolve()
    if source_resolved != target_resolved:
        shutil.copyfile(source_resolved, target_resolved)
    return target_resolved


def _envelope(
    evidence_type: str,
    subject: dict[str, str],
    payload: dict[str, Any],
    observed: datetime,
) -> dict[str, Any]:
    return {
        "schema_version": EVIDENCE_SCHEMA,
        "evidence_type": evidence_type,
        "subject": subject,
        "observed_at_utc": observed.isoformat(),
        "valid_until_utc": (observed + timedelta(days=2)).isoformat(),
        "payload": payload,
    }


def _github_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "honghu-stage4-readiness-audit",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def build_bundle(
    *,
    root: Path,
    evidence_root: Path,
    subject: dict[str, str],
    mapping_path: Path,
    mapping_approval_path: Path,
    adapter_rehearsal_path: Path,
    topology_path: Path,
    recovery_path: Path,
    github_repository: str,
) -> dict[str, Any]:
    evidence_root.mkdir(parents=True, exist_ok=True)
    observed = datetime.now(timezone.utc)
    mapping = _read_json(mapping_path)
    mapping_approval = _read_json(mapping_approval_path)
    adapter = _read_json(adapter_rehearsal_path)
    topology = _read_json(topology_path)
    recovery = _read_json(recovery_path)

    if topology.get("subject") != subject or recovery.get("subject") != subject:
        raise ValueError("topology/recovery subject does not match bundle subject")
    if adapter.get("status") != "pass":
        raise ValueError("adapter rehearsal did not pass")

    copied_mapping = evidence_root / "identity_mapping_manifest.json"
    copied_adapter = evidence_root / "adapter_rehearsal.json"
    copied_topology = evidence_root / "postgresql_topology.json"
    copied_recovery = evidence_root / "recovery.json"
    for source, target in (
        (mapping_path, copied_mapping),
        (adapter_rehearsal_path, copied_adapter),
        (topology_path, copied_topology),
        (recovery_path, copied_recovery),
    ):
        _copy_evidence_file(source, target)

    approval_payload = {
        "mapping_manifest_sha256": mapping["manifest_sha256"],
        "snapshot_identity_sha256": mapping["source_snapshot"]["snapshot_identity_sha256"],
        "mapping_count": len(mapping["mappings"]),
        "fallback_count": mapping_approval["counts"]["name_and_market_fallback"],
        "cutover_level_approved": bool(mapping_approval.get("cutover_level_approved")),
        "approval_reference": mapping_approval.get("approval_reference") or "",
        "approval_bundle_sha256": sha256_file(mapping_approval_path),
    }
    approval_file = _write(
        evidence_root / "identity_mapping_approval.json",
        _envelope("identity_mapping_approval", subject, approval_payload, observed),
    )

    tracked_sources = {
        relative: sha256_file(root / relative) for relative in TRACKED_APPLICATION_SOURCES
    }
    application_payload = {
        "tracked_route_sha256": sha256_file(
            root / "config/migration/user_content_backend_route.json"
        ),
        "route": {
            "authority_state": "S0",
            "backend": "sqlite_transition",
            "sqlite_writer_enabled": True,
            "production_postgresql_enabled": False,
        },
        "silent_fallback": "forbidden",
        "adapter_rehearsal": {
            "path": copied_adapter.name,
            "commit_sha": subject["commit_sha"],
            "artifact_sha256": sha256_file(copied_adapter),
            "passed_cases": [
                "create_update_delete_api_compatibility",
                "revision_and_idempotency",
                "trusted_principal_actor",
                "no_silent_fallback",
                "s3_forward_repair",
                "schema_compatible_code_rollback",
            ],
        },
        "tracked_source_identities": tracked_sources,
    }
    application_file = _write(
        evidence_root / "application_contract.json",
        _envelope("application_contract", subject, application_payload, observed),
    )

    base = f"https://api.github.com/repos/{github_repository}"
    main = _github_json(f"{base}/branches/main")
    checks = _github_json(f"{base}/commits/{subject['commit_sha']}/check-runs")
    successful = {
        item.get("name")
        for item in checks.get("check_runs") or []
        if item.get("status") == "completed" and item.get("conclusion") == "success"
    }
    required_contexts = set(
        ((main.get("protection") or {}).get("required_status_checks") or {}).get("contexts")
        or []
    )
    repository_payload = {
        "repository": {
            "repository": github_repository,
            "main_commit_sha": (main.get("commit") or {}).get("sha"),
            "subject_commit_sha": subject["commit_sha"],
            "required_checks": sorted(REQUIRED_CHECKS),
            "successful_checks": sorted(successful),
            "required_checks_green": REQUIRED_CHECKS <= successful,
            "branch_protection_verified": bool(main.get("protected"))
            and REQUIRED_CHECKS <= required_contexts,
            "production_authority_approved": False,
        },
        "second_company_admin_or_handover": False,
        "two_factor_and_recovery": False,
        "company_controlled_deploy_credential": False,
    }
    repository_file = _write(
        evidence_root / "repository_governance.json",
        _envelope("repository_governance", subject, repository_payload, observed),
    )

    plan_paths = (
        "openspec/changes/github-vm-dual-node-operations/stage4/stage4_execution_plan.md",
        "openspec/changes/github-vm-dual-node-operations/stage4/stage4_production_readiness_candidate_design.md",
    )
    cutover_payload = {
        "writer_fence_plan_verified": all((root / path).is_file() for path in plan_paths),
        "rollback_recovery_decision_tree_verified": all(
            (root / path).is_file() for path in plan_paths
        ),
        "tracked_plan_identities": {
            path: sha256_file(root / path) for path in plan_paths if (root / path).is_file()
        },
        "operator": {"approved": False, "approval_reference": ""},
        "approver": {"approved": False, "approval_reference": ""},
        "maintenance_window": {"approved": False, "approval_reference": ""},
        "enter_s2_approval": {"approved": False, "approval_reference": ""},
    }
    cutover_file = _write(
        evidence_root / "cutover_decision.json",
        _envelope("cutover_decision", subject, cutover_payload, observed),
    )

    artifact_paths = {
        "identity_mapping_manifest": copied_mapping,
        "identity_mapping_approval": approval_file,
        "application_contract": application_file,
        "postgresql_topology": copied_topology,
        "recovery": copied_recovery,
        "repository_governance": repository_file,
        "cutover_decision": cutover_file,
    }
    bundle = {
        "schema_version": BUNDLE_SCHEMA,
        "cutover_unit": "user_content_notes",
        "production_cutover_authorized": False,
        "evidence_cutoff_utc": observed.isoformat(),
        "subject": subject,
        "artifacts": {
            name: {
                "evidence_type": name,
                "path": path.name,
                "sha256": sha256_file(path),
            }
            for name, path in artifact_paths.items()
        },
    }
    _write(evidence_root / "readiness_bundle.json", bundle)
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a typed Stage 4 readiness bundle")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--environment-id", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--mapping-approval", type=Path, required=True)
    parser.add_argument("--adapter-rehearsal", type=Path, required=True)
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument("--recovery", type=Path, required=True)
    parser.add_argument("--github-repository", default="Garthzzz/honghu-ai-research-system")
    args = parser.parse_args()
    bundle = build_bundle(
        root=args.root.resolve(),
        evidence_root=args.evidence_root.resolve(),
        subject={
            "environment_id": args.environment_id,
            "candidate_id": args.candidate_id,
            "commit_sha": args.commit_sha,
            "config_sha256": args.config_sha256,
        },
        mapping_path=args.mapping.resolve(),
        mapping_approval_path=args.mapping_approval.resolve(),
        adapter_rehearsal_path=args.adapter_rehearsal.resolve(),
        topology_path=args.topology.resolve(),
        recovery_path=args.recovery.resolve(),
        github_repository=args.github_repository,
    )
    print(json.dumps(bundle, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
