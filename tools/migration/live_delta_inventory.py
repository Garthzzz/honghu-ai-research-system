from __future__ import annotations

"""Build a Git-external inventory for executable live-only SQLite paths.

The public application repository remains the deployable code authority.  This
tool records Python paths that are present in the active workspace but absent
from the repository, then binds that addendum to the tracked dependency
inventory.  It never embeds source text, database rows, papers, or credentials.
"""

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from tools.migration.sqlite_inventory import scan_file


ADDENDUM_SCHEMA_VERSION = "honghu.sqlite_live_only_addendum.v1"
AGGREGATE_SCHEMA_VERSION = "honghu.sqlite_dependency_aggregate.v1"
SCAN_PREFIXES = ("tools", "opportunity_lens", "tests")
BLOCKED_PARTS = {".git", "__pycache__", ".pytest_cache", "secrets"}


def _hash_json(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _tracked_paths(repo_root: Path) -> set[str]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=repo_root, stderr=subprocess.DEVNULL
    )
    return {
        item.decode("utf-8").replace("\\", "/")
        for item in output.split(b"\0")
        if item
    }


def _candidate_paths(live_root: Path) -> Iterable[Path]:
    for prefix in SCAN_PREFIXES:
        base = live_root / prefix
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            relative = path.relative_to(live_root)
            if any(part.lower() in BLOCKED_PARTS for part in relative.parts):
                continue
            yield path


def _summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    operation_ids = [
        operation["operation_id"]
        for record in records
        for operation in record["writer_operations"]
    ]
    transaction_ids = [
        transaction
        for record in records
        for transaction in record["transaction_boundaries"]
    ]
    return {
        "file_count": len(records),
        "production_file_count": sum(row["lifecycle"] != "test_only" for row in records),
        "write_file_count": sum(row["access"] == "write" for row in records),
        "writer_operation_count": len(operation_ids),
        "transaction_boundary_count": len(transaction_ids),
        "attach_file_count": sum(bool(row["attach_present"]) for row in records),
        "counts_by_domain": dict(sorted(Counter(row["domain"] for row in records).items())),
        "duplicate_operation_ids": sorted(
            operation_id
            for operation_id, count in Counter(operation_ids).items()
            if count > 1
        ),
        "duplicate_transaction_boundaries": sorted(
            transaction_id
            for transaction_id, count in Counter(transaction_ids).items()
            if count > 1
        ),
    }


def build_live_only_addendum(
    live_root: Path,
    repo_root: Path,
    deployable_inventory: dict[str, Any],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    live_root = live_root.resolve()
    repo_root = repo_root.resolve()
    tracked = _tracked_paths(repo_root)
    deployable_paths = {record["path"] for record in deployable_inventory["files"]}
    records: list[dict[str, Any]] = []
    for path in sorted(set(_candidate_paths(live_root))):
        relative = path.relative_to(live_root).as_posix()
        if relative in tracked or relative in deployable_paths:
            continue
        record = scan_file(live_root, path)
        if record is not None:
            records.append(record)
    records.sort(key=lambda row: row["path"])
    summary = _summary(records)
    payload: dict[str, Any] = {
        "schema_version": ADDENDUM_SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "deployable_source_commit": deployable_inventory["source_commit"],
        "deployable_inventory_sha256": deployable_inventory["inventory_sha256"],
        "scan_roots": list(SCAN_PREFIXES),
        "blocked_path_parts": sorted(BLOCKED_PARTS),
        "definition": {
            "scope": "live Python paths absent from the public repository that contain SQLite dependencies",
            "content_excluded": [
                "source_text",
                "database_rows",
                "papers_and_evidence",
                "credentials_and_browser_state",
            ],
            "authority": "audit addendum only; it is not a second deployable source authority",
            "retirement": "removal requires a separately reviewed boundary change",
        },
        "summary": summary,
        "validation": {
            "paths_disjoint_from_tracked_repository": all(
                record["path"] not in tracked for record in records
            ),
            "duplicate_operation_ids": summary["duplicate_operation_ids"],
            "duplicate_transaction_boundaries": summary["duplicate_transaction_boundaries"],
        },
        "files": records,
    }
    payload["addendum_sha256"] = _hash_json(payload)
    return payload


def build_aggregate_manifest(
    deployable_inventory: dict[str, Any],
    addendum: dict[str, Any],
    *,
    known_cutover_units: set[str] | None = None,
) -> dict[str, Any]:
    deployable_records = list(deployable_inventory["files"])
    live_only_records = list(addendum["files"])
    deployable_paths = {record["path"] for record in deployable_records}
    overlap = sorted(
        record["path"] for record in live_only_records if record["path"] in deployable_paths
    )
    merged = sorted(deployable_records + live_only_records, key=lambda row: row["path"])
    summary = _summary(merged)
    unknown_candidate_owners = sorted(
        {
            record["candidate_cutover_unit"]
            for record in live_only_records
            if known_cutover_units is not None
            and record["candidate_cutover_unit"] not in known_cutover_units
        }
    )
    payload: dict[str, Any] = {
        "schema_version": AGGREGATE_SCHEMA_VERSION,
        "generated_at": addendum["generated_at"],
        "deployable_source_commit": deployable_inventory["source_commit"],
        "deployable_inventory_sha256": deployable_inventory["inventory_sha256"],
        "live_only_addendum_sha256": addendum["addendum_sha256"],
        "summary": summary,
        "validation": {
            "path_overlap": overlap,
            "duplicate_operation_ids": summary["duplicate_operation_ids"],
            "duplicate_transaction_boundaries": summary["duplicate_transaction_boundaries"],
            "unknown_live_only_candidate_owners": unknown_candidate_owners,
            "passed": not overlap
            and not summary["duplicate_operation_ids"]
            and not summary["duplicate_transaction_boundaries"]
            and not unknown_candidate_owners,
        },
        "production_sequencing_contract": (
            "While live-only paths remain, production cutover review requires the deployable "
            "inventory, live-only addendum, and this aggregate identity together."
        ),
    }
    payload["aggregate_sha256"] = _hash_json(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--deployable-inventory", type=Path, required=True)
    parser.add_argument("--ownership", type=Path, required=True)
    parser.add_argument("--addendum-output", type=Path, required=True)
    parser.add_argument("--aggregate-output", type=Path, required=True)
    args = parser.parse_args(argv)

    deployable = json.loads(args.deployable_inventory.read_text(encoding="utf-8"))
    ownership = json.loads(args.ownership.read_text(encoding="utf-8"))
    known_units = set(ownership.get("units", {})) | set(
        ownership.get("operation_only_units", {})
    )
    addendum = build_live_only_addendum(args.live_root, args.repo_root, deployable)
    aggregate = build_aggregate_manifest(
        deployable,
        addendum,
        known_cutover_units=known_units,
    )
    args.addendum_output.parent.mkdir(parents=True, exist_ok=True)
    args.aggregate_output.parent.mkdir(parents=True, exist_ok=True)
    args.addendum_output.write_text(
        json.dumps(addendum, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.aggregate_output.write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "addendum": str(args.addendum_output),
                "addendum_sha256": addendum["addendum_sha256"],
                "aggregate": str(args.aggregate_output),
                "aggregate_sha256": aggregate["aggregate_sha256"],
                "validation": aggregate["validation"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if aggregate["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
