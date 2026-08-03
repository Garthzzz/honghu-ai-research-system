from __future__ import annotations

"""把现有公司财务兼容字段迁移到独立 ``financial.db``。

迁移只复制历史事实，不删除或改写 ``research.db``。默认在临时数据库中执行并
校验；写入 live ``data/financial.db`` 必须同时给出 ``--apply --confirm-live``。
重复执行由 observation_key 保证幂等。
"""

import argparse
import json
import shutil
import sqlite3
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

from .constants import DB_PATH
from .db import connect, initialize_database, transaction, verify_database
from .repository import record_source_snapshot, upsert_observation, upsert_security


ROOT = Path(__file__).resolve().parents[2]
RESEARCH_DB = ROOT / "data" / "research.db"

METRIC_MAP = {
    "市盈率PE_TTM": "pe_ttm",
    "市盈率PE_Forward": "pe_forward",
    "市净率PB": "pb",
    "市销率PS_TTM": "ps_ttm",
    "企业价值倍数EV_EBITDA": "ev_ebitda",
    "市盈增长比PEG": "peg",
    "总市值": "market_cap",
    "总市值_美元等值": "market_cap_usd",
    "净资产收益率ROE": "roe",
    "总资产收益率ROA": "roa",
    "投入资本回报率ROIC": "roic",
    "资产负债率": "debt_ratio",
    "总资产周转率": "asset_turnover",
    "总资产": "total_assets",
    "总负债": "total_liabilities",
    "归母净资产": "book_value",
    "每股收益EPS_TTM": "eps_ttm",
    "每股净资产BPS_MRQ": "bps_mrq",
    "营业收入_年报": "revenue",
    "净利润_年报": "net_income",
    "毛利率": "gross_margin",
    "净利率": "net_margin",
    "销售净利率_TTM": "net_margin_ttm",
    "研发费用率": "rd_expense_ratio",
    "经营活动现金流量净额": "operating_cash_flow",
    "资本性支出": "capex",
    "净利润_TTM": "net_income_ttm",
}

COMPANY_FIELDS = {
    "pe_ttm": ("pe_ttm", "倍", "market"),
    "pe_forward": ("pe_forward", "倍", "consensus"),
    "pb": ("pb", "倍", "market"),
    "ps_ttm": ("ps_ttm", "倍", "market"),
    "ev_ebitda": ("ev_ebitda", "倍", "market"),
    "peg": ("peg", "倍", "market"),
    "market_cap_cny": ("market_cap", "亿元人民币", "market"),
    "market_cap_usd": ("market_cap_usd", "亿美元", "market"),
    "roe": ("roe", "%", "actual"),
    "roa": ("roa", "%", "actual"),
    "eps_ttm": ("eps_ttm", "原币/股", "actual"),
    "bps_mrq": ("bps_mrq", "原币/股", "actual"),
}

FORECAST_FIELDS = {
    "forecast_eps_year1": ("eps", "FY1", "原币/股"),
    "forecast_eps_year2": ("eps", "FY2", "原币/股"),
    "forecast_revenue_year1": ("revenue", "FY1", None),
    "forecast_revenue_year2": ("revenue", "FY2", None),
}

MARKET_METRICS = {
    "pe_ttm", "pb", "ps_ttm", "ev_ebitda", "peg", "market_cap", "market_cap_usd",
}


def _ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _safe_json(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(str(value)) if value not in (None, "") else fallback
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _period_end(period: Any, fallback: str) -> tuple[str | None, int | None, str | None]:
    raw = str(period or "").strip().upper()
    if len(raw) == 4 and raw.isdigit():
        return f"{raw}-12-31", int(raw), "FY"
    if len(raw) == 6 and raw[:4].isdigit() and raw[4] == "Q" and raw[5] in "1234":
        month_day = {"1": "03-31", "2": "06-30", "3": "09-30", "4": "12-31"}[raw[5]]
        return f"{raw[:4]}-{month_day}", int(raw[:4]), raw[4:]
    try:
        parsed = date.fromisoformat(raw[:10]).isoformat()
        return parsed, int(parsed[:4]), None
    except ValueError:
        return fallback, None, raw or None


def _as_of(value: Any, *, fallback: str | None = None) -> str | None:
    raw = str(value or "").strip()
    if len(raw) >= 10:
        try:
            return date.fromisoformat(raw[:10]).isoformat()
        except ValueError:
            pass
    end, _, _ = _period_end(raw, fallback or "")
    if end:
        try:
            return date.fromisoformat(end[:10]).isoformat()
        except ValueError:
            return fallback
    return fallback


def _provider(fetch_method: Any) -> str:
    value = str(fetch_method or "legacy").lower()
    return value.removeprefix("api_") if value.startswith("api_") else value


def _source_snapshot(
    target: sqlite3.Connection,
    row: Mapping[str, Any] | sqlite3.Row | None,
    *,
    cache: dict[int | str, int],
    fallback_ref: str,
    as_of: str | None,
) -> tuple[int, str]:
    source_id = int(row["id"]) if row is not None and row["id"] is not None else None
    key: int | str = source_id if source_id is not None else fallback_ref
    if key in cache:
        provider = _provider(row["fetch_method"] if row is not None else "legacy")
        return cache[key], provider
    provider = _provider(row["fetch_method"] if row is not None else "legacy")
    ref = (
        str(row["source_url"] or row["url"] or row["file_path"] or f"research-source:{source_id}")
        if row is not None else fallback_ref
    )
    snapshot_id = record_source_snapshot(
        target,
        provider=provider,
        source_channel="legacy_compat",
        source_ref=ref,
        title=str(row["title"] or ref) if row is not None else fallback_ref,
        publisher=str(row["publisher"] or "") or None if row is not None else None,
        as_of_date=as_of,
        fetched_at=str(row["fetch_timestamp"] or "") or None if row is not None else None,
        raw_snapshot_path=str(row["content_snapshot_path"] or "") or None if row is not None else None,
        metadata={"research_source_id": source_id, "migration": "financial.schema.v1"},
    )
    cache[key] = snapshot_id
    return snapshot_id, provider


def _sources(source: sqlite3.Connection) -> dict[int, sqlite3.Row]:
    return {int(row["id"]): row for row in source.execute("SELECT * FROM source")}


def migrate_research_financials(
    research_db: Path,
    financial_db: Path,
    *,
    replace_existing: bool = False,
) -> dict[str, Any]:
    research_db = research_db.resolve()
    financial_db = financial_db.resolve()
    if not research_db.exists():
        raise FileNotFoundError(research_db)
    if replace_existing and financial_db.exists():
        financial_db.unlink()
    initialize_database(financial_db)
    source = _ro(research_db)
    target = connect(financial_db)
    counts = {
        "securities": 0,
        "company_current": 0,
        "company_consensus": 0,
        "profile_series": 0,
        "profile_snapshot": 0,
        "structured_legacy_points": 0,
    }
    try:
        source_rows = _sources(source)
        security_ids: dict[int, int] = {}
        source_cache: dict[int | str, int] = {}
        with transaction(target):
            companies = source.execute("SELECT * FROM company ORDER BY id").fetchall()
            for company in companies:
                company_id = int(company["id"])
                security_id = upsert_security(
                    target,
                    research_company_id=company_id,
                    canonical_name=str(company["name"]),
                    ticker=str(company["ticker"] or "") or None,
                    market=str(company["market"] or "") or None,
                    listing_status=str(company["listing_status"] or "") or None,
                    reporting_currency=str(company["per_share_currency"] or "") or None,
                )
                security_ids[company_id] = security_id
                counts["securities"] += 1

                for field, (metric, base_unit, fact_type) in COMPANY_FIELDS.items():
                    value = company[field]
                    if value is None:
                        continue
                    as_of = _as_of(
                        company["valuation_as_of"] if fact_type in {"market", "consensus"}
                        else company["financial_metrics_as_of"]
                    )
                    if not as_of:
                        continue
                    research_source_id = company[
                        "valuation_source_id" if fact_type in {"market", "consensus"}
                        else "financial_metrics_source_id"
                    ]
                    source_row = source_rows.get(int(research_source_id)) if research_source_id else None
                    snapshot_id, provider = _source_snapshot(
                        target, source_row, cache=source_cache,
                        fallback_ref=f"research-company:{company_id}:{field}", as_of=as_of,
                    )
                    unit = base_unit.replace("原币", str(company["per_share_currency"] or "原币"))
                    upsert_observation(
                        target,
                        security_id=security_id,
                        metric_name=metric,
                        value_num=value,
                        unit=unit,
                        currency=str(company["per_share_currency"] or "") or None,
                        period_end=as_of,
                        frequency="snapshot",
                        fact_type=fact_type,
                        as_of_date=as_of,
                        provider=provider,
                        raw_feature_name=field,
                        source_snapshot_id=snapshot_id,
                        legacy_ref=f"research.company:{company_id}:{field}",
                    )
                    counts["company_current"] += 1

                forecast_as_of = _as_of(company["forecast_as_of_date"])
                for field, (metric, horizon, default_unit) in FORECAST_FIELDS.items():
                    value = company[field]
                    if value is None or not forecast_as_of:
                        continue
                    source_id = company["forecast_source_id"]
                    source_row = source_rows.get(int(source_id)) if source_id else None
                    snapshot_id, provider = _source_snapshot(
                        target, source_row, cache=source_cache,
                        fallback_ref=f"research-company:{company_id}:forecast", as_of=forecast_as_of,
                    )
                    unit = default_unit or str(company["forecast_revenue_unit"] or "原币")
                    unit = unit.replace("原币", str(company["per_share_currency"] or "原币"))
                    upsert_observation(
                        target, security_id=security_id, metric_name=metric, value_num=value,
                        unit=unit, frequency="annual", fact_type="consensus", as_of_date=forecast_as_of,
                        provider=provider, raw_feature_name=field, source_snapshot_id=snapshot_id,
                        scenario_name="market_consensus", fiscal_period=horizon,
                        legacy_ref=f"research.company:{company_id}:{field}",
                    )
                    counts["company_consensus"] += 1

            for profile in source.execute("SELECT * FROM company_profile ORDER BY id"):
                company_id = int(profile["company_id"])
                security_id = security_ids.get(company_id)
                if security_id is None:
                    continue
                profile_source_ids = [int(x) for x in _safe_json(profile["source_ids"], []) if str(x).isdigit()]
                profile_source = source_rows.get(profile_source_ids[0]) if profile_source_ids else None
                as_of = _as_of(
                    profile["financials_as_of"] or profile["last_verified_at"] or profile["last_updated"],
                    fallback=_as_of(profile["period"]),
                )
                if not as_of:
                    continue
                snapshot_id, provider = _source_snapshot(
                    target, profile_source, cache=source_cache,
                    fallback_ref=f"company-profile:{profile['id']}", as_of=as_of,
                )
                for column, metric in (("revenue_series", "revenue"), ("net_income_series", "net_income")):
                    for index, item in enumerate(_safe_json(profile[column], [])):
                        if not isinstance(item, Mapping) or item.get("value") is None:
                            continue
                        end, fiscal_year, fiscal_period = _period_end(item.get("period"), as_of)
                        item_source_ids = [int(x) for x in item.get("source_ids", []) if str(x).isdigit()]
                        item_source = source_rows.get(item_source_ids[0]) if item_source_ids else profile_source
                        item_snapshot, item_provider = _source_snapshot(
                            target, item_source, cache=source_cache,
                            fallback_ref=f"company-profile:{profile['id']}:{column}:{index}", as_of=as_of,
                        )
                        upsert_observation(
                            target, security_id=security_id, metric_name=metric,
                            value_num=item["value"], unit=str(item.get("unit") or "原币"),
                            period_end=end, fiscal_year=fiscal_year, fiscal_period=fiscal_period,
                            frequency="annual", fact_type="actual", as_of_date=as_of,
                            provider=item_provider, raw_feature_name=column,
                            source_snapshot_id=item_snapshot,
                            legacy_ref=f"research.company_profile:{profile['id']}:{column}:{index}",
                        )
                        counts["profile_series"] += 1
                for column, metric, unit_column, default_unit in (
                    ("gross_margin", "gross_margin", None, "%"),
                    ("net_margin", "net_margin", None, "%"),
                    ("operating_cash_flow", "operating_cash_flow", "ocf_unit", "原币"),
                    ("capex_value", "capex", "capex_unit", "原币"),
                    ("rd_expense_ratio", "rd_expense_ratio", None, "%"),
                ):
                    if profile[column] is None:
                        continue
                    unit = str(profile[unit_column] or default_unit) if unit_column else default_unit
                    period_end, fiscal_year, fiscal_period = _period_end(profile["period"], as_of)
                    upsert_observation(
                        target, security_id=security_id, metric_name=metric,
                        value_num=profile[column], unit=unit, period_end=period_end,
                        fiscal_year=fiscal_year, fiscal_period=fiscal_period,
                        frequency="snapshot", fact_type="actual", as_of_date=as_of,
                        provider=provider, raw_feature_name=column, source_snapshot_id=snapshot_id,
                        legacy_ref=f"research.company_profile:{profile['id']}:{column}",
                    )
                    counts["profile_snapshot"] += 1

            query = """SELECT dp.*,s.fetch_method,s.title,s.publisher,s.source_url,s.url,s.file_path,
                              s.fetch_timestamp,s.content_snapshot_path,s.id AS research_source_id
                       FROM industry_data_point dp JOIN source s ON s.id=dp.source_id
                       WHERE dp.company_id IS NOT NULL
                         AND s.fetch_method IN ('api_wind','api_tushare','api_yfinance')
                       ORDER BY dp.id"""
            for point in source.execute(query):
                metric = METRIC_MAP.get(str(point["metric"]))
                if not metric or point["value_num"] is None:
                    continue
                security_id = security_ids.get(int(point["company_id"]))
                as_of = _as_of(point["as_of_date"] or point["period"])
                if security_id is None or not as_of:
                    continue
                source_row = source_rows.get(int(point["source_id"]))
                snapshot_id, provider = _source_snapshot(
                    target, source_row, cache=source_cache,
                    fallback_ref=f"industry-data-point:{point['id']}", as_of=as_of,
                )
                period_end, fiscal_year, fiscal_period = _period_end(point["period"], as_of)
                fact_type = "consensus" if int(point["is_forecast"] or 0) else (
                    "market" if metric in MARKET_METRICS else "actual"
                )
                upsert_observation(
                    target, security_id=security_id, metric_name=metric,
                    value_num=point["value_num"], unit=str(point["unit"]),
                    period_end=period_end, fiscal_year=fiscal_year, fiscal_period=fiscal_period,
                    frequency="annual" if fiscal_year else "snapshot", fact_type=fact_type,
                    as_of_date=as_of, provider=provider, raw_feature_name=str(point["metric"]),
                    source_snapshot_id=snapshot_id,
                    legacy_ref=f"research.industry_data_point:{point['id']}",
                )
                counts["structured_legacy_points"] += 1
        counts["source_snapshots"] = int(target.execute("SELECT count(*) FROM financial_source_snapshot").fetchone()[0])
        counts["observations"] = int(target.execute("SELECT count(*) FROM financial_observation").fetchone()[0])
    finally:
        target.close()
        source.close()
    return {**counts, "verification": verify_database(financial_db)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-db", type=Path, default=RESEARCH_DB)
    parser.add_argument("--financial-db", type=Path, default=DB_PATH)
    parser.add_argument("--apply", action="store_true", help="写入指定 financial DB；否则只建临时库验证")
    parser.add_argument("--confirm-live", action="store_true", help="允许写入默认 live financial.db")
    parser.add_argument("--replace-existing", action="store_true", help="重建目标 financial DB")
    args = parser.parse_args(argv)
    target = args.financial_db.resolve()
    if args.apply:
        if target == DB_PATH.resolve() and not args.confirm_live:
            parser.error("写入 live data/financial.db 必须同时给出 --confirm-live")
        result = migrate_research_financials(
            args.research_db, target, replace_existing=args.replace_existing,
        )
        result["database"] = str(target)
    else:
        with tempfile.TemporaryDirectory(prefix="financial_migration_") as td:
            temp_db = Path(td) / "financial.db"
            result = migrate_research_financials(args.research_db, temp_db, replace_existing=True)
            result["database"] = "temporary_validation"
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
