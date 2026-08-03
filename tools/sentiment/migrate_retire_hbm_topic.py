#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""精确退役“HBM/存储 供给拐点”专题的 SQLite 对象。

默认使用只读连接生成 dry-run 报告；只有显式传入 ``--apply`` 才会在
一个 ``BEGIN IMMEDIATE`` 事务中删除五张专题专属表。脚本采用固定白名单，
不会删除存储行业研究数据、机会透镜 run 或其他情绪数据。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "sentiment.db"
SCHEMA_VERSION = "sentiment.hbm_topic_retirement.v1"

# 逻辑子表在前、专题元信息在后。当前 schema 没有声明外键，但固定顺序可让
# 迁移在未来补上约束后仍保持清晰、安全。
TABLES = (
    "topic_fact",
    "topic_scenario",
    "topic_tornado",
    "topic_path",
    "topic_meta",
)


def _connect(db_path: Path, *, apply: bool) -> sqlite3.Connection:
    if apply:
        con = sqlite3.connect(str(db_path), timeout=60)
    else:
        # dry-run 必须是真只读，避免误建库或产生任何业务写入。
        con = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=60000")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _objects(con: sqlite3.Connection) -> dict[str, str]:
    placeholders = ",".join("?" for _ in TABLES)
    return {
        row["name"]: row["type"]
        for row in con.execute(
            f"SELECT name,type FROM sqlite_master WHERE name IN ({placeholders})",
            TABLES,
        )
    }


def retire(db_path: Path, *, apply: bool = False) -> dict:
    """报告或删除专题专属表；``apply=False`` 时保证只读。"""
    db_path = db_path.resolve()
    if not db_path.is_file():
        raise FileNotFoundError(db_path)

    con = _connect(db_path, apply=apply)
    try:
        existing = _objects(con)
        wrong_types = {
            name: obj_type for name, obj_type in existing.items() if obj_type != "table"
        }
        if wrong_types:
            raise RuntimeError(f"专题对象类型异常，拒绝迁移: {wrong_types}")

        counts = {
            table: con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            if table in existing
            else 0
            for table in TABLES
        }
        report = {
            "schema_version": SCHEMA_VERSION,
            "db": str(db_path),
            "mode": "apply" if apply else "dry_run",
            "allowed_tables": list(TABLES),
            "objects_present": existing,
            "rows_to_delete": counts,
            "rows_to_delete_total": sum(counts.values()),
        }
        if not apply:
            return report

        con.execute("BEGIN IMMEDIATE")
        for table in TABLES:
            con.execute(f'DROP TABLE IF EXISTS "{table}"')

        remaining = _objects(con)
        if remaining:
            raise RuntimeError(f"专题对象仍然存在: {remaining}")

        foreign_key_issues = con.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_issues:
            raise RuntimeError(f"foreign_key_check failed: {len(foreign_key_issues)}")
        integrity_rows = [row[0] for row in con.execute("PRAGMA integrity_check")]
        if integrity_rows != ["ok"]:
            raise RuntimeError(f"integrity_check failed: {integrity_rows[:10]}")

        con.commit()
        report.update(
            {
                "rows_deleted_total": sum(counts.values()),
                "remaining": {},
                "foreign_key_issues": 0,
                "integrity_check": "ok",
            }
        )
        return report
    except Exception:
        if apply:
            con.rollback()
        raise
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="退役 HBM/存储供给拐点专题五张专属表；默认 dry-run"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(retire(args.db, apply=args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
