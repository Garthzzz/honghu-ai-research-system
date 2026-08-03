from __future__ import annotations

"""Create or compare a read-only, run-scoped Opportunity Lens DB snapshot."""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


SPECIAL_TABLES = {
    "opportunity_entity",
    "opportunity_run",
    "opportunity_section_evidence_link",
    "opportunity_slot_data_point_link",
    "opportunity_visual_evidence_link",
}


def _encode(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"blob_sha256": hashlib.sha256(value).hexdigest(), "size": len(value)}
    return value


def _where_clause(table: str, columns: set[str], run_min: int, run_max: int) -> str | None:
    scope = f"BETWEEN {run_min} AND {run_max}"
    if table == "opportunity_run":
        return f"id {scope}"
    if table == "opportunity_entity":
        return (
            "id IN (SELECT entity_id FROM opportunity_entity_maturation "
            f"WHERE run_id {scope})"
        )
    if table == "opportunity_section_evidence_link":
        return (
            "section_id IN (SELECT id FROM opportunity_report_section "
            f"WHERE run_id {scope})"
        )
    if table == "opportunity_slot_data_point_link":
        return " OR ".join(
            (
                "slot_id IN (SELECT id FROM opportunity_metric_slot "
                f"WHERE run_id {scope})",
                "data_point_id IN (SELECT id FROM opportunity_data_point "
                f"WHERE run_id {scope})",
                "claim_id IN (SELECT id FROM opportunity_claim_evidence "
                f"WHERE run_id {scope})",
            )
        )
    if table == "opportunity_visual_evidence_link":
        parents = {
            "visual_block_id": "opportunity_visual_block",
            "source_id": "opportunity_source",
            "data_point_id": "opportunity_data_point",
            "metric_slot_id": "opportunity_metric_slot",
            "factor_score_id": "opportunity_factor_score",
            "composite_score_id": "opportunity_composite_score",
            "event_id": "opportunity_event_ledger",
            "audit_issue_id": "opportunity_audit_issue",
            "supplement_request_id": "opportunity_supplement_request",
        }
        terms = [
            f'{column} IN (SELECT id FROM {parent} WHERE run_id {scope})'
            for column, parent in parents.items()
            if column in columns
        ]
        return " OR ".join(terms) or None
    if "run_id" in columns:
        return f"run_id {scope}"
    return None


def snapshot(db_path: Path, run_min: int, run_max: int) -> dict[str, Any]:
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    try:
        tables = [
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name LIKE 'opportunity_%' ORDER BY name"
            )
            if str(row[0]) != "opportunity_schema_meta"
        ]
        results: dict[str, Any] = {}
        for table in tables:
            columns = [str(row["name"]) for row in conn.execute(f'PRAGMA table_info("{table}")')]
            where = _where_clause(table, set(columns), run_min, run_max)
            if where is None:
                continue
            order = ", ".join(f'"{column}"' for column in columns)
            rows = conn.execute(
                f'SELECT * FROM "{table}" WHERE {where} ORDER BY {order}'
            ).fetchall()
            encoded = [
                {column: _encode(row[column]) for column in columns}
                for row in rows
            ]
            canonical = json.dumps(
                encoded, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            results[table] = {
                "row_count": len(encoded),
                "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            }
        overall = json.dumps(results, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return {
            "schema_version": "opportunity_lens.run_snapshot.v1",
            "db_path": str(db_path.resolve()),
            "run_range": [run_min, run_max],
            "table_count": len(results),
            "tables": results,
            "overall_sha256": hashlib.sha256(overall.encode("utf-8")).hexdigest(),
            "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_issue_count": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("db", type=Path)
    parser.add_argument("--run-min", type=int, default=1)
    parser.add_argument("--run-max", type=int, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()
    if args.run_min < 1 or args.run_max < args.run_min:
        parser.error("run range is invalid")
    result = snapshot(args.db, args.run_min, args.run_max)
    if args.compare:
        baseline = json.loads(args.compare.read_text(encoding="utf-8"))
        changed = sorted(
            table
            for table in set(baseline.get("tables", {})) | set(result.get("tables", {}))
            if baseline.get("tables", {}).get(table) != result.get("tables", {}).get(table)
        )
        result["comparison"] = {
            "baseline": str(args.compare.resolve()),
            "unchanged": not changed,
            "changed_tables": changed,
        }
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if result["integrity_check"] != "ok" or result["foreign_key_issue_count"]:
        return 1
    if args.compare and not result["comparison"]["unchanged"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
