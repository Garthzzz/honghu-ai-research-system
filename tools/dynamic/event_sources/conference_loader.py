#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
B2 大会事件加载 — 从 config.yaml conferences 段写 event(event_type='大会')

反 slop:严禁 CC 给 config 加新大会(只 user 加);日期/url 不可改。
幂等:INSERT OR IGNORE on UNIQUE(title, scheduled_date)(event_store.upsert_conference)。
"""
from __future__ import annotations
import sqlite3, sys, io
from pathlib import Path
from datetime import datetime

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DB = ROOT / "data" / "research.db"
CONFIG = ROOT / "tools" / "dynamic" / "config.yaml"
sys.path.insert(0, str(ROOT / "tools" / "dynamic"))
import event_store
import yaml
CFG = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def main():
    con = sqlite3.connect(str(DB))
    confs = CFG.get("conferences", [])
    ins = exists = 0
    for c in confs:
        desc = f"{c['title']}(大会,scheduled_date={c['date']} **confirmed**);config 硬编码,user 维护"
        r = event_store.upsert_conference(
            con, title=c["title"], scheduled_date=c["date"], importance=int(c["importance"]),
            related_industry_ids=c.get("industries"), official_url=c.get("url"), description=desc)
        print(f"  {c['title']:<22} {c['date']} L{c['importance']} -> {r}")
        if r == "inserted":
            ins += 1
        else:
            exists += 1
    con.commit()
    print(f"\nconfig 大会 {len(confs)} 条:新增 {ins} / 已存在 {exists}")
    con.close()
    return {"config": len(confs), "inserted": ins, "exists": exists}


if __name__ == "__main__":
    main()
