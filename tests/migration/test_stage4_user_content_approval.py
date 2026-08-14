from __future__ import annotations

from copy import deepcopy

import pytest

from tools.migration.stage4_identity_mapping import _sha as mapping_sha
from tools.migration.stage4_user_content_approval import (
    UserContentApprovalError,
    compile_cutover_approval,
    compile_mapping_approval,
)
from tools.migration.stage4_user_content_approval import _sha


def _values() -> tuple[dict, dict, dict, dict, dict]:
    snapshot_core = {
        "transaction_contract": {"mode": "explicit_read_transaction"},
        "database_pragmas": {"schema_version": 1},
        "source_tables": {},
    }
    mapping_core = {
        "schema_version": "honghu.user_content_identity_mapping.v3",
        "source_database": "research.db",
        "source_tables": {},
        "source_snapshot": {
            **snapshot_core,
            "snapshot_identity_sha256": mapping_sha(snapshot_core),
        },
        "mappings": [],
        "alias_groups": [],
    }
    mapping = {**mapping_core, "manifest_sha256": mapping_sha(mapping_core)}
    decision = {
        "schema_version": "honghu.user_content_cutover_decision.v1",
        "cutover_unit": "user_content_notes",
        "approved_by": "user",
        "approved_at_utc": "2026-08-13T14:00:00Z",
        "approval_reference": "user-approved",
        "mapping_cutover_level_approved": True,
        "mapping_resolution_scope": "all records",
        "manual_review_resolutions": [{"legacy_id": "21", "resolution": "ACIA"}],
        "enter_s2_authorized": True,
        "operator": "principal:codex",
        "writer_identity": "honghu_user_content_writer",
        "scope_limit": "user_content_notes_only",
    }
    commit = "a" * 40
    s1_core = {"application_commit_sha": commit}
    s1 = {**s1_core, "evidence_sha256": _sha(s1_core)}
    recovery_core = {"application_commit_sha": commit}
    recovery = {**recovery_core, "evidence_sha256": _sha(recovery_core)}
    fence_core = {"application_commit_sha": commit}
    fence = {**fence_core, "evidence_sha256": _sha(fence_core)}
    return mapping, decision, s1, recovery, fence


def test_user_decision_compiles_mapping_and_exact_cutover_approval() -> None:
    mapping, decision, s1, recovery, fence = _values()
    mapping_approval = compile_mapping_approval(mapping=mapping, decision=decision)
    cutover = compile_cutover_approval(
        mapping=mapping,
        mapping_approval=mapping_approval,
        s1=s1,
        recovery=recovery,
        fence=fence,
        decision=decision,
    )
    assert mapping_approval["approved_by"] == "user"
    assert mapping_approval["manual_review_item_count"] == 1
    assert cutover["application_commit_sha"] == "a" * 40
    assert cutover["enter_s2_authorized"] is True


def test_approval_fails_closed_on_scope_or_commit_drift() -> None:
    mapping, decision, s1, recovery, fence = _values()
    bad = deepcopy(decision)
    bad["cutover_unit"] = "shared_identity"
    with pytest.raises(UserContentApprovalError, match="cutover_unit"):
        compile_mapping_approval(mapping=mapping, decision=bad)
    mapping_approval = compile_mapping_approval(mapping=mapping, decision=decision)
    recovery["application_commit_sha"] = "b" * 40
    with pytest.raises(UserContentApprovalError, match="another application commit"):
        compile_cutover_approval(
            mapping=mapping,
            mapping_approval=mapping_approval,
            s1=s1,
            recovery=recovery,
            fence=fence,
            decision=decision,
        )
