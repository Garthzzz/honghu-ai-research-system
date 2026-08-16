from __future__ import annotations

"""Publish one verified production WAL watermark to approved off-VM storage.

The cycle deliberately creates no business row.  It captures the current
durable flush point with the dedicated backup role, rotates WAL, waits for the
completed segment in the local archive, and then delegates immutable copy and
hash verification to :mod:`tools.operations.wal_offvm_sync`.  The production
maintenance path may instead publish the newest *already archived* complete
segment.  That mode requires PostgreSQL ``archive_timeout`` to bound lag, but
needs no database credential and cannot create a database write.
"""

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from tools.data_platform.postgres_runtime import (
    build_catalog_connection_factory,
    load_postgres_runtime_catalog,
)
from tools.migration.stage4_json_io import read_json
from tools.operations.wal_offvm_sync import sync_archived_wal


WAL_NAME = re.compile(r"^[0-9A-F]{24}$")


class RecoveryCycleError(RuntimeError):
    pass


def _wait_for_complete_segment(
    archive: Path,
    name: str,
    *,
    expected_size: int,
    timeout_seconds: float,
) -> Path:
    if not WAL_NAME.fullmatch(name):
        raise RecoveryCycleError("PostgreSQL returned an invalid WAL segment name")
    deadline = time.monotonic() + timeout_seconds
    target = archive / name
    while time.monotonic() < deadline:
        if target.is_file() and target.stat().st_size == expected_size:
            return target
        time.sleep(0.25)
    raise RecoveryCycleError("target WAL segment was not completely archived in time")


def _latest_complete_archived_segment(
    archive: Path,
    *,
    expected_size: int,
) -> tuple[Path, datetime]:
    candidates: list[Path] = []
    for path in archive.iterdir():
        if not path.is_file():
            continue
        if WAL_NAME.fullmatch(path.name):
            if path.is_symlink():
                raise RecoveryCycleError("archived WAL segment must not be a symlink")
            if path.stat().st_size == expected_size:
                candidates.append(path)
        elif re.fullmatch(r"[0-9a-fA-F]{24}", path.name):
            raise RecoveryCycleError("archived WAL segment name is not canonical uppercase")
    if not candidates:
        raise RecoveryCycleError("no complete archived WAL segment is available")
    target = max(candidates, key=lambda item: item.name)
    observed_at = datetime.fromtimestamp(target.stat().st_mtime, tz=timezone.utc)
    return target, observed_at


def run_cycle(
    *,
    runtime_catalog: Path,
    source_archive: Path,
    destination: Path,
    expected_storage_identity: str,
    at_rest_encryption_evidence: Mapping[str, Any],
    initial_recovery_boundary: Mapping[str, Any],
    wal_segment_size_bytes: int = 16 * 1024 * 1024,
    timeout_seconds: float = 90.0,
    connection_factory: Callable[[], Any] | None = None,
    archive_only: bool = False,
    max_archive_age_seconds: float | None = None,
    now_factory: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    if not source_archive.is_dir():
        raise RecoveryCycleError("production WAL archive is unavailable")
    if archive_only:
        if max_archive_age_seconds is None or max_archive_age_seconds <= 0:
            raise RecoveryCycleError(
                "archive-only recovery requires a positive maximum archive age"
            )
        target_path, target_at = _latest_complete_archived_segment(
            source_archive,
            expected_size=wal_segment_size_bytes,
        )
        observed_now = (now_factory or (lambda: datetime.now(timezone.utc)))()
        if observed_now.tzinfo is None or observed_now.utcoffset() is None:
            raise RecoveryCycleError("archive freshness clock must include a timezone")
        archive_age_seconds = (
            observed_now.astimezone(timezone.utc) - target_at
        ).total_seconds()
        if archive_age_seconds < 0:
            raise RecoveryCycleError("latest complete archived WAL is dated in the future")
        if archive_age_seconds > max_archive_age_seconds:
            raise RecoveryCycleError(
                "latest complete archived WAL exceeds the maximum allowed age"
            )
        target_segment = target_path.name
        target_lsn = None
        target_source = "latest_complete_archive_segment"
    else:
        catalog = load_postgres_runtime_catalog(runtime_catalog)
        connect = connection_factory or build_catalog_connection_factory(
            catalog, role="backup"
        )
        connection = connect()
        try:
            connection.autocommit = True
            row = connection.execute(
                """
                SELECT clock_timestamp(),
                       pg_current_wal_flush_lsn()::text,
                       pg_walfile_name(pg_current_wal_flush_lsn())
                """
            ).fetchone()
            if row is None or len(row) != 3:
                raise RecoveryCycleError("durable WAL watermark query returned no identity")
            target_at = row[0]
            target_lsn = str(row[1] or "")
            target_segment = str(row[2] or "").upper()
            if not isinstance(target_at, datetime) or not target_lsn:
                raise RecoveryCycleError("durable WAL watermark is incomplete")
            connection.execute("SELECT pg_switch_wal()").fetchone()
        finally:
            connection.close()
        _wait_for_complete_segment(
            source_archive,
            target_segment,
            expected_size=wal_segment_size_bytes,
            timeout_seconds=timeout_seconds,
        )
        target_source = "postgresql_flush_watermark_and_switch"
        archive_age_seconds = None
    verification = sync_archived_wal(
        source_archive=source_archive,
        destination=destination,
        recoverable_target_at=target_at,
        target_wal_segment=target_segment,
        expected_storage_identity=expected_storage_identity,
        wal_segment_size_bytes=wal_segment_size_bytes,
        at_rest_encryption_evidence=at_rest_encryption_evidence,
        initial_recovery_boundary=initial_recovery_boundary,
    )
    return {
        "schema_version": "honghu.stage5_recovery_cycle.v1",
        "status": "pass",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "target_lsn": target_lsn,
        "target_wal_segment": target_segment,
        "target_source": target_source,
        "database_credential_used": not archive_only,
        "wal_rotation_requested": not archive_only,
        "archive_age_seconds": archive_age_seconds,
        "max_archive_age_seconds": max_archive_age_seconds if archive_only else None,
        "latest_recoverable_at_utc": verification["latest_recoverable_at_utc"],
        "manifest_identity_sha256": verification["manifest_identity_sha256"],
        "storage_identity": verification["storage"]["derived_storage_identity"],
        "at_rest_encryption": verification["at_rest_encryption"],
        "base_recovery_set_identity_sha256": verification[
            "initial_recovery_boundary"
        ]["base_recovery_set_identity_sha256"],
        "first_required_wal_segment": verification[
            "initial_recovery_boundary"
        ]["first_required_wal_segment"],
        "retention": verification["retention"],
        "formal_business_data_written": False,
        "secret_recorded": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-catalog", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--expected-storage-identity", required=True)
    parser.add_argument("--at-rest-encryption-evidence", type=Path, required=True)
    parser.add_argument("--initial-recovery-boundary", type=Path, required=True)
    parser.add_argument("--wal-segment-size-bytes", type=int, default=16 * 1024 * 1024)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument(
        "--archive-only",
        action="store_true",
        help="Publish the latest fully archived segment without a database connection.",
    )
    parser.add_argument("--max-archive-age-seconds", type=float)
    args = parser.parse_args(argv)
    evidence = read_json(args.at_rest_encryption_evidence)
    if not isinstance(evidence, Mapping):
        raise RecoveryCycleError("at-rest encryption evidence must be an object")
    initial_boundary = read_json(args.initial_recovery_boundary)
    if not isinstance(initial_boundary, Mapping):
        raise RecoveryCycleError("initial recovery boundary evidence must be an object")
    result = run_cycle(
        runtime_catalog=args.runtime_catalog,
        source_archive=args.source_archive,
        destination=args.destination,
        expected_storage_identity=args.expected_storage_identity,
        at_rest_encryption_evidence=evidence,
        initial_recovery_boundary=initial_boundary,
        wal_segment_size_bytes=args.wal_segment_size_bytes,
        timeout_seconds=args.timeout_seconds,
        archive_only=args.archive_only,
        max_archive_age_seconds=args.max_archive_age_seconds,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
