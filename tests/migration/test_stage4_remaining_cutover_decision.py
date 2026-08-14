from __future__ import annotations

import json
from pathlib import Path


def test_remaining_cutover_decision_binds_refreshed_mapping_and_preserves_stage5_boundary() -> None:
    root = Path(__file__).resolve().parents[2]
    config = root / "config" / "migration"
    decision = json.loads(
        (config / "stage4_remaining_cutover_decision.json").read_text(encoding="utf-8")
    )
    approval = json.loads(
        (config / "stage4_identity_mapping_approval_summary.json").read_text(encoding="utf-8")
    )
    crosscheck = json.loads(
        (config / "stage4_identity_mapping_crosscheck_summary.json").read_text(encoding="utf-8")
    )
    mapping = decision["shared_identity_mapping_approval"]
    assert decision["approved_by"] == "user"
    assert mapping["cutover_level_approved"] is True
    assert mapping["mapping_manifest_sha256"] == approval["mapping_manifest_sha256"]
    assert mapping["mapping_snapshot_identity_sha256"] == approval["snapshot_identity_sha256"]
    assert mapping["approval_bundle_sha256"] == approval["approval_bundle_sha256"]
    assert mapping["crosscheck_source_snapshot_identity_sha256"] == crosscheck[
        "crosscheck_source_snapshot_identity_sha256"
    ]
    assert crosscheck["counts"]["fallback_requires_human"] == 0
    assert decision["approval_contract"]["stage5_runner_migration_authorized"] is False
    assert "stage5" in decision["forbidden_scope"]
