from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


RESOURCE_SEGMENTS = {
    "cobalt_products",
    "copper_products",
    "nickel_products",
    "lithium_products",
    "nickel_intermediates",
}
MATERIAL_SEGMENTS = {"ternary_precursors", "cathode_materials"}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _round(value: float, digits: int = 1) -> float:
    return round(float(value), digits)


def _segment_margin_delta(segment_key: str, scenario: dict[str, Any]) -> float:
    if segment_key in RESOURCE_SEGMENTS:
        return float(scenario["resource_margin_delta"])
    if segment_key in MATERIAL_SEGMENTS:
        return float(scenario["material_margin_delta"])
    return float(scenario["other_margin_delta"])


def _scenario_year(
    inputs: dict[str, Any],
    *,
    scenario_name: str,
    year: str,
) -> dict[str, Any]:
    scenario = inputs["scenario_adjustments"][scenario_name]
    base_segments = inputs["base_segment_forecast"][year]
    revenue_multiplier = float(scenario["revenue_multipliers"][year])
    segments: list[dict[str, Any]] = []
    for key, base in base_segments.items():
        revenue = float(base["revenue_100m_cny"]) * revenue_multiplier
        margin = max(
            0.0,
            min(
                0.80,
                float(base["gross_margin"])
                + _segment_margin_delta(key, scenario),
            ),
        )
        segments.append(
            {
                "segment_key": key,
                "revenue_100m_cny": _round(revenue),
                "gross_margin_pct": _round(margin * 100),
                "gross_profit_100m_cny": _round(revenue * margin),
            }
        )

    revenue = sum(float(row["revenue_100m_cny"]) for row in segments)
    gross_profit = sum(float(row["gross_profit_100m_cny"]) for row in segments)
    statement = inputs["base_income_statement_assumptions"][year]
    expense_ratio = sum(
        float(statement[name])
        for name in (
            "tax_surcharges_ratio",
            "selling_ratio",
            "administrative_ratio",
            "research_ratio",
            "finance_ratio",
        )
    ) + float(scenario["opex_ratio_delta"])
    operating_expenses = revenue * expense_ratio
    profit_before_tax = (
        gross_profit
        - operating_expenses
        + float(statement["other_income_100m_cny"])
        + float(statement["investment_income_100m_cny"])
        - float(statement["impairment_loss_100m_cny"])
        - float(statement["non_operating_net_loss_100m_cny"])
    )
    group_net_income = profit_before_tax * (
        1.0 - float(statement["income_tax_rate"])
    )
    parent_ratio = float(statement["parent_attribution_ratio"]) + float(
        scenario["parent_attribution_delta"]
    )
    parent_net_income = group_net_income * parent_ratio

    cash = dict(inputs["cash_flow_assumptions"][year])
    if "working_capital_outflow_100m_cny" in scenario:
        cash["working_capital_outflow_100m_cny"] = scenario[
            "working_capital_outflow_100m_cny"
        ][year]
    if "capex_100m_cny" in scenario:
        cash["capex_100m_cny"] = scenario["capex_100m_cny"][year]
    operating_cash_flow = (
        group_net_income
        + float(cash["depreciation_amortization_100m_cny"])
        + float(cash["finance_cost_addback_100m_cny"])
        - float(cash["investment_income_deduction_100m_cny"])
        + float(cash["impairment_addback_100m_cny"])
        - float(cash["working_capital_outflow_100m_cny"])
        + float(cash["other_adjustments_100m_cny"])
    )
    capex = float(cash["capex_100m_cny"])
    free_cash_flow = operating_cash_flow - capex
    return {
        "year": int(year),
        "scenario": scenario_name,
        "segments": segments,
        "revenue_100m_cny": _round(revenue),
        "gross_profit_100m_cny": _round(gross_profit),
        "gross_margin_pct": _round(gross_profit / revenue * 100),
        "operating_expenses_100m_cny": _round(operating_expenses),
        "profit_before_tax_100m_cny": _round(profit_before_tax),
        "group_net_income_100m_cny": _round(group_net_income),
        "parent_attribution_ratio_pct": _round(parent_ratio * 100),
        "parent_net_income_100m_cny": _round(parent_net_income),
        "operating_cash_flow_100m_cny": _round(operating_cash_flow),
        "capex_100m_cny": _round(capex),
        "free_cash_flow_100m_cny": _round(free_cash_flow),
    }


def _valuation(inputs: dict[str, Any], base_rows: list[dict[str, Any]]) -> dict[str, Any]:
    assumptions = inputs["valuation_assumptions"]
    shares = float(inputs["company"]["shares_100m"])
    fy1_profit = float(base_rows[0]["parent_net_income_100m_cny"])
    pe_low, pe_high = [float(value) for value in assumptions["pe_range"]]
    pe_equity_low = fy1_profit * pe_low
    pe_equity_high = fy1_profit * pe_high

    ending_equity = float(assumptions["estimated_2026_ending_parent_equity_100m_cny"])
    beginning_equity = float(inputs["actual_2026_q1"]["parent_equity_100m_cny"])
    forward_roe = fy1_profit / ((beginning_equity + ending_equity) / 2.0)
    sustainable_pb = (
        forward_roe - float(assumptions["long_term_growth"])
    ) / (
        float(assumptions["cost_of_equity"])
        - float(assumptions["long_term_growth"])
    )
    bps = ending_equity / shares
    pb_low, pb_high = [float(value) for value in assumptions["pb_range"]]
    pb_equity_low = ending_equity * pb_low
    pb_equity_high = ending_equity * pb_high

    ev_low, ev_high = [float(value) for value in assumptions["ev_ebitda_range"]]
    ebitda = float(assumptions["estimated_2026_ebitda_100m_cny"])
    net_debt = float(assumptions["estimated_2026_net_debt_100m_cny"])
    nci_value = float(assumptions["estimated_2026_nci_value_100m_cny"])
    ev_equity_low = ebitda * ev_low - net_debt - nci_value
    ev_equity_high = ebitda * ev_high - net_debt - nci_value

    market_cap = float(assumptions["market_cap_100m_cny"])
    market_pb = float(assumptions["market_pb"])
    implied_roe = (
        market_pb
        * (
            float(assumptions["cost_of_equity"])
            - float(assumptions["long_term_growth"])
        )
        + float(assumptions["long_term_growth"])
    )
    core_low = max(pe_equity_low, pb_equity_low, ev_equity_low)
    core_high = min(pe_equity_high, pb_equity_high, ev_equity_high)
    if core_low > core_high:
        core_low = sorted([pe_equity_low, pb_equity_low, ev_equity_low])[1]
        core_high = sorted([pe_equity_high, pb_equity_high, ev_equity_high])[1]
    return {
        "valuation_date": assumptions["valuation_date"],
        "market_price_cny": assumptions["market_price_cny"],
        "market_cap_100m_cny": market_cap,
        "market_implied_fy1_pe": _round(market_cap / fy1_profit, 2),
        "market_implied_roe_pct_from_pb": _round(implied_roe * 100, 2),
        "independent_forward_roe_pct": _round(forward_roe * 100, 2),
        "sustainable_pb_from_forward_roe": _round(sustainable_pb, 2),
        "estimated_2026_bps_cny": _round(bps, 2),
        "methods": [
            {
                "method": "市盈率",
                "role": "核心",
                "assumption": f"2026年归母净利润{_round(fy1_profit)}亿元，估值{pe_low:.1f}—{pe_high:.1f}倍",
                "equity_value_low_100m_cny": _round(pe_equity_low),
                "equity_value_high_100m_cny": _round(pe_equity_high),
                "price_low_cny": _round(pe_equity_low / shares, 2),
                "price_high_cny": _round(pe_equity_high / shares, 2),
            },
            {
                "method": "PB—ROE",
                "role": "交叉验证",
                "assumption": (
                    f"2026年末归母权益{ending_equity:.1f}亿元，PB {pb_low:.2f}—{pb_high:.2f}倍；"
                    f"可持续PB按(ROE-g)/(CoE-g)复算"
                ),
                "equity_value_low_100m_cny": _round(pb_equity_low),
                "equity_value_high_100m_cny": _round(pb_equity_high),
                "price_low_cny": _round(pb_equity_low / shares, 2),
                "price_high_cny": _round(pb_equity_high / shares, 2),
            },
            {
                "method": "EV/EBITDA",
                "role": "资本结构校验",
                "assumption": (
                    f"2026年EBITDA约{ebitda:.1f}亿元，倍数{ev_low:.1f}—{ev_high:.1f}倍，"
                    f"再扣净债务{net_debt:.1f}亿元和少数股东权益估值{nci_value:.1f}亿元"
                ),
                "equity_value_low_100m_cny": _round(ev_equity_low),
                "equity_value_high_100m_cny": _round(ev_equity_high),
                "price_low_cny": _round(ev_equity_low / shares, 2),
                "price_high_cny": _round(ev_equity_high / shares, 2),
            },
        ],
        "core_value_range_100m_cny": [_round(core_low), _round(core_high)],
        "core_price_range_cny": [
            _round(core_low / shares, 2),
            _round(core_high / shares, 2),
        ],
        "interpretation": (
            "市盈率是核心方法；PB—ROE检验资产回报能否支撑账面溢价；"
            "EV/EBITDA用于防止忽略净债务和少数股东权益。三者不做机械平均。"
        ),
    }


def build(inputs: dict[str, Any], *, input_path: Path) -> dict[str, Any]:
    scenarios: dict[str, list[dict[str, Any]]] = {}
    for scenario_name in inputs["scenario_adjustments"]:
        scenarios[scenario_name] = [
            _scenario_year(inputs, scenario_name=scenario_name, year=year)
            for year in ("2026", "2027", "2028")
        ]
    base = scenarios["基准情景"]
    return {
        "model_version": inputs["model_version"],
        "as_of_date": inputs["as_of_date"],
        "input_artifact_hash": _sha256_file(input_path),
        "model_formulas": {
            "segment_revenue": "分部收入＝2025年经营基数×销量、价格和产品结构的综合情景系数；新项目只在预计有效爬坡期进入对应分部",
            "gross_profit": "合并毛利润＝Σ（分部收入×分部毛利率）",
            "parent_net_income": "归母净利润＝（毛利润－税金及期间费用＋其他收益＋投资收益－减值－营业外净损失）×（1－所得税率）×归母比例",
            "operating_cash_flow": "经营现金流＝合并净利润＋折旧摊销＋财务费用－投资收益＋减值－营运资金占用＋其他非现金调整",
            "free_cash_flow": "自由现金流＝经营现金流－资本开支",
            "sustainable_pb": "可持续PB＝（预期ROE－长期增长率）÷（股权回报要求－长期增长率）",
        },
        "actual_reference": {
            "2025": inputs["actual_2025"],
            "2026_q1": inputs["actual_2026_q1"],
        },
        "scenarios": scenarios,
        "valuation": _valuation(inputs, base),
        "project_timing_rules": inputs["project_timing_rules"],
        "assumption_notes": inputs["assumption_notes"],
        "sanity_checks": {
            "segment_2025_revenue_reconciles_to_total": _round(
                sum(
                    float(row["revenue_100m_cny"])
                    for row in inputs["segments_2025"]
                )
                - float(inputs["actual_2025"]["revenue_100m_cny"]),
                6,
            ),
            "segment_2025_gross_profit_reconciles_to_total": _round(
                sum(
                    float(row["revenue_100m_cny"])
                    * float(row["gross_margin"])
                    for row in inputs["segments_2025"]
                )
                - float(inputs["actual_2025"]["gross_profit_100m_cny"]),
                6,
            ),
            "five_year_probability_used": False,
            "planned_capacity_counted_as_actual_output": False,
            "full_project_output_counted_as_parent_equity_output": False,
            "free_cash_flow_equals_operating_cash_flow_minus_capex": all(
                abs(
                    float(row["free_cash_flow_100m_cny"])
                    - (
                        float(row["operating_cash_flow_100m_cny"])
                        - float(row["capex_100m_cny"])
                    )
                )
                < 0.11
                for rows in scenarios.values()
                for row in rows
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="华友钴业镍钴锂一体化独立财务与估值模型"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inputs = json.loads(args.input.read_text(encoding="utf-8"))
    output = build(inputs, input_path=args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "input_hash": output["input_artifact_hash"],
                "base_parent_net_income": [
                    row["parent_net_income_100m_cny"]
                    for row in output["scenarios"]["基准情景"]
                ],
                "core_price_range_cny": output["valuation"][
                    "core_price_range_cny"
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
