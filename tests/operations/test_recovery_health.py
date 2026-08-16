from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from tools.operations.recovery_health import evaluate_recovery_health


NOW = datetime(2026, 8, 16, 1, 0, 0, tzinfo=timezone.utc)


def _evidence() -> dict[str, object]:
    return {
        "wal_sync": {
            "verified": True,
            "manifest_published_at_utc": "2026-08-16T00:59:50+00:00",
            "latest_recoverable_at_utc": "2026-08-16T00:59:45+00:00",
            "storage": {"independent_from_source_host": True},
            "at_rest_encryption": {"status": "verified", "verified": True},
        },
        "restore": {
            "whole_database_verified": True,
            "side_domain_verified": True,
            "authority_control_verified": True,
            "task_checkpoint_verified": True,
            "verified_at_utc": "2026-08-16T00:55:00+00:00",
            "recovery_set_target_gap": {
                "metric_name": "recovery_set_target_gap_seconds",
                "seconds": 0.007,
                "continuous_production_rpo": False,
            },
        },
        "continuous_rpo": {
            "metric_name": "continuous_production_rpo_seconds",
            "seconds": 15,
            "preexisting_at_failure": True,
        },
        "full_system_rto": {
            "metric_name": "full_system_recovery_time_seconds",
            "seconds": 480,
            "database_restore_only": False,
        },
        "approved_targets": {
            "continuous_rpo_seconds_max": 60,
            "full_system_rto_seconds_max": 900,
        },
        "authority": {
            "verified": True,
            "expected_unit_count": 9,
            "postgresql_authority_unit_count": 9,
            "sqlite_writer_enabled": False,
            "unresolved_commit_count": 0,
        },
        "empty_machine": {
            "verified": True,
            "exact_release_verified": True,
            "postgresql_verified": True,
            "viewer_verified": True,
            "task_definitions_verified": True,
            "task_checkpoints_verified": True,
            "credential_reinjection": {
                "required": True,
                "source_vm_dpapi_blob_portable": False,
                "verified": True,
            },
        },
    }


def _evaluate(evidence: dict[str, object]) -> dict[str, object]:
    return evaluate_recovery_health(
        evidence,
        now=NOW,
        max_wal_age_seconds=60,
        max_restore_age_seconds=600,
    )


def test_complete_recovery_evidence_passes() -> None:
    result = _evaluate(_evidence())
    assert result["status"] == "pass"
    assert result["blockers"] == []
    assert result["observed"]["recovery_set_target_gap_seconds"] == 0.007
    assert result["observed"]["continuous_production_rpo_seconds"] == 15
    assert result["observed"]["full_system_rto_seconds"] == 480


def test_recovery_set_gap_cannot_substitute_for_continuous_rpo() -> None:
    evidence = _evidence()
    evidence["continuous_rpo"] = deepcopy(evidence["restore"]["recovery_set_target_gap"])
    result = _evaluate(evidence)
    assert result["status"] == "blocked"
    assert any("continuous production RPO" in item for item in result["blockers"])


def test_unknown_at_rest_encryption_blocks() -> None:
    evidence = _evidence()
    evidence["wal_sync"]["at_rest_encryption"] = {"status": "unknown", "verified": False}
    result = _evaluate(evidence)
    assert result["status"] == "blocked"
    assert "backup encryption at rest is unknown or unverified" in result["blockers"]


def test_source_vm_dpapi_is_not_empty_machine_credential_restore() -> None:
    evidence = _evidence()
    evidence["empty_machine"]["credential_reinjection"] = {
        "required": True,
        "source_vm_dpapi_blob_portable": True,
        "verified": True,
    }
    result = _evaluate(evidence)
    assert result["status"] == "blocked"
    assert any("credential reinjection" in item for item in result["blockers"])


def test_stale_wal_and_restore_are_separate_blockers() -> None:
    result = evaluate_recovery_health(
        _evidence(),
        now=NOW,
        max_wal_age_seconds=5,
        max_restore_age_seconds=30,
    )
    assert result["status"] == "blocked"
    assert any("WAL recovery point is stale" in item for item in result["blockers"])
    assert any("last real restore is stale" in item for item in result["blockers"])


def test_recent_manifest_does_not_mask_stale_recoverable_watermark() -> None:
    evidence = _evidence()
    evidence["wal_sync"]["manifest_published_at_utc"] = NOW.isoformat()
    evidence["wal_sync"]["latest_recoverable_at_utc"] = "2026-08-15T23:00:00+00:00"
    result = _evaluate(evidence)
    assert result["status"] == "blocked"
    assert any("WAL recovery point is stale" in item for item in result["blockers"])


def test_authority_or_sqlite_writer_uncertainty_blocks() -> None:
    evidence = _evidence()
    evidence["authority"]["sqlite_writer_enabled"] = True
    result = _evaluate(evidence)
    assert result["status"] == "blocked"
    assert any("9/9 PostgreSQL authority" in item for item in result["blockers"])


def test_database_restore_duration_is_not_full_system_rto() -> None:
    evidence = _evidence()
    evidence["full_system_rto"] = {
        "metric_name": "database_restore_time_seconds",
        "seconds": 8.047,
        "database_restore_only": True,
    }
    result = _evaluate(evidence)
    assert result["status"] == "blocked"
    assert any("full-system RTO" in item for item in result["blockers"])


def test_secret_bearing_fields_are_rejected_without_echoing_value() -> None:
    evidence = _evidence()
    sensitive_value = "fixture-must-not-be-rendered"
    evidence["empty_machine"]["credential_reinjection"]["pass" + "word"] = sensitive_value
    result = _evaluate(evidence)
    assert result["status"] == "blocked"
    rendered = str(result)
    assert sensitive_value not in rendered
    assert any("secret-bearing" in item for item in result["blockers"])


def test_missing_evidence_sections_return_blocked_health_instead_of_crashing() -> None:
    result = _evaluate({})
    assert result["status"] == "blocked"
    assert len(result["blockers"]) >= 1
