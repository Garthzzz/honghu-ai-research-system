from __future__ import annotations

"""Apply the bounded battery-company snapshot to ``financial.db`` only."""

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from tools.financial.constants import DB_PATH
from tools.financial.db import connect, initialize_database, transaction, verify_database
from tools.financial.repository import record_source_snapshot, upsert_observation


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOT = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "models"
    / "battery_financial_snapshot_v1.json"
)

CURRENT_SPECS = {
    "price": ("close", "元/股", "market", "Wind WSS.close"),
    "pe_ttm": ("pe_ttm", "倍", "market", "Wind WSS.pe_ttm"),
    "pe_forward": ("pe_forward", "倍", "consensus", "Wind WSS.pe_est_ftm"),
    "pb": ("pb", "倍", "market", "Wind WSS.pb_lf"),
    "ps_ttm": ("ps_ttm", "倍", "market", "Wind WSS.ps_ttm"),
    "ev_ebitda": (
        "ev_ebitda",
        "倍",
        "market",
        "Wind WSS.ev2_to_ebitda",
    ),
    "roe": ("roe", "%", "actual", "Wind WSS.roe_ttm"),
    "roa": ("roa", "%", "actual", "Wind WSS.roa2_ttm"),
    "eps_ttm": ("eps_ttm", "元/股", "actual", "Wind WSS.eps_ttm"),
    "bps_mrq": ("bps_mrq", "元/股", "actual", "Wind WSS.bps_new"),
    "market_cap_cny": (
        "market_cap",
        "亿元人民币",
        "market",
        "Wind WSS.mkt_cap_ard",
    ),
}

ANNUAL_SPECS = {
    "oper_rev": ("revenue", "亿元人民币", 1e8),
    "np_belongto_parcomsh": ("net_income", "亿元人民币", 1e8),
    "net_cash_flows_oper_act": ("operating_cash_flow", "亿元人民币", 1e8),
    "cash_pay_acq_const_fiolta": ("capex", "亿元人民币", 1e8),
    "tot_assets": ("total_assets", "亿元人民币", 1e8),
    "tot_equity": ("total_equity", "亿元人民币", 1e8),
    "tot_liab": ("total_liabilities", "亿元人民币", 1e8),
    "roe": ("roe", "%", 1.0),
    "roa2": ("roa", "%", 1.0),
    "grossprofitmargin": ("gross_margin", "%", 1.0),
    "netprofitmargin": ("net_margin", "%", 1.0),
}

CONSENSUS_SPECS = {
    "west_sales_fy": ("revenue", "亿元人民币", 1e8),
    "west_netprofit_fy": ("net_income", "亿元人民币", 1e8),
    "west_eps_fy": ("eps", "元/股", 1.0),
    "west_avgroe_fy": ("roe", "%", 1.0),
}

YF_INFO_SPECS = {
    "currentPrice": ("close", "港元/股", "market"),
    "trailingPE": ("pe_ttm", "倍", "market"),
    "forwardPE": ("pe_forward", "倍", "consensus"),
    "priceToBook": ("pb", "倍", "market"),
    "priceToSalesTrailing12Months": ("ps_ttm", "倍", "market"),
    "enterpriseToEbitda": ("ev_ebitda", "倍", "market"),
    "trailingEps": ("eps_ttm", "港元/股", "actual"),
    "bookValue": ("bps_mrq", "港元/股", "actual"),
    "returnOnEquity": ("roe", "%", "actual"),
    "returnOnAssets": ("roa", "%", "actual"),
    "grossMargins": ("gross_margin", "%", "actual"),
    "profitMargins": ("net_margin", "%", "actual"),
    "marketCap": ("market_cap", "亿港元", "market"),
}

YF_STATEMENT_SPECS = {
    "income_stmt": {
        "Total Revenue": "revenue",
        "Net Income": "net_income",
        "Gross Profit": "gross_profit",
    },
    "balance_sheet": {
        "Total Assets": "total_assets",
        "Stockholders Equity": "total_equity",
        "Total Liabilities Net Minority Interest": "total_liabilities",
    },
    "cash_flow": {
        "Operating Cash Flow": "operating_cash_flow",
        "Capital Expenditure": "capex",
        "Free Cash Flow": "free_cash_flow",
    },
}


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _sha(payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _securities(conn: Any) -> dict[str, int]:
    return {
        str(row["ticker"]).upper(): int(row["id"])
        for row in conn.execute(
            "SELECT id,ticker FROM financial_security WHERE ticker IS NOT NULL"
        )
    }


def _source(
    conn: Any,
    *,
    provider: str,
    source_ref: str,
    title: str,
    as_of_date: str,
    payload: Mapping[str, Any],
) -> int:
    return record_source_snapshot(
        conn,
        provider=provider,
        source_channel="structured_api",
        source_ref=source_ref,
        title=title,
        publisher="Wind" if provider == "wind" else "Yahoo Finance",
        as_of_date=as_of_date,
        content_hash=_sha(payload),
        raw_snapshot_path=DEFAULT_SNAPSHOT.relative_to(ROOT).as_posix(),
        metadata={
            "database_boundary": "financial.db only",
            "research_run_ref": "lithium_battery_b_20260728",
        },
    )


def _record(conn: Any, counts: Counter[str], **payload: Any) -> None:
    _, status = upsert_observation(
        conn,
        return_status=True,
        revision_reason="lithium_battery_b_20260728_provider_refresh",
        **payload,
    )
    counts[status] += 1


def _annual_period(year: int) -> tuple[str, str]:
    return f"{year}-01-01", f"{year}-12-31"


def _apply_wind(
    conn: Any,
    snapshot: Mapping[str, Any],
    securities: Mapping[str, int],
    counts: Counter[str],
) -> None:
    if snapshot.get("status") != "ok":
        raise ValueError("Wind snapshot is not usable")
    trade_date = str(snapshot["trade_date"])
    source_id = _source(
        conn,
        provider="wind",
        source_ref=f"wind:battery_companies:{trade_date}",
        title="锂电池九家公司Wind小范围财务与估值快照",
        as_of_date=trade_date,
        payload=snapshot,
    )
    for ticker, row in snapshot["current"].items():
        security_id = securities[ticker.upper()]
        for field, (metric, unit, fact_type, raw_feature) in CURRENT_SPECS.items():
            value = _finite(row.get(field))
            if value is None:
                continue
            _record(
                conn,
                counts,
                security_id=security_id,
                metric_name=metric,
                value_num=value,
                unit=unit,
                currency="CNY",
                as_of_date=trade_date,
                frequency="snapshot",
                fact_type=fact_type,
                provider="wind",
                raw_feature_name=raw_feature,
                source_snapshot_id=source_id,
                quality_status="usable",
            )
    for year_text, batch in snapshot["annual"].items():
        year = int(year_text)
        period_start, period_end = _annual_period(year)
        for ticker, row in batch["rows"].items():
            security_id = securities[ticker.upper()]
            for field, (metric, unit, divisor) in ANNUAL_SPECS.items():
                value = _finite(row.get(field))
                if value is None:
                    continue
                _record(
                    conn,
                    counts,
                    security_id=security_id,
                    metric_name=metric,
                    value_num=value / divisor,
                    unit=unit,
                    currency="CNY",
                    period_start=period_start,
                    period_end=period_end,
                    fiscal_year=year,
                    fiscal_period="FY",
                    frequency="annual",
                    fact_type="actual",
                    as_of_date=period_end,
                    provider="wind",
                    raw_feature_name=f"Wind WSS.{field}",
                    source_snapshot_id=source_id,
                    quality_status="usable",
                )
    forecast_years = (2026, 2027, 2028)
    for ticker, row in snapshot["consensus_fy1_fy3"]["rows"].items():
        security_id = securities[ticker.upper()]
        for index, fiscal_year in enumerate(forecast_years, 1):
            for prefix, (metric, unit, divisor) in CONSENSUS_SPECS.items():
                raw_feature = f"{prefix}{index}"
                value = _finite(row.get(raw_feature))
                if value is None:
                    continue
                _record(
                    conn,
                    counts,
                    security_id=security_id,
                    metric_name=metric,
                    value_num=value / divisor,
                    unit=unit,
                    currency="CNY",
                    period_start=f"{fiscal_year}-01-01",
                    period_end=f"{fiscal_year}-12-31",
                    fiscal_year=fiscal_year,
                    fiscal_period="FY",
                    frequency="annual",
                    fact_type="consensus",
                    as_of_date=trade_date,
                    provider="wind",
                    raw_feature_name=f"Wind WSS.{raw_feature}",
                    source_snapshot_id=source_id,
                    scenario_name="market_consensus",
                    quality_status="usable",
                )


def _parse_yf_date(raw: str) -> str | None:
    text = str(raw).strip()[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _apply_yfinance(
    conn: Any,
    snapshots: Mapping[str, Any],
    securities: Mapping[str, int],
    counts: Counter[str],
    trade_date: str,
) -> None:
    for ticker, snapshot in snapshots.items():
        if snapshot.get("status") != "ok":
            continue
        security_id = securities[ticker.upper()]
        source_id = _source(
            conn,
            provider="yfinance",
            source_ref=f"yfinance:{ticker}:{trade_date}",
            title=f"{ticker}市场与财务快照",
            as_of_date=trade_date,
            payload=snapshot,
        )
        info = snapshot.get("info") or {}
        statement_currency = str(info.get("financialCurrency") or "CNY").upper()
        statement_unit = {
            "CNY": "亿元人民币",
            "HKD": "亿港元",
            "USD": "亿美元",
        }.get(statement_currency, f"亿{statement_currency}")
        for raw_feature, (metric, unit, fact_type) in YF_INFO_SPECS.items():
            value = _finite(info.get(raw_feature))
            if value is None:
                continue
            if raw_feature in {
                "returnOnEquity",
                "returnOnAssets",
                "grossMargins",
                "profitMargins",
            }:
                value *= 100.0
            if raw_feature == "marketCap":
                value /= 1e8
            _record(
                conn,
                counts,
                security_id=security_id,
                metric_name=metric,
                value_num=value,
                unit=unit,
                currency="HKD",
                as_of_date=trade_date,
                frequency="snapshot",
                fact_type=fact_type,
                provider="yfinance",
                raw_feature_name=f"yfinance.get_info.{raw_feature}",
                source_snapshot_id=source_id,
                quality_status="usable",
            )
        for table_name, metric_specs in YF_STATEMENT_SPECS.items():
            rows = (snapshot.get(table_name) or {}).get("rows") or {}
            for statement_row, metric in metric_specs.items():
                values = rows.get(statement_row) or {}
                for raw_date, raw_value in values.items():
                    period_end = _parse_yf_date(raw_date)
                    value = _finite(raw_value)
                    if period_end is None or value is None:
                        continue
                    if metric == "capex":
                        value = abs(value)
                    _record(
                        conn,
                        counts,
                        security_id=security_id,
                        metric_name=metric,
                        value_num=value / 1e8,
                        unit=statement_unit,
                        currency=statement_currency,
                        period_start=f"{period_end[:4]}-01-01",
                        period_end=period_end,
                        fiscal_year=int(period_end[:4]),
                        fiscal_period="FY",
                        frequency="annual",
                        fact_type="actual",
                        as_of_date=trade_date,
                        provider="yfinance",
                        raw_feature_name=f"yfinance.{table_name}.{statement_row}",
                        source_snapshot_id=source_id,
                        quality_status="usable",
                    )


def apply_snapshot(
    snapshot_path: Path = DEFAULT_SNAPSHOT,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    initialize_database(db_path)
    conn = connect(db_path)
    counts: Counter[str] = Counter()
    try:
        securities = _securities(conn)
        expected = set(payload["scope_audit"]["wind_tickers"]) | set(
            payload["yfinance"]
        )
        missing = sorted(expected - set(securities))
        if missing:
            raise ValueError(f"financial_security缺少证券身份: {missing}")
        with transaction(conn):
            _apply_wind(conn, payload["wind"], securities, counts)
            _apply_yfinance(
                conn,
                payload["yfinance"],
                securities,
                counts,
                str(payload["wind"]["trade_date"]),
            )
        verify_database(db_path)
    finally:
        conn.close()
    return {
        "snapshot": snapshot_path.relative_to(ROOT).as_posix(),
        "database": db_path.relative_to(ROOT).as_posix(),
        "counts": dict(counts),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()
    result = apply_snapshot(args.snapshot.resolve(), args.db.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
