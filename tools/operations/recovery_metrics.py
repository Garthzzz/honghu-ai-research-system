from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Mapping


class RecoveryMetricError(ValueError):
    """Raised when recovery timestamps cannot support the claimed metric."""


_ISO_FRACTION = re.compile(
    r"^(?P<prefix>.+?)(?P<fraction>\.\d+)(?P<offset>[+-]\d{2}:\d{2})?$"
)


def _python_microsecond_iso(raw: str) -> str:
    """Normalize PowerShell's seven-digit ISO fraction for Python 3.10."""

    match = _ISO_FRACTION.fullmatch(raw)
    if match is None:
        return raw
    digits = match.group("fraction")[1:]
    normalized = (digits + "000000")[:6]
    return (
        match.group("prefix")
        + "."
        + normalized
        + (match.group("offset") or "")
    )


def parse_utc(value: str | datetime, *, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        raw = _python_microsecond_iso(raw)
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise RecoveryMetricError(f"{field} is not a valid ISO-8601 timestamp") from exc
    else:
        raise RecoveryMetricError(f"{field} must be an ISO-8601 string or datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RecoveryMetricError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _elapsed(later: datetime, earlier: datetime, *, label: str) -> float:
    seconds = (later - earlier).total_seconds()
    if seconds < 0:
        raise RecoveryMetricError(f"{label} has an invalid timestamp order")
    return seconds


def measure_recovery_set_target_gap(
    *,
    durable_target_at: str | datetime,
    recovered_watermark_at: str | datetime,
) -> dict[str, Any]:
    """Measure one recovery set's target-to-recovered watermark gap.

    This deliberately does *not* claim a continuous production RPO.  It only
    measures the gap inside the recovery set exercised by a restore test.
    """

    target = parse_utc(durable_target_at, field="durable_target_at")
    recovered = parse_utc(recovered_watermark_at, field="recovered_watermark_at")
    gap = _elapsed(target, recovered, label="recovery-set target gap")
    return {
        "schema_version": "honghu.recovery_set_target_gap.v1",
        "metric_name": "recovery_set_target_gap_seconds",
        "seconds": gap,
        "durable_target_at_utc": _iso(target),
        "recovered_watermark_at_utc": _iso(recovered),
        "continuous_production_rpo": False,
    }


def measure_continuous_production_rpo(
    *,
    failure_cutoff_at: str | datetime,
    latest_preexisting_offvm_recoverable_at: str | datetime,
    recovery_point_published_at: str | datetime,
) -> dict[str, Any]:
    """Measure RPO from a recovery point published before the failure cutoff."""

    failure = parse_utc(failure_cutoff_at, field="failure_cutoff_at")
    recoverable = parse_utc(
        latest_preexisting_offvm_recoverable_at,
        field="latest_preexisting_offvm_recoverable_at",
    )
    published = parse_utc(recovery_point_published_at, field="recovery_point_published_at")
    if published > failure:
        raise RecoveryMetricError(
            "continuous RPO cannot use a recovery point published after the failure cutoff"
        )
    if recoverable > published:
        raise RecoveryMetricError(
            "recoverable watermark cannot be newer than its off-VM publication"
        )
    seconds = _elapsed(failure, recoverable, label="continuous production RPO")
    return {
        "schema_version": "honghu.continuous_production_rpo.v1",
        "metric_name": "continuous_production_rpo_seconds",
        "seconds": seconds,
        "failure_cutoff_at_utc": _iso(failure),
        "latest_preexisting_offvm_recoverable_at_utc": _iso(recoverable),
        "recovery_point_published_at_utc": _iso(published),
        "preexisting_at_failure": True,
    }


def measure_full_system_rto(
    *,
    recovery_started_at: str | datetime,
    postgres_ready_at: str | datetime,
    authority_verified_at: str | datetime,
    viewer_ready_at: str | datetime,
    task_checkpoints_verified_at: str | datetime,
    backup_chain_verified_at: str | datetime,
    recovery_completed_at: str | datetime,
) -> dict[str, Any]:
    """Measure safe full-system recovery, not only database restore execution."""

    started = parse_utc(recovery_started_at, field="recovery_started_at")
    milestones: Mapping[str, datetime] = {
        "postgres_ready": parse_utc(postgres_ready_at, field="postgres_ready_at"),
        "authority_verified": parse_utc(authority_verified_at, field="authority_verified_at"),
        "viewer_ready": parse_utc(viewer_ready_at, field="viewer_ready_at"),
        "task_checkpoints_verified": parse_utc(
            task_checkpoints_verified_at,
            field="task_checkpoints_verified_at",
        ),
        "backup_chain_verified": parse_utc(
            backup_chain_verified_at,
            field="backup_chain_verified_at",
        ),
    }
    completed = parse_utc(recovery_completed_at, field="recovery_completed_at")
    milestone_seconds: dict[str, float] = {}
    milestone_times: dict[str, str] = {}
    for name, observed_at in milestones.items():
        milestone_seconds[f"{name}_seconds"] = _elapsed(
            observed_at,
            started,
            label=f"{name} recovery time",
        )
        if observed_at > completed:
            raise RecoveryMetricError(f"{name} occurs after recovery_completed_at")
        milestone_times[f"{name}_at_utc"] = _iso(observed_at)
    total = _elapsed(completed, started, label="full-system RTO")
    return {
        "schema_version": "honghu.full_system_rto.v1",
        "metric_name": "full_system_recovery_time_seconds",
        "seconds": total,
        "recovery_started_at_utc": _iso(started),
        "recovery_completed_at_utc": _iso(completed),
        "milestone_seconds": milestone_seconds,
        "milestone_times": milestone_times,
        "database_restore_only": False,
    }
