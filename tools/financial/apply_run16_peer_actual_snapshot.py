from __future__ import annotations

"""Import a bounded Run16 Wind actual/market snapshot into financial.db only."""

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
    ROOT
    / "cache"
    / "research_runs"
    / "opportunity_lens_ai_app_full_chain_portfolio_20260801"
    / "application_peer_actual_snapshot.json"
)

CURRENT_FIELDS = {
    "CLOSE": ("price", "元/股", "CNY", "market", 1.0, True),
    "PE_TTM": ("pe_ttm", "倍", None, "market", 1.0, False),
    "PE_EST_FTM": ("pe_forward", "倍", None, "consensus", 1.0, False),
    "PB_LF": ("pb", "倍", None, "market", 1.0, False),
    "PS_TTM": ("ps_ttm", "倍", None, "market", 1.0, False),
    "MKT_CAP_ARD": ("market_cap", "亿元人民币", "CNY", "market", 1e8, True),
    "FREE_FLOAT_MARKET_CAP_CNY_100M": ("free_float_market_cap", "亿元人民币", "CNY", "market", 1.0, True),
    "ROE_TTM": ("roe", "%", None, "actual", 1.0, True),
    "ROA2_TTM": ("roa", "%", None, "actual", 1.0, True),
    "EPS_TTM": ("eps_ttm", "元/股", "CNY", "actual", 1.0, True),
    "BPS_NEW": ("bps_mrq", "元/股", "CNY", "actual", 1.0, True),
    "EV2_TO_EBITDA": ("ev_ebitda", "倍", None, "market", 1.0, False),
    "PEG": ("peg", "倍", None, "market", 1.0, False),
}

REPORTED_FIELDS = {
    "OPER_REV": ("revenue", "亿元人民币", "CNY", 1e8),
    "NP_BELONGTO_PARCOMSH": ("net_income", "亿元人民币", "CNY", 1e8),
    "NET_CASH_FLOWS_OPER_ACT": ("operating_cash_flow", "亿元人民币", "CNY", 1e8),
    "CASH_PAY_ACQ_CONST_FIOLTA": ("capex", "亿元人民币", "CNY", 1e8),
    "TOT_ASSETS": ("total_assets", "亿元人民币", "CNY", 1e8),
    "TOT_EQUITY": ("total_equity", "亿元人民币", "CNY", 1e8),
    "TOT_LIAB": ("total_liabilities", "亿元人民币", "CNY", 1e8),
    "ROE": ("roe", "%", None, 1.0),
    "ROA2": ("roa", "%", None, 1.0),
    "GROSSPROFITMARGIN": ("gross_margin", "%", None, 1.0),
    "NETPROFITMARGIN": ("net_margin", "%", None, 1.0),
}


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _hash(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _security_map(
    conn: sqlite3.Connection, universe: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    tickers = [str(row["ticker"]).upper() for row in universe]
    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT s.id,s.canonical_name,s.ticker,l.research_company_id
              FROM financial_security s
              JOIN financial_security_company_link l ON l.security_id=s.id
             WHERE upper(s.ticker) IN (%s)
            """ % ",".join("?" for _ in tickers),
            tuple(tickers),
        )
    ]
    result = {str(row["ticker"]).upper(): row for row in rows}
    missing = sorted(set(tickers) - set(result))
    if missing:
        raise ValueError(f"Run16候选缺少规范financial_security映射: {missing}")
    return result


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
    fiscal_period: str | None,
    frequency: str,
    fact_type: str,
    as_of: str,
    raw_feature: str,
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
        fiscal_period=fiscal_period,
        frequency=frequency,
        fact_type=fact_type,
        as_of_date=as_of,
        provider="wind",
        raw_feature_name=raw_feature,
        source_snapshot_id=source_id,
        quality_status="usable",
        scenario_name="reported" if fact_type != "consensus" else "consensus",
    )
    counts[status] += 1


def apply_snapshot(snapshot_path: Path, db_path: Path) -> dict[str, Any]:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if snapshot.get("snapshot_version") != "run16.ai_actual_market_history.v1":
        raise ValueError("不是受支持的Run16实际值快照")
    if snapshot.get("stage") != "actual_before_consensus":
        raise ValueError("Run16候选快照必须在一致预期读取前形成")
    universe = list(snapshot.get("universe") or [])
    wind = dict(snapshot.get("wind") or {})
    trade_date = str(snapshot.get("trade_date") or "")
    if not universe or not trade_date:
        raise ValueError("Run16候选快照缺少证券或交易日")

    conn = connect(db_path)
    counts = {"inserted": 0, "revised": 0, "unchanged": 0}
    try:
        securities = _security_map(conn, universe)
        with transaction(conn):
            source_ids: dict[str, int] = {}
            for item in universe:
                ticker = str(item["ticker"]).upper()
                ticker_slice = {
                    "current": (wind.get("current") or {}).get(ticker),
                    "reported": {
                        period: rows.get(ticker)
                        for period, rows in (wind.get("reported") or {}).items()
                    },
                    "prices": (wind.get("price_history") or {}).get(ticker),
                }
                source_ids[ticker] = record_source_snapshot(
                    conn,
                    provider="wind",
                    source_channel="structured_api",
                    source_ref=f"wind:run16_application_peer:{ticker}:{trade_date}",
                    title=f"{item['name']} Wind窄字段财务与市场快照",
                    publisher="Wind内网代理",
                    as_of_date=trade_date,
                    content_hash=_hash(ticker_slice),
                    raw_snapshot_path=str(snapshot_path.relative_to(ROOT)).replace("\\", "/"),
                    metadata={
                        "database_boundary": "financial.db only",
                        "request_scope": snapshot.get("request_audit"),
                    },
                )

            for ticker, raw in (wind.get("current") or {}).items():
                security = securities[str(ticker).upper()]
                for raw_name, (metric, unit, currency, fact_type, divisor, allow_nonpositive) in CURRENT_FIELDS.items():
                    value = _finite(raw.get(raw_name))
                    if value is None or (not allow_nonpositive and value <= 0):
                        continue
                    _write(
                        conn,
                        counts,
                        security_id=int(security["id"]),
                        source_id=source_ids[str(ticker).upper()],
                        metric=metric,
                        value=value / divisor,
                        unit=unit,
                        currency=currency,
                        period_end=trade_date,
                        fiscal_year=None,
                        fiscal_period=None,
                        frequency="snapshot",
                        fact_type=fact_type,
                        as_of=trade_date,
                        raw_feature=f"Wind WSS.{raw_name.lower()}",
                    )

            for report_date, rows in (wind.get("reported") or {}).items():
                period_end = f"{report_date[:4]}-{report_date[4:6]}-{report_date[6:8]}"
                annual = report_date.endswith("1231")
                fiscal_year = int(report_date[:4])
                for ticker, raw in rows.items():
                    security = securities[str(ticker).upper()]
                    for raw_name, (metric, unit, currency, divisor) in REPORTED_FIELDS.items():
                        value = _finite(raw.get(raw_name))
                        _write(
                            conn,
                            counts,
                            security_id=int(security["id"]),
                            source_id=source_ids[str(ticker).upper()],
                            metric=metric,
                            value=None if value is None else value / divisor,
                            unit=unit,
                            currency=currency,
                            period_end=period_end,
                            fiscal_year=fiscal_year,
                            fiscal_period="FY" if annual else "Q1",
                            frequency="annual" if annual else "quarterly",
                            fact_type="actual",
                            as_of=trade_date,
                            raw_feature=f"Wind WSS.{raw_name.lower()}",
                        )

            for ticker, prices in (wind.get("price_history") or {}).items():
                security = securities[str(ticker).upper()]
                for row in prices:
                    _write(
                        conn,
                        counts,
                        security_id=int(security["id"]),
                        source_id=source_ids[str(ticker).upper()],
                        metric="price",
                        value=_finite(row.get("close_forward_adjusted")),
                        unit="元/股",
                        currency="CNY",
                        period_end=str(row["date"]),
                        fiscal_year=None,
                        fiscal_period=None,
                        frequency="daily",
                        fact_type="market",
                        as_of=str(row["date"]),
                        raw_feature="Wind WSD.close.PriceAdj=F",
                    )

        verify_database(db_path)
        foreign_key_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_violations:
            raise ValueError(f"financial.db外键检查失败: {foreign_key_violations[:3]}")
        return {
            "snapshot": str(snapshot_path),
            "securities": len(universe),
            "observations": counts,
            "foreign_key_check": "pass",
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()
    print(
        json.dumps(
            apply_snapshot(args.snapshot.resolve(), args.db.resolve()),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
