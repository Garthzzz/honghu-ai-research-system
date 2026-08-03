#!/usr/bin/env python
"""Prove that the PCB-equipment release did not change out-of-scope research rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BEFORE = Path(r"D:\quant\industry_demo_backup_20260719_2215_pre_pcb_equipment_publish\research_pre_pcb_publish.db")
DEFAULT_AFTER = ROOT / "data" / "research.db"
DEFAULT_SOURCE_MAP = ROOT / "cache" / "db_queue" / "pcb_equipment_b_20260719_source_map.json"
DEFAULT_OUTPUT = ROOT / "cache" / "pcb_equipment_research" / "live_release_scope_audit.json"


def _rows(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    values = [tuple(row) for row in conn.execute(query, params)]
    values.sort(key=repr)
    return values


def _digest(values: list[tuple[Any, ...]]) -> str:
    return hashlib.sha256(repr(values).encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, default=DEFAULT_BEFORE)
    parser.add_argument("--after", type=Path, default=DEFAULT_AFTER)
    parser.add_argument("--source-map", type=Path, default=DEFAULT_SOURCE_MAP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    before_path = args.before.resolve()
    after_path = args.after.resolve()
    before = sqlite3.connect(before_path)
    after = sqlite3.connect(after_path)
    try:
        target_company_ids = sorted(
            row[0] for row in after.execute(
                "SELECT company_id FROM company_industry WHERE industry_id=23"
            )
        )
        source_ids = sorted(set(json.loads(args.source_map.read_text(encoding="utf-8")).values()))
        company_marks = ",".join("?" for _ in target_company_ids)
        source_marks = ",".join("?" for _ in source_ids)
        scoped_queries = {
            "industry": ("SELECT * FROM industry WHERE id<>23", ()),
            "industry_data_point": ("SELECT * FROM industry_data_point WHERE industry_id<>23", ()),
            "data_point_peer_group": ("SELECT * FROM data_point_peer_group WHERE industry_id<>23", ()),
            "company_industry": ("SELECT * FROM company_industry WHERE industry_id<>23", ()),
            "company_profile": ("SELECT * FROM company_profile WHERE industry_id<>23", ()),
            "company_sub_market_share": (
                "SELECT * FROM company_sub_market_share WHERE industry_id<>23", (),
            ),
            "industry_relation": (
                "SELECT * FROM industry_relation WHERE upstream_id<>23 AND downstream_id<>23", (),
            ),
            "company": (
                f"SELECT * FROM company WHERE id NOT IN ({company_marks})", tuple(target_company_ids),
            ),
            "source": (f"SELECT * FROM source WHERE id NOT IN ({source_marks})", tuple(source_ids)),
            "source_entity": (
                "SELECT * FROM source_entity WHERE NOT (entity_type='industry' AND entity_id='23')", (),
            ),
            "md_section_version": (
                "SELECT * FROM md_section_version "
                "WHERE md_path NOT LIKE 'docs/industries/PCB专用设备%'", (),
            ),
        }
        tables = [
            row[0] for row in after.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        comparisons = {}
        full_table_changes = []
        for table in tables:
            before_full = _rows(before, f'SELECT * FROM "{table}"')
            after_full = _rows(after, f'SELECT * FROM "{table}"')
            if _digest(before_full) != _digest(after_full):
                full_table_changes.append(table)
            query, params = scoped_queries.get(table, (f'SELECT * FROM "{table}"', ()))
            before_rows = _rows(before, query, params)
            after_rows = _rows(after, query, params)
            comparisons[table] = {
                "before_count": len(before_rows),
                "after_count": len(after_rows),
                "before_sha256": _digest(before_rows),
                "after_sha256": _digest(after_rows),
                "out_of_scope_match": before_rows == after_rows,
            }
        integrity = {
            "before": before.execute("PRAGMA integrity_check").fetchone()[0],
            "after": after.execute("PRAGMA integrity_check").fetchone()[0],
            "before_foreign_key_violations": len(before.execute("PRAGMA foreign_key_check").fetchall()),
            "after_foreign_key_violations": len(after.execute("PRAGMA foreign_key_check").fetchall()),
        }
    finally:
        before.close()
        after.close()

    passed = (
        all(item["out_of_scope_match"] for item in comparisons.values())
        and integrity["before"] == integrity["after"] == "ok"
        and integrity["before_foreign_key_violations"] == 0
        and integrity["after_foreign_key_violations"] == 0
    )
    payload = {
        "schema_version": "pcb_equipment.release_scope_audit.v1",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "before": {"path": str(before_path), "sha256": _sha256(before_path)},
        "after": {"path": str(after_path), "sha256": _sha256(after_path)},
        "authorized_scope": {
            "industry_id": 23,
            "company_ids": target_company_ids,
            "source_ids": source_ids,
        },
        "full_table_changes": full_table_changes,
        "comparisons": comparisons,
        "integrity": integrity,
        "out_of_scope_unchanged": passed,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["content_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "sha256": _sha256(output),
        "out_of_scope_unchanged": passed,
        "full_table_changes": full_table_changes,
        "checked_tables": len(comparisons),
    }, ensure_ascii=False, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
