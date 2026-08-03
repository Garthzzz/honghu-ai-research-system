from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from tools.opportunity_lens.constants import DB_PATH
from tools.opportunity_lens.metric_slot_gaps import summarize_missing_metric_slots


def _connect(path: Path, *, readonly: bool) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def collect_updates(conn: sqlite3.Connection, run_ids: list[int]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in run_ids)
    readiness_rows = conn.execute(
        f"""
        SELECT id, run_id, entity_id, factor_code, missing_reason
        FROM opportunity_factor_readiness
        WHERE run_id IN ({placeholders})
        ORDER BY run_id, entity_id, factor_code, id
        """,
        run_ids,
    ).fetchall()
    updates: list[dict[str, Any]] = []
    for row in readiness_rows:
        current = str(row["missing_reason"] or "").strip() or None
        if current:
            continue
        slots = [
            dict(item)
            for item in conn.execute(
                """
                SELECT slot_key, slot_label, metric_name, value_status, slot_score,
                       scoring_eligibility
                FROM opportunity_metric_slot
                WHERE run_id=? AND entity_id=? AND factor_code=?
                ORDER BY slot_key
                """,
                (row["run_id"], row["entity_id"], row["factor_code"]),
            ).fetchall()
        ]
        reason = summarize_missing_metric_slots(slots)
        if reason:
            updates.append(
                {
                    "id": int(row["id"]),
                    "run_id": int(row["run_id"]),
                    "entity_id": int(row["entity_id"]),
                    "factor_code": str(row["factor_code"]),
                    "before": current,
                    "after": reason,
                }
            )
    return updates


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill human-readable Opportunity Lens factor evidence gaps."
    )
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--run-id", type=int, action="append", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    run_ids = sorted(set(args.run_id))
    conn = _connect(args.db, readonly=not args.apply)
    try:
        updates = collect_updates(conn, run_ids)
        if args.apply:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for item in updates:
                    conn.execute(
                        "UPDATE opportunity_factor_readiness SET missing_reason=? WHERE id=?",
                        (item["after"], item["id"]),
                    )
                violations = conn.execute("PRAGMA foreign_key_check").fetchall()
                if violations:
                    raise RuntimeError(f"foreign_key_check failed: {violations[:5]}")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        print(
            json.dumps(
                {
                    "db": str(args.db.resolve()),
                    "run_ids": run_ids,
                    "mode": "apply" if args.apply else "dry_run",
                    "update_count": len(updates),
                    "updates_by_run": {
                        str(run_id): sum(1 for item in updates if item["run_id"] == run_id)
                        for run_id in run_ids
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
