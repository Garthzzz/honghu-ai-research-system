#!/usr/bin/env python
"""Verify that a released PCB-equipment slice matches the reviewed candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CANDIDATE = ROOT / "cache" / "pcb_equipment_research" / "research_validation_final_20260719_2125.db"
DEFAULT_RELEASE = ROOT / "data" / "research.db"
DEFAULT_SOURCE_MAP = ROOT / "cache" / "db_queue" / "pcb_equipment_b_20260719_source_map.json"
DEFAULT_OUTPUT = ROOT / "cache" / "pcb_equipment_research" / "live_release_equivalence.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_rows(
    conn: sqlite3.Connection,
    query: str,
    *,
    drop: set[str],
    params: tuple[Any, ...] = (),
) -> list[dict[str, Any]]:
    rows = []
    for row in conn.execute(query, params):
        rows.append({key: row[key] for key in row.keys() if key not in drop})
    rows.sort(key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, default=str))
    return rows


def _row_hash(rows: list[dict[str, Any]]) -> str:
    value = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--release", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument("--source-map", type=Path, default=DEFAULT_SOURCE_MAP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    candidate_path = args.candidate.resolve()
    release_path = args.release.resolve()
    source_ids = sorted(set(json.loads(args.source_map.read_text(encoding="utf-8")).values()))
    source_placeholders = ",".join("?" for _ in source_ids)
    queries = {
        "industry_data_points": (
            "SELECT * FROM industry_data_point WHERE industry_id=23",
            {"id", "created_at", "updated_at"},
            (),
        ),
        "company_profiles": (
            "SELECT * FROM company_profile WHERE industry_id=23",
            {"id", "created_at", "updated_at", "last_updated"},
            (),
        ),
        "company_links": (
            "SELECT * FROM company_industry WHERE industry_id=23",
            {"id", "created_at", "updated_at"},
            (),
        ),
        "sub_market_shares": (
            "SELECT * FROM company_sub_market_share WHERE industry_id=23",
            {"id", "created_at", "updated_at"},
            (),
        ),
        "industry_relations": (
            "SELECT * FROM industry_relation WHERE upstream_id=23",
            {"id", "created_at", "updated_at"},
            (),
        ),
        "companies": (
            "SELECT * FROM company WHERE id IN "
            "(SELECT company_id FROM company_industry WHERE industry_id=23)",
            {"created_at", "updated_at", "last_updated"},
            (),
        ),
        "registered_sources": (
            f"SELECT * FROM source WHERE id IN ({source_placeholders})",
            {"created_at", "updated_at", "fetch_timestamp", "last_updated"},
            tuple(source_ids),
        ),
    }

    connections = {}
    diagnostics = {}
    try:
        for label, path in (("candidate", candidate_path), ("release", release_path)):
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            connections[label] = conn
            diagnostics[label] = {
                "path": str(path),
                "sha256": _sha256(path),
                "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
                "foreign_key_violations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
            }

        comparisons = {}
        for name, (query, drop, params) in queries.items():
            candidate_rows = _canonical_rows(connections["candidate"], query, drop=drop, params=params)
            release_rows = _canonical_rows(connections["release"], query, drop=drop, params=params)
            candidate_hash = _row_hash(candidate_rows)
            release_hash = _row_hash(release_rows)
            comparisons[name] = {
                "candidate_count": len(candidate_rows),
                "release_count": len(release_rows),
                "candidate_logical_sha256": candidate_hash,
                "release_logical_sha256": release_hash,
                "match": candidate_hash == release_hash and len(candidate_rows) == len(release_rows),
            }
    finally:
        for conn in connections.values():
            conn.close()

    equivalent = (
        all(item["match"] for item in comparisons.values())
        and all(item["integrity_check"] == "ok" for item in diagnostics.values())
        and all(item["foreign_key_violations"] == 0 for item in diagnostics.values())
    )
    payload = {
        "schema_version": "pcb_equipment.release_equivalence.v1",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "industry": {"id": 23, "name": "PCB专用设备"},
        "databases": diagnostics,
        "comparisons": comparisons,
        "equivalent": equivalent,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["content_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "sha256": _sha256(output), "equivalent": equivalent,
                      "comparisons": comparisons}, ensure_ascii=False, indent=2))
    if not equivalent:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
