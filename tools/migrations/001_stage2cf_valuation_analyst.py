#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stage 2c-F 迁移:
  C1  company 表新增估值/盈利预测字段(roe/roa/ev_ebitda/ps/股息率 + 盈利预测 + 预测时点 + cell ^src 来源)
  D1  新增 analyst_note(研究员自由补充)+ company_thesis(反共识/超预期四件套)

幂等:每个 ALTER 前检查列是否已存在;CREATE TABLE IF NOT EXISTS。
不删除任何已有列/表。margins 仍由 company_profile 提供(不在 company 重复)。
"""
import sqlite3, sys
from pathlib import Path
DB = Path(__file__).resolve().parent.parent.parent / "data" / "research.db"

NEW_COMPANY_COLS = [
    ("roe",                  "REAL"),    # 净资产收益率 %
    ("roa",                  "REAL"),    # 总资产回报率 %
    ("ev_ebitda",            "REAL"),    # 企业价值/EBITDA
    ("ps_ttm",               "REAL"),    # 市销率 TTM
    ("dividend_yield",       "REAL"),    # 股息率 %
    ("peg",                  "REAL"),    # PEG
    ("forecast_eps_year1",   "REAL"),    # 一年后一致预期 EPS
    ("forecast_eps_year2",   "REAL"),    # 两年后一致预期 EPS
    ("forecast_revenue_year1","REAL"),   # 一年后一致预期营收(亿,原币)
    ("forecast_revenue_year2","REAL"),
    ("forecast_revenue_unit","TEXT"),
    ("forecast_as_of_date",  "TEXT"),    # ?? 梁总要的"预测时点"
    ("forecast_source_id",   "INTEGER"), # 盈利预测来源 source_id(cell ^src)
    ("valuation_source_id",  "INTEGER"), # 估值数据来源 source_id(cell ^src,通常 yfinance source)
]

ANALYST_NOTE_DDL = """
CREATE TABLE IF NOT EXISTS analyst_note (
  id          INTEGER PRIMARY KEY,
  entity_type TEXT NOT NULL,           -- 'company' / 'industry' / 'industry_q' / 'theme'
  entity_id   INTEGER NOT NULL,
  q_number    TEXT,                    -- entity_type='industry_q' 时记 Q0..Q6
  note_type   TEXT DEFAULT 'general',  -- general / thesis / contrarian / risk
  title       TEXT,
  content     TEXT NOT NULL,
  author      TEXT DEFAULT 'zhengze',
  created_at  TEXT DEFAULT (datetime('now','localtime')),
  updated_at  TEXT DEFAULT (datetime('now','localtime'))
);
"""
ANALYST_NOTE_IDX = """
CREATE INDEX IF NOT EXISTS idx_analyst_note_entity
  ON analyst_note(entity_type, entity_id);
"""

COMPANY_THESIS_DDL = """
CREATE TABLE IF NOT EXISTS company_thesis (
  id                 INTEGER PRIMARY KEY,
  company_id         INTEGER NOT NULL,
  industry_id        INTEGER,                 -- 同公司不同行业可分开(与 company_profile 一致)
  consensus_view     TEXT,                    -- 一致预期是什么
  contrarian_thesis  TEXT,                    -- 反共识 / 超预期判断
  validation_signals TEXT,                    -- 证实条件 / 监控指标
  invalidation_signals TEXT,                  -- 证伪条件
  conviction_level   INTEGER,                 -- 1-5 信心度
  author             TEXT DEFAULT 'zhengze',
  updated_at         TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE(company_id, industry_id)
);
"""

def main():
    con = sqlite3.connect(str(DB)); cur = con.cursor()
    existing = {r[1] for r in cur.execute("PRAGMA table_info(company)")}
    added = []
    for col, typ in NEW_COMPANY_COLS:
        if col not in existing:
            cur.execute(f"ALTER TABLE company ADD COLUMN {col} {typ}")
            added.append(col)
    cur.executescript(ANALYST_NOTE_DDL)
    cur.executescript(ANALYST_NOTE_IDX)
    cur.executescript(COMPANY_THESIS_DDL)
    con.commit()
    # verify
    print("company 新增列:", added if added else "(已存在,跳过)")
    tabs = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    print("analyst_note 存在:", "analyst_note" in tabs)
    print("company_thesis 存在:", "company_thesis" in tabs)
    cols_now = [r[1] for r in cur.execute("PRAGMA table_info(company)")]
    print("company 列数:", len(cols_now))
    con.close()
    print("MIGRATION 001 DONE")

if __name__ == "__main__":
    main()
