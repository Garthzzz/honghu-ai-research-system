#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Freeze a narrow overseas/Taiwan HDI peer snapshot for the B-track report.

The collector is intentionally small: seven listed peers, current ``get_info``
fields, and four single-security TWSE queries.  It writes only a cache artifact;
it never writes research.db or financial.db.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import yfinance as yf


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "cache" / "hdi_research" / "overseas_peer_snapshot.json"
AS_OF_DATE = "2026-07-26"
TWSE_MARKET_DATE = "20260724"

PEERS = [
    {"company_id": 589, "name": "华通电脑", "ticker": "2313.TW", "twse_symbol": "2313"},
    {"company_id": 218, "name": "AT&S", "ticker": "ATS.VI"},
    {"company_id": 562, "name": "TTM Technologies", "ticker": "TTMI"},
    {"company_id": 467, "name": "欣兴电子", "ticker": "3037.TW", "twse_symbol": "3037"},
    {"company_id": 563, "name": "健鼎科技", "ticker": "3044.TW", "twse_symbol": "3044"},
    {"company_id": 593, "name": "名幸电子", "ticker": "6787.T"},
    {"company_id": 561, "name": "臻鼎科技", "ticker": "4958.TW", "twse_symbol": "4958"},
]

YF_FIELDS = [
    "currency",
    "currentPrice",
    "marketCap",
    "trailingPE",
    "forwardPE",
    "priceToBook",
    "priceToSalesTrailing12Months",
    "enterpriseToEbitda",
    "returnOnEquity",
    "returnOnAssets",
    "profitMargins",
    "grossMargins",
    "revenueGrowth",
    "earningsGrowth",
    "totalDebt",
    "totalCash",
    "operatingCashflow",
]


def _get_json(url: str) -> Any:
    request = Request(
        url,
        headers={
            "User-Agent": "industry-demo-hdi-research/1.0",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def _twse_url(endpoint: str, **params: str) -> str:
    return f"https://www.twse.com.tw/rwd/en/afterTrading/{endpoint}?{urlencode(params)}"


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "--", "N/A"}:
        return None
    return float(text)


def collect() -> dict[str, Any]:
    company_master_url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
    company_master = _get_json(company_master_url)
    company_by_symbol = {
        str(item.get("公司代號", "")).strip(): item for item in company_master
    }

    rows: list[dict[str, Any]] = []
    for peer in PEERS:
        info = yf.Ticker(peer["ticker"]).get_info()
        row: dict[str, Any] = {
            **peer,
            "yfinance": {field: info.get(field) for field in YF_FIELDS},
        }
        symbol = peer.get("twse_symbol")
        if symbol:
            ratio_url = _twse_url(
                "BWIBBU",
                date=TWSE_MARKET_DATE,
                stockNo=symbol,
                response="json",
            )
            price_url = _twse_url(
                "STOCK_DAY",
                date=TWSE_MARKET_DATE,
                stockNo=symbol,
                response="json",
            )
            ratio_payload = _get_json(ratio_url)
            price_payload = _get_json(price_url)
            if ratio_payload.get("stat") != "OK" or not ratio_payload.get("data"):
                raise RuntimeError(f"TWSE ratio unavailable for {symbol}")
            if price_payload.get("stat") != "OK" or not price_payload.get("data"):
                raise RuntimeError(f"TWSE price unavailable for {symbol}")
            ratio = ratio_payload["data"][-1]
            price = price_payload["data"][-1]
            master = company_by_symbol.get(symbol)
            if not master:
                raise RuntimeError(f"TWSE company master unavailable for {symbol}")
            shares = _to_float(master.get("已發行普通股數或TDR原股發行股數"))
            close = _to_float(price[6])
            if shares is None or close is None:
                raise RuntimeError(f"TWSE market-cap inputs unavailable for {symbol}")
            row["twse_official"] = {
                "market_date": ratio[0],
                "close_twd": close,
                "issued_common_shares": shares,
                "market_cap_twd_bn": round(shares * close / 1_000_000_000, 2),
                "pe": _to_float(ratio[3]),
                "pb": _to_float(ratio[4]),
                "market_cap_formula": (
                    "台交所已发行普通股数×当日收盘价÷10亿；"
                    "属于由两项官方字段计算的本币市值。"
                ),
                "ratio_url": ratio_url,
                "price_url": price_url,
                "company_master_url": company_master_url,
            }
        rows.append(row)

    return {
        "schema_version": "hdi.overseas_peer_snapshot.v1",
        "as_of_date": AS_OF_DATE,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scope": {
            "security_count": len(PEERS),
            "twse_security_count": sum("twse_symbol" in peer for peer in PEERS),
            "policy": (
                "海外行情使用yfinance窄字段快照；中国台湾四家公司另用台交所"
                "单证券官方接口核验收盘价、PE、PB和已发行股本。"
            ),
            "database_write": False,
        },
        "official_operating_snapshots": {
            "TTMI": {
                "period": "2026Q1",
                "currency": "USD",
                "revenue_mn": 846.0,
                "revenue_yoy_pct": 30.0,
                "gaap_net_income_mn": 50.0,
                "adjusted_ebitda_mn": 132.9,
                "adjusted_ebitda_margin_pct": 15.7,
                "operating_cash_flow_mn": 21.7,
                "capex_mn": 106.8,
                "data_center_networking_revenue_share_pct": 36.0,
                "source_url": (
                    "https://investors.ttm.com/sec-filings/all-sec-filings/content/"
                    "0001193125-26-191490/d103788dex991.htm"
                ),
                "note": "公司8-K附件；Adjusted EBITDA为非GAAP口径。",
            },
            "ATS.VI": {
                "period": "FY2025/26",
                "currency": "EUR",
                "revenue_mn": 1790.8,
                "revenue_yoy_pct": 12.7,
                "profit_for_period_mn": -25.6,
                "ebitda_mn": 418.0,
                "ebitda_margin_pct": 23.3,
                "operating_cash_flow_mn": 413.7,
                "capex_mn": 178.3,
                "fy2026_27_revenue_growth_guidance_pct": [30.0, 35.0],
                "fy2026_27_ebitda_margin_guidance_pct": [25.0, 29.0],
                "fy2026_27_capex_guidance_mn": 400.0,
                "source_url": (
                    "https://ats.net/en/ir-news/"
                    "ats-closes-successful-financial-year-with-strong-fourth-quarter/"
                ),
                "note": "公司年度业绩新闻稿；财年截至2026-03-31。",
            },
        },
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = collect()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "security_count": len(payload["rows"]),
                "twse_security_count": payload["scope"]["twse_security_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
