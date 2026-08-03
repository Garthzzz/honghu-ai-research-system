from __future__ import annotations

"""Bind Run16 assumptions to company-specific historical facts and PE bands.

Only Wind actual/market observations from ``financial.db`` are read.  The
script never reads consensus, guidance or prior internal model observations,
so the independent-before-consensus freeze remains intact.
"""

import argparse
import json
import math
import statistics
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from tools.financial.read_models import company_bundle


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    return ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)


def _annual(
    observations: Iterable[dict[str, Any]], metric: str
) -> dict[str, float]:
    selected: dict[str, tuple[int, float]] = {}
    for row in observations:
        if row.get("metric_name") != metric or row.get("provider") != "wind":
            continue
        if row.get("fact_type") != "actual" or row.get("frequency") != "annual":
            continue
        period = str(row.get("period_end") or "")
        if period < "2021-12-31" or period > "2025-12-31":
            continue
        value = _finite(row.get("value_num"))
        if value is None:
            continue
        identity = int(row.get("id") or 0)
        if period not in selected or identity > selected[period][0]:
            selected[period] = (identity, value)
    return {period: value for period, (_, value) in sorted(selected.items())}


def _ratio(numerator: dict[str, float], denominator: dict[str, float]) -> list[float]:
    return [
        numerator[period] / denominator[period] * 100.0
        for period in sorted(set(numerator) & set(denominator))
        if denominator[period] > 0
    ]


def _growth(series: dict[str, float]) -> list[float]:
    values: list[float] = []
    previous: float | None = None
    for value in series.values():
        if previous is not None and previous > 0:
            values.append((value / previous - 1.0) * 100.0)
        previous = value
    return values


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": round(min(values), 2),
        "median": round(statistics.median(values), 2),
        "max": round(max(values), 2),
    }


def _base_values(item: dict[str, Any]) -> str:
    values = item.get("values", {}).get("base", {})
    return "/".join(f"{float(values[str(year)]):.2f}%" for year in (2026, 2027, 2028))


def _evidence_bound_base(
    company: dict[str, Any], metric: str, stats: dict[str, Any]
) -> dict[str, Any] | None:
    """Keep the base case inside the independently observed historical range.

    A value outside history is not automatically wrong, but it needs a
    company-specific quantitative operating bridge.  Run16 does not have a
    complete volume/price/capacity bridge for every company, so the base case
    is capped at the observed maximum and the uncapped value remains in the
    upside (or downside for capex) stress case.
    """

    if stats.get("count", 0) <= 0 or _finite(stats.get("max")) is None:
        return None
    item = company["forecast_assumptions"][metric]
    values = item["values"]
    original = item.setdefault(
        "pre_evidence_base_values", deepcopy(values.get("base", {}))
    )
    historical_max = float(stats["max"])
    changes: list[dict[str, Any]] = []
    higher_is_operating_upside = metric in {
        "revenue_growth_pct",
        "gross_margin_pct",
        "parent_net_margin_pct",
        "ocf_margin_pct",
        "total_assets_growth_pct",
    }
    for year in (2026, 2027, 2028):
        key = str(year)
        uncapped = float(original[key])
        bounded = min(uncapped, historical_max)
        values["base"][key] = round(bounded, 2)
        if uncapped > historical_max + 1e-9:
            changes.append(
                {
                    "year": year,
                    "uncapped_base": uncapped,
                    "evidence_bound_base": round(bounded, 2),
                    "historical_max": historical_max,
                    "difference_pp": round(uncapped - historical_max, 2),
                }
            )
            if higher_is_operating_upside:
                values["upside"][key] = max(
                    float(values["upside"][key]), uncapped
                )
                values["downside"][key] = min(
                    float(values["downside"][key]), bounded
                )
            else:
                # Higher capex is an adverse cash-flow stress, not upside.
                values["downside"][key] = max(
                    float(values["downside"][key]), uncapped
                )
                values["upside"][key] = min(
                    float(values["upside"][key]), bounded
                )
    return {
        "policy": "基准不越过FY2021—FY2025已观察上沿；无定量经营桥的超历史值保留在压力情景",
        "changes": changes,
    }


def _project_base_profit(company: dict[str, Any], revenue_2025: float, net_income_2025: float) -> dict[str, float]:
    revenue = revenue_2025
    result = {"2025": net_income_2025}
    assumptions = company["forecast_assumptions"]
    for year in (2026, 2027, 2028):
        key = str(year)
        revenue *= 1.0 + float(
            assumptions["revenue_growth_pct"]["values"]["base"][key]
        ) / 100.0
        margin = float(
            assumptions["parent_net_margin_pct"]["values"]["base"][key]
        ) / 100.0
        result[key] = revenue * margin
    return result


def _enrich_company(company: dict[str, Any]) -> None:
    bundle = company_bundle(int(company["company_id"]))
    observations = bundle.get("observations", [])
    revenue = _annual(observations, "revenue")
    assets = _annual(observations, "total_assets")
    gross = list(_annual(observations, "gross_margin").values())
    net = list(_annual(observations, "net_margin").values())
    roe = list(_annual(observations, "roe").values())
    ocf = _annual(observations, "operating_cash_flow")
    capex = _annual(observations, "capex")
    net_income = _annual(observations, "net_income")
    pe_by_period: dict[str, tuple[int, float]] = {}
    current_pe: float | None = None
    for row in observations:
        if (
            row.get("metric_name") != "pe_ttm"
            or row.get("provider") != "wind"
            or row.get("fact_type") != "market"
        ):
            continue
        value = _finite(row.get("value_num"))
        if value is None or value <= 0:
            continue
        period = str(row.get("period_end") or row.get("as_of_date") or "")
        if period > "2026-07-30" or period < "2021-01-01":
            continue
        identity = int(row.get("id") or 0)
        if period not in pe_by_period or identity > pe_by_period[period][0]:
            pe_by_period[period] = (identity, value)
        if period == "2026-07-30":
            current_pe = value
    pe_values = [row[1] for row in pe_by_period.values()]
    anchor = {
        "data_contract": "仅使用financial.db中Wind actual/market；未读取一致预期或内部模型",
        "period": "FY2021—FY2025；PE截至2026-07-30",
        "revenue_growth_pct": _stats(_growth(revenue)),
        "gross_margin_pct": _stats(gross),
        "net_margin_pct": _stats(net),
        "ocf_margin_pct": _stats(_ratio(ocf, revenue)),
        "capex_margin_pct": _stats(_ratio(capex, revenue)),
        "total_assets_growth_pct": _stats(_growth(assets)),
        "roe_pct": _stats(roe),
        "pe_ttm": {
            "count": len(pe_values),
            "q25": round(_pct(pe_values, 0.25), 2) if pe_values else None,
            "median": round(_pct(pe_values, 0.50), 2) if pe_values else None,
            "q75": round(_pct(pe_values, 0.75), 2) if pe_values else None,
            "current": round(current_pe, 2) if current_pe is not None else None,
        },
    }
    company["quantitative_anchor"] = anchor
    forecast = company["forecast_assumptions"]
    mapping = {
        "revenue_growth_pct": "revenue_growth_pct",
        "gross_margin_pct": "gross_margin_pct",
        "parent_net_margin_pct": "net_margin_pct",
        "ocf_margin_pct": "ocf_margin_pct",
        "capex_margin_pct": "capex_margin_pct",
        "total_assets_growth_pct": "total_assets_growth_pct",
    }
    for metric, anchor_key in mapping.items():
        stats = anchor[anchor_key]
        prefix = f"financial.db Wind FY2021—FY2025 {anchor_key}；"
        prior_source = str(forecast[metric].get("source_ref") or "")
        # Re-running the enrichment step is part of the normal repair loop.
        # Keep the assumption ledger idempotent instead of prepending the same
        # financial.db anchor on every run.
        while prior_source.startswith(prefix):
            prior_source = prior_source[len(prefix) :]
        forecast[metric]["source_ref"] = prefix + prior_source
        adjustment = _evidence_bound_base(company, metric, stats)
        adjustment_note = ""
        if adjustment and adjustment["changes"]:
            changed = "、".join(
                f"FY{row['year']}由{row['uncapped_base']:.2f}%降至{row['evidence_bound_base']:.2f}%"
                for row in adjustment["changes"]
            )
            adjustment_note = (
                f" 由于缺少足以证明超历史上沿的量价/产能/项目桥，{changed}；"
                "原值仅保留在压力情景。"
            )
        forecast[metric]["rationale"] = (
            f"该公司历史样本{stats.get('count', 0)}期，区间"
            f"{stats.get('min')}%—{stats.get('max')}%，中位数{stats.get('median')}%；"
            f"独立基准FY2026—FY2028取{_base_values(forecast[metric])}。"
            f"{adjustment_note}基准只使用已观察历史边界和公司经营证据，不读取外部一致预期。"
        )
        forecast[metric]["operating_driver_bridge"] = {
            "company": company["name"],
            "economic_mechanism": company["economic_mechanism"],
            "metric": metric,
            "historical_observation": deepcopy(stats),
            "base_values": deepcopy(forecast[metric]["values"]["base"]),
            "uncapped_base_values": deepcopy(
                forecast[metric].get("pre_evidence_base_values", {})
            ),
            "evidence_source_ref": forecast[metric]["source_ref"],
            "calculation": {
                "revenue_growth_pct": "收入＝上年收入×(1+收入增速)",
                "gross_margin_pct": "毛利＝收入×毛利率",
                "parent_net_margin_pct": "归母净利润＝收入×归母净利率",
                "ocf_margin_pct": "经营现金流＝收入×经营现金流率",
                "capex_margin_pct": "资本开支＝收入×资本开支率",
                "total_assets_growth_pct": "资产增长候选＝期初总资产×(1+资产增速)",
            }[metric],
            "evidence_bound_policy": adjustment,
        }
    pe = company["valuation_methods"]["pe"]
    pe_anchor = anchor["pe_ttm"]
    revenue_2025 = list(revenue.values())[-1]
    reported_net_income_2025 = list(net_income.values())[-1]
    normalization = company.get("normalization_overrides", {}).get(
        "parent_net_income_100m_cny"
    )
    normalized_net_income_2025 = (
        float(normalization["value"])
        if isinstance(normalization, dict) and _finite(normalization.get("value")) is not None
        else reported_net_income_2025
    )
    profit_path = _project_base_profit(
        company, revenue_2025, normalized_net_income_2025
    )
    profit_cagr = (
        (profit_path["2028"] / normalized_net_income_2025) ** (1.0 / 3.0) - 1.0
    ) * 100.0
    q25 = _finite(pe_anchor.get("q25"))
    median = _finite(pe_anchor.get("median"))
    if q25 is None or median is None:
        low = float(pe["multiple_low"]["value"])
        high = float(pe["multiple_high"]["value"])
    else:
        # A deterministic growth/valuation bridge: the low bound uses 1.0x
        # normalized profit CAGR and the high bound 1.5x, both capped by the
        # company's own historical TTM Q25/median.  It is a valuation policy,
        # not an external fact, and is identical across all 18 companies.
        low = min(q25, max(8.0, profit_cagr))
        high = max(low, min(median, max(low, 1.5 * profit_cagr)))
        pe["multiple_low"]["value"] = round(low, 2)
        pe["multiple_high"]["value"] = round(high, 2)
    source = (
        f"financial.db Wind PE_TTM历史月末{pe_anchor['count']}期，"
        f"Q25/中位/Q75={pe_anchor['q25']}/{pe_anchor['median']}/{pe_anchor['q75']}倍，"
        f"2026-07-30为{pe_anchor['current']}倍"
    )
    pe["multiple_low"]["source_ref"] = source
    pe["multiple_high"]["source_ref"] = source
    pe["multiple_low"]["rationale"] = (
        f"FY2025—FY2028基准归母净利润复合增速{profit_cagr:.2f}%；下限＝min(历史PE_TTM Q25, "
        f"max(8倍, 1.0×利润复合增速))＝{low:.2f}倍。历史TTM只提供上限约束，目标倍数由统一增长桥计算。"
    )
    pe["multiple_high"]["rationale"] = (
        f"FY2025—FY2028基准归母净利润复合增速{profit_cagr:.2f}%；上限＝max(下限, min(历史PE_TTM中位, "
        f"1.5×利润复合增速))＝{high:.2f}倍。未读取卖方目标价。"
    )
    pe["multiple_bridge"] = {
        "formula_low": "min(历史PE_TTM Q25, max(8, 1.0×FY2025—FY2028归母净利润CAGR))",
        "formula_high": "max(下限, min(历史PE_TTM中位, 1.5×FY2025—FY2028归母净利润CAGR))",
        "profit_path_100m_cny": {key: round(value, 2) for key, value in profit_path.items()},
        "profit_cagr_pct": round(profit_cagr, 2),
        "historical_pe_ttm_q25": q25,
        "historical_pe_ttm_median": median,
        "result_low": round(low, 2),
        "result_high": round(high, 2),
        "limitation": "统一PEG式桥只约束拍数，不宣称增长与PE存在稳定线性关系；历史TTM与目标Forward PE仍非完全同口径。",
    }
    # Portfolio scores used to be 90 hand-entered company-level estimates
    # (18 companies x 5 dimensions).  They are now calculated inside the
    # frozen model from a public scorecard, so keeping the old inputs in the
    # active assumption contract would leave two competing score sources.
    for key in (
        "direction_score",
        "quality_score",
        "evidence_score",
        "valuation_score",
        "risk_score",
    ):
        company["portfolio"].pop(key, None)
    company["portfolio"]["scoring_contract"] = (
        "run16.portfolio_scorecard.v2：只由冻结实际值、历史锚、独立三情景预测和价格波动逐项复算；"
        "不再读取手工公司分数"
    )


def build(input_path: Path) -> dict[str, Any]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    for company in payload["companies"]:
        _enrich_company(company)
    payload["quantitative_anchor_contract"] = (
        "所有历史锚只读financial.db中的Wind actual/market；一致预期在独立模型冻结后另行对账。"
        "缺少公司级量价、产能或项目定量桥时，基准情景不得高于FY2021—FY2025已观察上沿；"
        "原超历史值只保留在上行经营情景（高资本开支保留在下行现金流压力情景）。"
        "Forward PE上下限使用统一的FY2025—FY2028正常化利润增速桥，并受公司自身历史PE_TTM"
        "Q25和中位数约束；该桥是研究估值政策，不是外部事实。"
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build(args.input)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(args.output.resolve()), "company_count": len(payload["companies"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
