#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""精确退役关键词情绪专属 SQLite 对象。

默认只报告；只有 ``--apply`` 才在一个 IMMEDIATE 事务内删除四张专属表和审计 view。
个股 ``senti_raw`` 与所有 retail/news/heat 表不在允许清单中，脚本无法连带删除。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = ROOT / "data" / "sentiment.db"
TABLES = (
    "senti_keyword_raw",
    "keyword_sentiment_bucket",
    "keyword_sentiment_daily",
    "keyword_meta",
)
VIEWS = ("v_keyword_coverage_audit",)


def retire(db_path: Path, *, apply: bool) -> dict:
    db_path = db_path.resolve()
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    con = sqlite3.connect(str(db_path), timeout=60)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys=ON")
        existing = {r["name"]: r["type"] for r in con.execute(
            "SELECT name,type FROM sqlite_master WHERE name IN (%s)" % ",".join("?" * (len(TABLES) + len(VIEWS))),
            (*TABLES, *VIEWS),
        )}
        counts = {}
        for table in TABLES:
            counts[table] = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] if table in existing else 0
        report = {
            "db": str(db_path), "mode": "apply" if apply else "dry_run",
            "objects_present": existing, "rows_to_delete": counts,
            "allowed_tables": list(TABLES), "allowed_views": list(VIEWS),
        }
        if not apply:
            return report
        con.execute("BEGIN IMMEDIATE")
        for view in VIEWS:
            con.execute(f'DROP VIEW IF EXISTS "{view}"')
        for table in TABLES:
            con.execute(f'DROP TABLE IF EXISTS "{table}"')
        foreign_key_issues = con.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_issues:
            raise RuntimeError(f"foreign_key_check failed: {len(foreign_key_issues)}")
        remaining = [r["name"] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE name IN (%s)" % ",".join("?" * (len(TABLES) + len(VIEWS))),
            (*TABLES, *VIEWS),
        )]
        if remaining:
            raise RuntimeError(f"retired objects remain: {remaining}")
        con.commit()
        report["foreign_key_issues"] = 0
        report["remaining"] = []
        return report
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="退役关键词情绪专属表/view；默认 dry-run")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(retire(args.db, apply=args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
