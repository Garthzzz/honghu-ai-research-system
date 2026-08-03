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
    created_at TEXT
);
CREATE TABLE source (
    id INTEGER PRIMARY KEY,
    title TEXT,
    quality_tier INTEGER
);
CREATE TABLE company (
    id INTEGER PRIMARY KEY,
    name TEXT,
    ticker TEXT
);
"""

SENTIMENT_SCHEMA = """
CREATE TABLE senti_raw (id INTEGER PRIMARY KEY);
CREATE TABLE stock_kline (id INTEGER PRIMARY KEY);
CREATE TABLE funda_semi_nodes (id INTEGER PRIMARY KEY);
"""


def _initialize(path: Path, schema: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(schema)
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
    conn = sqlite3.connect(data_root / "research.db")
    try:
        conn.execute(
            "INSERT INTO industry(id,name,description,chain_position,created_at) "
            "VALUES(1,?,?,?,?)",
            ("本地开发样例", "仅用于本地页面和健康检查", "synthetic", "fixture"),
        )
        conn.commit()
    finally:
        conn.close()
    _initialize(data_root / "sentiment.db", SENTIMENT_SCHEMA)
    init_opportunity_db(data_root / "opportunity_lens.db", reset=False)
    initialize_database(data_root / "financial.db")
    (content_root / "docs" / "industries").mkdir(parents=True, exist_ok=True)
    (content_root / "docs" / "industries" / "本地开发样例.md").write_text(
        "# 本地开发样例\n\n该文档只用于隔离开发，不含生产研究内容。\n",
        encoding="utf-8",
    )
    (content_root / "papers").mkdir(parents=True, exist_ok=True)
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
