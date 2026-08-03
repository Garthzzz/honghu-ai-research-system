from __future__ import annotations

"""Apply the audited lithium snapshot to ``financial.db``.

The script never writes ``research.db``.  Wind and Tushare observations keep
their own provider, raw field, date and source snapshot.  The viewer therefore
prefers Wind while retaining same-period Tushare observations for reconciliation.
"""

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

from tools.financial.constants import DB_PATH
from tools.financial.db import connect, initialize_database, transaction, verify_database
from tools.financial.repository import record_source_snapshot, upsert_observation


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOT = ROOT / "cache" / "lithium_research" / "lithium_financial_snapshot.json"

CURRENT_SPECS = {
    "price": ("close", "元/股", "market", "Wind WSS.close"),
    "pe_ttm": ("pe_ttm", "倍", "market", "Wind WSS.pe_ttm"),
    "pe_forward": ("pe_forward", "倍", "consensus", "Wind WSS.pe_est_ftm"),
    "pb": ("pb", "倍", "market", "Wind WSS.pb_lf"),
    "ps_ttm": ("ps_ttm", "倍", "market", "Wind WSS.ps_ttm"),
    "ev_ebitda": ("ev_ebitda", "倍", "market", "Wind WSS.ev2_to_ebitda"),
    "peg": ("peg", "倍", "market", "Wind WSS.peg"),
    "roe": ("roe", "%", "actual", "Wind WSS.roe_ttm"),
    "roa": ("roa", "%", "actual", "Wind WSS.roa2_ttm"),
    "eps_ttm": ("eps_ttm", "元/股", "actual", "Wind WSS.eps_ttm"),
    "bps_mrq": ("bps_mrq", "元/股", "actual", "Wind WSS.bps_new"),
    "market_cap_cny": ("market_cap", "亿元人民币", "market", "Wind WSS.mkt_cap_ard"),
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
WIND_CONSENSUS_SPECS = {
    "west_sales": ("revenue", "亿元人民币", 1e8),
    "west_netprofit": ("net_income", "亿元人民币", 1e8),
    "west_eps": ("eps", "元/股", 1.0),
    "west_avgroe": ("roe", "%", 1.0),
}
TUSHARE_CURRENT_SPECS = {
    "close": ("close", "元/股"),
    "pe_ttm": ("pe_ttm", "倍"),
    "pb": ("pb", "倍"),
    "ps_ttm": ("ps_ttm", "倍"),
    "total_mv": ("market_cap", "亿元人民币"),
}
TUSHARE_TABLE_SPECS = {
    "income_2021_2026": {
        "revenue": ("revenue", "亿元人民币", 1e8),
        "n_income_attr_p": ("net_income", "亿元人民币", 1e8),
        "rd_exp": ("rd_expense", "亿元人民币", 1e8),
    },
    "balancesheet_2021_2026": {
        "total_assets": ("total_assets", "亿元人民币", 1e8),
        "total_liab": ("total_liabilities", "亿元人民币", 1e8),
        "total_hldr_eqy_exc_min_int": ("book_value", "亿元人民币", 1e8),
        "accounts_receiv": ("accounts_receivable", "亿元人民币", 1e8),
        "inventories": ("inventory", "亿元人民币", 1e8),
        "fix_assets": ("fixed_assets", "亿元人民币", 1e8),
        "cip": ("construction_in_progress", "亿元人民币", 1e8),
        "contract_liab": ("contract_liabilities", "亿元人民币", 1e8),
    },
    "cashflow_2021_2026": {
        "n_cashflow_act": ("operating_cash_flow", "亿元人民币", 1e8),
        "c_pay_acq_const_fiolta": ("capex", "亿元人民币", 1e8),
    },
    "fina_indicator_2021_2026": {
        "eps": ("eps", "元/股", 1.0),
        "bps": ("bps_mrq", "元/股", 1.0),
        "grossprofit_margin": ("gross_margin", "%", 1.0),
        "netprofit_margin": ("net_margin", "%", 1.0),
        "roe": ("roe", "%", 1.0),
        "roa": ("roa", "%", 1.0),
        "rd_exp_to_operting_revenue": ("rd_expense_ratio", "%", 1.0),
    },
}
REPORT_RC_SPECS = {
    "op_rt": ("revenue", "亿元人民币", 10000.0),
    "op_pr": ("operating_profit", "亿元人民币", 10000.0),
    "tp": ("total_profit", "亿元人民币", 10000.0),
    "np": ("net_income", "亿元人民币", 10000.0),
    "eps": ("eps", "元/股", 1.0),
    "pe": ("pe_forward", "倍", 1.0),
    "roe": ("roe", "%", 1.0),
    "ev_ebitda": ("ev_ebitda", "倍", 1.0),
    "max_price": ("target_price_high", "元/股", 1.0),
    "min_price": ("target_price_low", "元/股", 1.0),
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


def _iso(raw: Any) -> str:
    text = str(raw or "").strip()
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return date.fromisoformat(text[:10]).isoformat()


def _period(end_date: str) -> tuple[int, str, str]:
    year = int(end_date[:4])
    month_day = end_date[5:]
    fiscal_period = {
        "03-31": "Q1",
        "06-30": "Q2",
        "09-30": "Q3",
        "12-31": "FY",
    }.get(month_day, "snapshot")
    frequency = "annual" if fiscal_period == "FY" else "quarterly"
    return year, fiscal_period, frequency


def _security_map(conn: Any) -> dict[str, int]:
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
    raw_snapshot_path: str,
) -> int:
    return record_source_snapshot(
        conn,
        provider=provider,
        source_channel="structured_api",
        source_ref=source_ref,
        title=title,
        publisher="Wind" if provider == "wind" else "Tushare Pro",
        as_of_date=as_of_date,
        content_hash=_sha(payload),
        raw_snapshot_path=raw_snapshot_path,
        metadata={
            "database_boundary": "financial.db only",
            "research_run_ref": "lithium_b_20260727",
        },
    )


def _record(conn: Any, counts: Counter[str], **payload: Any) -> None:
    _, status = upsert_observation(conn, return_status=True, **payload)
    counts[status] += 1


def _wind_rows(snapshot: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for batch in snapshot.get("rows") or []:
        result.update(batch.get("rows") or {})
    return result


def _unique_report_rows(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    result: dict[tuple[str, ...], Mapping[str, Any]] = {}
    for row in rows:
        identity = (
            str(row.get("report_date") or ""),
            str(row.get("org_name") or ""),
            str(row.get("report_title") or ""),
            str(row.get("quarter") or ""),
        )
        result.setdefault(identity, row)
    return list(result.values())


def _current_tushare_row(rows: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    items = list(rows)
    if not items:
        return None
    return max(items, key=lambda row: str(row.get("trade_date") or ""))


def _preferred_table_rows(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    by_period: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        end_date = str(row.get("end_date") or "")
        if len(end_date) != 8:
            continue
        if str(row.get("report_type") or "1") not in {"1", ""}:
            continue
        by_period.setdefault(end_date, []).append(row)
    chosen = []
    for period_rows in by_period.values():
        chosen.append(
            max(
                period_rows,
                key=lambda row: (
                    str(row.get("update_flag") or ""),
                    str(row.get("f_ann_date") or ""),
                    str(row.get("ann_date") or ""),
                ),
            )
        )
    return sorted(chosen, key=lambda row: str(row.get("end_date") or ""))


def apply_snapshot(
    snapshot_path: Path = DEFAULT_SNAPSHOT,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if payload.get("wind", {}).get("status") != "ok":
        raise ValueError("Wind snapshot is not usable")
    if payload.get("tushare", {}).get("status") != "ok":
        raise ValueError("Tushare snapshot is not usable")
    initialize_database(db_path)
    conn = connect(db_path)
    counts: Counter[str] = Counter()
    try:
        securities = _security_map(conn)
        missing = sorted(set(payload["scope_audit"]["wind_tickers"]) - set(securities))
        if missing:
            raise ValueError(f"financial_security missing: {missing}")
        raw_ref = str(snapshot_path.resolve())
        accessed_at = str(payload["accessed_at_utc"])
        with transaction(conn):
            wind = payload["wind"]
            for ticker, row in wind["current"].items():
                security_id = securities[ticker]
                as_of = _iso(row["trade_date"])
                source_id = _source(
                    conn,
                    provider="wind",
                    source_ref=f"wind:WSS:{ticker}:current:{as_of}",
                    title=f"{ticker} Wind 当前估值与财务快照",
                    as_of_date=as_of,
                    payload=row,
                    raw_snapshot_path=raw_ref,
                )
                for raw_name, (metric, unit, fact_type, feature) in CURRENT_SPECS.items():
                    value = _finite(row.get(raw_name))
                    if value is None:
                        continue
                    _record(
                        conn,
                        counts,
                        security_id=security_id,
                        metric_name=metric,
                        value_num=value,
                        unit=unit,
                        currency="CNY" if unit in {"元/股", "亿元人民币"} else None,
                        period_end=as_of,
                        frequency="snapshot",
                        fact_type=fact_type,
                        as_of_date=as_of,
                        provider="wind",
                        raw_feature_name=feature,
                        source_snapshot_id=source_id,
                        scenario_name="reported",
                    )

            for year, batches in wind["annual"].items():
                rows: dict[str, dict[str, Any]] = {}
                for batch in batches:
                    rows.update(batch["rows"])
                end_date = f"{year}-12-31"
                for ticker, row in rows.items():
                    security_id = securities[ticker]
                    source_id = _source(
                        conn,
                        provider="wind",
                        source_ref=f"wind:WSS:{ticker}:annual:{year}",
                        title=f"{ticker} Wind {year} 年报财务",
                        as_of_date=end_date,
                        payload=row,
                        raw_snapshot_path=raw_ref,
                    )
                    for raw_name, (metric, unit, divisor) in ANNUAL_SPECS.items():
                        value = _finite(row.get(raw_name))
                        if value is None:
                            continue
                        _record(
                            conn,
                            counts,
                            security_id=security_id,
                            metric_name=metric,
                            value_num=value / divisor,
                            unit=unit,
                            currency="CNY" if unit == "亿元人民币" else None,
                            period_end=end_date,
                            fiscal_year=int(year),
                            fiscal_period="FY",
                            frequency="annual",
                            fact_type="actual",
                            as_of_date=end_date,
                            provider="wind",
                            raw_feature_name=f"Wind WSS.{raw_name}",
                            source_snapshot_id=source_id,
                            scenario_name="reported",
                        )

            q1_rows: dict[str, dict[str, Any]] = {}
            for batch in wind["q1_2026"]:
                q1_rows.update(batch["rows"])
            for ticker, row in q1_rows.items():
                security_id = securities[ticker]
                end_date = "2026-03-31"
                source_id = _source(
                    conn,
                    provider="wind",
                    source_ref=f"wind:WSS:{ticker}:quarter:2026Q1",
                    title=f"{ticker} Wind 2026 年第一季度财务",
                    as_of_date=end_date,
                    payload=row,
                    raw_snapshot_path=raw_ref,
                )
                for raw_name, (metric, unit, divisor) in ANNUAL_SPECS.items():
                    value = _finite(row.get(raw_name))
                    if value is None:
                        continue
                    _record(
                        conn,
                        counts,
                        security_id=security_id,
                        metric_name=metric,
                        value_num=value / divisor,
                        unit=unit,
                        currency="CNY" if unit == "亿元人民币" else None,
                        period_end=end_date,
                        fiscal_year=2026,
                        fiscal_period="Q1",
                        frequency="quarterly",
                        fact_type="actual",
                        as_of_date=end_date,
                        provider="wind",
                        raw_feature_name=f"Wind WSS.{raw_name}",
                        source_snapshot_id=source_id,
                        scenario_name="reported_ytd",
                    )

            consensus_rows: dict[str, dict[str, Any]] = {}
            for batch in wind["consensus_fy1_fy3"]:
                consensus_rows.update(batch["rows"])
            as_of = _iso(wind["trade_date"])
            for ticker, row in consensus_rows.items():
                security_id = securities[ticker]
                source_id = _source(
                    conn,
                    provider="wind",
                    source_ref=f"wind:WSS:{ticker}:consensus:{as_of}",
                    title=f"{ticker} Wind FY1—FY3 一致预期",
                    as_of_date=as_of,
                    payload=row,
                    raw_snapshot_path=raw_ref,
                )
                for horizon, year in (("fy1", 2026), ("fy2", 2027), ("fy3", 2028)):
                    for prefix, (metric, unit, divisor) in WIND_CONSENSUS_SPECS.items():
                        raw_name = f"{prefix}_{horizon}"
                        value = _finite(row.get(raw_name))
                        if value is None:
                            continue
                        _record(
                            conn,
                            counts,
                            security_id=security_id,
                            metric_name=metric,
                            value_num=value / divisor,
                            unit=unit,
                            currency="CNY" if unit in {"元/股", "亿元人民币"} else None,
                            period_end=f"{year}-12-31",
                            fiscal_year=year,
                            fiscal_period="FY",
                            frequency="annual",
                            fact_type="consensus",
                            as_of_date=as_of,
                            provider="wind",
                            raw_feature_name=f"Wind WSS.{raw_name}",
                            source_snapshot_id=source_id,
                            scenario_name="market_consensus",
                        )

            for ticker, company in payload["tushare"]["securities"].items():
                security_id = securities[ticker]
                current = _current_tushare_row(company["daily_basic"])
                if current:
                    as_of = _iso(current["trade_date"])
                    source_id = _source(
                        conn,
                        provider="tushare",
                        source_ref=f"tushare:daily_basic:{ticker}:{as_of}",
                        title=f"{ticker} Tushare 日行情与估值对账",
                        as_of_date=as_of,
                        payload=current,
                        raw_snapshot_path=raw_ref,
                    )
                    for raw_name, (metric, unit) in TUSHARE_CURRENT_SPECS.items():
                        value = _finite(current.get(raw_name))
                        if value is None:
                            continue
                        if raw_name == "total_mv":
                            value /= 10000.0
                        _record(
                            conn,
                            counts,
                            security_id=security_id,
                            metric_name=metric,
                            value_num=value,
                            unit=unit,
                            currency="CNY" if unit in {"元/股", "亿元人民币"} else None,
                            period_end=as_of,
                            frequency="snapshot",
                            fact_type="market",
                            as_of_date=as_of,
                            provider="tushare",
                            raw_feature_name=f"daily_basic.{raw_name}",
                            source_snapshot_id=source_id,
                            scenario_name="reported",
                        )

                for table_name, specs in TUSHARE_TABLE_SPECS.items():
                    for row in _preferred_table_rows(company[table_name]):
                        end_date = _iso(row["end_date"])
                        year, fiscal_period, frequency = _period(end_date)
                        announcement = _iso(row["ann_date"])
                        source_id = _source(
                            conn,
                            provider="tushare",
                            source_ref=(
                                f"tushare:{table_name}:{ticker}:{end_date}:"
                                f"update={row.get('update_flag')}"
                            ),
                            title=f"{ticker} Tushare {end_date} {table_name}",
                            as_of_date=announcement,
                            payload=row,
                            raw_snapshot_path=raw_ref,
                        )
                        for raw_name, (metric, unit, divisor) in specs.items():
                            value = _finite(row.get(raw_name))
                            if value is None:
                                continue
                            _record(
                                conn,
                                counts,
                                security_id=security_id,
                                metric_name=metric,
                                value_num=value / divisor,
                                unit=unit,
                                currency="CNY" if unit in {"元/股", "亿元人民币"} else None,
                                period_end=end_date,
                                fiscal_year=year,
                                fiscal_period=fiscal_period,
                                frequency=frequency,
                                fact_type="actual",
                                as_of_date=announcement,
                                announcement_date=announcement,
                                provider="tushare",
                                raw_feature_name=f"{table_name}.{raw_name}",
                                source_snapshot_id=source_id,
                                scenario_name="reported_ytd" if frequency == "quarterly" else "reported",
                            )

                for row in _unique_report_rows(
                    company["institution_forecasts_recent_six_months"]
                ):
                    quarter = str(row.get("quarter") or "")
                    if len(quarter) != 6 or not quarter[:4].isdigit():
                        continue
                    year = int(quarter[:4])
                    if year not in {2026, 2027, 2028}:
                        continue
                    report_date = _iso(row["report_date"])
                    org = str(row.get("org_name") or "未标注机构").strip()
                    title = str(row.get("report_title") or f"{org}预测").strip()
                    source_id = _source(
                        conn,
                        provider="tushare",
                        source_ref=(
                            f"tushare:report_rc:{ticker}:{report_date}:"
                            f"{org}:{_sha(title)[:18]}"
                        ),
                        title=f"{ticker} {org}：{title}",
                        as_of_date=report_date,
                        payload=row,
                        raw_snapshot_path=raw_ref,
                    )
                    scenario = f"机构预测｜{org}｜{report_date}"
                    for raw_name, (metric, unit, divisor) in REPORT_RC_SPECS.items():
                        value = _finite(row.get(raw_name))
                        if value is None:
                            continue
                        _record(
                            conn,
                            counts,
                            security_id=security_id,
                            metric_name=metric,
                            value_num=value / divisor,
                            unit=unit,
                            currency="CNY" if unit in {"元/股", "亿元人民币"} else None,
                            period_end=f"{year}-12-31",
                            fiscal_year=year,
                            fiscal_period="FY",
                            frequency="annual",
                            fact_type="consensus",
                            as_of_date=report_date,
                            announcement_date=report_date,
                            provider="tushare",
                            raw_feature_name=f"report_rc.{raw_name}",
                            source_snapshot_id=source_id,
                            scenario_name=scenario,
                        )
        verification = verify_database(db_path)
    finally:
        conn.close()
    return {
        "snapshot": str(snapshot_path.resolve()),
        "snapshot_sha256": payload["content_sha256"],
        "database": str(db_path.resolve()),
        "accessed_at": accessed_at,
        "inserted": counts["inserted"],
        "revised": counts["revised"],
        "unchanged": counts["unchanged"],
        "verification": verification,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args(argv)
    result = apply_snapshot(args.snapshot.resolve(), args.db.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
