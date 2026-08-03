from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


YEARS = [2026, 2027, 2028, 2029, 2030, 2031]


def _round(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


def _hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _forecast(
    revenue: list[float],
    gross_margin: list[float],
    net_margin: list[float],
    cash_conversion: list[float],
    capex: list[float],
) -> list[dict[str, float | int]]:
    rows: list[dict[str, float | int]] = []
    for index, year in enumerate(YEARS):
        net_income = revenue[index] * net_margin[index]
        operating_cash_flow = net_income * cash_conversion[index]
        free_cash_flow = operating_cash_flow - capex[index]
        rows.append(
            {
                "year": year,
                "revenue_cny_100m": _round(revenue[index]),
                "gross_margin_pct": _round(gross_margin[index] * 100),
                "net_margin_pct": _round(net_margin[index] * 100),
                "net_income_cny_100m": _round(net_income),
                "cash_conversion_pct": _round(cash_conversion[index] * 100),
                "operating_cash_flow_cny_100m": _round(operating_cash_flow),
                "capex_cny_100m": _round(capex[index]),
                "free_cash_flow_cny_100m": _round(free_cash_flow),
            }
        )
    return rows


def _stress(
    baseline: list[dict[str, float | int]],
    *,
    volume_share_effect: list[float],
    extra_asp_pressure: list[float],
    demand_mix_offset: list[float],
    gross_margin_hit_pp: list[float],
    cash_conversion_hit_pp: list[float],
    capex_multiplier: list[float],
) -> list[dict[str, float | int]]:
    rows: list[dict[str, float | int]] = []
    for index, base in enumerate(baseline):
        revenue_factor = (
            (1 - volume_share_effect[index])
            * (1 - extra_asp_pressure[index])
            * (1 + demand_mix_offset[index])
        )
        revenue = float(base["revenue_cny_100m"]) * revenue_factor
        gross_margin = float(base["gross_margin_pct"]) - gross_margin_hit_pp[index]
        # 毛利压力按75%的税后传导进入净利率；费用、税率和非经常项没有另行拍数。
        net_margin = max(0.0, float(base["net_margin_pct"]) - gross_margin_hit_pp[index] * 0.75)
        net_income = revenue * net_margin / 100
        cash_conversion = max(0.0, float(base["cash_conversion_pct"]) - cash_conversion_hit_pp[index])
        operating_cash_flow = net_income * cash_conversion / 100
        capex = float(base["capex_cny_100m"]) * capex_multiplier[index]
        free_cash_flow = operating_cash_flow - capex
        rows.append(
            {
                "year": int(base["year"]),
                "volume_share_effect_pct": _round(-volume_share_effect[index] * 100),
                "extra_asp_pressure_pct": _round(-extra_asp_pressure[index] * 100),
                "demand_mix_offset_pct": _round(demand_mix_offset[index] * 100),
                "revenue_cny_100m": _round(revenue),
                "revenue_vs_baseline_pct": _round((revenue_factor - 1) * 100),
                "gross_margin_pct": _round(gross_margin),
                "gross_margin_vs_baseline_pp": _round(-gross_margin_hit_pp[index]),
                "net_income_cny_100m": _round(net_income),
                "net_income_vs_baseline_pct": _round((net_income / float(base["net_income_cny_100m"]) - 1) * 100),
                "cash_conversion_pct": _round(cash_conversion),
                "operating_cash_flow_cny_100m": _round(operating_cash_flow),
                "capex_cny_100m": _round(capex),
                "free_cash_flow_cny_100m": _round(free_cash_flow),
                "free_cash_flow_vs_baseline_pct": _round((free_cash_flow / float(base["free_cash_flow_cny_100m"]) - 1) * 100),
            }
        )
    return rows


def _cash_flow_diagnostic(
    rows: list[dict[str, float | int]],
    required_return: float,
    terminal_growth: float,
    sustainable_roe: float,
) -> dict[str, float]:
    """零净举债假设下的股权现金流敏感性，不宣称正式目标价值。"""
    exponents = [0.44, 1.44, 2.44, 3.44, 4.44, 5.44]
    remaining_2026_fraction = 162 / 365
    pv_explicit = 0.0
    for index, row in enumerate(rows):
        cash_flow = float(row["free_cash_flow_cny_100m"])
        if index == 0:
            cash_flow *= remaining_2026_fraction
        pv_explicit += cash_flow / ((1 + required_return) ** exponents[index])
    terminal_reinvestment_rate = terminal_growth / sustainable_roe
    terminal_cash_flow = (
        float(rows[-1]["net_income_cny_100m"])
        * (1 + terminal_growth)
        * (1 - terminal_reinvestment_rate)
    )
    terminal_value = terminal_cash_flow / (required_return - terminal_growth)
    pv_terminal = terminal_value / ((1 + required_return) ** exponents[-1])
    value = pv_explicit + pv_terminal
    return {
        "valuation_date": "2026-07-22",
        "remaining_2026_fraction": _round(remaining_2026_fraction, 4),
        "required_return_pct": _round(required_return * 100),
        "terminal_growth_pct": _round(terminal_growth * 100),
        "sustainable_roe_pct": _round(sustainable_roe * 100),
        "terminal_reinvestment_rate_pct": _round(terminal_reinvestment_rate * 100),
        "pv_explicit_cash_flow_cny_100m": _round(pv_explicit),
        "pv_terminal_cny_100m": _round(pv_terminal),
        "cash_flow_value_before_balance_sheet_bridge_cny_100m": _round(value),
        "terminal_share_pct": _round(pv_terminal / value * 100),
    }


def _entrant_business_case(
    *,
    baseline_revenue: list[float],
    baseline_parent_net_income: list[float],
    optical_revenue: list[float],
    optical_net_margin: list[float],
    optical_capex: list[float],
    parent_attribution: float,
    working_capital_rate: float,
) -> list[dict[str, float | int]]:
    """Translate a new optical business into group revenue, profit and cash impact.

    Revenue is consolidated at 100%.  Profit attributable to the listed parent is
    reduced by ``parent_attribution`` where the operating business sits in a
    non-wholly-owned subsidiary.  Working-capital investment applies only to the
    annual increase in optical revenue, preventing a steady-state revenue base from
    being charged repeatedly.
    """
    rows: list[dict[str, float | int]] = []
    previous_optical_revenue = 0.0
    for index, year in enumerate(YEARS):
        project_profit = optical_revenue[index] * optical_net_margin[index]
        parent_profit = project_profit * parent_attribution
        working_capital = max(0.0, optical_revenue[index] - previous_optical_revenue) * working_capital_rate
        project_free_cash_flow = project_profit - optical_capex[index] - working_capital
        rows.append(
            {
                "year": year,
                "group_baseline_revenue_cny_100m": _round(baseline_revenue[index]),
                "group_baseline_parent_net_income_cny_100m": _round(baseline_parent_net_income[index]),
                "optical_revenue_cny_100m": _round(optical_revenue[index]),
                "optical_net_margin_pct": _round(optical_net_margin[index] * 100),
                "optical_project_net_income_cny_100m": _round(project_profit),
                "listed_parent_attribution_pct": _round(parent_attribution * 100),
                "incremental_parent_net_income_cny_100m": _round(parent_profit),
                "parent_net_income_uplift_pct": _round(
                    parent_profit / baseline_parent_net_income[index] * 100
                ),
                "optical_capex_cny_100m": _round(optical_capex[index]),
                "incremental_working_capital_cny_100m": _round(working_capital),
                "optical_project_free_cash_flow_cny_100m": _round(project_free_cash_flow),
            }
        )
        previous_optical_revenue = optical_revenue[index]
    return rows


def _weighted_probability(states: list[dict[str, float]], key: str) -> float:
    return sum(state["weight"] * state[key] for state in states)


def _joint_probability(
    states: list[dict[str, float]],
    *,
    within_state_positive_dependence: float = 0.0,
) -> dict[str, float]:
    """在共享产业状态之外，允许两家公司仍有未观测的正向联动。

    系数为0时，表示给定共享状态后的条件独立近似；系数为1时，同时进入概率
    移到该状态下的可行同向上界 min(p_byd, p_luxshare)。这不是Pearson相关系数。
    """
    if not 0 <= within_state_positive_dependence <= 1:
        raise ValueError("within_state_positive_dependence 必须在0和1之间")
    byd = _weighted_probability(states, "byd")
    luxshare = _weighted_probability(states, "luxshare")
    both = 0.0
    for state in states:
        independent_joint = state["byd"] * state["luxshare"]
        same_direction_upper = min(state["byd"], state["luxshare"])
        state_joint = independent_joint + within_state_positive_dependence * (
            same_direction_upper - independent_joint
        )
        both += state["weight"] * state_joint
    return {
        "byd_pct": _round(byd * 100, 1),
        "luxshare_pct": _round(luxshare * 100, 1),
        "both_pct": _round(both * 100, 1),
        "at_least_one_pct": _round((byd + luxshare - both) * 100, 1),
    }


def _probability_model() -> dict[str, Any]:
    weights = {
        "战略意愿明确": 8,
        "专属团队形成": 10,
        "直接产品和规格形成": 14,
        "关键器件与专属产线准备": 12,
        "互操作和可靠性通过": 12,
        "正式客户验证": 16,
        "小批量订单": 10,
        "规模量产和重复订单": 12,
        "多客户或连续两代产品": 6,
    }
    evidence_scores = {
        "比亚迪电子": {
            "战略意愿明确": 0.60,
            "专属团队形成": 0.25,
            "直接产品和规格形成": 0.0,
            "关键器件与专属产线准备": 0.0,
            "互操作和可靠性通过": 0.0,
            "正式客户验证": 0.0,
            "小批量订单": 0.0,
            "规模量产和重复订单": 0.0,
            "多客户或连续两代产品": 0.0,
        },
        "立讯精密": {
            "战略意愿明确": 1.0,
            "专属团队形成": 0.75,
            "直接产品和规格形成": 1.0,
            "关键器件与专属产线准备": 0.60,
            "互操作和可靠性通过": 0.80,
            "正式客户验证": 0.55,
            "小批量订单": 0.65,
            "规模量产和重复订单": 0.25,
            "多客户或连续两代产品": 0.30,
        },
    }
    evidence_maps = {
        "比亚迪电子": {
            "战略意愿明确": (["byd_ir_20260330", "byde_ar_2025"], "AI基础设施方向明确，但光模块本身尚未成为公司明确披露的产品战略，因此只记部分完成。"),
            "专属团队形成": (["byd_recruitment_2026"], "集团招聘出现光通信与光芯片方向，但未披露具体用人主体、人数、地点和数据中心产品任务。"),
            "直接产品和规格形成": (["byde_product_page", "byde_idce_2026"], "当前官方产品页和展会回顾未提供800G或1.6T规格，不能用卖方转述补齐。"),
            "关键器件与专属产线准备": (["byde_ar_2025", "byd_vertilite_stake"], "没有专属设备、产线、良率或器件锁产证据，小比例上游持股不等于供货保障。"),
            "互操作和可靠性通过": (["byde_idce_2026"], "没有找到数据中心高速光模块互操作或可靠性原始记录。"),
            "正式客户验证": (["byde_ar_2025", "byde_product_page"], "宽泛AI基础设施客户不能映射成具体光模块资格。"),
            "小批量订单": (["byde_ar_2025"], "9.43亿元AI基础设施收入没有拆出光模块，不能视为光模块小批量。"),
            "规模量产和重复订单": (["byde_ar_2025", "byd_weak_rumor_202607"], "量产和海外交付仅见于未核传闻，未进入核心事实。"),
            "多客户或连续两代产品": (["byde_product_page"], "没有多客户或800G至1.6T连续商业化的直接披露。"),
        },
        "立讯精密": {
            "战略意愿明确": (["luxshare_ar_2025", "luxshare_ir_20260420"], "公司连续披露光互连和下一代架构投入。"),
            "专属团队形成": (["luxshare_us_optical_recruitment", "luxshare_ar_2025"], "公开岗位覆盖高速光模块工程、客户资格和量产，但无法据此获得完整团队人数。"),
            "直接产品和规格形成": (["luxshare_product_matrix", "luxshare_ar_2025"], "10G至1.6T产品矩阵和上市公司研发项目均可核验。"),
            "关键器件与专属产线准备": (["luxshare_ir_20251126", "xinqiang_supplier_ipo"], "可确认外部器件平台、PCB采购和后端工艺活动，但专属高端产能及良率未公开。"),
            "互操作和可靠性通过": (["keysight_luxshare_ofc2024", "oif_luxshare_2024", "poet_luxshare_2024"], "多厂商互操作和光引擎集成真实，但2024年材料较旧且低于客户长期资格。"),
            "正式客户验证": (["luxshare_ar_2025", "luxshare_ir_20250828"], "部分产品验证可确认，头部云客户正式资格仍没有公开闭环。"),
            "小批量订单": (["luxshare_ar_2025", "luxshare_ir_20250828"], "中小数据中心客户小批量成立；不同产品和客户阶段不能合并成全球规模量产。"),
            "规模量产和重复订单": (["luxshare_interactive_20260428", "luxshare_ir_20260525"], "收入仍小、头部客户仍早期接洽，重复订单和连续季度规模不可得。"),
            "多客户或连续两代产品": (["luxshare_ar_2025", "luxshare_product_matrix"], "跨代产品布局存在，但多客户跨代重复供货未被客户或财务资料验证。"),
        },
    }
    ledgers: dict[str, Any] = {}
    for company, scores in evidence_scores.items():
        rows = []
        total = 0.0
        for milestone, weight in weights.items():
            contribution = weight * scores[milestone]
            total += contribution
            rows.append(
                {
                    "milestone": milestone,
                    "weight_pct": weight,
                    "completion": scores[milestone],
                    "contribution": _round(contribution, 1),
                    "evidence_refs": evidence_maps[company][milestone][0],
                    "rationale": evidence_maps[company][milestone][1],
                }
            )
        ledgers[company] = {
            "rows": rows,
            "evidence_score": _round(total, 1),
            "aggregation_caveat": "这是跨产品、跨客户的证据成熟度检查，不是同一SKU的严格漏斗，也不把总分机械映射为概率。",
        }

    shared_states = {
        "3y": {
            "low": [
                {"state": "认证和器件约束偏强", "weight": 0.45, "byd": 0.05, "luxshare": 0.42},
                {"state": "产业条件中性", "weight": 0.45, "byd": 0.13, "luxshare": 0.58},
                {"state": "需求强且器件供给改善", "weight": 0.10, "byd": 0.24, "luxshare": 0.76},
            ],
            "central": [
                {"state": "认证和器件约束偏强", "weight": 0.30, "byd": 0.08, "luxshare": 0.48},
                {"state": "产业条件中性", "weight": 0.50, "byd": 0.18, "luxshare": 0.65},
                {"state": "需求强且器件供给改善", "weight": 0.20, "byd": 0.30, "luxshare": 0.82},
            ],
            "high": [
                {"state": "认证和器件约束偏强", "weight": 0.15, "byd": 0.12, "luxshare": 0.55},
                {"state": "产业条件中性", "weight": 0.50, "byd": 0.22, "luxshare": 0.72},
                {"state": "需求强且器件供给改善", "weight": 0.35, "byd": 0.36, "luxshare": 0.88},
            ],
        },
        "5y": {
            "low": [
                {"state": "认证和器件约束偏强", "weight": 0.40, "byd": 0.13, "luxshare": 0.58},
                {"state": "产业条件中性", "weight": 0.50, "byd": 0.25, "luxshare": 0.72},
                {"state": "需求强且器件供给改善", "weight": 0.10, "byd": 0.40, "luxshare": 0.87},
            ],
            "central": [
                {"state": "认证和器件约束偏强", "weight": 0.25, "byd": 0.18, "luxshare": 0.65},
                {"state": "产业条件中性", "weight": 0.50, "byd": 0.32, "luxshare": 0.80},
                {"state": "需求强且器件供给改善", "weight": 0.25, "byd": 0.48, "luxshare": 0.92},
            ],
            "high": [
                {"state": "认证和器件约束偏强", "weight": 0.10, "byd": 0.25, "luxshare": 0.72},
                {"state": "产业条件中性", "weight": 0.50, "byd": 0.40, "luxshare": 0.85},
                {"state": "需求强且器件供给改善", "weight": 0.40, "byd": 0.55, "luxshare": 0.96},
            ],
        },
    }
    joint_results = {
        horizon: {case: _joint_probability(states) for case, states in cases.items()}
        for horizon, cases in shared_states.items()
    }
    residual_dependence_sensitivity = {
        horizon: {
            f"剩余正向联动系数{dependence:.2f}": _joint_probability(
                cases["central"], within_state_positive_dependence=dependence
            )
            for dependence in (0.0, 0.15, 0.30)
        }
        for horizon, cases in shared_states.items()
    }
    competition_distributions = {
        "3y": {
            "需求继续吸收新增供给": {"温和竞争加剧_pct": 70, "明显竞争恶化_pct": 25, "严重结构性恶化_pct": 5},
            "基准判断": {"温和竞争加剧_pct": 62, "明显竞争恶化_pct": 29, "严重结构性恶化_pct": 9},
            "供给释放且架构变化不利": {"温和竞争加剧_pct": 55, "明显竞争恶化_pct": 33, "严重结构性恶化_pct": 12},
        },
        "5y": {
            "需求继续吸收新增供给": {"温和竞争加剧_pct": 60, "明显竞争恶化_pct": 30, "严重结构性恶化_pct": 10},
            "基准判断": {"温和竞争加剧_pct": 53, "明显竞争恶化_pct": 35, "严重结构性恶化_pct": 12},
            "供给释放且架构变化不利": {"温和竞争加剧_pct": 45, "明显竞争恶化_pct": 35, "严重结构性恶化_pct": 20},
        },
    }
    damage_central: dict[str, int] = {}
    damage_ranges: dict[str, list[int]] = {}
    for company in ("innolight", "eoptolink"):
        for horizon in ("3y", "5y"):
            central_entry = joint_results[horizon]["central"]["at_least_one_pct"] / 100
            central_bad = sum(
                competition_distributions[horizon]["基准判断"][key]
                for key in ("明显竞争恶化_pct", "严重结构性恶化_pct")
            ) / 100
            central = central_entry * central_bad
            low_entry = joint_results[horizon]["low"]["at_least_one_pct"] / 100
            high_entry = joint_results[horizon]["high"]["at_least_one_pct"] / 100
            low_bad = sum(
                competition_distributions[horizon]["需求继续吸收新增供给"][key]
                for key in ("明显竞争恶化_pct", "严重结构性恶化_pct")
            ) / 100
            high_bad = sum(
                competition_distributions[horizon]["供给释放且架构变化不利"][key]
                for key in ("明显竞争恶化_pct", "严重结构性恶化_pct")
            ) / 100
            low = low_entry * low_bad
            high = high_entry * high_bad
            damage_central[f"{company}_{horizon}"] = round(central * 100)
            damage_ranges[f"{company}_{horizon}"] = [round(low * 100), round(high * 100)]
    significant_damage = {
        "definition": "2031年归母净利润或2026—2031年累计自由现金流至少一项较无新增进入者基线低20%。",
        "formula": "显著损失概率＝至少一家有意义进入概率×（明显竞争恶化概率＋严重结构性恶化概率）。明显与严重两档已经把需求吸收、产品升级和现金转换是否足以抵消竞争压力计入分档，因此不再重复乘一个主观的公司抵消系数。",
        "company_scope_note": "当前公开数据不足以稳健区分两家公司跨过20%损失阈值的条件概率，因此对中际旭创和新易盛使用同一事件概率；这不是两个独立的公司概率。公司差异只在情景收入、利润金额、现金转换和累计自由现金流中分别计算。",
        "sensitivity_method": "下界使用低进入概率和需求继续吸收新增供给时的明显加严重概率；上界使用高进入概率和供给释放、架构变化不利时的明显加严重概率。",
        "central_pct": damage_central,
        "sensitivity_range_pct": damage_ranges,
    }
    regional_central = {
        "byd": {"china_3y": 15, "global_3y": 8, "china_5y": 28, "global_5y": 16},
        "luxshare": {"china_3y": 57, "global_3y": 32, "china_5y": 71, "global_5y": 50},
    }
    company_keys = {"byd": "byd_pct", "luxshare": "luxshare_pct"}
    regional_only_china_bounds: dict[str, dict[str, list[float]]] = {}
    for company, total_key in company_keys.items():
        regional_only_china_bounds[company] = {}
        for horizon in ("3y", "5y"):
            total = joint_results[horizon]["central"][total_key]
            china = regional_central[company][f"china_{horizon}"]
            global_ = regional_central[company][f"global_{horizon}"]
            intersection_low = max(0.0, china + global_ - total)
            intersection_high = min(china, global_)
            regional_only_china_bounds[company][horizon] = [
                _round(china - intersection_high, 1),
                _round(china - intersection_low, 1),
            ]
    return {
        "event_contract": {
            "market_denominator": "800G及以上AI数据中心可插拔光模块、LPO/LRO模块和CPO/NPO光引擎的滚动12个月收入；排除PON、传统电信相干、车载光通信和纯铜缆AEC/DAC。",
            "global_threshold": "滚动12个月收入份额达到全球2%，并至少连续两个季度形成收入。",
            "china_threshold": "同一口径下中国客户体系收入份额达到5%，并至少连续两个季度形成收入。",
            "commercial_continuity": "至少一家正式客户资格、首个批量订单，以及相隔不少于90天的第二个商业订单；同时具备第二客户或下一代产品中的至少一项。",
            "strict_threshold": "全球份额达到5%、至少两家正式客户且连续两代产品形成批量收入。",
            "horizon_definition": "3年和5年均为自2026年7月22日起计算的累计事件，分别截至2029年7月22日和2031年7月22日；一旦在较早期限内满足，较长期限仍记为已发生。",
        },
        "prior_method": {
            "description": "没有同口径历史大样本，因此不用经验频率冒充先验。起始区间按可核验商业阶段划分：多元制造企业尚无直接产品时，3年5%—25%、5年15%—45%；已有直接产品、小批量和部分客户验证时，3年45%—80%、5年60%—90%。区间参考Fabrinet资格流程、AAOI/Jabil/Foxconn等相邻进入案例和当前公司阶段，但属于未校准的结构化专家判断。",
            "non_external_fact": True,
            "calibration_limit": "案例异质、样本少且公开披露存在选择偏差，区间是敏感性范围，不是统计置信区间。",
        },
        "milestone_weights_non_external_fact": weights,
        "milestone_ledgers": ledgers,
        "shared_industry_states_non_external_fact": shared_states,
        "within_state_dependence_method": "中心值在给定共享产业状态后使用条件独立近似；报告另测剩余正向联动系数0、0.15和0.30。系数把状态内同时进入概率从p×q推向min(p,q)，不是相关系数。",
        "residual_dependence_sensitivity_pct": residual_dependence_sensitivity,
        "joint_results_pct": joint_results,
        "regional_event_contract": {
            "china": "满足有意义进入的商业连续性条件，且收入主要由中国客户体系贡献。",
            "global": "满足有意义进入的商业连续性条件，并进入至少一家非中国头部云厂商、交换平台或其直接ODM/OEM的正式供应体系。",
            "relationship": "中国事件和全球事件都是总进入事件的子集，但公司可同时服务两类客户，二者不是互斥分类。公开资料不足以确定交集，因此只对‘仅中国’给可行范围。",
        },
        "regional_central_pct": regional_central,
        "only_china_feasible_range_pct": regional_only_china_bounds,
        "threshold_sensitivity_pct": {
            "宽松：正式客户小批量且全球份额约1%": {"byd_3y": [18, 35], "byd_5y": [35, 55], "luxshare_3y": [70, 85], "luxshare_5y": [80, 95]},
            "基准：全球2%或中国5%并形成重复订单": {"byd_3y": [11, 25], "byd_5y": [22, 45], "luxshare_3y": [53, 75], "luxshare_5y": [68, 88]},
            "严格：全球5%、两家客户且连续两代": {"byd_3y": [3, 10], "byd_5y": [8, 20], "luxshare_3y": [30, 50], "luxshare_5y": [45, 70]},
        },
        "competition_severity_contract": {
            "温和或可吸收的竞争加剧": "在把需求吸收和龙头产品升级计入后，2031年归母净利润和2026—2031年累计自由现金流均较无新增进入者基线下降不足20%。",
            "明显竞争恶化": "在把需求吸收和龙头产品升级计入后，至少一项下降20%至30%，并能由份额、同代额外降价、毛利率或现金转换中的至少两项结果端指标解释。",
            "严重结构性恶化": "在把需求吸收和龙头产品升级计入后，至少一项下降30%以上，且价格、份额或架构冲击持续两年以上。",
        },
        "competition_distribution_method": "各情景比例为未校准的结构化专家判断，不是历史频率。证据桥依次观察需求能否吸收、上游器件能否释放、新进入者是否完成全球复购、同代价格是否额外下降，以及龙头是否守住新架构。",
        "conditional_competition_distributions_pct_non_external_fact": True,
        "conditional_competition_distributions_pct": competition_distributions,
        "significant_damage_probability": significant_damage,
    }


def build_model() -> dict[str, Any]:
    actuals = {
        "innolight": {
            "2023": {"revenue_cny_100m": 107.18, "parent_net_income_cny_100m": 21.74, "operating_cash_flow_cny_100m": 18.97, "capex_cny_100m": 17.04, "free_cash_flow_cny_100m": 1.93},
            "2024": {"revenue_cny_100m": 238.62, "parent_net_income_cny_100m": 51.71, "operating_cash_flow_cny_100m": 31.65, "capex_cny_100m": 28.66, "free_cash_flow_cny_100m": 2.99},
            "2025": {"revenue_cny_100m": 382.40, "parent_net_income_cny_100m": 107.97, "operating_cash_flow_cny_100m": 108.96, "capex_cny_100m": 27.60, "optical_gross_margin_pct": 42.61},
            "2026q1": {"revenue_cny_100m": 194.96, "parent_net_income_cny_100m": 57.35, "operating_cash_flow_cny_100m": 33.68, "capex_cny_100m": 19.29, "gross_margin_pct": 46.06},
        },
        "eoptolink": {
            "2023": {"revenue_cny_100m": 30.98, "parent_net_income_cny_100m": 6.88, "operating_cash_flow_cny_100m": 12.46, "capex_cny_100m": 5.54, "free_cash_flow_cny_100m": 6.92},
            "2024": {"revenue_cny_100m": 86.47, "parent_net_income_cny_100m": 28.38, "operating_cash_flow_cny_100m": 6.41, "capex_cny_100m": 14.76, "free_cash_flow_cny_100m": -8.35},
            "2025": {"revenue_cny_100m": 248.42, "parent_net_income_cny_100m": 95.32, "operating_cash_flow_cny_100m": 77.01, "capex_cny_100m": 13.20, "optical_gross_margin_pct": 47.81},
            "2026q1": {"revenue_cny_100m": 83.38, "parent_net_income_cny_100m": 27.80, "operating_cash_flow_cny_100m": 6.84, "capex_cny_100m": 6.31, "gross_margin_pct": 49.16},
        },
        "luxshare": {
            "2025": {
                "revenue_cny_100m": 3323.44,
                "parent_net_income_cny_100m": 166.00,
                "operating_cash_flow_cny_100m": 173.25,
                "capex_cny_100m": 179.04,
                "gross_margin_pct": 11.91,
                "roe_pct": 21.52,
                "roa_pct": 7.66,
                "total_assets_cny_100m": 3065.38,
                "total_equity_cny_100m": 1040.20,
            },
        },
        "byd": {
            "2025": {
                "revenue_cny_100m": 8039.65,
                "parent_net_income_cny_100m": 326.19,
                "operating_cash_flow_cny_100m": 591.36,
                "capex_cny_100m": 1568.08,
                "gross_margin_pct": 17.74,
                "roe_pct": 15.12,
                "roa_pct": 4.78,
                "total_assets_cny_100m": 8837.30,
                "total_equity_cny_100m": 2585.39,
            },
        },
    }
    baseline = {
        "innolight": _forecast(
            [800, 1000, 1180, 1320, 1410, 1460],
            [0.445, 0.438, 0.428, 0.418, 0.408, 0.400],
            [0.295, 0.288, 0.280, 0.270, 0.260, 0.250],
            [0.95, 0.97, 0.98, 0.99, 1.00, 1.00],
            [45, 46, 46, 44, 40, 35],
        ),
        "eoptolink": _forecast(
            [360, 450, 530, 585, 625, 655],
            [0.480, 0.465, 0.450, 0.435, 0.420, 0.410],
            [0.340, 0.325, 0.310, 0.295, 0.280, 0.270],
            [0.85, 0.88, 0.91, 0.93, 0.95, 0.95],
            [25, 22, 19, 18, 16, 12],
        ),
    }
    zero = [0.0] * 6
    one = [1.0] * 6
    scenario_specs = {
        "没有新增公司形成有意义规模": {
            "volume_share_effect": zero,
            "extra_asp_pressure": zero,
            "demand_mix_offset": zero,
            "gross_margin_hit_pp": zero,
            "cash_conversion_hit_pp": zero,
            "capex_multiplier": one,
        },
        "立讯形成规模、比亚迪仍处研发或区域供货": {
            "volume_share_effect": [0, 0.005, 0.015, 0.025, 0.040, 0.060],
            "extra_asp_pressure": [0, 0.005, 0.015, 0.020, 0.030, 0.040],
            "demand_mix_offset": [0, 0.004, 0.008, 0.010, 0.010, 0.010],
            "gross_margin_hit_pp": [0, 0.2, 0.6, 1.0, 1.5, 2.0],
            "cash_conversion_hit_pp": [0, 0.5, 0.8, 1.2, 1.6, 2.0],
            "capex_multiplier": [1.00, 1.02, 1.04, 1.05, 1.05, 1.03],
        },
        "比亚迪形成规模、立讯影响有限": {
            "volume_share_effect": [0, 0.002, 0.008, 0.015, 0.025, 0.040],
            "extra_asp_pressure": [0, 0.003, 0.010, 0.015, 0.020, 0.030],
            "demand_mix_offset": [0, 0.003, 0.006, 0.008, 0.010, 0.010],
            "gross_margin_hit_pp": [0, 0.1, 0.3, 0.6, 0.9, 1.3],
            "cash_conversion_hit_pp": [0, 0.2, 0.5, 0.8, 1.0, 1.3],
            "capex_multiplier": [1.00, 1.01, 1.02, 1.03, 1.03, 1.02],
        },
        "两家公司进入但主要局限于中国客户": {
            "volume_share_effect": [0, 0.004, 0.010, 0.018, 0.025, 0.030],
            "extra_asp_pressure": [0, 0.004, 0.010, 0.015, 0.022, 0.030],
            "demand_mix_offset": [0, 0.003, 0.006, 0.008, 0.010, 0.010],
            "gross_margin_hit_pp": [0, 0.2, 0.4, 0.7, 1.0, 1.2],
            "cash_conversion_hit_pp": [0, 0.3, 0.6, 0.9, 1.2, 1.5],
            "capex_multiplier": [1.00, 1.01, 1.02, 1.03, 1.03, 1.02],
        },
        "至少一家成为全球头部客户的重要第二供应商": {
            "volume_share_effect": [0, 0.010, 0.030, 0.050, 0.075, 0.100],
            "extra_asp_pressure": [0, 0.010, 0.025, 0.040, 0.060, 0.080],
            "demand_mix_offset": [0, 0.006, 0.010, 0.012, 0.012, 0.010],
            "gross_margin_hit_pp": [0, 0.4, 0.9, 1.5, 2.5, 3.5],
            "cash_conversion_hit_pp": [0, 0.8, 1.5, 2.5, 3.3, 4.0],
            "capex_multiplier": [1.00, 1.03, 1.08, 1.10, 1.10, 1.05],
        },
        "两家公司全球突破并用低价和组合方案抢份额": {
            "volume_share_effect": [0, 0.015, 0.050, 0.090, 0.140, 0.180],
            "extra_asp_pressure": [0, 0.015, 0.035, 0.070, 0.110, 0.150],
            "demand_mix_offset": [0, 0.005, 0.010, 0.012, 0.012, 0.010],
            "gross_margin_hit_pp": [0, 0.7, 1.8, 3.0, 5.0, 7.0],
            "cash_conversion_hit_pp": [0, 1.0, 2.5, 4.0, 6.0, 8.0],
            "capex_multiplier": [1.00, 1.05, 1.12, 1.18, 1.18, 1.10],
        },
        "光引擎和共封装加快、价值向平台与核心器件迁移": {
            "volume_share_effect": [0, 0.005, 0.020, 0.040, 0.075, 0.120],
            "extra_asp_pressure": [0, 0.005, 0.015, 0.030, 0.050, 0.080],
            "demand_mix_offset": [0, 0.002, 0.004, 0.004, 0.003, 0.000],
            "gross_margin_hit_pp": [0, 0.3, 0.8, 1.5, 2.4, 3.2],
            "cash_conversion_hit_pp": [0.5, 1.0, 2.0, 3.0, 4.0, 5.0],
            "capex_multiplier": [1.02, 1.08, 1.15, 1.18, 1.15, 1.08],
        },
    }
    scenarios: dict[str, Any] = {}
    for scenario, spec in scenario_specs.items():
        scenarios[scenario] = {}
        for company, rows in baseline.items():
            stressed = _stress(rows, **spec)
            scenarios[scenario][company] = {
                "annual": stressed,
                "cumulative_fcf_2026_2031_cny_100m": _round(sum(float(row["free_cash_flow_cny_100m"]) for row in stressed)),
                "cash_flow_diagnostic": _cash_flow_diagnostic(stressed, 0.11, 0.03, 0.15),
            }

    entrant_baseline = {
        "luxshare": {
            "revenue_cny_100m": [3900, 4500, 5100, 5650, 6100, 6500],
            "parent_net_income_cny_100m": [210, 260, 310, 350, 385, 420],
            "baseline_basis": "从2025年集团实际值出发，通信、汽车和消费电子分别建桥；没有把光模块规模化写入基线。",
        },
        "byd": {
            "revenue_cny_100m": [8800, 9700, 10700, 11600, 12400, 13100],
            "parent_net_income_cny_100m": [400, 480, 560, 630, 690, 750],
            "baseline_basis": "从2025年集团实际值出发，汽车销量、单车盈利、海外和电池业务构成主基线；光模块只作为条件增量。",
        },
    }
    entrant_case_inputs = {
        "luxshare": {
            "listed_parent_attribution": 1.0,
            "working_capital_rate": 0.10,
            "scenarios": {
                "停留在样品和小批量": {
                    "optical_revenue": [3, 5, 8, 10, 12, 15],
                    "optical_net_margin": [-0.02, 0.00, 0.03, 0.04, 0.05, 0.06],
                    "optical_capex": [8, 5, 3, 2, 2, 2],
                },
                "在中国客户形成规模": {
                    "optical_revenue": [6, 20, 60, 95, 135, 180],
                    "optical_net_margin": [-0.03, 0.01, 0.05, 0.06, 0.07, 0.075],
                    "optical_capex": [12, 15, 18, 15, 12, 10],
                },
                "成为全球重要第二供应商": {
                    "optical_revenue": [10, 45, 150, 260, 380, 500],
                    "optical_net_margin": [-0.03, 0.02, 0.08, 0.10, 0.11, 0.12],
                    "optical_capex": [15, 25, 35, 30, 25, 20],
                },
                "以低价和组合销售快速扩张": {
                    "optical_revenue": [15, 80, 250, 430, 620, 800],
                    "optical_net_margin": [-0.05, 0.00, 0.06, 0.07, 0.075, 0.08],
                    "optical_capex": [20, 35, 50, 45, 35, 30],
                },
            },
        },
        "byd": {
            # 比亚迪电子是潜在经营承载主体；比亚迪股份的归母增量只按其
            # 对非全资子公司的经济归属计入，避免把子公司利润100%归母。
            "listed_parent_attribution": 0.6576,
            "working_capital_rate": 0.12,
            "scenarios": {
                "停留在研发和样品": {
                    "optical_revenue": [0, 1, 3, 5, 8, 10],
                    "optical_net_margin": [-0.10, -0.05, -0.02, 0.00, 0.01, 0.02],
                    "optical_capex": [4, 5, 4, 3, 2, 2],
                },
                "在中国客户形成规模": {
                    "optical_revenue": [1, 5, 20, 45, 80, 120],
                    "optical_net_margin": [-0.05, -0.02, 0.02, 0.04, 0.05, 0.06],
                    "optical_capex": [5, 10, 15, 12, 10, 8],
                },
                "成为全球重要第二供应商": {
                    "optical_revenue": [1, 10, 50, 100, 190, 300],
                    "optical_net_margin": [-0.05, -0.02, 0.03, 0.05, 0.06, 0.07],
                    "optical_capex": [8, 20, 30, 25, 20, 15],
                },
                "以低价和组合销售快速扩张": {
                    "optical_revenue": [2, 20, 80, 180, 320, 500],
                    "optical_net_margin": [-0.08, -0.04, 0.01, 0.03, 0.04, 0.05],
                    "optical_capex": [12, 30, 50, 45, 35, 25],
                },
            },
        },
    }
    entrant_business_cases: dict[str, Any] = {}
    for company, company_inputs in entrant_case_inputs.items():
        company_baseline = entrant_baseline[company]
        entrant_business_cases[company] = {}
        for scenario_name, case_inputs in company_inputs["scenarios"].items():
            entrant_business_cases[company][scenario_name] = _entrant_business_case(
                baseline_revenue=company_baseline["revenue_cny_100m"],
                baseline_parent_net_income=company_baseline["parent_net_income_cny_100m"],
                optical_revenue=case_inputs["optical_revenue"],
                optical_net_margin=case_inputs["optical_net_margin"],
                optical_capex=case_inputs["optical_capex"],
                parent_attribution=company_inputs["listed_parent_attribution"],
                working_capital_rate=company_inputs["working_capital_rate"],
            )

    independent_valuation_diagnostics: dict[str, Any] = {}
    for company, rows in baseline.items():
        dcf_grid = {}
        for required_return in (0.09, 0.11, 0.13):
            for growth in (0.02, 0.03, 0.04):
                key = f"回报要求{required_return:.0%}__长期增长{growth:.0%}"
                dcf_grid[key] = _cash_flow_diagnostic(rows, required_return, growth, 0.15)
        independent_valuation_diagnostics[company] = {
            "method_applicability": {
                "市盈率与反向市盈率": "需要在独立模型冻结后读取市场价格，放入外部对账文件，不回写本模型。",
                "股权现金流": "缺完整净举债、净现金和少数股东桥，只作零净举债敏感性，不作为正式目标价值。",
                "企业价值倍数": "缺可审计EBITDA、净债务和少数股东预测，关闭。",
                "市净率与剩余收益": "账面净资产不是高速光模块超额回报的主要经营驱动，只保留当前PB背景，不形成目标值。",
                "市销率": "竞争情景直接改变毛利率和现金转换，同一收入对应价值差异过大，关闭。",
                "股利折现": "高增长扩产期没有稳定分红合同，关闭。",
            },
            "cash_flow_sensitivity_grid": dcf_grid,
        }

    result: dict[str, Any] = {
        "model_name": "Run13 比亚迪与立讯进入高速光模块的独立概率与经营压力模型",
        "model_version": "run13.independent_model.v4",
        "frozen_before_external_consensus": True,
        "external_consensus_inputs_present": False,
        "freeze_date": "2026-07-23",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "actuals": actuals,
        "historical_data_provenance": {
            "provider": "公司年报、Wind内网HTTP与Tushare逐字段复核",
            "source_contract": "2025年度收入、归母净利润、经营现金流、购建长期资产现金支出、总资产、权益及ROE/ROA以公司年报口径为最终权威，Wind单证券窄字段用于结构化复核，Tushare仅逐字段补缺；自由现金流为经营现金流减该资本开支代理。",
        },
        "industry_demand": [
            {"year": year, "ai_cluster_optics_market_usd_bn": value, "status": "公开行业锚" if year == 2026 else "独立需求情景，非外部预测"}
            for year, value in zip(YEARS, [26, 33, 39, 45, 50, 54])
        ],
        "architecture_mix_assumption_pct": {
            "2026": {"800G": 55, "1.6T": 40, "3.2T": 1, "CPO或NPO光引擎": 2, "其他": 2},
            "2031": {"800G": 10, "1.6T": 45, "3.2T": 23, "CPO或NPO光引擎": 17, "其他": 5},
        },
        "effective_supply_contract": "有效供给＝名义产能×客户资格覆盖率×可持续良率×关键器件到位率。公开资料没有统一口径的厂商名义产能和良率，因此不伪造逐厂商件数；以产品代际、资格、批量、上游约束和重复订单判断供给是否有效。",
        "financial_model_level": {
            "level": "Level 3 财务桥接与条件压力测试",
            "why_not_level_1_or_2": "公司没有公开按800G、1.6T、3.2T及客户拆分的出货量、同代ASP、有效产能、良率和营运资本，因此不能建立可审计的产品量价或市场份额模型。",
            "baseline_method": "2026—2028收入先以2026年一季度、公司订单/产品节奏和行业需求锚定，2029—2031逐年降低增速；净利润由收入×净利率得到，经营现金流由净利润×现金转换率得到，自由现金流再扣资本开支。每个年度的收入、毛利率、净利率、现金转换率和资本开支均直接列在baseline中，均为独立研究假设而非公司指引。",
            "use_boundary": "用于比较竞争情景、识别结果阈值和当前估值需要的盈利强度，不输出正式目标价，也不声称替代完整三表模型。",
        },
        "baseline": baseline,
        "entrant_group_baseline_non_external_fact": entrant_baseline,
        "entrant_case_inputs_non_external_fact": entrant_case_inputs,
        "entrant_business_cases": entrant_business_cases,
        "scenario_specs_non_external_fact": scenario_specs,
        "scenarios": scenarios,
        "probability_model": _probability_model(),
        "independent_valuation_diagnostics": independent_valuation_diagnostics,
        "formulas": {
            "demand": "可服务模块量＝AI节点或交换端口量×每节点光互联强度×光连接比例×对应代际占比。",
            "effective_supply": "有效供给＝名义产能×客户资格覆盖率×可持续良率×关键器件到位率。",
            "scenario_revenue": "情景收入＝基线收入×（1－份额或销量损失）×（1－额外ASP压力）×（1＋需求与产品组合缓冲）。",
            "scenario_profit": "情景净利润＝情景收入×〔基线净利率－毛利率额外下降×75%〕。",
            "scenario_cash": "情景自由现金流＝情景净利润×（基线现金转换率－情景折损）－基线资本开支×扩产倍数。",
            "entrant_parent_profit": "上市公司归母增量＝光模块收入×光模块净利率×上市公司经济归属比例；集团合并收入按100%计入，非全资子公司的归母利润不按100%计入。",
            "entrant_project_cash": "光模块项目自由现金流＝项目净利润－专属资本开支－新增收入×营运资金占用率。",
            "joint_probability": "联合概率先在每个共享产业状态内计算两家公司同时进入，再按状态权重加总；至少一家进入＝比亚迪边际概率＋立讯边际概率－两家同时进入概率。",
            "significant_damage": "显著损失概率＝至少一家进入概率×明显或严重竞争的条件概率；明显与严重分档已经计入需求吸收和产品升级，避免重复乘主观抵消系数。",
        },
        "limitations": [
            "概率权重、共享状态权重和未来情景参数都是明确标注的研究判断，不是外部事实，也没有足够历史样本校准。",
            "2027—2031行业总量和架构占比为独立情景；公司没有公开按代际、客户、距离和形态拆分的销量与ASP。",
            "竞争情景是条件压力测试，不是概率加权后的盈利预测；没有把主观概率直接乘进收入和利润。",
            "现金流敏感性缺净现金、净举债和少数股东完整桥，不能称为正式目标价值；市场价格、市盈率和聚合预测全部留到冻结后的外部对账。",
            "所有金额为亿元人民币，行业市场为十亿美元；归母净利润与集团总净利润没有混用。",
        ],
    }
    result["content_sha256"] = _hash(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_model()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "sha256": payload["content_sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
