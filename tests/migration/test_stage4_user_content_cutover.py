from __future__ import annotations

from pathlib import Path

import pytest

from tools.migration.stage4_user_content_cutover import (
    UserContentCutoverError,
    _route,
    _sha,
    validate_enter_s2_inputs,
)
from tools.migration.stage4_user_content_s1 import _sha as s1_sha


def _hashed(payload: dict, field: str = "evidence_sha256") -> dict:
    return {**payload, field: _sha(payload)}


def _fixture() -> tuple[dict, dict, dict, dict, dict, dict]:
    mapping_core = {
        "schema_version": "honghu.user_content_identity_mapping.v2",
        "source_database": "research.db",
        "source_tables": {},
        "mappings": [],
        "alias_groups": [],
    }
    mapping = {**mapping_core, "manifest_sha256": _sha(mapping_core)}
    mapping_approval_core = {
        "schema_version": "honghu.identity_mapping_cutover_approval.v1",
        "mapping_manifest_sha256": mapping["manifest_sha256"],
        "cutover_level_approved": True,
        "approved_by": "user",
        "approved_at_utc": "2026-08-13T00:00:00Z",
        "approval_reference": "mapping-approved",
        "manual_review_item_count": 0,
        "manual_review_resolutions": [],
    }
    mapping_approval = {
        **mapping_approval_core,
        "approval_sha256": s1_sha(mapping_approval_core),
    }
    s1 = _hashed({
        "schema_version": "honghu.user_content_notes_s1_evidence.v1",
        "state": "S1",
        "authoritative_backend": "sqlite_transition",
        "mapping_manifest_sha256": mapping["manifest_sha256"],
        "mapping_approval_sha256": mapping_approval["approval_sha256"],
        "source_note_count": 0,
        "target_note_count": 0,
        "authority_revision": 2,
    })
    recovery = _hashed({
        "schema_version": "honghu.stage4_production_recovery.v1",
        "status": "pass",
        "whole_database_restore": "pass",
        "off_vm_verified": True,
        "target": {"sentinel_operation_id": "sentinel-1"},
        "recovered": {
            "sentinel_operation_id": "sentinel-1",
            "target_lsn_reached": True,
        },
    })
    fence = _hashed({
        "schema_version": "honghu.user_content_writer_fence.v1",
        "verified": True,
        "sqlite_writer_fenced": True,
        "old_listener_absent": True,
        "scheduled_writer_absent": True,
        "production_8080_stopped_for_cutover": True,
        "sqlite_final_watermark": {"analyst_note_count": 0, "max_id": None},
    })
    approval_core = {
        "schema_version": "honghu.user_content_cutover_approval.v1",
        "approved_by": "user",
        "approved_at_utc": "2026-08-13T00:00:00Z",
        "approval_reference": "user-approved-s2",
        "operator": "principal:codex",
        "writer_identity": "honghu_user_content_writer",
        "enter_s2_authorized": True,
        "mapping_manifest_sha256": mapping["manifest_sha256"],
        "mapping_approval_sha256": mapping_approval["approval_sha256"],
        "s1_evidence_sha256": s1["evidence_sha256"],
        "recovery_evidence_sha256": recovery["evidence_sha256"],
        "writer_fence_evidence_sha256": fence["evidence_sha256"],
    }
    approval = {**approval_core, "approval_sha256": _sha(approval_core)}
    return mapping, mapping_approval, s1, recovery, fence, approval


def test_s2_gate_binds_every_authority_input() -> None:
    values = _fixture()
    watermark = validate_enter_s2_inputs(
        mapping=values[0], mapping_approval=values[1], s1=values[2],
        recovery=values[3], fence=values[4], approval=values[5]
    )
    assert watermark["analyst_note_count"] == 0


@pytest.mark.parametrize(
    "target,field",
    [(3, "off_vm_verified"), (4, "sqlite_writer_fenced"), (5, "enter_s2_authorized")],
)
def test_s2_gate_fails_closed_when_recovery_fence_or_approval_is_false(
    target: int, field: str
) -> None:
    values = list(_fixture())
    values[target][field] = False
    identity_field = "approval_sha256" if target == 5 else "evidence_sha256"
    values[target][identity_field] = _sha({
        key: value for key, value in values[target].items() if key != identity_field
    })
    with pytest.raises(UserContentCutoverError):
        validate_enter_s2_inputs(
            mapping=values[0], mapping_approval=values[1], s1=values[2],
            recovery=values[3], fence=values[4], approval=values[5]
        )


def test_runtime_route_never_reenables_sqlite_writer() -> None:
    for state in ("S2", "S3"):
        route = _route(
            state=state,
            revision=3,
            writer_identity="writer",
            approval_reference="approval",
            cutover_epoch="epoch-1",
        )
        assert route["backend"] == "postgresql_production"
        assert route["sqlite_writer_enabled"] is False
        assert route["production_postgresql_enabled"] is True
