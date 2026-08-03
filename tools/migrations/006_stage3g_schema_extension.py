#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stage 3-G migration 006 — schema 扩展(只新增字段,不动现有数据)

A2:subtopic(news_item/voice_post/event)— vocab §22 细分
A3:is_ai_relevant + relevance_reason(news_item/voice_post/event)— 反向过滤(默认 1,classifier 改)
B4:voice_post 加 parent_post_text(被转推文)+ media_urls(JSON 图片/视频)
幂等:列存在则跳过。现有 137 news / 40 voice / 22 event 数据不动。
"""
import sqlite3, sys
from pathlib import Path
DB = Path(__file__).resolve().parent.parent.parent / "data" / "research.db"

ADD = {
    "news_item":  [("subtopic","TEXT"), ("is_ai_relevant","INTEGER DEFAULT 1"), ("relevance_reason","TEXT")],
    "voice_post": [("subtopic","TEXT"), ("is_ai_relevant","INTEGER DEFAULT 1"), ("relevance_reason","TEXT"),
                   ("parent_post_text","TEXT"), ("media_urls","TEXT")],
    "event":      [("subtopic","TEXT"), ("is_ai_relevant","INTEGER DEFAULT 1")],
}

def main():
    con = sqlite3.connect(str(DB)); cur = con.cursor()
    added = []
    for tbl, cols in ADD.items():
        ex = {r[1] for r in cur.execute(f"PRAGMA table_info({tbl})")}
        for name, typ in cols:
            if name not in ex:
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN {name} {typ}")
                added.append(f"{tbl}.{name}")
    con.commit()
    print("新增列:", added if added else "(已存在,跳过)")
    # 数据未动校验
    for t, n in (("news_item",137),("voice_post",40),("event",22)):
        c = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {c} 行(期望 {n})")
    con.close()
    print("MIGRATION 006 DONE")

if __name__ == "__main__":
    main()
