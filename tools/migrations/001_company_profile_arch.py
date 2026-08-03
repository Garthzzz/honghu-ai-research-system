#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
001_company_profile_arch.py — 公司透视架构升级迁移(Phase3 Stage B)

幂等迁移:每个 ADD COLUMN 前 PRAGMA 检查列是否已存在(LIVE schema 已与
schema.sql 分叉:industry_data_point 已有 company_id;company 已有 ticker)。

动作:
  1. source 表 ALTER 加 8 列(source_subtype/fetch_timestamp/fetch_method/domain/
     language/is_primary_source/source_credibility/content_snapshot_path)
  2. industry_data_point 加 1 列(last_verified_at)
  3. company 表 ALTER 加 8 列(listing_status/pe_ttm/pe_forward/pb/market_cap_value/
     market_cap_unit/valuation_as_of/display_mode);ticker 已存在跳过
  4. 新表 company_profile / source_review_queue + 索引
  5. 存量回填:
     - source: fetch_method='pdf_local', source_credibility='whitelisted',
               is_primary_source(按 source_type), language='zh'
     - company: listing_status —— 镜像现有 market(A股/港股/美股),
               其他/None 桶用 db 实际 name override(只填高确信值;不编造 ticker)
     - industry_data_point.last_verified_at: 留 NULL(协议 C1,不 backfill)
  6. 验证:1993 dp + extraction_method 分布 + 新列/新表存在,失败抛异常(调用方 halt)

用法:python tools/migrations/001_company_profile_arch.py
     python tools/migrations/001_company_profile_arch.py --verify-only
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "research.db"

EXPECTED_DP_COUNT = 1993
EXPECTED_EM = {"pdf_direct": 1988, "inferred": 5}


# ── 列定义 ────────────────────────────────────────────
SOURCE_NEW_COLS = [
    ("source_subtype",        "TEXT"),
    ("fetch_timestamp",       "TEXT"),
    ("fetch_method",          "TEXT"),
    ("domain",                "TEXT"),
    ("language",              "TEXT"),
    ("is_primary_source",     "INTEGER DEFAULT 0"),
    ("source_credibility",    "TEXT DEFAULT 'unverified'"),
    ("content_snapshot_path", "TEXT"),
]
IDP_NEW_COLS = [
    ("last_verified_at", "TEXT"),
]
COMPANY_NEW_COLS = [
    ("listing_status",   "TEXT"),
    ("pe_ttm",           "REAL"),
    ("pe_forward",       "REAL"),
    ("pb",               "REAL"),
    ("market_cap_value", "REAL"),
    ("market_cap_unit",  "TEXT"),
    ("valuation_as_of",  "TEXT"),
    ("display_mode",     "TEXT DEFAULT 'quantitative'"),
]

# 其他/None 桶的 listing_status override(按 db 实际 name 精确匹配)。
# value = (listing_status, ticker_or_None)。只填高确信值;不确定的留 NULL(等 Stage 2 网搜)。
NAME_OVERRIDES = {
    # 存储 — 韩股/日股 majors(market='其他',ticker 当前空,补全)
    "三星":            ("kospi", "005930.KS"),
    "SK海力士":        ("kospi", "000660.KS"),
    "Kioxia":          ("tse",   "285A.T"),
    "住友电气":        ("tse",   None),
    "Sumitomo":        ("tse",   None),
    "三菱电机":        ("tse",   None),
    # 存储 — 国资未上市
    "长江存储":        ("soe",   None),
    "长鑫存储":        ("soe",   None),
    # 私营未上市(中/美 AI + 硬件)
    "华为":            ("unlisted", None),
    "字节跳动":        ("unlisted", None),
    "OpenAI":          ("unlisted", None),
    "Anthropic":       ("unlisted", None),
    "xAI":             ("unlisted", None),
    "Perplexity":      ("unlisted", None),
    "Anysphere":       ("unlisted", None),
    "Figure AI":       ("unlisted", None),
    "Scale AI":        ("unlisted", None),
    "MiniMax":         ("unlisted", None),
    "Moonshot/月之暗面": ("unlisted", None),
    "深度求索/DeepSeek": ("unlisted", None),
    "阶跃星辰":        ("unlisted", None),
    "生数科技":        ("unlisted", None),
    "爱诗科技":        ("unlisted", None),
    "智元机器人":      ("unlisted", None),
    "宇树科技":        ("unlisted", None),
    "银河通用":        ("unlisted", None),
    # 拟 IPO
    "智谱AI":          ("pre_ipo", None),
}

# market(中文)→ listing_status 镜像(已上市桶,不覆盖既有分类)
MARKET_TO_STATUS = {"A股": "a_share", "港股": "hk", "美股": "us"}

# 一手监管/公告类 source_type → is_primary_source=1
PRIMARY_SOURCE_TYPES = {"公告", "招股书", "业绩说明会"}


def cols_of(conn: sqlite3.Connection, table: str) -> set:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def add_columns(conn: sqlite3.Connection, table: str, cols) -> list:
    existing = cols_of(conn, table)
    added = []
    for name, decl in cols:
        if name in existing:
            print(f"  [skip] {table}.{name} 已存在")
            continue
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        added.append(name)
        print(f"  [add ] {table}.{name} {decl}")
    return added


def create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS company_profile (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        company_id      INTEGER NOT NULL,
        industry_id     INTEGER NOT NULL,
        period          TEXT    NOT NULL,
        revenue_series      TEXT,
        net_income_series   TEXT,
        gross_margin        REAL,
        net_margin          REAL,
        operating_cash_flow REAL,
        ocf_unit            TEXT,
        financials_as_of    TEXT,
        global_share        REAL,
        global_share_as_of  TEXT,
        global_rank         INTEGER,
        china_share         REAL,
        china_share_as_of   TEXT,
        china_rank          INTEGER,
        share_rank_change   TEXT,
        revenue_share_in_industry REAL,
        main_products       TEXT,
        main_customers      TEXT,
        customer_concentration TEXT,
        rd_expense_ratio    REAL,
        capex_value         REAL,
        capex_unit          TEXT,
        tech_node           TEXT,
        private_valuation_value REAL,
        private_valuation_unit  TEXT,
        private_round           TEXT,
        private_valuation_as_of TEXT,
        recent_events       TEXT,
        risks               TEXT,
        is_china_tech_leader INTEGER NOT NULL DEFAULT 0,
        in_global_table      INTEGER NOT NULL DEFAULT 0,
        in_china_table       INTEGER NOT NULL DEFAULT 0,
        listing_status      TEXT,
        source_ids          TEXT,
        summary             TEXT,
        display_note        TEXT,
        last_updated        TEXT,
        last_verified_at    TEXT,
        created_at          TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (company_id)  REFERENCES company(id)  ON DELETE CASCADE,
        FOREIGN KEY (industry_id) REFERENCES industry(id) ON DELETE CASCADE,
        CHECK (is_china_tech_leader IN (0,1)),
        CHECK (in_global_table IN (0,1)),
        CHECK (in_china_table IN (0,1)),
        UNIQUE (company_id, industry_id, period)
    );
    CREATE INDEX IF NOT EXISTS idx_cp_company     ON company_profile(company_id);
    CREATE INDEX IF NOT EXISTS idx_cp_industry    ON company_profile(industry_id);
    CREATE INDEX IF NOT EXISTS idx_cp_tech_leader ON company_profile(is_china_tech_leader);

    CREATE TABLE IF NOT EXISTS source_review_queue (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        domain          TEXT    NOT NULL,
        sample_url      TEXT,
        used_for_field  TEXT,
        cc_judgment     TEXT,
        suggested_action TEXT,
        industry_context TEXT,
        company_context  TEXT,
        encountered_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        user_decision   TEXT,
        user_decided_at TEXT,
        CHECK (suggested_action IS NULL OR suggested_action IN ('whitelist','blacklist','keep_gray')),
        CHECK (user_decision   IS NULL OR user_decision   IN ('whitelist','blacklist','keep_gray')),
        UNIQUE (domain)
    );
    """)
    print("  [ok  ] company_profile / source_review_queue 表 + 索引就绪")


def backfill_source(conn: sqlite3.Connection) -> None:
    # 存量 source 都是研报 PDF 精读:fetch_method=pdf_local, credibility=whitelisted, language=zh
    conn.execute("UPDATE source SET fetch_method='pdf_local' WHERE fetch_method IS NULL")
    conn.execute("UPDATE source SET language='zh' WHERE language IS NULL")
    # ?? BUGFIX(review #2):source_credibility 列 ALTER 时带 DEFAULT 'unverified',
    #   已有行被默认值占住(非 NULL),原 `WHERE IS NULL OR =''` 影响 0 行 → 存量全留
    #   unverified。改按 fetch_method='pdf_local' 锁定存量研报源 → whitelisted。
    #   该谓词对 Stage2 的 web_fetch 源不生效(它们 fetch_method!=pdf_local,保持
    #   default 'unverified' 由 classify_source 后续判定),且 pdf_local 行重跑幂等。
    conn.execute("UPDATE source SET source_credibility='whitelisted' WHERE fetch_method='pdf_local'")
    # is_primary_source 按 source_type
    qmarks = ",".join("?" * len(PRIMARY_SOURCE_TYPES))
    conn.execute(
        f"UPDATE source SET is_primary_source=1 WHERE source_type IN ({qmarks})",
        tuple(PRIMARY_SOURCE_TYPES),
    )
    conn.execute("UPDATE source SET is_primary_source=0 WHERE is_primary_source IS NULL")
    n = conn.execute("SELECT COUNT(*) FROM source").fetchone()[0]
    np = conn.execute("SELECT COUNT(*) FROM source WHERE is_primary_source=1").fetchone()[0]
    print(f"  [ok  ] source 存量回填:{n} 条,其中一手 {np} 条(fetch_method=pdf_local / credibility=whitelisted / language=zh)")


def backfill_company_listing_status(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id, name, ticker, market, listing_status FROM company").fetchall()
    mirror, override, left_null = 0, 0, 0
    for r in rows:
        cid, name, ticker, market, cur = r[0], r[1], r[2], r[3], r[4]
        if cur:  # 幂等:已填则跳过
            continue
        status, new_ticker = None, None
        # 1) 已上市桶:镜像现有 market(不覆盖既有分类,绝不编造)
        if market in MARKET_TO_STATUS:
            status = MARKET_TO_STATUS[market]
            mirror += 1
        # 2) 其他/None 桶:按 db 实际 name override(高确信)
        elif name in NAME_OVERRIDES:
            status, new_ticker = NAME_OVERRIDES[name]
            override += 1
        else:
            left_null += 1
            continue
        if status:
            conn.execute("UPDATE company SET listing_status=? WHERE id=?", (status, cid))
        # 仅当 override 给了 ticker 且当前为空时补 ticker(三星/SK/Kioxia)
        if new_ticker and not ticker:
            conn.execute("UPDATE company SET ticker=? WHERE id=?", (new_ticker, cid))
    print(f"  [ok  ] company listing_status 回填:镜像 market {mirror} 家 / name override {override} 家 / 留空待 Stage2 {left_null} 家")


def verify(conn: sqlite3.Connection) -> None:
    print("── 验证 ──")
    dp = conn.execute("SELECT COUNT(*) FROM industry_data_point").fetchone()[0]
    print(f"  dp count = {dp}（期望 {EXPECTED_DP_COUNT}）")
    if dp != EXPECTED_DP_COUNT:
        raise RuntimeError(f"FATAL: dp count {dp} != {EXPECTED_DP_COUNT} —— 立即 halt")
    em = {r[0]: r[1] for r in conn.execute(
        "SELECT extraction_method, COUNT(*) FROM industry_data_point GROUP BY extraction_method")}
    print(f"  extraction_method = {em}（期望 {EXPECTED_EM}）")
    if em != EXPECTED_EM:
        raise RuntimeError(f"FATAL: extraction_method 分布 {em} != {EXPECTED_EM} —— 立即 halt")
    # 新列
    scols, ccols, icols = cols_of(conn, "source"), cols_of(conn, "company"), cols_of(conn, "industry_data_point")
    for name, _ in SOURCE_NEW_COLS:
        assert name in scols, f"FATAL: source.{name} 缺失"
    for name, _ in COMPANY_NEW_COLS:
        assert name in ccols, f"FATAL: company.{name} 缺失"
    assert "last_verified_at" in icols, "FATAL: idp.last_verified_at 缺失"
    # 新表
    tbls = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    for tb in ("company_profile", "source_review_queue"):
        assert tb in tbls, f"FATAL: 表 {tb} 缺失"
    # 存量 idp.last_verified_at 应全 NULL(协议 C1,不 backfill)
    nn = conn.execute("SELECT COUNT(*) FROM industry_data_point WHERE last_verified_at IS NOT NULL").fetchone()[0]
    print(f"  idp.last_verified_at 非空 = {nn}（期望 0,存量留 NULL）")
    assert nn == 0, "FATAL: 存量 last_verified_at 不应被 backfill"
    print("  ?? 全部验证通过")


def main():
    verify_only = "--verify-only" in sys.argv
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys=OFF")  # ALTER 期间关 FK,完成后开
    try:
        if not verify_only:
            print(f"=== 001_company_profile_arch 迁移 @ {datetime.now().isoformat(timespec='seconds')} ===")
            print("ALTER source:")
            add_columns(conn, "source", SOURCE_NEW_COLS)
            print("ALTER industry_data_point:")
            add_columns(conn, "industry_data_point", IDP_NEW_COLS)
            print("ALTER company:")
            add_columns(conn, "company", COMPANY_NEW_COLS)
            print("CREATE TABLES:")
            create_tables(conn)
            print("BACKFILL:")
            backfill_source(conn)
            backfill_company_listing_status(conn)
            conn.commit()
        verify(conn)
        conn.execute("PRAGMA foreign_keys=ON")
        print("=== 迁移完成 ===")
    except Exception as e:
        conn.rollback()
        print(f"!!! 迁移失败,已回滚:{e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
