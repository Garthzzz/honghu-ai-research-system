from __future__ import annotations

"""Publish one verified production WAL watermark to approved off-VM storage.

The cycle deliberately creates no business row.  It captures the current
durable flush point with the dedicated backup role, rotates WAL, waits for the
completed segment in the local archive, and then delegates immutable copy and
hash verification to :mod:`tools.operations.wal_offvm_sync`.
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


def run_cycle(
    *,
    runtime_catalog: Path,
    source_archive: Path,
    destination: Path,
    expected_storage_identity: str,
    at_rest_encryption_evidence: Mapping[str, Any],
    wal_segment_size_bytes: int = 16 * 1024 * 1024,
    timeout_seconds: float = 90.0,
    connection_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    if not source_archive.is_dir():
        raise RecoveryCycleError("production WAL archive is unavailable")
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
        # The role is granted only this control function.  Rotation makes the
        # target segment immutable and eligible for archive/hash verification.
        connection.execute("SELECT pg_switch_wal()").fetchone()
    finally:
        connection.close()
    _wait_for_complete_segment(
        source_archive,
        target_segment,
        expected_size=wal_segment_size_bytes,
        timeout_seconds=timeout_seconds,
    )
    verification = sync_archived_wal(
        source_archive=source_archive,
        destination=destination,
        recoverable_target_at=target_at,
        target_wal_segment=target_segment,
        expected_storage_identity=expected_storage_identity,
        wal_segment_size_bytes=wal_segment_size_bytes,
        at_rest_encryption_evidence=at_rest_encryption_evidence,
    )
    return {
        "schema_version": "honghu.stage5_recovery_cycle.v1",
        "status": "pass",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "target_lsn": target_lsn,
        "target_wal_segment": target_segment,
        "latest_recoverable_at_utc": verification["latest_recoverable_at_utc"],
        "manifest_identity_sha256": verification["manifest_identity_sha256"],
        "storage_identity": verification["storage"]["derived_storage_identity"],
        "at_rest_encryption": verification["at_rest_encryption"],
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
    parser.add_argument("--wal-segment-size-bytes", type=int, default=16 * 1024 * 1024)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    args = parser.parse_args(argv)
    evidence = read_json(args.at_rest_encryption_evidence)
    if not isinstance(evidence, Mapping):
        raise RecoveryCycleError("at-rest encryption evidence must be an object")
    result = run_cycle(
        runtime_catalog=args.runtime_catalog,
        source_archive=args.source_archive,
        destination=args.destination,
        expected_storage_identity=args.expected_storage_identity,
        at_rest_encryption_evidence=evidence,
        wal_segment_size_bytes=args.wal_segment_size_bytes,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
