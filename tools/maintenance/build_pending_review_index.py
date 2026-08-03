from __future__ import annotations

"""Build a public-safe, durable index for excluded pending-review paths."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "honghu.pending_review_index.v1"


def _category(path: str) -> str:
    if path.startswith("openspec/"):
        return "historical_change"
    if path.startswith("skills/"):
        return "non_active_skill"
    if path.startswith("docs/"):
        return "legacy_or_diagnostic_document"
    if path.startswith("opportunity_lens/"):
        return "legacy_opportunity_document"
    return "root_legacy_or_research_instruction"


def build_index(inventory: dict[str, Any]) -> dict[str, Any]:
    records = [
        record
        for record in inventory.get("records", [])
        if record.get("classification") == "pending_review"
    ]
    indexed: list[dict[str, Any]] = []
    for record in sorted(records, key=lambda item: str(item["path"]).casefold()):
        path = str(record["path"]).replace("\\", "/")
        path_hash = hashlib.sha256(path.encode("utf-8")).hexdigest()
        indexed.append(
            {
                "safe_id": f"pending:{path_hash[:16]}",
                "path_sha256": path_hash,
                "scope": path.split("/", 1)[0] if "/" in path else "project_root",
                "suffix": Path(path).suffix.lower(),
                "size_bytes": int(record.get("size", 0)),
                "category": _category(path),
                "reason": "not covered by the approved tracked policy",
                "status": "pending_review_untracked",
            }
        )

    source_bytes = json.dumps(
        inventory, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "schema_version": SCHEMA_VERSION,
        "privacy": (
            "Raw paths remain only in the ignored local inventory. This public-safe "
            "index uses deterministic path hashes so a candidate can be matched "
            "without disclosing research titles or internal filenames."
        ),
        "source_inventory_canonical_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "pending_count": len(indexed),
        "records": indexed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    result = build_index(inventory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "pass", "pending_count": result["pending_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
