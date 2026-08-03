#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""星瀚情绪重构 v4 schema 迁移(只写 sentiment.db)。幂等。

1) 散户/热度桶+日表 增列 n_ths / n_eastmoney(同花顺/东方财富 平台计数)。
2) 新股注册(T4):senti_company —— 全集中不在 research.db 的个股,独立 id 空间(900001+),
   守隔离(绝不写 research.db);别名进 company_alias(同 id)供 AliasIndex 归因。
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

TZ = timezone(timedelta(hours=8))


def add_col(con, table, col, decl):
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
    if col not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        return True
    return False

DDL = """
CREATE TABLE IF NOT EXISTS senti_company (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  ticker TEXT,
  industry TEXT,
  created_at TEXT,
  note TEXT
);
"""


def main():
    con = common.get_senti_db()
    common.assert_senti_only(con)
    added = []
    for t in ("senti_retail_bucket", "senti_retail_daily", "heat_volume_bucket", "heat_volume_daily"):
        for col in ("n_ths", "n_eastmoney"):
            if add_col(con, t, col, "INTEGER DEFAULT 0"):
                added.append(f"{t}.{col}")
    con.executescript(DDL)
    con.commit()
    tbls = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='senti_company' ORDER BY name")]
    print("?? v4 迁移完成")
    print("  增列:", ", ".join(added) or "(已存在)")
    print("  新表:", ", ".join(tbls))
    con.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
