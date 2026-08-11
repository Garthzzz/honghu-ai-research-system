from __future__ import annotations

import copy
import json
from pathlib import Path

from tools.migration.stage4_readiness_preflight import evaluate_readiness


ROOT = Path(__file__).resolve().parents[2]


def _template() -> dict:
    return json.loads(
        (ROOT / "config/migration/stage4_user_content_readiness_template.json").read_text(
            encoding="utf-8"
        )
    )


def _complete() -> dict:
    payload = _template()
    payload["evidence_cutoff_utc"] = "2026-08-12T00:00:00Z"
    payload["identity_mapping"].update(
        {
            "verified": True,
            "manifest_sha256": "a" * 64,
            "source_database_sha256": "b" * 64,
            "mapping_count": 1,
            "collision_count": 0,
            "unapproved_alias_count": 0,
            "alias_group_count": 0,
            "approval_reference": "identity-approved",
        }
    )
    for section in (
        "application_contract",
        "postgresql_topology",
        "recovery",
        "repository_governance",
        "cutover_window",
    ):
        for key, value in list(payload[section].items()):
            if isinstance(value, bool):
                payload[section][key] = True
            elif key.endswith("sha256"):
                payload[section][key] = "c" * 64
            elif key.endswith("reference"):
                payload[section][key] = "approved-reference"
    return payload


def test_template_is_blocked_and_does_not_self_authorize() -> None:
    result = evaluate_readiness(root=ROOT, evidence=_template())
    assert result["status"] == "blocked"
    assert result["production_cutover_authorized"] is False
    assert result["tracked_default_route"] == {
        "state": "S0",
        "backend": "sqlite_transition",
        "sqlite_writer_enabled": True,
    }
    assert any("off_vm_copy_verified" in item for item in result["blockers"])
    assert any("production_authority_approved" in item for item in result["blockers"])


def test_complete_evidence_is_only_ready_to_request_authorization() -> None:
    result = evaluate_readiness(root=ROOT, evidence=_complete())
    assert result["status"] == "ready_to_request_production_authorization"
    assert result["production_cutover_authorized"] is False
    assert result["blockers"] == []


def test_missing_single_recovery_fact_fails_closed() -> None:
    payload = copy.deepcopy(_complete())
    payload["recovery"]["authority_recovery_evidence_sha256"] = ""
    result = evaluate_readiness(root=ROOT, evidence=payload)
    assert result["status"] == "blocked"
    assert "recovery.authority_recovery_evidence_sha256 is missing or invalid" in result[
        "blockers"
    ]
