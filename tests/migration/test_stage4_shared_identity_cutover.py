from __future__ import annotations

import copy

import pytest

from tools.migration.stage4_shared_identity_cutover import (
    SharedIdentityCutoverError,
    route_from_evidence,
    validate_inputs,
)


def _inputs():
    mapping = {
        "manifest_sha256": "a" * 64,
        "snapshot_identity_sha256": "b" * 64,
    }
    decision = {
        "schema_version": "honghu.stage4_remaining_cutover_decision.v1",
        "approved_by": "user",
        "approval_reference": "user-stage4-batch",
        "approval_scope": ["shared_identity"],
        "approval_contract": {
            "stage5_runner_migration_authorized": False,
            "dual_writer_authorized": False,
            "shadow_write_authorized": False,
            "silent_fallback_authorized": False,
        },
        "shared_identity_mapping_approval": {
            "cutover_level_approved": True,
            "mapping_manifest_sha256": "a" * 64,
            "mapping_snapshot_identity_sha256": "b" * 64,
            "manual_review_item_count": 0,
        },
    }
    s1 = {
        "schema_version": "honghu.shared_identity_s1_evidence.v1",
        "authority_state": "S1",
        "authoritative_backend": "sqlite_transition",
        "formal_business_data": False,
        "source_row_count": 10,
        "target_row_count": 10,
        "source_content_sha256": "c" * 64,
        "target_content_sha256": "c" * 64,
        "mapping_manifest_sha256": "a" * 64,
        "application_commit_sha": "d" * 40,
    }
    recovery = {
        "schema_version": "honghu.stage4_production_recovery.v1",
        "status": "pass",
        "off_vm_verified": True,
        "whole_database_restore": "pass",
        "application_commit_sha": "d" * 40,
        "target": {"sentinel_operation_id": "sentinel"},
        "recovered": {
            "sentinel_operation_id": "sentinel",
            "target_lsn_reached": True,
        },
        "authority_snapshots": {
            "shared_identity": {
                "state": "S1",
                "authoritative_backend": "sqlite_transition",
            }
        },
    }
    return mapping, decision, s1, recovery


def test_shared_identity_cutover_inputs_bind_mapping_s1_and_off_vm_recovery() -> None:
    mapping, decision, s1, recovery = _inputs()
    validate_inputs(mapping=mapping, decision=decision, s1=s1, recovery=recovery)

    broken = copy.deepcopy(recovery)
    broken["recovered"]["target_lsn_reached"] = False
    with pytest.raises(SharedIdentityCutoverError, match="sentinel"):
        validate_inputs(mapping=mapping, decision=decision, s1=s1, recovery=broken)

    broken_decision = copy.deepcopy(decision)
    broken_decision["approval_contract"]["dual_writer_authorized"] = True
    with pytest.raises(SharedIdentityCutoverError, match="unsafe approval"):
        validate_inputs(
            mapping=mapping, decision=broken_decision, s1=s1, recovery=recovery
        )


def test_shared_identity_s3_route_is_explicit_and_fences_sqlite() -> None:
    route = route_from_evidence(
        {
            "state_revision": 4,
            "writer_identity": "honghu_writer_shared_identity",
            "cutover_epoch": "epoch",
            "approval_reference": "approval",
        }
    )
    assert route["authority_state"] == "S3"
    assert route["backend"] == "postgresql_production"
    assert route["sqlite_writer_enabled"] is False
    assert route["production_postgresql_enabled"] is True
