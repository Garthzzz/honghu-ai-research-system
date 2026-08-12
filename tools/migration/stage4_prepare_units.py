from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.migration.stage4_s1_loader import _connection_from_runtime, load_snapshot
from tools.migration.stage4_unit_s1 import PRODUCTION_UNITS, build_unit_snapshot


class Stage4PreparationError(RuntimeError):
    pass


def _sha(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage4PreparationError(f"JSON object required: {path}")
    return value


def _authority_guard(connection: Any) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT cutover_unit, state, authoritative_backend, writer_identity,
                   cutover_epoch, postgresql_first_formal_commit
              FROM operations.cutover_unit_authority
             ORDER BY cutover_unit
            """
        )
        rows = [
            {
                "cutover_unit": row[0],
                "state": row[1],
                "authoritative_backend": row[2],
                "writer_identity": row[3],
                "cutover_epoch": row[4],
                "postgresql_first_formal_commit": row[5],
            }
            for row in cursor.fetchall()
        ]
    for row in rows:
        if (
            row["state"] not in {"S0", "S1"}
            or row["authoritative_backend"] != "sqlite_transition"
            or row["writer_identity"] is not None
            or row["cutover_epoch"] is not None
            or row["postgresql_first_formal_commit"] is not None
        ):
            raise Stage4PreparationError(
                f"production authority exceeds S0/S1: {row['cutover_unit']}"
            )
    return rows


def prepare_units(
    *,
    source_data_root: Path,
    registry_path: Path,
    route_path: Path,
    runtime_path: Path,
    application_commit_sha: str,
    work_root: Path,
    units: tuple[str, ...] = PRODUCTION_UNITS,
) -> dict[str, Any]:
    if len(application_commit_sha) != 40:
        raise Stage4PreparationError("full application commit SHA is required")
    registry = _read_json(registry_path)
    if not bool((registry.get("validation") or {}).get("passed")):
        raise Stage4PreparationError("reviewed cutover registry is not green")
    route = _read_json(route_path)
    if not (
        route.get("authority_state") in {"S0", "S1"}
        and route.get("backend") == "sqlite_transition"
        and route.get("sqlite_writer_enabled") is True
        and route.get("production_postgresql_enabled") is False
    ):
        raise Stage4PreparationError("tracked route is outside S0/S1 SQLite authority")
    unknown = sorted(set(units) - set(PRODUCTION_UNITS))
    if unknown:
        raise Stage4PreparationError(f"unknown production unit: {', '.join(unknown)}")

    free = shutil.disk_usage(work_root.parent if work_root.parent.exists() else source_data_root).free
    largest_source = max((source_data_root / name).stat().st_size for name in (
        "research.db", "financial.db", "opportunity_lens.db", "sentiment.db"
    ))
    if free < max(2 * largest_source, 2 * 1024**3):
        raise Stage4PreparationError("insufficient free space for bounded online snapshot and row stream")

    work_root.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    connection = _connection_from_runtime(runtime_path, "migration")
    try:
        before_authority = _authority_guard(connection)
        for unit in units:
            unit_root = work_root / unit
            unit_root.mkdir(parents=True, exist_ok=True)
            rows_path = unit_root / f"{unit}.rows.jsonl"
            manifest_path = unit_root / f"{unit}.snapshot.json"
            try:
                snapshot = build_unit_snapshot(
                    unit=unit,
                    source_data_root=source_data_root,
                    registry_path=registry_path,
                    application_commit_sha=application_commit_sha,
                    output_dir=unit_root,
                    include_rows=True,
                )
                rows_sha = _sha_file(rows_path)
                loaded = load_snapshot(
                    connection,
                    manifest_path=manifest_path,
                    rows_path=rows_path,
                    route_path=route_path,
                    registry_path=registry_path,
                )
                rows_path.unlink()
                results.append(
                    {
                        "cutover_unit": unit,
                        "status": "staging_reconciled_s0_s1_preparation",
                        "snapshot_id": snapshot["snapshot_id"],
                        "snapshot_manifest_sha256": snapshot["manifest_sha256"],
                        "source_row_count": loaded["source_row_count"],
                        "source_content_sha256": loaded["source_content_sha256"],
                        "target_content_sha256": loaded["target_content_sha256"],
                        "transient_rows_sha256": rows_sha,
                        "transient_rows_removed_after_load": True,
                        "formal_business_data": False,
                        "authoritative_backend": "sqlite_transition",
                    }
                )
            except Exception as exc:
                failures.append(
                    {
                        "cutover_unit": unit,
                        "error_type": type(exc).__name__,
                        "reason": str(exc),
                    }
                )
        after_authority = _authority_guard(connection)
    finally:
        connection.close()
    if before_authority != after_authority:
        raise Stage4PreparationError("unit staging changed authority control state")
    core = {
        "schema_version": "honghu.stage4_all_unit_preparation.v1",
        "application_commit_sha": application_commit_sha,
        "registry_sha256": registry["registry_sha256"],
        "started_at_utc": started,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "units": results,
        "failures": failures,
        "authority_before": before_authority,
        "authority_after": after_authority,
        "authority_changed": False,
        "production_cutover_authorized": False,
        "s2_s3_entered": False,
        "formal_business_mutation_written": False,
    }
    result = {**core, "evidence_sha256": _sha(core)}
    (work_root / "all_unit_preparation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-data-root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--route", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--application-commit-sha", required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--unit", action="append", choices=PRODUCTION_UNITS)
    args = parser.parse_args(argv)
    result = prepare_units(
        source_data_root=args.source_data_root.resolve(),
        registry_path=args.registry.resolve(),
        route_path=args.route.resolve(),
        runtime_path=args.runtime.resolve(),
        application_commit_sha=args.application_commit_sha,
        work_root=args.work_root.resolve(),
        units=tuple(args.unit or PRODUCTION_UNITS),
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not result["failures"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
