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
    file_path TEXT
);
CREATE TABLE company (
    id INTEGER PRIMARY KEY,
    name TEXT,
    ticker TEXT
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
    c REAL
);
CREATE TABLE funda_semi_nodes (
    ticker TEXT,
    name TEXT,
    layer TEXT
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
    (content_root / "docs" / "themes").mkdir(parents=True, exist_ok=True)
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
