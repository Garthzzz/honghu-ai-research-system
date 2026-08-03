from __future__ import annotations

"""Provision a verified listed-company identity before A/B or C research ingest.

This is deliberately separate from the Opportunity Lens database transaction:
the C database remains a read-only consumer of the A/B company identity layer.
"""

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Iterable

from tools.financial.constants import DB_PATH as DEFAULT_FINANCIAL_DB
from tools.financial.db import initialize_database as initialize_financial_database
from tools.financial.repository import upsert_security


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESEARCH_DB = ROOT / "data" / "research.db"


def ensure_listed_company_profile(
    *,
    canonical_name: str,
    ticker: str,
    market: str,
    listing_status: str,
    verification_source_ref: str,
    aliases: Iterable[str] = (),
    research_db_path: str | Path = DEFAULT_RESEARCH_DB,
    financial_db_path: str | Path = DEFAULT_FINANCIAL_DB,
    confirm_live: bool = False,
) -> dict[str, object]:
    name = str(canonical_name or "").strip()
    code = str(ticker or "").strip().upper()
    market_name = str(market or "").strip()
    source_ref = str(verification_source_ref or "").strip()
    if not all((name, code, market_name, listing_status, source_ref)):
        raise ValueError("公司建档必须有规范名称、证券代码、市场、上市状态和身份核验来源")
    research_path = Path(research_db_path).resolve()
    financial_path = Path(financial_db_path).resolve()
    if research_path == DEFAULT_RESEARCH_DB.resolve() and not confirm_live:
        raise PermissionError("写入 live 公司主数据必须显式 confirm_live=True")
    if financial_path == DEFAULT_FINANCIAL_DB.resolve() and not confirm_live:
        raise PermissionError("写入 live 财务证券映射必须显式 confirm_live=True")
    initialize_financial_database(financial_path)
    conn = sqlite3.connect(research_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute("ATTACH DATABASE ? AS financial", (str(financial_path),))
        conn.execute("BEGIN IMMEDIATE")
        ticker_rows = conn.execute(
            "SELECT id,name,ticker,market FROM company WHERE upper(ticker)=upper(?)",
            (code,),
        ).fetchall()
        if len(ticker_rows) > 1:
            raise ValueError(f"证券代码 {code} 对应多个公司记录，必须先完成身份合并")
        created = False
        if ticker_rows:
            row = ticker_rows[0]
            if str(row["market"] or "").strip() and str(row["market"]).strip() != market_name:
                raise ValueError(f"证券代码 {code} 的市场与现有记录冲突")
            company_id = int(row["id"])
            conn.execute(
                """UPDATE company
                   SET market=COALESCE(market,?),
                       listing_status=COALESCE(listing_status,?),
                       note=COALESCE(note,?)
                   WHERE id=?""",
                (
                    market_name,
                    listing_status,
                    f"身份核验来源：{source_ref}",
                    company_id,
                ),
            )
        else:
            name_rows = conn.execute("SELECT id,ticker,market FROM company WHERE name=?", (name,)).fetchall()
            if len(name_rows) > 1:
                raise ValueError(f"公司名称 {name} 对应多个主体，必须补充人工身份核验")
            if name_rows:
                row = name_rows[0]
                existing_ticker = str(row["ticker"] or "").strip().upper()
                if existing_ticker and existing_ticker != code:
                    raise ValueError(f"同名公司 {name} 已绑定不同证券代码 {existing_ticker}")
                company_id = int(row["id"])
                conn.execute(
                    "UPDATE company SET ticker=?,market=COALESCE(market,?),listing_status=COALESCE(listing_status,?),note=COALESCE(note,?) WHERE id=?",
                    (code, market_name, listing_status, f"身份核验来源：{source_ref}", company_id),
                )
            else:
                company_id = int(conn.execute(
                    "INSERT INTO company(name,ticker,market,listing_status,note) VALUES(?,?,?,?,?)",
                    (name, code, market_name, listing_status, f"身份核验来源：{source_ref}"),
                ).lastrowid)
                created = True
        alias_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='company_identity_alias'"
        ).fetchone()
        if alias_table:
            for alias in dict.fromkeys([name, *(str(value).strip() for value in aliases if str(value).strip())]):
                conn.execute(
                    """INSERT OR IGNORE INTO company_identity_alias(
                         canonical_company_id,alias,alias_type,source) VALUES(?,?,?,?)""",
                    (company_id, alias, "verified_name", source_ref),
                )
        security_id = upsert_security(
            conn, schema="financial", research_company_id=company_id,
            canonical_name=name, ticker=code, market=market_name,
            listing_status=listing_status,
        )
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("research.db foreign_key_check 失败")
        if conn.execute("PRAGMA financial.foreign_key_check").fetchall():
            raise RuntimeError("financial.db foreign_key_check 失败")
        conn.commit()
        return {
            "company_id": company_id, "financial_security_id": security_id,
            "created": created, "company_url": f"/company/{company_id}",
            "identity_source_ref": source_ref,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--market", required=True)
    parser.add_argument("--listing-status", required=True)
    parser.add_argument("--verification-source-ref", required=True)
    parser.add_argument("--alias", action="append", default=[])
    parser.add_argument("--research-db", type=Path, default=DEFAULT_RESEARCH_DB)
    parser.add_argument("--financial-db", type=Path, default=DEFAULT_FINANCIAL_DB)
    parser.add_argument("--confirm-live", action="store_true")
    args = parser.parse_args(argv)
    result = ensure_listed_company_profile(
        canonical_name=args.name, ticker=args.ticker, market=args.market,
        listing_status=args.listing_status,
        verification_source_ref=args.verification_source_ref, aliases=args.alias,
        research_db_path=args.research_db, financial_db_path=args.financial_db,
        confirm_live=args.confirm_live,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
