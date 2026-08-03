#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stage 4-A migration 009 — 研究员投资假说模块(5 表 + seed 6 researcher)。

?? 反 slop:
  - 只建表 + seed 6 个研究员名字(focus 留空给 user 填);绝不预填任何假说内容。
  - 研究员名单严格 6 人:潘毅 / 石一玮 / 吴博闻 / 吴行健 / 马志远 / 张正泽,CC 不自加。
  - 幂等:CREATE TABLE IF NOT EXISTS + INSERT OR IGNORE(按 name UNIQUE)。
  - 只新增表,绝不动现有 idp/cp/industry_thesis/news/voice/event 行数据。
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent.parent / "data" / "research.db"

# ?? user 给定的 6 人(顺序即录入顺序;focus 字段一律留空,user/各研究员自填)
RESEARCHERS = ["潘毅", "石一玮", "吴博闻", "吴行健", "马志远", "张正泽"]

DDL = [
    # ── 表 1:researcher(研究员名单)──────────────────────────
    """
    CREATE TABLE IF NOT EXISTS researcher (
      id              INTEGER PRIMARY KEY,
      name            TEXT NOT NULL,
      display_name    TEXT,
      email           TEXT,
      avatar_url      TEXT,
      bio             TEXT,
      focus_industries TEXT,                 -- JSON [industry_id]
      focus_summary   TEXT,
      is_active       INTEGER DEFAULT 1,
      joined_at       TEXT DEFAULT (datetime('now','localtime')),
      created_at      TEXT DEFAULT (datetime('now','localtime')),
      updated_at      TEXT DEFAULT (datetime('now','localtime')),
      UNIQUE (name)
    )""",
    # ── 表 2:hypothesis(假说主体)──────────────────────────
    """
    CREATE TABLE IF NOT EXISTS hypothesis (
      id                    INTEGER PRIMARY KEY,
      researcher_id         INTEGER NOT NULL,
      title                 TEXT NOT NULL,
      hypothesis_text       TEXT NOT NULL,
      thesis_type           TEXT NOT NULL,
      status                TEXT NOT NULL DEFAULT 'active',
      conviction_level      INTEGER,
      is_draft              INTEGER DEFAULT 0,
      related_industry_ids  TEXT,             -- JSON [industry_id]
      related_company_ids   TEXT,             -- JSON [company_id]
      horizon_months        INTEGER,
      cite_source_ids       TEXT,             -- JSON [source.id]
      cite_news_ids         TEXT,             -- JSON [news_item.id]
      cite_voice_ids        TEXT,             -- JSON [voice_post.id]
      cite_event_ids        TEXT,             -- JSON [event.id]
      created_at            TEXT DEFAULT (datetime('now','localtime')),
      last_updated_at       TEXT,
      falsified_at          TEXT,
      confirmed_at          TEXT,
      FOREIGN KEY (researcher_id) REFERENCES researcher(id),
      CHECK (thesis_type IN ('bullish','bearish','neutral','contrarian')),
      CHECK (status IN ('active','partially_falsified','falsified','confirmed','withdrawn')),
      CHECK (conviction_level IS NULL OR conviction_level BETWEEN 1 AND 5)
    )""",
    # ── 表 3:hypothesis_monitoring_signal(证伪条件 / 监控指标)──
    """
    CREATE TABLE IF NOT EXISTS hypothesis_monitoring_signal (
      id                INTEGER PRIMARY KEY,
      hypothesis_id     INTEGER NOT NULL,
      signal_type       TEXT NOT NULL,
      description       TEXT NOT NULL,
      observation_target TEXT,
      current_status    TEXT NOT NULL DEFAULT 'not_triggered',
      last_check_at     TEXT,
      last_check_note   TEXT,
      ai_check_keywords TEXT,                 -- JSON ["关键词", ...]
      display_order     INTEGER DEFAULT 0,
      created_at        TEXT DEFAULT (datetime('now','localtime')),
      updated_at        TEXT DEFAULT (datetime('now','localtime')),
      FOREIGN KEY (hypothesis_id) REFERENCES hypothesis(id),
      CHECK (signal_type IN ('falsification','confirmation','monitor')),
      CHECK (current_status IN ('not_triggered','partially_triggered','triggered','contradicted'))
    )""",
    # ── 表 4:hypothesis_trade(交易方案,正向 + 反向)────────────
    """
    CREATE TABLE IF NOT EXISTS hypothesis_trade (
      id              INTEGER PRIMARY KEY,
      hypothesis_id   INTEGER NOT NULL,
      trade_scenario  TEXT NOT NULL,
      direction       TEXT NOT NULL,
      target_industry_ids TEXT,              -- JSON [industry_id]
      target_company_ids  TEXT,              -- JSON [company_id]
      target_description  TEXT NOT NULL,
      position_sizing TEXT,
      entry_trigger   TEXT,
      exit_trigger    TEXT,
      status          TEXT NOT NULL DEFAULT 'proposed',
      display_order   INTEGER DEFAULT 0,
      created_at      TEXT DEFAULT (datetime('now','localtime')),
      updated_at      TEXT DEFAULT (datetime('now','localtime')),
      FOREIGN KEY (hypothesis_id) REFERENCES hypothesis(id),
      CHECK (trade_scenario IN ('primary','falsification_reverse')),
      CHECK (direction IN ('long','short','neutral','pair')),
      CHECK (status IN ('proposed','active','closed_profit','closed_loss','abandoned'))
    )""",
    # ── 表 5:hypothesis_update(版本化更新日志,append-only)──────
    """
    CREATE TABLE IF NOT EXISTS hypothesis_update (
      id              INTEGER PRIMARY KEY,
      hypothesis_id   INTEGER NOT NULL,
      updated_by      INTEGER NOT NULL,
      update_type     TEXT NOT NULL,
      update_note     TEXT,
      snapshot_status TEXT,
      snapshot_text   TEXT,
      snapshot_conviction INTEGER,
      triggered_by_news_id  INTEGER,
      triggered_by_event_id INTEGER,
      created_at      TEXT DEFAULT (datetime('now','localtime')),
      FOREIGN KEY (hypothesis_id) REFERENCES hypothesis(id),
      FOREIGN KEY (updated_by) REFERENCES researcher(id),
      FOREIGN KEY (triggered_by_news_id) REFERENCES news_item(id),
      FOREIGN KEY (triggered_by_event_id) REFERENCES event(id),
      CHECK (update_type IN ('create','edit_text','status_change','signal_update','trade_update','cite_add'))
    )""",
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_hyp_researcher ON hypothesis(researcher_id)",
    "CREATE INDEX IF NOT EXISTS idx_hyp_status ON hypothesis(status)",
    "CREATE INDEX IF NOT EXISTS idx_sig_hyp ON hypothesis_monitoring_signal(hypothesis_id)",
    "CREATE INDEX IF NOT EXISTS idx_trade_hyp ON hypothesis_trade(hypothesis_id)",
    "CREATE INDEX IF NOT EXISTS idx_update_hyp ON hypothesis_update(hypothesis_id)",
]


def main():
    con = sqlite3.connect(str(DB)); cur = con.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    for ddl in DDL:
        cur.execute(ddl)
    for idx in INDEXES:
        cur.execute(idx)
    # seed 6 researcher(仅 name + display_name=name;focus 全留空给 user 手填)
    ins = 0
    for nm in RESEARCHERS:
        r = cur.execute("INSERT OR IGNORE INTO researcher(name, display_name) VALUES(?,?)", (nm, nm))
        ins += r.rowcount
    con.commit()

    # ── 验证 ──
    tabs = {r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'hypothesis%' OR name='researcher'")}
    want = {"researcher", "hypothesis", "hypothesis_monitoring_signal", "hypothesis_trade", "hypothesis_update"}
    print("建表:", sorted(tabs & want), "缺:", sorted(want - tabs) or "无")
    rs = cur.execute("SELECT id, name FROM researcher ORDER BY id").fetchall()
    print(f"researcher 入库 {len(rs)} 行(本次新增 {ins}):", [f"{r[0]}:{r[1]}" for r in rs])
    nh = cur.execute("SELECT COUNT(*) FROM hypothesis").fetchone()[0]
    print(f"hypothesis 预填检查:{nh} 条(必须为 0 —— CC 不预填)")
    assert want <= tabs, "缺表!"
    assert nh == 0, "检测到预填假说,违反红线!"
    con.close()
    print("MIGRATION 009 DONE")


if __name__ == "__main__":
    main()
