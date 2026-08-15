from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tools.data_platform.routing import CutoverUnitRegistry
from tools.migration.stage4_remaining_unit_cutover import (
    RemainingUnitCutoverError,
    build_or_load_intent,
    validate_inputs,
)


def _registry(tmp_path: Path) -> CutoverUnitRegistry:
    units = {}
    for unit in (
        "user_content_notes",
        "shared_identity",
        "financial_data",
        "research_publication",
        "dynamic_intelligence",
        "operations_governance",
        "investment_hypotheses",
        "opportunity_lens",
        "sentiment_analytics",
    ):
        units[unit] = {
            "owner": "owner",
            "objects": [{"database": "research.db", "object": unit, "kind": "table"}],
            "writer_operations": [],
            "transaction_boundaries": [],
        }
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "honghu.cutover_unit_registry.v1",
                "source_commit": "a" * 40,
                "registry_sha256": "e" * 64,
                "boundary_change_policy": "human_review_required",
                "validation": {"passed": True},
                "units": units,
            }
        ),
        encoding="utf-8",
    )
    return CutoverUnitRegistry.from_path(path)


def _inputs(unit: str = "financial_data"):
    gates = [
        "live_drift",
        "dependency_transaction_boundary",
        "stable_identity_mapping",
        "source_baseline_delta_catchup",
        "migration_backfill_reconciliation",
        "unique_writer_runner",
        "least_privilege_acl",
        "off_vm_recovery",
        "s2_s3_authority_evidence",
        "application_compatibility",
        "fail_closed_rollback_recovery",
    ]
    decision = {
        "schema_version": "honghu.stage4_remaining_cutover_decision.v1",
        "approved_by": "user",
        "approval_reference": "user-stage4-batch",
        "approval_scope": [unit],
        "approval_contract": {
            "per_unit_gates_required": gates,
            "stage5_runner_migration_authorized": False,
            "dual_writer_authorized": False,
            "shadow_write_authorized": False,
            "silent_fallback_authorized": False,
        },
    }
    s1 = {
        "schema_version": "honghu.generic_unit_s1_evidence.v1",
        "cutover_unit": unit,
        "application_commit_sha": "b" * 40,
        "source_snapshot_application_commit_sha": "a" * 40,
        "authority_state": "S1",
        "authoritative_backend": "sqlite_transition",
        "formal_business_data": False,
        "source_snapshot_id": f"{unit}:snapshot",
        "source_identity_sha256": "c" * 64,
        "source_row_count": 5,
        "target_row_count": 5,
        "source_content_sha256": "d" * 64,
        "target_content_sha256": "d" * 64,
    }
    recovery = {
        "schema_version": "honghu.stage4_production_recovery.v2",
        "status": "pass",
        "off_vm_verified": True,
        "whole_database_restore": "pass",
        "application_commit_sha": "b" * 40,
        "target": {"sentinel_operation_id": "sentinel"},
        "recovered": {
            "sentinel_operation_id": "sentinel",
            "target_lsn_reached": True,
        },
        "authority_snapshots": {
            unit: {"state": "S1", "authoritative_backend": "sqlite_transition"}
        },
    }
    return decision, s1, recovery


def test_cutover_inputs_bind_user_decision_s1_and_off_vm_restore(tmp_path: Path) -> None:
    decision, s1, recovery = _inputs()
    validate_inputs(
        unit="financial_data",
        decision=decision,
        s1=s1,
        recovery=recovery,
        registry=_registry(tmp_path),
        expected_commit="b" * 40,
    )
    broken = copy.deepcopy(recovery)
    broken["recovered"]["target_lsn_reached"] = False
    with pytest.raises(RemainingUnitCutoverError, match="sentinel"):
        validate_inputs(
            unit="financial_data",
            decision=decision,
            s1=s1,
            recovery=broken,
            registry=_registry(tmp_path),
            expected_commit="b" * 40,
        )


def test_cutover_intent_is_stable_and_rejects_identity_drift(tmp_path: Path) -> None:
    decision, s1, _recovery = _inputs()
    path = tmp_path / "intent.json"
    first = build_or_load_intent(
        path,
        unit="financial_data",
        s1=s1,
        decision=decision,
        writer_identity="honghu_writer_financial_data",
        actor="principal:operator",
    )
    second = build_or_load_intent(
        path,
        unit="financial_data",
        s1=s1,
        decision=decision,
        writer_identity="honghu_writer_financial_data",
        actor="principal:operator",
    )
    assert second == first
    changed = copy.deepcopy(s1)
    changed["source_snapshot_id"] = "other"
    with pytest.raises(RemainingUnitCutoverError, match="another cutover"):
        build_or_load_intent(
            path,
            unit="financial_data",
            s1=changed,
            decision=decision,
            writer_identity="honghu_writer_financial_data",
            actor="principal:operator",
        )
