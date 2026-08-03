#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""信源链路重构 P1 — migration 010:news_item 补 DeepSeek 摘要 + 正文中译 4 列。

背景(只读核对 2026-06-09):
  news_item 现有 summary(RSS verbatim,004)/ summary_zh(008)/ title_zh(008)/
  translated_at / translated_by(008),但**缺** ai_summary 三件套 + content_text_zh。
  voice_post 已全有(004 的 ai_summary 三件套 + 008 的 content_text_zh / ai_summary_zh)。
  本 migration 让 news_item 对齐 voice_post 的 AI 摘要 provenance 能力。

字段语义(写入约定见 DESIGN §2.5 字段映射表):
  ai_summary              DeepSeek B2 生成的 AI 摘要(news 统一产中文摘要;= B2.summary_zh 落点)
  ai_summary_source_ids   JSON [source.id] 溯源(对齐 voice_post,默认 = 本条 source_id)
  ai_summary_generated_at 生成时间戳
  content_text_zh         正文中译(?? 仅非中文源产;中文源留 NULL,见 D1 条件触发)

?? 红线:只新增列,不动任何行数据;importance CHECK IN(1,2,3) 不改
   (过闸入表的 importance 本就 ≤3;B1 原始 1-5 落 dynamic_seen,不入 news_item)。
?? 幂等:列存在则跳过(ADD COLUMN guarded)。
?? 本文件仅供审阅 —— 执行需 user 批准(阶段 0 审过后再跑 `python 010_p1_news_ai_cols.py`)。
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent.parent / "data" / "research.db"

ADD = {
    "news_item": [
        ("ai_summary",              "TEXT"),
        ("ai_summary_source_ids",   "TEXT"),
        ("ai_summary_generated_at", "TEXT"),
        ("content_text_zh",         "TEXT"),
    ],
}


def main():
    con = sqlite3.connect(str(DB)); cur = con.cursor(); added = []
    for t, cols in ADD.items():
        ex = {r[1] for r in cur.execute(f"PRAGMA table_info({t})")}
        for name, typ in cols:
            if name not in ex:
                cur.execute(f"ALTER TABLE {t} ADD COLUMN {name} {typ}")
                added.append(f"{t}.{name}")
    con.commit()
    print("新增列:", added if added else "(已存在,跳过)")

    # 数据未动校验(期望 604 行)
    c = cur.execute("SELECT COUNT(*) FROM news_item").fetchone()[0]
    print(f"  news_item: {c} 行(期望 604,数据不动)")

    # importance CHECK 未改校验
    sql = cur.execute("SELECT sql FROM sqlite_master WHERE name='news_item'").fetchone()[0]
    print("  importance CHECK IN(1,2,3) 保持:", "CHECK (importance IN (1,2,3))" in sql)

    # 4 列就位校验
    now_cols = {r[1] for r in cur.execute("PRAGMA table_info(news_item)")}
    want = {"ai_summary", "ai_summary_source_ids", "ai_summary_generated_at", "content_text_zh"}
    print("  4 列就位:", want <= now_cols, "缺:", sorted(want - now_cols) or "无")
    con.close()
    print("MIGRATION 010 DONE")


if __name__ == "__main__":
    main()
