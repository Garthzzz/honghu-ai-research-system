#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""扩展迁移 v2(T1–T3):小时表 / 帖级表 / 情绪K线 / 情绪方向分列 + 清洗非法日期。只写 sentiment.db(门C)。"""
from __future__ import annotations
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

DDL = """
CREATE TABLE IF NOT EXISTS senti_post (
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, ticker TEXT,
  post_id TEXT NOT NULL, post_url TEXT,
  ts_hour TEXT, trade_date TEXT, posted_at TEXT,
  title TEXT, read_count INTEGER, reply_count INTEGER,
  sentiment_label TEXT, label_score REAL, labeled_by TEXT, labeled_at TEXT,
  source_url TEXT, as_of TEXT, fetched_at TEXT NOT NULL,
  UNIQUE(company_id, post_id)
);
CREATE INDEX IF NOT EXISTS idx_spost_ch ON senti_post(company_id, ts_hour DESC);
CREATE INDEX IF NOT EXISTS idx_spost_unlabeled ON senti_post(labeled_by) WHERE labeled_by IS NULL;

CREATE TABLE IF NOT EXISTS senti_discussion_hourly (
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, ticker TEXT,
  ts_hour TEXT NOT NULL, post_count_hour INTEGER, read_sum_hour INTEGER,
  bull_count INTEGER, bear_count INTEGER, neutral_count INTEGER,
  sentiment_direction REAL, direction_src TEXT,
  source_url TEXT, as_of TEXT, fetched_at TEXT NOT NULL,
  UNIQUE(company_id, ts_hour)
);
CREATE INDEX IF NOT EXISTS idx_sdh_ch ON senti_discussion_hourly(company_id, ts_hour DESC);

CREATE TABLE IF NOT EXISTS senti_indicator_hourly (
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, ts_hour TEXT NOT NULL,
  post_count_hour INTEGER, ma3 REAL, ma20 REAL, cross_up INTEGER,
  pct_rank REAL, significant INTEGER, ready INTEGER,
  sentiment_direction REAL, computed_at TEXT,
  UNIQUE(company_id, ts_hour)
);
CREATE INDEX IF NOT EXISTS idx_sih_ch ON senti_indicator_hourly(company_id, ts_hour DESC);

CREATE TABLE IF NOT EXISTS senti_kline_hourly (
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, ts_hour TEXT NOT NULL,
  metric TEXT, o REAL, h REAL, l REAL, c REAL, vol INTEGER, computed_at TEXT,
  UNIQUE(company_id, ts_hour, metric)
);
CREATE INDEX IF NOT EXISTS idx_skl_ch ON senti_kline_hourly(company_id, ts_hour DESC);
"""

ALTERS = [
    ("senti_discussion_daily", "sentiment_direction", "REAL"),
    ("senti_discussion_daily", "direction_src", "TEXT"),
    ("senti_discussion_daily", "bull_count", "INTEGER"),
    ("senti_discussion_daily", "bear_count", "INTEGER"),
    ("senti_discussion_daily", "neutral_count", "INTEGER"),
    ("senti_indicator_daily", "sentiment_direction", "REAL"),
]

META = {
    "K线语义": "情绪K线 metric 默认=direction(情绪方向分,无则 post_count);粒度=小时;OHLC=该小时内逐帖累积方向分的开/高/低/收;vol=发帖量。窗口/度量 config 可调,默认待用户确认。",
    "方向分口径": "T3:DeepSeek 对股吧帖标题分类 看涨(+1)/看跌(-1)/中性(0)→ 每小时/日聚合 direction=(bull-bear)/(bull+bear+neutral)∈[-1,1]。??自算非平台原生,tier≤2,^src 溯源原帖。",
    "粒度": "小时级(senti_*_hourly)主用于盘中盯买卖点;日表(senti_*_daily)为 rollup。",
}


def is_valid_date(s):
    import datetime
    try:
        y, m, d = s.split("-")
        datetime.date(int(y), int(m), int(d))
        return True
    except Exception:
        return False


def main():
    con = common.get_senti_db()
    common.assert_senti_only(con)                  # 门C
    con.executescript(DDL)
    for tbl, col, typ in ALTERS:
        try:
            con.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {typ}")
        except Exception:
            pass                                    # 已存在
    for k, v in META.items():
        con.execute("INSERT OR REPLACE INTO senti_meta(k, v) VALUES(?, ?)", (k, v))
    # ?? 清洗已有非法 trade_date(无法重解析 → 删 + 记)
    bad = [r["id"] for r in con.execute("SELECT id, trade_date FROM senti_discussion_daily")
           if not is_valid_date(r["trade_date"])]
    bad_ind = [r["id"] for r in con.execute("SELECT id, trade_date FROM senti_indicator_daily")
               if not is_valid_date(r["trade_date"])]
    for i in bad:
        con.execute("DELETE FROM senti_discussion_daily WHERE id=?", (i,))
    for i in bad_ind:
        con.execute("DELETE FROM senti_indicator_daily WHERE id=?", (i,))
    con.commit()
    print(f"v2 迁移完成:新增 4 表 + 6 列 + K线/方向口径 meta")
    print(f"清洗非法日期:senti_discussion_daily 删 {len(bad)} 行 / senti_indicator_daily 删 {len(bad_ind)} 行(无法重解析的垃圾)")
    tbls = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    print(f"sentiment.db 表数:{len(tbls)}")
    con.close()


if __name__ == "__main__":
    main()
