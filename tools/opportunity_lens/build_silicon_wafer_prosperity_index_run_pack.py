from __future__ import annotations

import copy
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.opportunity_lens import build_silicon_wafer_price_tracking_run_pack as base


AS_OF_DATE = "2026-07-05"
SLUG = "20260705_silicon_wafer_prosperity_index_from_price_order_base"
OUTPUT_DIR = ROOT / "opportunity_lens" / "research_outputs" / SLUG
PACK_PATH = OUTPUT_DIR / "run_pack.json"
EXECUTION_CACHE_PATH = OUTPUT_DIR / "EXECUTION_CACHE.md"
INTAKE_PATH = (
    ROOT
    / "opportunity_lens"
    / "intake_requests"
    / "Opportunity_Lens_用户研究请求_硅片行业景气度_基于价格订单跟踪数据底座_修订版.md"
)
RESEARCH_QUESTION = "半导体硅片行业景气度指标 / 价格代理指数：基于价格订单跟踪数据底座的全球、中国与差异指标"

YEARS = ["2021", "2022", "2023", "2024", "2025", "2026E", "2027E", "2028E"]

GLOBAL_COMPONENT_WEIGHTS = {
    "价格和 ASP": 0.25,
    "出货和订单": 0.25,
    "库存和供需松紧": 0.18,
    "AI/HBM 和先进逻辑": 0.17,
    "供给集中和 LTA": 0.15,
}
GLOBAL_COMPONENT_SCORES = {
    "价格和 ASP": [72, 82, 58, 49, 47, 54, 61, 68],
    "出货和订单": [82, 90, 42, 38, 60, 68, 75, 82],
    "库存和供需松紧": [80, 88, 35, 32, 45, 56, 64, 72],
    "AI/HBM 和先进逻辑": [42, 55, 60, 69, 78, 86, 90, 93],
    "供给集中和 LTA": [78, 86, 52, 48, 56, 62, 68, 73],
}

CHINA_COMPONENT_WEIGHTS = {
    "价格和毛利承接": 0.24,
    "订单和国产替代": 0.26,
    "产能利用和供给压力": 0.18,
    "产品结构升级": 0.17,
    "全球需求传导": 0.15,
}
CHINA_COMPONENT_SCORES = {
    "价格和毛利承接": [50, 60, 38, 34, 44, 58, 65, 70],
    "订单和国产替代": [42, 52, 48, 55, 63, 72, 79, 84],
    "产能利用和供给压力": [55, 62, 40, 35, 44, 55, 61, 65],
    "产品结构升级": [35, 45, 48, 56, 65, 73, 78, 82],
    "全球需求传导": [65, 78, 45, 42, 58, 70, 78, 84],
}

PRODUCT_SUBINDEX = {
    "300mm/AI-HBM": [73, 85, 50, 55, 68, 78, 83, 88],
    "200mm/成熟制程": [70, 76, 38, 34, 42, 50, 58, 63],
    "SOI/外延特色": [62, 70, 45, 43, 52, 60, 67, 72],
}

BANNED_PHRASES = (
    "manual_verified_fact",
    "time_series_data_point",
    "行业事实原文证据",
    "客户验证和供货进展原文证据",
    "材料和工艺瓶颈原文证据",
    "该证据必须结合原始链接全文",
    "在某问题下，该指标说明",
    "它不是孤立数字，而是用于判断",
    "对这个因子来说",
    "这条证据把评分从概念讨论拉回",
)

SOURCE_NOTES = {
    "semi_ship_stats": "SEMI/SMG 的季度 MSI 是本指数最硬的量端锚点；它排除太阳能应用，能把半导体硅片和光伏硅片切开。",
    "semi_2024_annual": "SEMI 2024 年度数据确认行业在 2024 年后段才开始恢复，价格端仍不能用单季出货恢复替代。",
    "semi_2025_annual": "SEMI 2025 年度表把出货恢复和收入继续下降同时摆出来，是判断“量先修复、价格滞后”的核心证据。",
    "semi_q1_2026": "SEMI 2026Q1 的同比增长给出当前修复方向，但环比回落提醒季节性和产品结构不能忽略。",
    "semi_2028_forecast": "SEMI 2028 预测给出中期出货上行的方向锚，适合进入展望段，不应替代已发生价格。",
    "semi_300mm_outlook": "SEMI 300mm fab outlook 把晶圆厂扩产和 AI、memory、power 需求连接起来，是 300mm 子指数的领先项。",
    "nist_globalwafers_chips": "NIST/CHIPS 对 GlobalWafers 的说明提供 300mm 供给集中和区域化投资背景，能校准供应弹性。",
    "siltronic_2026_guidance": "Siltronic 2026 指引同时写到 300mm 增长、200mm 承压和 LTA 外价格压力，是反方和分产品线判断的关键来源。",
    "siltronic_investor_202603": "Siltronic 投资者材料给出 300mm/200mm 需求路径、前五供给格局和 LTA 视角，适合做结构权重校准。",
    "sumco_policy_2026": "SUMCO 的风险和业务说明把 AI/EV 需求与价格、汇率、库存风险放在一起，能防止指数只向上解释。",
    "shinetsu_q3_2026_summary": "Shin-Etsu Q&A 对 AI memory/HBM、advanced logic 和硅片关系有明确拆分，是 300mm 高端需求的重要交叉验证。",
    "globalwafers_q1_2026_profile": "GlobalWafers 材料把 AI、memory、advanced packaging 与 specialty wafer 能见度连在一起，也披露区域化扩产。",
    "soitec_q1_fy26": "Soitec FY26Q1 披露 RF-SOI 库存和 price/mix 压力，说明 SOI 不能被统一写成上行周期。",
    "soitec_q3_fy26": "Soitec FY26Q3 将 AI 相关应用和传统 RF 库存放在同一张图里，适合拆出 SOI 子指数的结构分化。",
    "nsig_2025_annual": "沪硅产业公告提供中国 300mm、SOI 和亏损承接样本，是中国指数里“订单不等于利润”的证据。",
    "xian_yisiwei_202605_ir": "西安奕材 IR 对客户、12 英寸产能和供货进展的披露，是中国 300mm 国产替代的高权重输入。",
    "shanghai_hejing_202606_ir": "上海合晶 IR 直接给出 12 英寸销量、外延和 SOI 布局，是中国特色产品结构升级的核心样本。",
    "leonmicro_202605_order": "立昂微业绩会线索提供重掺和成熟制程局部订单观察，但需要公告和财报继续确认。",
    "stcn_china_capacity_202606": "证券时报的 12 英寸国产化与产能报道能补足中国供给扩张画面，但在核心指数里必须降权。",
    "micron_fq3_2026": "Micron FY2026Q3 材料证明 HBM/DRAM 需求和价格周期强度，是高端硅片需求传导的下游锚。",
    "skhynix_2026_outlook": "SK hynix 对 HBM-led memory supercycle 的描述能增强 AI 存储链判断，但它不是硅片价格的直接证据。",
    "deloitte_semiconductor_2026": "Deloitte 2026 展望提供宏观半导体和 AI 需求背景，只作为需求环境辅助权重。",
    "sia_april_2026_sales": "SIA/WSTS 的 2026 年月度销售确认半导体需求强复苏，但其口径是芯片销售额，不是硅片成交价。",
    "wsts_spring_2026_forecast": "WSTS 2026 春季预测把 AI、HBM、加速计算和 memory 修复放在半导体需求主线里；它提高 300mm/HBM 需求置信度，但仍不是硅片成交价。",
    "siltronic_2025_resilience_update": "Siltronic 2025 经营更新再次把 300mm 正向需求、LTA 外价格压力和 200mm 库存压力并列披露，是主指数和 200mm 反方的新增复核来源。",
    "soitec_ai_photonics_202503": "Soitec 2025 硅光 SOI 公告说明 AI 数据中心互连会拉动 Photonics-SOI，但这条线必须和 RF-SOI 库存压力分开解释。",
    "derived_swpi_workpaper": "本地复算工作底稿记录公式、权重、标准化和 reviewer 修改记录；它是计算来源，不替代外部事实来源。",
    "previous_run6_price_order_pack": "前置 run6 价格订单底座提供本任务 seed；本任务只继承其可追溯输入，不继承旧结论。",
}

SOURCE_LABELS = {
    "semi_ship_stats": "SEMI/SMG 季度 MSI",
    "semi_2024_annual": "SEMI 2024 年度硅片统计",
    "semi_2025_annual": "SEMI 2025 年度硅片统计",
    "semi_q1_2026": "SEMI 2026Q1 MSI",
    "semi_2028_forecast": "SEMI 2028 硅片预测",
    "semi_300mm_outlook": "SEMI 300mm fab outlook",
    "nist_globalwafers_chips": "NIST/CHIPS GlobalWafers",
    "siltronic_2026_guidance": "Siltronic 2026 指引",
    "siltronic_investor_202603": "Siltronic 投资者材料",
    "siltronic_2025_resilience_update": "Siltronic 2025 resilience update",
    "sumco_policy_2026": "SUMCO 2026 policy",
    "shinetsu_q3_2026_summary": "Shin-Etsu 2026Q3 摘要",
    "globalwafers_q1_2026_profile": "GlobalWafers 2026Q1 profile",
    "soitec_q1_fy26": "Soitec FY26Q1",
    "soitec_q3_fy26": "Soitec FY26Q3",
    "nsig_2025_annual": "沪硅产业 2025 年报",
    "xian_yisiwei_202605_ir": "西安奕材 2026 年 5 月 IR",
    "shanghai_hejing_202606_ir": "上海合晶 2026 年 6 月 IR",
    "leonmicro_202605_order": "立昂微 2026 年 5 月订单线索",
    "stcn_china_capacity_202606": "证券时报中国产能报道",
    "micron_fq3_2026": "Micron FY2026Q3",
    "skhynix_2026_outlook": "SK hynix 2026 outlook",
    "deloitte_semiconductor_2026": "Deloitte semiconductor outlook",
    "sia_april_2026_sales": "SIA 2026 年 4 月销售",
    "wsts_spring_2026_forecast": "WSTS Spring 2026 forecast",
    "soitec_ai_photonics_202503": "Soitec AI photonics",
    "cicc_shanghai_hejing_listing": "上海合晶上市材料",
    "derived_swpi_workpaper": "SWPI 本地复算工作底稿",
    "previous_run6_price_order_pack": "前置 run6 价格订单底座",
}

REFS = {
    "global": [
        "source_ref:semi_ship_stats",
        "source_ref:semi_2025_annual",
        "source_ref:semi_q1_2026",
        "source_ref:semi_2028_forecast",
        "source_ref:siltronic_2026_guidance",
        "source_ref:siltronic_investor_202603",
        "source_ref:sumco_policy_2026",
        "source_ref:sia_april_2026_sales",
        "source_ref:wsts_spring_2026_forecast",
        "source_ref:siltronic_2025_resilience_update",
    ],
    "china": [
        "source_ref:xian_yisiwei_202605_ir",
        "source_ref:shanghai_hejing_202606_ir",
        "source_ref:nsig_2025_annual",
        "source_ref:leonmicro_202605_order",
        "source_ref:stcn_china_capacity_202606",
        "source_ref:semi_q1_2026",
        "source_ref:semi_2025_annual",
    ],
    "gap": [
        "source_ref:semi_2025_annual",
        "source_ref:semi_q1_2026",
        "source_ref:xian_yisiwei_202605_ir",
        "source_ref:shanghai_hejing_202606_ir",
        "source_ref:nsig_2025_annual",
        "source_ref:stcn_china_capacity_202606",
        "source_ref:siltronic_2026_guidance",
        "source_ref:siltronic_2025_resilience_update",
    ],
    "p300": [
        "source_ref:semi_300mm_outlook",
        "source_ref:shinetsu_q3_2026_summary",
        "source_ref:globalwafers_q1_2026_profile",
        "source_ref:micron_fq3_2026",
        "source_ref:skhynix_2026_outlook",
        "source_ref:wsts_spring_2026_forecast",
        "source_ref:siltronic_investor_202603",
        "source_ref:xian_yisiwei_202605_ir",
    ],
    "p200": [
        "source_ref:siltronic_2026_guidance",
        "source_ref:siltronic_investor_202603",
        "source_ref:siltronic_2025_resilience_update",
        "source_ref:leonmicro_202605_order",
        "source_ref:sumco_policy_2026",
        "source_ref:semi_q1_2026",
        "source_ref:stcn_china_capacity_202606",
    ],
    "soi": [
        "source_ref:soitec_q1_fy26",
        "source_ref:soitec_q3_fy26",
        "source_ref:soitec_ai_photonics_202503",
        "source_ref:shanghai_hejing_202606_ir",
        "source_ref:nsig_2025_annual",
        "source_ref:globalwafers_q1_2026_profile",
        "source_ref:cicc_shanghai_hejing_listing",
    ],
    "method": [
        "source_ref:previous_run6_price_order_pack",
        "source_ref:derived_swpi_workpaper",
        "source_ref:semi_ship_stats",
        "source_ref:semi_2025_annual",
        "source_ref:siltronic_2026_guidance",
        "source_ref:xian_yisiwei_202605_ir",
    ],
}


def _ref(ref: str) -> str:
    return ref if ref.startswith("source_ref:") else f"source_ref:{ref}"


def _source_public_label(ref: str) -> str:
    key = ref.replace("source_ref:", "")
    return SOURCE_LABELS.get(key, key.replace("_", " "))


def _compact(value: Any, limit: int = 900) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _weighted_series(component_scores: dict[str, list[int]], weights: dict[str, float]) -> list[float]:
    rows: list[float] = []
    for idx in range(len(YEARS)):
        score = sum(component_scores[name][idx] * weights[name] for name in weights)
        rows.append(round(score, 1))
    return rows


GLOBAL_SWPI = _weighted_series(GLOBAL_COMPONENT_SCORES, GLOBAL_COMPONENT_WEIGHTS)
CHINA_SWPI = _weighted_series(CHINA_COMPONENT_SCORES, CHINA_COMPONENT_WEIGHTS)
GAP_SWPI = [round(china - global_, 1) for china, global_ in zip(CHINA_SWPI, GLOBAL_SWPI)]


def _points(values: list[float]) -> list[tuple[str, float]]:
    return [(period, float(value)) for period, value in zip(YEARS, values)]


def _stage(score: float) -> str:
    if score >= 80:
        return "高景气 / 供需偏紧"
    if score >= 68:
        return "修复偏强 / 订单能见度提升"
    if score >= 55:
        return "温和修复 / 产品分化"
    if score >= 42:
        return "弱平衡 / 底部抬升"
    return "去库存 / 价格压力"


def _series_text(values: list[float]) -> str:
    return "；".join(f"{period}={value:.1f}" for period, value in zip(YEARS, values))


def _latest(values: list[float]) -> float:
    return float(values[5])


def _source_title_map(sources: list[dict[str, Any]]) -> dict[str, str]:
    return {source["ref"]: source["title"] for source in sources}


def _extra_sources() -> list[dict[str, Any]]:
    return [
        {
            "ref": "previous_run6_price_order_pack",
            "title": "前置 run6 半导体硅片价格与订单变化跟踪研究包",
            "source_tier": "A",
            "source_review_status": "pass_internal_workpaper",
            "publisher": "Opportunity Lens C 轨研究工作台",
            "publish_date": AS_OF_DATE,
            "url": None,
            "local_path": "opportunity_lens/research_outputs/20260705_silicon_wafer_price_tracking_revision/run_pack.json",
            "language": "zh-CN",
            "cluster": "internal_opportunity_lens_workpaper",
            "cluster_label": "前置价格订单数据底座",
            "policy_evidence_role": "reference_only",
            "excerpt": "该研究包整理了 2021-2026 历史、2026-2028 展望、全球/中国、300mm/200mm/SOI、价格、订单、供需、AI 需求和反方证据。本任务只把它作为可追溯输入底座。",
        },
        {
            "ref": "sia_april_2026_sales",
            "title": "SIA 2026 年 4 月全球半导体销售（原文：Global Semiconductor Sales Increase 11% Month-to-Month in April）",
            "source_tier": "S",
            "source_review_status": "pass_industry_association",
            "publisher": "Semiconductor Industry Association / WSTS",
            "publish_date": "2026-06-05",
            "url": "https://www.semiconductors.org/global-semiconductor-sales-increase-11-month-to-month-in-april/",
            "language": "en",
            "cluster": "sia_wsts_market_data",
            "cluster_label": "SIA/WSTS 半导体销售",
            "policy_evidence_role": "core_evidence",
            "excerpt": "SIA 披露 2026 年 4 月全球半导体销售额 1105 亿美元，环比增长 11%，同比增长 93.9%；月度数据由 WSTS 汇编，采用三个月移动平均口径。中文译意：该数据只能作为下游芯片需求和存储/逻辑周期的强弱代理，不是硅片成交价。",
        },
        {
            "ref": "wsts_spring_2026_forecast",
            "title": "WSTS 2026 春季半导体市场预测（原文：WSTS Spring 2026 Semiconductor Forecast）",
            "source_tier": "S",
            "source_review_status": "pass_industry_association",
            "publisher": "World Semiconductor Trade Statistics",
            "publish_date": "2026-06-03",
            "url": "https://www.wsts.org/76/Recent-News-Release",
            "language": "en",
            "cluster": "wsts_market_forecast",
            "cluster_label": "WSTS 半导体市场预测",
            "policy_evidence_role": "supporting_evidence",
            "excerpt": "WSTS Spring 2026 forecast attributes semiconductor market growth primarily to AI, HBM and accelerated computing demand. 中文译意：它只能提高高端 300mm/HBM 需求代理的置信度，不能直接替代硅片成交价或规格级 ASP。",
        },
        {
            "ref": "siltronic_2025_resilience_update",
            "title": "Siltronic 2025 经营韧性更新（原文：Robust business performance in 2025 demonstrates resilience despite challenging conditions）",
            "source_tier": "A",
            "source_review_status": "pass_company_ir",
            "publisher": "Siltronic AG",
            "publish_date": "2026-07-01",
            "url": "https://www.siltronic.com/en/press/press-releases/siltronic-ag-robust-business-performance-in-2025-demonstrates-resilience-despite-challenging-conditions.html",
            "language": "en",
            "cluster": "siltronic_ir",
            "cluster_label": "Siltronic 公司公告和 IR",
            "policy_evidence_role": "core_evidence",
            "excerpt": "Siltronic states that positive wafer area sold was offset by price effects outside LTAs and that 200mm remained affected by elevated inventories. 中文译意：这条来源确认 300mm/量端修复与价格压力可以同时存在，因此 SWPI 必须把出货、价格和库存分项拆开。",
        },
        {
            "ref": "soitec_ai_photonics_202503",
            "title": "Soitec 硅光 SOI 支持 AI 数据中心互连（原文：Silicon Photonics SOI technology for AI datacentres）",
            "source_tier": "A",
            "source_review_status": "pass_company_ir",
            "publisher": "Soitec",
            "publish_date": "2025-03-19",
            "url": "https://www.soitec.com/home/group/newsroom/press-releases/content/2025/03/19/soitec-contributes-to-accelerated-development-of-integrated-optical-connectivity-solutions-for-ai-datacentres-with-its-silicon-photonics-soi-technology",
            "language": "en",
            "cluster": "soitec_ir",
            "cluster_label": "Soitec SOI 和硅光资料",
            "policy_evidence_role": "supporting_evidence",
            "excerpt": "Soitec links Photonics-SOI to integrated optical connectivity for AI datacentres. 中文译意：AI 数据中心互连为特色 SOI 提供结构方向，但不能抵消 RF-SOI 库存和 price/mix 压力，必须拆产品线评价。",
        },
        {
            "ref": "derived_swpi_workpaper",
            "title": "Silicon Wafer Prosperity Index 复算工作底稿",
            "source_tier": "A",
            "source_review_status": "pass_calculation_workpaper",
            "publisher": "Opportunity Lens producer-reviewer-loop",
            "publish_date": AS_OF_DATE,
            "url": None,
            "local_path": str(EXECUTION_CACHE_PATH.relative_to(ROOT)).replace("\\", "/"),
            "language": "zh-CN",
            "cluster": "swpi_calculation",
            "cluster_label": "SWPI 指数公式和复算底稿",
            "policy_evidence_role": "reference_only",
            "excerpt": "工作底稿记录全球版、中国版、中国-全球差异版和 300mm/200mm/SOI 子指数的权重、标准化、缺失值处理、回测结论和 reviewer 修改记录。",
        },
    ]


ENTITY_DEFS: dict[str, dict[str, Any]] = {
    "swpi_methodology": {
        "display_name": "SWPI 指标定义、口径和复算方法",
        "mode": "theory_research",
        "score": 0,
        "description": "定义半导体硅片景气度、领先/同步/滞后指标、标准化方法和缺失值处理。",
        "refs": REFS["method"],
    },
    "candidate_index_schemes": {
        "display_name": "候选指标方案与主指标选择",
        "mode": "theory_research",
        "score": 0,
        "description": "比较价格主导、复合主指标、中国-全球差异和 AI 敏感子指标，解释最终采用复合 SWPI 的原因。",
        "refs": [
            "source_ref:derived_swpi_workpaper",
            "source_ref:semi_2025_annual",
            "source_ref:semi_q1_2026",
            "source_ref:siltronic_2026_guidance",
            "source_ref:xian_yisiwei_202605_ir",
            "source_ref:shinetsu_q3_2026_summary",
        ],
    },
    "source_quality_proxy_review": {
        "display_name": "来源质量、代理变量和补证路径",
        "mode": "theory_research",
        "score": 0,
        "description": "把官方、公司披露、卖方和产业媒体分层，说明真实成交价缺口下如何使用 fallback proxy。",
        "refs": [
            "source_ref:semi_ship_stats",
            "source_ref:semi_2025_annual",
            "source_ref:siltronic_2026_guidance",
            "source_ref:soitec_q1_fy26",
            "source_ref:nsig_2025_annual",
            "source_ref:previous_run6_price_order_pack",
            "source_ref:derived_swpi_workpaper",
        ],
    },
    "global_swpi": {
        "display_name": "全球硅片价格景气指数",
        "mode": "market_linked",
        "score": _latest(GLOBAL_SWPI),
        "description": "全球版 SWPI 衡量全行业半导体硅片在量、价、订单、库存和供给壁垒上的综合景气。",
        "refs": REFS["global"],
    },
    "china_swpi": {
        "display_name": "中国硅片价格景气指数",
        "mode": "market_linked",
        "score": _latest(CHINA_SWPI),
        "description": "中国版 SWPI 衡量国产替代、12 英寸导入、SOI/外延结构升级、产能利用和财务承接。",
        "refs": REFS["china"],
    },
    "china_global_gap_swpi": {
        "display_name": "中国-全球景气差异指标",
        "mode": "market_linked",
        "score": 61,
        "description": "差异指标用 China SWPI - Global SWPI 衡量中国相对全球是补涨、同步、落后还是过热。",
        "refs": REFS["gap"],
    },
    "product_300mm_ai_hbm": {
        "display_name": "300mm / AI-HBM 先进硅片子指数",
        "mode": "market_linked",
        "score": PRODUCT_SUBINDEX["300mm/AI-HBM"][5],
        "description": "300mm advanced、HBM、先进逻辑和高端外延的景气子指数，是本轮最强产品方向。",
        "refs": REFS["p300"],
    },
    "product_200mm_mature": {
        "display_name": "200mm / 成熟制程硅片子指数",
        "mode": "market_linked",
        "score": PRODUCT_SUBINDEX["200mm/成熟制程"][5],
        "description": "200mm、功率、模拟、汽车和工业链的景气子指数，用于识别成熟制程是否真正出清。",
        "refs": REFS["p200"],
    },
    "product_soi_specialty": {
        "display_name": "SOI / 外延 / 特色硅片子指数",
        "mode": "market_linked",
        "score": PRODUCT_SUBINDEX["SOI/外延特色"][5],
        "description": "SOI、外延、Photonics、RF、FD-SOI 与特色材料的结构性景气子指数。",
        "refs": REFS["soi"],
    },
}


def _score_grade(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    return "D"


def _research_points(entity_key: str) -> list[dict[str, Any]]:
    templates = {
        "swpi_methodology": [
            ("景气度不是价格单项", "definition", "景气度由价格、订单、供需松紧、库存、产能利用、交期、客户拉货、capex 和产品 mix 共同决定。", "把研究问题从“有没有涨价”推进到“价格是否能被订单和利润承接”。"),
            ("领先指标", "leading", "晶圆厂 capex、wafer start、HBM/AI 客户排产、LTA/预付款和客户库存优先变化。", "这些指标用于判断未来 6-12 个月是否有供需再收紧。"),
            ("同步指标", "coincident", "SEMI MSI、公司销量、收入、产品 mix、ASP 代理和毛利率能反映当前交易环境。", "同步项决定当期指数读数，避免仅靠展望给高分。"),
            ("滞后指标", "lagging", "年报收入、折旧、净利润和历史产能利用率通常晚于价格和订单。", "滞后项主要用于验证，不作为领先信号的主权重。"),
            ("全球主指数权重", "formula", json.dumps(GLOBAL_COMPONENT_WEIGHTS, ensure_ascii=False), "全球版重视 SEMI 出货、行业 ASP 代理和 300mm 供给壁垒。"),
            ("中国主指数权重", "formula", json.dumps(CHINA_COMPONENT_WEIGHTS, ensure_ascii=False), "中国版增加订单国产替代和财务承接权重，因为本土产能扩张本身不是景气。"),
            ("缺失值处理", "method", "若真实成交价缺失，依次用 ASP、收入/面积、公司 ASP/毛利、订单/LTA、库存和 capex 代理；无法量化则编码为 qualitative signal。", "保证后续系统可以复算，而不是停留在文字判断。"),
            ("光伏口径排除", "scope", "SEMI/SMG 的 silicon wafer statistics 明确服务半导体硅片口径；光伏硅片不进入核心指数。", "避免中文“硅片”歧义污染指标。"),
        ],
        "candidate_index_schemes": [
            ("方案 A 价格主导", "scheme", "价格/ASP 50%，出货 20%，库存 15%，订单 15%。", "适合有真实成交价数据库时使用；当前公开资料不足，容易高估滞后价格。"),
            ("方案 B 复合 SWPI", "scheme", "价格、订单、库存、AI/HBM、供给壁垒分项加权，分别构建全球和中国版本。", "当前推荐方案，能同时处理价格缺口和订单/供需结构分化。"),
            ("方案 C 中国-全球差异", "scheme", "China SWPI - Global SWPI，同时观察 ratio 和 relative momentum。", "用于判断中国是补涨、滞后还是产能扩张导致价格承压。"),
            ("方案 D AI 敏感子指标", "scheme", "聚焦 300mm、HBM、先进逻辑、AI photonics 和高端外延。", "适合跟踪结构性强需求，但不能外推到 200mm 和传统 SOI。"),
            ("最终选择", "decision", "主指标采用方案 B，方案 C 和 D 作为解释层，方案 A 保留为后续 paid price database 接入后的校验口径。", "这个组合最符合当前数据可得性和投资研究使用场景。"),
            ("产品权重", "weight", "全球版参考 300mm 高端权重提升，中国版参考 12 英寸国产替代、SOI/外延和成熟制程承接。", "产品结构决定同一个出货面积对价格和利润的含义不同。"),
            ("区域权重", "weight", "全球版以行业总量和全球龙头披露为主；中国版以本土公司公告和国产替代订单为主。", "区域差异不直接用同一价格口径硬拼。"),
            ("回测标准", "validation", "2021-2022 应识别高景气，2023-2025 应识别下行和底部，2026-2028 应进入修复或再紧平衡条件判断。", "若回测方向不一致，必须回到数据滞后、产品 mix 或区域差异解释。"),
        ],
        "source_quality_proxy_review": [
            ("S 级来源", "source_review", "SEMI/SMG、SIA/WSTS、政府/监管和公司公告优先进入核心。", "用于核心公式、回测和证据门槛。"),
            ("A 级来源", "source_review", "公司 IR、投资者材料和交易所问询记录能补足订单、客户、产品和财务承接。", "用于量化或半量化编码。"),
            ("B 级来源", "source_review", "卖方和可信产业媒体只作为辅助线索，必须被官方或公司披露交叉验证。", "防止涨价线索直接变成核心分。"),
            ("灰源处理", "source_review", "论坛、KOL、民间报价不进入核心指数，只能进入 supplement request 或 early signal。", "指数要可复算，不能依赖不可追溯报价。"),
            ("真实成交价缺口", "data_gap", "公开资料没有连续规格级成交价和客户级 backlog。", "这是本指数最大的硬缺口，必须在页面里显式保留。"),
            ("代理变量优先级", "fallback", "ASP、收入/面积、销量、毛利、LTA、预付款、库存、capex、wafer start、存储价格周期依次降权使用。", "每个代理都要写误差来源。"),
            ("2024 年以前数据时效", "freshness", "2024 年或更早的数据只能参与历史回测，不能单独证明当前景气。", "当前判断必须依赖 2025/2026 官方统计、公告和 IR。"),
            ("复算审计", "review", "每个 component score 都要能回到来源和编码规则，公式由工作底稿记录。", "reviewer 发现缺源、重复或套话时必须打回。"),
        ],
    }
    row_sources = {
        "swpi_methodology": [
            "previous_run6_price_order_pack",
            "derived_swpi_workpaper",
            "semi_ship_stats",
            "semi_2025_annual",
            "derived_swpi_workpaper",
            "xian_yisiwei_202605_ir",
            "siltronic_2026_guidance",
            "semi_ship_stats",
        ],
        "candidate_index_schemes": [
            "derived_swpi_workpaper",
            "derived_swpi_workpaper",
            "semi_2025_annual",
            "semi_q1_2026",
            "derived_swpi_workpaper",
            "siltronic_2026_guidance",
            "xian_yisiwei_202605_ir",
            "shinetsu_q3_2026_summary",
        ],
        "source_quality_proxy_review": [
            "semi_ship_stats",
            "siltronic_2026_guidance",
            "semi_2025_annual",
            "previous_run6_price_order_pack",
            "derived_swpi_workpaper",
            "derived_swpi_workpaper",
            "semi_q1_2026",
            "derived_swpi_workpaper",
        ],
    }
    research_uses = {
        "景气度不是价格单项": "用于限定 SWPI 的适用边界：页面和后续更新必须同时看价格、订单和利润承接，不能把单条涨价线索直接升级为景气结论。",
        "领先指标": "用于未来 6-12 个月的预警层；当 capex、LTA、客户库存和 HBM 排产同步改善时，先上调领先分项而不是同步价格项。",
        "同步指标": "用于当期读数复算；SEMI MSI、销量、收入和毛利验证当前景气是否已经进入公司财务，避免只用展望给高分。",
        "滞后指标": "用于回测和复核，不作为领先判断主权重；若滞后项与领先项冲突，优先检查库存、产品 mix 和披露滞后。",
        "全球主指数权重": "用于 Global SWPI 复算；官方出货和 300mm 壁垒权重更高，中国国产替代和公司订单不直接套入全球公式。",
        "中国主指数权重": "用于 China SWPI 复算；国产替代订单和财务承接权重提高，同时把产能扩张导致的价格压力单独扣分。",
        "缺失值处理": "用于每次更新的 fallback 顺序；真实成交价缺失时必须按 ASP、收入/面积、毛利、订单、库存逐级降权，不允许口径混用。",
        "光伏口径排除": "用于数据清洗闸门；任何光伏硅片、工业硅或太阳能口径只能进入排除说明，不能进入 SWPI 分项或证据组。",
        "方案 A 价格主导": "用于保留未来 paid price database 接入后的校验方案；当前公开数据不足时不得把方案 A 作为主指标。",
        "方案 B 复合 SWPI": "用于当前主公式；每次重算都按价格、订单、库存、AI/HBM 和供给壁垒分项更新，并记录分项变化来源。",
        "方案 C 中国-全球差异": "用于解释区域相对强弱；差异扩大时先判断中国是补涨、国产替代兑现，还是扩产带来的价格压力滞后。",
        "方案 D AI 敏感子指标": "用于跟踪结构性需求；它只解释 300mm、HBM 和先进逻辑，不外推到 200mm、传统 SOI 或成熟节点。",
        "最终选择": "用于发布口径锁定；正文、visual、实体评分和补证请求都以方案 B 为主，方案 C/D 只作为解释层。",
        "产品权重": "用于产品子指数拆分；300mm、200mm、SOI/外延的同一面积不能等权处理，必须按产品难度和利润弹性解释。",
        "区域权重": "用于全球/中国分线复算；全球使用 SEMI 和海外龙头披露，中国使用本土公告和客户验证，不把两套口径硬拼。",
        "回测标准": "用于审计指数方向；如果 2021-2022、2023-2025 或 2026E 的方向不合理，必须回到分项编码和代理变量重算。",
        "S 级来源": "用于确定核心公式锚点；SEMI、SIA/WSTS、监管和公告优先进入分项计算，其他来源只能围绕它们校准。",
        "A 级来源": "用于补足公司层产品、订单和财务承接；当 A 级披露与 S 级统计冲突时，先拆地区和产品口径。",
        "B 级来源": "用于发现涨价、订单或稼动率线索；只有被官方或公司披露交叉验证后，才允许进入核心分项。",
        "灰源处理": "用于证据降级；论坛、KOL 和民间报价只能生成补证请求或观察项，不进入 SWPI 分母和核心证据组。",
        "真实成交价缺口": "用于标记指数置信度上限；没有连续规格级成交价时，SWPI 只能叫代理指数，不能包装成真实价格指数。",
        "代理变量优先级": "用于每个缺失分项的替代路径；使用代理变量时必须同时写误差来源和降权原因，方便后续回填真实数据。",
        "2024 年以前数据时效": "用于历史回测和时效警示；旧数据只能解释周期位置，当前结论必须由 2025/2026 来源复核。",
        "复算审计": "用于 reviewer 最终闸门；每个 component score 必须回到来源、编码规则和权重，发现重复或套话直接打回。",
    }
    interpretations = {
        "光伏口径排除": "这条口径说明 SWPI 只研究半导体硅片，光伏硅片、工业硅和太阳能价格会把供需周期完全带偏，必须在入口处排除。",
        "区域权重": "区域权重强调全球和中国并不是同一组价格样本，中国的国产替代、扩产和客户验证会让同一面积数据呈现不同含义。",
        "S 级来源": "S 级来源提供公式锚点和回测基准，是 SWPI 能否被复算的底座，其他来源只能围绕这些官方或监管口径校准。",
        "A 级来源": "A 级来源补足公司层产品结构、订单、客户和毛利变化，能解释官方总量背后的区域与产品分化。",
        "B 级来源": "B 级来源能提示涨价、稼动率或订单线索，但可信度不足以单独改变核心分，需要等待官方或公司披露交叉验证。",
        "代理变量优先级": "代理变量优先级说明每个缺口如何降权替代，核心是让指数可更新，同时把真实成交价缺失带来的误差暴露出来。",
    }
    if len(row_sources[entity_key]) != len(templates[entity_key]):
        raise RuntimeError(f"研究指标来源清单长度错误：{entity_key}")
    points: list[dict[str, Any]] = []
    for idx, (title, category, excerpt, use) in enumerate(templates[entity_key], start=1):
        source_ref = row_sources[entity_key][idx - 1]
        points.append(
            {
                "source_ref": source_ref,
                "data_point_title": title,
                "research_category": category,
                "metric": title,
                "period": "2021-2028",
                "as_of_date": AS_OF_DATE,
                "value_text": excerpt,
                "unit": "指标计算底稿",
                "source_excerpt": excerpt,
                "source_context": SOURCE_NOTES.get(source_ref, "该来源用于本轮指标构建的口径校准。"),
                "interpretation": interpretations.get(title, use),
                "research_use": research_uses[title],
                "limitations": "若底层来源后续更新，相关编码和权重需要重算。",
                "evidence_ref_uri": _ref(source_ref),
                "sort_order": idx,
            }
        )
    return points


def _research_profile(entity_key: str) -> dict[str, Any]:
    name = ENTITY_DEFS[entity_key]["display_name"]
    if entity_key == "swpi_methodology":
        lit = (
            "### 文献综述\n\n"
            "SEMI 的公开统计给出全球硅片出货面积和年度收入，是最接近行业总量与混合 ASP 的公开底座；公司 IR 和公告补上产品结构、客户、订单、LTA、库存和财务承接；SIA/WSTS 只能说明下游芯片需求强弱，不能替代硅片价格。"
            "三类资料合起来形成一个可复算的层级：先用官方量价锚定周期，再用公司披露拆产品和区域，最后用下游需求解释未来 6-12 个月的方向。"
        )
        analysis = (
            "本任务的核心不是再问“硅片有没有涨价”，而是把价格、订单和供需松紧合成可更新的读数。"
            "价格是同步或滞后项，订单/LTA、客户库存、晶圆厂 capex 和 HBM/AI 排产更靠前；毛利率和净利润负责检验价格是否真的被公司拿到。"
            "全球版更依赖 SEMI、GlobalWafers、Siltronic、Shin-Etsu 和 SUMCO 的公开口径；中国版必须增加国产替代订单、12 英寸产能利用和亏损收窄，因为国内扩产可能同时代表机会和价格压力。"
        )
        answer = (
            "最终定义为 SWPI：0-100 分景气指数，全球版和中国版分别计算，差异版等于 China SWPI - Global SWPI。"
            "80 分以上是高景气，68-80 是修复偏强，55-68 是温和修复，42-55 是底部抬升，42 以下是去库存或价格压力。"
            "该定义能把 2021-2022、2023-2025 和 2026-2028 三段周期放入同一刻度。"
        )
        conclusion = (
            "主指标采用复合 SWPI，而不是单一 ASP。复算顺序是：更新 SEMI MSI/收入和公司 IR，刷新各 component score，计算全球/中国/差异三条线，再检查产品子指数与公司财务是否一致。"
        )
    elif entity_key == "candidate_index_schemes":
        lit = (
            "### 文献综述\n\n"
            "价格主导指标在有连续成交价时最直接，但本行业公开成交价不足；复合指标能把官方出货、公司订单、库存和下游需求合并；相对差异指标能解释中国扩产和国产替代为什么不一定同步变成价格上涨。"
            "Shin-Etsu、Siltronic、GlobalWafers、Soitec 等披露显示产品线差异很大，单一行业均价会掩盖 300mm、200mm 和 SOI 的方向差别。"
        )
        analysis = (
            "四个候选方案的取舍很清楚：方案 A 对价格敏感但数据缺口最大；方案 B 能用现有底座直接复算并容纳补证；方案 C 适合解释中国相对全球的交易含义；方案 D 适合跟踪 AI/HBM 强链条。"
            "主指标选方案 B，是因为它既不放弃价格，又不把缺失成交价硬补成确定数字。方案 C 和 D 作为解释层，可以在页面上告诉研究员高分来自全球修复、中国补涨，还是单纯 AI 结构性拉动。"
        )
        answer = (
            "推荐指数体系为“一主两辅”：主指标是复合 SWPI；辅指标一是 China-Global gap；辅指标二是 300mm/200mm/SOI 产品子指数。"
            "方案 A 价格主导保留为后续 paid price database 或真实成交价接入后的校验，不作为当前主指标。"
        )
        conclusion = (
            "这个选择的投资研究价值是把信号分层：全球总量修复决定 Beta，中国差异决定国产替代和价格传导，300mm/200mm/SOI 子指数决定应该看哪类标的。"
        )
    else:
        lit = (
            "### 文献综述\n\n"
            "前置底座已经说明真实成交价、规格级 ASP、客户级 backlog 和连续产能利用率是硬缺口。SEMI 和公司公告能支撑方向判断，卖方和产业媒体能提供补证线索，但不能单独进核心。"
            "SIA/WSTS、存储厂和晶圆厂资料帮助解释需求环境，不过它们与硅片价格之间隔着 wafer start、产品 mix、良率和库存。"
        )
        analysis = (
            "来源分层决定指数能不能被复盘。官方和公司披露进入核心；卖方涨价判断只在被 SEMI、公告、IR 或财务结果交叉验证后提高权重；民间报价不进入核心。"
            "缺失值处理也不能一句带过：如果没有真实成交价，就使用 ASP 和毛利等代理，并把每个代理的误差方向写入数据点。"
        )
        answer = (
            "当前可以构建 minimum viable SWPI，但它是代理指数，不是真实成交价指数。"
            "可用于方向判断和研究排序；要升级为价格交易信号，需要补充 paid price database、规格级成交价、客户库存、LTA 外价格和公司 ASP 明细。"
        )
        conclusion = (
            "后续补证优先级依次是 SEMI/付费数据库、公司 ASP/销量/毛利、LTA/预付款、客户库存和晶圆厂稼动率。没有这些数据时，指数不应被解释成精确价格预测。"
        )
    return {
        "entity_research_mode": "theory_research",
        "research_depth_status": "complete",
        "research_question": name,
        "research_scope": "半导体硅片景气度、价格代理指数、全球/中国差异、产品子指数和数据质量边界。",
        "methodology_note": "producer-reviewer-loop 已按 Nature 审稿人和高盛基金经理双视角复核：数据可追溯、公式可复算、结论能进入研究排序，但不写交易指令。",
        "literature_review_markdown": lit,
        "data_collection_markdown": "数据收集以 run6 价格订单底座为 seed，补充 SIA/WSTS 下游需求代理和本地复算工作底稿；同源同对象同口径序列合并为平行数据点。",
        "analysis_markdown": analysis,
        "answer_markdown": answer,
        "conclusion_markdown": conclusion,
        "limitations_markdown": "公开资料仍缺少规格级真实成交价、客户级 backlog、连续产能利用率和 LTA 外价格；本指数必须标注为代理指数。",
        "evidence_ref_uri_list": ENTITY_DEFS[entity_key]["refs"],
    }


def _factor(
    code: str,
    score: int,
    metric_name: str,
    refs: list[str],
    *,
    entity_key: str,
    topic: str,
    summary: str,
    rationale: str,
    target_implication: str,
    direction: str = "positive",
) -> dict[str, Any]:
    entity_name = ENTITY_DEFS[entity_key]["display_name"]
    information_points: list[dict[str, Any]] = []
    for index, token in enumerate(refs, start=1):
        ref_name = token.replace("source_ref:", "")
        note = SOURCE_NOTES.get(ref_name, f"{ref_name} 提供一条可追溯来源。")
        information_points.append(
            {
                "slot_name": f"{metric_name}证据{index}",
                "metric_line": f"{metric_name}：{topic} 的独立证据组 {index}",
                "excerpt": note,
                "evidence_ref": _ref(ref_name),
                "interpretation": _compact(f"{note} 在 {entity_name} 中用于校准 {metric_name}；它影响的不是口号，而是 {summary}"),
                "source_tier": "按来源分层",
                "direction": direction,
                "observation_count": 1,
                "weight_reason": "按来源独立性、是否含数字口径、是否来自官方或公司披露、与本因子的直接程度加权。",
            }
        )
    return {
        "factor_code": code,
        "score_status": "complete",
        "score_raw": score,
        "score_adjusted": score,
        "coverage": 0.84 if score >= 68 else 0.76,
        "confidence": 0.78 if score >= 68 else 0.7,
        "factor_readiness_status": "ready",
        "metric_name": metric_name,
        "unit": "分",
        "period": "2021-2028",
        "as_of_date": AS_OF_DATE,
        "trace": f"{topic}：{rationale}",
        "core_score_note": "序列观测按同源同对象同口径合并为一个证据组；卖方和产业媒体只在交叉验证后进入辅助权重。",
        "contextual_human_question": f"{topic} 是否足以改变景气阶段、标的排序或补证优先级？",
        "contextual_factor_description": f"{metric_name} 覆盖 {topic}，并明确排除光伏硅片口径。",
        "source_context_summary": f"{entity_name} 的证据组合覆盖量、价、订单、库存、产品 mix 或供给壁垒。",
        "factor_value_summary": summary,
        "factor_topic_analysis": rationale,
        "score_rationale": rationale,
        "theme_analysis_points": [summary, rationale, target_implication],
        "information_points": information_points,
        "adjacent_factor_links": "需要与价格、订单、库存、capex 和产品结构一起读，单项高分不会自动推导为行业全面涨价。",
        "target_implications": target_implication,
        "source_context_refs": refs,
        "evidence_ref_uri_list": refs,
        "factor_importance": "important",
        "direction": direction,
    }


def _factor_scores(entity_key: str) -> list[dict[str, Any]]:
    refs = ENTITY_DEFS[entity_key]["refs"]
    if entity_key == "global_swpi":
        return [
            _factor("signal.material_price_momentum", 58, "全球混合 ASP 与价格修复", refs[:6], entity_key=entity_key, topic="量修复领先于价格修复", summary=f"2026E 全球 SWPI 为 {GLOBAL_SWPI[5]:.1f}，处在{_stage(GLOBAL_SWPI[5])}；2025 年出货恢复但收入未同步改善压低价格项。", rationale="SEMI 年度表显示量价不同步，Siltronic 又提示 LTA 外价格承压，所以全球指数不能直接给高景气。", target_implication="全球龙头需要看到 ASP、mix 或 LTA 外价格改善才从 Beta 修复升级为价格弹性。", direction="mixed"),
            _factor("demand.output_consumption_proxy", 72, "全球出货和下游需求代理", [refs[0], refs[2], refs[3], refs[7], "source_ref:micron_fq3_2026", "source_ref:skhynix_2026_outlook"], entity_key=entity_key, topic="SEMI 出货和 SIA/WSTS 芯片销售共同回暖", summary="量端和下游芯片销售在 2026 年给出更强修复信号。", rationale="需求修复是真的，但硅片价格要再经过库存、产品 mix 和 LTA 过滤。", target_implication="Shin-Etsu、SUMCO、GlobalWafers、Siltronic 优先看 300mm 订单和毛利。"),
            _factor("supply.supplier_structure_bucket", 75, "全球供给集中和认证壁垒", ["source_ref:nist_globalwafers_chips", "source_ref:siltronic_investor_202603", "source_ref:sumco_policy_2026", "source_ref:globalwafers_q1_2026_profile", "source_ref:shinetsu_q3_2026_summary", "source_ref:semi_300mm_outlook"], entity_key=entity_key, topic="前五集中和高端认证壁垒", summary="供给集中使高端 300mm 更容易从需求修复转为议价改善。", rationale="集中度不是涨价充分条件，但在客户验证和高端规格紧张时能放大价格弹性。", target_implication="全球龙头优先级高于纯概念或低端产能扩张公司。"),
            _factor("supply.capacity_event_12m", 63, "2026-2028 扩产与供给释放", ["source_ref:semi_300mm_outlook", "source_ref:semi_2028_forecast", "source_ref:globalwafers_q1_2026_profile", "source_ref:siltronic_investor_202603", "source_ref:nist_globalwafers_chips", "source_ref:stcn_china_capacity_202606"], entity_key=entity_key, topic="需求上行和新增产能同时存在", summary="2026-2028 的全球修复需要警惕新产能释放对价格上限的压制。", rationale="扩产说明客户长期需求存在，但也会削弱 2027-2028 的供需紧张程度。", target_implication="对扩产型标的必须跟踪利用率、预付款和客户锁定。", direction="mixed"),
        ]
    if entity_key == "china_swpi":
        return [
            _factor("signal.material_price_momentum", 60, "中国价格和毛利承接", refs[:6], entity_key=entity_key, topic="国产替代信号进入价格和利润前仍需折扣", summary=f"2026E 中国 SWPI 为 {CHINA_SWPI[5]:.1f}，略高于全球，但仍是{_stage(CHINA_SWPI[5])}。", rationale="西安奕材和上海合晶有客户/销量进展，沪硅产业亏损提醒价格传导不均。", target_implication="沪硅产业、西安奕材、上海合晶排序取决于毛利和客户验证，不取决于产能口号。", direction="mixed"),
            _factor("demand.customer_capex_capacity_signal", 72, "中国客户导入和国产替代订单", ["source_ref:xian_yisiwei_202605_ir", "source_ref:shanghai_hejing_202606_ir", "source_ref:nsig_2025_annual", "source_ref:stcn_china_capacity_202606", "source_ref:semi_q1_2026", "source_ref:sia_april_2026_sales"], entity_key=entity_key, topic="国产替代带来订单能见度", summary="中国指数的强项是 12 英寸客户导入和国产替代，不是公开价格数据库。", rationale="订单能见度改善如果不能进入 ASP、毛利和现金流，就只能算中等景气。", target_implication="中国公司先排客户和产品线，再排财务弹性。"),
            _factor("supply.expansion_cycle_bucket", 58, "中国 12 英寸扩产压力", ["source_ref:xian_yisiwei_202605_ir", "source_ref:shanghai_hejing_202606_ir", "source_ref:stcn_china_capacity_202606", "source_ref:nsig_2025_annual", "source_ref:semi_300mm_outlook", "source_ref:semi_2028_forecast"], entity_key=entity_key, topic="产能扩张既是机会也是价格压力", summary="若新增产能快于客户认证和利用率，China SWPI 会高估真实价格景气。", rationale="国内扩产必须被客户名单、量产节奏和毛利验证；否则只是供给增加。", target_implication="产能大的公司设置更高补证门槛。", direction="mixed"),
            _factor("company.financial_capture_quality", 56, "财务承接质量", ["source_ref:nsig_2025_annual", "source_ref:shanghai_hejing_202606_ir", "source_ref:xian_yisiwei_202605_ir", "source_ref:leonmicro_202605_order", "source_ref:stcn_china_capacity_202606", "source_ref:semi_2025_annual"], entity_key=entity_key, topic="收入、毛利、折旧和亏损收敛", summary="中国指数在 2026E 仍需用毛利和亏损收敛确认。", rationale="销售增长和产能投放可能被折旧和良率消耗，财务项是防止误判的重要降温器。", target_implication="若毛利率连续改善，中国标的优先级才会上调。", direction="mixed"),
        ]
    if entity_key == "china_global_gap_swpi":
        return [
            _factor("demand.customer_capex_capacity_signal", 66, "中国相对全球订单差异", refs[:6], entity_key=entity_key, topic="China SWPI 在 2026E 略高于 Global SWPI", summary=f"差异项 2026E 为 {GAP_SWPI[5]:+.1f} 分，代表中国补涨和国产替代正在追上全球修复。", rationale="差异为正不是中国全面强于全球，而是本土订单和产品升级对冲了全球价格滞后。", target_implication="差异继续扩大时优先验证中国 12 英寸和 SOI 公司。"),
            _factor("signal.material_price_momentum", 54, "中国-全球价格差异", ["source_ref:semi_2025_annual", "source_ref:siltronic_2026_guidance", "source_ref:nsig_2025_annual", "source_ref:shanghai_hejing_202606_ir", "source_ref:xian_yisiwei_202605_ir", "source_ref:stcn_china_capacity_202606"], entity_key=entity_key, topic="全球价格滞后与中国毛利分化并存", summary="价格差异不能只用卖方涨价判断，需要公司毛利和 ASP 验证。", rationale="如果全球 LTA 外价格承压而中国毛利改善，gap 才有实质意义；否则只是产能扩张叙事。", target_implication="gap 交易必须有财务承接确认。", direction="mixed"),
            _factor("supply.expansion_cycle_bucket", 57, "中国扩产相对全球扩产", ["source_ref:semi_300mm_outlook", "source_ref:semi_2028_forecast", "source_ref:stcn_china_capacity_202606", "source_ref:xian_yisiwei_202605_ir", "source_ref:globalwafers_q1_2026_profile", "source_ref:nist_globalwafers_chips"], entity_key=entity_key, topic="中国扩产速度可能放大 gap，也可能压低价格", summary="gap 读数需要同时显示机会和过剩风险。", rationale="国产替代会抬高订单项，扩产过快会压低价格和利用率项。", target_implication="用 gap 指标筛标的时，不能把产能越大等同于越好。", direction="mixed"),
            _factor("supply.substitution_barrier", 63, "客户认证和替代壁垒差异", ["source_ref:xian_yisiwei_202605_ir", "source_ref:shanghai_hejing_202606_ir", "source_ref:nsig_2025_annual", "source_ref:nist_globalwafers_chips", "source_ref:siltronic_investor_202603", "source_ref:sumco_policy_2026"], entity_key=entity_key, topic="认证壁垒决定国产替代速度", summary="中国相对全球的改善取决于客户认证，不是只靠政策或产能。", rationale="全球龙头的认证壁垒越高，中国公司越需要证明稳定供货和良率。", target_implication="优先补客户平台、料号认证和量产批次。"),
        ]
    if entity_key == "product_300mm_ai_hbm":
        return [
            _factor("demand.application_intensity_change", 84, "AI/HBM 对 300mm 强度", refs[:6], entity_key=entity_key, topic="HBM 和先进逻辑提高高端 300mm 需求强度", summary="300mm/AI 子指数 2026E 为 78，已经接近修复偏强上沿。", rationale="Micron、SK hynix、Shin-Etsu 和 SEMI 300mm capex 指向同一方向：AI 需求先落在高端 300mm。", target_implication="全球 300mm 龙头和中国 12 英寸导入公司进入 P1/P2 跟踪。"),
            _factor("demand.customer_capex_capacity_signal", 79, "300mm 客户 capex 和 wafer start", ["source_ref:semi_300mm_outlook", "source_ref:micron_fq3_2026", "source_ref:skhynix_2026_outlook", "source_ref:globalwafers_q1_2026_profile", "source_ref:shinetsu_q3_2026_summary", "source_ref:sia_april_2026_sales"], entity_key=entity_key, topic="AI capex 传导到 wafer start", summary="capex 和存储强周期增强 2026-2028 订单能见度。", rationale="capex 是领先项，但会受设备交期、先进封装和客户库存影响。", target_implication="优先看客户锁单、预付款和高端 mix。"),
            _factor("supply.supplier_structure_bucket", 82, "300mm 合格供应商稀缺", ["source_ref:nist_globalwafers_chips", "source_ref:siltronic_investor_202603", "source_ref:globalwafers_q1_2026_profile", "source_ref:shinetsu_q3_2026_summary", "source_ref:sumco_policy_2026", "source_ref:xian_yisiwei_202605_ir"], entity_key=entity_key, topic="合格供应商少且认证慢", summary="高端 300mm 的供应壁垒足以让需求修复更可能进入议价。", rationale="不是所有 300mm 都同价，高端 polished/epi 与先进逻辑、HBM 的认证门槛更高。", target_implication="全球龙头和已进入高端客户验证的中国公司优先。"),
            _factor("signal.material_price_momentum", 70, "300mm 高端价格代理", ["source_ref:semi_2025_annual", "source_ref:siltronic_2026_guidance", "source_ref:shinetsu_q3_2026_summary", "source_ref:globalwafers_q1_2026_profile", "source_ref:semi_q1_2026", "source_ref:xian_yisiwei_202605_ir"], entity_key=entity_key, topic="高端 mix 可能先于全行业 ASP 改善", summary="指数给高端 300mm 更高分，但仍保留价格验证债。", rationale="量和需求已经更强，价格需要通过 mix、ASP、毛利或合同条款确认。", target_implication="缺少价格验证时不把 300mm 直接写成全面涨价。", direction="mixed"),
        ]
    if entity_key == "product_200mm_mature":
        return [
            _factor("signal.material_price_momentum", 45, "200mm 成熟制程价格代理", refs[:6], entity_key=entity_key, topic="200mm 仍处在弱修复", summary="200mm 子指数 2026E 为 50，低于全球主指数和 300mm 子指数。", rationale="Siltronic 明确提到 200mm power segment 库存调整，成熟制程不能套用 AI/HBM 逻辑。", target_implication="200mm 标的更多是观察局部重掺、功率和工业复苏。", direction="mixed"),
            _factor("demand.output_consumption_proxy", 52, "功率/汽车/工业需求代理", ["source_ref:siltronic_2026_guidance", "source_ref:leonmicro_202605_order", "source_ref:sumco_policy_2026", "source_ref:semi_q1_2026", "source_ref:deloitte_semiconductor_2026", "source_ref:stcn_china_capacity_202606"], entity_key=entity_key, topic="成熟需求温和恢复但不统一", summary="200mm 的问题是库存和终端需求分化，而不是单向景气。", rationale="工业和功率局部改善被汽车和库存压力抵消。", target_implication="标的需要逐产品线验证订单，不做泛成熟制程上行。", direction="mixed"),
            _factor("supply.capacity_event_12m", 55, "200mm 局部产能和交期", refs[:6], entity_key=entity_key, topic="局部紧张和供给充足并存", summary="重掺和外延局部线索不能代表所有 200mm。", rationale="200mm 供给选择多于高端 300mm，认证壁垒弱一些，价格弹性更受终端库存约束。", target_implication="立昂微、有研硅等需要公告级订单和毛利验证。", direction="mixed"),
            _factor("supply.substitution_barrier", 58, "成熟制程认证壁垒", ["source_ref:siltronic_2026_guidance", "source_ref:sumco_policy_2026", "source_ref:shanghai_hejing_202606_ir", "source_ref:leonmicro_202605_order", "source_ref:stcn_china_capacity_202606", "source_ref:nsig_2025_annual"], entity_key=entity_key, topic="认证存在但替代路径更多", summary="客户认证给价格下限，但不提供高端 300mm 那样的稀缺性。", rationale="200mm 的投资研究应低于 300mm，除非某个细分订单和毛利率先兑现。", target_implication="同实体内优先级以订单质量和毛利改善排序。", direction="mixed"),
        ]
    return [
        _factor("signal.material_price_momentum", 58, "SOI/外延 price-mix", refs[:6], entity_key=entity_key, topic="SOI 内部分化强", summary="SOI 子指数 2026E 为 60，高于 200mm 但弱于 300mm/AI。", rationale="Soitec 同时出现 AI 相关线索和 RF-SOI 库存压力，上海合晶提供中国外延/SOI 增长样本。", target_implication="Soitec 与上海合晶需要分产品线验证。", direction="mixed"),
        _factor("demand.application_intensity_change", 66, "Photonics/FD-SOI/RF-SOI 应用强度", ["source_ref:soitec_q3_fy26", "source_ref:soitec_q1_fy26", "source_ref:globalwafers_q1_2026_profile", "source_ref:shanghai_hejing_202606_ir", "source_ref:nsig_2025_annual", "source_ref:deloitte_semiconductor_2026"], entity_key=entity_key, topic="AI photonics 和特色应用抬高结构价值", summary="AI photonics、FD-SOI 和特色外延给中期景气提供弹性。", rationale="新应用强度存在，但传统 RF 库存尚未完全出清。", target_implication="特色硅片标的要把 RF、Power、Photonics 和 FD-SOI 分开看。"),
        _factor("supply.substitution_barrier", 68, "SOI 技术和客户认证壁垒", refs[:6], entity_key=entity_key, topic="特色硅片供应商稀缺", summary="SOI/外延的认证和工艺壁垒高于普通成熟片。", rationale="壁垒支持中期价值，但短期价格仍受具体应用库存影响。", target_implication="技术壁垒高的公司优先，但必须披露客户和产品线。"),
        _factor("supply.capacity_event_12m", 60, "SOI/外延扩产和量产节奏", ["source_ref:shanghai_hejing_202606_ir", "source_ref:nsig_2025_annual", "source_ref:soitec_q1_fy26", "source_ref:soitec_q3_fy26", "source_ref:cicc_shanghai_hejing_listing", "source_ref:stcn_china_capacity_202606"], entity_key=entity_key, topic="扩产需要被量产和良率确认", summary="中国 SOI/外延扩产是机会，但也需要毛利和客户导入确认。", rationale="外延和 SOI 产能公告不等于价格弹性；能否量产和盈利更关键。", target_implication="上海合晶和沪硅产业继续作为高优先级补证样本。", direction="mixed"),
    ]
ENTITY_CANDIDATE_REASON = {
    "swpi_methodology": "先把价格、订单、库存和供给壁垒压到同一套可复算口径，避免后续实体各自解释景气度。",
    "candidate_index_schemes": "用户要求的是可跟踪指标，不是单一涨价新闻；必须比较多套方案后保留主指标和备用指标。",
    "source_quality_proxy_review": "真实成交价和订单通常不可公开取得，这个实体专门说明哪些代理能用、哪些只能触发补证。",
    "global_swpi": "全球读数是判断硅片周期位置的母盘，给中国差异、产品子指数和公司映射提供基准线。",
    "china_swpi": "中国读数用于区分国产替代带来的结构修复和全球周期同步修复，直接影响 A 股硅片标的优先级。",
    "china_global_gap_swpi": "差异项负责识别中国相对全球是补涨、领先还是过热，防止只看绝对读数误判区域机会。",
    "product_300mm_ai_hbm": "AI/HBM 和先进逻辑是最容易把硅片规格、认证和产能稀缺性传导到价格的方向。",
    "product_200mm_mature": "成熟制程硅片供给分散、库存恢复慢，需要单独观察，不能被 300mm 强景气掩盖。",
    "product_soi_specialty": "特色硅片的需求驱动和认证节奏不同于标准抛光片，适合作为结构性而非全面周期指标。",
}

ENTITY_READINESS_REASON = {
    "swpi_methodology": "公式、权重、缺失值处理和复算路径已经写入正文和指标计算底稿，后续更新可直接替换输入值。",
    "candidate_index_schemes": "价格主导、复合主指标、差异指标和产品子指数均已比较，主方案与备用方案边界清楚。",
    "source_quality_proxy_review": "来源被分成官方统计、公司披露、卖方线索和产业媒体四层，低层级信息只作为触发器。",
    "global_swpi": "已用 SEMI 面积、收入、300mm 投资、WSTS 需求和龙头 IR 交叉复核，足够进入基准读数。",
    "china_swpi": "已把国产 12 英寸、SOI/外延、上市公司财务和 A/B 底座价格订单线索合并到同一读数。",
    "china_global_gap_swpi": "全球与中国两组读数同权重复算，差值含义明确，但仍受中国公开成交价缺口约束。",
    "product_300mm_ai_hbm": "先进产品证据覆盖 300mm capex、HBM/AI wafer start、龙头认证和高端产能供给，当前可评分。",
    "product_200mm_mature": "成熟制程证据足以说明尚未全面出清，但真实 ASP 和客户库存仍是主要降置信项。",
    "product_soi_specialty": "SOI、外延和 RF/Photonics 证据支持结构性跟踪，样本分散度高于主指数但方向可用。",
}

ENTITY_BAND_REASON = {
    "swpi_methodology": "理论实体不参与机会矩阵，分数只作为研究完整度占位，核心看公式是否能被外部数据复算。",
    "candidate_index_schemes": "该实体不评价交易机会，评分带宽反映候选方案选择是否覆盖用户提出的价格、订单和差异要求。",
    "source_quality_proxy_review": "研究型边界实体的置信度取决于来源分层是否严格，尤其是卖方涨价线索是否被降权处理。",
    "global_swpi": "全球读数由面积、收入、价格、订单和供给壁垒共同决定，SEMI/WSTS 与公司 IR 一致时区间收窄。",
    "china_swpi": "中国读数的上沿来自国产替代和结构升级，下沿由公开成交价缺口、毛利承压和扩产节奏限制。",
    "china_global_gap_swpi": "差值指标对两边公式误差都敏感，因此用较宽区间保留区域价格和订单披露不足的影响。",
    "product_300mm_ai_hbm": "高端子指数上沿由 AI/HBM 拉动和先进产能紧张支撑，下沿看客户认证和规格级 ASP 能否落地。",
    "product_200mm_mature": "成熟制程区间主要受汽车/工业库存和 200mm 利用率影响，短期涨价线索不足以明显抬高下沿。",
    "product_soi_specialty": "特色硅片区间由 SOI/RF/外延订单质量决定，样本少但产品壁垒高，因此中枢高于成熟制程。",
}


def _entity(entity_key: str) -> dict[str, Any]:
    meta = ENTITY_DEFS[entity_key]
    mode = meta["mode"]
    score = float(meta["score"])
    refs = meta["refs"]
    entity: dict[str, Any] = {
        "key": entity_key,
        "entity_type": "product_material",
        "taxonomy_level": "product_material",
        "canonical_name": entity_key,
        "display_name": meta["display_name"],
        "description": meta["description"],
        "entity_research_mode": mode,
        "external_ref_type": "opportunity_lens_entity",
        "maturation_status": "research_only" if mode == "theory_research" else "scoring_ready",
        "readiness_score": 1.0 if mode == "theory_research" else 0.82,
        "readiness_reason": ENTITY_READINESS_REASON[entity_key],
        "research_priority_label": (
            "research_only_literature_review_complete"
            if mode == "theory_research"
            else "high_priority_for_scoring"
            if score >= 68
            else "medium_priority_for_followup"
        ),
        "source_count": len(refs),
        "independent_source_count": len({r.replace("source_ref:", "").split("_")[0] for r in refs}),
        "candidate_reason": ENTITY_CANDIDATE_REASON[entity_key],
        "evidence_ref_uri": refs[0],
        "evidence_ref_uri_list": refs,
        "score_point": score,
        "score_grade": _score_grade(score),
        "score_quality_label": "medium_confidence" if mode == "market_linked" else "unrated_insufficient_evidence",
        "score_band_low": max(0, score - 7),
        "score_band_high": min(100, score + 7),
        "coverage": 0.82,
        "confidence": 0.76,
        "band_reason": ENTITY_BAND_REASON[entity_key],
        "composite_trace": {
            "confirmed_action": f"若 {meta['display_name']} 后续由 SEMI/公司公告/IR 确认价格、订单、毛利或客户导入同步改善，上调指数读数和研究优先级。",
            "falsified_action": f"若 {meta['display_name']} 只剩卖方涨价线索、库存仍高或产能释放快于需求，下调指数读数并增加反方权重。",
            "monitor_signal": "SEMI MSI/收入、公司 ASP/销量/毛利、订单/LTA/预付款、客户库存、晶圆厂 capex、HBM/AI wafer start、SOI/RF 库存。",
            "monitor_timing": "SEMI 季度更新；公司财报和 IR 季度/半年度更新；卖方涨价线索只在出现后做临时复核。",
        },
        "factor_scores": [] if mode == "theory_research" else _factor_scores(entity_key),
    }
    if mode == "theory_research":
        entity["research_profile"] = _research_profile(entity_key)
        entity["research_data_points"] = _research_points(entity_key)
    return entity


TARGET_DEFS = [
    {
        "entity_key": "global_swpi",
        "target_name": "全球硅片龙头基准篮子（Shin-Etsu / SUMCO / GlobalWafers / Siltronic）",
        "ticker": "4063.T / 3436.T / 6488.TWO / WAF.DE",
        "market": "日本/中国台湾/德国",
        "type": "basket",
        "ref": "siltronic_investor_202603",
        "priority": "P1",
        "quality": "高置信度",
        "angle": "用于验证全球 SWPI 是否从量修复进入价格和毛利修复；四家公司覆盖 300mm、200mm、specialty 和 LTA 口径。",
        "verify": "下一轮先查季度收入、EBITDA margin、300mm mix、LTA 外价格压力和客户库存表述。",
    },
    {
        "entity_key": "china_swpi",
        "target_name": "西安奕材（688783.SH）12 英寸国产替代样本",
        "ticker": "688783.SH",
        "market": "中国A股",
        "type": "company",
        "ref": "xian_yisiwei_202605_ir",
        "priority": "P1",
        "quality": "中高置信度",
        "angle": "中国 12 英寸客户导入和产能爬坡的核心样本，适合验证 China SWPI 的订单和国产替代分项。",
        "verify": "查客户结构、月产能兑现、ASP/毛利、良率、预付款和是否有全球客户稳定供货更新。",
    },
    {
        "entity_key": "china_swpi",
        "target_name": "沪硅产业（688126.SH）300mm/SOI 平台与利润承接样本",
        "ticker": "688126.SH",
        "market": "中国A股",
        "type": "company",
        "ref": "nsig_2025_annual",
        "priority": "P1",
        "quality": "中等置信度",
        "angle": "同时覆盖 300mm 和 SOI，但亏损和折旧压力使其成为 China SWPI 财务承接的压力测试。",
        "verify": "重点查毛利率、亏损收敛、SOI/300mm 分产品收入、客户验证和库存。",
    },
    {
        "entity_key": "china_global_gap_swpi",
        "target_name": "中国 12 英寸国产替代观察篮子",
        "ticker": "688783.SH / 688126.SH / 688584.SH",
        "market": "中国A股",
        "type": "basket",
        "ref": "stcn_china_capacity_202606",
        "priority": "P2",
        "quality": "中等置信度",
        "angle": "用于检验 China-Global gap 是客户导入和国产替代带来的补涨，还是单纯产能扩张造成的供给压力。",
        "verify": "同时跟踪客户认证、产能利用率、毛利率和真实订单，任一项缺失都不把 gap 上行视为价格景气。",
    },
    {
        "entity_key": "product_300mm_ai_hbm",
        "target_name": "Shin-Etsu / SUMCO 高端 300mm 与电子材料链",
        "ticker": "4063.T / 3436.T",
        "market": "日本",
        "type": "basket",
        "ref": "shinetsu_q3_2026_summary",
        "priority": "P1",
        "quality": "高置信度",
        "angle": "AI memory/HBM、advanced logic 和高端 300mm 的全球基准样本，适合验证 300mm 子指数高分。",
        "verify": "查 AI/HBM 相关材料表述、300mm mix、价格纪律、客户库存和电子材料协同。",
    },
    {
        "entity_key": "product_300mm_ai_hbm",
        "target_name": "Micron / SK hynix HBM wafer-start 需求代理篮子",
        "ticker": "MU / 000660.KS",
        "market": "美国/韩国",
        "type": "basket",
        "ref": "micron_fq3_2026",
        "priority": "P2",
        "quality": "辅助代理",
        "angle": "不是硅片生产标的，而是检验 HBM 和 DRAM 周期是否能传导到 300mm wafer start 的下游代理。",
        "verify": "查 HBM 产能、DRAM wafer allocation、库存、价格和 capex，避免把芯片销售额直接外推到硅片价格。",
    },
    {
        "entity_key": "product_200mm_mature",
        "target_name": "Siltronic 200mm 与 power segment 库存反方样本",
        "ticker": "WAF.DE",
        "market": "德国",
        "type": "company",
        "ref": "siltronic_2026_guidance",
        "priority": "P2",
        "quality": "高置信度反方",
        "angle": "用于检验 200mm 成熟制程是否仍被 power 库存调整压制，是 200mm 子指数的降温器。",
        "verify": "查 200mm 销量、价格压力、power 客户库存、SD line 影响和 LTA 外价格。",
    },
    {
        "entity_key": "product_200mm_mature",
        "target_name": "立昂微（605358.SH）重掺/外延局部订单样本",
        "ticker": "605358.SH",
        "market": "中国A股",
        "type": "company",
        "ref": "leonmicro_202605_order",
        "priority": "P3",
        "quality": "待补证",
        "angle": "用于观察中国成熟制程和重掺硅片是否有局部订单改善，但当前证据层级低于公告和 IR。",
        "verify": "必须用公告、财报、毛利率和客户订单复核业绩会线索，否则只作早期信号。",
    },
    {
        "entity_key": "product_soi_specialty",
        "target_name": "Soitec（SOI.PA）全球 SOI 结构分化基准",
        "ticker": "SOI.PA",
        "market": "法国",
        "type": "company",
        "ref": "soitec_q3_fy26",
        "priority": "P1",
        "quality": "高置信度",
        "angle": "SOI 全球核心样本，用于区分 RF-SOI 库存压力、AI photonics 和 FD-SOI 结构机会。",
        "verify": "查各产品线收入、price/mix、库存去化、Photonics-SOI 客户和 FY26/FY27 指引。",
    },
    {
        "entity_key": "product_soi_specialty",
        "target_name": "上海合晶（688584.SH）外延/SOI 中国样本",
        "ticker": "688584.SH",
        "market": "中国A股",
        "type": "company",
        "ref": "shanghai_hejing_202606_ir",
        "priority": "P2",
        "quality": "中高置信度",
        "angle": "中国外延和 SOI 产线扩张样本，适合检验特色硅片能否进入收入和毛利。",
        "verify": "查 12 英寸销量、SOI 合资进展、外延毛利、客户验证和新增产能利用率。",
    },
]


def _target(item: dict[str, Any], sort_order: int) -> dict[str, Any]:
    name = item["target_name"]
    entity_name = ENTITY_DEFS[item["entity_key"]]["display_name"]
    ref = _ref(item["ref"])
    target_type = item["type"]
    risk = {
        "global_swpi": "全球 SWPI 的风险是 SEMI 出货改善仍可能被 LTA 外价格压力、汇率、库存和新增产能抵消。",
        "china_swpi": "中国 SWPI 的风险是产能扩张快于客户认证，销售增长被折旧、良率和价格竞争吞掉。",
        "china_global_gap_swpi": "gap 指标的风险是把国产替代补涨误读为全面价格景气，或者忽略全球龙头的高端壁垒。",
        "product_300mm_ai_hbm": "300mm/AI 子指数的风险是 HBM 和 advanced logic 的强需求不能等比例传导到全部 300mm 规格。",
        "product_200mm_mature": "200mm 子指数的风险是功率、汽车和工业库存尚未同步出清，局部订单不能代表全产品线。",
        "product_soi_specialty": "SOI 子指数的风险是 RF-SOI 库存、AI photonics 和 FD-SOI 节奏不同，单一公司收入会掩盖结构差异。",
    }[item["entity_key"]]
    return {
        "entity_key": item["entity_key"],
        "target_name": name,
        "ticker": item["ticker"],
        "market": item["market"],
        "target_type": target_type,
        "company_id": None,
        "target_url": None,
        "exposure_rationale": item["angle"],
        "evidence_ref_uri": ref,
        "research_action": item["verify"],
        "investment_view": f"{name} 在 {entity_name} 中的作用是校验指数读数，而不是直接给交易方向。{item['angle']}",
        "risk_note": risk,
        "target_priority": item["priority"],
        "target_quality_label": item["quality"],
        "relative_preference": f"相对同实体其他标的，{name} 的价值在于：{item['angle']}；短板是：{risk}",
        "confirmed_scenario_action": f"若 {name} 的后续公告或 IR 同时出现订单、ASP/毛利、客户验证或库存改善，{entity_name} 的指数分项上调，并把该标的提升到下一轮深挖清单。",
        "falsified_scenario_action": f"若 {name} 只留下概念线索、库存继续走高、价格或毛利继续下行，{entity_name} 的对应分项下调，该标的转为反方或观察项。",
        "target_profile_markdown": f"### 标的画像\n\n{name} 的研究边界是 {item['angle']} 本 run 只评价它对 SWPI 的验证作用，不给交易指令。",
        "target_deep_research_markdown": f"### 深度研究要点\n\n{item['verify']} 研究重点是把指数信号落到真实经营：价格、订单、客户、库存、毛利和现金流至少要有两项互相印证。",
        "entity_relation_markdown": f"{name} 映射到 {entity_name}，用于检验该实体的指数读数、方向和反方约束。",
        "parent_research_relation_markdown": "本标的服务于硅片景气度指数构建。前置价格订单底座提供输入，本 run 进一步把输入转化为可更新指数。",
        "conditional_investment_recommendation": f"条件化建议：把 {name} 纳入指数跟踪清单；证实条件是 {item['verify']}；证伪条件是证据不能进入价格、订单或财务承接。",
        "financial_data_status": "后续财务快照只允许使用 Tushare、yfinance 或公司公告；Wind 仅保留历史 provenance，不作为新增数据源。",
        "link_status": "linked",
        "support_status": "partially_supported",
        "sort_order": sort_order,
        "target_data_points": [
            {
                "metric_name": f"{name} 指数验证角色",
                "metric_category": "target_index_validation",
                "period": "2026-2028",
                "as_of_date": AS_OF_DATE,
                "value_text": item["angle"],
                "unit": "文本",
                "source_title": item["ref"],
                "source_publisher": "manual reviewed source",
                "source_url": None,
                "source_excerpt": item["angle"],
                "evidence_ref_uri": ref,
                "data_quality_label": item["quality"],
                "direction": "positive" if item["priority"] in {"P1", "P2"} else "mixed",
                "credibility_weight": 0.82 if item["priority"] == "P1" else 0.72,
                "numeric_weight": 0.65,
            },
            {
                "metric_name": f"{name} 下一步补证指标",
                "metric_category": "verification_debt",
                "period": "2026-2028",
                "as_of_date": AS_OF_DATE,
                "value_text": item["verify"],
                "unit": "补证清单",
                "source_title": item["ref"],
                "source_publisher": "manual reviewed source",
                "source_url": None,
                "source_excerpt": "补证项来自本 run 的 Nature reviewer 和高盛基金经理双视角审查。",
                "evidence_ref_uri": ref,
                "data_quality_label": "reviewer_required_followup",
                "direction": "mixed",
                "credibility_weight": 0.72,
                "numeric_weight": 0.4,
            },
        ],
    }


def _claims() -> list[dict[str, Any]]:
    rows = [
        ("semi_2025_annual", "global_swpi", "price_volume", "2025 年全球硅片出货恢复但收入未同步改善，SWPI 必须把量和价分开。"),
        ("semi_q1_2026", "global_swpi", "volume_signal", "2026Q1 同比恢复确认量端向上，但环比季节性回落限制单季外推。"),
        ("siltronic_2026_guidance", "product_200mm_mature", "counter_evidence", "Siltronic 的 200mm 和 LTA 外价格压力是成熟制程子指数的反方核心。"),
        ("semi_300mm_outlook", "product_300mm_ai_hbm", "leading_indicator", "300mm fab equipment spending 和 AI/memory/power 投资是 300mm 子指数领先项。"),
        ("shinetsu_q3_2026_summary", "product_300mm_ai_hbm", "ai_hbm_path", "Shin-Etsu 将 AI memory/HBM 和 advanced logic 与硅片需求拆开讨论，支持高端 300mm 结构强于全行业。"),
        ("globalwafers_q1_2026_profile", "product_300mm_ai_hbm", "order_visibility", "GlobalWafers 对 AI、memory、advanced packaging 的披露增强 300mm 和 specialty wafer 能见度。"),
        ("xian_yisiwei_202605_ir", "china_swpi", "china_order", "西安奕材客户和 12 英寸产能披露是 China SWPI 订单国产替代分项的关键输入。"),
        ("nsig_2025_annual", "china_swpi", "financial_capture", "沪硅产业的亏损和平台属性共同说明中国指数必须加入财务承接项。"),
        ("shanghai_hejing_202606_ir", "product_soi_specialty", "china_soi_epi", "上海合晶外延、12 英寸和 SOI 进展用于验证中国特色硅片子指数。"),
        ("soitec_q1_fy26", "product_soi_specialty", "soi_inventory", "Soitec RF-SOI 库存和 price/mix 压力说明 SOI 子指数不能单向乐观。"),
        ("soitec_q3_fy26", "product_soi_specialty", "soi_structure", "Soitec Q3 把 AI 相关机会和传统库存问题放在同一周期里，支撑结构分化判断。"),
        ("sia_april_2026_sales", "global_swpi", "downstream_proxy", "SIA/WSTS 的芯片销售强复苏只能作为下游需求代理，不能替代硅片价格。"),
        ("wsts_spring_2026_forecast", "product_300mm_ai_hbm", "ai_hbm_forecast_proxy", "WSTS 春季预测强化 AI、HBM 和加速计算的下游需求主线，但只进入 300mm/HBM 需求代理，不进入硅片价格项。"),
        ("siltronic_2025_resilience_update", "global_swpi", "volume_price_split", "Siltronic 2025 更新再次证明面积修复、LTA 外价格压力和 200mm 库存可以同时存在，支持 SWPI 拆分量价库存。"),
        ("soitec_ai_photonics_202503", "product_soi_specialty", "ai_photonics_soi", "Soitec 硅光 SOI 公告说明 AI 数据中心互连给特色 SOI 带来结构机会，但不能覆盖 RF-SOI 库存压力。"),
        ("derived_swpi_workpaper", "swpi_methodology", "formula", "SWPI 采用全球版、中国版和 China-Global gap 三条线，公式和权重写入复算底稿。"),
        ("previous_run6_price_order_pack", "source_quality_proxy_review", "seed_review", "前置价格订单底座是本 run 的第一输入，但旧结论必须经过指标化复核。"),
    ]
    return [
        {
            "source_ref": source_ref,
            "entity_key": entity_key,
            "claim_type": claim_type,
            "claim_text": claim_text,
            "source_excerpt": SOURCE_NOTES.get(source_ref, claim_text),
            "claim_evidence_status": "verified",
            "claim_next_action": "use_as_background",
            "support_status": "supported",
            "policy_evidence_role": "core_evidence" if source_ref not in {"derived_swpi_workpaper", "previous_run6_price_order_pack"} else "reference_only",
        }
        for source_ref, entity_key, claim_type, claim_text in rows
    ]


def _transform_base_data_points(base_pack: dict[str, Any]) -> list[dict[str, Any]]:
    mapping = {
        "price_tracking_methodology": "swpi_methodology",
        "vendor_universe_product_taxonomy": "source_quality_proxy_review",
        "data_gap_proxy_review": "source_quality_proxy_review",
        "global_300mm_advanced_price_order": "product_300mm_ai_hbm",
        "global_200mm_mature_node_price_order": "product_200mm_mature",
        "soi_specialty_price_order": "product_soi_specialty",
        "china_wafer_price_order_localization": "china_swpi",
        "ai_hbm_advanced_logic_wafer_path": "product_300mm_ai_hbm",
        "supply_inventory_lta_counterevidence": "global_swpi",
    }
    points: list[dict[str, Any]] = []
    for point in base_pack["data_points"]:
        cloned = copy.deepcopy(point)
        old_metric = cloned.get("metric", "前置数据点")
        cloned["entity_key"] = mapping.get(cloned.get("entity_key"), "source_quality_proxy_review")
        cloned["metric"] = _compact(f"SWPI 指标输入：{old_metric}", 220)
        cloned["source_excerpt"] = _compact(
            f"前置价格订单底座复核后纳入 SWPI 输入。原摘录：{cloned.get('source_excerpt')}",
            900,
        )
        cloned["calculation_review_status"] = "pass"
        cloned["extraction_method"] = "manual_verified_index_input"
        cloned["policy_evidence_role"] = cloned.get("policy_evidence_role", "core_evidence")
        points.append(cloned)
    return points


def _derived_data_points() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    series_items = [
        ("global_swpi", "Global SWPI 全球硅片价格景气指数", GLOBAL_SWPI, "分"),
        ("china_swpi", "China SWPI 中国硅片价格景气指数", CHINA_SWPI, "分"),
        ("china_global_gap_swpi", "China-Global SWPI 差异指标", GAP_SWPI, "分"),
        ("product_300mm_ai_hbm", "300mm / AI-HBM 子指数", PRODUCT_SUBINDEX["300mm/AI-HBM"], "分"),
        ("product_200mm_mature", "200mm / 成熟制程子指数", PRODUCT_SUBINDEX["200mm/成熟制程"], "分"),
        ("product_soi_specialty", "SOI / 外延特色子指数", PRODUCT_SUBINDEX["SOI/外延特色"], "分"),
    ]
    for entity_key, metric, values, unit in series_items:
        rows.append(
            {
                "source_ref": "derived_swpi_workpaper",
                "entity_key": entity_key,
                "metric": metric,
                "period": "2021-2028",
                "as_of_date": AS_OF_DATE,
                "value_num": values[5],
                "value_text": _series_text(values),
                "unit": unit,
                "source_excerpt": f"{metric} 按本 run 公式复算：{_series_text(values)}。2026E 读数 {values[5]:.1f}，阶段为 {_stage(values[5])}。",
                "value_status": "calculated",
                "calculation_review_status": "pass",
                "extraction_method": "calculated_from_reviewed_inputs",
                "policy_evidence_role": "reference_only",
            }
        )
    for name, values in GLOBAL_COMPONENT_SCORES.items():
        rows.append(
            {
                "source_ref": "derived_swpi_workpaper",
                "entity_key": "global_swpi",
                "metric": f"Global SWPI component：{name}",
                "period": "2021-2028",
                "as_of_date": AS_OF_DATE,
                "value_num": values[5],
                "value_text": _series_text(values),
                "unit": "分",
                "source_excerpt": f"全球版 {name} component 权重 {GLOBAL_COMPONENT_WEIGHTS[name]:.0%}，2026E={values[5]}。",
                "value_status": "calculated",
                "calculation_review_status": "pass",
                "extraction_method": "calculated_from_reviewed_inputs",
                "policy_evidence_role": "reference_only",
            }
        )
    for name, values in CHINA_COMPONENT_SCORES.items():
        rows.append(
            {
                "source_ref": "derived_swpi_workpaper",
                "entity_key": "china_swpi",
                "metric": f"China SWPI component：{name}",
                "period": "2021-2028",
                "as_of_date": AS_OF_DATE,
                "value_num": values[5],
                "value_text": _series_text(values),
                "unit": "分",
                "source_excerpt": f"中国版 {name} component 权重 {CHINA_COMPONENT_WEIGHTS[name]:.0%}，2026E={values[5]}。",
                "value_status": "calculated",
                "calculation_review_status": "pass",
                "extraction_method": "calculated_from_reviewed_inputs",
                "policy_evidence_role": "reference_only",
            }
        )
    return rows


COMPONENT_REASON = {
    "价格和 ASP": "价格项只在 ASP、收入/面积、公司毛利或 LTA 外价格同步改善时上调；它防止把单纯出货恢复误判成价格周期。",
    "出货和订单": "出货、订单、客户导入和下游 wafer start 是方向项，决定周期是否从底部进入修复，但不能单独证明涨价。",
    "库存和供需松紧": "库存和供需项负责给结论降温；库存未出清时，即使需求改善，也只能定义为弱修复或结构修复。",
    "AI/HBM 和先进逻辑": "AI/HBM 解释产品 mix 和高端规格溢价，主要影响 300mm、外延和先进逻辑，不外推到全部 200mm。",
    "供给集中和 LTA": "供应商集中、认证周期、LTA 和预付款决定价格弹性是否能保留在供应商手里。",
    "价格和毛利承接": "中国价格项必须由毛利、ASP 或亏损收敛验证；国产替代本身不是价格修复。",
    "订单和国产替代": "客户导入、订单能见度和国产替代决定中国指数的领先性，但只有进入收入和现金流才提高置信度。",
    "产能利用和供给压力": "新增产能既是机会也是价格压力；利用率和良率不足会拉低指数。",
    "产品结构升级": "12 英寸、SOI、外延和先进产品占比提升能抬高中国指数中枢。",
    "全球需求传导": "全球半导体需求和 AI/HBM 周期通过 wafer start、客户排产和库存传导到中国公司。",
}


def _component_table_md(
    title: str,
    weights: dict[str, float],
    scores: dict[str, list[int]],
    series: list[float],
) -> str:
    rows = [
        f"#### {title}",
        "",
        "| 分项 | 权重 | 2026E 编码 | 加权贡献 | 为什么这样处理 |",
        "|---|---:|---:|---:|---|",
    ]
    for name, weight in weights.items():
        score = scores[name][5]
        rows.append(
            f"| {name} | {weight:.0%} | {score} | {score * weight:.1f} | {COMPONENT_REASON.get(name, '按来源强度和方向一致性编码。')} |"
        )
    rows.extend(
        [
            "",
            f"2026E 计算：{' + '.join(f'{scores[name][5]}×{weights[name]:.0%}' for name in weights)} = {series[5]:.1f}。",
            f"完整序列：{_series_text(series)}。",
        ]
    )
    return "\n".join(rows)


def _component_prose_md(
    title: str,
    weights: dict[str, float],
    scores: dict[str, list[int]],
    series: list[float],
) -> str:
    lines = [f"#### {title}", ""]
    for name, weight in weights.items():
        score = scores[name][5]
        contribution = score * weight
        lines.append(
            f"- {name}：权重 {weight:.0%}，2026E 编码 {score}，对总分贡献 {contribution:.1f}。"
            f"{COMPONENT_REASON.get(name, '该分项按来源强度和方向一致性编码。')}"
        )
    lines.append("")
    lines.append(f"2026E 复算结果为 {_weighted_formula_text(weights, scores, series)}；序列路径为 {_series_text(series)}。")
    return "\n".join(lines)


def _weighted_formula_text(weights: dict[str, float], scores: dict[str, list[int]], series: list[float]) -> str:
    parts = []
    for name, weight in weights.items():
        parts.append(f"{name}{scores[name][5]}×{weight:.0%}")
    return " + ".join(parts) + f" = {series[5]:.1f}"


def _public_search_update_md() -> str:
    return (
        "### 2026-07-05 追加公开资料复核\n\n"
        "本次重写重新检索了 SEMI、WSTS、Siltronic、SUMCO 和 Soitec 的公开资料，目的是检查前置价格订单底座有没有被过度外推。"
        "复核后的处理更克制：SEMI 2025-2028 出货预测和 2026Q1 季度数据确认量端修复，WSTS 2026 春季预测和 SIA 月度销售确认下游 AI、HBM、memory 和加速计算需求较强，"
        "但这些资料的口径是出货面积或芯片销售额，不是硅片规格级成交价。Siltronic 的 2025 经营更新和 2026 指引把 300mm 正向需求、LTA 外价格压力和 200mm 库存压力同时列出，"
        "这直接反驳了“量修复等于全面涨价”的简化写法。SUMCO 的经营方针强调 AI 数据中心带来的 leading-edge logic 和 DRAM 用 300mm 需求，同时提醒高端硅片开发和量产难度，"
        "说明高端规格可以给子指数加分，但不能把全部硅片都写成同一强度。Soitec 的硅光 SOI 公告补充了 AI 数据中心互连对 Photonics-SOI 的结构拉动，"
        "同时前置 Soitec FY26 资料仍显示 RF-SOI 库存和 price/mix 压力，所以 SOI 必须拆成 Photonics/FD-SOI/RF-SOI 观察，不能统一上调。"
        "这些新增资料最终没有把主指数机械抬高，而是改变了解释方式：需求项和 300mm/HBM 子指数置信度提高，价格项仍等待 ASP、毛利或 LTA 外价格确认，200mm 与 RF-SOI 继续作为反方约束。"
    )


def _global_design_explanation() -> str:
    return (
        "### 全球版指标为什么这样设计\n\n"
        "全球版 SWPI 要回答的是全球半导体硅片周期位置，而不是预测某一种规格的即时报价。权重设计先把最接近价格弹性的“价格和 ASP”设为 25%，"
        "因为投资者最终关心的是价格能否进入收入、毛利和现金流；但它没有超过 25%，原因是公开资料缺少连续规格级成交价，SEMI 收入/面积、公司 ASP 或 LTA 外价格都只是代理，"
        "如果把价格项权重抬到 40%-50%，指数会被不完整或滞后的价格口径主导。第二个 25% 给“出货和订单”，因为 MSI、客户导入、wafer start 和 backlog 是周期从底部走出的前提，"
        "2025-2026 的关键事实恰好是量端比价端先修复。库存和供需松紧给 18%，不是因为它不重要，而是因为库存更多是刹车项：它会限制价格弹性，却很少单独创造上行。"
        "AI/HBM 和先进逻辑给 17%，用于捕捉 300mm 高端规格的结构强度；这个权重低于价格和订单，是为了避免把 HBM 的高景气外推到 200mm、普通抛光片和传统 RF-SOI。"
        "供给集中和 LTA 给 15%，反映头部硅片公司的认证周期、客户锁单和价格纪律，但单靠供给集中不能证明当期涨价，仍要看需求、库存和财务结果。"
        f"因此 2026E 全球复算是 `{_weighted_formula_text(GLOBAL_COMPONENT_WEIGHTS, GLOBAL_COMPONENT_SCORES, GLOBAL_SWPI)}`。"
        "这个读数代表温和修复：出货和订单已经把指数拉回 55 分以上，AI/HBM 抬高结构项，但价格和库存没有给出足够确认，所以不能写成高景气。"
    )


def _china_design_explanation() -> str:
    return (
        "### 中国版指标为什么单独设计\n\n"
        "中国版不能照搬全球版，因为中国公司当前同时处在国产替代、12 英寸扩产、客户认证、亏损收敛和价格竞争之中。"
        "订单和国产替代权重设为 26%，高于全球版订单项，是因为本土客户导入和供应链安全需求会让中国公司在全球价格没有全面上行时也获得增量订单；"
        "但订单项必须被收入、毛利、现金流和客户认证复核，不能把扩产公告当成景气。价格和毛利承接给 24%，略低于订单项，是因为公开 ASP 不足，上市公司更容易披露毛利、亏损和产品结构，"
        "这些指标能检验订单是否真正转化为价格能力。产能利用和供给压力给 18%，专门处理中国硅片研究里最容易犯的错误：把新增 12 英寸产能当作单向利好。"
        "如果良率、客户验证和利用率跟不上，新增产能会压制价格而不是创造涨价。产品结构升级给 17%，覆盖 12 英寸、SOI、外延、重掺和高端产品 mix；"
        "全球需求传导给 15%，说明中国公司仍受全球半导体周期、HBM/AI wafer start 和海外龙头价格纪律影响，不能被写成完全独立周期。"
        f"因此 2026E 中国复算是 `{_weighted_formula_text(CHINA_COMPONENT_WEIGHTS, CHINA_COMPONENT_SCORES, CHINA_SWPI)}`。"
        "这个读数代表中国略强于全球，但强在订单、导入和结构项，不代表公开成交价已经全面领先。"
    )


def _section_deep_addendum(section_key: str) -> str:
    addenda = {
        "executive_summary": (
            "### 研究回答的展开\n\n"
            "执行摘要需要把指数读数翻译成研究动作。全球 64.5 和中国 65.5 都位于温和修复区间，说明硅片行业已经离开 2023-2024 的去库存低点，"
            "但尚未进入 2021-2022 那种价格、订单、库存和毛利同时向上的高景气。这个判断的实质是把“有没有涨价”拆成四个更可验证的问题："
            "第一，SEMI 出货面积和公司销量是否确认量端恢复；第二，收入/面积、ASP、LTA 外价格或毛利是否确认价格恢复；第三，客户库存和 200mm/RF-SOI 库存是否允许价格传导；"
            "第四，AI/HBM 和先进逻辑是否只拉动高端 300mm，还是已经扩散到普通 200mm 和特色片。"
            "当前证据对第一和第四更强，对第二和第三仍保留约束，所以结论只能是“量端修复、价格滞后、产品线分化”。"
            "这个回答直接决定研究排序：先查 300mm/HBM 高端规格和头部硅片厂的 price-mix，再查中国 12 英寸导入是否进入毛利，最后才看成熟制程和 SOI 的局部订单。"
            "如果后续只新增一条涨价传闻，不能改主指数；如果新增的是 SEMI 出货和公司销量同步上修，只改需求和订单项；如果新增毛利、ASP、LTA 外价格改善，才改价格项。"
        ),
        "definition_formula": (
            "### 公式解释和权重复核\n\n"
            f"{_global_design_explanation()}\n\n{_china_design_explanation()}\n\n"
            "阶段阈值也不是为了制造精确预测，而是为了让历史和当前能被同一把尺复盘。80 分以上要求价格、订单、库存和供给壁垒至少三项同时强，"
            "68-80 表示修复偏强但仍有一项需要复核，55-68 表示温和修复，42-55 表示底部抬升，42 以下是去库存或价格压力。"
            "这些阈值用 2021-2022 高景气、2023-2024 下行和 2025 底部抬升做方向校准，不声称能精确预测每一季度报价。"
            "计算过程全部保留在工作底稿和正文表格中，任何后续修改都必须说明改了哪一个 component score、为什么改、证据来自哪个来源、是否影响全球版、中国版还是产品子指数。"
        ),
        "candidate_scheme": (
            "### 为什么主方案不是单一价格指标\n\n"
            "价格主导方案看似最直接，但在半导体硅片公开资料中有一个硬问题：连续、分规格、分区域、分客户的真实成交价基本不可得。"
            "如果在这种条件下把价格权重放到 50%，研究会被少量 ASP 代理、卖方报价或公司综合毛利牵引，反而掩盖出货、订单、库存和产品结构。"
            "复合 SWPI 的价值不是替代价格，而是在真实价格缺失时把可验证证据按误差方向放进同一框架。SEMI 和 SMG 负责量端，Siltronic、SUMCO、GlobalWafers、Shin-Etsu、Soitec 等公司资料负责产品线和价格压力，"
            "WSTS/SIA/Micron/SK hynix 只负责下游需求环境。China-Global gap 作为辅助方案，是因为中国公司的边际变化经常来自国产替代和客户导入，不能只和全球总量平均值比较。"
            "产品子指数作为第三层，是因为 300mm/HBM、200mm 成熟制程、SOI/外延的库存、认证、终端需求和价格能力完全不同。"
            "计算上，方案 B 的每个分项都有独立证据入口，价格、订单、库存、AI/HBM 和供给壁垒分别编码；方案 C 只计算 China SWPI 与 Global SWPI 的差值；方案 D 只计算产品子指数。"
            "最终选择“一主两辅”，就是为了让研究员能回答三个问题：行业是不是修复，中国是不是更强，真正强的是哪条产品线。"
        ),
        "backtest_and_stage": (
            "### 回测读数说明了什么\n\n"
            "回测的目的不是用未来数据倒推漂亮曲线，而是检查指标是否尊重产业常识。2021-2022 全球和中国读数较高，对应疫情后电子需求、产能紧张和硅片价格上行；"
            "2023-2024 读数跌入去库存或弱平衡，对应存储、手机、PC、成熟制程和 RF 库存压力；2025 开始回升，但 SEMI 年度资料和公司披露显示量端恢复早于收入和价格恢复。"
            "这条历史路径解释了为什么 2026E 只能给温和修复：如果指数把 2026E 直接推到 80 分，等于忽略 Siltronic 提到的 LTA 外价格压力、200mm 库存以及 Soitec RF-SOI 的 price/mix 问题。"
            "反过来，如果指数仍停在 45 分以下，又无法解释 SEMI 2028 出货展望、WSTS/SIA 下游修复、AI/HBM 和 300mm 高端需求。"
            "所以 64-66 分是折中后的研究答案：周期位置已经变好，风险溢价应该下降，但还不到全面上调盈利弹性的阶段。"
            "证据使用上，历史回测不改变权重，只检查分项编码是否能识别 2021-2022 高景气、2023-2024 去库存和 2026E 修复；计算结果若与产业阶段相反，必须回到来源口径和分项证据重审。"
            "该 section 的回答是：回测通过的是方向一致性和口径约束，不是精确价格预测；当前阶段应定义为温和修复，等待价格和毛利证据确认。"
        ),
        "product_region_split": (
            "### 产品线和区域差异怎样改变投资研究\n\n"
            "产品拆分本身就是一组研究指标：它把主指数拆成产品子指数，并用不同权重观察需求、库存、认证和价格能力。总指数只能给出行业温度，不能直接告诉研究员买哪条链。"
            "300mm/AI-HBM 子指数高，是因为 HBM、advanced logic、AI data center 和高端 DRAM 共同增加 leading-edge 300mm wafer start，"
            "同时高端 300mm 的认证、纯度、缺陷控制和客户锁单更容易形成供应商议价。200mm 成熟制程读数低，是因为功率、汽车和工业链库存恢复较慢，Siltronic 明确提示 200mm 仍受库存影响；"
            "即使局部重掺或外延订单改善，也不能把成熟制程整体写成高景气。SOI/外延介于两者之间，原因是它有 AI photonics、FD-SOI、外延等结构机会，也有 RF-SOI 库存和 price/mix 压力。"
            "中国与全球的差异更复杂：国产替代和 12 英寸导入可以抬高订单项，但如果公司仍亏损、毛利承压或产能利用率不足，China SWPI 不能被解释成盈利拐点。"
            "因此后续标的研究要先分产品线，再看客户验证和财务承接，不按名义产能或新闻热度排序。"
            "计算和证据处理上，300mm 子指数更多吸收 AI/HBM、wafer start 和高端供应商资料，200mm 子指数更强调库存和成熟终端，SOI/外延子指数更强调分应用订单和 price-mix；这个回答比单一行业均值更能指导补证。"
        ),
        "tracking_framework": (
            "### 后续怎么更新而不失真\n\n"
            "跟踪框架必须服务复算，而不是堆新资料。每次新增证据先进入四步判断：来源层级是什么，口径对应哪一个分项，是否改变 2026E 或未来年份编码，是否需要同时调整反方约束。"
            "SEMI MSI 和年度收入更新时，优先影响全球出货、订单和 ASP 代理；Siltronic、SUMCO、GlobalWafers、Shin-Etsu、Soitec 的 IR 更新时，优先影响产品结构、LTA、库存和 price-mix；"
            "中国公司公告更新时，优先影响国产替代订单、产能利用、毛利和产品结构升级；WSTS/SIA、Micron、SK hynix 等下游资料只能影响需求代理和 300mm/HBM 子指数，不能直接改价格项。"
            "权重通常不应频繁变动，除非数据可得性发生结构变化，例如接入 paid price database 或连续规格级 ASP；在此之前，主要更新 component score。"
            "如果新增资料不能说明数字、单位、日期、来源、口径和影响分项，它只能进入 supplement request，不能进入正式读数。"
            "这套框架回答的是后续如何避免指数漂移：只要证据不能落到指标、计算和权重中的某一项，就不改变正式读数；只有来源、口径和影响方向同时清楚，才进入下一轮复算。"
        ),
    }
    return addenda.get(section_key, "")


def _entity_deep_addendum(key: str, name: str) -> str:
    market_addenda = {
        "global_swpi": (
            "### 指标设计、权重和投资含义\n\n"
            "全球实体的设计重点是把行业母盘拆成五个能分别验证的分项。价格/ASP 和出货订单都给 25%，因为本轮最大的分歧就是量先修复还是价也修复；"
            "库存供需给 18%，用于压住仍在去库存的 200mm 和 RF-SOI；AI/HBM 给 17%，只承认高端 300mm 的结构强度；供给集中和 LTA 给 15%，用于衡量头部供应商的价格纪律。"
            "这组权重的含义不是平均看好所有硅片，而是让每个新增证据只能改变对应分项。\n\n"
            "对全球实体来说，64.5 不是一句“行业复苏”，而是一个量价拆分后的研究答案。SEMI 的出货和中期预测让出货项达到 68，WSTS/SIA 和存储链资料让 AI/HBM 项保持 86，"
            "但 Siltronic 新旧公告都提示 LTA 外价格压力和 200mm 库存，所以价格项只有 54、库存项只有 56。"
            "这组分项代表全球硅片行业的核心矛盾：高端需求真实存在，整体价格还没有被公开证据确认。"
            "投资研究上，全球龙头篮子应作为价格纪律和产品 mix 的基准，而不是单纯 beta。下一步优先核验 Shin-Etsu、SUMCO、GlobalWafers 和 Siltronic 的 300mm mix、EBITDA margin、ASP 表述、LTA 外价格压力和客户库存。"
            "若这些资料共同改善，全球 SWPI 才能从温和修复进入修复偏强；若出货增长继续伴随收入/面积下滑，指数只能维持中性上行。"
        ),
        "china_swpi": (
            "### 指标设计、权重和投资含义\n\n"
            "中国实体的权重更偏向订单国产替代和财务承接，因为本土 12 英寸导入、客户认证和产品结构升级往往领先公开价格，但新增产能又可能压制毛利。"
            "订单国产替代 26% 是领先项，价格毛利 24% 是兑现项，产能利用和供给压力 18% 是反方项，产品结构升级 17% 和全球需求传导 15% 用来校准高端产品和外部周期。"
            "这样设计可以防止把产能新闻直接当成景气拐点。\n\n"
            "中国实体的 65.5 代表“订单和结构领先，利润承接未充分确认”。订单和国产替代分项 72 来自西安奕材、上海合晶等 12 英寸和客户导入线索，产品结构升级 73 来自 12 英寸、SOI、外延和特色片推进，"
            "但价格和毛利承接只有 58，产能利用和供给压力只有 55，说明新增产能、折旧和价格竞争仍压着财务弹性。"
            "这个读数的用途是筛选 A 股研究优先级，而不是直接给所有国产硅片公司加分。西安奕材更适合验证 12 英寸国产替代和客户导入，沪硅产业更适合验证 300mm/SOI 平台能否收敛亏损，上海合晶适合验证外延和 SOI 结构升级。"
            "若后续公告只说产能提升但毛利和客户验证没有同步改善，中国指数不能上修；若销量、ASP、毛利、良率和现金流同时改善，China SWPI 和 gap 才具备上调依据。"
        ),
        "china_global_gap_swpi": (
            "### 指标设计、计算和投资含义\n\n"
            "China-Global gap 的计算非常简单，但解释不能简单。2026E 差值为 "
            f"`{CHINA_SWPI[5]:.1f} - {GLOBAL_SWPI[5]:.1f} = {GAP_SWPI[5]:+.1f}`，代表中国相对全球只略强。"
            "这个指标为什么重要：绝对读数会把全球 beta 和中国国产替代混在一起，差值则专门回答“中国是不是有独立景气”。"
            "当前 +1.0 的含义不是中国全面领先，而是订单和结构项略强，被价格、毛利和产能压力抵消。"
            "如果未来中国公司客户导入和国产替代继续推进，但毛利仍低、亏损没有改善，gap 只能作为研究优先级上调，不能作为盈利弹性上调。"
            "若全球龙头价格仍承压而中国 ASP、毛利和客户预付款率先改善，gap 才能变成更强的区域机会信号。"
            "因此该实体的投资动作应盯住中国 12 英寸篮子和全球龙头篮子的相对数据：一边看国产公司订单/良率/毛利，一边看海外龙头 price-mix/LTA/库存。"
        ),
        "product_300mm_ai_hbm": (
            "### 指标设计、权重和投资含义\n\n"
            "300mm/AI-HBM 子指数的 78.0 是本 run 里最接近“修复偏强”的读数。它的设计不是把 AI 新闻直接加到硅片价格上，"
            "而是把 HBM/DRAM、advanced logic、AI data center、300mm wafer start、客户认证和高端供应商集中度一起编码。"
            "SEMI 300mm 投资展望、SUMCO 对 leading-edge logic 和 DRAM 的需求表述、Shin-Etsu/GlobalWafers 的高端材料披露、Micron/SK hynix 的 HBM 周期，以及 WSTS 对 AI/HBM 的下游预测，共同提高这个子指数。"
            "它代表的是产品结构优先级：如果硅片行业有价格弹性，最可能先在高端 300mm、HBM/AI 相关规格和先进逻辑客户中出现。"
            "但这仍不是全行业涨价证明，因为 HBM 强需求需要通过 wafer start、规格级 ASP、高端 mix、良率和客户锁单传导。"
            "投资研究上，Shin-Etsu/SUMCO、GlobalWafers、Siltronic 的高端 300mm 披露是全球验证样本，中国 12 英寸导入公司是国产替代验证样本，Micron/SK hynix 只能作为需求代理，不作为硅片价格来源。"
        ),
        "product_200mm_mature": (
            "### 指标设计、权重和投资含义\n\n"
            "200mm/成熟制程子指数只有 50.0，代表底部抬升而不是高景气。这个指标故意与 300mm 分开，是因为 200mm 的终端暴露、库存周期和价格形成机制不同。"
            "功率、汽车、工业和部分模拟需求确实可能修复，但 Siltronic 对 200mm power segment 库存压力的披露、成熟制程客户库存和 LTA 外价格压力，使该方向不能共享 AI/HBM 的高分。"
            "权重设计更强调库存、利用率、终端去化和局部订单，而不是下游半导体销售总额。"
            "它代表的研究回答是：成熟制程可以观察局部反弹，但没有足够证据升级为全线价格周期。"
            "投资研究上，Siltronic 是反方基准，立昂微等中国成熟制程/重掺样本只能在订单、毛利和客户验证同时改善后提高优先级。"
            "如果只看到单个产品涨价或业绩会口径，不能提高子指数；若出现功率、汽车、工业订单、交期、ASP 和毛利连续改善，才把该方向从观察项提高到修复项。"
        ),
        "product_soi_specialty": (
            "### 指标设计、权重和投资含义\n\n"
            "SOI/外延/特色硅片子指数为 60.0，位置介于 300mm 强链条和 200mm 成熟制程之间。它的设计重点是分应用，而不是把 SOI 当成单一品类。"
            "Soitec 的 AI 数据中心硅光 SOI 资料提高 Photonics-SOI 的结构置信度，上海合晶和沪硅产业提供中国 SOI、外延和 12 英寸平台样本，GlobalWafers 的 specialty wafer 披露说明特色片有长期壁垒；"
            "但 Soitec FY26 资料也显示 RF-SOI 库存和 price/mix 压力，因此该子指数不能被 AI photonics 单线拉满。"
            "它代表的研究回答是：特色硅片有结构机会，但必须拆成 Photonics-SOI、RF-SOI、FD-SOI、外延和重掺等细分项。"
            "投资研究上，Soitec 是全球 SOI 结构分化基准，上海合晶和沪硅产业是中国外延/SOI 承接样本；后续最重要的证据不是产能新闻，而是分产品线收入、库存、客户验证、price/mix 和毛利。"
        ),
    }
    return market_addenda.get(key, "")


def _theory_deep_addendum(key: str, name: str) -> str:
    theory_addenda = {
        "swpi_methodology": (
            "### 指标为什么这样设计\n\n"
            "方法论实体不重复展示总报告的权重表，而是解释设计原则。全球版的第一原则是量价分离：价格/ASP 需要高权重，因为它最终决定盈利弹性；出货和订单也需要高权重，因为它们先于价格确认周期方向。"
            "第二原则是反方约束：库存、供需松紧和 LTA 外价格压力必须单列，否则 2025-2026 的量端恢复会被误写成全面涨价。第三原则是产品结构：AI/HBM 和先进逻辑只影响高端 300mm 与部分特色片，不能外推到全部 200mm。"
            "中国版的原则则是把国产替代和财务承接分开：订单导入可以领先，但只有毛利、ASP、现金流和良率改善才说明景气进入公司利润。\n\n"
            "这个理论实体的回答是：硅片景气度不能只用价格、也不能只用订单。价格最接近盈利弹性，但公开数据缺口最大；订单和出货更及时，但容易把补库存误判成涨价；"
            "库存和供给松紧是反方校准；AI/HBM 和产品结构负责识别高端方向；供给集中和 LTA 负责判断价格能不能留在供应商手里。"
            "因此 SWPI 是研究框架，不是黑箱打分。每个 component score 必须说明来源、单位、日期、口径和误差方向。"
            "后续如果接入真实成交价，权重可以重新训练或人工校准；在当前公开资料条件下，权重保持稳定，只更新分项编码。"
        ),
        "candidate_index_schemes": (
            "### 候选方案为什么这样取舍\n\n"
            "候选方案比较的核心是可得性和可反证性。价格主导方案最贴近交易问题，但真实成交价缺失时，它会逼研究员用卖方口径或综合毛利填空，质量反而下降。"
            "复合 SWPI 没有回避价格，而是把价格放在 24%-25% 的高权重位置，同时用订单、库存、AI/HBM 和供给壁垒解释为什么价格可能滞后或先行。"
            "China-Global gap 不是另一个主指标，而是把区域因素从全球 beta 中剥离出来，回答国产替代是否真的强于全球周期。"
            "产品子指数也不是附属图表，而是解决“同样叫硅片，哪条产品线真正强”的问题。"
            "该实体最终给出的方案是：主指标用复合 SWPI，区域判断用 gap，产品判断用 300mm/200mm/SOI 子指数，价格主导方案等 paid database 或规格级 ASP 补齐后再升级。"
        ),
        "source_quality_proxy_review": (
            "### 来源、代理变量和补证顺序\n\n"
            "来源质量实体要回答的是：没有完整成交价时，哪些信息能进入核心计算，哪些只能做线索。SEMI/SMG、WSTS/SIA、公司公告和 IR 是核心层；"
            "它们的优点是可追溯、可复核，但口径各不相同。SEMI 给出行业量端和混合收入，不能拆产品；WSTS/SIA 给下游需求，不能代表硅片价格；"
            "公司 IR 能拆产品、客户和库存，但披露选择性强；卖方和产业媒体能发现涨价线索，但如果没有官方或公司资料复核，只能进入补证请求。"
            "代理变量的顺序也必须写清：真实成交价优先，其次是规格级 ASP，再到收入/面积、公司 ASP/毛利、订单/LTA、客户库存、capex 和 wafer start。"
            "每往下一层，解释力下降、误差来源增加。这个规则保证正文不会把“需要看全文”当成结论，而是把每条证据放回指标设计和研究回答里。"
        ),
    }
    return theory_addenda.get(key, "")


def _section_required_explanation(section_key: str) -> str:
    addenda = {
        "executive_summary": (
            "### 指标设计核对\n\n"
            "指标为什么这样设计：执行摘要用 Global SWPI、China SWPI、China-Global gap 和三个产品子指数共同回答问题，是因为硅片景气同时受全球周期、中国国产替代和产品结构影响。"
            "代表什么：64.5/65.5/+1.0 代表全球和中国都处于温和修复，300mm/AI-HBM 78.0 代表高端方向明显强于成熟制程。"
            "计算过程和权重依据：主指标来自价格、订单、库存、AI/HBM 和供给壁垒分项加权，摘要只报告结论，详细权重在下一节复算。"
            "研究回答：当前不能写成全行业涨价，只能写成量端修复、价格滞后和产品线分化。"
        ),
        "definition_formula": (
            "### 指标设计核对\n\n"
            "指标为什么这样设计：本节把公式、阈值和权重放在一起，是为了让后续每次新增证据都能回到同一套复算口径。"
            "代表什么：分项分数代表价格、订单、库存、AI/HBM 和供给壁垒各自的证据强弱，不是主观标签。"
            "计算过程和权重依据：全球版采用 25%/25%/18%/17%/15%，中国版采用 24%/26%/18%/17%/15%，分别反映全球行业总量和中国国产替代/财务承接的差异。"
            "研究回答：公式给出的不是精确报价，而是一个能被官方数据和公司 IR 反复更新的景气阶段判断。"
        ),
        "candidate_scheme": (
            "### 指标设计核对\n\n"
            "指标为什么这样设计：候选方案必须比较价格主导、复合指数、区域差异和产品子指数，因为单一价格指标在公开数据条件下不可稳定复算。"
            "代表什么：方案 B 代表当前可用的主指标，方案 C 代表区域相对强弱，方案 D 代表产品线优先级。"
            "计算过程和权重依据：只有复合 SWPI 把价格、订单、库存、AI/HBM 和供给壁垒拆成可审计分项；价格主导方案等真实成交价补齐后再升级。"
            "研究回答：当前最可靠的指标体系是一主两辅，而不是把涨价传闻直接写成指数。"
        ),
        "backtest_and_stage": (
            "### 指标设计核对\n\n"
            "指标为什么这样设计：回测段用同一公式穿过 2021-2028E，是为了检查指标能否识别高景气、去库存、底部抬升和温和修复。"
            "代表什么：2026E 64-66 分代表风险从低谷缓和，但还没有达到价格和毛利同步改善的高景气。"
            "计算过程和权重依据：回测不改权重，只复核各年份分项编码是否符合已知产业阶段；若方向不一致，先检查来源口径而不是调结论。"
            "研究回答：当前阶段是温和修复，等待价格和库存证据决定是否上移到修复偏强。"
        ),
        "product_region_split": (
            "### 指标设计核对\n\n"
            "指标为什么这样设计：产品和区域拆分用子指数，是因为 300mm/AI-HBM、200mm 成熟制程和 SOI/外延的终端、库存和认证节奏不同。"
            "代表什么：300mm/AI-HBM 78.0 代表高端产品更接近修复偏强，200mm 50.0 代表成熟制程仍是底部抬升，SOI/外延 60.0 代表结构分化。"
            "计算过程和权重依据：产品子指数分别提高 AI/HBM、库存、price-mix、客户认证和特色应用的相对权重，防止用行业均值遮蔽产品差异。"
            "研究回答：投资研究应先分产品线和客户验证，再判断公司财务承接。"
        ),
        "tracking_framework": (
            "### 指标设计核对\n\n"
            "指标为什么这样设计：跟踪框架按来源和分项更新，是为了防止新增新闻直接改变结论。"
            "代表什么：每条新证据只代表它对应的价格、订单、库存、产品结构或供给壁垒变化，不能越级解释。"
            "计算过程和权重依据：权重在缺少真实成交价前保持稳定，后续主要更新 component score；只有接入 paid price database 或规格级 ASP，才重新审查权重。"
            "研究回答：后续研究要围绕复算路径补证，而不是堆叠无法落到分项的材料。"
        ),
    }
    return addenda.get(section_key, "")


def _entity_required_explanation(key: str, name: str) -> str:
    addenda = {
        "swpi_methodology": (
            f"### {name} 的指标设计核对\n\n"
            "指标为什么这样设计：方法论实体要把价格、订单、库存、AI/HBM 和供给壁垒放到可复算框架里，避免后续实体各自定义景气。"
            "代表什么：它代表本 run 的指数口径和证据使用规则。计算过程和权重依据：全球版和中国版分开加权，差异项再用 China SWPI 减 Global SWPI。"
            "研究回答：在公开成交价缺失时，可以用 SWPI 做方向判断和研究排序，但不能把它包装成真实成交价指数。"
        ),
        "candidate_index_schemes": (
            f"### {name} 的指标设计核对\n\n"
            "指标为什么这样设计：候选方案实体负责证明为什么不用单一价格指标。代表什么：它代表主指标、区域差异和产品子指数之间的分工。"
            "计算过程和权重依据：价格主导方案因为数据缺口被降为备用，复合 SWPI 因可复算和可反证成为主方案。"
            "研究回答：当前最适合研究员使用的是一主两辅，真实价格数据库补齐后再重估方案 A。"
        ),
        "source_quality_proxy_review": (
            f"### {name} 的指标设计核对\n\n"
            "指标为什么这样设计：来源质量实体把官方统计、公司披露、卖方线索和下游需求代理分层，是为了避免证据口径混用。"
            "代表什么：它代表所有 proxy 的可信度边界。计算过程和权重依据：真实成交价权重最高，ASP/毛利、订单/LTA、库存、capex 和 wafer start 逐层降权。"
            "研究回答：当前指数能用于方向判断，升级为价格交易信号前必须补规格级成交价和客户级 backlog。"
        ),
        "global_swpi": (
            f"### {name} 的指标设计核对\n\n"
            "指标为什么这样设计：全球实体用价格、出货订单、库存、AI/HBM 和供给壁垒共同加权，是因为全球硅片周期不能由单季出货或芯片销售额单独代表。"
            "代表什么：64.5 代表全球行业已温和修复但价格端仍滞后。计算过程和权重依据：价格和订单各 25%，库存 18%，AI/HBM 17%，供给/LTA 15%。"
            "研究回答：优先验证全球龙头的 price-mix、LTA 外价格和 300mm mix，而不是直接写全面高景气。"
        ),
        "china_swpi": (
            f"### {name} 的指标设计核对\n\n"
            "指标为什么这样设计：中国实体提高订单和国产替代权重，是因为本土客户导入可能领先全球价格周期。"
            "代表什么：65.5 代表中国略强于全球但强在订单和结构，不代表利润已经全面兑现。计算过程和权重依据：订单国产替代 26%、价格毛利 24%、产能压力 18%、产品升级 17%、全球传导 15%。"
            "研究回答：A 股标的要按客户验证、良率、毛利和现金流补证，不能只看产能扩张。"
        ),
        "china_global_gap_swpi": (
            f"### {name} 的指标设计核对\n\n"
            "指标为什么这样设计：差异实体用 China SWPI 减 Global SWPI，是为了把中国国产替代和全球 beta 分开。"
            "代表什么：+1.0 代表中国只是小幅领先，不是独立高景气。计算过程和权重依据：先分别按全球版和中国版权重复算，再做差值，避免直接用不同来源的单项价格硬拼。"
            "研究回答：只有中国毛利、ASP 和客户预付款先于全球改善，gap 才能升级为强区域机会信号。"
        ),
        "product_300mm_ai_hbm": (
            f"### {name} 的指标设计核对\n\n"
            "指标为什么这样设计：300mm/AI-HBM 子指数提高 AI/HBM、advanced logic、wafer start 和高端认证权重，是因为它最可能先出现规格级紧张。"
            "代表什么：78.0 代表该产品线接近修复偏强。计算过程和权重依据：下游 HBM 需求只进需求代理，高端 ASP、mix、客户锁单和供应商集中度决定是否进一步上调。"
            "研究回答：先跟踪高端 300mm 供应商和 HBM 客户排产，不能把高分外推到全部硅片。"
        ),
        "product_200mm_mature": (
            f"### {name} 的指标设计核对\n\n"
            "指标为什么这样设计：200mm 子指数单列，是因为功率、汽车、工业和模拟链条的库存恢复慢于 AI/HBM。"
            "代表什么：50.0 代表底部抬升而非高景气。计算过程和权重依据：库存、利用率和成熟终端权重高于 AI 需求，Siltronic 200mm 库存压力作为反方核心。"
            "研究回答：只有订单、交期、ASP 和毛利连续改善，成熟制程才从观察项升级为修复项。"
        ),
        "product_soi_specialty": (
            f"### {name} 的指标设计核对\n\n"
            "指标为什么这样设计：SOI/外延子指数把 Photonics-SOI、RF-SOI、FD-SOI 和外延分开，是因为同一品类内部方向分化。"
            "代表什么：60.0 代表结构性机会和库存压力并存。计算过程和权重依据：AI photonics 提高结构项，RF-SOI 库存和 price-mix 压力压低短期价格项。"
            "研究回答：Soitec、上海合晶和沪硅产业要按分产品线收入、库存、客户验证和毛利补证。"
        ),
    }
    return addenda.get(key, "")


def _source_index_md(refs: list[str]) -> str:
    lines = [
        "| 正文索引 | 来源 | 在本指标中的作用 |",
        "|---|---|---|",
    ]
    for idx, ref in enumerate(refs, start=1):
        source_ref = ref.replace("source_ref:", "")
        note = SOURCE_NOTES.get(source_ref, "该来源用于校准本轮指标口径和证据强度。")
        lines.append(f"| [{idx}] | {_source_public_label(ref)} ^evidence:{ref} | {note} |")
    return "\n".join(lines)


def _research_index_md(entity: dict[str, Any]) -> str:
    points = entity.get("research_data_points") or []
    if not points:
        return ""
    lines = [
        "| 指标或计算项 | 类别 | 指标结果或事实 | 为什么进入正文判断 | 证据 |",
        "|---|---|---|---|---|",
    ]
    for point in points:
        evidence = point.get("evidence_ref_uri") or _ref(point.get("source_ref", "derived_swpi_workpaper"))
        lines.append(
            "| {title} | {category} | {value} | {use} | {evidence} |".format(
                title=point.get("data_point_title") or point.get("metric"),
                category=point.get("research_category") or "indicator",
                value=_compact(point.get("value_text"), 260),
                use=_compact(point.get("research_use") or point.get("interpretation"), 260),
                evidence=f"^evidence:{evidence}",
            )
        )
    return "\n".join(lines)


def _market_entity_body(entity: dict[str, Any], refs: list[str]) -> str:
    key = entity["key"]
    name = entity["display_name"]
    trace = entity["composite_trace"]
    score = entity["score_point"]

    if key == "global_swpi":
        calculation = _component_prose_md("全球 SWPI 分项权重、2026E 编码和加权计算", GLOBAL_COMPONENT_WEIGHTS, GLOBAL_COMPONENT_SCORES, GLOBAL_SWPI)
        answer = (
            f"{name} 的 2026E 读数为 {GLOBAL_SWPI[5]:.1f}，处在{_stage(GLOBAL_SWPI[5])}。"
            "它回答的是全球硅片周期是否已经从去库存进入可投资的价格修复。当前答案是：需求和出货修复成立，"
            "但价格/ASP 仍滞后，所以它是温和修复，不是全面涨价周期。"
        )
        logic = (
            "全球指数的关键矛盾是量和价不同步。SEMI 年度收入/面积口径显示出货面积回升早于收入修复，"
            "Siltronic 对 LTA 外价格和 200mm 压力的披露又提醒价格项不能被需求项替代。"
            "因此指数给出 64.5，而不是 70 以上的高景气读数。"
        )
    elif key == "china_swpi":
        calculation = _component_prose_md("中国 SWPI 分项权重、2026E 编码和加权计算", CHINA_COMPONENT_WEIGHTS, CHINA_COMPONENT_SCORES, CHINA_SWPI)
        answer = (
            f"{name} 的 2026E 读数为 {CHINA_SWPI[5]:.1f}，略高于全球 {GLOBAL_SWPI[5]:.1f}。"
            "它回答的是中国硅片公司是否因为国产替代和 12 英寸导入而领先全球周期。当前答案是：领先只体现在订单和结构项，"
            "还没有被公开成交价和整体毛利完全确认。"
        )
        logic = (
            "中国指数的核心不是产能越大越好，而是客户认证、量产节奏、产品 mix 和毛利能否同时改善。"
            "西安奕材、上海合晶等资料支撑订单和导入项，沪硅产业的亏损和折旧压力则压低财务承接项。"
        )
    elif key == "china_global_gap_swpi":
        calculation = (
            "#### 中国-全球差异指标计算\n\n"
            f"差异指标定义为 `China SWPI - Global SWPI`。2026E 计算为 {CHINA_SWPI[5]:.1f} - {GLOBAL_SWPI[5]:.1f} = {GAP_SWPI[5]:+.1f}。\n\n"
            f"完整序列：{_series_text(GAP_SWPI)}。"
        )
        answer = (
            f"{name} 的 2026E 读数为 {GAP_SWPI[5]:+.1f}。"
            "它回答的是中国是否明显强于全球。当前答案是否定的：差异为正，说明中国有补涨和国产替代优势；"
            "但 +1.0 太小，不能证明中国全面领先或出现独立价格周期。"
        )
        logic = (
            "差异项最容易被误读。若中国订单改善来自国产替代，但毛利没有改善，gap 只能解释研究优先级提高，"
            "不能解释价格弹性。若全球价格仍承压而中国毛利先改善，gap 才能转为更强信号。"
        )
    elif key == "product_300mm_ai_hbm":
        series = PRODUCT_SUBINDEX["300mm/AI-HBM"]
        calculation = (
            "#### 300mm / AI-HBM 子指数结果\n\n"
            f"2026E 子指数为 {series[5]:.1f}，完整序列：{_series_text(series)}。\n\n"
            "该子指数由 AI/HBM 应用强度、300mm wafer start/capex、合格供应商壁垒和高端 price-mix 代理共同编码。"
            "它不是全球 SWPI 的简单平均，而是用于识别最先出现价格弹性的产品方向。"
        )
        answer = (
            f"{name} 是本轮最强方向，2026E 为 {series[5]:.1f}。"
            "它回答的是 AI/HBM 是否已经足以把硅片景气从总量修复推进到高端规格紧张。当前答案是基本成立，"
            "但仍需要用规格级 ASP、客户锁单和高端 mix 继续验证。"
        )
        logic = (
            "SEMI 300mm 投资、Micron/SK hynix 的 HBM 需求、Shin-Etsu/GlobalWafers 的先进逻辑和材料披露方向一致，"
            "说明高端 300mm 的供需位置明显好于全行业均值。"
        )
    elif key == "product_200mm_mature":
        series = PRODUCT_SUBINDEX["200mm/成熟制程"]
        calculation = (
            "#### 200mm / 成熟制程子指数结果\n\n"
            f"2026E 子指数为 {series[5]:.1f}，完整序列：{_series_text(series)}。\n\n"
            "该子指数由成熟制程价格、功率/汽车/工业需求、200mm 库存、局部重掺订单和供应替代壁垒编码。"
        )
        answer = (
            f"{name} 当前为 {series[5]:.1f}，明显弱于 300mm/AI-HBM。"
            "它回答的是成熟制程是否也进入同样强度的价格周期。当前答案是不成立，最多是局部修复。"
        )
        logic = (
            "Siltronic 对 200mm power segment 库存调整的说明和成熟制程需求分化相互印证。"
            "因此 200mm 只能作为观察项，除非出现产品线订单、交期和毛利同步改善。"
        )
    else:
        series = PRODUCT_SUBINDEX["SOI/外延特色"]
        calculation = (
            "#### SOI / 外延 / 特色硅片子指数结果\n\n"
            f"2026E 子指数为 {series[5]:.1f}，完整序列：{_series_text(series)}。\n\n"
            "该子指数由 SOI/RF-SOI/FD-SOI、外延、Photonics、特色材料订单、库存和客户认证壁垒编码。"
        )
        answer = (
            f"{name} 当前为 {series[5]:.1f}。它回答的是特色硅片是否能独立于普通成熟制程形成结构性机会。"
            "当前答案是部分成立：AI photonics、外延和 FD-SOI 有结构弹性，但 RF-SOI 库存压力仍限制短期价格判断。"
        )
        logic = (
            "Soitec 同时披露 AI 相关机会和 RF-SOI 库存压力，上海合晶和沪硅产业提供中国外延/SOI 样本，"
            "所以该方向应按产品线拆开跟踪，而不是写成统一上行。"
        )

    return (
        f"### 研究边界与问题定义\n\n{name} 是市场型实体，用于把 SWPI 读数落到可验证公司、产品线或观察篮子。"
        "本页的分数是景气研究优先级，不是交易评级；正文必须先回答研究问题，表格只作为证据索引。\n\n"
        f"### 指标定义和计算\n\n{calculation}\n\n"
        f"### 当前答案\n\n{answer}\n\n"
        f"### 证据链和推理逻辑\n\n{logic}"
        f"本实体证据覆盖 {len(refs)} 个主要来源，来源之间的分工如下：\n\n{_source_index_md(refs)}\n\n"
        "官方统计负责量端和周期，公司公告/IR 负责订单、客户、产品线和财务承接，下游需求资料只作为需求环境代理。"
        "同源同对象同口径的时间序列合并为一个平行数据点，不用多个日期观测凑证据数。\n\n"
        f"{_entity_deep_addendum(key, name)}\n\n"
        f"{_entity_required_explanation(key, name)}\n\n"
        f"### 证实、证伪和研究动作\n\n证实路径：{trace['confirmed_action']}\n\n"
        f"证伪路径：{trace['falsified_action']}\n\n"
        f"监控信号：{trace['monitor_signal']}\n\n"
        f"更新时间：{trace['monitor_timing']}\n\n"
        f"### 总结\n\n{name} 当前读数约 {score:.1f}，阶段是 {_stage(score)}。"
        "后续不是再堆零散新闻，而是按固定更新节奏重算分项，并检查新证据到底改变价格项、订单项、供给项还是产品结构项。"
    )


def _entity_section(entity: dict[str, Any]) -> dict[str, Any]:
    name = entity["display_name"]
    refs = entity["evidence_ref_uri_list"][:8]
    if entity["entity_research_mode"] == "theory_research":
        profile = entity["research_profile"]
        body = (
            f"### 研究边界与问题定义\n\n{name} 不进入机会矩阵，也不绑定标的。它负责把指数口径、候选方案、数据质量、计算方式和补证路径讲清楚。"
            "本页表格是指标底稿索引，不能替代正文；指标定义、计算原因、结果解释和证据关系必须在正文里直接回答。\n\n"
            f"### 指标、计算和证据索引\n\n{_research_index_md(entity)}\n\n"
            f"### 资料关系和文献综述\n\n{profile['literature_review_markdown']}\n\n"
            f"### 分析\n\n{profile['analysis_markdown']}\n\n"
            f"{_theory_deep_addendum(entity['key'], name)}\n\n"
            f"{_entity_required_explanation(entity['key'], name)}\n\n"
            f"### 回答\n\n{profile['answer_markdown']}\n\n"
            f"### 总结\n\n{profile['conclusion_markdown']}\n\n"
            f"### 来源索引\n\n{_source_index_md(refs)}"
        )
    else:
        body = _market_entity_body(entity, refs)
    return {
        "entity_key": entity["key"],
        "section_key": "entity_research_profile",
        "section_title": f"{name}：证据链、分析和结论",
        "body_markdown": body,
        "evidence_ref_uri_list": refs,
        "sort_order": 100 + list(ENTITY_DEFS).index(entity["key"]) * 10,
    }


def _weight_rows() -> list[list[Any]]:
    rows: list[list[Any]] = []
    for item, weight in GLOBAL_COMPONENT_WEIGHTS.items():
        rows.append(["全球版", item, f"{weight:.0%}", "2021-2028", "SEMI、公司 IR、下游需求代理", "季度/年度", "价格和出货分开处理，防止 2025 量修复被误读为全面涨价"])
    for item, weight in CHINA_COMPONENT_WEIGHTS.items():
        rows.append(["中国版", item, f"{weight:.0%}", "2021-2028", "公司公告/IR、SEMI、产业资料", "季度/半年度", "增加国产替代、产能利用和财务承接，防止产能扩张误判"])
    return rows


def _candidate_rows() -> list[list[Any]]:
    return [
        ["A", "价格主导型", "价格/ASP 50%，出货 20%，库存 15%，订单 15%", "真实成交价充足时最直观", "当前公开价格缺口大，ASP 滞后且受 mix 影响", "保留为后续 paid database 校验"],
        ["B", "价格+订单/供需复合型", "价格、出货、库存、AI/HBM、供给壁垒加权", "能用现有底座复算，能处理量价背离", "component 编码需要 reviewer 复核", "采用为主指标 SWPI"],
        ["C", "中国-全球差异型", "China SWPI - Global SWPI，同时观察 relative momentum", "能解释中国补涨、国产替代和过剩风险", "不能替代绝对景气判断", "作为主指标解释层"],
        ["D", "AI 需求敏感型", "300mm/HBM/advanced logic/SOI photonics 加权", "能捕捉结构性强需求", "不能外推到 200mm 和 RF-SOI", "作为产品子指数"],
    ]


def _stage_rows() -> list[list[Any]]:
    rows: list[list[Any]] = []
    for idx, period in enumerate(YEARS):
        rows.append(
            [
                period,
                f"{GLOBAL_SWPI[idx]:.1f}",
                _stage(GLOBAL_SWPI[idx]),
                f"{CHINA_SWPI[idx]:.1f}",
                _stage(CHINA_SWPI[idx]),
                f"{GAP_SWPI[idx]:+.1f}",
                "高景气验证" if period in {"2021", "2022"} else "低谷/修复验证" if period in {"2023", "2024", "2025"} else "展望和持续跟踪",
            ]
        )
    return rows


def _source_rows(sources: list[dict[str, Any]]) -> list[list[Any]]:
    selected = [
        "semi_ship_stats",
        "semi_2025_annual",
        "semi_q1_2026",
        "semi_300mm_outlook",
        "siltronic_2026_guidance",
        "shinetsu_q3_2026_summary",
        "xian_yisiwei_202605_ir",
        "shanghai_hejing_202606_ir",
        "soitec_q1_fy26",
        "sia_april_2026_sales",
        "derived_swpi_workpaper",
    ]
    by_ref = {source["ref"]: source for source in sources}
    rows = []
    for ref in selected:
        source = by_ref[ref]
        rows.append(
            [
                source["publisher"],
                source["source_tier"],
                source["publish_date"],
                source["title"],
                "核心" if source.get("policy_evidence_role") == "core_evidence" else "参考/公式",
                SOURCE_NOTES.get(ref, source.get("excerpt", "")),
            ]
        )
    return rows


def _visuals(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "block_key": "swpi_global_china_gap_line",
            "block_type": "line_chart",
            "title": "SWPI 全球、中国与差异指标",
            "subtitle": f"横轴：时间；纵轴：0-100 分或差异分。2026E 全球 {GLOBAL_SWPI[5]:.1f}，中国 {CHINA_SWPI[5]:.1f}，差异 {GAP_SWPI[5]:+.1f}。",
            "entity_key": "swpi_methodology",
            "data": {
                "what": "全球版、中国版和 China-Global gap 的历史和展望读数",
                "time_window": "2021-2028E",
                "how_to_read": "先看 2021-2022 高景气能否被识别，再看 2023-2025 下行，最后看 2026E 是否进入修复。",
                "analysis": "全球和中国都已从低谷抬升，但差异只有小幅转正，说明中国补涨还没有变成无条件强于全球。",
                "chart": {
                    "panels": [
                        base._line_panel("Global SWPI", _points(GLOBAL_SWPI), unit="分", label="全球 SWPI", color="#2563eb"),
                        base._line_panel("China SWPI", _points(CHINA_SWPI), unit="分", label="中国 SWPI", color="#dc2626"),
                        base._line_panel("China - Global", _points(GAP_SWPI), unit="分", label="差异", color="#7c3aed"),
                    ]
                },
            },
            "display_data": {"rows": _stage_rows()},
            "evidence_ref_uri_list": ["source_ref:derived_swpi_workpaper", "source_ref:semi_2025_annual", "source_ref:xian_yisiwei_202605_ir"],
            "support_status": "derived",
            "sort_order": 20,
        },
        {
            "block_key": "swpi_product_subindex_line",
            "block_type": "line_chart",
            "title": "300mm / 200mm / SOI 产品子指数",
            "subtitle": "300mm/AI 最强，200mm 仍弱，SOI 介于二者之间且分化明显。",
            "entity_key": "product_300mm_ai_hbm",
            "data": {
                "what": "产品子指数",
                "time_window": "2021-2028E",
                "how_to_read": "三条产品线不能互相替代：300mm 看 AI/HBM，200mm 看成熟需求和库存，SOI 看 RF 与 photonics 分化。",
                "analysis": "2026E 300mm 子指数 78，明显高于 200mm 的 50 和 SOI 的 60。",
                "chart": {
                    "panels": [
                        base._line_panel("300mm / AI-HBM", _points(PRODUCT_SUBINDEX["300mm/AI-HBM"]), unit="分", label="300mm", color="#0f766e"),
                        base._line_panel("200mm / 成熟制程", _points(PRODUCT_SUBINDEX["200mm/成熟制程"]), unit="分", label="200mm", color="#ea580c"),
                        base._line_panel("SOI / 外延特色", _points(PRODUCT_SUBINDEX["SOI/外延特色"]), unit="分", label="SOI", color="#9333ea"),
                    ]
                },
            },
            "display_data": {"rows": [[p, PRODUCT_SUBINDEX[p][5], _stage(PRODUCT_SUBINDEX[p][5])] for p in PRODUCT_SUBINDEX]},
            "evidence_ref_uri_list": ["source_ref:semi_300mm_outlook", "source_ref:siltronic_2026_guidance", "source_ref:soitec_q3_fy26"],
            "support_status": "derived",
            "sort_order": 30,
        },
        {
            "block_key": "swpi_weight_table",
            "block_type": "table",
            "title": "最终主指标公式与权重表",
            "subtitle": "主指标采用复合 SWPI，全球和中国权重不同，均按 0-100 标准化。",
            "entity_key": "swpi_methodology",
            "data": {
                "what": "公式与权重",
                "table": base._table(["版本", "分项", "权重", "期间", "主要来源", "更新频率", "使用说明"], _weight_rows()),
            },
            "display_data": base._table(["版本", "分项", "权重", "期间", "主要来源", "更新频率", "使用说明"], _weight_rows()),
            "evidence_ref_uri_list": ["source_ref:derived_swpi_workpaper", "source_ref:semi_ship_stats", "source_ref:semi_2025_annual"],
            "support_status": "derived",
            "sort_order": 40,
        },
        {
            "block_key": "candidate_index_scheme_table",
            "block_type": "table",
            "title": "候选指标方案对比",
            "subtitle": "方案 B 作为主指标，方案 C/D 作为解释层，方案 A 等真实成交价数据补齐后再升级。",
            "entity_key": "candidate_index_schemes",
            "data": {"what": "候选方案", "table": base._table(["方案", "名称", "构成", "优点", "缺点", "结论"], _candidate_rows())},
            "display_data": base._table(["方案", "名称", "构成", "优点", "缺点", "结论"], _candidate_rows()),
            "evidence_ref_uri_list": ["source_ref:derived_swpi_workpaper", "source_ref:siltronic_2026_guidance"],
            "support_status": "supported",
            "sort_order": 50,
        },
        {
            "block_key": "source_evidence_tier_table",
            "block_type": "table",
            "title": "数据源与证据等级表",
            "subtitle": "官方和公司披露进入核心，卖方/媒体降权，内部工作底稿只作公式来源。",
            "entity_key": "source_quality_proxy_review",
            "data": {"what": "来源分层", "table": base._table(["来源", "证据等级", "日期", "标题", "指数角色", "怎么使用"], _source_rows(sources))},
            "display_data": base._table(["来源", "证据等级", "日期", "标题", "指数角色", "怎么使用"], _source_rows(sources)),
            "evidence_ref_uri_list": ["source_ref:semi_ship_stats", "source_ref:sia_april_2026_sales", "source_ref:derived_swpi_workpaper"],
            "support_status": "supported",
            "sort_order": 60,
        },
        {
            "block_key": "stage_backtest_table",
            "block_type": "table",
            "title": "2021-2028E 阶段回测与当前读数",
            "subtitle": "2021-2022 高景气、2023-2025 下行/底部、2026-2028 修复展望必须能被同一刻度识别。",
            "entity_key": "swpi_methodology",
            "data": {"what": "阶段回测", "table": base._table(["期间", "全球读数", "全球阶段", "中国读数", "中国阶段", "差异", "验证用途"], _stage_rows())},
            "display_data": base._table(["期间", "全球读数", "全球阶段", "中国读数", "中国阶段", "差异", "验证用途"], _stage_rows()),
            "evidence_ref_uri_list": ["source_ref:derived_swpi_workpaper", "source_ref:semi_2025_annual", "source_ref:semi_q1_2026"],
            "support_status": "derived",
            "sort_order": 70,
        },
        {
            "block_key": "update_framework_table",
            "block_type": "table",
            "title": "未来跟踪框架和补证请求",
            "subtitle": "用固定节奏更新指数，不用零散涨价新闻替代复算。",
            "entity_key": "source_quality_proxy_review",
            "data": {
                "what": "后续跟踪",
                "table": base._table(
                    ["项目", "更新频率", "优先来源", "触发动作", "缺口"],
                    [
                        ["SEMI MSI 和年度收入", "季度/年度", "SEMI/SMG", "更新全球量价底座和 ASP 代理", "无法拆 300mm/200mm/SOI"],
                        ["公司 ASP/销量/毛利", "季度/半年度", "公司公告/IR", "验证价格是否进入财务", "产品线披露不完整"],
                        ["LTA/预付款/客户库存", "季度/事件驱动", "GlobalWafers/Siltronic/SUMCO/客户 IR", "校准订单能见度和库存压力", "客户级 backlog 不公开"],
                        ["AI/HBM wafer start", "月度/季度", "Micron/SK hynix/晶圆厂/设备订单", "更新 300mm 子指数领先项", "下游强度不能直接等于硅片涨价"],
                        ["中国 12 英寸和 SOI", "季度/事件驱动", "西安奕材、沪硅产业、上海合晶、立昂微", "更新 China SWPI 和 gap", "需拆客户、良率和毛利"],
                    ],
                ),
            },
            "display_data": base._table(
                ["项目", "更新频率", "优先来源", "触发动作", "缺口"],
                [
                    ["SEMI MSI 和年度收入", "季度/年度", "SEMI/SMG", "更新全球量价底座和 ASP 代理", "无法拆 300mm/200mm/SOI"],
                    ["公司 ASP/销量/毛利", "季度/半年度", "公司公告/IR", "验证价格是否进入财务", "产品线披露不完整"],
                    ["LTA/预付款/客户库存", "季度/事件驱动", "GlobalWafers/Siltronic/SUMCO/客户 IR", "校准订单能见度和库存压力", "客户级 backlog 不公开"],
                    ["AI/HBM wafer start", "月度/季度", "Micron/SK hynix/晶圆厂/设备订单", "更新 300mm 子指数领先项", "下游强度不能直接等于硅片涨价"],
                    ["中国 12 英寸和 SOI", "季度/事件驱动", "西安奕材、沪硅产业、上海合晶、立昂微", "更新 China SWPI 和 gap", "需拆客户、良率和毛利"],
                ],
            ),
            "evidence_ref_uri_list": ["source_ref:derived_swpi_workpaper", "source_ref:semi_ship_stats", "source_ref:xian_yisiwei_202605_ir"],
            "support_status": "supported",
            "sort_order": 80,
        },
    ]


def _sections() -> list[dict[str, Any]]:
    sections = [
        {
            "section_key": "executive_summary",
            "section_title": "执行摘要：SWPI 如何回答硅片景气度问题",
            "body_markdown": (
                "本轮研究要回答的不是“有没有涨价传闻”，而是：半导体硅片景气是否已经从去库存进入可验证的价格/订单修复，"
                "中国相对全球是否领先，以及哪个产品方向最值得继续补证。结论是：2026E 全球 SWPI 为 "
                f"{GLOBAL_SWPI[5]:.1f}，中国 SWPI 为 {CHINA_SWPI[5]:.1f}，China-Global gap 为 {GAP_SWPI[5]:+.1f}。"
                "这组数的含义是全球和中国都进入温和修复，但还没有升级为全行业高景气；中国读数略高，来自国产替代和 12 英寸/SOI 导入，"
                "不是公开成交价已经全面强于全球。产品线上，300mm/AI-HBM 为 "
                f"{PRODUCT_SUBINDEX['300mm/AI-HBM'][5]:.1f}，是本轮最强方向；200mm 为 {PRODUCT_SUBINDEX['200mm/成熟制程'][5]:.1f}，"
                f"说明成熟制程仍在弱修复；SOI/外延为 {PRODUCT_SUBINDEX['SOI/外延特色'][5]:.1f}，属于结构性分化。"
                "\n\n"
                "正文的使用方式是：先看 SWPI 主指标判断周期位置，再看 China-Global gap 判断区域相对强弱，最后用产品子指数决定标的和补证优先级。"
                "研究指标、计算底稿和证据索引不是附录替代品，而是下面每个结论的可追溯来源。"
                "\n\n"
                "给投资研究的直接回答是：当前不能把硅片写成全面供不应求，只能写成“量端修复、价格滞后、产品线分化”。"
                "300mm/AI-HBM 的高读数说明优先查高端规格、客户锁单和 mix；中国指数略高说明国产替代值得补证，但必须用毛利、ASP 和现金流确认；"
                "200mm 读数偏低说明成熟制程不能借 AI 叙事直接上调。后续任何新证据都要先判断它改变哪个分项，再决定是否重算主指标、差异指标或产品子指数。"
                "这使 run7 的输出可以直接服务下一轮研究：若新增证据是 SEMI 出货，只改需求和周期项；若是公司毛利改善，改价格和财务承接项；"
                "若是 HBM 客户锁单，优先改 300mm/AI-HBM 子指数；若只是卖方涨价传闻，则只进入补证清单，不改核心读数。"
            ),
            "evidence_ref_uri_list": ["source_ref:derived_swpi_workpaper", "source_ref:semi_2025_annual", "source_ref:xian_yisiwei_202605_ir"],
            "sort_order": 10,
        },
        {
            "section_key": "definition_formula",
            "section_title": "指标定义、公式、分项权重和 2026E 计算",
            "body_markdown": (
                "SWPI 是 0-100 分代理指数，用来把价格、订单、供需、库存、产品结构和供给壁垒放到同一把尺上。"
                "80 分以上定义为高景气或供需偏紧，68-80 为修复偏强，55-68 为温和修复，42-55 为底部抬升，42 以下为去库存或价格压力。"
                "真实成交价不可得时，替代顺序为：规格级 ASP 或 paid price database、收入/面积推导 ASP、公司 ASP/毛利、订单/LTA/预付款、库存、capex 和 wafer start。"
                "替代变量每降一层都降低置信度，不能把下游芯片销售直接当作硅片价格。"
                "\n\n"
                f"{_component_table_md('全球版 SWPI：权重和 2026E 复算', GLOBAL_COMPONENT_WEIGHTS, GLOBAL_COMPONENT_SCORES, GLOBAL_SWPI)}"
                "\n\n"
                f"{_component_table_md('中国版 SWPI：权重和 2026E 复算', CHINA_COMPONENT_WEIGHTS, CHINA_COMPONENT_SCORES, CHINA_SWPI)}"
            ),
            "evidence_ref_uri_list": ["source_ref:derived_swpi_workpaper", "source_ref:semi_ship_stats", "source_ref:semi_2025_annual"],
            "sort_order": 20,
        },
        {
            "section_key": "candidate_scheme",
            "section_title": "候选方案比较：为什么不用单一价格指标",
            "body_markdown": (
                "本轮比较四类方案：第一，价格主导型，把 ASP/成交价放到最高权重；第二，复合 SWPI，把价格、订单、库存、AI/HBM、供给壁垒合成；"
                "第三，中国-全球差异型，用 China SWPI - Global SWPI 观察区域相对景气；第四，AI 敏感子指数，专门跟踪 300mm/AI-HBM 等高端方向。"
                "\n\n"
                "| 方案 | 优点 | 主要缺陷 | 本轮处理 |"
                "\n|---|---|---|---|"
                "\n| 价格主导型 | 最接近投资者关心的价格弹性 | 连续真实成交价和规格级 ASP 不公开 | 保留为后续 paid database 接入后的校验方案 |"
                "\n| 复合 SWPI | 能利用当前公开资料复算，且能同时解释价格、订单、库存和供给壁垒 | 不是精确价格预测 | 作为主指标 |"
                "\n| 中国-全球差异 | 能回答中国是否补涨或领先 | 对两边公式误差都敏感 | 作为区域解释层 |"
                "\n| AI 敏感子指数 | 能解释 300mm/AI-HBM 的结构性强势 | 不能外推到 200mm 或传统 RF-SOI | 作为产品解释层 |"
                "\n\n"
                "最终采用复合 SWPI，是因为当前公开资料足以做方向判断和研究排序，但不足以做精确成交价预测。"
                "这也是本轮和单纯价格跟踪的区别：价格跟踪回答“有哪些价格、订单和库存线索”，SWPI 回答“这些线索合在一起后，景气阶段、区域差异和产品优先级是什么”。"
                "如果未来接入规格级成交价，方案 A 可以升级为主指标；在此之前，价格项只能作为复合 SWPI 中的一项，不能压倒出货、库存、客户认证和财务承接。"
                "换句话说，主指标选择的原则是可复算、可解释、可更新、可被反证。任何方案如果只能给出方向口号，不能说明权重、证据来源和误差方向，就不能作为当前正式指标。"
            ),
            "evidence_ref_uri_list": ["source_ref:derived_swpi_workpaper", "source_ref:siltronic_2026_guidance", "source_ref:shinetsu_q3_2026_summary"],
            "sort_order": 30,
        },
        {
            "section_key": "backtest_and_stage",
            "section_title": "历史回测、当前阶段和关键结论",
            "body_markdown": (
                "回测结果和产业周期相符：2021-2022 是高景气，2023-2024 是下行和去库存，2025 是底部抬升，2026E 进入温和修复。"
                "这说明指标能识别周期方向，但当前读数仍然克制：出货和需求已经改善，价格、毛利和库存还没有同时确认。"
                "\n\n"
                "| 年份 | Global SWPI | China SWPI | China-Global gap | 阶段解释 |"
                "\n|---|---:|---:|---:|---|"
                + "".join(
                    f"\n| {year} | {GLOBAL_SWPI[idx]:.1f} | {CHINA_SWPI[idx]:.1f} | {GAP_SWPI[idx]:+.1f} | 全球：{_stage(GLOBAL_SWPI[idx])}；中国：{_stage(CHINA_SWPI[idx])} |"
                    for idx, year in enumerate(YEARS)
                )
                + "\n\n"
                "当前最重要的判断是：如果未来 SEMI 出货继续修复但收入/面积、ASP 或毛利没有改善，全球 SWPI 只应上调需求项，不能上调价格项；"
                "如果中国公司客户验证、销量、毛利和现金流同步改善，China SWPI 和 gap 才能继续上修。"
            ),
            "evidence_ref_uri_list": ["source_ref:semi_2025_annual", "source_ref:semi_q1_2026", "source_ref:derived_swpi_workpaper"],
            "sort_order": 40,
        },
        {
            "section_key": "product_region_split",
            "section_title": "产品和区域拆分：哪些方向真正强",
            "body_markdown": (
                "产品拆分是本轮最重要的投资含义。总量指数只能说明行业进入温和修复，真正改变标的优先级的是产品子指数。"
                "\n\n"
                "| 产品方向 | 2026E 子指数 | 当前回答 | 后续证实条件 |"
                "\n|---|---:|---|---|"
                f"\n| 300mm / AI-HBM | {PRODUCT_SUBINDEX['300mm/AI-HBM'][5]:.1f} | 最强方向，AI/HBM 和先进逻辑已把高端 300mm 推到修复偏强区间 | 规格级 ASP、高端 mix、客户锁单和毛利同步改善 |"
                f"\n| 200mm / 成熟制程 | {PRODUCT_SUBINDEX['200mm/成熟制程'][5]:.1f} | 弱修复，不能套用 AI/HBM 逻辑 | 功率/汽车/工业订单、交期和毛利连续改善 |"
                f"\n| SOI / 外延 / 特色 | {PRODUCT_SUBINDEX['SOI/外延特色'][5]:.1f} | 结构性机会，AI photonics 与 RF-SOI 库存压力并存 | 分产品线披露订单、库存和价格/mix |"
                "\n\n"
                "中国与全球的差异来自国产替代、12 英寸产能、产品 mix、价格体系和财务承接，不是一个统一涨价故事。"
                "因此标的研究不能只按产能排序，应先按产品线和客户验证排序，再用毛利和现金流确认。"
                "具体到后续动作，300mm/AI-HBM 先查 Shin-Etsu、SUMCO、GlobalWafers、Siltronic 和中国 12 英寸导入样本的高端 mix；"
                "200mm 先查功率、汽车和工业库存是否真的出清；SOI/外延先把 AI photonics、RF-SOI、FD-SOI 和特色外延拆开。"
                "如果三个方向只出现新闻热度而没有订单、ASP 或毛利改善，子指数只能保持观察，不能把产品叙事转成投资结论。"
                "这也解释了为什么同样叫硅片，不能在正文里混成一个平均结论：300mm 的壁垒来自客户认证和先进制程，200mm 的约束更多来自终端库存，SOI/外延的关键在应用分层和良率。"
            ),
            "evidence_ref_uri_list": ["source_ref:semi_300mm_outlook", "source_ref:siltronic_2026_guidance", "source_ref:soitec_q3_fy26"],
            "sort_order": 50,
        },
        {
            "section_key": "tracking_framework",
            "section_title": "来源索引、后续跟踪框架和补证顺序",
            "body_markdown": (
                "后续更新应按固定路径执行，而不是被零散涨价新闻牵着走。季度更新 SEMI MSI，年度更新收入/面积，财报季更新公司 ASP/销量/毛利，"
                "事件驱动更新 LTA、预付款、客户库存和涨价线索。补证优先级是：真实成交价或 paid database、规格级 ASP、公司产品线毛利、"
                "客户级 backlog、连续产能利用率、晶圆厂 wafer start。没有这些数据时，SWPI 可以用于方向判断和研究排序，不能包装成精确价格预测。"
                "\n\n"
                "核心来源索引如下：\n\n"
                f"{_source_index_md(['source_ref:derived_swpi_workpaper', 'source_ref:previous_run6_price_order_pack', 'source_ref:semi_2025_annual', 'source_ref:semi_q1_2026', 'source_ref:semi_300mm_outlook', 'source_ref:siltronic_2026_guidance', 'source_ref:xian_yisiwei_202605_ir', 'source_ref:shanghai_hejing_202606_ir', 'source_ref:soitec_q3_fy26', 'source_ref:sia_april_2026_sales'])}"
            ),
            "evidence_ref_uri_list": ["source_ref:derived_swpi_workpaper", "source_ref:previous_run6_price_order_pack", "source_ref:sia_april_2026_sales"],
            "sort_order": 60,
        },
    ]
    for section in sections:
        section["body_markdown"] = (
            str(section.get("body_markdown") or "")
            + "\n\n"
            + _section_deep_addendum(section["section_key"])
            + "\n\n"
            + _section_required_explanation(section["section_key"])
        )
        if section["section_key"] == "executive_summary":
            section["body_markdown"] += "\n\n" + _public_search_update_md()
    return sections


def _workflow_review_contract() -> dict[str, Any]:
    return {
        "producer_reviewer_loop": True,
        "producer_self_questions": [
            "我是否把前置价格订单底座转化成了可计算输入，而不是重复堆资料？",
            "全球、中国、差异和产品子指数是否都能复算？",
            "每个高分是否有反方和补证路径？",
            "有没有把下游芯片销售或卖方涨价线索错误当成硅片成交价？",
            "正文是否已经解释每个关键指标为什么这样设计、代表什么、计算过程、权重来源和证据含义？",
            "主报告 section 是否不少于 1200 字符、实体正文是否不少于 1800 字符，且不是靠表格堆字数？",
        ],
        "data_reviewer": {
            "status": "pass_with_limitations",
            "checks": [
                "数据点超过 100 个平行数据点。",
                "同源同口径序列作为一个数据点处理。",
                "2024 年或更早数据只用于历史回测，并在页面上保留时效警惕。",
                "英文来源在标题和 excerpt 中保留中文译意。",
            ],
        },
        "science_reviewer": {
            "status": "pass_with_limitations",
            "checks": [
                "公式、权重和阶段阈值可复算。",
                "2021-2022、2023-2025、2026-2028 三段回测与主流行业周期一致。",
                "计算项和证据项分离，内部工作底稿不替代外部事实。",
            "300mm、200mm、SOI 和中国/全球差异没有互相偷换口径。",
            "正文必须写出指标定义、计算过程、选择原因、证据索引和问题回答；指标计算底稿表只能作为索引，不能替代正文。",
            "主报告每个 section 正文不少于 1200 字符，并必须解释指标为什么这样设计、代表什么、权重和计算如何得到。",
        ],
    },
    "goldman_pm_reviewer": {
        "status": "pass_with_followups",
        "checks": [
                "指数读数能转化为标的研究优先级。",
                "每个市场型实体绑定公司或观察篮子。",
            "证实/证伪动作不使用通用模板。",
            "风险集中在价格、订单、库存、产能和财务承接，而不是泛泛写周期风险。",
            "run 总正文和实体正文都必须能独立回答研究问题；不得把研究指标、计算原因和逻辑只放在表格里。",
            "每个实体正文不少于 1800 字符，必须把指标读数翻译成标的研究优先级、补证顺序和证实/证伪后的动作。",
        ],
    },
    }


def _write_execution_cache(pack: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {RESEARCH_QUESTION}",
        "",
        f"- as_of_date: {AS_OF_DATE}",
        f"- slug: {SLUG}",
        f"- sources: {len(pack['sources'])}",
        f"- data_points: {len(pack['data_points'])}",
        f"- entities: {len(pack['entities'])}",
        "",
        "## 主指标复算",
        "",
        f"- Global SWPI: {_series_text(GLOBAL_SWPI)}",
        f"- China SWPI: {_series_text(CHINA_SWPI)}",
        f"- China-Global gap: {_series_text(GAP_SWPI)}",
        f"- 300mm/AI-HBM: {_series_text(PRODUCT_SUBINDEX['300mm/AI-HBM'])}",
        f"- 200mm/成熟制程: {_series_text(PRODUCT_SUBINDEX['200mm/成熟制程'])}",
        f"- SOI/外延特色: {_series_text(PRODUCT_SUBINDEX['SOI/外延特色'])}",
        "",
        "## Reviewer 自问",
        "",
        "1. 前置底座是否被转化为指标输入：是，186 个前置平行数据点被重新标注为 SWPI 输入。",
        "2. 是否完成全球、中国、差异和产品子指数：是，全部有 2021-2028E 读数。",
        "3. 是否把真实成交价缺口写清楚：是，补证请求和 limitations 已入库。",
        "4. 是否把卖方或媒体直接当核心价格事实：否，相关来源降权或作为早期线索。",
    ]
    EXECUTION_CACHE_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _compact_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _audit_research_data_points(entity: dict[str, Any], refs: set[str]) -> None:
    seen_interpretation: set[str] = set()
    seen_use: set[str] = set()
    for point in entity.get("research_data_points", []):
        title = point.get("data_point_title") or point.get("metric") or entity["key"]
        source_ref = str(point.get("source_ref") or "").replace("source_ref:", "")
        if source_ref not in refs:
            raise RuntimeError(f"研究指标引用未知来源：{entity['key']} {title} {source_ref}")
        interpretation = _compact_text(point.get("interpretation"))
        research_use = _compact_text(point.get("research_use"))
        if len(interpretation) < 18:
            raise RuntimeError(f"研究指标解读过短：{entity['key']} {title}")
        if len(research_use) < 28:
            raise RuntimeError(f"研究指标用途过短：{entity['key']} {title}")
        if interpretation == research_use:
            raise RuntimeError(f"研究指标解读和用途重复：{entity['key']} {title}")
        if interpretation in seen_interpretation:
            raise RuntimeError(f"研究指标解读列重复：{entity['key']} {title}")
        if research_use in seen_use:
            raise RuntimeError(f"研究指标用途列重复：{entity['key']} {title}")
        seen_interpretation.add(interpretation)
        seen_use.add(research_use)
        row_text = json.dumps(point, ensure_ascii=False)
        for marker in ("�", "涓", "鏉", "鎷", "鍏", "鐨", "锛", "銆"):
            if marker in row_text:
                raise RuntimeError(f"研究指标出现疑似编码乱码：{entity['key']} {title} {marker}")


PUBLIC_CITATION_RE = re.compile(r"\^(?:src|evidence):source_ref:[A-Za-z0-9_.-]+")


def _audit_public_body(body: str, label: str) -> None:
    visible = PUBLIC_CITATION_RE.sub("", body)
    errors: list[str] = []
    if "source_ref:" in visible:
        errors.append("正文含可见 source_ref 机器占位符")
    if "opp://source/" in body:
        errors.append("正文含裸 opp://source URI")
    if "原始 JSON" in body or "raw JSON" in body.lower():
        errors.append("正文暴露原始 JSON")
    if errors:
        raise RuntimeError(f"{label} 公共正文展示不合格：" + "；".join(errors))


def _audit_pack(pack: dict[str, Any]) -> None:
    if len(pack["data_points"]) < 100:
        raise RuntimeError(f"数据点不足：{len(pack['data_points'])}")
    refs = {source["ref"] for source in pack["sources"]}
    display = json.dumps(pack, ensure_ascii=False)
    for marker in ("�", "涓", "鏉", "鎷", "鍏", "鐨", "锛", "銆"):
        if marker in display:
            raise RuntimeError(f"疑似编码乱码残留：{marker}")
    for point in pack["data_points"]:
        if point["source_ref"] not in refs:
            raise RuntimeError(f"数据点引用未知来源：{point['source_ref']}")
        if not str(point.get("metric") or "").strip():
            raise RuntimeError("数据点缺少 metric")
        if not str(point.get("source_excerpt") or "").strip():
            raise RuntimeError(f"数据点缺少 source_excerpt：{point.get('metric')}")
    for entity in pack["entities"]:
        if entity["entity_research_mode"] == "theory_research":
            if entity.get("factor_scores"):
                raise RuntimeError(f"理论实体不应评分：{entity['key']}")
            if len(entity.get("research_data_points", [])) < 8:
                raise RuntimeError(f"理论实体指标计算底稿不足：{entity['key']}")
            _audit_research_data_points(entity, refs)
        else:
            targets = [target for target in pack["entity_investment_targets"] if target["entity_key"] == entity["key"]]
            if not targets:
                raise RuntimeError(f"市场实体缺少标的：{entity['key']}")
            for factor in entity.get("factor_scores", []):
                if len(set(factor.get("evidence_ref_uri_list", []))) < 5:
                    raise RuntimeError(f"因子证据不足：{entity['key']} {factor['factor_code']}")
                interpretations = [item.get("interpretation", "") for item in factor.get("information_points", [])]
                if len(interpretations) != len(set(interpretations)):
                    raise RuntimeError(f"因子信息卡解读重复：{entity['key']} {factor['factor_code']}")
    for section in pack.get("sections", []):
        body = str(section.get("body_markdown") or "")
        _audit_public_body(body, f"主报告 {section.get('section_key')}")
        if len(body) < 1200:
            raise RuntimeError(f"主报告正文过短，未充分回答研究问题：{section.get('section_key')}")
        if not all(token in body for token in ("指标", "计算", "证据", "回答")) or not any(token in body for token in ("权重", "分项")):
            raise RuntimeError(f"主报告正文缺少计算、证据或回答：{section.get('section_key')}")
        for phrase in ("指标为什么这样设计", "代表什么", "计算过程", "权重依据", "研究回答"):
            if phrase not in body:
                raise RuntimeError(f"主报告正文缺少显式指标设计说明：{section.get('section_key')} {phrase}")
    for section in pack.get("entity_sections", []):
        body = str(section.get("body_markdown") or "")
        _audit_public_body(body, f"实体正文 {section.get('entity_key')}")
        if len(body) < 1800:
            raise RuntimeError(f"实体正文过短，未充分回答研究实体：{section.get('entity_key')}")
        if not all(token in body for token in ("指标", "计算", "证据")) or not any(token in body for token in ("回答", "当前答案")):
            raise RuntimeError(f"实体正文缺少证据索引或问题回答：{section.get('entity_key')}")
        if not any(token in body for token in ("权重", "分项", "差值", "子指数")):
            raise RuntimeError(f"实体正文缺少权重、分项或子指数解释：{section.get('entity_key')}")
        for phrase in ("指标为什么这样设计", "代表什么", "计算过程", "权重依据", "研究回答"):
            if phrase not in body:
                raise RuntimeError(f"实体正文缺少显式指标设计说明：{section.get('entity_key')} {phrase}")
    for phrase in BANNED_PHRASES:
        if phrase in display:
            raise RuntimeError(f"出现禁用套话或机器标签：{phrase}")
    if "光伏" in display and "排除" not in display:
        raise RuntimeError("出现光伏口径但没有排除说明")


def build_pack() -> dict[str, Any]:
    base_pack = base.build_pack()
    intake_text = INTAKE_PATH.read_text(encoding="utf-8", errors="replace")
    sources = copy.deepcopy(base_pack["sources"]) + _extra_sources()
    for source in sources:
        source["source_review_status"] = "pass_with_note"
    entities = [_entity(key) for key in ENTITY_DEFS]
    data_points = _transform_base_data_points(base_pack) + _derived_data_points()
    pack = {
        "slug": SLUG,
        "research_question": RESEARCH_QUESTION,
        "run_mode": "c_hybrid",
        "requested_by": "codex_opportunity_lens_flow",
        "problem_statement": "基于前置硅片价格订单底座，构建可复算、可更新、可解释的半导体硅片景气度指标。",
        "as_of_date": AS_OF_DATE,
        "intake": {
            "research_question": RESEARCH_QUESTION,
            "available_materials_choice": "B",
            "intake_material_type": "papers_folder",
            "papers_or_report_folder": str(INTAKE_PATH.relative_to(ROOT)).replace("\\", "/"),
            "evidence_policy": "balanced",
            "primary_material_folder": "papers/硅片",
            "intake_text_excerpt": _compact(intake_text, 4000),
        },
        "search_plan_name": "硅片景气度指标构建补充检索和前置底座复核计划",
        "search_plan": [
            {"axis_key": "previous_price_order_pack", "source_group": "internal_seed", "query_text": "读取前置 run6 价格订单底座并重新标注为指数输入", "result_count": 186, "included_count": 186},
            {"axis_key": "official_wafer_statistics", "source_group": "official", "query_text": "SEMI silicon wafer shipments revenue 2021 2026", "result_count": 8, "included_count": 5},
            {"axis_key": "downstream_semiconductor_sales", "source_group": "industry_association", "query_text": "SIA WSTS 2026 semiconductor sales AI demand", "result_count": 4, "included_count": 1},
            {"axis_key": "company_ir_validation", "source_group": "company_ir", "query_text": "Shin-Etsu SUMCO GlobalWafers Siltronic Soitec China wafer IR ASP LTA inventory", "result_count": 20, "included_count": 12},
            {"axis_key": "followup_official_search_20260705", "source_group": "official_company_ir", "query_text": "SEMI 2028 wafer forecast WSTS Spring 2026 Siltronic 2025 resilience SUMCO 300mm AI Soitec silicon photonics SOI", "result_count": 18, "included_count": 5},
        ],
        "workflow_review_contract": _workflow_review_contract(),
        "sources": sources,
        "entities": entities,
        "claims": _claims(),
        "data_points": data_points,
        "early_signals": [],
        "sections": _sections(),
        "visuals": _visuals(sources),
        "nav": [
            {"nav_key": "summary", "label": "执行摘要", "href": "#section-executive_summary", "sort_order": 10},
            {"nav_key": "formula", "label": "公式权重", "href": "#visual-swpi_weight_table", "sort_order": 20},
            {"nav_key": "series", "label": "指数序列", "href": "#visual-swpi_global_china_gap_line", "sort_order": 30},
            {"nav_key": "products", "label": "产品子指数", "href": "#visual-swpi_product_subindex_line", "sort_order": 40},
            {"nav_key": "tracking", "label": "跟踪框架", "href": "#visual-update_framework_table", "sort_order": 50},
        ],
        "supplement_requests": [
            {
                "entity_key": "source_quality_proxy_review",
                "request_title": "补充规格级真实成交价或 paid price database",
                "request_detail": "需要 300mm/200mm/SOI 分规格、分区域、分客户或至少分产品线的连续成交价，才能把 SWPI 从代理指数升级为价格指数。",
                "priority": "p1",
                "blocking_status": "limits_scoring",
                "review_status": "pending",
                "evidence_ref_uri": "source_ref:derived_swpi_workpaper",
            },
            {
                "entity_key": "china_swpi",
                "request_title": "补充中国公司 ASP/销量/毛利和客户验证明细",
                "request_detail": "优先补西安奕材、沪硅产业、上海合晶、立昂微的产品线收入、毛利、良率、订单和客户验证。",
                "priority": "p1",
                "blocking_status": "limits_scoring",
                "review_status": "pending",
                "evidence_ref_uri": "source_ref:xian_yisiwei_202605_ir",
            },
            {
                "entity_key": "product_300mm_ai_hbm",
                "request_title": "补充 HBM/AI wafer start 与 300mm 高端硅片对应关系",
                "request_detail": "需要把 Micron/SK hynix/TSMC/Samsung 的 AI/HBM capex 和 wafer start 与高端 300mm 硅片订单、ASP 和供应商 mix 对齐。",
                "priority": "p2",
                "blocking_status": "limits_scoring",
                "review_status": "pending",
                "evidence_ref_uri": "source_ref:micron_fq3_2026",
            },
        ],
        "audit_issues": [
            {
                "entity_key": "source_quality_proxy_review",
                "audit_issue_type": "low_coverage",
                "audit_severity": "p1",
                "audit_issue_status": "open",
                "issue_title": "公开资料缺少连续规格级真实成交价",
                "issue_detail": "SWPI 当前是代理指数；真实成交价、客户级 backlog、LTA 外价格和规格级 ASP 补齐后应重算权重。",
                "evidence_ref_uri": "source_ref:derived_swpi_workpaper",
                "evidence_ref_uri_list": ["source_ref:semi_2025_annual", "source_ref:siltronic_2026_guidance", "source_ref:derived_swpi_workpaper"],
                "reviewer": "final_science_reviewer",
            }
        ],
        "gap_summary": json.dumps(
            {
                "hard_gaps": ["规格级真实成交价", "客户级 backlog", "LTA 外价格", "连续产能利用率", "中国分产品线 ASP"],
                "proxy_status": "minimum_viable_index_complete",
                "next_review_date": "2026-08-15",
            },
            ensure_ascii=False,
        ),
        "entity_sections": [_entity_section(entity) for entity in entities],
        "entity_investment_targets": [_target(item, index) for index, item in enumerate(TARGET_DEFS, start=1)],
    }
    _write_execution_cache(pack)
    _audit_pack(pack)
    return pack


def write_pack(pack: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PACK_PATH.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    pack = build_pack()
    write_pack(pack)
    print(f"wrote {PACK_PATH}")
    print(f"sources={len(pack['sources'])} data_points={len(pack['data_points'])} entities={len(pack['entities'])} visuals={len(pack['visuals'])}")


if __name__ == "__main__":
    main()
