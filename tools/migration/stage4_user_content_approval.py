from __future__ import annotations

"""Compile user-approved Stage 4 decisions into evidence-bound approvals.

The tracked decision records the human decision and its narrow scope.  This
compiler binds that decision to the current Git-external mapping, S1,
off-machine recovery and writer-fence evidence.  It does not transition
authority or write either database.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from tools.migration.stage4_json_io import read_json
from tools.migration.stage4_user_content_s1 import validate_mapping_approval


class UserContentApprovalError(RuntimeError):
    pass


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _object(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict):
        raise UserContentApprovalError(f"JSON object required: {path}")
    return value


def _decision(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != "honghu.user_content_cutover_decision.v1":
        raise UserContentApprovalError("unsupported user decision schema")
    expected = {
        "cutover_unit": "user_content_notes",
        "approved_by": "user",
        "mapping_cutover_level_approved": True,
        "enter_s2_authorized": True,
        "operator": "principal:codex",
        "writer_identity": "honghu_user_content_writer",
    }
    for field, required in expected.items():
        if value.get(field) != required:
            raise UserContentApprovalError(f"user decision does not authorize {field}")
    for field in ("approved_at_utc", "approval_reference", "scope_limit"):
        if not str(value.get(field) or "").strip():
            raise UserContentApprovalError(f"user decision is missing {field}")
    return value


def compile_mapping_approval(
    *, mapping: dict[str, Any], decision: dict[str, Any]
) -> dict[str, Any]:
    decision = _decision(decision)
    resolutions = decision.get("manual_review_resolutions")
    if not isinstance(resolutions, list) or not resolutions:
        raise UserContentApprovalError("mapping approval must record reviewed resolutions")
    core = {
        "schema_version": "honghu.identity_mapping_cutover_approval.v1",
        "mapping_manifest_sha256": mapping.get("manifest_sha256"),
        "cutover_level_approved": True,
        "approved_by": "user",
        "approved_at_utc": decision["approved_at_utc"],
        "approval_reference": decision["approval_reference"],
        "approval_scope": decision["mapping_resolution_scope"],
        "manual_review_item_count": len(resolutions),
        "manual_review_resolutions": resolutions,
        "decision_sha256": _sha(decision),
    }
    result = {**core, "approval_sha256": _sha(core)}
    validate_mapping_approval(mapping, result)
    return result


def compile_cutover_approval(
    *,
    mapping: dict[str, Any],
    mapping_approval: dict[str, Any],
    s1: dict[str, Any],
    recovery: dict[str, Any],
    fence: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    decision = _decision(decision)
    validate_mapping_approval(mapping, mapping_approval)
    application_commit_sha = str(s1.get("application_commit_sha") or "")
    if len(application_commit_sha) != 40:
        raise UserContentApprovalError("S1 evidence has no exact application commit")
    identities = {
        "mapping_manifest_sha256": mapping.get("manifest_sha256"),
        "mapping_approval_sha256": mapping_approval.get("approval_sha256"),
        "s1_evidence_sha256": s1.get("evidence_sha256"),
        "recovery_evidence_sha256": recovery.get("evidence_sha256"),
        "writer_fence_evidence_sha256": fence.get("evidence_sha256"),
    }
    if any(not isinstance(value, str) or len(value) != 64 for value in identities.values()):
        raise UserContentApprovalError("cutover evidence identity is missing")
    for evidence, label in ((recovery, "recovery"), (fence, "writer fence")):
        if evidence.get("application_commit_sha") != application_commit_sha:
            raise UserContentApprovalError(f"{label} belongs to another application commit")
    core = {
        "schema_version": "honghu.user_content_cutover_approval.v1",
        "approved_by": "user",
        "approved_at_utc": decision["approved_at_utc"],
        "approval_reference": decision["approval_reference"],
        "operator": decision["operator"],
        "writer_identity": decision["writer_identity"],
        "enter_s2_authorized": True,
        "scope_limit": decision["scope_limit"],
        "application_commit_sha": application_commit_sha,
        "decision_sha256": _sha(decision),
        **identities,
    }
    return {**core, "approval_sha256": _sha(core)}


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("mapping", "cutover"))
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mapping-approval", type=Path)
    parser.add_argument("--s1-evidence", type=Path)
    parser.add_argument("--recovery-evidence", type=Path)
    parser.add_argument("--fence-evidence", type=Path)
    args = parser.parse_args(argv)
    mapping = _object(args.mapping)
    decision = _object(args.decision)
    if args.action == "mapping":
        result = compile_mapping_approval(mapping=mapping, decision=decision)
    else:
        required = (
            args.mapping_approval,
            args.s1_evidence,
            args.recovery_evidence,
            args.fence_evidence,
        )
        if any(path is None for path in required):
            parser.error("cutover requires mapping approval, S1, recovery and fence evidence")
        result = compile_cutover_approval(
            mapping=mapping,
            mapping_approval=_object(args.mapping_approval),
            s1=_object(args.s1_evidence),
            recovery=_object(args.recovery_evidence),
            fence=_object(args.fence_evidence),
            decision=decision,
        )
    _write(args.output, result)
    print(json.dumps({
        "schema_version": result["schema_version"],
        "approval_sha256": result["approval_sha256"],
        "application_commit_sha": result.get("application_commit_sha"),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
