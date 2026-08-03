#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""扩展迁移 v3(T8/T10/T12):股价K线表 / 蒸馏语料表 / funda 供应链拓扑只读镜像。只写 sentiment.db(门C)。
funda.db 仅【只读】读取镜像拓扑(ticker/name/layer/country/edges),**不搬其情绪等过时数据**。"""
from __future__ import annotations
import sys, sqlite3
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

FUNDA_DB = common.ROOT / "funda" / "docs" / "data" / "funda.db"

DDL = """
CREATE TABLE IF NOT EXISTS stock_kline (
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, ticker TEXT,
  freq TEXT,                       -- 'd' 日线 | '60m' 60分钟
  ts TEXT,                         -- YYYY-MM-DD(日) | YYYY-MM-DD HH:MM(分钟)
  o REAL, h REAL, l REAL, c REAL, vol REAL, amount REAL,
  source_url TEXT, as_of TEXT, fetched_at TEXT NOT NULL,
  UNIQUE(company_id, freq, ts)
);
CREATE INDEX IF NOT EXISTS idx_kline_cf ON stock_kline(company_id, freq, ts);

-- T10 蒸馏语料:LLM 当标注器,留作将来微调本地金融-股吧模型
CREATE TABLE IF NOT EXISTS senti_label_corpus (
  id INTEGER PRIMARY KEY, post_id TEXT, company_id INTEGER, ticker TEXT,
  text TEXT,                       -- 标题(+正文摘要)
  label TEXT, label_score REAL, reason TEXT,
  model TEXT, labeled_at TEXT,
  UNIQUE(post_id)
);

-- T12 funda 供应链拓扑只读镜像(仅拓扑:ticker/name/layer/country/edges;不含 funda 情绪)
CREATE TABLE IF NOT EXISTS funda_semi_nodes (
  ticker TEXT PRIMARY KEY, name TEXT, layer TEXT, country TEXT, exchange TEXT, is_bottleneck INTEGER,
  src_note TEXT DEFAULT 'funda.db 2026-06-04 快照(仅拓扑)'
);
CREATE TABLE IF NOT EXISTS funda_semi_edges (
  id INTEGER PRIMARY KEY, src_ticker TEXT, dst_ticker TEXT, relation TEXT, directed INTEGER
);
CREATE INDEX IF NOT EXISTS idx_fse_src ON funda_semi_edges(src_ticker);
CREATE INDEX IF NOT EXISTS idx_fse_dst ON funda_semi_edges(dst_ticker);
"""

ALTERS = [("senti_indicator_daily", "stagnation_cut_signal2", "INTEGER")]  # 占位(实际复用现有列)


def mirror_funda(con):
    """只读读取 funda.db,镜像拓扑到 sentiment.db。幂等(先清后插)。"""
    if not FUNDA_DB.exists():
        print("  funda.db 不存在,跳过镜像"); return 0, 0
    fc = sqlite3.connect(f"file:{FUNDA_DB.as_posix()}?mode=ro", uri=True)
    fc.row_factory = sqlite3.Row
    nodes = fc.execute("SELECT ticker,name,layer,country,exchange,is_bottleneck FROM semi_nodes").fetchall()
    edges = fc.execute("SELECT src_ticker,dst_ticker,relation,directed FROM semi_edges").fetchall()
    fc.close()
    con.execute("DELETE FROM funda_semi_nodes"); con.execute("DELETE FROM funda_semi_edges")
    for n in nodes:
        con.execute("INSERT OR IGNORE INTO funda_semi_nodes(ticker,name,layer,country,exchange,is_bottleneck) VALUES(?,?,?,?,?,?)",
                    (n["ticker"], n["name"], n["layer"], n["country"], n["exchange"], n["is_bottleneck"]))
    for e in edges:
        con.execute("INSERT INTO funda_semi_edges(src_ticker,dst_ticker,relation,directed) VALUES(?,?,?,?)",
                    (e["src_ticker"], e["dst_ticker"], e["relation"], e["directed"]))
    return len(nodes), len(edges)


def main():
    con = common.get_senti_db()
    common.assert_senti_only(con)                      # 门C
    con.executescript(DDL)
    nn, ne = mirror_funda(con)
    con.execute("INSERT OR REPLACE INTO senti_meta(k,v) VALUES(?,?)",
                ("供应链图", "T12 /dynamic/supplychain:funda 572节点拓扑只读镜像(2026-06-04快照,仅 ticker/层/国家/边),情绪叠加用我们自算,不搬funda情绪。点击载邻居,不渲染全28550边。"))
    con.execute("INSERT OR REPLACE INTO senti_meta(k,v) VALUES(?,?)",
                ("股价K线", "T8 stock_kline:Tushare/yfinance 真OHLCV(日/60m);滞涨减仓=讨论99分位 且 价格N日滞涨。"))
    con.commit()
    print(f"v3 迁移:stock_kline / senti_label_corpus / funda 镜像 建成")
    print(f"funda 镜像:节点 {nn} / 边 {ne}(只读拓扑,as_of 2026-06-04)")
    print(f"sentiment.db 表数:{con.execute('SELECT COUNT(*) FROM sqlite_master WHERE type=' + chr(39) + 'table' + chr(39)).fetchone()[0]}")
    con.close()


if __name__ == "__main__":
    main()
