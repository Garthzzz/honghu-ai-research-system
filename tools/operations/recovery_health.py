from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.migration.stage4_json_io import read_json
from tools.operations.recovery_metrics import RecoveryMetricError, parse_utc


FORBIDDEN_KEY_FRAGMENTS = (
    "password",
    "passwd",
    "secret",
    "private_key",
    "credential_value",
    "access_token",
    "refresh_token",
    "cookie",
)


class RecoveryHealthError(ValueError):
    pass


def _forbidden_paths(value: Any, *, prefix: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key).casefold()
            child_path = f"{prefix}.{key}"
            if any(fragment in name for fragment in FORBIDDEN_KEY_FRAGMENTS):
                found.append(child_path)
            else:
                found.extend(_forbidden_paths(child, prefix=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_forbidden_paths(child, prefix=f"{prefix}[{index}]"))
    return found


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    # A missing or malformed evidence section must produce a BLOCKED health
    # result rather than crash the monitor before it can report the gate.
    del field
    return value if isinstance(value, Mapping) else {}


def evaluate_recovery_health(
    evidence: Mapping[str, Any],
    *,
    now: datetime | None = None,
    max_wal_age_seconds: float,
    max_restore_age_seconds: float,
) -> dict[str, Any]:
    observed_now = now or datetime.now(timezone.utc)
    if observed_now.tzinfo is None or observed_now.utcoffset() is None:
        raise RecoveryHealthError("now must include a timezone")
    observed_now = observed_now.astimezone(timezone.utc)
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []
    warnings: list[str] = []

    def check(name: str, passed: bool, reason: str, *, warning: bool = False) -> None:
        checks.append({"name": name, "passed": passed, "reason": reason, "warning": warning})
        if not passed:
            (warnings if warning else blockers).append(reason)

    forbidden = _forbidden_paths(evidence)
    check(
        "sensitive_fields_absent",
        not forbidden,
        "recovery evidence contains forbidden secret-bearing field names"
        if forbidden
        else "no forbidden secret-bearing field names observed",
    )

    wal = _mapping(evidence.get("wal_sync"), field="wal_sync")
    check("wal_sync_verified", wal.get("verified") is True, "off-VM WAL verification is not current")
    storage = _mapping(wal.get("storage"), field="wal_sync.storage")
    check(
        "offvm_failure_domain",
        storage.get("independent_from_source_host") is True,
        "WAL recovery material is not proven outside the source VM failure domain",
    )
    encryption = _mapping(wal.get("at_rest_encryption"), field="wal_sync.at_rest_encryption")
    encryption_verified = encryption.get("status") == "verified" and encryption.get("verified") is True
    check(
        "at_rest_encryption",
        encryption_verified,
        "backup encryption at rest is unknown or unverified",
    )
    try:
        wal_recoverable = parse_utc(
            wal.get("latest_recoverable_at_utc"),
            field="latest off-VM recoverable_at",
        )
        wal_age = (observed_now - wal_recoverable).total_seconds()
        wal_fresh = 0 <= wal_age <= max_wal_age_seconds
    except (RecoveryMetricError, TypeError):
        wal_age = None
        wal_fresh = False
    check("wal_freshness", wal_fresh, "off-VM WAL recovery point is stale or has invalid time evidence")

    restore = _mapping(evidence.get("restore"), field="restore")
    check("whole_restore", restore.get("whole_database_verified") is True, "whole-database restore is unverified")
    check("side_restore", restore.get("side_domain_verified") is True, "side-domain restore is unverified")
    check(
        "authority_restore",
        restore.get("authority_control_verified") is True,
        "authority-control restore is unverified",
    )
    check(
        "checkpoint_restore",
        restore.get("task_checkpoint_verified") is True,
        "task checkpoint restore is unverified",
    )
    target_gap = _mapping(restore.get("recovery_set_target_gap"), field="restore.recovery_set_target_gap")
    target_gap_valid = (
        target_gap.get("metric_name") == "recovery_set_target_gap_seconds"
        and target_gap.get("continuous_production_rpo") is False
        and isinstance(target_gap.get("seconds"), (int, float))
        and target_gap.get("seconds") >= 0
    )
    check(
        "recovery_set_target_gap",
        target_gap_valid,
        "recovery-set target gap is absent or mislabeled as continuous RPO",
    )
    try:
        restore_at = parse_utc(restore.get("verified_at_utc"), field="restore verified_at")
        restore_age = (observed_now - restore_at).total_seconds()
        restore_fresh = 0 <= restore_age <= max_restore_age_seconds
    except (RecoveryMetricError, TypeError):
        restore_age = None
        restore_fresh = False
    check("restore_freshness", restore_fresh, "last real restore is stale or has invalid time evidence")

    retention = _mapping(evidence.get("recovery_set_retention"), field="recovery_set_retention")
    sets = retention.get("sets")
    set_times: list[datetime] = []
    if isinstance(sets, list):
        try:
            set_times = [
                parse_utc(item.get("created_at_utc"), field="recovery set created_at")
                for item in sets
                if isinstance(item, Mapping)
            ]
        except RecoveryMetricError:
            set_times = []
    retention_ok = (
        retention.get("verified") is True
        and retention.get("inventory_complete") is True
        and retention.get("max_retained") == 2
        and retention.get("retained_count") == 2
        and retention.get("unverified_set_count") == 0
        and isinstance(sets, list)
        and len(sets) == 2
        and all(
            isinstance(item, Mapping)
            and item.get("verified") is True
            and isinstance(item.get("identity_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", item["identity_sha256"]) is not None
            for item in sets
        )
        and len(set_times) == 2
        and set_times == sorted(set_times, reverse=True)
    )
    check(
        "recovery_set_retention",
        retention_ok,
        "exactly two latest verified recovery sets are not proven",
    )

    continuous_rpo = _mapping(evidence.get("continuous_rpo"), field="continuous_rpo")
    continuous_valid = (
        continuous_rpo.get("metric_name") == "continuous_production_rpo_seconds"
        and continuous_rpo.get("preexisting_at_failure") is True
        and isinstance(continuous_rpo.get("seconds"), (int, float))
        and continuous_rpo.get("seconds") >= 0
    )
    check(
        "continuous_production_rpo_measured",
        continuous_valid,
        "continuous production RPO has not been measured from a pre-existing off-VM recovery point",
    )

    full_rto = _mapping(evidence.get("full_system_rto"), field="full_system_rto")
    full_rto_valid = (
        full_rto.get("metric_name") == "full_system_recovery_time_seconds"
        and full_rto.get("database_restore_only") is False
        and isinstance(full_rto.get("seconds"), (int, float))
        and full_rto.get("seconds") >= 0
    )
    check(
        "full_system_rto_measured",
        full_rto_valid,
        "full-system RTO is absent or only a database restore duration",
    )

    targets = _mapping(evidence.get("approved_targets"), field="approved_targets")
    rpo_target = targets.get("continuous_rpo_seconds_max")
    rto_target = targets.get("full_system_rto_seconds_max")
    check(
        "continuous_rpo_target",
        continuous_valid
        and isinstance(rpo_target, (int, float))
        and rpo_target >= 0
        and continuous_rpo["seconds"] <= rpo_target,
        "measured continuous RPO does not meet an approved target",
    )
    check(
        "full_system_rto_target",
        full_rto_valid
        and isinstance(rto_target, (int, float))
        and rto_target >= 0
        and full_rto["seconds"] <= rto_target,
        "measured full-system RTO does not meet an approved target",
    )

    authority = _mapping(evidence.get("authority"), field="authority")
    authority_ok = (
        authority.get("verified") is True
        and authority.get("expected_unit_count") == 9
        and authority.get("postgresql_authority_unit_count") == 9
        and authority.get("sqlite_writer_enabled") is False
        and authority.get("unresolved_commit_count") == 0
    )
    check(
        "authority_control",
        authority_ok,
        "9/9 PostgreSQL authority, writer fence, or uncertain-commit state is unverified",
    )

    empty_machine = _mapping(evidence.get("empty_machine"), field="empty_machine")
    reinjection = _mapping(
        empty_machine.get("credential_reinjection"),
        field="empty_machine.credential_reinjection",
    )
    check(
        "empty_machine_credential_reinjection",
        reinjection.get("required") is True
        and reinjection.get("source_vm_dpapi_blob_portable") is False
        and reinjection.get("verified") is True,
        "empty-machine credential reinjection is unverified or incorrectly assumes source-VM DPAPI portability",
    )
    check(
        "empty_machine_restore",
        empty_machine.get("verified") is True
        and empty_machine.get("exact_release_verified") is True
        and empty_machine.get("postgresql_verified") is True
        and empty_machine.get("viewer_verified") is True
        and empty_machine.get("task_definitions_verified") is True
        and empty_machine.get("task_checkpoints_verified") is True,
        "empty-machine PostgreSQL/application/task recovery is incomplete",
    )

    return {
        "schema_version": "honghu.stage5_recovery_health.v1",
        "checked_at_utc": observed_now.isoformat(),
        "status": "pass" if not blockers else "blocked",
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "observed": {
            "wal_age_seconds": wal_age,
            "restore_age_seconds": restore_age,
            "at_rest_encryption_status": encryption.get("status", "unknown"),
            "recovery_set_target_gap_seconds": target_gap.get("seconds"),
            "continuous_production_rpo_seconds": continuous_rpo.get("seconds"),
            "full_system_rto_seconds": full_rto.get("seconds"),
            "retained_recovery_set_count": retention.get("retained_count"),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Stage 5 backup and recovery health evidence")
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--max-wal-age-seconds", type=float, required=True)
    parser.add_argument("--max-restore-age-seconds", type=float, required=True)
    args = parser.parse_args(argv)
    payload = read_json(args.evidence)
    if not isinstance(payload, Mapping):
        raise RecoveryHealthError("recovery evidence root must be an object")
    result = evaluate_recovery_health(
        payload,
        max_wal_age_seconds=args.max_wal_age_seconds,
        max_restore_age_seconds=args.max_restore_age_seconds,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
