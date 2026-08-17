from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tools.operations.recovery_metrics import (
    RecoveryMetricError,
    measure_continuous_production_rpo,
    measure_full_system_rto,
    measure_recovery_set_target_gap,
    parse_utc,
)


def test_recovery_set_gap_is_not_continuous_rpo() -> None:
    result = measure_recovery_set_target_gap(
        durable_target_at="2026-08-16T01:00:10+00:00",
        recovered_watermark_at="2026-08-16T01:00:09.993+00:00",
    )
    assert result["metric_name"] == "recovery_set_target_gap_seconds"
    assert result["seconds"] == pytest.approx(0.007)
    assert result["continuous_production_rpo"] is False


def test_continuous_rpo_requires_preexisting_offvm_point() -> None:
    with pytest.raises(RecoveryMetricError, match="published after"):
        measure_continuous_production_rpo(
            failure_cutoff_at="2026-08-16T01:00:00+00:00",
            latest_preexisting_offvm_recoverable_at="2026-08-16T00:59:59+00:00",
            recovery_point_published_at="2026-08-16T01:00:01+00:00",
        )


def test_continuous_rpo_uses_failure_cutoff_and_published_watermark() -> None:
    result = measure_continuous_production_rpo(
        failure_cutoff_at="2026-08-16T01:00:00+00:00",
        latest_preexisting_offvm_recoverable_at="2026-08-16T00:59:40+00:00",
        recovery_point_published_at="2026-08-16T00:59:45+00:00",
    )
    assert result["metric_name"] == "continuous_production_rpo_seconds"
    assert result["seconds"] == 20
    assert result["preexisting_at_failure"] is True


def test_continuous_rpo_rejects_recoverable_watermark_after_publication() -> None:
    with pytest.raises(RecoveryMetricError, match="newer than"):
        measure_continuous_production_rpo(
            failure_cutoff_at="2026-08-16T01:00:00+00:00",
            latest_preexisting_offvm_recoverable_at="2026-08-16T00:59:50+00:00",
            recovery_point_published_at="2026-08-16T00:59:45+00:00",
        )


def test_full_system_rto_includes_all_safe_resume_milestones() -> None:
    result = measure_full_system_rto(
        recovery_started_at="2026-08-16T01:00:00+00:00",
        postgres_ready_at="2026-08-16T01:00:10+00:00",
        authority_verified_at="2026-08-16T01:00:20+00:00",
        viewer_ready_at="2026-08-16T01:00:25+00:00",
        task_checkpoints_verified_at="2026-08-16T01:00:40+00:00",
        backup_chain_verified_at="2026-08-16T01:00:45+00:00",
        recovery_completed_at="2026-08-16T01:00:50+00:00",
    )
    assert result["metric_name"] == "full_system_recovery_time_seconds"
    assert result["seconds"] == 50
    assert result["milestone_seconds"]["task_checkpoints_verified_seconds"] == 40
    assert result["database_restore_only"] is False


def test_full_system_rto_rejects_completion_before_required_milestone() -> None:
    with pytest.raises(RecoveryMetricError, match="occurs after"):
        measure_full_system_rto(
            recovery_started_at="2026-08-16T01:00:00+00:00",
            postgres_ready_at="2026-08-16T01:00:10+00:00",
            authority_verified_at="2026-08-16T01:00:20+00:00",
            viewer_ready_at="2026-08-16T01:00:25+00:00",
            task_checkpoints_verified_at="2026-08-16T01:00:40+00:00",
            backup_chain_verified_at="2026-08-16T01:00:55+00:00",
            recovery_completed_at="2026-08-16T01:00:50+00:00",
        )


def test_metrics_reject_naive_datetime() -> None:
    with pytest.raises(RecoveryMetricError, match="timezone"):
        measure_recovery_set_target_gap(
            durable_target_at=datetime(2026, 8, 16, 1, 0, 0),
            recovered_watermark_at=datetime(2026, 8, 16, 0, 59, 59, tzinfo=timezone.utc),
        )


def test_parse_utc_accepts_powershell_seven_digit_fraction_on_python_310() -> None:
    parsed = parse_utc(
        "2026-08-16T19:18:01.9167873+00:00",
        field="powershell timestamp",
    )
    assert parsed == datetime(2026, 8, 16, 19, 18, 1, 916787, tzinfo=timezone.utc)
