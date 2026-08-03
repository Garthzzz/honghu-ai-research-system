from __future__ import annotations

"""Bounded financial and market snapshot for the copper B-track research.

The collector only writes an auditable JSON artifact.  It uses the project Wind
HTTP client for two A-share securities and yfinance for MMG's Hong Kong listing.
It does not write research.db or financial.db.
"""

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yfinance as yf

from tools.pipeline.wind_http_provider import (
    WindHttpUnavailable,
    assert_wind_request_scope,
    fetch_current_market_financial_snapshot,
    load_wind_http_client,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "cache" / "copper_research" / "copper_financial_snapshot.json"
TRADE_DATE = "2026-07-24"
A_TICKERS = ("601899.SH", "603993.SH")
YEARS = (2021, 2022, 2023, 2024, 2025)

HISTORICAL_FIELDS = (
    "oper_rev",
    "np_belongto_parcomsh",
    "net_cash_flows_oper_act",
    "cash_pay_acq_const_fiolta",
    "tot_assets",
    "tot_equity",
    "tot_liab",
    "roe",
    "roa2",
    "grossprofitmargin",
    "netprofitmargin",
)

CONSENSUS_FIELDS = (
    "west_sales_fy1",
    "west_sales_fy2",
    "west_sales_fy3",
    "west_netprofit_fy1",
    "west_netprofit_fy2",
    "west_netprofit_fy3",
    "west_eps_fy1",
    "west_eps_fy2",
    "west_eps_fy3",
    "west_avgroe_fy1",
    "west_avgroe_fy2",
    "west_avgroe_fy3",
)

YF_INFO_FIELDS = (
    "currentPrice",
    "previousClose",
    "marketCap",
    "enterpriseValue",
    "trailingPE",
    "forwardPE",
    "priceToBook",
    "priceToSalesTrailing12Months",
    "enterpriseToEbitda",
    "trailingEps",
    "bookValue",
    "returnOnEquity",
    "returnOnAssets",
    "grossMargins",
    "profitMargins",
    "operatingCashflow",
    "freeCashflow",
    "totalCash",
    "totalDebt",
    "sharesOutstanding",
    "currency",
    "financialCurrency",
)


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _hash(payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _frame_rows(frame: Any) -> dict[str, dict[str, float | None]]:
    if frame is None or getattr(frame, "empty", True):
        return {}
    clean = frame.where(frame.notna(), None)
    result: dict[str, dict[str, float | None]] = {}
    for index, row in clean.iterrows():
        result[str(index).upper()] = {
            str(column).lower(): _finite(value.item() if hasattr(value, "item") else value)
            for column, value in row.items()
        }
    return result


def _wind_wss(
    client: Any,
    *,
    fields: tuple[str, ...],
    options: str,
) -> dict[str, Any]:
    assert_wind_request_scope(
        security_count=len(A_TICKERS),
        field_count=len(fields),
        estimated_observations=len(A_TICKERS) * len(fields),
    )
    response = client.wss(",".join(A_TICKERS), ",".join(fields), options)
    error_code = int(getattr(response, "ErrorCode", -1))
    if error_code != 0:
        raise WindHttpUnavailable(
            f"Copper Wind WSS failed: ErrorCode={error_code}; options={options}"
        )
    rows = _frame_rows(getattr(response, "dfData", None))
    if not rows:
        raise WindHttpUnavailable(f"Copper Wind WSS returned empty rows: {options}")
    return {"fields": list(fields), "options": options, "rows": rows}


def _collect_wind() -> dict[str, Any]:
    client = load_wind_http_client()
    current: dict[str, Any] = {}
    for ticker in A_TICKERS:
        current[ticker] = fetch_current_market_financial_snapshot(
            ticker,
            trade_date=TRADE_DATE,
            client=client,
        )
    annual = {
        str(year): _wind_wss(
            client,
            fields=HISTORICAL_FIELDS,
            options=f"rptDate={year}1231;rptType=1;unit=1",
        )
        for year in YEARS
    }
    consensus = _wind_wss(
        client,
        fields=CONSENSUS_FIELDS,
        options=f"tradeDate={TRADE_DATE.replace('-', '')};unit=1",
    )
    return {
        "status": "ok",
        "trade_date": TRADE_DATE,
        "current": current,
        "annual": annual,
        "consensus_fy1_fy3": consensus,
    }


def _dataframe_payload(frame: Any) -> dict[str, Any]:
    if frame is None or getattr(frame, "empty", True):
        return {"status": "empty", "columns": [], "rows": {}}
    clean = frame.where(frame.notna(), None)
    rows: dict[str, dict[str, float | None]] = {}
    for index, row in clean.iterrows():
        rows[str(index)] = {
            str(column): _finite(value.item() if hasattr(value, "item") else value)
            for column, value in row.items()
        }
    return {
        "status": "ok",
        "columns": [str(column) for column in clean.columns],
        "rows": rows,
    }


def _collect_yfinance() -> dict[str, Any]:
    ticker = yf.Ticker("1208.HK")
    info = ticker.get_info() or {}
    return {
        "status": "ok",
        "ticker": "1208.HK",
        "access_method": "yfinance get_info + annual financial statements",
        "info": {field: info.get(field) for field in YF_INFO_FIELDS},
        "income_stmt": _dataframe_payload(ticker.income_stmt),
        "balance_sheet": _dataframe_payload(ticker.balance_sheet),
        "cash_flow": _dataframe_payload(ticker.cashflow),
    }


def collect() -> dict[str, Any]:
    estimated_wind_observations = (
        len(A_TICKERS) * 12
        + len(A_TICKERS) * len(HISTORICAL_FIELDS) * len(YEARS)
        + len(A_TICKERS) * len(CONSENSUS_FIELDS)
    )
    payload: dict[str, Any] = {
        "snapshot_version": "copper_b_20260726.financial_snapshot.v1",
        "research_run_ref": "copper_b_20260726",
        "accessed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope_audit": {
            "wind_security_count": len(A_TICKERS),
            "wind_tickers": list(A_TICKERS),
            "wind_current_field_count": 12,
            "wind_historical_field_count": len(HISTORICAL_FIELDS),
            "wind_historical_years": list(YEARS),
            "wind_consensus_field_count": len(CONSENSUS_FIELDS),
            "wind_estimated_observations": estimated_wind_observations,
            "large_request_permission_required": False,
            "purpose": "铜行业三家核心公司实际财务、当前估值与冻结后的FY1—FY3外部对账",
        },
    }
    try:
        payload["wind"] = _collect_wind()
    except WindHttpUnavailable as exc:
        payload["wind"] = {
            "status": "unavailable",
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:240],
        }
    try:
        payload["yfinance"] = _collect_yfinance()
    except Exception as exc:  # noqa: BLE001 - audit external provider failure
        payload["yfinance"] = {
            "status": "unavailable",
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:240],
        }
    payload["content_sha256"] = _hash(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = collect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "sha256": payload["content_sha256"],
                "scope_audit": payload["scope_audit"],
                "wind_status": payload["wind"]["status"],
                "yfinance_status": payload["yfinance"]["status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
