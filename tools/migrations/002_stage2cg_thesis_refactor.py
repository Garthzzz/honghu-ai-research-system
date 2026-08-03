#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stage 2c-G migration 002 — thesis 模块重构

任务 5:company_thesis 删 validation_signals + invalidation_signals → 单字段 monitoring_signals。
        (2c-F 建表后 0 行,无迁移负担 → 直接重建。)
任务 3B:新增 industry_thesis 表(行业层级反共识 + AI 一致预期 + 溯源)。
任务 4:company_thesis / industry_thesis 都加 consensus_source_ids + consensus_generated_at(AI 总结溯源 + 时间戳)。

幂等:重建前先确认 company_thesis 行数=0(>0 则中止,避免毁数据);industry_thesis IF NOT EXISTS。
"""
import sqlite3, sys
from pathlib import Path
DB = Path(__file__).resolve().parent.parent.parent / "data" / "research.db"

NEW_COMPANY_THESIS = """
CREATE TABLE company_thesis (
  id                    INTEGER PRIMARY KEY,
  company_id            INTEGER NOT NULL,
  industry_id           INTEGER,
  consensus_view        TEXT,                  -- AI 总结的一致预期(可被研究员覆盖)
  consensus_source_ids  TEXT,                  -- JSON 溯源
  consensus_generated_at TEXT,                 -- AI 生成时间戳(人工覆盖后清空/留痕)
  contrarian_thesis     TEXT,                  -- 研究员手填:反共识 / 超预期
  monitoring_signals    TEXT,                  -- 研究员手填:监控指标(证实/证伪信号,合并)
  conviction_level      INTEGER,
  author                TEXT DEFAULT 'zhengze',
  updated_at            TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE(company_id, industry_id)
);
"""

INDUSTRY_THESIS = """
CREATE TABLE IF NOT EXISTS industry_thesis (
  id                    INTEGER PRIMARY KEY,
  industry_id           INTEGER NOT NULL UNIQUE,
  consensus_view        TEXT,                  -- AI 总结的一致预期
  consensus_source_ids  TEXT,                  -- JSON 溯源
  consensus_updated_at  TEXT,                  -- AI 生成 / 人工复核时间
  consensus_author      TEXT DEFAULT 'ai_consensus',
  contrarian_thesis     TEXT,                  -- 研究员手填:反共识 / 超预期
  monitoring_signals    TEXT,                  -- 研究员手填:监控指标(证实/证伪合并)
  conviction_level      INTEGER,
  author                TEXT DEFAULT 'zhengze',
  updated_at            TEXT DEFAULT (datetime('now','localtime'))
);
"""

def main():
    con = sqlite3.connect(str(DB)); cur = con.cursor()
    # company_thesis 重建(确认 0 行)
    n = cur.execute("SELECT COUNT(*) FROM company_thesis").fetchone()[0]
    if n > 0:
        print(f"中止:company_thesis 有 {n} 行,重建会毁数据。请先人工迁移。")
        sys.exit(1)
    cur.execute("DROP TABLE IF EXISTS company_thesis")
    cur.executescript(NEW_COMPANY_THESIS)
    cur.executescript(INDUSTRY_THESIS)
    con.commit()
    ct_cols = [r[1] for r in cur.execute("PRAGMA table_info(company_thesis)")]
    it_cols = [r[1] for r in cur.execute("PRAGMA table_info(industry_thesis)")]
    print("company_thesis 列:", ct_cols)
    print("  monitoring_signals 在:", "monitoring_signals" in ct_cols,
          "| validation 已删:", "validation_signals" not in ct_cols)
    print("industry_thesis 列:", it_cols)
    con.close()
    print("MIGRATION 002 DONE")

if __name__ == "__main__":
    main()
