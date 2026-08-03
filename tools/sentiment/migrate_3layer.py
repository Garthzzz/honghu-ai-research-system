#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""三层情绪重构 schema 迁移(只写 sentiment.db)。幂等:可重复跑。

三层分表绝不混:
  retail (散户) = 雪球(xueqiu) + 微博(weibo) + 东财股吧(guba)
  news   (新闻) = 新浪/网易/凤凰/今日头条/微信
  heat   (热度) = 各源条数,从两层派生,独立表

原始记录统一落 senti_raw(source_layer 标层),统计严格分层落各自 bucket/daily 表。
attitude 同尺度:1正 2负 3中(星瀚原生 + 股吧 DeepSeek 映射);attitude_src 标清来源。

别名表 company_alias:闭集 = research.db 104 只 A 股,做归因(命中多家则多归)。
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

DDL = """
-- ── 0. 公司别名(归因闭集) ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS company_alias (
  id          INTEGER PRIMARY KEY,
  company_id  INTEGER NOT NULL,      -- 闭集 research.db company.id
  ticker      TEXT NOT NULL,
  alias       TEXT NOT NULL,         -- 全称/股名/简称/ticker/别名
  alias_type  TEXT,                  -- name / short / ticker / code / nick
  UNIQUE(company_id, alias)
);
CREATE INDEX IF NOT EXISTS ix_alias_alias ON company_alias(alias);

-- ── 1. 桶台账(调度 + 断点补抓核心) ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS senti_bucket_ledger (
  bucket_id    TEXT PRIMARY KEY,     -- bucket_start ISO, e.g. 2026-06-15T08:00
  bucket_start TEXT NOT NULL,        -- 含时区 ISO
  bucket_end   TEXT NOT NULL,
  span_hours   INTEGER NOT NULL,     -- 3 日间 / 12 隔夜
  status       TEXT DEFAULT 'pending', -- pending / done / partial / failed
  layers_done  TEXT,                 -- 已完成层逗号串 retail,news,heat
  n_raw        INTEGER DEFAULT 0,
  backfilled   INTEGER DEFAULT 0,    -- 1=补抓
  attempts     INTEGER DEFAULT 0,
  note         TEXT,
  fetched_at   TEXT
);
CREATE INDEX IF NOT EXISTS ix_ledger_status ON senti_bucket_ledger(status);

-- ── 2. 原始记录(三层共表,source_layer 标层;统计严格分层) ───────────────
CREATE TABLE IF NOT EXISTS senti_raw (
  id            INTEGER PRIMARY KEY,
  bucket_id     TEXT NOT NULL,
  company_id    INTEGER NOT NULL,    -- 闭集归因(命中多家则多行)
  ticker        TEXT NOT NULL,
  source_layer  TEXT NOT NULL,       -- retail / news
  platform      TEXT NOT NULL,       -- xueqiu/weibo/guba/sina_news/netease_news/ifeng/toutiao/weixin/news_other
  attitude      INTEGER,             -- 1正 2负 3中
  attitude_src  TEXT NOT NULL,       -- xinghan_native / deepseek_self
  dedup_key     TEXT NOT NULL,       -- simHash 优先否则 post_id(同层同公司去重)
  post_id       TEXT,
  title         TEXT,
  url           TEXT,                -- ^src
  author        TEXT,
  author_uid    TEXT,
  fans_count    INTEGER,
  auth_type     INTEGER,             -- 星瀚 authorAuthType 1普通2橙V3蓝V
  web_name      TEXT,
  domain        TEXT,
  channel       TEXT,
  media_type    INTEGER,             -- 星瀚 mediaType
  hot_value     INTEGER,             -- 星瀚 相似信息条数
  sim_hash      TEXT,
  publish_time  TEXT,                -- ISO 发布时间(分桶依据)
  reason        TEXT,                -- DeepSeek 打标理由(股吧)
  as_of         TEXT,
  fetched_at    TEXT NOT NULL,
  backfilled    INTEGER DEFAULT 0,
  UNIQUE(company_id, source_layer, dedup_key)
);
CREATE INDEX IF NOT EXISTS ix_raw_bucket ON senti_raw(bucket_id);
CREATE INDEX IF NOT EXISTS ix_raw_co_layer ON senti_raw(company_id, source_layer);
CREATE INDEX IF NOT EXISTS ix_raw_unlabeled ON senti_raw(source_layer, attitude) WHERE attitude IS NULL;

-- ── 3. 散户情绪 — 桶级 / 日级 ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS senti_retail_bucket (
  id            INTEGER PRIMARY KEY,
  company_id    INTEGER NOT NULL,
  ticker        TEXT,
  bucket_id     TEXT NOT NULL,
  bucket_start  TEXT NOT NULL,
  span_hours    INTEGER NOT NULL,
  valid_count   INTEGER DEFAULT 0,
  pos INTEGER DEFAULT 0, neg INTEGER DEFAULT 0, neu INTEGER DEFAULT 0,
  net_sentiment REAL,                -- (pos-neg)/(pos+neg+neu)
  net_sentiment_weighted REAL,       -- 雪球/股吧 1.0、微博 0.3
  per_hour_count REAL,               -- valid_count/span_hours
  significant   INTEGER DEFAULT 0,   -- valid_count>10
  n_xueqiu INTEGER DEFAULT 0, n_weibo INTEGER DEFAULT 0, n_guba INTEGER DEFAULT 0,
  computed_at   TEXT,
  UNIQUE(company_id, bucket_id)
);
CREATE INDEX IF NOT EXISTS ix_retailb_co ON senti_retail_bucket(company_id, bucket_start);
CREATE TABLE IF NOT EXISTS senti_retail_daily (
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, ticker TEXT, trade_date TEXT NOT NULL,
  valid_count INTEGER, pos INTEGER, neg INTEGER, neu INTEGER,
  net_sentiment REAL, net_sentiment_weighted REAL, per_hour_count REAL, significant INTEGER,
  n_xueqiu INTEGER, n_weibo INTEGER, n_guba INTEGER, computed_at TEXT,
  UNIQUE(company_id, trade_date)
);

-- ── 4. 新闻情绪 — 桶级 / 日级(与散户完全独立) ───────────────────────────
CREATE TABLE IF NOT EXISTS senti_news_bucket (
  id            INTEGER PRIMARY KEY,
  company_id    INTEGER NOT NULL,
  ticker        TEXT,
  bucket_id     TEXT NOT NULL,
  bucket_start  TEXT NOT NULL,
  span_hours    INTEGER NOT NULL,
  valid_count   INTEGER DEFAULT 0,
  pos INTEGER DEFAULT 0, neg INTEGER DEFAULT 0, neu INTEGER DEFAULT 0,
  net_sentiment REAL,
  per_hour_count REAL,
  significant   INTEGER DEFAULT 0,
  n_sina INTEGER DEFAULT 0, n_netease INTEGER DEFAULT 0, n_ifeng INTEGER DEFAULT 0,
  n_toutiao INTEGER DEFAULT 0, n_weixin INTEGER DEFAULT 0, n_other INTEGER DEFAULT 0,
  computed_at   TEXT,
  UNIQUE(company_id, bucket_id)
);
CREATE INDEX IF NOT EXISTS ix_newsb_co ON senti_news_bucket(company_id, bucket_start);
CREATE TABLE IF NOT EXISTS senti_news_daily (
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, ticker TEXT, trade_date TEXT NOT NULL,
  valid_count INTEGER, pos INTEGER, neg INTEGER, neu INTEGER,
  net_sentiment REAL, per_hour_count REAL, significant INTEGER,
  n_sina INTEGER, n_netease INTEGER, n_ifeng INTEGER, n_toutiao INTEGER, n_weixin INTEGER, n_other INTEGER,
  computed_at TEXT,
  UNIQUE(company_id, trade_date)
);

-- ── 5. 热度 — 桶级 / 日级(条数,绝不并入情绪) ───────────────────────────
CREATE TABLE IF NOT EXISTS heat_volume_bucket (
  id            INTEGER PRIMARY KEY,
  company_id    INTEGER NOT NULL,
  ticker        TEXT,
  bucket_id     TEXT NOT NULL,
  bucket_start  TEXT NOT NULL,
  span_hours    INTEGER NOT NULL,
  total_count   INTEGER DEFAULT 0,
  per_hour_count REAL,
  retail_count  INTEGER DEFAULT 0,
  news_count    INTEGER DEFAULT 0,
  n_xueqiu INTEGER DEFAULT 0, n_weibo INTEGER DEFAULT 0, n_guba INTEGER DEFAULT 0, n_news INTEGER DEFAULT 0,
  sum_hot_value INTEGER DEFAULT 0,
  computed_at   TEXT,
  UNIQUE(company_id, bucket_id)
);
CREATE INDEX IF NOT EXISTS ix_heatb_co ON heat_volume_bucket(company_id, bucket_start);
CREATE TABLE IF NOT EXISTS heat_volume_daily (
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, ticker TEXT, trade_date TEXT NOT NULL,
  total_count INTEGER, per_hour_count REAL, retail_count INTEGER, news_count INTEGER,
  n_xueqiu INTEGER, n_weibo INTEGER, n_guba INTEGER, n_news INTEGER, sum_hot_value INTEGER, computed_at TEXT,
  UNIQUE(company_id, trade_date)
);

-- ── 6. 三层覆盖审计 view ─────────────────────────────────────────────────
DROP VIEW IF EXISTS v_layer_coverage_audit;
CREATE VIEW v_layer_coverage_audit AS
SELECT 'retail' AS layer,
       COUNT(DISTINCT company_id) AS n_companies,
       COUNT(*) AS n_bucket_rows,
       SUM(valid_count) AS n_valid,
       SUM(CASE WHEN significant=1 THEN 1 ELSE 0 END) AS n_significant
FROM senti_retail_bucket
UNION ALL
SELECT 'news', COUNT(DISTINCT company_id), COUNT(*), SUM(valid_count),
       SUM(CASE WHEN significant=1 THEN 1 ELSE 0 END)
FROM senti_news_bucket
UNION ALL
SELECT 'heat', COUNT(DISTINCT company_id), COUNT(*), SUM(total_count), NULL
FROM heat_volume_bucket;
"""


def build_aliases(con):
    """从 research.db(只读)生成 104 闭集别名。name 为主(A股股名=帖中常用名),ticker 为辅。
    保守:不做激进缩写,防误归因(铁律:归因只认闭集别名)。少量高频龙头加 curated 别名。"""
    rc = common.research_ro_conn()
    comps = rc.execute("""SELECT id, name, ticker FROM company
                          WHERE ticker LIKE '%.SZ' OR ticker LIKE '%.SH'
                             OR ticker LIKE '%.SS' OR ticker LIKE '%.BJ'""").fetchall()
    rc.close()
    # curated 别名(高频龙头常见简称/俗称;只加我确信无歧义的)
    CURATED = {
        "中际旭创": ["旭创"], "天孚通信": ["天孚"], "工业富联": ["富联"],
        "新易盛": [], "沪电股份": ["沪电"], "生益科技": ["生益"],
        "鼎龙股份": ["鼎龙"], "通富微电": ["通富"], "兆易创新": ["兆易"],
        "澜起科技": ["澜起"], "寒武纪": ["寒武纪-U", "寒武纪U"], "海光信息": ["海光"],
        "北方华创": ["北方华创"], "中芯国际": ["中芯"], "韦尔股份": ["韦尔"],
        "立讯精密": ["立讯"], "工业富联": ["富联"], "浪潮信息": ["浪潮"],
        "紫光股份": ["紫光"], "锐捷网络": ["锐捷"], "盛科通信": ["盛科"],
        "胜宏科技": ["胜宏"], "深南电路": ["深南"], "光迅科技": ["光迅"],
        "太辰光": [], "剑桥科技": ["剑桥"], "博创科技": ["博创"],
        "源杰科技": ["源杰"], "仕佳光子": ["仕佳"], "长光华芯": ["长光"],
    }
    rows = []
    for c in comps:
        cid, name, ticker = c["id"], (c["name"] or "").strip(), (c["ticker"] or "").strip()
        if not name or not ticker:
            continue
        seen = set()
        def add(a, t):
            a = (a or "").strip()
            if a and len(a) >= 2 and a.lower() not in seen:
                seen.add(a.lower()); rows.append((cid, ticker, a, t))
        add(name, "name")                              # 主:股名
        add(ticker, "ticker")                          # 300308.SZ
        code = ticker.split(".")[0]
        if code.isdigit():
            add(code, "code")                          # 300308
        for nick in CURATED.get(name, []):
            add(nick, "nick")
    con.executemany("INSERT OR IGNORE INTO company_alias(company_id,ticker,alias,alias_type) VALUES(?,?,?,?)", rows)
    return len(comps), len(rows)


def main():
    con = common.get_senti_db()
    common.assert_senti_only(con)                      # 门C 隔离
    con.executescript(DDL)
    con.commit()
    ncomp, nalias = build_aliases(con)
    con.commit()
    # 报告
    tbls = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'senti_%' OR name LIKE 'heat_%' OR name='company_alias' ORDER BY name")]
    n_alias_total = con.execute("SELECT COUNT(*) FROM company_alias").fetchone()[0]
    n_alias_co = con.execute("SELECT COUNT(DISTINCT company_id) FROM company_alias").fetchone()[0]
    print(f"?? 三层 schema 迁移完成。闭集公司 {ncomp} 家 → 别名 {n_alias_total} 条(覆盖 {n_alias_co} 家)")
    print("新表:", ", ".join(t for t in tbls if t in (
        "company_alias","senti_bucket_ledger","senti_raw","senti_retail_bucket","senti_retail_daily",
        "senti_news_bucket","senti_news_daily","heat_volume_bucket","heat_volume_daily")))
    con.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
