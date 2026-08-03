from __future__ import annotations

"""Bounded Wind/yfinance snapshot for the nine battery-company models.

The request is deliberately below the project permission thresholds:
7 A-share securities, at most 12 fields per request, five annual periods and
one FY1-FY3 consensus snapshot.  The two Hong Kong securities use yfinance.
This collector only writes JSON; database application is a separate step.
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
    latest_completed_trade_date,
    load_wind_http_client,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "models"
    / "battery_financial_snapshot_v1.json"
)
A_TICKERS = (
    "300438.SZ",
    "300750.SZ",
    "002594.SZ",
    "002074.SZ",
    "300014.SZ",
    "300207.SZ",
    "688567.SH",
)
HK_TICKERS = ("3931.HK", "0666.HK")
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
    return {
        str(index).upper(): {
            str(column).lower(): _finite(
                value.item() if hasattr(value, "item") else value
            )
            for column, value in row.items()
        }
        for index, row in clean.iterrows()
    }


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
            f"Battery Wind WSS failed: ErrorCode={error_code}; options={options}"
        )
    rows = _frame_rows(getattr(response, "dfData", None))
    if not rows:
        raise WindHttpUnavailable(f"Battery Wind WSS returned no rows: {options}")
    return {"fields": list(fields), "options": options, "rows": rows}


def _collect_wind() -> dict[str, Any]:
    client = load_wind_http_client()
    trade_date = latest_completed_trade_date(client=client)
    current = {
        ticker: fetch_current_market_financial_snapshot(
            ticker,
            trade_date=trade_date,
            client=client,
        )
        for ticker in A_TICKERS
    }
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
        options=f"tradeDate={trade_date.replace('-', '')};unit=1",
    )
    return {
        "status": "ok",
        "trade_date": trade_date,
        "current": current,
        "annual": annual,
        "consensus_fy1_fy3": consensus,
    }


def _dataframe_payload(frame: Any) -> dict[str, Any]:
    if frame is None or getattr(frame, "empty", True):
        return {"status": "empty", "columns": [], "rows": {}}
    clean = frame.where(frame.notna(), None)
    return {
        "status": "ok",
        "columns": [str(column) for column in clean.columns],
        "rows": {
            str(index): {
                str(column): _finite(
                    value.item() if hasattr(value, "item") else value
                )
                for column, value in row.items()
            }
            for index, row in clean.iterrows()
        },
    }


def _collect_yfinance(ticker_code: str) -> dict[str, Any]:
    ticker = yf.Ticker(ticker_code)
    info = ticker.get_info() or {}
    return {
        "status": "ok",
        "ticker": ticker_code,
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
        "schema_version": "lithium_battery.financial_snapshot.v1",
        "research_run_ref": "lithium_battery_b_20260728",
        "accessed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope_audit": {
            "wind_security_count": len(A_TICKERS),
            "wind_tickers": list(A_TICKERS),
            "max_fields_per_request": max(
                12, len(HISTORICAL_FIELDS), len(CONSENSUS_FIELDS)
            ),
            "estimated_wind_observations": estimated_wind_observations,
            "large_request_permission_required": False,
            "reason": (
                "7只A股、单次不超过12字段、5个年末截面和1个一致预期截面，"
                "未达到AGENTS.md大规模取数门槛。"
            ),
        },
    }
    try:
        payload["wind"] = _collect_wind()
    except Exception as exc:  # noqa: BLE001 - preserve provider failure audit
        payload["wind"] = {
            "status": "failed",
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:500],
        }
    payload["yfinance"] = {}
    for ticker in HK_TICKERS:
        try:
            payload["yfinance"][ticker] = _collect_yfinance(ticker)
        except Exception as exc:  # noqa: BLE001
            payload["yfinance"][ticker] = {
                "status": "failed",
                "ticker": ticker,
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:500],
            }
    try:
        fx_history = yf.Ticker("HKDCNY=X").history(period="5d", interval="1d")
        fx_rows = [
            {
                "date": str(index.date()),
                "close": _finite(row.get("Close")),
            }
            for index, row in fx_history.iterrows()
            if _finite(row.get("Close")) is not None
        ]
        payload["fx"] = {
            "status": "ok" if fx_rows else "empty",
            "ticker": "HKDCNY=X",
            "rows": fx_rows,
            "latest": fx_rows[-1] if fx_rows else None,
        }
    except Exception as exc:  # noqa: BLE001
        payload["fx"] = {
            "status": "failed",
            "ticker": "HKDCNY=X",
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:500],
        }
    payload["content_sha256"] = _hash(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = collect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "wind": result["wind"].get("status"),
                "trade_date": result["wind"].get("trade_date"),
                "yfinance": {
                    ticker: row.get("status")
                    for ticker, row in result["yfinance"].items()
                },
                "estimated_wind_observations": result["scope_audit"][
                    "estimated_wind_observations"
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0 if result["wind"].get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
