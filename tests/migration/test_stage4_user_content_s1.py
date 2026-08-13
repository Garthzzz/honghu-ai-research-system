from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.migration.stage4_identity_mapping import _sha as mapping_sha
from tools.migration.stage4_user_content_s1 import (
    UserContentS1Error,
    _sha,
    validate_mapping_approval,
)
from tools.migration.stage4_isolated_entry import ALLOWED_MODULES


ROOT = Path(__file__).resolve().parents[2]


def test_user_content_s1_is_an_allowlisted_isolated_entrypoint() -> None:
    assert ALLOWED_MODULES["tools.migration.stage4_user_content_s1"] == "main"


def _mapping() -> dict:
    core = {
        "schema_version": "honghu.user_content_identity_mapping.v2",
        "source_database": "research.db",
        "source_tables": {},
        "mappings": [],
        "alias_groups": [],
    }
    return {**core, "manifest_sha256": mapping_sha(core)}


def _approval(mapping: dict) -> dict:
    core = {
        "schema_version": "honghu.identity_mapping_cutover_approval.v1",
        "mapping_manifest_sha256": mapping["manifest_sha256"],
        "cutover_level_approved": True,
        "approved_by": "user",
        "approved_at_utc": "2026-08-12T00:00:00Z",
        "approval_reference": "human-stage4-mapping-approval",
        "manual_review_item_count": 0,
        "manual_review_resolutions": [],
    }
    return {**core, "approval_sha256": _sha(core)}


def test_mapping_approval_is_human_bound_and_hashed() -> None:
    mapping = _mapping()
    approval = _approval(mapping)
    assert validate_mapping_approval(mapping, approval) == approval
    approval["approved_by"] = "codex"
    approval["approval_sha256"] = _sha(
        {key: value for key, value in approval.items() if key != "approval_sha256"}
    )
    with pytest.raises(UserContentS1Error, match="not attributed to the user"):
        validate_mapping_approval(mapping, approval)


def test_mapping_approval_tamper_and_manifest_drift_fail_closed() -> None:
    mapping = _mapping()
    approval = _approval(mapping)
    approval["approval_reference"] = "tampered"
    with pytest.raises(UserContentS1Error, match="hash mismatch"):
        validate_mapping_approval(mapping, approval)
    approval = _approval(mapping)
    approval["mapping_manifest_sha256"] = "f" * 64
    approval["approval_sha256"] = _sha(
        {key: value for key, value in approval.items() if key != "approval_sha256"}
    )
    with pytest.raises(UserContentS1Error, match="another manifest"):
        validate_mapping_approval(mapping, approval)


def test_migration_role_has_only_s0_s1_authority_preparation() -> None:
    staging = (ROOT / "migrations/postgresql/0003_stage4_migration_staging.sql").read_text(
        encoding="utf-8"
    )
    grants = (
        ROOT / "migrations/postgresql/0003_stage4_migration_role_grants.sql"
    ).read_text(encoding="utf-8")
    assert "prepare_user_content_notes_authority_s1" in staging
    assert "ABSENT->S0 or S0->S1" in staging
    assert "REVOKE EXECUTE ON FUNCTION operations.transition_user_content_notes" in grants
    assert "GRANT EXECUTE ON FUNCTION operations.prepare_user_content_notes_authority_s1" in grants
    assert "operations.schema_migration" in grants
    assert "operations.cutover_unit_authority" in grants
    assert "operations.cutover_dependency_mapping" in grants
    assert "operations.idempotency_record" in grants
    assert "GRANT SELECT ON ALL TABLES IN SCHEMA operations" not in grants
