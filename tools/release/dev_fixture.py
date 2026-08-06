from __future__ import annotations

"""Create a small, synthetic local Viewer fixture outside the live project data."""

import argparse
import json
import sqlite3
from pathlib import Path

from tools.financial.db import initialize_database
from tools.opportunity_lens.migrate import init_db as init_opportunity_db


RESEARCH_SCHEMA = """
CREATE TABLE industry (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    chain_position TEXT,
    tier INTEGER NOT NULL DEFAULT 3,
    status TEXT NOT NULL DEFAULT '仅记录',
    created_at TEXT
);
CREATE TABLE source (
    id INTEGER PRIMARY KEY,
    title TEXT,
    quality_tier INTEGER,
    file_path TEXT,
    source_credibility TEXT,
    note TEXT,
    publish_date TEXT
);
CREATE TABLE company (
    id INTEGER PRIMARY KEY,
    name TEXT,
    ticker TEXT,
    market TEXT,
    listing_status TEXT,
    pe_ttm REAL,
    pe_forward REAL,
    pb REAL,
    ps_ttm REAL,
    ev_ebitda REAL,
    peg REAL,
    roe REAL,
    roa REAL,
    eps_ttm REAL,
    bps_mrq REAL,
    per_share_currency TEXT,
    financial_metrics_as_of TEXT,
    financial_metrics_source_id INTEGER,
    market_cap_value REAL,
    market_cap_unit TEXT,
    market_cap_cny REAL,
    market_cap_usd REAL,
    valuation_as_of TEXT,
    forecast_eps_year1 REAL,
    forecast_eps_year2 REAL,
    forecast_revenue_year1 REAL,
    forecast_revenue_year2 REAL,
    forecast_revenue_unit TEXT,
    forecast_as_of_date TEXT,
    forecast_source_id INTEGER,
    valuation_source_id INTEGER
);
CREATE TABLE news_item (
    id INTEGER PRIMARY KEY, title TEXT, url TEXT, source_id INTEGER,
    publish_date TEXT, fetch_timestamp TEXT, importance INTEGER,
    is_breaking INTEGER, is_ai_relevant INTEGER, ai_tags_company TEXT,
    ai_tags_industry TEXT
);
CREATE TABLE event (
    id INTEGER PRIMARY KEY, title TEXT, scheduled_date TEXT, importance INTEGER,
    event_type TEXT, status TEXT, related_company_ids TEXT,
    related_industry_ids TEXT
);
CREATE TABLE opinion_leader (
    id INTEGER PRIMARY KEY, name TEXT, platform TEXT, source_id INTEGER
);
CREATE TABLE voice_post (
    id INTEGER PRIMARY KEY, leader_id INTEGER, content_text TEXT, post_url TEXT,
    posted_at TEXT, post_type TEXT, is_ai_relevant INTEGER
);
CREATE TABLE researcher (
    id INTEGER PRIMARY KEY, name TEXT, display_name TEXT
);
CREATE TABLE hypothesis (
    id INTEGER PRIMARY KEY, title TEXT, thesis_type TEXT, status TEXT,
    created_at TEXT, last_updated_at TEXT, related_industry_ids TEXT,
    related_company_ids TEXT, is_draft INTEGER, researcher_id INTEGER
);
CREATE TABLE industry_data_point (
    id INTEGER PRIMARY KEY, industry_id INTEGER, source_id INTEGER,
    period TEXT, metric TEXT, extraction_method TEXT
);
CREATE TABLE industry_relation (
    upstream_id INTEGER, downstream_id INTEGER, cost_share REAL, demand_share REAL
);
CREATE TABLE company_industry (
    company_id INTEGER, industry_id INTEGER, role TEXT, revenue_share REAL, note TEXT
);
CREATE TABLE source_entity (
    source_id INTEGER, entity_type TEXT, entity_id TEXT
);
CREATE TABLE thesis (
    id INTEGER PRIMARY KEY, industry_id INTEGER, created_at TEXT
);
CREATE TABLE source_snapshot (
    industry_id INTEGER, snapshot_date TEXT
);
CREATE TABLE md_section_version (
    review_pending INTEGER, md_path TEXT
);
CREATE TABLE industry_thesis (
    industry_id INTEGER, consensus_narrative TEXT, consensus_source_ids TEXT
);
CREATE TABLE company_profile (
    id INTEGER PRIMARY KEY, company_id INTEGER, industry_id INTEGER, period TEXT,
    revenue_series TEXT, net_income_series TEXT, gross_margin REAL,
    net_margin REAL, operating_cash_flow REAL, ocf_unit TEXT,
    financials_as_of TEXT, global_share REAL, global_share_as_of TEXT,
    global_rank INTEGER, china_share REAL, china_share_as_of TEXT,
    china_rank INTEGER, share_rank_change TEXT, revenue_share_in_industry REAL,
    main_products TEXT, main_customers TEXT, customer_concentration TEXT,
    rd_expense_ratio REAL, capex_value REAL, capex_unit TEXT, tech_node TEXT,
    private_valuation_value REAL, private_valuation_unit TEXT,
    private_round TEXT, private_valuation_as_of TEXT, recent_events TEXT,
    risks TEXT, source_ids TEXT, summary TEXT, display_note TEXT
);
CREATE TABLE theme (
    id TEXT PRIMARY KEY, name TEXT, category TEXT, summary TEXT, status TEXT
);
CREATE TABLE theme_industry (
    id INTEGER PRIMARY KEY, theme_id TEXT, industry_id INTEGER,
    impact TEXT, note TEXT
);
CREATE TABLE theme_company (
    id INTEGER PRIMARY KEY, theme_id TEXT, company_id INTEGER,
    impact TEXT, note TEXT
);
"""

SENTIMENT_SCHEMA = """
CREATE TABLE senti_raw (
    id INTEGER PRIMARY KEY,
    company_id INTEGER,
    ticker TEXT,
    publish_time TEXT
);
CREATE TABLE stock_kline (
    id INTEGER PRIMARY KEY,
    company_id INTEGER,
    ticker TEXT,
    freq TEXT,
    ts TEXT,
    o REAL,
    h REAL,
    l REAL,
    c REAL
    ,vol REAL
);
CREATE TABLE funda_semi_nodes (
    ticker TEXT,
    name TEXT,
    layer TEXT
);
CREATE TABLE senti_retail_daily (
    company_id INTEGER, trade_date TEXT, valid_count INTEGER,
    net_sentiment_weighted REAL, net_sentiment_plain REAL,
    net_sentiment REAL, coverage REAL, usable INTEGER
);
CREATE TABLE event_item (
    entity_type TEXT, entity_id INTEGER, title TEXT, url TEXT, source TEXT,
    published_at TEXT, sentiment TEXT, materiality TEXT, summary_ai TEXT
);
"""


def _initialize(path: Path, schema: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()


def _execute(path: Path, statements: list[tuple[str, tuple]]) -> None:
    conn = sqlite3.connect(path)
    try:
        for sql, parameters in statements:
            conn.execute(sql, parameters)
        conn.commit()
    finally:
        conn.close()


def build_dev_fixture(target_root: str | Path, *, replace: bool = False) -> dict:
    root = Path(target_root).expanduser().resolve()
    marker = root / "DEV_FIXTURE_MANIFEST.json"
    if root.exists() and any(root.iterdir()) and not replace:
        raise FileExistsError(f"fixture target is not empty: {root}")
    if marker.is_file() and replace:
        import shutil

        shutil.rmtree(root)
    elif root.exists() and replace:
        raise RuntimeError("replace is allowed only for a directory created by this fixture tool")
    root.mkdir(parents=True, exist_ok=True)
    data_root = root / "data"
    content_root = root / "content"
    state_root = root / "state"
    _initialize(data_root / "research.db", RESEARCH_SCHEMA)
    _execute(
        data_root / "research.db",
        [
            (
                "INSERT INTO industry(id,name,description,chain_position,tier,status,created_at) "
                "VALUES(1,?,?,?,?,?,?)",
                ("本地开发样例", "仅用于本地页面和健康检查", "synthetic", 3, "仅记录", "fixture"),
            ),
            (
                "INSERT INTO company(id,name,ticker) VALUES(1,?,?)",
                ("本地开发公司", "000001.SZ"),
            ),
            (
                "INSERT INTO source(id,title,quality_tier,file_path) VALUES(1,?,?,?)",
                ("本地开发 PDF", 1, "papers/fixture.pdf"),
            ),
            (
                "INSERT INTO theme(id,name,category,summary,status) VALUES(?,?,?,?,?)",
                ("fixture-theme", "本地开发主题", "测试", "数据库承载的主题摘要", "跟踪"),
            ),
            (
                "INSERT INTO theme_industry(id,theme_id,industry_id,impact,note) "
                "VALUES(1,?,?,?,?)",
                ("fixture-theme", 1, "观察", "数据库关系样例"),
            ),
            (
                "INSERT INTO theme_company(id,theme_id,company_id,impact,note) "
                "VALUES(1,?,?,?,?)",
                ("fixture-theme", 1, "观察", "数据库关系样例"),
            ),
        ],
    )
    _initialize(data_root / "sentiment.db", SENTIMENT_SCHEMA)
    init_opportunity_db(data_root / "opportunity_lens.db", reset=False)
    _execute(
        data_root / "opportunity_lens.db",
        [(
            """
            INSERT INTO opportunity_run(
                id,question,run_mode,run_status,schema_version,api_contract_version,
                score_rule_version,source_tier_version,search_protocol_version,
                report_template_version,pdf_export_version,research_question,display_title
            ) VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "本地开发问题", "c_open", "created", "fixture", "fixture",
                "fixture", "fixture", "fixture", "fixture", "fixture",
                "本地开发问题", "本地开发 Run",
            ),
        )],
    )
    initialize_database(data_root / "financial.db")
    _execute(
        data_root / "financial.db",
        [(
            "INSERT INTO financial_security(research_company_id,canonical_name,ticker,market) "
            "VALUES(1,?,?,?)",
            ("本地开发公司", "000001.SZ", "CN"),
        )],
    )
    (content_root / "docs" / "industries").mkdir(parents=True, exist_ok=True)
    (content_root / "docs" / "industries" / "本地开发样例.md").write_text(
        "# 本地开发样例\n\n该文档只用于隔离开发，不含生产研究内容。\n",
        encoding="utf-8",
    )
    (content_root / "papers").mkdir(parents=True, exist_ok=True)
    (content_root / "papers" / "fixture.pdf").write_bytes(b"%PDF-1.4\n% synthetic fixture\n")
    (state_root / "cache").mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "honghu.local_dev_fixture.v1",
        "synthetic_only": True,
        "data_root": "data",
        "content_root": "content",
        "state_root": "state",
        "production_dependency": False,
        "databases": [
            "research.db",
            "sentiment.db",
            "opportunity_lens.db",
            "financial.db",
        ],
    }
    marker.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an isolated synthetic Viewer fixture")
    parser.add_argument("target_root", type=Path)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            build_dev_fixture(args.target_root, replace=args.replace),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
