from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = (
    ROOT / "cache" / "copper_research" / "models" / "copper_supply_demand_model_v1.json"
)


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _finite(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} 必须是有限数")
    return number


def _sum_components(components: dict[str, float], name: str) -> float:
    total = 0.0
    for key, value in components.items():
        total += _finite(value, f"{name}.{key}")
    return round(total, 6)


def _validate_series(rows: list[dict[str, Any]]) -> None:
    years = [int(row["year"]) for row in rows]
    if years != sorted(years) or len(years) != len(set(years)):
        raise ValueError("供需序列年份必须严格递增且不重复")
    for row in rows:
        supply = _finite(row["refined_supply_mt"], "refined_supply_mt")
        demand = _finite(row["refined_usage_mt"], "refined_usage_mt")
        balance = _finite(row["refined_balance_mt"], "refined_balance_mt")
        if abs((supply - demand) - balance) > 1e-6:
            raise ValueError(f"{row['year']} 年精炼铜供需平衡无法勾稽")


def build_model() -> dict[str, Any]:
    source_register = [
        {
            "source_id": "icsg_forecast_20260423",
            "title": "ICSG Copper Market Forecast 2026–2027",
            "publisher": "International Copper Study Group",
            "date": "2026-04-23",
            "source_channel": "web",
            "source_level": "行业组织原始统计与预测",
            "locator": "papers/铜/2026-04-23_ICSG_铜市场预测2026-2027_官方.pdf",
            "use": "2025—2027 年矿山产量、精炼铜产量、精炼铜消费与供需平衡锚点",
        },
        {
            "source_id": "icsg_tables_202607",
            "title": "ICSG Copper Bulletin Tables, July 2026",
            "publisher": "International Copper Study Group",
            "date": "2026-07",
            "source_channel": "web",
            "source_level": "行业组织原始月度统计",
            "locator": "papers/铜/2026-07_ICSG_铜月报表1_官方.pdf",
            "use": "核验 2025 年全年和 2026 年 1—5 月矿山利用率、精炼铜供需与库存",
        },
        {
            "source_id": "iea_gcm_2026",
            "title": "Global Critical Minerals Outlook 2026",
            "publisher": "International Energy Agency",
            "date": "2026",
            "source_channel": "web",
            "source_level": "国际组织原始研究",
            "locator": "papers/铜/2026_IEA_全球关键矿产展望_官方.pdf",
            "use": "2035 年结构性缺口、再生铜、冶炼集中度和长期需求方向",
        },
        {
            "source_id": "usgs_mcs_2026",
            "title": "Mineral Commodity Summaries 2026 — Copper",
            "publisher": "U.S. Geological Survey",
            "date": "2026",
            "source_channel": "web",
            "source_level": "政府原始统计",
            "locator": "papers/铜/2026_USGS_矿产品摘要_铜_官方.pdf",
            "use": "2025 年主要国家矿山产量、储量和美国供需结构",
        },
        {
            "source_id": "pacific_copper_20260705",
            "title": "铜行业供需平衡与价格展望",
            "publisher": "太平洋证券",
            "date": "2026-07-05",
            "source_channel": "report",
            "source_level": "卖方行业模型",
            "locator": "papers/铜",
            "use": "2028 年需求与新增项目供给的外部对账，不作为官方事实",
        },
        {
            "source_id": "orient_copper_20260721",
            "title": "铜：新兴需求与项目爬坡",
            "publisher": "东方证券",
            "date": "2026-07-21",
            "source_channel": "report",
            "source_level": "卖方行业模型",
            "locator": "papers/铜",
            "use": "数据中心用铜和项目爬坡的外部对账，不作为官方事实",
        },
    ]

    official_anchor = [
        {
            "year": 2025,
            "mine_supply_mt": 23.197,
            "refined_supply_mt": 28.656,
            "refined_usage_mt": 28.201,
            "refined_balance_mt": 0.455,
            "status": "ICSG 2026年4月估计",
            "source_id": "icsg_forecast_20260423",
        },
        {
            "year": 2026,
            "mine_supply_mt": 23.559,
            "refined_supply_mt": 28.760,
            "refined_usage_mt": 28.664,
            "refined_balance_mt": 0.096,
            "status": "ICSG 2026年4月预测",
            "source_id": "icsg_forecast_20260423",
        },
        {
            "year": 2027,
            "mine_supply_mt": 24.103,
            "refined_supply_mt": 29.613,
            "refined_usage_mt": 29.236,
            "refined_balance_mt": 0.377,
            "status": "ICSG 2026年4月预测",
            "source_id": "icsg_forecast_20260423",
        },
    ]
    _validate_series(official_anchor)

    demand_increment_assumptions = {
        2028: {
            "电网与电力设备": 0.22,
            "新能源汽车与充电设施": 0.16,
            "新能源发电与储能": 0.10,
            "数据中心直接用铜": 0.10,
            "建筑": -0.02,
            "家电与一般制造": 0.12,
            "节材与铝替代": -0.04,
        },
        2029: {
            "电网与电力设备": 0.24,
            "新能源汽车与充电设施": 0.18,
            "新能源发电与储能": 0.11,
            "数据中心直接用铜": 0.12,
            "建筑": 0.02,
            "家电与一般制造": 0.13,
            "节材与铝替代": -0.05,
        },
        2030: {
            "电网与电力设备": 0.26,
            "新能源汽车与充电设施": 0.20,
            "新能源发电与储能": 0.12,
            "数据中心直接用铜": 0.14,
            "建筑": 0.05,
            "家电与一般制造": 0.14,
            "节材与铝替代": -0.06,
        },
    }
    expected_demand_increments = {2028: 0.64, 2029: 0.75, 2030: 0.85}
    for year, components in demand_increment_assumptions.items():
        total = _sum_components(components, f"demand_increment.{year}")
        if abs(total - expected_demand_increments[year]) > 1e-9:
            raise ValueError(f"{year} 年需求增量分项与合计不一致")

    base_extension_inputs = {
        2028: {
            "mine_supply_mt": 24.40,
            "refined_supply_mt": 30.05,
            "secondary_refined_mt": 5.75,
        },
        2029: {
            "mine_supply_mt": 24.70,
            "refined_supply_mt": 30.60,
            "secondary_refined_mt": 6.00,
        },
        2030: {
            "mine_supply_mt": 25.00,
            "refined_supply_mt": 31.15,
            "secondary_refined_mt": 6.25,
        },
    }
    base_rows = [dict(row) for row in official_anchor]
    previous_demand = official_anchor[-1]["refined_usage_mt"]
    for year in (2028, 2029, 2030):
        demand = previous_demand + expected_demand_increments[year]
        inputs = base_extension_inputs[year]
        refined_supply = inputs["refined_supply_mt"]
        base_rows.append(
            {
                "year": year,
                "mine_supply_mt": inputs["mine_supply_mt"],
                "refined_supply_mt": refined_supply,
                "secondary_refined_mt": inputs["secondary_refined_mt"],
                "primary_refined_mt": round(
                    refined_supply - inputs["secondary_refined_mt"], 3
                ),
                "refined_usage_mt": round(demand, 3),
                "refined_balance_mt": round(refined_supply - demand, 3),
                "status": "本研究基准估算",
                "source_id": "internal_model_after_icsg_anchor",
                "demand_increment_mt": expected_demand_increments[year],
            }
        )
        previous_demand = demand
    _validate_series(base_rows)

    scenario_adjustments = {
        "供应宽松情景": {
            "description": (
                "主要爬坡项目大体按期、废铜回收较强，同时建筑需求偏弱；"
                "相对基准增加精炼供给并减少消费。"
            ),
            "supply_delta_mt": {2028: 0.20, 2029: 0.35, 2030: 0.50},
            "demand_delta_mt": {2028: -0.12, 2029: -0.20, 2030: -0.28},
        },
        "基准情景": {
            "description": (
                "ICSG 2027 年锚点之后，项目投产、矿山品位下降和爬坡损失部分抵消；"
                "电网、电动车和数据中心推动需求，但建筑恢复有限且存在节材替代。"
            ),
            "supply_delta_mt": {2028: 0.0, 2029: 0.0, 2030: 0.0},
            "demand_delta_mt": {2028: 0.0, 2029: 0.0, 2030: 0.0},
        },
        "供应受限情景": {
            "description": (
                "Kamoa、QB、Cobre Panamá 等大型资产至少一项低于计划，"
                "资源国政策或社区冲突增加，同时电网和数据中心需求较强。"
            ),
            "supply_delta_mt": {2028: -0.30, 2029: -0.55, 2030: -0.80},
            "demand_delta_mt": {2028: 0.16, 2029: 0.28, 2030: 0.40},
        },
    }
    scenarios: dict[str, list[dict[str, Any]]] = {}
    base_by_year = {row["year"]: row for row in base_rows}
    for scenario_name, adjustment in scenario_adjustments.items():
        rows: list[dict[str, Any]] = []
        for year in (2028, 2029, 2030):
            base = base_by_year[year]
            supply = base["refined_supply_mt"] + adjustment["supply_delta_mt"][year]
            demand = base["refined_usage_mt"] + adjustment["demand_delta_mt"][year]
            rows.append(
                {
                    "year": year,
                    "refined_supply_mt": round(supply, 3),
                    "refined_usage_mt": round(demand, 3),
                    "refined_balance_mt": round(supply - demand, 3),
                    "supply_delta_vs_base_mt": adjustment["supply_delta_mt"][year],
                    "demand_delta_vs_base_mt": adjustment["demand_delta_mt"][year],
                }
            )
        _validate_series(rows)
        scenarios[scenario_name] = rows

    project_ledger = [
        {
            "project": "Kamoa-Kakula",
            "country": "刚果（金）",
            "operator": "Ivanhoe Mines / Zijin",
            "current_or_guidance": (
                "2026年29—33万吨，2027年38—42万吨；2028年起年化产量超过50万吨"
            ),
            "increment_timing": "2026—2028恢复与爬坡",
            "base_model_role": "2027—2029矿山增量的重要组成",
            "main_risk": "地下水、地震活动、供电与修复进度",
            "source": "Ivanhoe Mines 2026-03-31及2026-07-08官方更新",
        },
        {
            "project": "Oyu Tolgoi地下矿",
            "country": "蒙古",
            "operator": "Rio Tinto",
            "current_or_guidance": "2028—2036年平均约50万吨/年",
            "increment_timing": "2026—2028爬坡",
            "base_model_role": "较确定的中期新增供给",
            "main_risk": "地下矿爬坡、政府收益分配与治理争议",
            "source": "Rio Tinto 2026年生产与蒙古协议更新",
        },
        {
            "project": "Grasberg地下矿恢复",
            "country": "印度尼西亚",
            "operator": "Freeport-McMoRan",
            "current_or_guidance": (
                "2026年约10亿磅；2027—2029年平均约16亿磅，分阶段恢复"
            ),
            "increment_timing": "2026—2027恢复",
            "base_model_role": "2026低基数后的恢复性供给",
            "main_risk": "恢复进度、尾矿与印尼国内加工要求",
            "source": "Freeport-McMoRan 2026年官方运营更新",
        },
        {
            "project": "Quebrada Blanca二期",
            "country": "智利",
            "operator": "Teck / partners",
            "current_or_guidance": (
                "2026年20—23.5万吨，2027年24—27.5万吨，2028年22—25.5万吨"
            ),
            "increment_timing": "2026—2028产能与回收率改善",
            "base_model_role": "增量低于早期设计预期",
            "main_risk": "尾矿设施、回收率和稳定运行",
            "source": "Teck 2026年产量指引",
        },
        {
            "project": "Centinela第二选厂",
            "country": "智利",
            "operator": "Antofagasta",
            "current_or_guidance": "新增铜产量约14.4万吨/年",
            "increment_timing": "2027年投产与爬坡",
            "base_model_role": "2028—2030新增供给",
            "main_risk": "建设进度、资本开支约44亿美元与爬坡",
            "source": "Antofagasta项目官方更新",
        },
        {
            "project": "Tía María",
            "country": "秘鲁",
            "operator": "Southern Copper",
            "current_or_guidance": "计划约12万吨/年，目标2027年投产",
            "increment_timing": "2027—2029",
            "base_model_role": "基准只计入部分产量",
            "main_risk": "社区关系、许可与建设节奏",
            "source": "Southern Copper 2026年官方项目更新",
        },
        {
            "project": "Cobre Panamá",
            "country": "巴拿马",
            "operator": "First Quantum Minerals",
            "current_or_guidance": "截至2026年仍处于安全维护，尚无重启决定",
            "increment_timing": "不计入基准持续产量",
            "base_model_role": "供应宽松情景的上行期权",
            "main_risk": "采矿合同、环境审计、政府与社会许可",
            "source": "First Quantum及巴拿马政府2026年公开更新",
        },
        {
            "project": "Escondida新选厂",
            "country": "智利",
            "operator": "BHP",
            "current_or_guidance": (
                "替代性新增能力约22—26万吨/年，预计2031—2032年首产"
            ),
            "increment_timing": "2030年前不形成主要增量",
            "base_model_role": "不计入2026—2030基准新增",
            "main_risk": "资本开支44—59亿美元、许可和建设",
            "source": "BHP 2026年项目更新",
        },
    ]

    country_policy = [
        {
            "country": "智利",
            "policy_or_constraint": (
                "2024年起矿业特许税：大型矿企包含1%从价税及按利润率计征部分，"
                "综合税负设上限"
            ),
            "transmission": "提高边际项目所需铜价并压缩矿企现金流，但不等同于减产",
            "companies_or_projects": "Escondida、Los Bronces、Centinela及紫金在塞尔维亚以外的同业比较",
            "investment_monitor": "投资决定、许可周期与单位资本开支",
        },
        {
            "country": "刚果（金）",
            "policy_or_constraint": (
                "2018年矿法提高权利金并取消长期稳定条款；地方分成、社区基金、"
                "电力和硫酸供应共同影响经营"
            ),
            "transmission": "高铜价下政府分成上升，营运资金与现金汇回折价扩大",
            "companies_or_projects": "洛阳钼业TFM/KFM、紫金Kamoa与Kolwezi",
            "investment_monitor": "出口政策、税费结算、电力、硫酸和股息汇回",
        },
        {
            "country": "秘鲁",
            "policy_or_constraint": "社区协商、道路封锁与许可执行是高于法定税率变化的短期变量",
            "transmission": "通过停产天数、运输中断和额外社区支出影响产量与C1成本",
            "companies_or_projects": "五矿资源Las Bambas、Tía María",
            "investment_monitor": "道路可用率、社区协议和政府协调",
        },
        {
            "country": "印度尼西亚",
            "policy_or_constraint": "延续下游化与国内冶炼要求，进口关税不是主要约束",
            "transmission": "增加冶炼资本开支和投产风险，改变精矿外销与国内销售结构",
            "companies_or_projects": "Grasberg及全球精矿市场",
            "investment_monitor": "冶炼厂利用率、出口许可和资源权益延续",
        },
        {
            "country": "蒙古",
            "policy_or_constraint": "围绕Oyu Tolgoi股东贷款利息、管理费和收益分配持续谈判",
            "transmission": "当前更直接影响现金分配和治理折价，而非已投产矿体的物理产量",
            "companies_or_projects": "Oyu Tolgoi及其供应增量",
            "investment_monitor": "协议执行、税务争议和地下矿爬坡",
        },
        {
            "country": "赞比亚",
            "policy_or_constraint": "铜价联动权利金与本地采购比例提高并行",
            "transmission": "高价期资源国分成增加，本地采购可能抬升或重构成本",
            "companies_or_projects": "区域新增项目与非洲铜带边际供给",
            "investment_monitor": "税制稳定性、电力和本地供应链能力",
        },
        {
            "country": "美国",
            "policy_or_constraint": (
                "2025年232措施对半成品和衍生品征收关税，矿石、精矿、阴极铜、"
                "阳极铜与废铜豁免，并提高国内销售和废铜留存要求"
            ),
            "transmission": "更可能造成地区价差、加工链迁移和库存重分布，而非全球铜短缺本身",
            "companies_or_projects": "美国进口链、废铜和铜加工企业",
            "investment_monitor": "关税口径、COMEX/LME价差和美国库存",
        },
    ]

    top_country_supply = [
        {"country": "智利", "mine_2025_kt": 5300, "reserves_2025_kt": 180000},
        {"country": "刚果（金）", "mine_2025_kt": 3200, "reserves_2025_kt": 80000},
        {"country": "秘鲁", "mine_2025_kt": 2700, "reserves_2025_kt": 85000},
        {"country": "中国", "mine_2025_kt": 1800, "reserves_2025_kt": 41000},
        {"country": "俄罗斯", "mine_2025_kt": 1300, "reserves_2025_kt": 80000},
        {"country": "赞比亚", "mine_2025_kt": 940, "reserves_2025_kt": 21000},
        {"country": "澳大利亚", "mine_2025_kt": 730, "reserves_2025_kt": 100000},
        {"country": "印度尼西亚", "mine_2025_kt": 710, "reserves_2025_kt": 21000},
    ]
    world_mine_2025 = 23000.0
    world_reserves_2025 = 980000.0
    for row in top_country_supply:
        row["world_mine_share"] = round(row["mine_2025_kt"] / world_mine_2025, 4)
        row["world_reserve_share"] = round(
            row["reserves_2025_kt"] / world_reserves_2025, 4
        )

    methodology = {
        "core_formula": (
            "精炼铜供需余额＝精炼铜产量－精炼铜消费；"
            "远期消费＝上年消费＋电网＋新能源汽车＋新能源发电与储能＋"
            "数据中心直接用铜＋建筑＋一般制造－节材与替代；"
            "情景余额＝基准供给＋项目/回收调整－（基准需求＋需求强弱调整）。"
        ),
        "anchor_rule": (
            "2025—2027年完全采用ICSG 2026年4月口径；2028—2030年才使用本研究假设，"
            "且不把IEA 2035年缺口机械摊入每一年。"
        ),
        "demand_scope_rule": (
            "数据中心只计服务器、配电和园区内直接用铜的研究增量；"
            "电网扩容放在“电网与电力设备”，避免把同一批铜同时归入AI和电网。"
        ),
        "supply_scope_rule": (
            "矿山产量、精炼铜产量和再生精炼铜分别列示。矿山新增不能直接等同于"
            "当年精炼铜新增，冶炼检修、精矿品位、库存与加工费会造成时间差。"
        ),
        "precision_boundary": (
            "2028—2030年结果只用于区分宽松、近均衡和短缺方向；"
            "0.01万吨级的小数不具有预测精度，公开报告按十万吨或更粗粒度解释。"
        ),
    }

    model_payload = {
        "schema_version": "copper.supply_demand_model.v1",
        "as_of_date": "2026-07-26",
        "unit": "million tonnes copper content",
        "methodology": methodology,
        "official_anchor": official_anchor,
        "demand_increment_assumptions": demand_increment_assumptions,
        "base_extension_inputs": base_extension_inputs,
        "base_series": base_rows,
        "scenario_definitions": scenario_adjustments,
        "scenarios": scenarios,
        "project_ledger": project_ledger,
        "country_policy_transmission": country_policy,
        "top_country_supply_and_reserves": top_country_supply,
        "source_register": source_register,
        "external_reconciliation": {
            "industry_report_ranges": [
                {
                    "source_id": "pacific_copper_20260705",
                    "metric": "global_refined_usage_mt",
                    "values": {2026: 28.29, 2027: 29.23, 2028: 30.08},
                    "comparison": (
                        "本研究2026—2027沿用ICSG；2028基准29.876Mt，"
                        "较该报告低0.204Mt，主要因建筑恢复和数据中心直接用铜口径更保守。"
                    ),
                },
                {
                    "source_id": "orient_copper_20260721",
                    "metric": "data_center_copper_demand_mt",
                    "values": {2025: 0.59, 2030: 1.40},
                    "comparison": (
                        "该值更接近广义数据中心及相关电力链口径；本研究只把直接用铜增量"
                        "计入数据中心，其余归入电网，以降低重复计算。"
                    ),
                },
            ],
            "long_term_check": (
                "IEA基于已宣布项目的基准情景指向2035年约25%的供应缺口。"
                "本模型2030年基准仅出现约0.33Mt短缺，二者不冲突：IEA缺口位于更远期限，"
                "还包含矿山开发周期、品位下降及长期需求累积。本研究不将其机械前移。"
            ),
        },
        "limitations": [
            (
                "ICSG的中国表观消费不包含未报告库存变动，2026年1—5月库存显著增加，"
                "因此年度表观余额与真实终端消费可能偏离。"
            ),
            (
                "2028—2030项目产量缺少统一的项目级可比披露；本研究把投产概率、爬坡损失"
                "和再生铜增量合并进情景调整，不输出伪精确的单矿概率。"
            ),
            (
                "数据中心与电网需求在外部研究中常有范围重叠，本模型采用互斥口径，"
                "因此不能直接与采用广义AI电力基础设施口径的报告单点比较。"
            ),
            (
                "供需余额是价格环境的重要变量，但库存、地区价差、美元、利率、投机仓位"
                "和冶炼端扰动也会使短期铜价偏离年度平衡。"
            ),
        ],
    }
    return model_payload


def main() -> int:
    parser = argparse.ArgumentParser(description="构建铜行业供需与项目情景模型")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    payload = build_model()
    payload["content_sha256"] = _sha256(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": payload["content_sha256"],
                "base_2030_balance_mt": payload["base_series"][-1][
                    "refined_balance_mt"
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
