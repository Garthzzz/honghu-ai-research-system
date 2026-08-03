#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""信源链路重构 P1 — migration 011:dynamic_seen 判定前去重账本(D6)。

作用:
  1. 省 token —— 判定前先查 dynamic_seen,已判过的 url/post 跳过,**不重发 DeepSeek B1**
     (防每小时 tick 对同一批旧条目反复烧 B1 token)。
  2. 校准底料 —— importance_raw 存 B1 原始 1-5(?? 含被丢弃条目),用户"看真实分布再收紧
     min_importance"靠一句 SQL 查本表,不必解析 jsonl:
        SELECT importance_raw, COUNT(*) FROM dynamic_seen
        WHERE kind='news' AND is_relevant=1 GROUP BY importance_raw;
  3. 可回溯 —— 被丢弃条目只进本表(不入 news_item / voice_post 正式表);
     保留条目 verdict='kept' 且同时入正式表。

dedup_key 约定:news = url;voice = f"{leader_id}:{post_id}"(写入侧负责生成)。
verdict 取值:
  kept                  双闸通过,入正式表
  dropped_prefilter     漏斗 A 关键词预过滤杀(未到 B1,is_relevant/importance_raw 为 NULL)
  dropped_irrelevant    B1 判 is_relevant=false
  dropped_importance    B1 importance 超 topic_gate.min_importance

留存策略(D6):dropped_* 记录默认保留 RETENTION_DAYS 天(供校准/回溯)后可 prune;
  kept 记录**不 prune**(与 news_item 永久去重一致,避免已入库条目被重判)。
  prune 仅手动 / scheduler 定期调用,本 migration **不自动删**。

?? 红线:只建表 + 索引,不动任何现有表 / 行。幂等:CREATE ... IF NOT EXISTS。
?? 本文件仅供审阅 —— 执行需 user 批准(阶段 0 审过后再跑 `python 011_p1_dynamic_seen.py`)。
"""
import sqlite3, sys, io
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

DB = Path(__file__).resolve().parent.parent.parent / "data" / "research.db"
RETENTION_DAYS = 30   # dropped_* 留存天数(可调);kept 永久

DDL = r"""
CREATE TABLE IF NOT EXISTS dynamic_seen (
  id               INTEGER PRIMARY KEY,
  kind             TEXT NOT NULL,                 -- 'news' | 'voice'
  dedup_key        TEXT NOT NULL,                 -- news=url;voice='{leader_id}:{post_id}'
  url              TEXT,                          -- 信息列(news)
  post_id          TEXT,                          -- 信息列(voice)
  verdict          TEXT NOT NULL,                 -- kept / dropped_prefilter / dropped_irrelevant / dropped_importance
  is_relevant      INTEGER,                       -- B1 判定 0/1(prefilter 杀的为 NULL)
  importance_raw   INTEGER,                       -- ?? B1 原始 1-5(校准底料);prefilter 杀的为 NULL
  relevance_reason TEXT,                          -- 理由非空(A 预过滤理由 / B1 判定理由)
  seen_at          TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE (kind, dedup_key),
  CHECK (kind IN ('news','voice')),
  CHECK (verdict IN ('kept','dropped_prefilter','dropped_irrelevant','dropped_importance')),
  CHECK (importance_raw IS NULL OR importance_raw BETWEEN 1 AND 5)
);
CREATE INDEX IF NOT EXISTS idx_seen_kind_time  ON dynamic_seen(kind, seen_at);
CREATE INDEX IF NOT EXISTS idx_seen_importance ON dynamic_seen(importance_raw);
CREATE INDEX IF NOT EXISTS idx_seen_verdict    ON dynamic_seen(verdict);
"""


def main():
    con = sqlite3.connect(str(DB)); cur = con.cursor()
    cur.executescript(DDL)
    con.commit()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(dynamic_seen)")]
    print("dynamic_seen 列:", cols)
    n = cur.execute("SELECT COUNT(*) FROM dynamic_seen").fetchone()[0]
    print(f"行数:{n}(新建应为 0)")
    con.close()
    print("MIGRATION 011 DONE")


def prune(days: int = RETENTION_DAYS):
    """留存清理:删 days 天前的 dropped_* 记录;kept 保留。仅手动 / scheduler 调,migration 不自动执行。"""
    con = sqlite3.connect(str(DB)); cur = con.cursor()
    r = cur.execute(
        "DELETE FROM dynamic_seen WHERE verdict LIKE 'dropped_%' "
        "AND seen_at < datetime('now','localtime',?)", (f"-{int(days)} days",))
    con.commit()
    print(f"prune: 删除 {r.rowcount} 条过期 dropped 记录(>{days}天)")
    con.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "prune":
        prune(int(sys.argv[2]) if len(sys.argv) > 2 else RETENTION_DAYS)
    else:
        main()
