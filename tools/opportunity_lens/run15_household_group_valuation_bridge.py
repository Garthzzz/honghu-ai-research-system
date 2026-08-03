from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.financial.constants import ROOT
from tools.financial.opportunity_profile_export import EXPORT_SCHEMA_VERSION
from tools.opportunity_lens.run15_portable_artifacts import (
    materialize_run15_portable_artifacts,
)
from tools.pipeline.wind_http_provider import (
    assert_wind_request_scope,
    fetch_current_market_financial_snapshot,
    load_wind_http_client,
)


COMPANY_ID = 632
TICKER = "601877.SH"
COMPANY_NAME = "正泰电器"
TRADE_DATE = "2026-07-27"

CACHE_DIR = ROOT / "cache" / "chint_run15"
RUN_DIR = (
    ROOT
    / "opportunity_lens"
    / "research_outputs"
    / "20260725_chint_pv_profit_quality_run15"
)
FINANCIAL_MODEL_PATH = CACHE_DIR / "run15_chint_financial_model.json"
HOUSEHOLD_MODEL_PATH = CACHE_DIR / "run15_household_contract_cashflow_model.json"
MARKET_PATH = CACHE_DIR / "wind_current_market_snapshot_20260727.json"
BRIDGE_PATH = CACHE_DIR / "run15_household_to_group_valuation_bridge.json"
EXPORT_PATH = RUN_DIR / "company_financial_profile_export_bridge_v1.json"


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 必须是 JSON object")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def collect_market_snapshot() -> dict[str, Any]:
    # One A-share security and twelve narrow current fields.  This is below the
    # project permission threshold and is deliberately not expanded to history.
    assert_wind_request_scope(
        security_count=1,
        field_count=12,
        estimated_observations=12,
    )
    client = load_wind_http_client()
    current = fetch_current_market_financial_snapshot(
        TICKER,
        trade_date=TRADE_DATE,
        client=client,
    )
    payload = {
        "snapshot_version": "run15.chint_current_market.v1",
        "accessed_at_utc": datetime.now(timezone.utc).isoformat(),
        "company": {
            "company_id": COMPANY_ID,
            "name": COMPANY_NAME,
            "ticker": TICKER,
        },
        "scope_audit": {
            "security_count": 1,
            "field_count": 12,
            "estimated_observations": 12,
            "large_request_permission_required": False,
            "purpose": "更新正泰电器公司页当前行情，并对Run15买卖区间重新计价。",
        },
        "current": current,
    }
    _write_json(MARKET_PATH, payload)
    return payload


def build_bridge(
    market_payload: dict[str, Any],
    financial_model: dict[str, Any],
    household_model: dict[str, Any],
) -> dict[str, Any]:
    market = dict(market_payload["current"])
    price = float(market["price"])
    market_cap = float(market["market_cap_cny"])
    pe_ttm = float(market["pe_ttm"])
    pb = float(market["pb"])
    shares_100m = market_cap / price

    official_inputs = {
        "minimum_generation_guarantee_capacity_gw": 27.0,
        "basic_om_price_cny_per_w_year": 0.0386,
        "basic_om_revenue_2024_100m_cny": 6.176247,
        "net_generation_compensation_2024_100m_cny": 0.380852,
        "om_net_revenue_2024_100m_cny": 5.795395,
        "om_gross_margin_2024_pct": 37.83,
        "expected_liabilities_2025_100m_cny": 7.1619508841,
        "expected_liabilities_2024_100m_cny": 3.2132335521,
        "expected_return_liability_2025_100m_cny": 6.44080638,
        "pv_loan_guarantee_loss_2025_100m_cny": 0.4481395148,
        "parent_net_income_2025_100m_cny": 45.01,
        "parent_stake_after_transaction_pct": 71.24,
        "model_tax_rate_pct": 20.0,
    }
    capacity_w = (
        official_inputs["minimum_generation_guarantee_capacity_gw"] * 1_000_000_000
    )
    om_basic_revenue = (
        capacity_w
        * official_inputs["basic_om_price_cny_per_w_year"]
        / 100_000_000
    )
    compensation_ratio = (
        official_inputs["net_generation_compensation_2024_100m_cny"]
        / official_inputs["basic_om_revenue_2024_100m_cny"]
    )
    compensation_at_2024_intensity = om_basic_revenue * compensation_ratio
    om_net_revenue = om_basic_revenue - compensation_at_2024_intensity
    om_gross_profit = (
        om_net_revenue * official_inputs["om_gross_margin_2024_pct"] / 100
    )
    tax_after_parent_share = (
        (1 - official_inputs["model_tax_rate_pct"] / 100)
        * official_inputs["parent_stake_after_transaction_pct"]
        / 100
    )
    attributable_profit_upper_bound = om_gross_profit * tax_after_parent_share

    three_x_total_compensation = compensation_at_2024_intensity * 3
    three_x_incremental_compensation = (
        three_x_total_compensation - compensation_at_2024_intensity
    )
    three_x_incremental_parent_ni_impact = (
        three_x_incremental_compensation * tax_after_parent_share
    )
    three_x_incremental_eps_impact = (
        three_x_incremental_parent_ni_impact / shares_100m
    )

    expected_liability_increase = (
        official_inputs["expected_liabilities_2025_100m_cny"]
        - official_inputs["expected_liabilities_2024_100m_cny"]
    )
    base_2026 = financial_model["scenarios"]["基准情景"][0]
    risk_2026 = financial_model["scenarios"]["风险情景"][0]
    risk_2028 = financial_model["scenarios"]["风险情景"][2]
    value_low, value_high = financial_model["valuation"][
        "research_core_price_range_cny"
    ]
    consensus_2026 = 54.16
    implied_profit_at_11_5x = market_cap / 11.5
    implied_roe = (pb * (0.095 - 0.03) + 0.03) * 100
    risk_2026_price = (
        float(risk_2026["parent_net_income_100m_cny"]) / shares_100m * pe_ttm
    )
    risk_2028_price = (
        float(risk_2028["parent_net_income_100m_cny"]) / shares_100m * pe_ttm
    )
    core_range_text = f"{value_low:.2f}—{value_high:.2f}"
    current_upside_low = float(
        financial_model["valuation"]["market_to_research_low_pct"]
    )
    current_upside_high = float(
        financial_model["valuation"]["market_to_research_high_pct"]
    )
    buy_zone_reference = 22.50
    buy_zone_upside_low = (value_low / buy_zone_reference - 1) * 100
    buy_zone_upside_high = (value_high / buy_zone_reference - 1) * 100

    bridge = {
        "model_name": "Run15单户合同到正泰电器集团现金流与估值传导桥",
        "model_version": "run15.household_group_valuation_bridge.v2",
        "as_of_date": TRADE_DATE,
        "input_artifacts": {
            "financial_model": {
                "path": str(FINANCIAL_MODEL_PATH.relative_to(ROOT)),
                "sha256": _sha256(FINANCIAL_MODEL_PATH),
            },
            "household_model": {
                "path": str(HOUSEHOLD_MODEL_PATH.relative_to(ROOT)),
                "sha256": _sha256(HOUSEHOLD_MODEL_PATH),
            },
            "current_market": {
                "path": str(MARKET_PATH.relative_to(ROOT)),
                "sha256": _sha256(MARKET_PATH),
            },
        },
        "method_boundary": {
            "principle": (
                "100平方米案例只识别一份合同中谁收钱、谁承担责任；组合层改用公司披露的"
                "每瓦运维费、实际补偿率、保障容量和预计负债校准，不能把一次屋顶维修"
                "机械乘到全部27GW。"
            ),
            "post_sale_boundary": (
                "电站出售后，资产买方通常取得发电现金余量；正泰保留开发转让毛利、"
                "可能的运维收入，以及合同约定的发电保障、退回、贷款担保和品牌责任。"
            ),
        },
        "official_inputs": official_inputs,
        "portfolio_calibration": {
            "formula": (
                "组合基础运维收入＝保障容量×基础运维单价；组合补偿＝组合基础运维收入"
                "×2024年净补偿/基础运维收入；运维毛利润＝（基础运维收入－组合补偿）"
                "×2024年运维毛利率。"
            ),
            "minimum_capacity_gw": 27.0,
            "annualized_basic_om_revenue_100m_cny": round(om_basic_revenue, 4),
            "compensation_ratio_at_2024_intensity_pct": round(
                compensation_ratio * 100, 4
            ),
            "annualized_compensation_at_2024_intensity_100m_cny": round(
                compensation_at_2024_intensity, 4
            ),
            "annualized_net_om_revenue_100m_cny": round(om_net_revenue, 4),
            "annualized_om_gross_profit_100m_cny": round(om_gross_profit, 4),
            "attributable_profit_upper_bound_100m_cny": round(
                attributable_profit_upper_bound, 4
            ),
            "limitation": (
                "27GW是“超过27GW”的保守下限；37.83%为2024年运维综合毛利率。"
                "归母贡献只按税后和71.24%持股缩放，未扣集团费用，因此是上限式诊断，"
                "不是独立净利润预测。"
            ),
        },
        "tail_liability_diagnostics": {
            "expected_liabilities_2025_100m_cny": round(
                official_inputs["expected_liabilities_2025_100m_cny"], 4
            ),
            "expected_liability_increase_2025_100m_cny": round(
                expected_liability_increase, 4
            ),
            "expected_liabilities_to_2025_parent_ni_pct": round(
                official_inputs["expected_liabilities_2025_100m_cny"]
                / official_inputs["parent_net_income_2025_100m_cny"]
                * 100,
                2,
            ),
            "increase_to_2025_parent_ni_pct": round(
                expected_liability_increase
                / official_inputs["parent_net_income_2025_100m_cny"]
                * 100,
                2,
            ),
            "expected_liabilities_to_current_market_cap_pct": round(
                official_inputs["expected_liabilities_2025_100m_cny"]
                / market_cap
                * 100,
                2,
            ),
            "interpretation": (
                "预计负债是存量资产负债表义务，不等于下一年会全部形成现金支出；"
                "但其规模和同比增加证明“已经出售”不等于集团责任归零。"
            ),
        },
        "three_x_compensation_stress": {
            "total_compensation_100m_cny": round(three_x_total_compensation, 4),
            "incremental_compensation_vs_2024_intensity_100m_cny": round(
                three_x_incremental_compensation, 4
            ),
            "incremental_parent_net_income_impact_100m_cny": round(
                three_x_incremental_parent_ni_impact, 4
            ),
            "incremental_eps_impact_cny": round(
                three_x_incremental_eps_impact, 4
            ),
            "price_impact_at_11_5x_to_14x_cny": [
                round(three_x_incremental_eps_impact * 11.5, 2),
                round(three_x_incremental_eps_impact * 14.0, 2),
            ],
            "interpretation": (
                "单独把补偿强度提高到2024年的三倍，对集团估值的影响仍小于交割、"
                "存货和预计退回责任的组合风险；不能把它当成全部下行情景。"
            ),
        },
        "group_cash_flow_and_valuation": {
            "current_market": {
                "price_cny": round(price, 2),
                "market_cap_100m_cny": round(market_cap, 4),
                "pe_ttm": round(pe_ttm, 4),
                "pe_forward_wind": round(float(market["pe_forward"]), 4),
                "pb": round(pb, 4),
                "roe_ttm_pct": round(float(market["roe"]), 4),
                "roa_ttm_pct": round(float(market["roa"]), 4),
                "shares_100m": round(shares_100m, 4),
            },
            "base_2026": {
                "parent_net_income_100m_cny": base_2026[
                    "parent_net_income_100m_cny"
                ],
                "operating_cash_flow_100m_cny": base_2026[
                    "operating_cash_flow_100m_cny"
                ],
                "free_cash_flow_100m_cny": base_2026[
                    "free_cash_flow_100m_cny"
                ],
                "pe_on_current_market_cap": round(
                    market_cap / float(base_2026["parent_net_income_100m_cny"]),
                    2,
                ),
                "free_cash_flow_yield_pct": round(
                    float(base_2026["free_cash_flow_100m_cny"])
                    / market_cap
                    * 100,
                    2,
                ),
            },
            "risk_2026": {
                "parent_net_income_100m_cny": risk_2026[
                    "parent_net_income_100m_cny"
                ],
                "operating_cash_flow_100m_cny": risk_2026[
                    "operating_cash_flow_100m_cny"
                ],
                "free_cash_flow_100m_cny": risk_2026[
                    "free_cash_flow_100m_cny"
                ],
                "free_cash_flow_yield_pct": round(
                    float(risk_2026["free_cash_flow_100m_cny"])
                    / market_cap
                    * 100,
                    2,
                ),
                "price_at_current_pe_ttm_cny": round(risk_2026_price, 2),
            },
            "risk_2028_price_at_current_pe_ttm_cny": round(risk_2028_price, 2),
            "wind_consensus_2026_net_income_100m_cny": consensus_2026,
            "pe_on_wind_consensus_2026": round(market_cap / consensus_2026, 2),
            "market_implied_normal_profit_at_11_5x_100m_cny": round(
                implied_profit_at_11_5x, 2
            ),
            "market_implied_sustainable_roe_pct": round(implied_roe, 2),
            "independent_core_price_range_cny": [value_low, value_high],
            "upside_to_core_range_pct": [
                round((value_low / price - 1) * 100, 2),
                round((value_high / price - 1) * 100, 2),
            ],
        },
        "price_decision_framework": [
            {
                "price_range_cny": "24—25",
                "action": "小仓位观察或试仓，不是强买",
                "reason": (
                    "当前24.57元对应独立2026年利润约9.62倍PE；到核心价值下沿的"
                    f"空间约{current_upside_low:.2f}%，与约21—22元组合风险区间相比"
                    "安全边际仍不够厚。"
                ),
            },
            {
                "price_range_cny": "22—23",
                "action": "更合适的分批买入区",
                "reason": (
                    "前提是下跌来自市场波动，而不是现金流、存货、预计退回或担保恶化；"
                    f"以22.50元计，至{core_range_text}元的空间约"
                    f"{buy_zone_upside_low:.2f}%—{buy_zone_upside_high:.2f}%。"
                ),
            },
            {
                "price_range_cny": "20.5—22",
                "action": "高赔率观察区，但必须先排除基本面证伪",
                "reason": (
                    "已接近组合风险情景的约21—22元；如果价格下跌同时伴随经营现金流"
                    "塌陷、存货和预计负债激增，不能机械补仓。"
                ),
            },
            {
                "price_range_cny": core_range_text,
                "action": "基准价值兑现区，逐步止盈或等待新证据",
                "reason": (
                    "需要连续两个报告期看到电站交割、库存下降和回款同步，且合作运营"
                    "毛利与尾部责任没有恶化。"
                ),
            },
            {
                "price_range_cny": f"高于{value_high:.2f}",
                "action": "基准情景已充分定价",
                "reason": "只有改善情景中的利润和现金流开始兑现，才支持继续持有。",
            },
        ],
        "bottom_line": (
            "截至2026年7月27日，正泰电器24.57元可以小仓位观察，但不是风险收益比"
            "足够突出的强买点；22—23元且现金流、存货、预计负债未恶化时，分批买入"
            "更合理。若股价下跌源于组合风险情景正在兑现，约21—22元也不是自动买点。"
        ),
        "limitations": [
            "没有27GW逐项目所在省份、电价、光照、合同阈值、实际补偿和资产买方数据。",
            "运维归母贡献按2024年综合毛利率、20%税率和71.24%持股缩放，只是上限式诊断。",
            "自由现金流按经营现金流减固定资产资本开支，未构成完整FCFE或DCF。",
            "价格区间是条件化研究判断，不是个性化投资建议；触发条件比单一价格更重要。",
        ],
        "source_refs": [
            "r-chint-ar2025",
            "r-aneng-ipo2025",
            "r-run15-household-contract-model",
            "r-run15-model",
            "r-run15-reconciliation",
        ],
    }
    return bridge


def _observation(
    *,
    metric_name: str,
    value_num: float,
    unit: str,
    raw_feature_name: str,
    currency: str | None = None,
    frequency: str = "daily",
    formula: str | None = None,
) -> dict[str, Any]:
    return {
        "metric_name": metric_name,
        "value_num": float(value_num),
        "unit": unit,
        "currency": currency,
        "period_end": TRADE_DATE,
        "fiscal_year": None,
        "fiscal_period": None,
        "frequency": frequency,
        "fact_type": "market",
        "as_of_date": TRADE_DATE,
        "announcement_date": None,
        "provider": "wind",
        "raw_feature_name": raw_feature_name,
        "formula": formula,
        "input_refs": [],
        "quality_status": "usable",
        "scenario_name": "reported",
        "source_snapshot_key": "wind_current_market",
        "model_run_key": None,
    }


def build_financial_export(
    market_payload: dict[str, Any],
    bridge: dict[str, Any],
) -> dict[str, Any]:
    portable_artifacts = materialize_run15_portable_artifacts()
    market = dict(market_payload["current"])
    bridge_hash = _sha256(BRIDGE_PATH)
    market_hash = _sha256(MARKET_PATH)
    group = bridge["group_cash_flow_and_valuation"]
    current = group["current_market"]
    risk = group["risk_2026"]
    decision = bridge["price_decision_framework"]

    summary = {
        "conclusion": bridge["bottom_line"],
        "operating_analysis": (
            "100平方米案例只负责识别现金和责任的归属，不能直接乘到全部电站。"
            f"按超过27GW保障义务、0.0386元/W·年基础运维费和2024年实际补偿率缩放，"
            f"年度基础运维收入约{bridge['portfolio_calibration']['annualized_basic_om_revenue_100m_cny']:.2f}亿元，"
            f"扣补偿后净运维收入约{bridge['portfolio_calibration']['annualized_net_om_revenue_100m_cny']:.2f}亿元、"
            f"毛利润约{bridge['portfolio_calibration']['annualized_om_gross_profit_100m_cny']:.2f}亿元。"
            "2025年预计负债7.16亿元、同比增加3.95亿元，说明电站出售后仍存在退回、"
            "贷款担保和质量等尾部义务。真正会显著改变集团现金流的不是一次普通屋顶维修，"
            "而是资产交割放慢、项目存货上升、预计退回和担保责任同时恶化。"
        ),
        "valuation_analysis": (
            f"截至{TRADE_DATE}收盘价{current['price_cny']:.2f}元、市值{current['market_cap_100m_cny']:.2f}亿元，"
            f"滚动PE {current['pe_ttm']:.2f}倍、PB {current['pb']:.2f}倍。"
            f"按独立2026年54.90亿元利润为{group['base_2026']['pe_on_current_market_cap']:.2f}倍PE，"
            f"按Wind一致预期54.16亿元为{group['pe_on_wind_consensus_2026']:.2f}倍。"
            f"多方法严格交集为{group['independent_core_price_range_cny'][0]:.2f}—"
            f"{group['independent_core_price_range_cny'][1]:.2f}元，当前上行空间约"
            f"{group['upside_to_core_range_pct'][0]:.2f}%—{group['upside_to_core_range_pct'][1]:.2f}%；"
            f"组合风险情景按当前PE约对应{risk['price_at_current_pe_ttm_cny']:.2f}元，"
            "因此现价有折价但没有足够厚的单边安全边际。"
        ),
        "buy_point_analysis": (
            f"{decision[0]['price_range_cny']}元只适合小仓位观察。"
            f"{decision[1]['price_range_cny']}元是更合理的分批买入区，但必须确认下跌不是由"
            "经营现金流、项目存货、预计退回或担保恶化造成。"
            f"{decision[2]['price_range_cny']}元接近风险情景，只有风险触发项没有兑现时才有高赔率；"
            "不能因为PB低而机械补仓。"
        ),
        "sell_point_analysis": (
            f"{group['independent_core_price_range_cny'][0]:.2f}—"
            f"{group['independent_core_price_range_cny'][1]:.2f}元进入基准价值兑现区，"
            "应结合交割、回款和预计负债决定是否止盈；"
            f"高于{group['independent_core_price_range_cny'][1]:.2f}元时，除非改善情景中的"
            "利润和现金流已经被财报验证，否则基准情景"
            "已充分定价。若任何价格下连续两个报告期出现现金流塌陷、项目存货与预计负债"
            "同步上升，也应先下修模型而不是只看价格。"
        ),
        "difference_causes": [
            "独立2026年利润54.90亿元与Wind一致预期54.16亿元接近，分歧不在利润总额。",
            "独立收入高于卖方中位数主要来自低毛利电站转让量，对价值的贡献远小于收入差。",
            "市场折价主要对应资产交割、营运资金和出售后的预计退回、担保及发电保障责任。",
        ],
        "future_view": (
            "未来两个报告期同时看转让收入、回款、项目存货、应付款、合作运营毛利和预计负债；"
            "只有交割、库存下降与回款同步，才确认现金质量改善。"
        ),
        "positive_trigger": (
            "经营现金流向独立基准91.5亿元年化路径收敛，转让放量同时项目存货下降，"
            "合作运营毛利维持50%以上，预计负债占利润比例不再上升。"
        ),
        "risk_trigger": (
            "经营现金流明显低于利润、项目存货与应收连续快于收入、预计退回或担保损失"
            "继续大幅增加，或合作运营毛利连续低于48%。"
        ),
    }

    run_key = "ol15:601877.SH:household_group_valuation_bridge:v2"
    inputs = [
        {
            "input_name": "2026年独立基准归母净利润",
            "value_num": 54.9,
            "value_text": None,
            "unit": "亿元人民币",
            "period_or_as_of_date": "2026",
            "source_ref": (
                f"{_sha256(FINANCIAL_MODEL_PATH)}#scenarios.基准情景.2026"
            ),
            "input_type": "derived_fact",
            "formula_or_method": "Run15冻结分业务财务模型。",
            "sensitivity_note": "电站转让、合作运营毛利、营运资金和归母比例。",
            "limitation_note": None,
        },
        {
            "input_name": "当前市场快照",
            "value_num": current["market_cap_100m_cny"],
            "value_text": None,
            "unit": "亿元人民币",
            "period_or_as_of_date": TRADE_DATE,
            "source_ref": f"{market_hash}#current.market_cap_cny",
            "input_type": "direct_fact",
            "formula_or_method": "Wind单证券窄字段收盘快照。",
            "sensitivity_note": "市场价格每日变化。",
            "limitation_note": None,
        },
        {
            "input_name": "出售后长期责任组合",
            "value_num": 27.0,
            "value_text": "超过27GW发电保障或差额补偿义务，另有预计退回和贷款担保责任。",
            "unit": "GW",
            "period_or_as_of_date": "2025",
            "source_ref": f"{bridge_hash}#official_inputs",
            "input_type": "derived_fact",
            "formula_or_method": "公司披露容量与预计负债结合，不把保障容量当预计损失。",
            "sensitivity_note": "区域电价、光照、限电、合同阈值和资产买方。",
            "limitation_note": "没有逐项目公开数据。",
        },
    ]
    outputs = [
        {
            "output_name": "当前市值隐含归母净利润",
            "value_num": group[
                "market_implied_normal_profit_at_11_5x_100m_cny"
            ],
            "value_text": None,
            "range_low": None,
            "range_high": None,
            "unit": "亿元人民币",
            "period_or_as_of_date": TRADE_DATE,
            "formula": "当前市值÷11.5倍正常化PE",
            "substitution": (
                f"{current['market_cap_100m_cny']:.2f}÷11.5＝"
                f"{group['market_implied_normal_profit_at_11_5x_100m_cny']:.2f}亿元"
            ),
            "dependency_group": "当前市场隐含预期",
            "conclusion": "低于独立2026年54.90亿元，但差异需要现金流兑现。",
        },
        {
            "output_name": "2026年组合风险情景目标市值",
            "value_num": risk["parent_net_income_100m_cny"] * current["pe_ttm"],
            "value_text": None,
            "range_low": None,
            "range_high": None,
            "unit": "亿元人民币",
            "period_or_as_of_date": "2026",
            "formula": "风险情景归母净利润×当前滚动PE",
            "substitution": (
                f"{risk['parent_net_income_100m_cny']:.2f}×"
                f"{current['pe_ttm']:.2f}＝"
                f"{risk['parent_net_income_100m_cny'] * current['pe_ttm']:.2f}亿元"
            ),
            "dependency_group": "组合风险情景",
            "conclusion": (
                f"对应约{risk['price_at_current_pe_ttm_cny']:.2f}元/股；"
                "若风险同时触发倍数还可能收缩。"
            ),
        },
        {
            "output_name": "27GW运维责任组合归母利润上限",
            "value_num": bridge["portfolio_calibration"][
                "attributable_profit_upper_bound_100m_cny"
            ],
            "value_text": None,
            "range_low": None,
            "range_high": None,
            "unit": "亿元人民币",
            "period_or_as_of_date": "2025口径年化",
            "formula": "组合净运维收入×运维毛利率×税后比例×正泰持股",
            "substitution": (
                f"{bridge['portfolio_calibration']['annualized_net_om_revenue_100m_cny']:.2f}"
                f"×37.83%×80%×71.24%＝"
                f"{bridge['portfolio_calibration']['attributable_profit_upper_bound_100m_cny']:.2f}亿元"
            ),
            "dependency_group": "出售后运维责任",
            "conclusion": "未扣集团费用的上限式诊断，不是净利润预测。",
        },
    ]

    field_map = [
        ("close", "price", "元/股", "Wind WSS.close", "CNY", None),
        (
            "market_cap_cny",
            "market_cap_cny",
            "亿元人民币",
            "Wind WSS.mkt_cap_ard / 1e8",
            "CNY",
            "Wind总市值人民币元÷1e8",
        ),
        ("pe_ttm", "pe_ttm", "倍", "Wind WSS.pe_ttm", None, None),
        (
            "pe_forward",
            "pe_forward",
            "倍",
            "Wind WSS.pe_est_ftm",
            None,
            None,
        ),
        ("pb", "pb", "倍", "Wind WSS.pb_lf", None, None),
        ("ps_ttm", "ps_ttm", "倍", "Wind WSS.ps_ttm", None, None),
        (
            "ev_ebitda",
            "ev_ebitda",
            "倍",
            "Wind WSS.ev2_to_ebitda",
            None,
            None,
        ),
        ("roe", "roe", "%", "Wind WSS.roe_ttm", None, None),
        ("roa", "roa", "%", "Wind WSS.roa2_ttm", None, None),
        ("eps_ttm", "eps_ttm", "元/股", "Wind WSS.eps_ttm", "CNY", None),
        ("bps_mrq", "bps_mrq", "元/股", "Wind WSS.bps_new", "CNY", None),
    ]
    observations = [
        _observation(
            metric_name=metric,
            value_num=float(market[key]),
            unit=unit,
            raw_feature_name=feature,
            currency=currency,
            formula=formula,
        )
        for metric, key, unit, feature, currency, formula in field_map
        if market.get(key) is not None
    ]

    return {
        "export_schema_version": EXPORT_SCHEMA_VERSION,
        "research_run_ref": "financial_refresh:company_632:20260727",
        "as_of_date": TRADE_DATE,
        "source_artifacts": [
            {
                "path": str(portable_artifacts[MARKET_PATH].relative_to(ROOT)),
                "sha256": market_hash,
                "role": "Wind单证券窄字段当前市场快照",
            },
            {
                "path": str(portable_artifacts[BRIDGE_PATH].relative_to(ROOT)),
                "sha256": bridge_hash,
                "role": "单户合同到集团现金流与估值传导模型",
            },
            {
                "path": str(
                    portable_artifacts[FINANCIAL_MODEL_PATH].relative_to(ROOT)
                ),
                "sha256": _sha256(FINANCIAL_MODEL_PATH),
                "role": "Run15冻结分业务财务模型",
            },
        ],
        "companies": [
            {
                "research_company_id": COMPANY_ID,
                "security": {
                    "canonical_name": COMPANY_NAME,
                    "ticker": TICKER,
                    "market": "A股",
                    "listing_status": "a_share",
                    "reporting_currency": "CNY",
                    "identity_status": "verified",
                },
                "source_snapshots": [
                    {
                        "key": "wind_current_market",
                        "provider": "wind",
                        "source_channel": "structured_api",
                        "source_ref": f"wind:{TICKER}:{TRADE_DATE}:narrow_current",
                        "title": "正泰电器Wind当前市场窄字段快照",
                        "publisher": "Wind内网HTTP代理",
                        "as_of_date": TRADE_DATE,
                        "fetched_at": market_payload["accessed_at_utc"],
                        "content_hash": market_hash,
                        "raw_snapshot_path": str(MARKET_PATH.relative_to(ROOT)),
                        "metadata": market_payload["scope_audit"],
                    },
                    {
                        "key": "household_group_bridge",
                        "provider": "internal_model",
                        "source_channel": "internal_calculation",
                        "source_ref": "run15:chint:household_group_valuation_bridge:v2",
                        "title": "正泰电器单户合同到集团现金流与估值传导模型",
                        "publisher": "Industry Demo内部研究模型",
                        "as_of_date": TRADE_DATE,
                        "fetched_at": None,
                        "content_hash": bridge_hash,
                        "raw_snapshot_path": str(BRIDGE_PATH.relative_to(ROOT)),
                        "metadata": {
                            "financial_model_hash": _sha256(
                                FINANCIAL_MODEL_PATH
                            ),
                            "household_model_hash": _sha256(
                                HOUSEHOLD_MODEL_PATH
                            ),
                            "market_snapshot_hash": market_hash,
                        },
                    },
                ],
                "model_runs": [
                    {
                        "run_key": run_key,
                        "skill_name": "company_valuation_modeling",
                        "model_name": "Run15单户合同到集团现金流与价格区间诊断",
                        "model_role": "diagnostic",
                        "supersedes_run_keys": [
                            "ol15:601877.SH:household_group_valuation_bridge:v1"
                        ],
                        "forecast_start": "2026",
                        "forecast_end": "2028",
                        "valuation_date": TRADE_DATE,
                        "assumptions": {
                            "company_detail_summary": summary,
                            "method_role": (
                                "基于既有独立财务模型和最新市场价格的风险收益诊断；"
                                "不替代已冻结的核心多方法估值。"
                            ),
                        },
                        "limitations": (
                            "没有27GW逐项目合同、电价、光照、补偿和买方数据；"
                            "价格区间必须与经营触发条件一起使用。"
                        ),
                        "finalization": "reviewed",
                        "inputs": inputs,
                        "outputs": outputs,
                        "reconciliations": [],
                    }
                ],
                "observations": observations,
            }
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="构建Run15单户合同到集团现金流、估值和公司页价格区间桥。"
    )
    parser.add_argument(
        "--refresh-market",
        action="store_true",
        help="执行一次Wind单证券12个当前窄字段请求。",
    )
    args = parser.parse_args()

    if args.refresh_market:
        market_payload = collect_market_snapshot()
    else:
        market_payload = _read_json(MARKET_PATH)
    financial_model = _read_json(FINANCIAL_MODEL_PATH)
    household_model = _read_json(HOUSEHOLD_MODEL_PATH)
    bridge = build_bridge(market_payload, financial_model, household_model)
    _write_json(BRIDGE_PATH, bridge)
    export = build_financial_export(market_payload, bridge)
    _write_json(EXPORT_PATH, export)
    print(
        json.dumps(
            {
                "market_snapshot": str(MARKET_PATH),
                "bridge": str(BRIDGE_PATH),
                "financial_export": str(EXPORT_PATH),
                "bottom_line": bridge["bottom_line"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
