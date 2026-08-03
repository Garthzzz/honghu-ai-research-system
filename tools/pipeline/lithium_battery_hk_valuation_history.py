from __future__ import annotations

"""Fetch a bounded, point-in-time monthly valuation history for two HK peers.

Only 3931.HK and 0666.HK are in scope.  Annual EPS/BPS become usable after the
annual-report publication date; month-end PE/PB therefore never uses a later
year's accounts before publication.  Statement values are CNY, prices are HKD,
and HKDCNY is aligned to each month-end before the multiple is calculated.
"""

import argparse
import bisect
import hashlib
import json
import math
from datetime import date
from pathlib import Path
from typing import Any

import yfinance as yf


ROOT = Path(__file__).resolve().parents[2]
FINANCIAL_SNAPSHOT = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "models"
    / "battery_financial_snapshot_v1.json"
)
FILING_MANIFEST = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "sources"
    / "company_filing_manifest_v1.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "models"
    / "battery_hk_valuation_history_v1.json"
)
TICKERS = ("3931.HK", "0666.HK")
START_DATE = "2022-01-01"
END_DATE = "2026-07-29"


def _sha(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _annual_values(
    snapshot: dict[str, Any],
    ticker: str,
    publication_dates: dict[tuple[str, int], str],
) -> list[dict[str, Any]]:
    row = snapshot["yfinance"][ticker]
    income = row["income_stmt"]["rows"]
    balance = row["balance_sheet"]["rows"]
    net_income = income.get("Net Income Common Stockholders") or income.get(
        "Net Income"
    )
    shares = balance.get("Ordinary Shares Number") or income.get(
        "Diluted Average Shares"
    )
    equity = balance.get("Stockholders Equity")
    result: list[dict[str, Any]] = []
    for raw_period, raw_income in (net_income or {}).items():
        year = int(str(raw_period)[:4])
        period_key = next(
            (key for key in (shares or {}) if str(key)[:4] == str(year)), None
        )
        equity_key = next(
            (key for key in (equity or {}) if str(key)[:4] == str(year)), None
        )
        income_value = _finite(raw_income)
        share_value = _finite((shares or {}).get(period_key))
        equity_value = _finite((equity or {}).get(equity_key))
        if (
            income_value is None
            or share_value is None
            or equity_value is None
            or share_value <= 0
            or equity_value <= 0
        ):
            continue
        available_from = publication_dates.get(
            (ticker, year), f"{year + 1}-04-30"
        )
        result.append(
            {
                "fiscalYear": year,
                "availableFrom": available_from,
                "netIncomeCny": income_value,
                "equityCny": equity_value,
                "shares": share_value,
                "epsCny": income_value / share_value,
                "bpsCny": equity_value / share_value,
                "sourceFields": [
                    "yfinance.income_stmt.Net Income Common Stockholders",
                    "yfinance.balance_sheet.Stockholders Equity",
                    "yfinance.balance_sheet.Ordinary Shares Number",
                ],
            }
        )
    return sorted(result, key=lambda item: item["availableFrom"])


def _publication_dates(manifest: dict[str, Any]) -> dict[tuple[str, int], str]:
    result: dict[tuple[str, int], str] = {}
    for row in manifest.get("rows") or []:
        period = str(row.get("period") or "")
        if not period.endswith("A") or row.get("status") != "downloaded":
            continue
        year = int(period[:-1])
        result[(str(row["ticker"]), year)] = str(row["filename"])[:10]
    return result


def _daily_close(frame: Any) -> list[tuple[str, float]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    series = frame["Close"]
    if getattr(series, "ndim", 1) > 1:
        series = series.iloc[:, 0]
    result = []
    for index, raw in series.dropna().items():
        value = _finite(raw)
        if value is not None and value > 0:
            result.append((str(index)[:10], value))
    return result


def _month_ends(rows: list[tuple[str, float]]) -> list[tuple[str, float]]:
    by_month: dict[str, tuple[str, float]] = {}
    for day, value in rows:
        by_month[day[:7]] = (day, value)
    return [by_month[key] for key in sorted(by_month)]


def _latest_on_or_before(
    rows: list[tuple[str, float]], day: str
) -> tuple[str, float] | None:
    dates = [item[0] for item in rows]
    index = bisect.bisect_right(dates, day) - 1
    return rows[index] if index >= 0 else None


def _financial_available(
    rows: list[dict[str, Any]], day: str
) -> dict[str, Any] | None:
    candidates = [item for item in rows if item["availableFrom"] <= day]
    return candidates[-1] if candidates else None


def build() -> dict[str, Any]:
    snapshot = json.loads(FINANCIAL_SNAPSHOT.read_text(encoding="utf-8"))
    manifest = json.loads(FILING_MANIFEST.read_text(encoding="utf-8"))
    publication_dates = _publication_dates(manifest)
    fx_rows = _daily_close(
        yf.Ticker("HKDCNY=X").history(
            start=START_DATE,
            end=END_DATE,
            interval="1d",
            auto_adjust=False,
            actions=False,
        )
    )
    if not fx_rows:
        raise RuntimeError("HKDCNY月末换算序列为空")
    companies = []
    for ticker in TICKERS:
        price_rows = _month_ends(
            _daily_close(
                yf.Ticker(ticker).history(
                    start=START_DATE,
                    end=END_DATE,
                    interval="1d",
                    auto_adjust=False,
                    actions=False,
                )
            )
        )
        if len(price_rows) < 12:
            raise RuntimeError(f"{ticker}月末价格不足12期")
        annual = _annual_values(snapshot, ticker, publication_dates)
        observations = []
        for day, close_hkd in price_rows:
            fx = _latest_on_or_before(fx_rows, day)
            financial = _financial_available(annual, day)
            if fx is None or financial is None:
                continue
            hkd_cny = fx[1]
            pe_ttm = (
                close_hkd * hkd_cny / financial["epsCny"]
                if financial["epsCny"] > 0
                else None
            )
            pb = close_hkd * hkd_cny / financial["bpsCny"]
            observations.append(
                {
                    "date": day,
                    "closeHkd": close_hkd,
                    "hkdCny": hkd_cny,
                    "financialYear": financial["fiscalYear"],
                    "financialAvailableFrom": financial["availableFrom"],
                    "epsCny": financial["epsCny"],
                    "bpsCny": financial["bpsCny"],
                    "peTtmApprox": pe_ttm,
                    "pbApprox": pb,
                    "formula": (
                        "PE≈月末收盘价（港元）×HKDCNY÷已公开年报归母EPS（人民币）；"
                        "PB≈月末收盘价（港元）×HKDCNY÷已公开年报BPS（人民币）"
                    ),
                }
            )
        companies.append(
            {
                "ticker": ticker,
                "statementCurrency": "CNY",
                "tradingCurrency": "HKD",
                "annualAnchors": annual,
                "observations": observations,
                "positivePeObservations": sum(
                    1 for row in observations if row["peTtmApprox"] is not None
                ),
                "pbObservations": len(observations),
            }
        )
    payload = {
        "schemaVersion": "lithium_battery.hk_valuation_history.v1",
        "asOfDate": "2026-07-28",
        "scope": list(TICKERS),
        "sourceContract": {
            "price": "yfinance.history month-end unadjusted Close",
            "fx": "yfinance HKDCNY=X, latest close on or before month-end",
            "financials": (
                "existing bounded yfinance annual statements; each fiscal year is "
                "used only after the annual report became public"
            ),
            "frequency": "monthly",
            "lookAheadControl": (
                "2025 uses the actual downloaded annual-report date; earlier years "
                "use the conservative next-year April 30 availability date"
            ),
            "limitation": (
                "This is a point-in-time annual EPS/BPS approximation, not a vendor "
                "historical TTM multiple. Negative EPS months do not produce PE."
            ),
        },
        "companies": companies,
    }
    payload["contentSha256"] = _sha(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": args.output.relative_to(ROOT).as_posix(),
                "contentSha256": payload["contentSha256"],
                "companies": {
                    row["ticker"]: {
                        "pb": row["pbObservations"],
                        "positivePe": row["positivePeObservations"],
                    }
                    for row in payload["companies"]
                },
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
