#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""信源链路重构 P1 — migration 012:opinion_leader.is_featured 精选标记。

背景:意见领袖增至 10+ 后,首页/观点流不应给每个领袖都摆卡片。is_featured=1 的少数
"高质量索引"才上卡片墙,其余通过筛选(?all_leaders=1 / leader 下拉)手动找出。

?? 红线:只加一列(幂等 ALTER),不动任何现有行/列。默认 0(不精选)。
?? 执行:python 012_p1_leader_featured.py
"""
import sqlite3, sys, io
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

DB = Path(__file__).resolve().parent.parent.parent / "data" / "research.db"


def main():
    con = sqlite3.connect(str(DB)); cur = con.cursor()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(opinion_leader)")]
    if "is_featured" not in cols:
        cur.execute("ALTER TABLE opinion_leader ADD COLUMN is_featured INTEGER NOT NULL DEFAULT 0")
        con.commit()
        print("已加列 opinion_leader.is_featured (DEFAULT 0)")
    else:
        print("opinion_leader.is_featured 已存在,跳过")
    cols = [r[1] for r in cur.execute("PRAGMA table_info(opinion_leader)")]
    print("opinion_leader 列:", cols)
    con.close()
    print("MIGRATION 012 DONE")


if __name__ == "__main__":
    main()
