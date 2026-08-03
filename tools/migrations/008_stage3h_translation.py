#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stage 3-H P4.1 migration 008 — 翻译字段(voice 全文中译 + news 标题/摘要中译)。
只新增列,不动行数据。news 不加 content_text_zh(全文翻译 token 太大,只翻 title+summary)。"""
import sqlite3
from pathlib import Path
DB = Path(__file__).resolve().parent.parent.parent / "data" / "research.db"
ADD = {
    "voice_post": [("content_text_zh","TEXT"),("ai_summary_zh","TEXT"),("translated_at","TEXT"),("translated_by","TEXT")],
    "news_item":  [("title_zh","TEXT"),("summary_zh","TEXT"),("translated_at","TEXT"),("translated_by","TEXT")],
}
def main():
    con=sqlite3.connect(str(DB)); cur=con.cursor(); added=[]
    for t,cols in ADD.items():
        ex={r[1] for r in cur.execute(f"PRAGMA table_info({t})")}
        for n,ty in cols:
            if n not in ex: cur.execute(f"ALTER TABLE {t} ADD COLUMN {n} {ty}"); added.append(f"{t}.{n}")
    con.commit()
    print("新增列:", added if added else "(已存在)")
    for t,n in (("voice_post",40),("news_item",604)):
        print(f"  {t}: {cur.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]} 行(期望 {n})")
    con.close(); print("MIGRATION 008 DONE")
if __name__=="__main__": main()
