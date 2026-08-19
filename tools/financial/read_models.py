from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from .constants import DB_PATH
from .db import connect
from .valuation import historical_pb_band


CORE_METRICS = {
    "close", "pe_ttm", "pe_forward", "pb", "ps_ttm", "ev_ebitda",
    "market_cap", "market_cap_cny", "market_cap_usd",
    "roe", "roa", "eps", "eps_ttm", "bps_mrq", "revenue", "net_income",
    "revenue_yoy", "net_income_yoy",
    "operating_cash_flow", "capex", "free_cash_flow", "total_assets", "book_value",
    "total_equity", "total_liabilities", "debt_ratio", "asset_turnover",
    "gross_margin", "net_margin", "roic", "interest_bearing_debt",
    "operating_liabilities", "net_debt", "ebitda",
}

IMPLIED_METRIC_LABELS = {
    "pe_forward": "当前市值对应的独立预测市盈率",
    "pb": "固定当前市值的留存收益桥市净率",
    "net_income": "终值倍数情景要求的归母净利润",
    "revenue": "当前价格隐含营业收入",
    "roe": "当前价格隐含净资产收益率",
    "free_cash_flow": "当前价格隐含自由现金流",
}

PUBLIC_SCENARIO_LABELS = {
    "reported": "已披露实际值",
    "base": "基准情景",
    "downside": "下行情景",
    "upside": "上行情景",
    "median": "市场预测中位数",
    "target_pe_midpoint": "目标市盈率中值口径",
    "market_pb_gordon": "当前PB的长期回报口径",
}

PUBLIC_MODEL_SUBSTITUTION_LABELS = {
    "net_income_rmb_bn": "归母净利润（十亿元）",
    "pe_range": "市盈率区间（倍）",
    "sustainable_roe_pct": "可持续净资产收益率（%）",
    "cost_of_equity_pct": "股权资本成本（%）",
    "terminal_growth_pct": "永续增长率（%）",
    "cycle_haircut": "周期折价系数",
    "pb_range": "市净率区间（倍）",
    "fcfe_rmb_bn": "股权自由现金流（十亿元）",
    "terminal_value_share_pct": "终值占估值比例（%）",
    "company_project_ownership_pct": "公司项目权益比例（%）",
    "planned_capacity_10kt": "规划产能（万吨）",
    "risk_discount_pct": "项目风险折价（%）",
}

PROVIDER_PRIORITY = {
    "company_filing": -1,
    "wind": 0,
    "tushare": 1,
    "yfinance": 2,
    "internal_model": 3,
    "legacy": 9,
}


def _feature_priority(row: dict[str, Any]) -> int:
    """Prefer like-for-like current fields before generic report-period copies."""
    metric = str(row.get("metric_name") or "").lower()
    feature = str(row.get("raw_feature_name") or "").lower()
    preferred_tokens = {
        "pe_ttm": ("wss.pe_ttm", "wsd.pe_ttm", "pe_ttm"),
        "pb": ("wss.pb_lf", "wsd.pb_lf", "pb_lf"),
        "roe": ("wss.roe_ttm", "roe_ttm"),
        "roa": ("wss.roa2_ttm", "roa2_ttm"),
        "eps_ttm": ("wss.eps_ttm", "eps_ttm"),
        "bps_mrq": ("wss.bps_new", "bps_new"),
        "close": ("wsd.close", "wss.close", "close"),
        "market_cap_cny": ("wss.mkt_cap_ard", "mkt_cap_ard"),
    }
    for rank, token in enumerate(preferred_tokens.get(metric, ())):
        if token in feature:
            return rank
    return 20


def _row_priority(row: dict[str, Any]) -> tuple[Any, ...]:
    """A股按 Wind 主源、Tushare 逐字段补缺，再比较字段口径和时点。"""
    return (
        -PROVIDER_PRIORITY.get(str(row.get("provider") or "").lower(), 5),
        -_feature_priority(row),
        str(row.get("as_of_date") or ""),
        int(row.get("id") or 0),
    )


def _public_model_source_label(source_ref: Any, input_type: Any = None) -> str:
    ref = str(source_ref or "").strip()
    kind = str(input_type or "").strip()
    if kind == "external_consensus":
        return "市场或一致预期快照"
    if kind == "company_guidance":
        return "公司指引"
    if kind == "expert_assumption":
        return "冻结内部研究假设"
    if kind == "direct_fact":
        return "公司披露或结构化财务快照"
    if kind == "derived_fact":
        return "冻结模型推导"
    if ref.startswith("sha256:"):
        return "已冻结模型底稿"
    return "可追溯模型来源"


def _public_scenario_label(value: Any) -> str:
    """Translate stored scenario identifiers before they reach public pages."""
    name = str(value or "").strip()
    if not name:
        return "口径未单列"
    if name in PUBLIC_SCENARIO_LABELS:
        return PUBLIC_SCENARIO_LABELS[name]
    if "_" in name and name.isascii():
        return "模型设定口径"
    return name


def _public_model_substitution(value: Any) -> str:
    """Render structured model substitutions as readable Chinese, not raw JSON."""
    text = str(value or "").strip()
    if not text:
        return "模型账本未单列代入值"

    def format_numbers(source: str) -> str:
        return re.sub(
            r"(?<![A-Za-z0-9.\-])-?\d+(?:\.\d+)?(?![A-Za-z0-9.\-])",
            lambda match: f"{float(match.group(0)):.2f}",
            source,
        )

    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return format_numbers(text)
    if not isinstance(parsed, dict):
        return format_numbers(text)

    def format_value(item: Any) -> str:
        if isinstance(item, list):
            values = [format_value(child) for child in item]
            return "—".join(values) if len(values) == 2 else "、".join(values)
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            return f"{float(item):.2f}"
        return str(item)

    return "；".join(
        (
            f"{PUBLIC_MODEL_SUBSTITUTION_LABELS.get(key, key.replace('_', ' '))}"
            f"＝{format_value(item)}"
        )
        for key, item in parsed.items()
    )


def _model_implied_expectations(model_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expose explicit reverse-valuation outputs already frozen in model ledgers."""
    def metric_name(output_name: str) -> str:
        for token, canonical in (
            ("归母净利润", "net_income"), ("净利润", "net_income"),
            ("市盈率", "pe_forward"), ("PE", "pe_forward"),
            ("营业收入", "revenue"), ("收入", "revenue"),
            ("净资产收益率", "roe"), ("ROE", "roe"),
            ("自由现金流", "free_cash_flow"),
        ):
            if token in output_name:
                return canonical
        return output_name

    rows: list[dict[str, Any]] = []
    for run in model_runs:
        if run.get("skill_name") != "company_valuation_modeling":
            continue
        for output in run.get("outputs") or []:
            output_name = str(output.get("output_name") or "").strip()
            if "隐含" not in output_name:
                continue
            rows.append({
                "metric_name": metric_name(output_name),
                "metric_label": output_name,
                "value_num": output.get("value_num"),
                "value_text": output.get("value_text"),
                "range_low": output.get("range_low"),
                "range_high": output.get("range_high"),
                "unit": output.get("unit"),
                "period": output.get("period_or_as_of_date") or run.get("forecast_end"),
                "as_of_date": run.get("valuation_date"),
                "provider": "internal_model",
                "formula": output.get("formula"),
                "substitution": output.get("substitution"),
                "scenario_name": "模型反推",
                "source_title": run.get("model_name"),
                "model_run_id": run.get("id"),
            })
    return rows


def _latest(rows: list[dict[str, Any]], *, fact_types: set[str] | None = None) -> dict[str, Any] | None:
    eligible = [
        row for row in rows
        if row.get("quality_status") not in {"superseded", "not_applicable"}
        and (fact_types is None or row.get("fact_type") in fact_types)
    ]
    return max(eligible, key=_row_priority) if eligible else None


def _provider_label(provider: Any) -> str:
    return {
        "wind": "Wind",
        "tushare": "Tushare",
        "yfinance": "Yahoo Finance",
        "company_filing": "公司年报",
        "external_consensus": "最近两个季度卖方预测中位数",
        "internal_model": "内部模型",
        "legacy": "历史兼容数据",
    }.get(str(provider or "").lower(), str(provider or "来源未标明"))


def _current_metrics_view(
    metrics: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, Any] | None]:
    selected: dict[str, dict[str, Any] | None] = {}
    for metric in (
        "close", "pe_ttm", "pe_forward", "pb", "ps_ttm", "ev_ebitda",
        "roe", "roa", "eps_ttm", "bps_mrq",
        "market_cap_cny", "market_cap_usd",
    ):
        fact_types = {"market"} if metric in {
            "close", "pe_ttm", "pe_forward", "pb", "ps_ttm", "ev_ebitda",
            "market_cap_cny", "market_cap_usd",
        } else (
            # Wind WSS 的最新 TTM/MRQ 指标属于可随市场日更新的快照，写在
            # market 层；年度/季度报表值仍在 actual 层。公司页应优先显示
            # 同口径的最新 Wind 快照，再回退到历史 actual，不能把 market
            # 层存在误判成“接口不可得”。
            {"market", "actual"}
            if metric in {"roe", "roa", "eps_ttm", "bps_mrq"}
            else {"actual"}
        )
        row = _latest(metrics.get(metric, []), fact_types=fact_types)
        if row:
            row = dict(row)
            row["provider_label"] = _provider_label(row.get("provider"))
        selected[metric] = row
    if selected["market_cap_cny"] is None:
        row = _latest(metrics.get("market_cap", []), fact_types={"market"})
        if row:
            row = dict(row)
            row["provider_label"] = _provider_label(row.get("provider"))
        selected["market_cap_cny"] = row
    return selected


def _period_key(row: dict[str, Any]) -> str:
    if row.get("fiscal_year"):
        suffix = str(row.get("fiscal_period") or "FY")
        if suffix == "FY":
            return str(int(row["fiscal_year"]))
        if suffix in {"FY1", "FY2", "FY3", "FY4", "FY5", "FY6"}:
            return f"{int(row['fiscal_year'])}（{suffix}）"
        return f"{int(row['fiscal_year'])}{suffix}"
    return str(row.get("period_end") or row.get("as_of_date") or "")


def _return_period_label(row: dict[str, Any]) -> str:
    """Use an economically meaningful report-period label for PB/return plots.

    Some legacy snapshot rows carry ``fiscal_year`` without ``fiscal_period`` even
    though the underlying observation is a quarter.  Labeling those rows as a full
    year both misstates the return period and creates duplicate labels beside the
    normalized record.  Prefer an explicit period and otherwise infer the standard
    A-share reporting slot from ``period_end``.
    """
    year = row.get("fiscal_year")
    period = str(row.get("fiscal_period") or "").upper()
    if year and period in {"FY", "Q1", "Q2", "Q3", "Q4", "H1"}:
        return f"{int(year)}{period if period != 'FY' else ''}"
    raw = str(row.get("period_end") or "")
    try:
        ended = date.fromisoformat(raw[:10])
    except ValueError:
        return _period_key(row)
    suffix = {3: "Q1", 6: "H1", 9: "Q3", 12: ""}.get(ended.month)
    return f"{ended.year}{suffix}" if suffix is not None else ended.isoformat()


def _deduplicate_economic_observations(
    rows: list[dict[str, Any]],
    *,
    date_field: str,
) -> list[dict[str, Any]]:
    """Collapse legacy/current copies of the same dated numeric observation."""
    selected: dict[tuple[str, float], dict[str, Any]] = {}
    for row in rows:
        if (
            row.get("quality_status") in {"superseded", "not_applicable"}
            or row.get("value_num") is None
            or not row.get(date_field)
        ):
            continue
        key = (str(row[date_field])[:10], round(float(row["value_num"]), 10))
        if key not in selected or _row_priority(row) > _row_priority(selected[key]):
            selected[key] = row
    return list(selected.values())


def _historical_table(metrics: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    wanted = ("revenue", "net_income", "gross_margin", "net_margin", "roe", "roa", "operating_cash_flow", "capex", "free_cash_flow", "book_value", "total_assets")
    by_period: dict[str, dict[str, Any]] = {}
    for metric in wanted:
        candidates: dict[str, dict[str, Any]] = {}
        for row in metrics.get(metric, []):
            if row.get("fact_type") != "actual" or row.get("value_num") is None:
                continue
            if row.get("quality_status") in {"superseded", "not_applicable"}:
                continue
            key = _period_key(row)
            if key and (key not in candidates or _row_priority(row) > _row_priority(candidates[key])):
                candidates[key] = row
        for period, row in candidates.items():
            item = by_period.setdefault(period, {"period": period, "metrics": {}})
            item["metrics"][metric] = {
                "value": row.get("value_num"), "unit": row.get("unit"),
                "as_of_date": row.get("as_of_date"), "provider": row.get("provider"),
                "source_title": row.get("source_title"), "source_ref": row.get("source_ref"),
            }
    # 同比必须与同口径上年同期比较。供应商已经给出季度同比时，显式附着到
    # 对应收入/利润观测，避免 Viewer 把一季度累计值与上一年度全年值顺序相除。
    for growth_metric, base_metric in (
        ("revenue_yoy", "revenue"),
        ("net_income_yoy", "net_income"),
    ):
        candidates: dict[str, dict[str, Any]] = {}
        for row in metrics.get(growth_metric, []):
            if row.get("fact_type") != "actual" or row.get("value_num") is None:
                continue
            if row.get("quality_status") in {"superseded", "not_applicable"}:
                continue
            key = _period_key(row)
            if key and (
                key not in candidates
                or _row_priority(row) > _row_priority(candidates[key])
            ):
                candidates[key] = row
        for period, row in candidates.items():
            base = by_period.get(period, {}).get("metrics", {}).get(base_metric)
            if base is not None:
                base["yoy"] = row.get("value_num")
    return [by_period[key] for key in sorted(by_period)]


def _forecast_table(metrics: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for horizon in ("FY1", "FY2", "FY3"):
        item: dict[str, Any] = {"horizon": horizon, "internal": {}, "consensus": {}}
        for metric in ("revenue", "net_income", "eps", "operating_cash_flow", "capex", "free_cash_flow", "roe", "roa", "book_value"):
            for fact_type, key in (("internal_estimate", "internal"), ("consensus", "consensus")):
                candidates = [
                    row for row in metrics.get(metric, [])
                    if row.get("fact_type") == fact_type and row.get("fiscal_period") == horizon
                    and row.get("value_num") is not None
                    and row.get("quality_status") not in {
                        "superseded", "not_applicable"
                    }
                ]
                if fact_type == "internal_estimate":
                    base_candidates = [
                        row
                        for row in candidates
                        if str(row.get("scenario_name") or "base")
                        in {"base", "reported"}
                    ]
                    if base_candidates:
                        candidates = base_candidates
                if candidates:
                    row = max(candidates, key=_row_priority)
                    item[key][metric] = {
                        "value": row["value_num"], "unit": row["unit"],
                        "fiscal_year": row.get("fiscal_year"),
                        "as_of_date": row["as_of_date"], "provider": row["provider"],
                        "source_title": row.get("source_title"), "source_ref": row.get("source_ref"),
                    }
        rows.append(item)
    return rows


def _paired_return_points(
    return_rows: list[dict[str, Any]],
    pb_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """One report period to one later PB observation; never expand one ROE into many daily samples."""
    returns = _deduplicate_economic_observations(
        [
            row for row in return_rows
            if row.get("fact_type") == "actual"
            and row.get("value_num") is not None
            and row.get("period_end")
        ],
        date_field="period_end",
    )
    multiples = _deduplicate_economic_observations(
        [
            row for row in pb_rows
            if row.get("fact_type") == "market"
            and row.get("value_num") is not None
            and row.get("as_of_date")
        ],
        date_field="as_of_date",
    )
    used_pb_ids: set[int] = set()
    points: list[dict[str, Any]] = []
    for result in sorted(returns, key=lambda row: str(row.get("period_end"))):
        if (
            str(result.get("frequency") or "").lower() == "annual"
            and not result.get("announcement_date")
        ):
            # Pairing an undisclosed full-year return to year-end PB would use
            # information the market did not yet have. Keep the annual return
            # in the history table, but exclude it from PB-return regression.
            continue
        try:
            report_date = date.fromisoformat(
                str(result.get("announcement_date") or result["period_end"])[:10]
            )
        except ValueError:
            continue
        eligible = []
        for pb in multiples:
            if int(pb.get("id") or 0) in used_pb_ids:
                continue
            try:
                pb_date = date.fromisoformat(str(pb["as_of_date"])[:10])
            except ValueError:
                continue
            lag = (pb_date - report_date).days
            if 0 <= lag <= 550:
                eligible.append((lag, pb))
        if not eligible:
            continue
        _, pb = min(eligible, key=lambda pair: (pair[0], int(pair[1].get("id") or 0)))
        used_pb_ids.add(int(pb.get("id") or 0))
        points.append({
            "period": _return_period_label(result), "return_value": result["value_num"],
            "return_as_of": result.get("period_end"),
            "return_available_date": (
                result.get("announcement_date") or result.get("period_end")
            ),
            "pb": pb["value_num"],
            "pb_as_of": pb.get("as_of_date"), "return_source": result.get("source_title"),
            "pb_source": pb.get("source_title"),
        })
    return points


def _safe_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _latest_value(
    metrics: dict[str, list[dict[str, Any]]],
    metric: str,
    *,
    fact_types: set[str] | None = None,
) -> float | None:
    row = _latest(metrics.get(metric, []), fact_types=fact_types)
    return float(row["value_num"]) if row and row.get("value_num") is not None else None


def _full_year_actuals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[int, dict[str, Any]] = {}
    for row in rows:
        if (
            row.get("fact_type") != "actual"
            or row.get("quality_status") in {"superseded", "not_applicable"}
            or row.get("value_num") is None
            or not row.get("fiscal_year")
        ):
            continue
        period = str(row.get("fiscal_period") or "").upper()
        period_end = str(row.get("period_end") or "")
        if period not in {"FY", "Q4"} and not period_end.endswith("-12-31"):
            continue
        year = int(row["fiscal_year"])
        if year not in selected or _row_priority(row) > _row_priority(selected[year]):
            selected[year] = row
    return [selected[year] for year in sorted(selected)]


def _full_year_actual_display(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep explicit filing-level ``not applicable`` years in the public table."""
    selected: dict[int, dict[str, Any]] = {}
    for row in rows:
        if (
            row.get("fact_type") != "actual"
            or row.get("quality_status") == "superseded"
            or (
                row.get("value_num") is None
                and not str(row.get("value_text") or "").strip()
            )
            or not row.get("fiscal_year")
        ):
            continue
        period = str(row.get("fiscal_period") or "").upper()
        period_end = str(row.get("period_end") or "")
        if period not in {"FY", "Q4"} and not period_end.endswith("-12-31"):
            continue
        year = int(row["fiscal_year"])
        if year not in selected or _row_priority(row) > _row_priority(selected[year]):
            selected[year] = row
    return [selected[year] for year in sorted(selected)]


def _quality_panel(metrics: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    current = {
        name: _latest(metrics.get(name, []), fact_types={"actual"})
        for name in (
            "roe", "roa", "roic", "debt_ratio", "total_assets", "book_value",
            "total_equity", "total_liabilities", "interest_bearing_debt",
            "operating_liabilities", "net_debt", "ebitda",
            "operating_cash_flow", "net_income", "capex", "free_cash_flow",
        )
    }
    assets = current["total_assets"]
    # Total assets must be paired with total equity (including minority
    # interests) when calculating an accounting equity multiplier.  Parent
    # equity is still used by the separate shareholder book-value bridge.
    equity = current["total_equity"] or current["book_value"]
    liabilities = current["total_liabilities"]
    multiplier = None
    if assets and equity and float(equity["value_num"]) > 0:
        multiplier = float(assets["value_num"]) / float(equity["value_num"])
    debt_ratio = (
        float(current["debt_ratio"]["value_num"])
        if current["debt_ratio"]
        else (
            float(liabilities["value_num"]) / float(assets["value_num"]) * 100
            if liabilities and assets and float(assets["value_num"]) > 0
            else None
        )
    )
    ocf = _latest_value(metrics, "operating_cash_flow", fact_types={"actual"})
    profit = _latest_value(metrics, "net_income", fact_types={"actual"})
    capex = _latest_value(metrics, "capex", fact_types={"actual"})
    net_debt = _latest_value(metrics, "net_debt", fact_types={"actual"})
    ebitda = _latest_value(metrics, "ebitda", fact_types={"actual"})
    roe = _latest_value(metrics, "roe", fact_types={"actual"})
    roa = _latest_value(metrics, "roa", fact_types={"actual"})
    implied = roa * multiplier if roa is not None and multiplier else None
    if roe is None or roa is None or multiplier is None:
        return {
            "metrics": current,
            "equity_multiplier": multiplier,
            "debt_ratio": debt_ratio,
            "ocf_to_net_income": ocf / profit if ocf is not None and profit else None,
            "ocf_to_capex": ocf / capex if ocf is not None and capex else None,
            "net_debt_to_ebitda": (
                net_debt / ebitda if net_debt is not None and ebitda else None
            ),
            "roe_quality_conclusion": "现有字段不足以完整拆解ROE质量。",
            "data_status": "partial",
        }
    residual = roe - implied
    if roa >= 10 and multiplier <= 2.5:
        conclusion = "当前ROE主要有较高资产回报支撑，杠杆不是唯一来源。"
    elif multiplier >= 3 and roa < 10:
        conclusion = "当前ROE较多依赖权益乘数放大，需要进一步核对有息与经营性负债。"
    else:
        conclusion = "当前ROE由资产回报和资本结构共同形成，不能只看单一比率。"
    return {
        "metrics": current,
        "equity_multiplier": multiplier,
        "debt_ratio": debt_ratio,
        "implied_roe_from_roa": implied,
        "roe_bridge_residual": residual,
        "ocf_to_net_income": ocf / profit if ocf is not None and profit else None,
        "ocf_to_capex": ocf / capex if ocf is not None and capex else None,
        "net_debt_to_ebitda": (
            net_debt / ebitda if net_debt is not None and ebitda else None
        ),
        "roe_quality_conclusion": conclusion,
        "data_status": "usable",
    }


def _valuation_band_history(
    metrics: dict[str, list[dict[str, Any]]],
    multiple_metric: str,
) -> dict[str, Any] | None:
    """Build a Wind-style price band from aligned close and valuation multiples.

    For each month, ``per_share_base = close / observed_multiple``.  Applying
    fixed historical multiple quantiles to that month's base gives comparable
    price-band lines without inventing a separate EPS/BPS history.
    """
    if multiple_metric not in {"pe_ttm", "pb"}:
        raise ValueError(f"不支持的估值带指标：{multiple_metric}")
    current = _latest(metrics.get(multiple_metric, []), fact_types={"market"})
    if not current or float(current.get("value_num") or 0) <= 0:
        return None
    close_rows = [
        row for row in metrics.get("close", [])
        if row.get("fact_type") == "market"
        and row.get("frequency") in {None, "", "monthly"}
        and row.get("value_num") is not None
        and row.get("as_of_date")
        and (
            "wsd.close" in str(row.get("raw_feature_name") or "").lower()
            or "yfinance.history.month_end_close"
            in str(row.get("raw_feature_name") or "").lower()
        )
    ]
    multiple_rows = [
        row for row in metrics.get(multiple_metric, [])
        if row.get("fact_type") == "market"
        and row.get("frequency") in {None, "", "monthly"}
        and row.get("value_num") is not None
        and row.get("as_of_date")
        and (
            f"wsd.{'pe_ttm' if multiple_metric == 'pe_ttm' else 'pb_lf'}"
            in str(row.get("raw_feature_name") or "").lower()
            or f"yfinance.derived.point_in_time.{multiple_metric}"
            in str(row.get("raw_feature_name") or "").lower()
        )
        and float(row.get("value_num") or 0) > 0
    ]
    derived_point_in_time = any(
        "yfinance.derived.point_in_time" in str(row.get("raw_feature_name") or "").lower()
        for row in multiple_rows
    )
    close_by_date = {
        str(row["as_of_date"])[:10]: row
        for row in _deduplicate_economic_observations(
            close_rows, date_field="as_of_date"
        )
    }
    multiple_by_date = {
        str(row["as_of_date"])[:10]: row
        for row in _deduplicate_economic_observations(
            multiple_rows, date_field="as_of_date"
        )
    }
    dates = sorted(set(close_by_date) & set(multiple_by_date))
    if len(dates) < 12:
        return None
    values = [float(multiple_by_date[item]["value_num"]) for item in dates]
    try:
        statistics = historical_pb_band(
            values,
            current_pb=float(current["value_num"]),
        )
    except ValueError:
        return None
    rows: list[dict[str, Any]] = []
    for item in dates:
        close = float(close_by_date[item]["value_num"])
        multiple = float(multiple_by_date[item]["value_num"])
        if close <= 0 or multiple <= 0:
            continue
        base = close / multiple
        rows.append({
            "date": item,
            "close": close,
            "multiple": multiple,
            "base_per_share": base,
            "q20_price": base * float(statistics["q20"]),
            "median_price": base * float(statistics["median"]),
            "q80_price": base * float(statistics["q80"]),
        })
    return {
        "metric_name": multiple_metric,
        "rows": rows,
        "statistics": statistics,
        "current": current,
        "source_provider": _provider_label(current.get("provider")),
        "history_basis": (
            "Yahoo Finance月末收盘价＋当时已公开年报EPS/BPS的点时近似"
            if derived_point_in_time else "供应商同日月末收盘价与估值倍数"
        ),
        "formula": (
            "每期隐含每股基础＝当期收盘价÷当期估值倍数；"
            "估值带价格＝每期隐含每股基础×历史估值倍数分位。"
        ),
        "boundary": (
            (
                "海外公司历史PE/PB按当时已公开年报EPS/BPS近似，不是Yahoo Finance历史TTM字段；"
                if derived_point_in_time else ""
            )
            + "估值带展示历史倍数位置，不是目标价；盈利或净资产口径发生结构变化时，"
            "历史分位的可比性会下降。"
        ),
    }


def _valuation_band_availability(
    metrics: dict[str, list[dict[str, Any]]],
    multiple_metric: str,
) -> dict[str, Any]:
    """Explain price-band availability without conflating history with API failure."""
    if multiple_metric not in {"pe_ttm", "pb"}:
        raise ValueError(f"不支持的估值带指标：{multiple_metric}")
    raw_multiple = "wsd.pe_ttm" if multiple_metric == "pe_ttm" else "wsd.pb_lf"
    derived_multiple = f"yfinance.derived.point_in_time.{multiple_metric}"
    close_by_date = {
        str(row.get("as_of_date") or "")[:10]
        for row in metrics.get("close", [])
        if row.get("fact_type") == "market"
        and row.get("frequency") in {None, "", "monthly"}
        and row.get("value_num") is not None
        and float(row.get("value_num") or 0) > 0
        and (
            "wsd.close" in str(row.get("raw_feature_name") or "").lower()
            or "yfinance.history.month_end_close"
            in str(row.get("raw_feature_name") or "").lower()
        )
    }
    multiple_by_date = {
        str(row.get("as_of_date") or "")[:10]
        for row in metrics.get(multiple_metric, [])
        if row.get("fact_type") == "market"
        and row.get("frequency") in {None, "", "monthly"}
        and row.get("value_num") is not None
        and float(row.get("value_num") or 0) > 0
        and (
            raw_multiple in str(row.get("raw_feature_name") or "").lower()
            or derived_multiple in str(row.get("raw_feature_name") or "").lower()
        )
    }
    aligned_dates = sorted((close_by_date & multiple_by_date) - {""})
    current = _latest(metrics.get(multiple_metric, []), fact_types={"market"})
    current_valid = bool(current and float(current.get("value_num") or 0) > 0)
    current_provider = str((current or {}).get("provider") or "").lower()
    current_provider_label = _provider_label((current or {}).get("provider"))
    sample_size = len(aligned_dates)
    metric_label = "PB" if multiple_metric == "pb" else "PE"
    if not current_valid:
        message = f"历史估值带待补：当前{metric_label}没有可用正值。"
        status = "current_multiple_missing"
    elif sample_size == 0 and current_provider != "wind":
        message = f"历史估值带待补：需要至少12个月同口径月末数据，当前为0个月。"
        status = "provider_monthly_history_not_loaded"
    elif sample_size == 0:
        message = f"历史估值带待补：需要至少12个月同口径月末数据，当前为0个月。"
        status = "monthly_history_not_loaded"
    elif sample_size < 12:
        message = f"历史估值带待补：至少需要12个月同口径月末数据，当前为{sample_size}个月。"
        status = "insufficient_monthly_history"
    else:
        message = (
            f"{current_provider_label}已取得{sample_size}个有效月末观察，"
            f"可绘制{metric_label}历史估值带。"
        )
        status = "ready"
    return {
        "status": status,
        "sample_size": sample_size,
        "minimum_required": 12,
        "first_date": aligned_dates[0] if aligned_dates else None,
        "last_date": aligned_dates[-1] if aligned_dates else None,
        "current_multiple_available": current_valid,
        "current_provider": current_provider_label if current else None,
        "message": message,
    }


def _asset_return_view(metrics: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    pb = _latest(metrics.get("pb", []), fact_types={"market"})
    roe = _latest(metrics.get("roe", []), fact_types={"market", "actual"})
    roa = _latest(metrics.get("roa", []), fact_types={"market", "actual"})
    roic = _latest(metrics.get("roic", []), fact_types={"actual"})
    debt_ratio = _latest(metrics.get("debt_ratio", []), fact_types={"actual"})
    asset_turnover = _latest(metrics.get("asset_turnover", []), fact_types={"actual"})
    net_margin = _latest(metrics.get("net_margin", []), fact_types={"actual"})
    assets = _latest(metrics.get("total_assets", []), fact_types={"actual"})
    equity = _latest(metrics.get("book_value", []) + metrics.get("total_equity", []), fact_types={"actual"})
    equity_multiplier = None
    if assets and equity and float(equity.get("value_num") or 0) > 0:
        equity_multiplier = float(assets["value_num"]) / float(equity["value_num"])
    roe_points = _paired_return_points(metrics.get("roe", []), metrics.get("pb", []))
    roa_points = _paired_return_points(metrics.get("roa", []), metrics.get("pb", []))
    pb_candidates = [
        row for row in metrics.get("pb", [])
        if row.get("fact_type") == "market"
        and row.get("value_num") is not None
        and row.get("as_of_date")
    ]
    # A complete WSD sequence has one deliberate observation per sampling date.
    # Do not mix legacy one-off WSS/Tushare snapshots into that historical band:
    # they add arbitrary dates and shift empirical percentiles.  Keep the
    # fallback for companies without a sufficiently long WSD history.
    provider_history = [
        row for row in pb_candidates
        if row.get("frequency") in {None, "", "monthly"}
        and (
            "wsd.pb_lf" in str(row.get("raw_feature_name") or "").lower()
            or "yfinance.derived.point_in_time.pb"
            in str(row.get("raw_feature_name") or "").lower()
        )
    ]
    pb_history = _deduplicate_economic_observations(
        provider_history if len(provider_history) >= 12 else pb_candidates,
        date_field="as_of_date",
    )
    pb_by_date: dict[str, dict[str, Any]] = {}
    for row in pb_history:
        key = str(row.get("as_of_date") or "")[:10]
        if key and (
            key not in pb_by_date
            or _row_priority(row) > _row_priority(pb_by_date[key])
        ):
            pb_by_date[key] = row
    pb_history = [
        pb_by_date[key] for key in sorted(pb_by_date)
    ]
    pb_band = None
    if pb and len(pb_history) >= 12:
        try:
            pb_band = historical_pb_band(
                [float(row["value_num"]) for row in pb_history],
                current_pb=float(pb["value_num"]),
            )
        except ValueError:
            pb_band = None
    roe_history = _full_year_actuals(metrics.get("roe", []))
    roe_history_display = _full_year_actual_display(metrics.get("roe", []))
    roe_values = [float(row["value_num"]) for row in roe_history]
    quality = _quality_panel(metrics)
    return {
        "current": {
            "pb": pb, "roe": roe, "roa": roa, "roic": roic,
            "debt_ratio": debt_ratio, "asset_turnover": asset_turnover,
            "net_margin": net_margin, "equity_multiplier": equity_multiplier,
            "pb_historical_percentile": (
                pb_band["current_percentile"] if pb_band else None
            ),
            "pb_percentile_sample_size": (
                pb_band["sample_size"] if pb_band else 0
            ),
            "implied_roe_from_roa": (float(roa["value_num"]) * equity_multiplier if roa and equity_multiplier else None),
        },
        "roe_history": roe_history,
        "roe_history_display": roe_history_display,
        "roe_history_excluded_count": sum(
            1
            for row in roe_history_display
            if row.get("quality_status") == "not_applicable"
        ),
        "roe_history_summary": {
            "sample_size": len(roe_values),
            "average": sum(roe_values) / len(roe_values) if roe_values else None,
            "minimum": min(roe_values) if roe_values else None,
            "maximum": max(roe_values) if roe_values else None,
        },
        "pb_history": pb_history,
        "pb_band": pb_band,
        "pe_price_band": _valuation_band_history(metrics, "pe_ttm"),
        "pb_price_band": _valuation_band_history(metrics, "pb"),
        "pe_price_band_availability": _valuation_band_availability(metrics, "pe_ttm"),
        "pb_price_band_availability": _valuation_band_availability(metrics, "pb"),
        "quality": quality,
        "pb_roe_points": roe_points,
        "pb_roa_points": roa_points,
        "pb_roe_status": "estimable" if len(roe_points) >= 3 else "insufficient_paired_periods",
        "pb_roa_status": "estimable" if len(roa_points) >= 3 else "insufficient_paired_periods",
        "minimum_pair_rule": "至少三个独立财务报告期，每期只匹配一个报告后 PB 观察值。",
    }


def _valuation_framework_view(
    model_runs: list[dict[str, Any]],
    metrics: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    # Prefer an explicitly configured PB framework.  A multi-method valuation
    # run does not have to contain "PB" in its public model name/run key; using
    # the name as the only router hid valid framework assumptions for the
    # lithium-battery company models.
    configured_pb_runs = [
        run for run in model_runs
        if run.get("skill_name") == "company_valuation_modeling"
        and isinstance((run.get("assumptions") or {}).get("pb_framework"), dict)
        and bool((run.get("assumptions") or {}).get("pb_framework"))
    ]
    named_pb_runs = [
        run for run in model_runs
        if run.get("skill_name") == "company_valuation_modeling"
        and (
            "pb" in str(run.get("run_key") or "").lower()
            or "PB" in str(run.get("model_name") or "")
        )
    ]
    pb_runs = configured_pb_runs or named_pb_runs
    selected = pb_runs[0] if pb_runs else None
    assumptions = (
        dict(selected.get("assumptions") or {}) if selected else {}
    )
    framework = dict(assumptions.get("pb_framework") or {})
    if not framework:
        framework = {
            "applicability": (
                "诊断方法"
                if _latest(metrics.get("pb", []), fact_types={"market"})
                else "数据不足，暂不路由"
            ),
            "cycle_sensitivity": "尚未完成专项判断",
            "asset_intensity": "尚未完成专项判断",
            "basis": (
                "当前仅有市场PB与财务观察值；未完成业务、周期和资产结构专项研究。"
            ),
            "price_exposure": "尚未形成可追溯结论",
            "profit_driver": "尚未形成可追溯结论",
            "tags": [],
        }
    framework["model_run_key"] = selected.get("run_key") if selected else None
    framework["limitations"] = selected.get("limitations") if selected else None
    return framework


def _scenario_workbench_view(
    model_runs: list[dict[str, Any]],
    metrics: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    configured: dict[str, Any] = {}
    for run in model_runs:
        assumptions = dict(run.get("assumptions") or {})
        candidate = assumptions.get("scenario_workbench")
        if isinstance(candidate, dict) and candidate:
            configured = dict(candidate)
            configured["model_run_key"] = run.get("run_key")
            break
    if not configured:
        return {
            "simple_ready": False,
            "detailed_ready": False,
            "default_mode": "simple",
            "reason": (
                "尚无经过冻结的期初净资产、净利润路径、留存率和目标PB组合；"
                "页面不会从当前倍数自动生成研究员默认情景。"
            ),
            "simple": {},
            "detailed": {},
        }
    configured.setdefault("default_mode", "simple")
    configured.setdefault("simple_ready", False)
    configured.setdefault("detailed_ready", False)
    configured.setdefault("simple", {})
    configured.setdefault("detailed", {})
    return configured


def _valuation_summary_view(
    model_runs: list[dict[str, Any]],
    metrics: dict[str, list[dict[str, Any]]],
    forecast_table: list[dict[str, Any]],
    asset_return: dict[str, Any],
) -> dict[str, Any]:
    """Compact company-page conclusion from frozen research plus live financial facts."""
    configured: dict[str, Any] = {}
    for run in model_runs:
        candidate = (run.get("assumptions") or {}).get("company_detail_summary")
        if isinstance(candidate, dict) and candidate:
            configured = dict(candidate)
            configured["model_run_key"] = run.get("run_key")
            break
    if not configured:
        return {
            "ready": False,
            "reason": "尚无经过冻结研究支持的公司级综合估值结论，页面不自动生成买卖观点。",
        }

    current_metrics = _current_metrics_view(metrics)
    source_index: list[dict[str, Any]] = []
    seen_sources: set[tuple[str, str, str]] = set()
    for metric in ("close", "market_cap_cny", "pe_ttm", "pb", "roe", "roa"):
        row = current_metrics.get(metric)
        if not row:
            continue
        key = (
            str(row.get("provider_label") or ""),
            str(row.get("as_of_date") or ""),
            str(row.get("source_title") or ""),
        )
        if key not in seen_sources:
            seen_sources.add(key)
            source_index.append({
                "provider": row.get("provider_label"),
                "as_of_date": row.get("as_of_date"),
                "source_title": row.get("source_title"),
                "source_ref": row.get("source_ref"),
            })

    comparison_rows: list[dict[str, Any]] = []
    largest_gap: dict[str, Any] | None = None
    for row in forecast_table:
        internal = (row.get("internal") or {}).get("net_income")
        consensus = (row.get("consensus") or {}).get("net_income")
        if not internal and not consensus:
            continue
        internal_value = float(internal["value"]) if internal else None
        market_value = float(consensus["value"]) if consensus else None
        difference_pct = None
        if internal_value is not None and market_value not in {None, 0.0}:
            difference_pct = (internal_value - market_value) / abs(market_value) * 100
        item = {
            "period": row.get("horizon"),
            "metric_label": "归母净利润",
            "our_value": internal_value,
            "market_value": market_value,
            "unit": (internal or consensus or {}).get("unit"),
            "difference_pct": difference_pct,
            "market_provider": (
                _provider_label(consensus.get("provider")) if consensus else None
            ),
            "market_as_of": consensus.get("as_of_date") if consensus else None,
            "market_source_title": consensus.get("source_title") if consensus else None,
        }
        comparison_rows.append(item)
        if difference_pct is not None and (
            largest_gap is None
            or abs(difference_pct) > abs(float(largest_gap["difference_pct"]))
        ):
            largest_gap = item
        if consensus:
            key = (
                str(item["market_provider"] or ""),
                str(item["market_as_of"] or ""),
                str(item["market_source_title"] or ""),
            )
            if key not in seen_sources:
                seen_sources.add(key)
                source_index.append({
                    "provider": item["market_provider"],
                    "as_of_date": item["market_as_of"],
                    "source_title": item["market_source_title"],
                    "source_ref": consensus.get("source_ref"),
                })

    model_reference_values: list[dict[str, Any]] = []
    wanted_fragments = (
        "现金流价值", "保持当前PB", "目标市值", "隐含归母净利润",
    )
    for run in model_runs:
        if run.get("skill_name") != "company_valuation_modeling":
            continue
        for output in run.get("outputs") or []:
            name = str(output.get("output_name") or "")
            if not any(fragment in name for fragment in wanted_fragments):
                continue
            model_reference_values.append({
                "model_name": run.get("model_name"),
                "output_name": name,
                "value_num": output.get("value_num"),
                "range_low": output.get("range_low"),
                "range_high": output.get("range_high"),
                "unit": output.get("unit"),
                "period": output.get("period_or_as_of_date"),
                "role": run.get("model_role"),
                "conclusion": output.get("conclusion"),
            })

    trade_zones: list[dict[str, Any]] = []
    for metric, per_share_metric, label in (
        ("pb", "bps_mrq", "PB历史带"),
        ("pe_ttm", "eps_ttm", "PE历史带"),
    ):
        band_key = "pb_price_band" if metric == "pb" else "pe_price_band"
        band = asset_return.get(band_key) or {}
        stats = band.get("statistics") or {}
        per_share = current_metrics.get(per_share_metric)
        if not stats or not per_share or float(per_share.get("value_num") or 0) <= 0:
            continue
        base = float(per_share["value_num"])
        trade_zones.append({
            "label": label,
            "basis_metric": per_share_metric,
            "basis_value": base,
            "basis_unit": per_share.get("unit"),
            "q20_price": base * float(stats["q20"]),
            "median_price": base * float(stats["median"]),
            "q80_price": base * float(stats["q80"]),
            "sample_size": stats.get("sample_size"),
            "provider": per_share.get("provider_label"),
            "as_of_date": per_share.get("as_of_date"),
            "applicability": (
                "历史盈利低基数使PE上沿明显失真；低位和中位仅作辅助，80%分位不作为卖出阈值。"
                if metric == "pe_ttm"
                and float(stats["q80"]) / float(stats["median"]) > 2.5
                else "估值分位可作历史位置参照，仍需经营与现金流确认。"
            ),
        })

    current_snapshot = []
    for metric, label, unit in (
        ("close", "收盘价", "元/股"),
        ("market_cap_cny", "总市值", "亿元人民币"),
        ("pe_ttm", "滚动市盈率", "倍"),
        ("pb", "市净率", "倍"),
        ("roe", "滚动净资产收益率", "%"),
        ("roa", "滚动总资产收益率", "%"),
    ):
        row = current_metrics.get(metric)
        if row and row.get("value_num") is not None:
            current_snapshot.append({
                "metric_name": metric,
                "label": label,
                "value_num": float(row["value_num"]),
                "unit": unit,
                "provider": row.get("provider_label"),
                "as_of_date": row.get("as_of_date"),
            })

    if largest_gap and abs(float(largest_gap["difference_pct"])) >= 20:
        direction = "低于" if float(largest_gap["difference_pct"]) < 0 else "高于"
        difference_conclusion = (
            f"存在较大分歧：{largest_gap['period']}内部归母净利润"
            f"{direction}市场一致预期约{abs(float(largest_gap['difference_pct'])):.0f}%。"
        )
    elif largest_gap:
        difference_conclusion = (
            f"分歧目前有限：最大归母净利润差异约"
            f"{abs(float(largest_gap['difference_pct'])):.0f}%。"
        )
    else:
        difference_conclusion = "缺少可同口径对账的内部预测与市场一致预期，暂不判断分歧大小。"

    return {
        "ready": True,
        **configured,
        "current_snapshot": current_snapshot,
        "comparison_rows": comparison_rows,
        "difference_conclusion": difference_conclusion,
        "model_reference_values": model_reference_values[:6],
        "trade_zones": trade_zones,
        "source_index": source_index,
        "trade_zone_boundary": (
            "价格区间按最新EPS/BPS乘以五年历史估值分位换算，只是观察区，"
            "不是目标价或无条件买卖建议；必须同时满足对应的经营和现金流触发条件。"
        ),
    }


def peer_asset_return_rows(
    research_company_ids: list[int],
    *,
    db_path: str | Path = DB_PATH,
) -> list[dict[str, Any]]:
    """Return one latest, source-preserving asset-return snapshot per canonical peer."""
    company_ids = sorted({int(value) for value in research_company_ids if int(value) > 0})[:200]
    path = Path(db_path)
    if not company_ids or not path.is_file():
        return []
    conn = connect(path, readonly=True)
    try:
        placeholders = ",".join("?" for _ in company_ids)
        securities = [dict(row) for row in conn.execute(
            f"""SELECT DISTINCT s.*
                   FROM financial_security s
                   JOIN financial_security_company_link l ON l.security_id=s.id
                  WHERE l.research_company_id IN ({placeholders})""",
            company_ids,
        )]
        if not securities:
            return []
        security_ids = [int(row["id"]) for row in securities]
        security_placeholders = ",".join("?" for _ in security_ids)
        wanted = ("pb", "roe", "roa", "roic", "debt_ratio", "total_assets", "book_value", "total_equity")
        metric_placeholders = ",".join("?" for _ in wanted)
        observations = [dict(row) for row in conn.execute(
            f"""SELECT o.*,ss.title AS source_title,ss.source_ref
                   FROM financial_observation o
                   LEFT JOIN financial_source_snapshot ss ON ss.id=o.source_snapshot_id
                  WHERE o.security_id IN ({security_placeholders})
                    AND o.metric_name IN ({metric_placeholders})
                  ORDER BY o.security_id,o.metric_name,o.as_of_date,o.id""",
            (*security_ids, *wanted),
        )]
        grouped: dict[int, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        for row in observations:
            grouped[int(row["security_id"])][str(row["metric_name"])].append(row)
        rows: list[dict[str, Any]] = []
        for security in securities:
            metrics = grouped.get(int(security["id"]), {})
            selected = {
                "pb": _latest(metrics.get("pb", []), fact_types={"market"}),
                "roe": _latest(metrics.get("roe", []), fact_types={"market", "actual"}),
                "roa": _latest(metrics.get("roa", []), fact_types={"market", "actual"}),
                "roic": _latest(metrics.get("roic", []), fact_types={"actual"}),
                "debt_ratio": _latest(metrics.get("debt_ratio", []), fact_types={"actual"}),
            }
            assets = _latest(metrics.get("total_assets", []), fact_types={"actual"})
            equity = _latest(metrics.get("book_value", []) + metrics.get("total_equity", []), fact_types={"actual"})
            multiplier = None
            if assets and equity and float(equity.get("value_num") or 0) > 0:
                multiplier = float(assets["value_num"]) / float(equity["value_num"])
            if not any(selected.values()) and multiplier is None:
                continue
            as_of_dates = [str(value.get("as_of_date") or "") for value in selected.values() if value]
            rows.append({
                "research_company_id": security.get("research_company_id"),
                "canonical_name": security.get("canonical_name"),
                "ticker": security.get("ticker"), "market": security.get("market"),
                **selected, "equity_multiplier": multiplier,
                "latest_as_of_date": max(as_of_dates) if as_of_dates else None,
            })
        return sorted(rows, key=lambda row: str(row.get("canonical_name") or ""))
    finally:
        conn.close()


def company_current_metrics_batch(
    research_company_ids: list[int] | tuple[int, ...] | set[int],
    *,
    db_path: str | Path = DB_PATH,
) -> dict[int, dict[str, Any]]:
    """Read current company-list metrics in one read-only financial DB pass.

    The company index can contain hundreds of rows.  Calling ``company_bundle``
    once per card would repeatedly open SQLite and load model ledgers that the
    list does not display.  This lightweight view keeps the same provider and
    field-priority rules as the company page, but only reads the current metric
    subset needed by the index.
    """
    company_ids = sorted({int(value) for value in research_company_ids})
    path = Path(db_path)
    if not company_ids or not path.is_file():
        return {}

    conn = connect(path, readonly=True)
    try:
        company_placeholders = ",".join("?" for _ in company_ids)
        security_rows = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT COALESCE(l.research_company_id, s.research_company_id)
                           AS linked_company_id,
                       s.*
                  FROM financial_security s
                  LEFT JOIN financial_security_company_link l
                    ON l.security_id=s.id
                 WHERE COALESCE(l.research_company_id, s.research_company_id)
                       IN ({company_placeholders})
                 ORDER BY linked_company_id,
                          CASE
                            WHEN s.research_company_id=
                                 COALESCE(l.research_company_id,
                                          s.research_company_id)
                            THEN 0 ELSE 1
                          END,
                          s.id
                """,
                company_ids,
            )
        ]
        security_by_company: dict[int, dict[str, Any]] = {}
        for row in security_rows:
            company_id = int(row["linked_company_id"])
            security_by_company.setdefault(company_id, row)
        if not security_by_company:
            return {}

        security_ids = [
            int(row["id"]) for row in security_by_company.values()
        ]
        security_placeholders = ",".join("?" for _ in security_ids)
        metric_names = (
            "pe_ttm", "pb", "roe", "roa", "eps_ttm",
            "market_cap_cny", "market_cap_usd",
        )
        metric_placeholders = ",".join("?" for _ in metric_names)
        observations = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT o.*, ss.title AS source_title,
                       ss.publisher AS source_publisher,
                       ss.source_channel, ss.source_ref
                  FROM financial_observation o
                  LEFT JOIN financial_source_snapshot ss
                    ON ss.id=o.source_snapshot_id
                 WHERE o.security_id IN ({security_placeholders})
                   AND o.metric_name IN ({metric_placeholders})
                 ORDER BY o.security_id, o.metric_name,
                          o.as_of_date, o.id
                """,
                (*security_ids, *metric_names),
            )
        ]
        grouped: dict[int, dict[str, list[dict[str, Any]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for row in observations:
            grouped[int(row["security_id"])][row["metric_name"]].append(row)

        result: dict[int, dict[str, Any]] = {}
        for company_id, security in security_by_company.items():
            metric_view = _current_metrics_view(
                grouped.get(int(security["id"]), {})
            )
            result[company_id] = {
                "security": security,
                "current_metrics": metric_view,
            }
        return result
    finally:
        conn.close()


def company_page_summaries_batch(
    research_company_ids: list[int] | tuple[int, ...] | set[int],
    *,
    db_path: str | Path = DB_PATH,
) -> dict[int, dict[str, Any]]:
    """Read every financial field used by industry company cards in one pass.

    Loading a full ``company_bundle`` per row also loads model ledgers that
    industry pages do not render and repeats projection setup after cutover.
    Existing selection helpers preserve provider priority, period identity and
    field-level provenance.
    """
    company_ids = sorted({int(value) for value in research_company_ids})
    path = Path(db_path)
    if not company_ids or not path.is_file():
        return {}

    conn = connect(path, readonly=True)
    try:
        company_placeholders = ",".join("?" for _ in company_ids)
        security_rows = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT COALESCE(l.research_company_id, s.research_company_id)
                           AS linked_company_id,
                       s.*
                  FROM financial_security s
                  LEFT JOIN financial_security_company_link l
                    ON l.security_id=s.id
                 WHERE COALESCE(l.research_company_id, s.research_company_id)
                       IN ({company_placeholders})
                 ORDER BY linked_company_id,
                          CASE
                            WHEN s.research_company_id=
                                 COALESCE(l.research_company_id,
                                          s.research_company_id)
                            THEN 0 ELSE 1
                          END,
                          s.id
                """,
                company_ids,
            )
        ]
        security_by_company: dict[int, dict[str, Any]] = {}
        for row in security_rows:
            company_id = int(row["linked_company_id"])
            security_by_company.setdefault(company_id, row)
        if not security_by_company:
            return {}

        security_ids = [int(row["id"]) for row in security_by_company.values()]
        security_placeholders = ",".join("?" for _ in security_ids)
        metric_names = tuple(sorted({
            "close", "pe_ttm", "pe_forward", "pb", "ps_ttm", "ev_ebitda",
            "market_cap", "market_cap_cny", "market_cap_usd",
            "roe", "roa", "eps", "eps_ttm", "bps_mrq",
            "revenue", "net_income", "revenue_yoy", "net_income_yoy",
            "gross_margin", "net_margin", "operating_cash_flow",
        }))
        metric_placeholders = ",".join("?" for _ in metric_names)
        observations = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT o.*, ss.title AS source_title,
                       ss.publisher AS source_publisher,
                       ss.source_channel, ss.source_ref
                  FROM financial_observation o
                  LEFT JOIN financial_source_snapshot ss
                    ON ss.id=o.source_snapshot_id
                 WHERE o.security_id IN ({security_placeholders})
                   AND o.metric_name IN ({metric_placeholders})
                 ORDER BY o.security_id, o.metric_name,
                          o.period_end, o.as_of_date, o.id
                """,
                (*security_ids, *metric_names),
            )
        ]
        grouped: dict[int, dict[str, list[dict[str, Any]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for row in observations:
            grouped[int(row["security_id"])][str(row["metric_name"])].append(row)

        result: dict[int, dict[str, Any]] = {}
        for company_id, security in security_by_company.items():
            metrics = grouped.get(int(security["id"]), {})
            result[company_id] = {
                "security": security,
                "current_metrics": _current_metrics_view(metrics),
                "historical_table": _historical_table(metrics),
                "forecast_table": _forecast_table(metrics),
            }
        return result
    finally:
        conn.close()


def company_bundle(research_company_id: int, *, db_path: str | Path = DB_PATH) -> dict[str, Any] | None:
    path = Path(db_path)
    if not path.is_file():
        return None
    conn = connect(path, readonly=True)
    try:
        security = conn.execute(
            """SELECT s.* FROM financial_security s
                 LEFT JOIN financial_security_company_link l ON l.security_id=s.id
                WHERE l.research_company_id=? OR s.research_company_id=?
                ORDER BY CASE WHEN s.research_company_id=? THEN 0 ELSE 1 END,s.id LIMIT 1""",
            (int(research_company_id), int(research_company_id), int(research_company_id)),
        ).fetchone()
        if security is None:
            return None
        security_dict = dict(security)
        observations = [dict(row) for row in conn.execute(
            """SELECT o.*,ss.title AS source_title,ss.publisher AS source_publisher,
                      ss.source_channel,ss.source_ref
                 FROM financial_observation o
                 LEFT JOIN financial_source_snapshot ss ON ss.id=o.source_snapshot_id
                WHERE o.security_id=? AND o.metric_name IN ({})
                ORDER BY o.metric_name,o.period_end,o.as_of_date,o.id""".format(
                    ",".join("?" for _ in CORE_METRICS)
                ),
            (security_dict["id"], *sorted(CORE_METRICS)),
        )]
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in observations:
            grouped[row["metric_name"]].append(row)
        model_runs = [dict(row) for row in conn.execute(
            """SELECT * FROM financial_model_run
                WHERE security_id=? AND status<>'superseded'
                ORDER BY created_at DESC,id DESC""",
            (security_dict["id"],),
        )]
        for run in model_runs:
            run["assumptions"] = _safe_json_object(run.get("assumptions_json"))
            run["inputs"] = [dict(row) for row in conn.execute(
                "SELECT * FROM financial_model_input WHERE model_run_id=? ORDER BY id", (run["id"],)
            )]
            for item in run["inputs"]:
                item["source_label"] = _public_model_source_label(
                    item.get("source_ref"), item.get("input_type")
                )
            run["outputs"] = [dict(row) for row in conn.execute(
                "SELECT * FROM financial_model_output WHERE model_run_id=? ORDER BY id", (run["id"],)
            )]
            for item in run["outputs"]:
                item["substitution"] = _public_model_substitution(
                    item.get("substitution")
                )
            run["reconciliations"] = [dict(row) for row in conn.execute(
                "SELECT * FROM financial_reconciliation WHERE model_run_id=? ORDER BY id", (run["id"],)
            )]
            for item in run["reconciliations"]:
                item["benchmark_source_label"] = {
                    "consensus": "一致预期快照",
                    "guidance": "公司指引",
                    "market_implied": "估值日市场快照",
                    "peer": "可比公司样本",
                    "historical": "历史估值样本",
                    "sell_side_report": "近期卖方报告",
                }.get(str(item.get("benchmark_type") or ""), "外部对账来源")
        implied_by_identity: dict[tuple[str, str, str], dict[str, Any]] = {}
        for metric_name, metric_rows in grouped.items():
            for row in metric_rows:
                if (
                    row.get("fact_type") != "implied"
                    or row.get("quality_status")
                    in {"superseded", "not_applicable"}
                ):
                    continue
                identity = (
                    metric_name,
                    _period_key(row),
                    str(row.get("scenario_name") or "reported"),
                )
                if (
                    identity not in implied_by_identity
                    or _row_priority(row) > _row_priority(implied_by_identity[identity])
                ):
                    implied_by_identity[identity] = row
        implied_expectations = [
            {
                "metric_name": row["metric_name"],
                "metric_label": (
                    str(row.get("raw_feature_name") or "").strip()
                    or IMPLIED_METRIC_LABELS.get(row["metric_name"], row["metric_name"])
                ),
                "value_num": row.get("value_num"),
                "value_text": row.get("value_text"),
                "unit": row.get("unit"),
                "period": _period_key(row),
                "as_of_date": row.get("as_of_date"),
                "provider": row.get("provider"),
                "formula": row.get("formula"),
                "scenario_name": _public_scenario_label(row.get("scenario_name")),
                "source_title": row.get("source_title"),
            }
            for row in sorted(
                implied_by_identity.values(),
                key=lambda item: (
                    int(item.get("fiscal_year") or 9999),
                    str(item.get("metric_name") or ""),
                    str(item.get("scenario_name") or ""),
                    int(item.get("id") or 0),
                ),
            )
        ]
        observation_implied_keys = {
            (
                str(item.get("metric_name") or ""),
                str(item.get("period") or "")[:4],
            )
            for item in implied_expectations
        }
        implied_expectations.extend(
            item
            for item in _model_implied_expectations(model_runs)
            if (
                str(item.get("metric_name") or ""),
                str(item.get("period") or "")[:4],
            ) not in observation_implied_keys
        )
        metrics_view = dict(grouped)
        historical_table = _historical_table(metrics_view)
        forecast_table = _forecast_table(metrics_view)
        asset_return = _asset_return_view(metrics_view)
        return {
            "security": security_dict,
            "observations": observations,
            "metrics": metrics_view,
            "current_metrics": _current_metrics_view(metrics_view),
            "model_runs": model_runs,
            "valuation_model_runs": [
                run
                for run in model_runs
                if run.get("skill_name") == "company_valuation_modeling"
            ],
            "implied_expectations": implied_expectations,
            "historical_table": historical_table,
            "forecast_table": forecast_table,
            "asset_return": asset_return,
            "valuation_framework": _valuation_framework_view(
                model_runs, metrics_view
            ),
            "scenario_workbench": _scenario_workbench_view(
                model_runs, metrics_view
            ),
            "valuation_summary": _valuation_summary_view(
                model_runs, metrics_view, forecast_table, asset_return
            ),
            "data_boundary": "结构化财务、市场快照、一致预期、内部模型和隐含预期来自独立 financial.db；行业观点仍留在 research.db。",
        }
    finally:
        conn.close()
