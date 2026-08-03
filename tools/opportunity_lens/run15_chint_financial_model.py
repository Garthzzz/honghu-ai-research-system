from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _round(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


def _scenario_year(
    inputs: dict[str, Any], scenario_name: str, year: str
) -> dict[str, Any]:
    scenario = inputs["scenarios"][scenario_name][year]
    segments = []
    for row in scenario["segments"]:
        revenue = float(row["revenue_100m_cny"])
        margin = float(row["gross_margin"])
        segments.append(
            {
                "segment": row["segment"],
                "revenue_100m_cny": _round(revenue, 1),
                "gross_margin_pct": _round(margin * 100, 1),
                "gross_profit_100m_cny": _round(revenue * margin, 1),
            }
        )
    revenue = sum(float(row["revenue_100m_cny"]) for row in segments)
    gross_profit = sum(float(row["gross_profit_100m_cny"]) for row in segments)
    operating_deductions = revenue * float(
        scenario["operating_deduction_ratio"]
    )
    profit_before_tax = (
        gross_profit
        - operating_deductions
        + float(scenario["net_other_income_100m_cny"])
        - float(scenario["impairment_100m_cny"])
    )
    group_net_income = profit_before_tax * (
        1.0 - float(scenario["income_tax_rate"])
    )
    parent_net_income = group_net_income * float(
        scenario["parent_attribution_ratio"]
    )

    cash = scenario["cash_flow"]
    operating_cash_flow = (
        group_net_income
        + float(cash["depreciation_amortization_100m_cny"])
        + float(cash["non_cash_provision_100m_cny"])
        - float(cash["working_capital_outflow_100m_cny"])
        + float(cash["other_adjustments_100m_cny"])
    )
    capex = float(cash["fixed_asset_capex_100m_cny"])
    return {
        "year": int(year),
        "scenario": scenario_name,
        "segments": segments,
        "revenue_100m_cny": _round(revenue, 1),
        "gross_profit_100m_cny": _round(gross_profit, 1),
        "gross_margin_pct": _round(gross_profit / revenue * 100, 1),
        "operating_deductions_100m_cny": _round(operating_deductions, 1),
        "profit_before_tax_100m_cny": _round(profit_before_tax, 1),
        "group_net_income_100m_cny": _round(group_net_income, 1),
        "parent_net_income_100m_cny": _round(parent_net_income, 1),
        "parent_attribution_ratio_pct": _round(
            float(scenario["parent_attribution_ratio"]) * 100, 1
        ),
        "operating_cash_flow_100m_cny": _round(operating_cash_flow, 1),
        "fixed_asset_capex_100m_cny": _round(capex, 1),
        "free_cash_flow_100m_cny": _round(operating_cash_flow - capex, 1),
        "working_capital_outflow_100m_cny": _round(
            float(cash["working_capital_outflow_100m_cny"]), 1
        ),
    }


def _valuation(
    inputs: dict[str, Any], base_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    assumptions = inputs["valuation"]
    shares = float(inputs["company"]["shares_100m"])
    fy1_profit = float(base_rows[0]["parent_net_income_100m_cny"])
    market_cap = float(assumptions["market_cap_100m_cny"])
    market_price = float(assumptions["market_price_cny"])

    pe_low, pe_high = [float(value) for value in assumptions["pe_range"]]
    pe_value = [fy1_profit * pe_low, fy1_profit * pe_high]

    ending_equity = float(assumptions["estimated_2026_parent_equity_100m_cny"])
    beginning_equity = float(inputs["actual"]["2025"]["parent_equity_100m_cny"])
    forecast_payout = float(
        assumptions["forecast_cash_dividend_payout_ratio"]
    )
    forecast_cash_dividend = fy1_profit * forecast_payout
    equity_bridge_result = (
        beginning_equity + fy1_profit - forecast_cash_dividend
    )
    if abs(equity_bridge_result - ending_equity) > 0.02:
        raise ValueError(
            "2026年归母净资产与简化权益桥不一致："
            f"{equity_bridge_result:.4f}!={ending_equity:.4f}"
        )
    forward_roe = fy1_profit / ((beginning_equity + ending_equity) / 2)
    cost_of_equity = float(assumptions["cost_of_equity"])
    long_term_growth = float(assumptions["long_term_growth"])
    sustainable_pb = (forward_roe - long_term_growth) / (
        cost_of_equity - long_term_growth
    )
    pb_low, pb_high = [float(value) for value in assumptions["pb_range"]]
    pb_value = [ending_equity * pb_low, ending_equity * pb_high]

    aneng_value = float(assumptions["aneng_100pct_equity_value_100m_cny"])
    aneng_stake = float(assumptions["aneng_stake_after_transaction"])
    aneng_attributable = aneng_value * aneng_stake
    remaining_profit = float(
        assumptions["remaining_business_parent_profit_2026_100m_cny"]
    )
    remain_low, remain_high = [
        float(value) for value in assumptions["remaining_business_pe_range"]
    ]
    sotp_value = [
        aneng_attributable + remaining_profit * remain_low,
        aneng_attributable + remaining_profit * remain_high,
    ]

    method_ranges = {
        "市盈率": pe_value,
        "分部估值": sotp_value,
        "PB—ROE": pb_value,
    }
    core_low = max(values[0] for values in method_ranges.values())
    core_high = min(values[1] for values in method_ranges.values())
    if core_low > core_high:
        raise ValueError(
            "三种估值方法没有重叠区间，不能生成多方法核心价值区间"
        )
    implied_roe = (
        float(assumptions["market_pb"])
        * (cost_of_equity - long_term_growth)
        + long_term_growth
    )

    def method(
        name: str,
        role: str,
        values: list[float],
        basis: str,
    ) -> dict[str, Any]:
        return {
            "method": name,
            "role": role,
            "basis": basis,
            "equity_value_low_100m_cny": _round(values[0], 1),
            "equity_value_high_100m_cny": _round(values[1], 1),
            "price_low_cny": _round(values[0] / shares, 2),
            "price_high_cny": _round(values[1] / shares, 2),
        }

    return {
        "valuation_date": assumptions["valuation_date"],
        "market_price_cny": market_price,
        "market_cap_100m_cny": market_cap,
        "market_pe_ttm": float(assumptions["market_pe_ttm"]),
        "market_pb": float(assumptions["market_pb"]),
        "market_implied_fy1_pe": _round(market_cap / fy1_profit, 2),
        "market_implied_roe_pct_from_pb": _round(implied_roe * 100, 2),
        "independent_forward_roe_pct": _round(forward_roe * 100, 2),
        "sustainable_pb_from_forward_roe": _round(sustainable_pb, 2),
        "estimated_2026_bps_cny": _round(ending_equity / shares, 2),
        "estimated_2026_parent_equity_bridge": {
            "beginning_parent_equity_100m_cny": _round(
                beginning_equity, 2
            ),
            "parent_net_income_100m_cny": _round(fy1_profit, 2),
            "cash_dividend_payout_ratio_pct": _round(
                forecast_payout * 100, 2
            ),
            "cash_dividend_100m_cny": _round(
                forecast_cash_dividend, 2
            ),
            "other_equity_changes_100m_cny": 0.0,
            "ending_parent_equity_100m_cny": _round(ending_equity, 2),
            "formula": (
                "期末归母净资产＝期初归母净资产＋归母净利润－现金分红"
                "－回购＋增发及其他权益变动"
            ),
            "limitation": (
                "简化桥假设没有新增回购、增发和其他权益变动；"
                "若实际发生，需按财报重算。"
            ),
        },
        "methods": [
            method(
                "市盈率",
                "核心盈利估值",
                pe_value,
                f"2026年归母净利润{fy1_profit:.1f}亿元，11.5—14.0倍",
            ),
            method(
                "分部估值",
                "核心结构估值",
                sotp_value,
                (
                    f"正泰安能100%股权交易值{aneng_value:.1f}亿元×"
                    f"{aneng_stake:.2%}持股，加其余业务利润"
                    f"{remaining_profit:.1f}亿元×12—15倍"
                ),
            ),
            method(
                "PB—ROE",
                "资产回报交叉验证",
                pb_value,
                (
                    f"2025年归母权益{beginning_equity:.1f}亿元＋"
                    f"2026年利润{fy1_profit:.1f}亿元－"
                    f"{forecast_payout:.0%}分红＝"
                    f"2026年末归母权益{ending_equity:.1f}亿元，"
                    f"1.20—1.40倍PB；可持续PB按(ROE-g)/(CoE-g)复算"
                ),
            ),
        ],
        "research_core_value_range_100m_cny": [
            _round(core_low, 1),
            _round(core_high, 1),
        ],
        "research_core_price_range_cny": [
            _round(core_low / shares, 2),
            _round(core_high / shares, 2),
        ],
        "market_to_research_low_pct": _round(
            (core_low / market_cap - 1) * 100, 2
        ),
        "market_to_research_high_pct": _round(
            (core_high / market_cap - 1) * 100, 2
        ),
        "research_core_derivation": {
            "method": "三种适用估值方法区间的严格交集",
            "formula": "核心下限＝各方法下限的最大值；核心上限＝各方法上限的最小值",
            "method_ranges_100m_cny": {
                name: [_round(values[0], 1), _round(values[1], 1)]
                for name, values in method_ranges.items()
            },
            "result_100m_cny": [
                _round(core_low, 1),
                _round(core_high, 1),
            ],
            "limitation": (
                "三种方法共享部分盈利和资产假设，严格交集只表示结果相互兼容，"
                "不代表三条完全独立证据；若未来方法区间不再重叠，应分别展示而"
                "不是强行生成核心区间。"
            ),
        },
        "method_interpretation": (
            "市盈率反映盈利兑现，分部估值把正泰安能与其余业务拆开，"
            "PB—ROE检验账面资产回报能否支撑估值。三种方法共享部分经营"
            "假设，因此不做算术平均；核心区间取三种方法区间的严格交集。"
        ),
    }


def _risk_sensitivities(
    inputs: dict[str, Any],
    scenarios: dict[str, list[dict[str, Any]]],
    valuation: dict[str, Any],
) -> dict[str, Any]:
    shares = float(inputs["company"]["shares_100m"])
    market_pe = float(valuation["market_pe_ttm"])
    base_by_year = {
        str(row["year"]): row for row in scenarios["基准情景"]
    }
    risk_by_year = {
        str(row["year"]): row for row in scenarios["风险情景"]
    }
    scenario_deltas = []
    for year in ("2026", "2027", "2028"):
        base = base_by_year[year]
        risk = risk_by_year[year]
        row: dict[str, Any] = {"year": int(year)}
        for field, label in (
            ("revenue_100m_cny", "revenue"),
            ("gross_profit_100m_cny", "gross_profit"),
            ("parent_net_income_100m_cny", "parent_net_income"),
            ("operating_cash_flow_100m_cny", "operating_cash_flow"),
            ("free_cash_flow_100m_cny", "free_cash_flow"),
        ):
            base_value = float(base[field])
            risk_value = float(risk[field])
            row[f"base_{label}_100m_cny"] = _round(base_value, 2)
            row[f"risk_{label}_100m_cny"] = _round(risk_value, 2)
            row[f"{label}_change_100m_cny"] = _round(
                risk_value - base_value, 2
            )
            row[f"{label}_change_pct"] = _round(
                (risk_value / base_value - 1.0) * 100.0, 2
            )
        row["risk_price_at_unchanged_market_pe_cny"] = _round(
            float(risk["parent_net_income_100m_cny"])
            * market_pe
            / shares,
            2,
        )
        scenario_deltas.append(row)

    assumptions = inputs["risk_sensitivity_assumptions"]
    tax_rate = float(assumptions["tax_rate"])
    pe_low, pe_high = [
        float(value) for value in assumptions["valuation_pe_range"]
    ]

    def unit_sensitivity(
        *,
        name: str,
        pretax_impact: float,
        input_description: str,
        parent_attribution_factor: float = 1.0,
    ) -> dict[str, Any]:
        after_tax = (
            pretax_impact
            * (1.0 - tax_rate)
            * parent_attribution_factor
        )
        eps = after_tax / shares
        return {
            "name": name,
            "input_description": input_description,
            "pretax_profit_impact_100m_cny": _round(pretax_impact, 2),
            "after_tax_parent_profit_impact_100m_cny": _round(
                after_tax, 2
            ),
            "eps_impact_cny": _round(eps, 3),
            "price_impact_at_pe_range_cny": [
                _round(eps * pe_low, 2),
                _round(eps * pe_high, 2),
            ],
            "limitation": (
                "只表示给定单位冲击的财务敏感性，不代表发生概率、"
                "预计损失或目标价变化；未计二阶融资和估值倍数收缩。"
            ),
        }

    guarantee_balance = float(
        assumptions["group_guarantee_balance_100m_cny"]
    )
    guarantee_increment = float(
        assumptions["guarantee_loss_conversion_increment_pct"]
    )
    compensation_increment = float(
        assumptions["annual_compensation_increment_100m_cny"]
    )
    operating_deduction_increment = float(
        assumptions["operating_deduction_ratio_increment_pct"]
    )
    base_2026 = base_by_year["2026"]
    operating_deduction_pretax = (
        float(base_2026["revenue_100m_cny"])
        * operating_deduction_increment
        / 100.0
    )
    base_parent_attribution = (
        float(base_2026["parent_attribution_ratio_pct"]) / 100.0
    )
    return {
        "scenario_deltas": scenario_deltas,
        "unit_sensitivities": [
            unit_sensitivity(
                name="集团担保余额每新增1%转为实际损失",
                pretax_impact=guarantee_balance
                * guarantee_increment
                / 100.0,
                input_description=(
                    f"{guarantee_balance:.2f}亿元集团担保余额×"
                    f"{guarantee_increment:.0f}%"
                ),
            ),
            unit_sensitivity(
                name="发电保障或其他补偿每增加1亿元",
                pretax_impact=compensation_increment,
                input_description=(
                    f"年度税前补偿支出增加"
                    f"{compensation_increment:.2f}亿元"
                ),
            ),
            unit_sensitivity(
                name="经营与融资等扣减率每提高1个百分点",
                pretax_impact=operating_deduction_pretax,
                input_description=(
                    f"2026年收入{float(base_2026['revenue_100m_cny']):.0f}"
                    f"亿元×{operating_deduction_increment:.0f}%"
                ),
                parent_attribution_factor=base_parent_attribution,
            ),
        ],
        "interpretation": (
            "风险情景是交割量、毛利、减值和营运资金共同变化的组合压力测试；"
            "单位敏感性仅用于把担保或补偿风险换算成利润、EPS和估值影响，"
            "两者不能相加为预计损失。"
        ),
    }


def build(inputs: dict[str, Any], *, input_path: Path) -> dict[str, Any]:
    scenarios = {
        scenario_name: [
            _scenario_year(inputs, scenario_name, year)
            for year in ("2026", "2027", "2028")
        ]
        for scenario_name in inputs["scenarios"]
    }
    base_rows = scenarios["基准情景"]
    valuation = _valuation(inputs, base_rows)
    return {
        "model_version": inputs["model_version"],
        "as_of_date": inputs["as_of_date"],
        "input_artifact_hash": _sha256_file(input_path),
        "model_formulas": {
            "revenue": "合并收入＝Σ各业务收入；各业务收入分别由存量规模、当年新增规模、转让规模、单位价格和低压电器需求增速决定",
            "gross_profit": "合并毛利润＝Σ（各业务收入×各业务毛利率）",
            "parent_net_income": "归母净利润＝[毛利润－期间费用与融资等经营扣减＋其他净收益－减值]×（1－所得税率）×归母比例",
            "operating_cash_flow": "经营现金流＝合并净利润＋折旧摊销＋非现金减值－营运资金新增占用＋其他调整",
            "free_cash_flow": "自由现金流＝经营现金流－固定资产资本开支；项目电站存货建设已进入经营现金流，不重复扣减",
            "sustainable_pb": "可持续PB＝（预期ROE－长期增长率）÷（股权回报要求－长期增长率）",
        },
        "actual": inputs["actual"],
        "scenarios": scenarios,
        "valuation": valuation,
        "risk_transmission": inputs["risk_transmission"],
        "risk_sensitivities": _risk_sensitivities(
            inputs, scenarios, valuation
        ),
        "assumption_basis": inputs["assumption_basis"],
        "sanity_checks": {
            "actual_segment_revenue_gap_100m_cny": _round(
                sum(
                    float(row["revenue_100m_cny"])
                    for row in inputs["actual"]["2025"]["segments"]
                )
                - float(inputs["actual"]["2025"]["revenue_100m_cny"]),
                6,
            ),
            "actual_segment_gross_profit_gap_100m_cny": _round(
                sum(
                    float(row["revenue_100m_cny"])
                    * float(row["gross_margin"])
                    for row in inputs["actual"]["2025"]["segments"]
                )
                - float(inputs["actual"]["2025"]["gross_profit_100m_cny"]),
                6,
            ),
            "free_cash_flow_reconciles": all(
                abs(
                    float(row["free_cash_flow_100m_cny"])
                    - float(row["operating_cash_flow_100m_cny"])
                    + float(row["fixed_asset_capex_100m_cny"])
                )
                < 0.11
                for scenario_rows in scenarios.values()
                for row in scenario_rows
            ),
            "downside_profit_below_base": all(
                scenarios["风险情景"][index]["parent_net_income_100m_cny"]
                < scenarios["基准情景"][index]["parent_net_income_100m_cny"]
                for index in range(3)
            ),
            "upside_profit_above_base": all(
                scenarios["改善情景"][index]["parent_net_income_100m_cny"]
                > scenarios["基准情景"][index]["parent_net_income_100m_cny"]
                for index in range(3)
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="正泰电器光伏业务盈利质量与分布式风险独立财务模型"
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
                    "research_core_price_range_cny"
                ],
                "sanity_checks": output["sanity_checks"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
