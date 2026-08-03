from __future__ import annotations

"""Apply the frozen copper-peer provider snapshot to financial.db only."""

import argparse
import hashlib
import json
import math
import sqlite3
from pathlib import Path
from typing import Any

from tools.financial.constants import DB_PATH
from tools.financial.db import connect, transaction, verify_database
from tools.financial.repository import record_source_snapshot, upsert_observation


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOT = (
    ROOT / "cache" / "copper_research" / "copper_peer_financial_snapshot.json"
)
TICKER_IDENTITIES = {
    "1258.HK": ("中国有色矿业", "港股"),
    "601168.SH": ("西部矿业", "A股"),
    "600362.SH": ("江西铜业", "A股"),
    "000630.SZ": ("铜陵有色", "A股"),
    "000878.SZ": ("云南铜业", "A股"),
    "002203.SZ": ("海亮股份", "A股"),
    "601137.SH": ("博威合金", "A股"),
    "601609.SH": ("金田股份", "A股"),
}
A_RAW = {
    "oper_rev": ("revenue", "亿元人民币", "CNY", 1e8),
    "np_belongto_parcomsh": ("net_income", "亿元人民币", "CNY", 1e8),
    "net_cash_flows_oper_act": (
        "operating_cash_flow",
        "亿元人民币",
        "CNY",
        1e8,
    ),
    "cash_pay_acq_const_fiolta": ("capex", "亿元人民币", "CNY", 1e8),
    "tot_assets": ("total_assets", "亿元人民币", "CNY", 1e8),
    "tot_equity": ("total_equity", "亿元人民币", "CNY", 1e8),
    "tot_liab": ("total_liabilities", "亿元人民币", "CNY", 1e8),
    "roe": ("roe", "%", None, 1.0),
    "roa2": ("roa", "%", None, 1.0),
    "grossprofitmargin": ("gross_margin", "%", None, 1.0),
    "netprofitmargin": ("net_margin", "%", None, 1.0),
}
CURRENT_SPECS = {
    "price": ("price", "元/股", "market"),
    "pe_ttm": ("pe_ttm", "倍", "market"),
    "pe_forward": ("pe_forward", "倍", "consensus"),
    "pb": ("pb", "倍", "market"),
    "ps_ttm": ("ps_ttm", "倍", "market"),
    "ev_ebitda": ("ev_ebitda", "倍", "market"),
    "roe": ("roe", "%", "actual"),
    "roa": ("roa", "%", "actual"),
    "eps_ttm": ("eps_ttm", "元/股", "actual"),
    "bps_mrq": ("bps_mrq", "元/股", "actual"),
    "market_cap_cny": ("market_cap", "亿元人民币", "market"),
    "market_cap_usd": ("market_cap_usd", "亿美元", "market"),
}
CONSENSUS_SPECS = {
    "west_sales_fy1": ("revenue", 2026, "亿元人民币", 1e8),
    "west_sales_fy2": ("revenue", 2027, "亿元人民币", 1e8),
    "west_sales_fy3": ("revenue", 2028, "亿元人民币", 1e8),
    "west_netprofit_fy1": ("net_income", 2026, "亿元人民币", 1e8),
    "west_netprofit_fy2": ("net_income", 2027, "亿元人民币", 1e8),
    "west_netprofit_fy3": ("net_income", 2028, "亿元人民币", 1e8),
    "west_eps_fy1": ("eps", 2026, "元/股", 1.0),
    "west_eps_fy2": ("eps", 2027, "元/股", 1.0),
    "west_eps_fy3": ("eps", 2028, "元/股", 1.0),
    "west_avgroe_fy1": ("roe", 2026, "%", 1.0),
    "west_avgroe_fy2": ("roe", 2027, "%", 1.0),
    "west_avgroe_fy3": ("roe", 2028, "%", 1.0),
}


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


def _security_map(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT s.id,s.canonical_name,s.ticker,s.market,s.reporting_currency,
                   l.research_company_id
              FROM financial_security s
              JOIN financial_security_company_link l ON l.security_id=s.id
             WHERE upper(s.ticker) IN (%s)
            """
            % ",".join("?" for _ in TICKER_IDENTITIES),
            tuple(TICKER_IDENTITIES),
        )
    ]
    result = {str(row["ticker"]).upper(): row for row in rows}
    missing = sorted(set(TICKER_IDENTITIES) - set(result))
    if missing:
        raise ValueError(f"以下铜同行尚无规范financial_security映射: {missing}")
    return result


def _source(
    conn: sqlite3.Connection,
    *,
    provider: str,
    ticker: str,
    title: str,
    as_of: str,
    content_hash: str,
    raw_path: str,
    metadata: dict[str, Any],
) -> int:
    return record_source_snapshot(
        conn,
        provider=provider,
        source_channel="structured_api",
        source_ref=f"{provider}:copper_peer:{ticker}:{as_of}",
        title=title,
        publisher="Wind" if provider == "wind" else "Yahoo Finance / yfinance",
        as_of_date=as_of,
        content_hash=content_hash,
        raw_snapshot_path=raw_path,
        metadata={"database_boundary": "financial.db only", **metadata},
    )


def _write(
    conn: sqlite3.Connection,
    counts: dict[str, int],
    *,
    security_id: int,
    source_id: int,
    metric: str,
    value: float | None,
    unit: str,
    currency: str | None,
    period_end: str,
    fiscal_year: int | None,
    frequency: str,
    fact_type: str,
    as_of: str,
    provider: str,
    raw_feature: str,
    formula: str | None = None,
    input_refs: list[Any] | None = None,
) -> None:
    if value is None:
        return
    _, status = upsert_observation(
        conn,
        return_status=True,
        security_id=security_id,
        metric_name=metric,
        value_num=value,
        unit=unit,
        currency=currency,
        period_end=period_end,
        fiscal_year=fiscal_year,
        fiscal_period="FY" if fiscal_year else None,
        frequency=frequency,
        fact_type=fact_type,
        as_of_date=as_of,
        provider=provider,
        raw_feature_name=raw_feature,
        source_snapshot_id=source_id,
        formula=formula,
        input_refs=input_refs or [],
        quality_status="usable",
        scenario_name="reported" if fact_type != "consensus" else "consensus",
    )
    counts[status] += 1


def _apply_wind(
    conn: sqlite3.Connection,
    snapshot: dict[str, Any],
    securities: dict[str, dict[str, Any]],
    counts: dict[str, int],
    *,
    raw_path: str,
) -> None:
    wind = snapshot.get("wind") or {}
    if wind.get("status") != "ok":
        raise ValueError(f"Wind铜同行快照不可用: {wind.get('error_message')}")
    trade_date = str(wind["trade_date"])
    for ticker, current in (wind.get("current") or {}).items():
        ticker = ticker.upper()
        security = securities[ticker]
        source_id = _source(
            conn,
            provider="wind",
            ticker=ticker,
            title=f"{security['canonical_name']} Wind当前估值窄字段",
            as_of=trade_date,
            content_hash=_hash(current),
            raw_path=raw_path,
            metadata={"scope": "current market and TTM financial snapshot"},
        )
        currency = str(current.get("per_share_currency") or "CNY")
        for key, (metric, unit, fact_type) in CURRENT_SPECS.items():
            value = _finite(current.get(key))
            if value is None or (metric in {"pe_ttm", "pe_forward"} and value <= 0):
                continue
            _write(
                conn,
                counts,
                security_id=int(security["id"]),
                source_id=source_id,
                metric=metric,
                value=value,
                unit=unit,
                currency=(
                    currency
                    if metric in {"price", "eps_ttm", "bps_mrq"}
                    else "CNY"
                    if metric == "market_cap"
                    else "USD"
                    if metric == "market_cap_usd"
                    else None
                ),
                period_end=trade_date,
                fiscal_year=None,
                frequency="snapshot",
                fact_type=fact_type,
                as_of=trade_date,
                provider="wind",
                raw_feature=f"Wind WSS.{key}",
            )

    for year_text, annual_payload in (wind.get("annual") or {}).items():
        year = int(year_text)
        for ticker, raw_row in (annual_payload.get("rows") or {}).items():
            ticker = ticker.upper()
            security = securities[ticker]
            source_id = _source(
                conn,
                provider="wind",
                ticker=ticker,
                title=f"{security['canonical_name']} Wind {year}年财务窄字段",
                as_of=trade_date,
                content_hash=_hash(raw_row),
                raw_path=raw_path,
                metadata={
                    "report_period": f"{year}-12-31",
                    "options": annual_payload.get("options"),
                },
            )
            converted: dict[str, float] = {}
            for raw_field, (metric, unit, currency, divisor) in A_RAW.items():
                value = _finite(raw_row.get(raw_field))
                if value is None:
                    continue
                value /= divisor
                converted[metric] = value
                _write(
                    conn,
                    counts,
                    security_id=int(security["id"]),
                    source_id=source_id,
                    metric=metric,
                    value=value,
                    unit=unit,
                    currency=currency,
                    period_end=f"{year}-12-31",
                    fiscal_year=year,
                    frequency="annual",
                    fact_type="actual",
                    as_of=trade_date,
                    provider="wind",
                    raw_feature=f"Wind WSS.{raw_field}",
                )
            if {"operating_cash_flow", "capex"} <= set(converted):
                _write(
                    conn,
                    counts,
                    security_id=int(security["id"]),
                    source_id=source_id,
                    metric="free_cash_flow",
                    value=converted["operating_cash_flow"] - converted["capex"],
                    unit="亿元人民币",
                    currency="CNY",
                    period_end=f"{year}-12-31",
                    fiscal_year=year,
                    frequency="annual",
                    fact_type="actual",
                    as_of=trade_date,
                    provider="derived",
                    raw_feature="derived.Wind OCF-capex",
                    formula="自由现金流＝经营现金流－资本开支",
                    input_refs=[
                        f"{ticker}:{year}:operating_cash_flow",
                        f"{ticker}:{year}:capex",
                    ],
                )

    consensus = wind.get("consensus_fy1_fy3") or {}
    for ticker, raw_row in (consensus.get("rows") or {}).items():
        ticker = ticker.upper()
        security = securities[ticker]
        source_id = _source(
            conn,
            provider="wind",
            ticker=ticker,
            title=f"{security['canonical_name']} Wind FY1—FY3一致预期",
            as_of=trade_date,
            content_hash=_hash(raw_row),
            raw_path=raw_path,
            metadata={"options": consensus.get("options")},
        )
        for raw_field, (metric, year, unit, divisor) in CONSENSUS_SPECS.items():
            value = _finite(raw_row.get(raw_field))
            if value is None:
                continue
            _write(
                conn,
                counts,
                security_id=int(security["id"]),
                source_id=source_id,
                metric=metric,
                value=value / divisor,
                unit=unit,
                currency="CNY" if unit in {"亿元人民币", "元/股"} else None,
                period_end=f"{year}-12-31",
                fiscal_year=year,
                frequency="annual",
                fact_type="consensus",
                as_of=trade_date,
                provider="wind",
                raw_feature=f"Wind WSS.{raw_field}",
            )


def _table_value(table: dict[str, Any], metric: str, date_key: str) -> float | None:
    return _finite(((table.get("rows") or {}).get(metric) or {}).get(date_key))


def _first_value(
    table: dict[str, Any],
    metrics: tuple[str, ...],
    date_key: str,
) -> float | None:
    for metric in metrics:
        value = _table_value(table, metric, date_key)
        if value is not None:
            return value
    return None


def _apply_yfinance(
    conn: sqlite3.Connection,
    snapshot: dict[str, Any],
    securities: dict[str, dict[str, Any]],
    counts: dict[str, int],
    *,
    raw_path: str,
) -> None:
    payloads = snapshot.get("yfinance") or {}
    if payloads.get("status") == "unavailable":
        raise ValueError(f"yfinance铜同行快照不可用: {payloads.get('error_message')}")
    as_of = "2026-07-28"
    fx = snapshot.get("fx_cny_per_currency") or {}
    for ticker, payload in payloads.items():
        ticker = ticker.upper()
        security = securities[ticker]
        info = payload.get("info") or {}
        currency = str(info.get("currency") or "HKD")
        report_currency = str(info.get("financialCurrency") or "USD")
        source_id = _source(
            conn,
            provider="yfinance",
            ticker=ticker,
            title=f"{security['canonical_name']} yfinance市场与财务快照",
            as_of=as_of,
            content_hash=_hash(payload),
            raw_path=raw_path,
            metadata={"quote_currency": currency, "reporting_currency": report_currency},
        )
        current_map = {
            "price": (_finite(info.get("currentPrice")), f"{currency}/股", currency),
            "pe_ttm": (_finite(info.get("trailingPE")), "倍", None),
            "pe_forward": (_finite(info.get("forwardPE")), "倍", None),
            "pb": (_finite(info.get("priceToBook")), "倍", None),
            "ps_ttm": (_finite(info.get("priceToSalesTrailing12Months")), "倍", None),
            "ev_ebitda": (_finite(info.get("enterpriseToEbitda")), "倍", None),
            "eps_ttm": (_finite(info.get("trailingEps")), f"{currency}/股", currency),
            "bps_mrq": (_finite(info.get("bookValue")), f"{currency}/股", currency),
            "roe": (
                (_finite(info.get("returnOnEquity")) or 0) * 100
                if _finite(info.get("returnOnEquity")) is not None
                else None,
                "%",
                None,
            ),
            "roa": (
                (_finite(info.get("returnOnAssets")) or 0) * 100
                if _finite(info.get("returnOnAssets")) is not None
                else None,
                "%",
                None,
            ),
        }
        market_cap = _finite(info.get("marketCap"))
        if market_cap is not None:
            current_map["market_cap"] = (
                market_cap * float(fx.get(currency, 0)) / 1e8,
                "亿元人民币",
                "CNY",
            )
            current_map["market_cap_usd"] = (
                market_cap * float(fx.get(currency, 0)) / float(fx.get("USD", 1)) / 1e8,
                "亿美元",
                "USD",
            )
        for metric, (value, unit, metric_currency) in current_map.items():
            if value is None or (metric in {"pe_ttm", "pe_forward"} and value <= 0):
                continue
            fact_type = "consensus" if metric == "pe_forward" else (
                "actual" if metric in {"roe", "roa", "eps_ttm", "bps_mrq"} else "market"
            )
            _write(
                conn,
                counts,
                security_id=int(security["id"]),
                source_id=source_id,
                metric=metric,
                value=value,
                unit=unit,
                currency=metric_currency,
                period_end=as_of,
                fiscal_year=None,
                frequency="snapshot",
                fact_type=fact_type,
                as_of=as_of,
                provider="yfinance",
                raw_feature=f"yfinance.info.{metric}",
            )

        income = payload.get("income_stmt") or {}
        balance = payload.get("balance_sheet") or {}
        cash = payload.get("cash_flow") or {}
        date_keys = sorted(
            {
                str(column)
                for table in (income, balance, cash)
                for column in (table.get("columns") or [])
                if str(column)[:4].isdigit()
            }
        )
        prior_equity = prior_assets = None
        for date_key in date_keys:
            year = int(date_key[:4])
            if year < 2021 or year > 2025:
                continue
            revenue = _first_value(income, ("Total Revenue", "Operating Revenue"), date_key)
            net_income = _first_value(
                income,
                ("Net Income Common Stockholders", "Net Income"),
                date_key,
            )
            gross_profit = _first_value(income, ("Gross Profit",), date_key)
            assets = _first_value(balance, ("Total Assets",), date_key)
            equity = _first_value(
                balance,
                ("Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"),
                date_key,
            )
            liabilities = _first_value(
                balance,
                ("Total Liabilities Net Minority Interest", "Total Liabilities"),
                date_key,
            )
            ocf = _first_value(
                cash,
                ("Operating Cash Flow", "Total Cash From Operating Activities"),
                date_key,
            )
            capex_raw = _first_value(cash, ("Capital Expenditure", "Capital Expenditures"), date_key)
            capex = abs(capex_raw) if capex_raw is not None else None
            values = {
                "revenue": revenue,
                "net_income": net_income,
                "operating_cash_flow": ocf,
                "capex": capex,
                "free_cash_flow": (
                    ocf - capex if ocf is not None and capex is not None else None
                ),
                "total_assets": assets,
                "total_equity": equity,
                "total_liabilities": liabilities,
                "gross_margin": (
                    gross_profit / revenue * 100
                    if gross_profit is not None and revenue
                    else None
                ),
                "net_margin": (
                    net_income / revenue * 100 if net_income is not None and revenue else None
                ),
                "roe": (
                    net_income / ((equity + prior_equity) / 2) * 100
                    if net_income is not None and equity and prior_equity
                    else net_income / equity * 100
                    if net_income is not None and equity
                    else None
                ),
                "roa": (
                    net_income / ((assets + prior_assets) / 2) * 100
                    if net_income is not None and assets and prior_assets
                    else net_income / assets * 100
                    if net_income is not None and assets
                    else None
                ),
            }
            percent_metrics = {"gross_margin", "net_margin", "roe", "roa"}
            for metric, value in values.items():
                _write(
                    conn,
                    counts,
                    security_id=int(security["id"]),
                    source_id=source_id,
                    metric=metric,
                    value=(value if metric in percent_metrics else value / 1e8 if value is not None else None),
                    unit="%" if metric in percent_metrics else f"亿{report_currency}",
                    currency=None if metric in percent_metrics else report_currency,
                    period_end=f"{year}-12-31",
                    fiscal_year=year,
                    frequency="annual",
                    fact_type="actual",
                    as_of=as_of,
                    provider="yfinance" if metric != "free_cash_flow" else "derived",
                    raw_feature=f"yfinance.statements.{metric}",
                    formula=(
                        "自由现金流＝经营现金流－资本开支"
                        if metric == "free_cash_flow"
                        else "ROE＝归母净利润÷平均股东权益"
                        if metric == "roe"
                        else "ROA＝归母净利润÷平均总资产"
                        if metric == "roa"
                        else None
                    ),
                )
            prior_equity, prior_assets = equity, assets


def apply(snapshot_path: Path, db_path: Path) -> dict[str, Any]:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    expected_hash = snapshot.get("content_sha256")
    hash_input = dict(snapshot)
    hash_input.pop("content_sha256", None)
    if expected_hash != _hash(hash_input):
        raise ValueError("铜同行财务快照content_sha256校验失败")
    counts = {"inserted": 0, "revised": 0, "unchanged": 0}
    conn = connect(db_path)
    try:
        securities = _security_map(conn)
        with transaction(conn):
            relative_path = str(snapshot_path.resolve().relative_to(ROOT)).replace("\\", "/")
            _apply_wind(
                conn,
                snapshot,
                securities,
                counts,
                raw_path=relative_path,
            )
            _apply_yfinance(
                conn,
                snapshot,
                securities,
                counts,
                raw_path=relative_path,
            )
        verification = verify_database(db_path)
    finally:
        conn.close()
    return {
        "database": str(db_path.resolve()),
        "snapshot": str(snapshot_path.resolve()),
        "securities": len(TICKER_IDENTITIES),
        **counts,
        "verification": verification,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, nargs="?", default=DEFAULT_SNAPSHOT)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--confirm-live", action="store_true")
    args = parser.parse_args(argv)
    db_path = args.db.resolve()
    if db_path == DB_PATH.resolve() and not args.confirm_live:
        raise PermissionError("写入live financial.db必须显式--confirm-live")
    print(json.dumps(apply(args.snapshot.resolve(), db_path), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
