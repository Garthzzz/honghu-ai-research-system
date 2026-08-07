from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "honghu.cutover_unit_registry.v1"


def _hash_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_registry(
    ownership: dict[str, Any], inventory: dict[str, Any], live_schema: dict[str, Any]
) -> dict[str, Any]:
    units: dict[str, Any] = {}
    object_owner: dict[tuple[str, str], str] = {}
    ownership_conflicts: list[dict[str, Any]] = []

    for unit_name, definition in ownership["units"].items():
        units[unit_name] = {
            "owner": definition["owner"],
            "risk": definition["risk"],
            "dependencies": definition.get("dependencies", []),
            "state": ownership["states"]["current"],
            "authoritative_backend": ownership["states"]["authoritative_backend"],
            "objects": [],
            "writer_operations": [],
            "transaction_boundaries": [],
        }
        for database, names in definition.get("objects", {}).items():
            for name in names:
                key = (database, name)
                if key in object_owner:
                    ownership_conflicts.append(
                        {"database": database, "object": name, "owners": [object_owner[key], unit_name]}
                    )
                object_owner[key] = unit_name
                units[unit_name]["objects"].append({"database": database, "object": name, "kind": "table"})

    live_tables = {
        (database, table["name"])
        for database, detail in live_schema["databases"].items()
        for table in detail["tables"]
    }
    for unit_name, definition in ownership["units"].items():
        for database, prefixes in definition.get("object_prefixes", {}).items():
            for database_name, table_name in sorted(live_tables):
                if database_name == database and any(table_name.startswith(prefix) for prefix in prefixes):
                    key = (database_name, table_name)
                    if key in object_owner:
                        ownership_conflicts.append(
                            {"database": database_name, "object": table_name, "owners": [object_owner[key], unit_name]}
                        )
                    object_owner[key] = unit_name
                    units[unit_name]["objects"].append(
                        {"database": database_name, "object": table_name, "kind": "table"}
                    )

    for unit_name, definition in ownership.get("operation_only_units", {}).items():
        units[unit_name] = {
            "owner": definition["owner"],
            "risk": definition["risk"],
            "dependencies": definition.get("dependencies", []),
            "state": ownership["states"]["current"],
            "authoritative_backend": ownership["states"]["authoritative_backend"],
            "disposition": definition["disposition"],
            "objects": [],
            "writer_operations": [],
            "transaction_boundaries": [],
        }

    overrides = ownership.get("operation_owner_overrides", {})
    operation_ids: set[str] = set()
    transaction_ids: set[str] = set()
    unknown_owners: list[dict[str, str]] = []
    for record in inventory["files"]:
        for operation in record["writer_operations"]:
            operation_owner = overrides.get(
                f'{record["path"]}:{operation["operation"]}',
                overrides.get(record["path"], record["candidate_cutover_unit"]),
            )
            if operation_owner not in units:
                unknown_owners.append(
                    {"path": record["path"], "operation": operation["operation"], "owner": operation_owner}
                )
                continue
            operation_id = operation["operation_id"]
            if operation_id in operation_ids:
                ownership_conflicts.append({"writer_operation": operation_id, "reason": "duplicate ownership"})
            operation_ids.add(operation_id)
            units[operation_owner]["writer_operations"].append(
                {
                    "operation_id": operation_id,
                    "path": record["path"],
                    "operation": operation["operation"],
                    "lifecycle": record["lifecycle"],
                    "dml_targets": record["dml_targets"],
                    "surface_types": record.get("surface_types", []),
                    "routes": record.get("routes", []),
                }
            )
        for transaction_id in record["transaction_boundaries"]:
            operation_name = transaction_id.rsplit(":", 1)[-1]
            operation_owner = overrides.get(
                f'{record["path"]}:{operation_name}',
                overrides.get(record["path"], record["candidate_cutover_unit"]),
            )
            if operation_owner not in units:
                continue
            if transaction_id in transaction_ids:
                ownership_conflicts.append({"transaction_boundary": transaction_id, "reason": "duplicate ownership"})
            transaction_ids.add(transaction_id)
            units[operation_owner]["transaction_boundaries"].append(
                {"transaction_id": transaction_id, "path": record["path"], "dml_targets": record["dml_targets"]}
            )

    unowned = sorted(live_tables - set(object_owner))
    nonexistent = sorted(set(object_owner) - live_tables)
    matrix = [
        {
            "database": database,
            "object": name,
            "owning_cutover_unit": unit,
            "state": ownership["states"]["current"],
            "authoritative_backend": ownership["states"]["authoritative_backend"],
            "writer_backend": database,
        }
        for (database, name), unit in sorted(object_owner.items())
    ]
    for definition in units.values():
        definition["objects"].sort(key=lambda item: (item["database"], item["object"]))
        definition["writer_operations"].sort(key=lambda item: item["operation_id"])
        definition["transaction_boundaries"].sort(key=lambda item: item["transaction_id"])
    result = {
        "schema_version": SCHEMA_VERSION,
        "source_commit": inventory["source_commit"],
        "inventory_sha256": inventory["inventory_sha256"],
        "boundary_change_policy": ownership["boundary_change_policy"],
        "units": dict(sorted(units.items())),
        "authoritative_backend_matrix": matrix,
        "validation": {
            "ownership_conflicts": ownership_conflicts,
            "unknown_operation_owners": unknown_owners,
            "unowned_live_tables": [{"database": db, "object": name} for db, name in unowned],
            "configured_objects_not_in_live_schema": [
                {"database": db, "object": name} for db, name in nonexistent
            ],
            "object_count": len(matrix),
            "writer_operation_count": len(operation_ids),
            "transaction_boundary_count": len(transaction_ids),
            "passed": not ownership_conflicts and not unknown_owners and not unowned and not nonexistent,
        },
    }
    result["registry_sha256"] = _hash_json(result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[2]
    parser.add_argument("--ownership", type=Path, default=root / "config/migration/table_ownership.json")
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--live-schema", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = build_registry(_load(args.ownership), _load(args.inventory), _load(args.live_schema))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "validation": result["validation"]}, ensure_ascii=False))
    return 0 if result["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
