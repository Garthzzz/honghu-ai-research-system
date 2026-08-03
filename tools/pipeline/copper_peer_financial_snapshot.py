from __future__ import annotations

"""Collect a bounded financial snapshot for the copper valuation peer set.

The command writes JSON only.  Seven A-share peers use the project Wind HTTP
proxy; one Hong Kong peer uses yfinance.  No database is changed.
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yfinance as yf

from tools.pipeline.copper_financial_snapshot import (
    CONSENSUS_FIELDS,
    HISTORICAL_FIELDS,
    YF_INFO_FIELDS,
    _dataframe_payload,
    _frame_rows,
)
from tools.pipeline.market_snapshot_utils import fetch_live_fx_rates
from tools.pipeline.wind_http_provider import (
    WindHttpUnavailable,
    assert_wind_request_scope,
    fetch_current_market_financial_snapshot,
    load_wind_http_client,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = (
    ROOT / "cache" / "copper_research" / "copper_peer_financial_snapshot.json"
)
# 2026-07-28盘中Wind仅返回部分TTM字段；使用最近完整收盘日避免把盘中空值
# 误写成“接口没有数据”。
TRADE_DATE = "2026-07-27"
A_TICKERS = (
    "601168.SH",
    "600362.SH",
    "000630.SZ",
    "000878.SZ",
    "002203.SZ",
    "601137.SH",
    "601609.SH",
)
HK_TICKERS = ("1258.HK",)
YEARS = (2021, 2022, 2023, 2024, 2025)
ESTIMATED_WIND_OBSERVATIONS = (
    len(A_TICKERS) * 12
    + len(A_TICKERS) * len(HISTORICAL_FIELDS) * len(YEARS)
    + len(A_TICKERS) * len(CONSENSUS_FIELDS)
)


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
            f"Copper peer Wind WSS failed: ErrorCode={error_code}; options={options}"
        )
    rows = _frame_rows(getattr(response, "dfData", None))
    if not rows:
        raise WindHttpUnavailable(f"Copper peer Wind WSS returned empty: {options}")
    return {"fields": list(fields), "options": options, "rows": rows}


def _collect_wind() -> dict[str, Any]:
    client = load_wind_http_client()
    current = {
        ticker: fetch_current_market_financial_snapshot(
            ticker,
            trade_date=TRADE_DATE,
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
        options=f"tradeDate={TRADE_DATE.replace('-', '')};unit=1",
    )
    return {
        "status": "ok",
        "trade_date": TRADE_DATE,
        "current": current,
        "annual": annual,
        "consensus_fy1_fy3": consensus,
    }


def _collect_yfinance() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for symbol in HK_TICKERS:
        ticker = yf.Ticker(symbol)
        info = ticker.get_info() or {}
        result[symbol] = {
            "status": "ok",
            "ticker": symbol,
            "access_method": "yfinance get_info + annual financial statements",
            "info": {field: info.get(field) for field in YF_INFO_FIELDS},
            "income_stmt": _dataframe_payload(ticker.income_stmt),
            "balance_sheet": _dataframe_payload(ticker.balance_sheet),
            "cash_flow": _dataframe_payload(ticker.cashflow),
        }
    return result


def collect() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "snapshot_version": "copper_valuation_peers_20260728.snapshot.v1",
        "accessed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope_audit": {
            "wind_security_count": len(A_TICKERS),
            "wind_tickers": list(A_TICKERS),
            "wind_current_field_count": 12,
            "wind_historical_field_count": len(HISTORICAL_FIELDS),
            "wind_historical_years": list(YEARS),
            "wind_consensus_field_count": len(CONSENSUS_FIELDS),
            "wind_estimated_observations": ESTIMATED_WIND_OBSERVATIONS,
            "large_request_permission_required": False,
            "purpose": "铜估值对比新增同行当前估值、五年财务及FY1—FY3一致预期",
        },
    }
    payload["fx_cny_per_currency"] = fetch_live_fx_rates()
    try:
        payload["wind"] = _collect_wind()
    except WindHttpUnavailable as exc:
        payload["wind"] = {
            "status": "unavailable",
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:300],
        }
    try:
        payload["yfinance"] = _collect_yfinance()
    except Exception as exc:  # noqa: BLE001 - external provider audit
        payload["yfinance"] = {
            "status": "unavailable",
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:300],
        }
    payload["content_sha256"] = _hash(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
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
                "wind_status": payload["wind"]["status"],
                "yfinance_status": (
                    payload["yfinance"].get("status")
                    if isinstance(payload["yfinance"], dict)
                    and "status" in payload["yfinance"]
                    else "ok"
                ),
                "estimated_wind_observations": ESTIMATED_WIND_OBSERVATIONS,
                "content_sha256": payload["content_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
