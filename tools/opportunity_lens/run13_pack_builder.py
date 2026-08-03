from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from tools.opportunity_lens.intake_parser import parse_markdown_intake_text
from tools.opportunity_lens.run13_source_catalog import SOURCES, build_claims, build_data_points
from tools.opportunity_lens.run_pack_builder import RunPackBuilder
from tools.opportunity_lens.run_pack_contract import validate_run_pack


ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "cache" / "research_runs" / "opportunity_lens_run13_byd_luxshare_20260722"
INTAKE_PATH = ROOT / "opportunity_lens" / "intake_requests" / "Opportunity_Lens_研究请求_比亚迪与立讯进军光模块竞争格局风险_深度版.md"
MODEL_PATH = RUN_DIR / "independent_model_v4.json"
RECONCILIATION_PATH = RUN_DIR / "external_reconciliation_v4.json"
OUTPUT_PATH = RUN_DIR / "run13_pack_stage.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ev(ref: str) -> str:
    return f"source_ref:{ref}"


SOURCE_BY_REF = {str(item["ref"]): item for item in SOURCES}

DYNAMIC_FINANCIAL_SOURCE_REFS = {
    "innolight_market_snapshot_202607",
    "eoptolink_market_snapshot_202607",
    "luxshare_market_snapshot_202607",
    "byd_market_snapshot_202607",
    "innolight_pb_history_202607",
    "eoptolink_pb_history_202607",
    "luxshare_pb_history_202607",
    "byd_pb_history_202607",
}


def _cite(ref: str) -> str:
    return f"^src:{_ev(ref)}"


COMPANY_LINKS = {
    "中际旭创": "/company/1",
    "新易盛": "/company/2",
    "立讯精密": "/company/14",
    "比亚迪": "/company/414",
}

COMPANY_MENTION_ALIASES = {
    "中际旭创": ("中际旭创", "中际"),
    "新易盛": ("新易盛",),
    "立讯精密": ("立讯精密", "立讯"),
    "比亚迪": ("比亚迪电子", "比亚迪股份", "比亚迪集团", "比亚迪"),
}


def _link_company_mentions(body: str) -> str:
    """Link each company's first mention in every prose paragraph.

    Markdown tables remain compact and target/company cards already carry their own
    navigation.  Headings are also left untouched so links appear where readers
    first encounter the company in the actual analysis.
    """
    blocks = re.split(r"(\n\s*\n)", body)
    linked: list[str] = []
    for block in blocks:
        stripped = block.lstrip()
        if (
            not stripped
            or stripped.startswith("#")
            or stripped.startswith("|")
            or stripped.startswith("```")
        ):
            linked.append(block)
            continue
        updated = block
        for name, route in COMPANY_LINKS.items():
            if f"]({route})" in updated:
                continue
            aliases = sorted(COMPANY_MENTION_ALIASES[name], key=len, reverse=True)
            pattern = re.compile("|".join(re.escape(alias) for alias in aliases))
            updated = pattern.sub(lambda match: f"[{match.group(0)}]({route})", updated, count=1)
        linked.append(updated)
    return "".join(linked)


def _factor(
    code: str,
    metric_name: str,
    unit: str,
    score: float,
    coverage: float,
    confidence: float,
    value_summary: str,
    rationale: str,
    topic_analysis: str,
    analysis_points: list[str],
    refs: list[str],
) -> dict[str, Any]:
    information_points: list[dict[str, Any]] = []
    for index, ref in enumerate(refs):
        source = SOURCE_BY_REF[ref]
        excerpt = str(source.get("excerpt_zh") or source.get("excerpt") or "")
        information_points.append(
            {
                "evidence_ref": _ev(ref),
                "excerpt": excerpt,
                "interpretation": f"第{index + 1}条证据由{source['publisher']}发布，直接约束“{metric_name}”：{excerpt}",
                "independence_key": source["independence_key"],
            }
        )
    return {
        "factor_code": code,
        "metric_name": metric_name,
        "unit": unit,
        "period": "截至2026-07-22，观察窗口为未来3—5年",
        "score_raw": score,
        "score_adjusted": score,
        "score_status": "complete",
        "coverage": coverage,
        "confidence": confidence,
        "score_rationale": rationale,
        "factor_value_summary": value_summary,
        "source_context_summary": "评分同时纳入公司原始披露、客户或供应商侧资料、标准与互操作记录、财务结果及明确反证；同源转载只计一次。",
        "factor_topic_analysis": topic_analysis,
        "theme_analysis_points": analysis_points,
        "evidence_ref_uri_list": [_ev(ref) for ref in refs],
        "information_points": information_points,
    }


def _target_point(
    metric_name: str,
    category: str,
    value_text: str,
    unit: str,
    ref: str,
    period: str,
    *,
    value_num: float | None = None,
) -> dict[str, Any]:
    source = SOURCE_BY_REF[ref]
    point: dict[str, Any] = {
        "metric_name": metric_name,
        "metric_category": category,
        "period": period,
        "value_text": value_text,
        "unit": unit,
        "source_title": source["title"],
        "source_publisher": source["publisher"],
        "source_excerpt": source["excerpt"],
        "evidence_ref_uri": _ev(ref),
    }
    if value_num is not None:
        point["value_num"] = value_num
    if str(source.get("language") or "").startswith("en"):
        point["source_title_zh"] = source["title_zh"]
        point["source_excerpt_zh"] = source["excerpt_zh"]
    return point


def _section(key: str, title: str, body: str, refs: list[str], order: int) -> dict[str, Any]:
    inline_refs = [ref for ref in SOURCE_BY_REF if _cite(ref) in body]
    resolved_refs = inline_refs or refs
    return {
        "section_key": key,
        "section_title": title,
        "title": title,
        "body_markdown": _link_company_mentions(body.strip()),
        "evidence_ref_uri_list": [_ev(ref) for ref in resolved_refs],
        "support_status": "supported",
        "review_status": "approved",
        "sort_order": order,
    }


def _entity_section(key: str, title: str, body: str, refs: list[str], order: int) -> dict[str, Any]:
    row = _section(f"{key}_deep_research", title, body, refs, order)
    row["entity_key"] = key
    return row


def _exclude_dynamic_financial_records(pack: dict[str, Any]) -> dict[str, Any]:
    """Keep live Wind/Tushare facts in financial.db, not the C-track database.

    Run13 may still contain frozen model conclusions that were calculated from an
    as-of snapshot, but it must not duplicate vendor rows as C-track sources,
    claims, target data points or evidence groups.
    """
    blocked_uris = {_ev(ref) for ref in DYNAMIC_FINANCIAL_SOURCE_REFS}
    citation_tokens = {
        _cite(ref) for ref in DYNAMIC_FINANCIAL_SOURCE_REFS
    }

    def clean(value: Any) -> Any:
        if isinstance(value, list):
            cleaned: list[Any] = []
            for item in value:
                if isinstance(item, dict):
                    ref = str(
                        item.get("ref")
                        or item.get("source_ref")
                        or item.get("evidence_ref")
                        or item.get("evidence_ref_uri")
                        or ""
                    )
                    if ref in DYNAMIC_FINANCIAL_SOURCE_REFS or ref in blocked_uris:
                        continue
                cleaned.append(clean(item))
            return cleaned
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                if key == "evidence_ref_uri_list" and isinstance(item, list):
                    result[key] = [
                        ref for ref in item if str(ref) not in blocked_uris
                    ]
                    continue
                if key == "evidence_groups" and isinstance(item, dict):
                    result[key] = {
                        ref: group for ref, group in item.items()
                        if str(ref) not in DYNAMIC_FINANCIAL_SOURCE_REFS
                    }
                    continue
                result[key] = clean(item)
            return result
        if isinstance(value, str):
            updated = value
            for token in citation_tokens:
                updated = updated.replace(token, "")
            return re.sub(r"[ \t]{2,}", " ", updated)
        return value

    cleaned = clean(pack)
    cleaned["financial_data_boundary"] = {
        "database": "financial.db",
        "policy": (
            "Wind、Tushare、yfinance的市场、估值、财务和一致预期记录只保存在"
            "financial.db；本研究包不复制供应商快照，只保留冻结模型与研究结论。"
        ),
        "excluded_source_refs": sorted(DYNAMIC_FINANCIAL_SOURCE_REFS),
    }
    return cleaned


def _search_plan() -> list[dict[str, Any]]:
    axes = {
        "entity_mapping": "比亚迪电子、比亚迪半导体、Luxshare-Tech的法律主体、业务归属与并表关系",
        "product_and_roadmap": "800G、1.6T、3.2T、硅光、LPO、LRO、DPO、CPO产品与路线图",
        "qualification_and_customers": "客户送样、互操作、正式认证、设计定点、批量订单和重复订单",
        "talent_and_patents": "招聘、公开人才、专利受让人、专利族、标准与会议参与",
        "capacity_and_yield": "工厂、设备、产线、良率、自动化、产能和规模交付准备",
        "upstream_constraints": "DSP、激光器、InP、硅光、耦合、测试设备和关键供应商约束",
        "demand_supply_and_asp": "2026—2031 AI光互联需求、供给、混合ASP、同代降价和CPO渗透",
        "incumbent_defense": "中际旭创、新易盛的产品、客户、产能、盈利、现金流与架构应对",
        "probability_and_cases": "相邻行业进入案例、里程碑基准率、反例和条件概率",
        "valuation_and_financials": "收入、毛利率、净利润、自由现金流、资本开支、估值和市场隐含预期",
    }
    plan: list[dict[str, Any]] = []
    for axis_key, topic in axes.items():
        plan.append(
            {
                "axis_key": axis_key,
                "source_channel": "report",
                "round": 1,
                "query": f"本地研报与正式研究资料：{topic}",
                "status": "completed",
            }
        )
        plan.append(
            {
                "axis_key": axis_key,
                "source_channel": "web",
                "round": 1,
                "query": f"公司、客户、供应商、监管、标准组织与专利原文：{topic}",
                "status": "completed",
            }
        )
    second_round = {
        "entity_mapping": "第一轮发现集团口径与上市主体口径可能混用，因此回查年报、公司历史和产品页。",
        "product_and_roadmap": "第一轮发现网络文章声称比亚迪具备800G/1.6T，故追溯专利受让人、展会官方回顾和最新产品页。",
        "qualification_and_customers": "第一轮发现产品展示与客户认证被混写，故反查客户支持清单、互操作报告和公司最新问答。",
        "talent_and_patents": "第一轮专利命中大量车载光通信及主体错配，故按受让人、权利要求和应用场景重新聚类。",
        "capacity_and_yield": "第一轮没有得到新进入者可核验的专线和良率，故从供应商采购、政府项目和财务代理反向搜索。",
        "upstream_constraints": "第一轮显示InP与激光器短缺可能推迟供给，故追踪设备订单、扩产节奏和平台合作。",
        "demand_supply_and_asp": "第一轮发现混合ASP上涨易被误读，故区分产品组合升级与同代产品自然降价。",
        "incumbent_defense": "第一轮只解释了进入压力，故补查龙头1.6T量产、产能扩张、XPO/CPO路线和现金流约束。",
        "probability_and_cases": "第一轮缺少同口径历史样本，故以里程碑完成度和反方约束构造宽区间，不伪装成统计频率。",
        "valuation_and_financials": "独立模型与市场聚合预测差距很大，故复核单位、季度节奏、终值占比和隐含利润路径。",
    }
    for axis_key, trigger in second_round.items():
        plan.append(
            {
                "axis_key": axis_key,
                "source_channel": "web",
                "round": 2,
                "query": f"针对第一轮缺口的原始来源、反证和替代解释补查：{axes[axis_key]}",
                "gap_trigger": trigger,
                "status": "completed",
            }
        )
    plan.extend(
        [
            {
                "axis_key": "upstream_constraints",
                "source_channel": "web",
                "round": 3,
                "query": "边际新增检索：2026年6—7月EML、CW激光器、InP和硅光产能扩张的最新原始或高质量公开资料",
                "gap_trigger": "新任务时效性高，二轮资料仍可能漏掉2026年6—7月新增产能披露。",
                "status": "completed",
                "result": "新增TrendForce 2026-06-03激光器产能预测；明确器件产能不能等同合格模块有效供给。",
            },
            {
                "axis_key": "qualification_and_customers",
                "source_channel": "web",
                "round": 3,
                "query": "边际新增检索：立讯2026年4—5月最新互动答复、原始IR记录及比亚迪7月传闻最早可见出处",
                "gap_trigger": "强反证定位和弱线索最早出处需要可点击复核，通用行情页不能满足引用合同。",
                "status": "completed",
                "result": "将立讯答复换成逐字镜像并降级；比亚迪传闻追到7月16日版本，7月18日转载合并为同一证据组。",
            },
        ]
    )
    return plan


def _entities() -> list[dict[str, Any]]:
    byd_refs = [
        "byde_ar_2025", "byd_ir_20260330", "byde_idce_2026", "byde_product_page",
        "byd_recruitment_2026", "byd_patent_vehicle_1", "byd_wrong_patent_800g",
        "wuhan_junheng_1p6t_patent", "byd_vehicle_cpo_patent", "byd_vehicle_optical_standard", "byd_vertilite_stake",
        "luxshare_ir_20260525", "ethernet_alliance_qualification", "fabrinet_qualification",
    ]
    lux_refs = [
        "luxshare_ar_2025", "luxshare_ir_20250428", "luxshare_ir_20260507", "luxshare_ir_20260525",
        "luxshare_interactive_20260428", "luxshare_ir_20250828", "luxshare_ir_20260420",
        "luxshare_ir_20251126", "keysight_luxshare_ofc2024", "oif_luxshare_2024", "poet_luxshare_2024",
        "poet_anonymous_order_boundary", "luxshare_us_optical_recruitment",
        "nvidia_connectx8_list", "xinqiang_supplier_ipo", "luxshare_patent_cpo",
    ]
    incumbent_refs = [
        "innolight_ar_2025", "innolight_q1_2026", "innolight_ir_20260424", "eoptolink_ar_2025",
        "eoptolink_q1_2026", "eoptolink_xpo_2026", "lightcounting_jan2026", "lightcounting_apr2026",
        "nvidia_cpo_202607", "nvidia_cpo_pluggable_coexist", "aaoi_1p6t_order",
        "accelink_ir_20260514", "ligent_hkex_20260305", "hgg_ir_2026q1",
        "broadcom_sian3_20250325", "marvell_ara_1p6t", "lumentum_eml_capacity_20260625",
    ]
    entities = [
        {
            "key": "byd_entry_risk",
            "canonical_name": "比亚迪电子高速光模块进入路径",
            "display_name": "比亚迪电子进入路径",
            "entity_type": "company",
            "taxonomy_level": "company",
            "description": "研究比亚迪集团内与AI数据中心高速光互联最相关的比亚迪电子，以及其从服务器、液冷、电源和高速互联向800G及以上光模块迁移的真实阶段。",
            "entity_research_mode": "market_linked",
            "score_point": 35,
            "score_band_low": 25,
            "score_band_high": 46,
            "coverage": 0.76,
            "confidence": 0.60,
            "evidence_ref_uri_list": [_ev(ref) for ref in byd_refs],
            "factor_scores": [
                _factor(
                    "company.exposure_directness", "AI高速光模块业务的直接证据", "分",
                    28, 0.78, 0.67,
                    "官方资料确认AI服务器、液冷、电源和高速互联，但未确认800G/1.6T产品、客户认证或批量收入。",
                    "28分反映业务邻近性较强、核心产品证据仍弱；若出现官方规格书和客户侧认证，分数应明显上修。",
                    "该因子区分集团级AI基础设施能力与高速光模块的直接能力，避免把服务器和电源收入误当成光模块收入。",
                    ["AI基础设施收入增长说明战略方向真实，但产品构成并不支持拆出光模块规模。", "展会官方清单和现有产品页未出现800G或1.6T，构成对网络传闻的直接约束。"],
                    ["byde_ar_2025", "byd_ir_20260330", "byde_idce_2026", "byde_product_page", "byd_wrong_patent_800g"],
                ),
                _factor(
                    "company.capacity_readiness_window", "客户认证与量产准备度", "分",
                    24, 0.70, 0.55,
                    "公开资料尚未形成“产品规格—互操作—客户验证—批量订单—重复交付”的连续链条。",
                    "24分对应仍处邻近能力或早期研发阶段；券商说法和招聘只提高补证优先级，不替代产线、良率和客户证据。",
                    "规模制造能力是比亚迪的优势，但高速光模块能否量产仍取决于光学耦合、测试、可靠性和客户资格。",
                    ["最新公司材料没有披露高速光模块专线、良率、客户验证或重复订单。", "行业资格流程通常需要实验室、现场、互操作与制造验证，电子制造规模不能跳过这些环节。"],
                    ["byde_ar_2025", "byde_idce_2026", "byd_recruitment_2026", "ethernet_alliance_qualification", "fabrinet_qualification"],
                ),
                _factor(
                    "supply.substitution_barrier", "跨越光学与客户壁垒的难度", "分",
                    34, 0.80, 0.70,
                    "比亚迪拥有制造、热管理和供应链基础，但数据中心光学设计、核心器件、互操作和多代客户协同尚无直接证明。",
                    "34分并非否定迁移可能，而是把车载光通信、高速连接和AI服务器能力降为邻近证据。",
                    "真正的替代壁垒来自良率、可靠性、固件、平台互操作、上游优先级和客户连续认证的组合。",
                    ["车载光通信专利证明相邻技术兴趣，不证明数据中心800G产品成熟。", "龙头已在1.6T和新架构上继续迭代，新进入者面对的是移动中的门槛。"],
                    ["byd_patent_vehicle_1", "gov_vehicle_optics_2026", "ethernet_alliance_qualification", "innolight_ir_20260424", "eoptolink_xpo_2026"],
                ),
                _factor(
                    "company.revenue_exposure_proxy", "光模块收入可验证程度", "分",
                    18, 0.68, 0.62,
                    "2025年AI基础设施收入为9.43亿元，但公司没有把其中任何金额归入高速光模块。",
                    "18分只承认AI基础设施业务已商业化，不把宽泛业务收入、券商预测或市场传闻转换成光模块收入。",
                    "该收入代理被服务器、液冷、电源和其他高速互联产品污染，因此只能作为投入能力和客户接近度的背景。",
                    ["公开财务提供了AI基础设施总额，却没有产品级光模块口径。", "二手报告对800G量产的判断尚未获得官方产品、客户或财务侧闭环。"],
                    ["byde_ar_2025", "byde_interim_2025", "byd_firstshanghai_202509", "byd_cmbi_202511", "byde_product_page"],
                ),
                _factor(
                    "demand.customer_capex_capacity_signal", "客户需求窗口", "分",
                    82, 0.90, 0.86,
                    "全球云厂商2026年资本开支继续显著扩张，为潜在进入者提供大市场和第二供应商窗口。",
                    "82分只衡量需求窗口，不等于比亚迪已获客户资格；强需求降低进入后的供给冲击，却不自动提高产品成熟度。",
                    "需求强度决定新进入者有无试单空间，但客户仍会按技术、可靠性、地缘政策和交付记录选择供应商。",
                    ["微软、Alphabet、Amazon和Meta均给出高额AI基础设施投入。", "阿里三年投入提供中国客户体系的本土需求锚，但不能外推全球CSP资格。"],
                    ["microsoft_fy26q3", "alphabet_2025q4", "amazon_2025q4", "meta_2026q1", "alibaba_ai_2025"],
                ),
                _factor(
                    "company.financial_capture_quality", "进入后的利润转化能力", "分",
                    38, 0.66, 0.50,
                    "比亚迪可能以制造规模和组合方案获得收入，但光学良率、返工、上游器件和客户账期可能侵蚀利润。",
                    "38分是对潜在制造协同的有限肯定；没有光模块收入、毛利率、良率和营运资本披露，不能据此推断高利润。",
                    "低利润容忍度可能提高入场率，却未必创造高资本回报；对行业的威胁可能先表现为报价压力而非其自身利润。",
                    ["公司整体规模和现金能力支持投入，但未分拆光模块经济性。", "行业客户资格和制造验证周期使收入兑现晚于产品或招聘信号。"],
                    ["byde_ar_2025", "byd_ir_20260330", "fabrinet_qualification", "sourcephotonics_asp_mix", "report_cicc_optics_202605"],
                ),
            ],
        },
        {
            "key": "luxshare_entry_risk",
            "canonical_name": "立讯精密高速光模块进入路径",
            "display_name": "立讯精密进入路径",
            "entity_type": "company",
            "taxonomy_level": "company",
            "description": "研究立讯精密及Luxshare-Tech在800G、1.6T、LRO、LPO、DPO、硅光和CPO相关产品上的研发、互操作、客户验证、量产与财务兑现。",
            "entity_research_mode": "market_linked",
            "score_point": 65,
            "score_band_low": 54,
            "score_band_high": 76,
            "coverage": 0.90,
            "confidence": 0.78,
            "evidence_ref_uri_list": [_ev(ref) for ref in lux_refs],
            "factor_scores": [
                _factor(
                    "company.exposure_directness", "高速光模块产品与业务直接性", "分",
                    78, 0.95, 0.88,
                    "年报、产品资料和投资者交流均直接覆盖800G、1.6T、DPO、LPO、LRO、AOC及硅光路线。",
                    "78分确认产品和业务直接性，但不把产品矩阵、小批量或互操作展示等同于全球头部客户规模份额。",
                    "与比亚迪不同，立讯的证据已经进入光模块产品本身；当前争议集中在规模、客户和盈利，而非是否涉足。",
                    ["2025年年报披露800G和1.6T小批量及部分客户验证。", "公司最新交流称业务刚起步，防止把早期产品成熟度夸大为显著市场份额。"],
                    ["luxshare_ar_2025", "luxshare_ir_20250428", "luxshare_ir_20260507", "luxshare_ir_20260525", "luxshare_product_matrix"],
                ),
                _factor(
                    "company.capacity_readiness_window", "量产、认证与重复订单准备度", "分",
                    62, 0.91, 0.78,
                    "已有800G量产表述、1.6T小批量和互操作展示，但客户数量、稳定产能、良率与重复订单仍未公开。",
                    "62分位于小批量向规模商业化过渡区；若出现客户侧资格名单和连续季度收入，分数才可进入高确定性区间。",
                    "供应商与OIF材料验证了技术和互操作接近度，最新公司表述则限制了对商业规模的外推。",
                    ["跨厂商演示和供应商合作证明产品可以进入生态测试。", "NVIDIA特定平台支持清单未显示立讯800G，仅能约束该版本和该平台，不能证明全面未认证。"],
                    ["keysight_luxshare_ofc2024", "oif_luxshare_2024", "poet_luxshare_2024", "nvidia_connectx8_list", "luxshare_ir_20260525"],
                ),
                _factor(
                    "supply.substitution_barrier", "突破核心器件和平台壁垒的能力", "分",
                    58, 0.88, 0.76,
                    "立讯具备连接器、线缆、精密制造和系统协同优势，但公开资料显示核心DSP等器件仍依赖外部平台。",
                    "58分反映封装与自动化能力可以迁移，核心芯片所有权、客户联合开发和多代量产经验仍落后于龙头。",
                    "后端模块制造、光学对准与测试能够形成成本优势，却不能单独替代高速光学设计、核心器件供应和客户认证。",
                    ["公司明确与Broadcom、Marvell等合作，说明生态接入同时也意味着关键器件依赖。", "专利与政府项目支持封装能力，但不支持自研1.6T硅光芯片的结论。"],
                    ["luxshare_ir_20251126", "luxshare_ir_20260525", "luxshare_siph_gov_project", "luxshare_patent_cpo", "luxshare_patent_sipho"],
                ),
                _factor(
                    "company.revenue_exposure_proxy", "光模块收入规模可见度", "分",
                    42, 0.82, 0.70,
                    "公司确认光模块业务刚开始且相对总体规模很小，没有披露独立收入、出货量或毛利率。",
                    "42分高于纯研发阶段，但低于可从财报验证份额的成熟业务；卖方给出的未来收入和利润贡献只用于对账。",
                    "立讯集团规模很大，光模块增量即使快速增长也可能暂时被消费电子和通信业务总盘子稀释。",
                    ["最新公司交流没有确认投资者提问中的具体收入数字。", "供应商PCB采购证明产品活动，但无法把终端客户和收入完整映射到上市公司。"],
                    ["luxshare_ir_20260507", "luxshare_ir_20260525", "xinqiang_supplier_ipo", "report_hsbc_luxshare_202605", "report_jpm_luxshare_202606"],
                ),
                _factor(
                    "demand.customer_capex_capacity_signal", "全球与中国客户需求窗口", "分",
                    86, 0.94, 0.90,
                    "云厂商资本开支与1.6T端口需求同步增长，给具备产品和系统客户关系的立讯更现实的切入窗口。",
                    "86分衡量市场拉动，不表示立讯已进入具体CSP；所有模糊的国际客户表述都保持匿名。",
                    "强需求有利于客户引入第二供应商并容纳新增供给，但上游短缺和资格认证会决定真正可售规模。",
                    ["四家美国云厂商继续提高AI基础设施投入。", "LightCounting预计800G继续翻倍、1.6T进入数千万端口量级，需求斜率高。"],
                    ["microsoft_fy26q3", "alphabet_2025q4", "amazon_2025q4", "meta_2026q1", "lightcounting_feb2026"],
                ),
                _factor(
                    "company.financial_capture_quality", "制造协同转化为利润的质量", "分",
                    55, 0.76, 0.62,
                    "立讯有自动化、供应链和组合销售潜力，但早期业务的良率、报价、返工、营运资本和毛利率均未单列。",
                    "55分代表可能以规模和成本形成竞争力，却无法确认能达到现有龙头的高毛利和高现金回报。",
                    "对龙头最现实的冲击可能先是客户议价与第二供应商份额，而不是立讯立即复制龙头利润率。",
                    ["公司最新材料承认商业化规模仍需时间。", "行业供给紧张与混合ASP上升可能掩盖新进入者的低价压力，必须分开分析。"],
                    ["luxshare_ir_20260525", "luxshare_ir_20251126", "lightcounting_apr2026", "sourcephotonics_asp_mix", "report_cicc_optics_202605"],
                ),
            ],
        },
        {
            "key": "incumbent_profitability_risk",
            "canonical_name": "中际旭创与新易盛长期盈利风险",
            "display_name": "龙头长期盈利风险",
            "entity_type": "company",
            "taxonomy_level": "company",
            "description": "研究中际旭创和新易盛在需求高增长、新进入者扩张、上游供给变化与CPO架构迁移共同作用下的收入、利润、现金流和估值风险。",
            "entity_research_mode": "market_linked",
            "score_point": 63,
            "score_band_low": 52,
            "score_band_high": 74,
            "coverage": 0.93,
            "confidence": 0.82,
            "evidence_ref_uri_list": [_ev(ref) for ref in incumbent_refs],
            "factor_scores": [
                _factor(
                    "company.exposure_directness", "高速光模块盈利暴露", "分",
                    94, 0.98, 0.96,
                    "两家公司收入和利润高度直接暴露于800G、1.6T及更高速AI数据中心光互联。",
                    "94分表示竞争和架构变化会直接影响其经营结果，不表示风险必然发生。",
                    "高暴露带来需求上行弹性，也使客户份额、ASP、毛利率与产品路线变化快速传导至估值。",
                    ["2025年收入、产能和光模块毛利率均显示业务高度集中。", "2026年第一季度收入和利润继续快速增长，当前盈利基数处于高位。"],
                    ["innolight_ar_2025", "innolight_q1_2026", "innolight_ir_20260424", "eoptolink_ar_2025", "eoptolink_q1_2026"],
                ),
                _factor(
                    "company.financial_capture_quality", "高增长转化为现金流的质量", "分",
                    74, 0.95, 0.87,
                    "2025年现金流强，但2026年第一季度扩产和营运资本占用已使利润与现金流分化。",
                    "74分反映龙头当前盈利能力强，同时对产能扩张、库存、预付款和客户账期保持折扣。",
                    "竞争压力若与扩产高峰重叠，会通过应收、库存、资本开支和利用率放大，而不只体现在毛利率。",
                    ["中际旭创2025年经营现金流接近净利润，2026年一季度仍需观察扩产后的现金转换。", "新易盛2026年一季度经营现金流明显低于净利润，预付款和在建工程增加。"],
                    ["innolight_ar_2025", "innolight_q1_2026", "eoptolink_ar_2025", "eoptolink_q1_2026", "sourcephotonics_asp_mix"],
                ),
                _factor(
                    "supply.substitution_barrier", "龙头客户与技术防御力", "分",
                    82, 0.94, 0.90,
                    "龙头拥有多代产品、客户协同、自动化量产和1.6T爬坡记录，并开始布局XPO、NPO和CPO。",
                    "82分说明新进入者需要跨越移动中的门槛；该分数不会消除客户主动引入第二供应商的动机。",
                    "技术迭代提高认证难度，却也可能让平台和核心器件掌握更大价值，因此防御力需要按架构层级观察。",
                    ["中际旭创确认1.6T逐步放量且订单充足。", "新易盛发布多种下一代架构，表明其并非静态防守。"],
                    ["innolight_ir_20260424", "eoptolink_xpo_2026", "ethernet_alliance_qualification", "nvidia_cpo_pluggable_coexist", "fabrinet_qualification"],
                ),
                _factor(
                    "demand.customer_capex_capacity_signal", "AI光互联需求强度", "分",
                    91, 0.96, 0.92,
                    "AI光学市场和800G/1.6T端口继续高速扩张，短期需求增长可能吸收部分新增供应。",
                    "91分解释为什么新进入者增加不等于龙头收入立即下降；但估值已反映较高增长预期。",
                    "需求斜率、网络光强度和产品代际是龙头抵消份额下降的第一道缓冲。",
                    ["行业机构预计2026年AI集群光学市场约260亿美元。", "云厂商资本开支和端口升级共同支撑需求，但不能机械映射为单一供应商收入。"],
                    ["lightcounting_jan2026", "lightcounting_feb2026", "microsoft_fy26q3", "alphabet_2025q4", "amazon_2025q4"],
                ),
                _factor(
                    "supply.capacity_event_12m", "未来一年供给扩张与瓶颈变化", "分",
                    68, 0.92, 0.84,
                    "InP、激光器和高端器件仍紧，但设备订单和六英寸平台扩产指向2026年末至2027年供给逐步缓解。",
                    "68分表示短期紧缺支撑盈利、随后供给释放提高竞争强度；两段逻辑不能混成单一方向。",
                    "当上游瓶颈缓解、新进入者资格完成、龙头扩产同时兑现时，价格和利用率风险才会显著上升。",
                    ["LightCounting估计需求一度超过InP和激光器供给约30%。", "Veeco、AIXTRON与器件厂扩产订单显示供给响应正在形成。"],
                    ["lightcounting_apr2026", "coherent_capacity_2026", "veeco_inp_orders_2026", "aixtron_lumentum_2026", "nvidia_coherent_2026"],
                ),
                _factor(
                    "signal.material_price_momentum", "正常降价与额外竞争压价", "分",
                    58, 0.80, 0.68,
                    "产品组合升级可使混合ASP上升，即便同代模块价格下降；目前缺少同规格、同客户、同距离的公开价格序列。",
                    "58分代表价格压力值得监控但尚不能从混合ASP直接归因；新增竞争造成的额外降价需由同代报价或毛利差验证。",
                    "若只看混合ASP，会把1.6T占比上升误认成定价权增强，也可能遗漏同一代产品的降价。",
                    ["索尔思披露的混合ASP上升主要受高速产品占比推动。", "行业需求紧张和供应缓解会在不同阶段改变同代价格压力。"],
                    ["sourcephotonics_asp_mix", "lightcounting_apr2026", "aaoi_1p6t_order", "foxconn_q1_2026", "jabil_1p6t_2025"],
                ),
            ],
        },
    ]
    expanded: list[dict[str, Any]] = []
    for entity in entities:
        if entity["key"] != "incumbent_profitability_risk":
            expanded.append(entity)
            continue
        innolight = copy.deepcopy(entity)
        innolight.update(
            {
                "key": "innolight_profitability_risk",
                "canonical_name": "中际旭创长期盈利与估值风险",
                "display_name": "中际旭创长期盈利风险",
                "description": "研究中际旭创在新增供应商、同代降价、上游供给释放与架构迁移下的收入、利润、现金流、ROE、ROA和估值风险。",
                "score_point": 61,
                "score_band_low": 50,
                "score_band_high": 72,
            }
        )
        eoptolink = copy.deepcopy(entity)
        eoptolink.update(
            {
                "key": "eoptolink_profitability_risk",
                "canonical_name": "新易盛长期盈利与估值风险",
                "display_name": "新易盛长期盈利风险",
                "description": "研究新易盛在新增供应商、同代降价、扩产现金占用与架构迁移下的收入、利润、现金流、ROE、ROA和估值风险。",
                "score_point": 65,
                "score_band_low": 54,
                "score_band_high": 76,
            }
        )
        for factor in eoptolink["factor_scores"]:
            if factor["factor_code"] == "company.financial_capture_quality":
                factor["score_raw"] = 68
                factor["score_adjusted"] = 68
                factor["score_rationale"] = "68分反映利润率很强，但扩产期现金转换和营运资金对竞争冲击更敏感。"
        expanded.extend([innolight, eoptolink])
    return expanded


def _targets() -> list[dict[str, Any]]:
    targets = [
        {
            "entity_key": "byd_entry_risk",
            "target_name": "比亚迪",
            "ticker": "002594.SZ",
            "market": "SZ",
            "target_type": "security",
            "exposure_rationale": "比亚迪电子更可能是光模块经营承载主体，比亚迪股份是本研究要求的集团上市公司观察标的；收入可以合并，但归母利润必须扣除非全资子公司少数股东归属。",
            "evidence_ref_uri": _ev("byde_ar_2025"),
            "research_action": "将其作为高优先级验证标的，重点等待官方产品规格、客户资格、专线与收入拆分，而不是根据传闻提前确认。",
            "investment_view": "当前光模块更像比亚迪集团的远期期权，而不是比亚迪股份2026—2028年盈利的主要驱动；即使项目成功，集团体量和非全资归属也会显著稀释归母影响。",
            "risk_note": "服务器、电源和高速连接的宽口径披露极易被误映射为800G/1.6T光模块，导致收入和概率高估。",
            "target_priority": "高：信息变化可能显著改变行业竞争概率",
            "target_quality_label": "产品与客户链条尚待官方闭环",
            "relative_preference": "相对立讯，进入证据更早、更弱，但制造规模和组合销售使尾部风险不能忽略。",
            "confirmed_scenario_action": "若出现客户侧认证、连续批量订单和分拆收入，显著上调全球进入概率并重跑龙头价格与份额情景。",
            "falsified_scenario_action": "若未来两轮财报和展会仍只有服务器、电源、液冷及普通高速连接，继续下调光模块进入概率。",
            "target_profile_markdown": f"比亚迪股份提供资金、制造和客户协同，比亚迪电子更可能承载服务器、液冷、电源和高速互联业务。{_cite('byde_ar_2025')} {_cite('byde_product_page')} 研究同时区分集团合并收入、子公司项目利润和比亚迪股份归母利润。",
            "target_deep_research_markdown": f"2025年比亚迪股份收入8039.65亿元、归母净利润326.19亿元；2026年7月22日市值8348.62亿元、PE TTM 30.31倍、PB 3.60倍。{_cite('byd_market_snapshot_202607')} 独立模型显示，即使2031年光模块收入达到300—500亿元，比亚迪股份归母净利润增量约14—16亿元，仅相当于集团独立基线的约2%；扩产和营运资金使项目自由现金流在快速扩张期仍可能为负。光模块可以增强AI基础设施组合方案，却不足以单独重估整个汽车、电池与电子集团。",
            "entity_relation_markdown": "该标的是集团财务和估值观察主体；光模块技术成熟度仍按比亚迪电子经营证据判断，不能把汽车光通信或比亚迪半导体能力直接并入数据中心光模块。",
            "parent_research_relation_markdown": "其客户认证与量产是否成立，决定联合情景中比亚迪一侧的3年和5年概率，也决定价格压力是否从中国客户扩散至全球头部客户。",
            "conditional_investment_recommendation": "不以光模块传闻作为当前盈利预测；把正式规格、客户资格、专线和收入拆分设为四个必须触发条件。",
            "financial_data_status": "比亚迪股份集团财务、估值和FY1—FY3一致预期可得；比亚迪电子高速光模块收入、利润率、出货、良率、资本开支与归母桥不可分拆。",
            "link_status": "linked",
            "support_status": "partially_supported",
            "sort_order": 10,
            "target_data_points": [
                _target_point("AI基础设施收入", "经营", "9.43亿元，同比增长31.7%", "亿元人民币", "byde_ar_2025", "2025年", value_num=9.43),
                _target_point("集团估值与资本回报", "估值", "市值8348.62亿元，PE TTM 30.31倍，PB 3.60倍，ROE TTM 11.02%，ROA TTM 3.71%", "亿元人民币/倍/%", "byd_market_snapshot_202607", "截至2026-07-22", value_num=8348.62),
                _target_point("数据中心公开产品范围", "产品", "服务器、液冷、电源和高速互联，未列800G/1.6T光模块", "事实", "byde_product_page", "截至2026-07-22"),
                _target_point("2026年IDCE展品", "产品", "AI服务器、液冷和800V直流电源，没有官方光模块展品", "事实", "byde_idce_2026", "2026年"),
                _target_point("光通信招聘线索", "组织", "校园招聘出现光通信与光芯片光器件方向，但缺少专属团队和产品映射", "事实", "byd_recruitment_2026", "2026届"),
                _target_point("800G专利受让人核验", "专利", "网络传播的CN113514924A申请人为苏州卓昱与亨通，不属于比亚迪", "事实", "byd_wrong_patent_800g", "截至2026-07-22"),
            ],
        },
        {
            "entity_key": "luxshare_entry_risk",
            "target_name": "立讯精密",
            "ticker": "002475.SZ",
            "market": "SZ",
            "target_type": "security",
            "exposure_rationale": "立讯精密通过Luxshare-Tech已直接披露800G、1.6T和多种低功耗路线，是两家候选中最接近真实商业化的一家。",
            "evidence_ref_uri": _ev("luxshare_ar_2025"),
            "research_action": "跟踪小批量向连续季度收入、多个客户与下一代产品延续的转换，尤其核验海外平台资格和实际产线效率。",
            "investment_view": "产品和互操作证据较强，但公司最新表述仍将自身定义为新进入者，规模与利润兑现尚未达到可从财报验证的阶段。",
            "risk_note": "卖方模型可能把小批量、部分客户验证和供应商合作过早外推为全球CSP份额及高利润率。",
            "target_priority": "最高：未来12个月最可能出现可验证进展",
            "target_quality_label": "产品明确、规模和客户仍需核验",
            "relative_preference": "相对比亚迪，立讯的3年进入概率明显更高；相对现有龙头，其多代量产、客户资格和光学经验仍有差距。",
            "confirmed_scenario_action": "若客户侧名单、批量订单与收入拆分同时出现，转入全球第二供应商情景并评估龙头议价与毛利率。",
            "falsified_scenario_action": "若2027年前仍停留在小批量且没有重复订单或下一代验证，将概率收敛到中国局部供应情景。",
            "target_profile_markdown": f"立讯的优势来自连接器、线缆、精密制造、自动化和系统级客户关系。{_cite('luxshare_ar_2025')} 高速光模块的公开证据已经超过概念阶段，但商业规模小，关键芯片仍依赖生态伙伴，且公司没有披露客户数量、稳定产能、良率和独立毛利率。{_cite('luxshare_ir_20251126')} {_cite('luxshare_ir_20260525')}",
            "target_deep_research_markdown": f"2024年年报曾称800G通过AI客户测试并向国际客户批量交付；2025年8月公司进一步限定，800G/1.6T主要交付中小型数据中心，尚未获得头部客户明确商务机会。{_cite('luxshare_ar_2024')} {_cite('luxshare_ir_20250828')} 2025年报仍把相关产品描述为小批量或部分验证，2026年4月又披露2025年光模块收入约占0.1%、北美头部云客户仍在早期接洽，并否认1000万只订单。{_cite('luxshare_ar_2025')} {_cite('luxshare_interactive_20260428')} OIF、Keysight、POET和PCB供应商证明产品与工程活动真实，但不能替代头部客户资格和复购。{_cite('oif_luxshare_2024')} {_cite('keysight_luxshare_ofc2024')} {_cite('poet_luxshare_2024')} {_cite('xinqiang_supplier_ipo')}",
            "entity_relation_markdown": "该标的是“立讯精密进入路径”的上市公司载体，Luxshare-Tech产品活动应在合并报表层面观察，但产品网站和展会名称不能单独证明上市公司收入。",
            "parent_research_relation_markdown": "立讯的商业化节奏是未来3年联合进入概率的主变量；比亚迪更影响5年尾部风险，二者不能等权处理。",
            "conditional_investment_recommendation": "在客户与财务证据形成前，不直接使用卖方远期光模块利润；优先验证客户、数量、产品代际和重复订单。",
            "financial_data_status": "上市公司财务完整，光模块分部收入、利润、出货、良率和客户集中度没有单独披露。",
            "link_status": "linked",
            "support_status": "supported",
            "sort_order": 20,
            "target_data_points": [
                _target_point("800G与1.6T商业阶段", "产品", "800G和1.6T处于小批量，800G LRO有部分客户验证", "事实", "luxshare_ar_2025", "2025年"),
                _target_point("中小客户与头部客户边界", "客户", "800G/1.6T主要向中小型数据中心交付，尚未获得头部客户明确商务机会", "事实", "luxshare_ir_20250828", "2025-08-28"),
                _target_point("光模块收入与北美客户阶段", "经营", "2025年收入约占0.1%，北美头部云客户仍早期接洽，1000万只订单为不实消息", "事实", "luxshare_interactive_20260428", "2026-04-28"),
                _target_point("客户数量与规模化边界", "客户", "未披露具体CSP数量，并称自身是新进入者、规模化仍需时间", "事实", "luxshare_ir_20260525", "2026-05-25"),
                _target_point("800G互操作证明", "认证", "OFC多厂商互操作演示可核验，但不等于正式客户资格", "事实", "keysight_luxshare_ofc2024", "2024年"),
                _target_point("核心器件路线", "供应链", "与Broadcom、Marvell等合作，立讯主要承担模块制造、光学对准和测试", "事实", "luxshare_ir_20251126", "2025-11-26"),
            ],
        },
        {
            "entity_key": "innolight_profitability_risk",
            "target_name": "中际旭创",
            "ticker": "300308.SZ",
            "market": "SZ",
            "target_type": "security",
            "exposure_rationale": "中际旭创是AI高速光模块头部公司，新进入者、客户多源化与CPO架构变化会直接影响其份额、毛利率、现金流和终值。",
            "evidence_ref_uri": _ev("innolight_ar_2025"),
            "research_action": "同时跟踪1.6T放量、产能利用、同代ASP、客户份额、毛利率和自由现金流，不把单一竞争者新闻当作完整风险信号。",
            "investment_view": "经营基本面仍强，真正风险是需求减速、供给释放和第二供应商扩张在高估值阶段同时发生。",
            "risk_note": "当前市场价格要求远高于独立保守基线的利润和现金流路径，任何长期份额或利润率下修都会被估值放大。",
            "target_priority": "高：组合中的主要风险暴露",
            "target_quality_label": "经营证据强、估值隐含要求高",
            "relative_preference": "相对新易盛，规模更大、现金流基数更强；但当前绝对市值对长期增长兑现的要求同样很高。",
            "confirmed_scenario_action": "若立讯或比亚迪出现全球客户重复订单且公司同代ASP和毛利率同步低于正常路径，采用明显竞争恶化情景。",
            "falsified_scenario_action": "若龙头份额稳定、1.6T放量、毛利率和现金转换保持，同时新进入者长期停留小批量，则下调竞争损害概率。",
            "target_profile_markdown": f"2025年中际旭创实现收入382.40亿元、归母净利润107.97亿元、经营现金流108.96亿元，光模块业务毛利率42.61%；2026年一季度继续高增长。{_cite('innolight_ar_2025')} {_cite('innolight_q1_2026')} 其优势在于多代产品、头部客户、自动化量产和供货稳定性。",
            "target_deep_research_markdown": f"独立模型从2026年800亿元收入、236亿元归母净利润起步，随后让增速和利润率逐年回落。{_cite('innolight_ar_2025')} {_cite('innolight_q1_2026')} 11%回报要求和3%长期增长下的零净举债现金流敏感值约3231亿元，明显低于2026年7月约11830亿元市值；由于缺完整净现金、净举债和少数股东桥，它只用于市场隐含要求诊断，不是目标价。{_cite('innolight_market_snapshot_202607')} 新进入者若限于中国客户，2031年归母净利润约下降8%；若至少一家成为全球重要第二供应商，约下降25%；两家同时全球突破并压价时约下降44%。",
            "entity_relation_markdown": "该标的是“龙头长期盈利风险”的核心上市公司，风险通过收入份额、毛利率、营运资本、资本开支和终值逐层传导。",
            "parent_research_relation_markdown": "其财务模型用于回答进入风险是否足以抵消近年高增长，而不是机械生成交易指令。",
            "conditional_investment_recommendation": "将估值判断与证据触发绑定；未出现全球客户、重复订单和同代价格压力前，不把极端竞争情景当作基准。",
            "financial_data_status": "2025年和2026年一季度财务及当前市场数据可得；按速率、客户和地区拆分的销量、ASP与份额不可得。",
            "link_status": "linked",
            "support_status": "supported",
            "sort_order": 30,
            "target_data_points": [
                _target_point("营业收入", "财务", "382.40亿元", "亿元人民币", "innolight_ar_2025", "2025年", value_num=382.40),
                _target_point("归母净利润", "财务", "107.97亿元", "亿元人民币", "innolight_ar_2025", "2025年", value_num=107.97),
                _target_point("经营现金流", "财务", "108.96亿元", "亿元人民币", "innolight_ar_2025", "2025年", value_num=108.96),
                _target_point("第一季度收入", "财务", "194.96亿元", "亿元人民币", "innolight_q1_2026", "2026年第一季度", value_num=194.96),
                _target_point("市场估值快照", "估值", "总市值约11830.41亿元，滚动市盈率约79.14倍", "亿元人民币/倍", "innolight_market_snapshot_202607", "截至2026-07-22", value_num=11830.41),
            ],
        },
        {
            "entity_key": "eoptolink_profitability_risk",
            "target_name": "新易盛",
            "ticker": "300502.SZ",
            "market": "SZ",
            "target_type": "security",
            "exposure_rationale": "新易盛同样高度暴露于AI高速光模块，规模较中际旭创小，增长和估值对产品结构、客户和现金转换更敏感。",
            "evidence_ref_uri": _ev("eoptolink_ar_2025"),
            "research_action": "重点复核1.6T及新架构产品、海外客户份额、扩产后的现金转换和营运资本，而不是只跟踪利润增速。",
            "investment_view": "毛利率与增长强，但2026年一季度现金流显著落后于利润，扩产和营运资本会放大竞争风险。",
            "risk_note": "较高市场估值需要未来收入和现金流大幅兑现；进入竞争与架构迁移若重叠，长期下修弹性较大。",
            "target_priority": "高：盈利弹性与现金流风险并存",
            "target_quality_label": "产品迭代强、现金转换需复核",
            "relative_preference": "相对中际旭创，毛利率更高且新架构响应积极，但规模、客户透明度和一季度现金转换更需要折扣。",
            "confirmed_scenario_action": "若竞争者全球突破同时公司预付款、库存和资本开支继续快于经营现金流，优先下调自由现金流和终值。",
            "falsified_scenario_action": "若新易盛通过XPO、NPO或CPO继续保持客户地位且现金流恢复，将架构风险从损失项改为价值迁移机会。",
            "target_profile_markdown": f"2025年新易盛实现收入248.42亿元、归母净利润95.32亿元、经营现金流77.01亿元，光模块毛利率47.81%；2026年一季度收入83.38亿元、净利润27.80亿元。{_cite('eoptolink_ar_2025')} {_cite('eoptolink_q1_2026')}",
            "target_deep_research_markdown": f"独立模型从2026年360亿元收入、122.4亿元归母净利润起步，2031年基线归母净利润176.85亿元。{_cite('eoptolink_ar_2025')} {_cite('eoptolink_q1_2026')} 11%回报要求和3%长期增长下的零净举债现金流敏感值约1541亿元，明显低于2026年7月约7094亿元市值。{_cite('eoptolink_market_snapshot_202607')} 独立预测比2026财年聚合收入低34%、利润低49%，差异主要来自1.6T后三季度放量、产能、利润率和现金转换。中国局部竞争情景下2031年利润约下降8%；全球重要第二供应商情景约下降25%；两家全球突破并压价时约下降43%。",
            "entity_relation_markdown": "该标的是龙头风险组合中的第二个上市公司，模型单独保留其更高毛利率、不同产能和现金流路径。",
            "parent_research_relation_markdown": "其结果用于比较同一竞争冲击对不同经营基数的传导，并识别现金流先于利润恶化的风险。",
            "conditional_investment_recommendation": "竞争证据未闭环前保持多情景；若现金流修复且产品迭代延续，不因新玩家出现就直接判定终值受损。",
            "financial_data_status": "年度和季度财务、市场数据可得；产品代际销量、客户份额、同代ASP及扩产后良率仍需补充。",
            "link_status": "linked",
            "support_status": "supported",
            "sort_order": 40,
            "target_data_points": [
                _target_point("营业收入", "财务", "248.42亿元", "亿元人民币", "eoptolink_ar_2025", "2025年", value_num=248.42),
                _target_point("归母净利润", "财务", "95.32亿元", "亿元人民币", "eoptolink_ar_2025", "2025年", value_num=95.32),
                _target_point("经营现金流", "财务", "77.01亿元", "亿元人民币", "eoptolink_ar_2025", "2025年", value_num=77.01),
                _target_point("第一季度经营现金流", "财务", "6.84亿元，约为同期净利润四分之一", "亿元人民币", "eoptolink_q1_2026", "2026年第一季度", value_num=6.84),
                _target_point("市场估值快照", "估值", "总市值约7093.98亿元，滚动市盈率约66.05倍", "亿元人民币/倍", "eoptolink_market_snapshot_202607", "截至2026-07-22", value_num=7093.98),
            ],
        },
    ]
    for target in targets:
        for field in (
            "target_profile_markdown",
            "target_deep_research_markdown",
            "entity_relation_markdown",
            "parent_research_relation_markdown",
        ):
            target[field] = _link_company_mentions(str(target.get(field) or ""))
    return targets


def _sections() -> list[dict[str, Any]]:
    c = _cite
    sections = [
        _section(
            "executive_summary",
            "摘要",
            f"""
## 结论先行

本节使用的计算方法是：先按产品、客户、产能和重复订单定义进入事件，再根据独立证据完成度给出宽概率区间，最后把竞争通过收入、毛利率、营运资本和资本开支传入现金流；摘要只呈现该过程的主要结果，详细输入和假设在后文展开。

截至2026年7月22日，**立讯精密已经是可被原始资料确认的高速光模块新进入者，比亚迪电子则仍属于有制造与系统协同基础、但光模块产品和客户链条尚未闭环的潜在进入者**。立讯2025年年报直接披露800G、1.6T小批量以及800G LRO部分客户验证；但公司在2026年5月又明确称自身是新进入者、商业和收入规模需要时间，并未披露具体云客户数量。{c('luxshare_ar_2025')} {c('luxshare_ir_20260525')} 比亚迪电子2025年AI基础设施收入9.43亿元，公开产品集中在服务器、液冷、电源和高速互联；2026年IDCE官方回顾仍没有列出800G或1.6T光模块。{c('byde_ar_2025')} {c('byde_idce_2026')}

我们把“有意义进入”定义为：在800G及以上数据中心光互联形成可持续批量收入，并达到全球约2%份额或中国约5%份额；证据至少跨越客户验证、批量订单和连续两代产品中的两项。产品页、展会、招聘或专利本身不满足定义。按这个口径，结论如下：

| 研究对象与市场 | 未来3年 | 未来5年 | 当前判断依据 |
|---|---:|---:|---|
| 比亚迪电子：任何市场 | 12%—25% | 22%—42% | AI基础设施和制造基础真实，但缺高速光模块规格、客户资格、专线与收入闭环 |
| 比亚迪电子：中国客户 | 10%—22% | 20%—38% | 中国系统客户和集团协同更可行，仍缺可核验订单 |
| 比亚迪电子：全球头部客户 | 4%—12% | 8%—22% | 产品与客户证据不足，且存在地缘与资格门槛 |
| 立讯精密：任何市场 | 55%—75% | 70%—88% | 有产品、小批量、互操作和供应商侧证据，规模与重复订单未闭环 |
| 立讯精密：中国客户 | 50%—70% | 65%—82% | 制造与本土系统客户协同更强 |
| 立讯精密：全球头部客户 | 20%—40% | 35%—60% | 国际客户基础存在，但光模块资格和份额没有公开闭环 |

两家公司并非独立事件：它们共享AI需求、DSP和激光器供给、认证窗口与架构变化。基准区间是未来3年“至少一家进入”60%—80%、“两家都进入”8%—20%；未来5年分别为75%—92%和18%—38%。其中，未来3年至少一家进入全球头部客户体系的概率为24%—45%，未来5年为42%—68%。这些区间是证据约束的结构化判断，不是历史频率置信区间，也不输出小数伪精度。

## 进入不等于利润崩塌

LightCounting估计2026年AI集群光学市场约260亿美元，800G仍可能同比翻倍，1.6T进入数千万端口量级。{c('lightcounting_jan2026')} {c('lightcounting_feb2026')} 因此最常见结果不是龙头收入马上下降，而是新进入者成为第二供应商、客户议价增强、份额和毛利率温和承压。给定至少一家有意义进入，未来3年温和竞争加剧的条件概率为55%—70%，明显恶化为20%—35%，严重结构性恶化只有5%—12%；未来5年分别为45%—60%、28%—42%和10%—20%。

真正危险的组合是：**至少一家完成全球头部客户认证并获得重复订单，上游InP和激光器瓶颈同步缓解，新进入者用低价或服务器、连接、液冷、电源组合销售扩张，而中际旭创、新易盛的同代ASP、毛利率、现金转换和客户份额同时恶化。** 单独看到招聘、产品页、互操作演示或CPO新闻，都不足以触发这一结论。

财务模型显示，在只限中国客户的情景中，2031年中际旭创和新易盛净利润较独立基线分别约低9%和8%；至少一家成为全球重要第二供应商时约低26%；两家公司都全球突破并以价格和组合销售抢份额时约低46%和45%。这回答了“进入后盈利会恶化多少”，同时也显示极端损失需要多项条件共同成立。当前两家龙头的市场市值都显著高于保守股权现金流模型，风险不仅来自比亚迪和立讯，还来自需求兑现、产能释放、现金转换、架构变化和估值回落。{c('innolight_market_snapshot_202607')} {c('eoptolink_market_snapshot_202607')}

## 投资判断

“明年估值看似便宜也不能买”目前不能被研究证据直接确认。更准确的表述是：龙头当期基本面强，但当前价格要求远高于本报告的保守独立盈利路径，长期竞争消息会放大估值波动。只有当全球客户资格、重复订单、份额、同代报价和龙头财务同时验证，竞争风险才应从情景折扣升级为基准盈利下修。反过来，如果立讯长期停留小批量、比亚迪没有正式产品，而龙头1.6T放量、毛利率和现金流保持，市场可能高估了“新增玩家等于利润崩塌”的风险。
""",
            ["luxshare_ar_2025", "luxshare_ir_20260525", "byde_ar_2025", "byde_idce_2026", "lightcounting_jan2026", "lightcounting_feb2026", "innolight_market_snapshot_202607", "eoptolink_market_snapshot_202607"],
            10,
        ),
        _section(
            "definitions_and_method",
            "事件定义、研究方法与概率口径",
            f"""
## 研究究竟在算什么

核心事件不是“公司是否展示过光模块”，而是“是否形成足以改变行业价格和份额的持续供给”。基准定义要求800G及以上数据中心光互联形成可持续批量收入，并达到全球约2%份额或中国约5%份额；同时，公开证据必须在客户验证、批量订单、连续两代产品三类里至少跨越两类。中国市场和全球头部客户分别判断，因为客户结构、认证、地缘政策和供应链要求不同。

竞争影响分三层。温和竞争加剧是新玩家成为第二供应商，需求增长仍能吸收新增供给，龙头份额和毛利率只小幅下降；明显恶化要求新增供应导致同代ASP、客户份额、付款条件或毛利率超出正常技术降本路径；严重结构性恶化则要求份额、利润率、资本回报和自由现金流持续下修，并且1.6T、3.2T、LPO、CPO或客户扩展无法抵消。

## 证据如何进入概率

研究没有把网页数量当概率。每条重要主张先追最早可见出处，再核对主体、产品、日期和数量，然后从公司、客户、供应商、专利、招聘、设备或标准组织寻找独立侧证，最后主动搜索否认、冲突和替代解释。同一公告的转载、共享同一匿名消息的券商报告和照搬同一图片的文章只算一个证据组。本轮共登记71个来源、70个独立证据组和142个平行数据点；其中市场传闻只进入线索队列，不能成为概率事实输入。

概率由里程碑完成度和反方约束共同决定。我们依次观察战略意愿、团队与专利、产品与互操作、器件与产线、客户资格、批量订单、重复订单和多代产品。立讯已有产品、小批量、互操作和供应商侧证据，所以基准区间高于比亚迪；但最新公司仍称业务刚起步，客户和财务规模不可见，因此区间没有收窄到高确定性。比亚迪具备服务器、热管理和制造邻近能力，却缺少光模块规格、客户资格、产线和收入，网络流传的部分专利还存在受让人错配，因此区间较低且更宽。

联合事件不按“比亚迪概率×立讯概率”机械相乘。两家公司共同受AI需求、上游器件、客户认证、标准节奏和架构窗口影响，同时又有不同的产品成熟度和客户路径。联合区间由三个约束构成：至少一家成功不能低于较高的单体概率；两家都成功不能高于较低的单体概率；需求与供给共同上行时提高同向发生的可能性，客户、产品和组织差异则保留分散。这个方法给出宽区间，避免把不可观察的相关系数伪装成精确参数。

## 阈值敏感性

定义越宽松，概率越高。若只要求可持续小批量和约1%全球份额，比亚迪未来3年为18%—35%、5年35%—55%，立讯分别70%—85%和80%—95%。若采用基准阈值，比亚迪降至12%—25%和22%—42%，立讯为55%—75%和70%—88%。若要求约5%全球份额、多客户且连续两代产品，比亚迪只有3%—10%和8%—20%，立讯为30%—50%和45%—70%。因此报告中的概率只有与事件定义一起阅读才有意义。

## 财务和供需模型

模型只保留三个难以用短句准确表达的核心关系：

1. **可服务模块量＝客户算力或交换端口量×网络架构对应的光互联强度×可服务产品比例×已认证份额。** 云厂商资本开支只是第一项的上游驱动，不能直接等同为公司收入。
2. **未来同代ASP＝当前同类ASP×正常代际降价因子×供需再平衡因子×新进入者额外压价因子。** 混合ASP还会被800G向1.6T升级抬高，因此必须把产品组合与同代价格分开。索尔思申请文件显示混合ASP随高速产品占比上升，正说明二者不能混写。{c('sourcephotonics_asp_mix')}
3. **自由现金流＝经营现金流－资本开支；股权价值＝预测期自由现金流折现值＋终值折现值。** 竞争先改变份额、收入、毛利率、营运资本和资本开支，再进入现金流和估值，模型没有直接给净利润乘一个主观折扣。

所有2027—2031年行业总量和公司预测都标为独立情景，不冒充外部事实。股权现金流估值使用9%—13%的回报要求与2%—4%的长期增长率作诊断；终值占比高达约58%—78%，因此只用于解释当前市值隐含什么，不强行给出目标价。外部一致预期在独立模型冻结后才读取，差异保留并单独解释。

## 方法局限

公开资料无法获得按客户、速率、距离和形态拆分的完整销量、ASP、良率和份额；招聘平台和网页历史也无法稳定还原全部岗位。概率因此是有方向、有上下界的判断区间，而不是统计频率。缺失客户私有资格资料可能低估真实进展，但不能用匿名传闻补齐。行业机构的付费逐年数据库不可得，2027—2031总量只能作为可复算情景。上述局限主要扩大区间，不改变“立讯证据显著强于比亚迪、规模化仍待验证”的相对结论。
""",
            ["sourcephotonics_asp_mix", "luxshare_ar_2025", "luxshare_ir_20260525", "byde_ar_2025", "byd_wrong_patent_800g", "ethernet_alliance_qualification", "fabrinet_qualification"],
            20,
        ),
        _section(
            "fresh_evidence_comparison",
            "比亚迪与立讯的真实进展对比",
            f"""
## 哪家公司更接近形成威胁

立讯明显领先，但“领先”指进入里程碑更靠后，并不代表已经获得可验证的大规模全球份额。比亚迪电子的公开证据目前主要是AI基础设施邻近能力；立讯的公开证据已经落在具体光模块产品、小批量、互操作和供应商合作。两者最重要的差异不是制造规模，而是光模块专属产品、客户与连续交付证据的完整度。

| 比较维度 | 比亚迪电子 | 立讯精密 / Luxshare-Tech | 研究结论 |
|---|---|---|---|
| 上市主体与业务归属 | 比亚迪电子承载AI服务器、液冷、电源和高速互联；比亚迪半导体不是同一业务主体 | Luxshare-Tech产品活动并入立讯精密体系 | 必须按经营主体判断，不能把集团能力直接相加 |
| 高速产品 | 官方年报、产品页和IDCE材料未列800G/1.6T光模块 | 年报和产品资料直接列800G、1.6T、DPO、LPO、LRO、AOC等 | 立讯已越过“是否有产品”阶段，比亚迪尚未由一手资料确认 |
| 客户与认证 | 没有公开的光模块客户、互操作、设计定点或批量订单 | 有部分客户验证、小批量、OIF/Keysight互操作；具体CSP数量未披露 | 立讯更接近商业化，但全球头部客户份额仍无法确认 |
| 专利与人才 | 有光通信招聘及车载光通信专利；流传的800G专利主体不属于比亚迪 | 有CPO、硅光外置激光与光模块结构专利及政府项目 | 专利只证明研发主题，不能证明订单、芯片所有权或良率 |
| 制造与供应链 | 大规模电子制造、服务器、热管理和电源协同强；光模块专线和良率不可见 | 自动化、连接器、线缆和模块制造协同强；核心DSP等仍依赖伙伴 | 两者都有可迁移优势，均需跨越光学与客户资格门槛 |
| 当前商业阶段 | 邻近能力与早期线索 | 新进入者、小批量向规模化过渡 | 未来3年立讯主导风险，未来5年才需要显著考虑比亚迪尾部路径 |

比亚迪电子2025年年度报告确认AI基础设施收入9.43亿元，同比增长31.7%，产品包括服务器、液冷、电源和高速互联。{c('byde_ar_2025')} 2026年3月投资者交流仍沿用这些大类，说明数据中心战略真实；但“高速互联”可能包括铜缆、连接器、背板或其他系统组件，不能自动翻译成800G或1.6T光模块。{c('byd_ir_20260330')} 公司IDCE 2026官方回顾展示的是AI服务器、液冷和800V直流供电，市场文章所称光模块展品在官方清单中没有出现。{c('byde_idce_2026')}

对比亚迪专利的核验改变了证据权重。公司确有车辆光通信系统专利和坪山区车载光通信活动，这些说明光通信邻近能力，但应用对象、温度、可靠性、协议和供应链与AI数据中心不同。{c('byd_patent_vehicle_1')} {c('gov_vehicle_optics_2026')} 网络文章引用的CN113514924A“800G光模块”实际申请人为苏州卓昱和亨通，不属于比亚迪；另一项1.6T光引擎专利属于武汉钧恒。错误归属不只是一处细节，它意味着此前“比亚迪已有直接专利”的概率输入必须删除。{c('byd_wrong_patent_800g')}

立讯的证据链更直接。2025年年报列出DPO、LPO、LRO、AOC及最高1.6T产品，称800G和1.6T处于小批量，800G LRO有部分客户验证；2025年4月交流曾称800G量产、1.6T在客户验证。{c('luxshare_ar_2025')} {c('luxshare_ir_20250428')} OIF和Keysight记录了800G多厂商互操作，POET从供应商侧确认双方扩展AI网络800G产品合作。{c('oif_luxshare_2024')} {c('keysight_luxshare_ofc2024')} {c('poet_luxshare_2024')} 这些证据能确认产品和生态接近度，却仍不能确认某家CSP正式资格或大规模份额。

最新反方证据更重要。立讯在2026年5月的交流中没有确认投资者提出的具体收入和CSP数量，反而称自身是新进入者，商业化和收入规模仍需时间，并表示没有可确认的自研1.6T硅光芯片。{c('luxshare_ir_20260507')} {c('luxshare_ir_20260525')} 公司在2025年11月还说明与Broadcom、Marvell等合作，自己更多承担后端模块制造、光学对准和测试。{c('luxshare_ir_20251126')} 这并不否定竞争力，但表明其优势首先是制造、系统和客户协同，而不是已经拥有从核心芯片到全球客户份额的完整闭环。

招聘在本轮只能作为领先指标。比亚迪校园材料出现光通信和光芯片光器件方向，但没有稳定公开的岗位ID、专属团队规模、产品代际、客户项目与时间序列；招聘聚合站的重复职位不能转化为“持续扩招人数”。立讯产品、专利和政府项目比招聘更具可核验性。公开职业信息未形成足够独立的关键人才流入证据，因此报告不写具体个人，也不从缺失信息反推“没有团队”。继续研究应优先获得原始岗位存档、首次和最后可见日期、地点、职责文本与后续产品对应关系。

综上，立讯的威胁路径是“已有产品和生态测试—扩大客户资格—自动化规模交付—用系统客户关系成为第二供应商”；比亚迪的威胁路径则是“AI基础设施和大制造平台—组建光学团队与关键器件生态—形成产品—先进入中国客户或集团协同—再挑战全球资格”。二者不应使用同一概率和同一时间表。
""",
            ["byde_ar_2025", "byd_ir_20260330", "byde_idce_2026", "byd_patent_vehicle_1", "gov_vehicle_optics_2026", "byd_wrong_patent_800g", "luxshare_ar_2025", "luxshare_ir_20250428", "oif_luxshare_2024", "keysight_luxshare_ofc2024", "poet_luxshare_2024", "luxshare_ir_20260507", "luxshare_ir_20260525", "luxshare_ir_20251126", "byd_recruitment_2026"],
            30,
        ),
        _section(
            "qualification_supply_chain",
            "客户资格、产能与供应链决定商业化速度",
            f"""
## 产品展示之后还有多远

本节要回答的问题是：一家公司从产品展示走到可持续批量究竟还要跨越哪些客户资格、供应链和制造环节，以及这些环节会把比亚迪和立讯的进度推迟多久。

高速光模块从样机到稳定收入通常要经过实验室评估、现场试验、互操作、客户系统验证、制造地点和流程资格、小批量订单、重复订单以及跨代延续。Ethernet Alliance对800G部署路径的描述明确区分实验室、现场、测试版、互操作、制造和商业阶段；Fabrinet年报披露制造地点或产品资格通常需要三至六个月甚至更长，并且可能同时需要直接客户和最终客户批准。{c('ethernet_alliance_qualification')} {c('fabrinet_qualification')} 因此展会互操作能显著提高“技术可用”的置信度，却不能单独证明正式量产和份额。

立讯目前已跨过产品与互操作，但公开证据未跨过“多客户重复订单和可验证规模”。Keysight和OIF记录的是多厂商演示，NVIDIA特定ConnectX-8支持清单中800G模块列出了其他供应商，而立讯仅出现200G DAC。{c('keysight_luxshare_ofc2024')} {c('oif_luxshare_2024')} {c('nvidia_connectx8_list')} 这份清单只适用于特定平台和版本，不能推断立讯在所有客户都未认证；但它足以反驳“公开生态资料已经证明全面进入NVIDIA平台”的强说法。欣强电子上市文件显示东莞讯滔采购800G和1.6T模块PCB，说明产品制造活动真实，却无法从该材料反推出最终客户、完整出货和收入。{c('xinqiang_supplier_ipo')}

比亚迪连这一阶段链条仍未形成。公开资料没有800G/1.6T规格书、互操作报告、客户送样或批准、设计定点、批量订单、专属产线和良率；公司AI基础设施总收入又混合服务器、液冷和电源。缺失不能被解释为“没有业务”，因为客户保密可能隐藏早期项目；但在投资研究中，它意味着不能把传闻升格为已确认量产。

## 上游瓶颈既限制新进入者，也保护现有供应商

LightCounting在2026年4月指出，需求一度超过InP和激光器供给约30%，紧缺可能到2026年末才缓解。{c('lightcounting_apr2026')} 这使新进入者即使完成模块设计，也可能在DSP、EML、CW Laser、硅光平台、TIA/Driver和高端测试设备上处于供货优先级劣势。立讯公开承认依赖Broadcom和Marvell等核心器件生态，说明规模制造不是全链自给。比亚迪的关键光器件来源更缺少公开资料。

供给保护不会永久存在。Veeco披露超过2.5亿美元的InP激光器设备订单，2026年交付并在2027年加速；AIXTRON获得Lumentum多台六英寸InP设备订单；Coherent也提出2026年扩产并在2027年继续增加。{c('veeco_inp_orders_2026')} {c('aixtron_lumentum_2026')} {c('coherent_capacity_2026')} 这意味着2026年的紧缺可以同时抬高龙头利润和推迟新进入者，但2027年后上游缓解、龙头扩产和新进入者认证可能重叠，反而成为价格压力最需要警惕的窗口。

## 制造准备度不能用公司总资本开支代替

光模块量产需要高精度贴装、主动或被动耦合、COB/COC、FA/MT装配、光电测试、老化与可靠性、散热、固件和可追溯质量体系。比亚迪和立讯在精密制造与自动化上都有可迁移优势，但公开资料没有给出可直接归属于高速光模块的设计产能、实际产能、良率、稼动率、单线投资或返修率。政府硅光项目、专利、PCB采购和合作伙伴能证明研发及制造活动，却不能补出这些数值。

相较之下，中际旭创2025年披露产能2806万只、产量2376万只、销量2109万只，新易盛披露产能1747万只、产量1634万只、销量1603万只；两家公司同时给出高毛利和多代量产的财务结果。{c('innolight_ar_2025')} {c('eoptolink_ar_2025')} 这些总量同样不能直接视为800G或1.6T数量，但至少提供了规模交付和制造爬坡的已实现基线。新进入者需要证明的不是“理论上可以组装”，而是同样复杂产品在客户质量要求下的持续良率和重复交付。

## 客户结构和地缘分层

中国客户和全球头部云客户应分开。中国客户更可能因本地供应链、系统集成和组合销售引入比亚迪或立讯；全球客户则还要考虑出口管制、数据安全、制造地点、长期合作、客户特定固件和供应链政策。报告没有把“国际客户”“北美大客户”映射为某一家CSP，也没有把NVIDIA平台合作自动视为终端客户订单。

客户侧最强证据应是公司与客户共同披露的资格、支持清单、兼容性记录、正式采购或多代重复供货。次强证据是供应商能够明确映射产品、数量和客户阶段。展会、专利和招聘更适合判断研发准备度。未来若出现单一客户的匿名产业链传闻，它只能扩大不确定性，不能直接进入市场份额或财务模型。

因此商业化速度的排序是：立讯最可能先通过中国或现有系统客户扩大，再尝试全球头部客户；比亚迪若进入，较可能先依托中国AI基础设施或集团协同；现有龙头则利用上游优先级、多代交付和客户共同开发守住全球高端份额。只有上游缓解、客户多源化和新进入者良率爬坡同时发生，竞争压力才会从局部变成行业级。
""",
            ["ethernet_alliance_qualification", "fabrinet_qualification", "keysight_luxshare_ofc2024", "oif_luxshare_2024", "nvidia_connectx8_list", "xinqiang_supplier_ipo", "lightcounting_apr2026", "veeco_inp_orders_2026", "aixtron_lumentum_2026", "coherent_capacity_2026", "innolight_ar_2025", "eoptolink_ar_2025"],
            40,
        ),
        _section(
            "demand_supply_model",
            "2026—2031需求、供给、价格与架构变化",
            f"""
## 需求增长可以吸收多少新增供给

本报告把2026年AI集群光学市场260亿美元作为公开锚，之后按需求由高增长逐步回落的独立情景扩展至2031年510亿美元。{c('lightcounting_jan2026')} 这不是LightCounting付费数据库的逐年预测，而是用于检验供给和财务数量级的研究假设。模型同时参考800G在2026年继续翻倍、1.6T达到数千万端口的行业判断，以及微软、Alphabet、Amazon、Meta和阿里公开的AI基础设施资本开支。{c('lightcounting_feb2026')} {c('microsoft_fy26q3')} {c('alphabet_2025q4')} {c('amazon_2025q4')} {c('meta_2026q1')} {c('alibaba_ai_2025')}

| 年份 | AI集群光学市场 | 主要需求变化 | 主要供给与架构变化 |
|---:|---:|---|---|
| 2026 | 260亿美元 | 800G继续扩张，1.6T进入规模部署 | InP与激光器仍紧，CPO开始批量制造 |
| 2027 | 320亿美元 | 1.6T成为增量主力，前后端网络同时扩容 | 上游扩产逐步释放，更多第二供应商完成资格 |
| 2028 | 370亿美元 | 1.6T深化，3.2T与200G/通道进入验证 | 新进入者的量产、良率和重复订单开始可检验 |
| 2029 | 420亿美元 | 网络光强度上升与每比特成本下降并存 | 中国与全球客户分层，CPO在部分交换层提高渗透 |
| 2030 | 470亿美元 | 增长回落，产品组合继续升级 | 供给更充分，同代价格与客户议价压力上升 |
| 2031 | 510亿美元 | 光互联仍增长，但不再维持早期高斜率 | 可插拔、LPO/LRO、光引擎和CPO按网络层共存 |

需求模型没有把资本开支直接变成光模块收入。资本开支先影响加速器、交换端口与网络拓扑，再由每个架构的光互联强度决定模块量。GPU与定制ASIC、前端与后端网络、scale-out与scale-up、机架内铜连接和机架间光连接的用量不同。缺少完整节点与端口底稿时，报告不输出看似精确的模块只数，而用行业总量、龙头产能、客户资本开支和产品节奏作交叉约束。

## 正常降价与竞争压价必须分开

光模块每比特成本会随代际、良率和规模自然下降；同时，800G向1.6T升级会推高混合ASP。索尔思申请文件披露数据中心模块销量增长且混合ASP上升，核心原因是高速产品占比提高，而不是同一代产品全面涨价。{c('sourcephotonics_asp_mix')} 因此模型先设置正常代际降价，再单独加入供需再平衡和新进入者额外压价。只有同规格、同距离、同客户或毛利率证据显示价格偏离正常路径，才把差额归因于竞争。

新进入者主要通过三条路径影响价格。第一，客户将其作为第二供应商，扩大比价能力；第二，以服务器、交换机、连接、液冷和电源组合报价，降低单个模块的可见利润；第三，在中国客户先取得规模后向全球扩张。反方向是需求增长吸收新增供给、上游器件仍紧、新进入者良率和售后成本抵消低价，以及客户因地缘和质量要求限制供应商。

## CPO不是对可插拔模块的一次性替代

2026年7月，NVIDIA披露Vera Rubin与Spectrum-X光子交换机进入批量制造，CoreWeave、Lambda和Oracle Cloud Infrastructure为首批采用者，说明CPO已经从长期概念进入早期商业部署。{c('nvidia_cpo_202607')} 但NVIDIA同一生态材料也列出中际旭创、新易盛、Fabrinet和Coherent等可插拔支持伙伴。{c('nvidia_cpo_pluggable_coexist')} 这意味着CPO主要先改变特定交换层的端口和价值分配，不等于所有网络层的可插拔模块同时消失。

模型按“可插拔需求＝总光端口×该网络层未采用CPO的比例×每端口模块数”处理架构迁移。CPO在交换芯片附近减少面板模块，却增加光引擎、激光源、光纤连接和封装测试需求。对中际旭创、新易盛而言，结果取决于它们能否从可插拔向XPO、NPO、CPO光引擎或相关制造迁移。新易盛已发布XPO及多种1.6T路线，显示现有龙头也在主动适应。{c('eoptolink_xpo_2026')}

## 新进入者不是唯一新增供给

AOI已披露1.6T首个批量订单，并计划把800G与1.6T合计能力提升至每月50万只以上；鸿海讨论2026年第三季度准备1.6T与CPO生产交付；Jabil已发布基于Intel硅光的1.6T模块。{c('aaoi_1p6t_order')} {c('foxconn_q1_2026')} {c('jabil_1p6t_2025')} 这些公司比尚无直接产品证据的比亚迪更接近当前竞争，因此行业风险模型不能只盯两家中国消费电子制造商。

到2031年的基准判断是：总需求仍增长，但增长速度下降；上游瓶颈逐步缓解；新老供应商数量增加；CPO在部分层级渗透；产品组合升级支撑混合ASP，而同代ASP和毛利率承压。这个组合更可能造成利润增速低于收入增速和估值中枢下降，而不是行业收入绝对崩塌。若需求低于本情景、CPO扩张更快且供应同时释放，竞争损失将明显扩大；若AI端口增长持续超预期、上游继续紧缺且龙头保持新架构份额，则新增供给主要被市场吸收。
""",
            ["lightcounting_jan2026", "lightcounting_feb2026", "microsoft_fy26q3", "alphabet_2025q4", "amazon_2025q4", "meta_2026q1", "alibaba_ai_2025", "sourcephotonics_asp_mix", "nvidia_cpo_202607", "nvidia_cpo_pluggable_coexist", "eoptolink_xpo_2026", "aaoi_1p6t_order", "foxconn_q1_2026", "jabil_1p6t_2025"],
            50,
        ),
        _section(
            "probability_results",
            "进入概率、联合情景与竞争影响",
            f"""
## 单体概率为什么不同

比亚迪电子的基准概率为未来3年12%—25%、5年22%—42%。支持上界的证据是AI基础设施收入增长、服务器与液冷电源能力、集团制造规模、光通信招聘和车载光通信邻近能力；压低下界的证据是没有官方800G/1.6T规格、互操作、客户资格、专线、良率、收入和重复订单，且网络文章引用的直接专利存在主体错配。{c('byde_ar_2025')} {c('byd_recruitment_2026')} {c('byd_wrong_patent_800g')} 中国市场概率高于全球头部客户，因为本地系统协同和供应链路径更短；全球客户还要增加产品代际、资格、制造地点和地缘约束。

立讯精密的基准概率为未来3年55%—75%、5年70%—88%。支持因素包括直接产品矩阵、年报小批量、部分客户验证、800G互操作、供应商合作和精密制造基础。{c('luxshare_ar_2025')} {c('keysight_luxshare_ofc2024')} {c('poet_luxshare_2024')} 区间没有进一步提高，是因为公司最新仍称自己为新进入者、没有披露客户数量和规模，核心器件依赖生态伙伴，财报也未分拆收入、毛利率和良率。{c('luxshare_ir_20260525')} {c('luxshare_ir_20251126')}

## 联合结果

未来3年至少一家有意义进入的概率为60%—80%，两家都进入为8%—20%，至少一家进入全球头部客户为24%—45%。未来5年相应为75%—92%、18%—38%和42%—68%。至少一家概率主要由立讯驱动；两家都进入的尾部由比亚迪的产品和客户证据决定。共享AI需求和上游供给使事件存在正相关，但两家公司起点和路径不同，所以不能把单体区间简单相乘，也不能把它们当成完全同向。

联合概率使用边界约束与情景一致性，而不是假装存在可观测相关系数。若上游短缺长期持续，两者会共同被压低；若客户大规模引入第二供应商且器件供给缓解，两者会共同上移。立讯先进入中国客户不会自动证明比亚迪也会进入；比亚迪服务器业务增长也不会自动提高立讯的光模块客户资格。

## 进入后的行业结果

给定至少一家成功进入，未来3年温和竞争加剧为55%—70%、明显竞争恶化20%—35%、严重结构性恶化5%—12%；未来5年分别45%—60%、28%—42%和10%—20%。最常见结果仍是需求增长吸收一部分新增供给，新玩家作为第二供应商提高客户议价，龙头份额和利润率下降但收入继续增长。

“明显恶化”需要至少三类事实一起出现：一是全球头部客户正式资格和重复订单；二是可验证产能、良率与跨代产品；三是龙头同代ASP、客户份额、毛利率或现金转换偏离正常路径。严重恶化还需要需求或架构缓冲失效，例如CPO在关键网络层快速替代而龙头未能转型，或新增供给在需求放缓时集中释放。

把进入概率与损失幅度合并后，中际旭创未来3年发生显著利润损失的概率为18%—32%、未来5年28%—48%；新易盛分别为20%—35%和32%—52%。这里“显著利润损失”指模型中的全球重要第二供应商或更差路径，而不是任何轻微毛利变化。新易盛区间略高，是因为规模更小、当前现金转换波动更大，且市场对长期增长要求更高；这不是对公司管理能力的主观排序。

## 什么证据会更新概率

上调比亚迪概率的强证据依次是：官方800G/1.6T规格、独立互操作、客户侧资格、专属产线与设备、连续批量订单、分拆收入和跨代延续。只有招聘或专利会小幅上调准备度，不会直接推动到量产概率。下调证据是未来两个关键展会和两轮财报仍无产品、客户和收入，相关岗位长期不再出现，或官方明确将高速互联限定为非光模块产品。

上调立讯概率的强证据是客户数量与产品代际可验证、1.6T连续季度批量、财务分拆、多个平台支持清单和下一代产品重复资格。下调证据是长期停留小批量、客户资格推迟、核心器件无法获得、产线良率未达标，或公司再次弱化收入时间表。

上调龙头盈利损失概率必须看到结果端同步变化：同代报价降幅扩大、全球客户份额下降、毛利率超出正常产品周期下滑、库存或应收上升、经营现金流显著弱于利润、资本开支回报下降。若只出现新玩家新闻而龙头订单、价格和现金流保持，则损失概率不应机械提高。

## 重要但尚未验证的线索

2026年7月网络文章反复声称比亚迪已具备800G月产、海外交付和IDCE光模块展示。追溯后，这些文章共享相近措辞，属于一个传闻簇；官方IDCE回顾未列光模块，关键专利受让人也不属于比亚迪。{c('byd_weak_rumor_202607')} {c('byde_idce_2026')} {c('byd_wrong_patent_800g')} 该线索不会进入概率事实或财务输入，但因其若属实会显著抬高比亚迪3年概率，仍保留为最高优先级补证事项。需要的不是更多转载，而是公司、客户、供应商、产品规格、产线或正式采购中的至少两条独立原始证据。
""",
            ["byde_ar_2025", "byd_recruitment_2026", "byd_wrong_patent_800g", "luxshare_ar_2025", "keysight_luxshare_ofc2024", "poet_luxshare_2024", "luxshare_ir_20260525", "luxshare_ir_20251126", "byd_weak_rumor_202607", "byde_idce_2026"],
            60,
        ),
        _section(
            "financial_impact",
            "中际旭创与新易盛的盈利、现金流和估值影响",
            f"""
## 独立基线先于市场预期冻结

为避免被卖方和聚合预测锚定，模型先用2025年年报、2026年一季度、产能和行业需求建立2026—2031独立经营基线，再读取市场一致预期。中际旭创2025年收入382.40亿元、归母净利润107.97亿元、经营现金流108.96亿元；2026年一季度收入194.96亿元、净利润57.35亿元。{c('innolight_ar_2025')} {c('innolight_q1_2026')} 新易盛2025年收入248.42亿元、净利润95.32亿元、经营现金流77.01亿元；2026年一季度收入83.38亿元、净利润27.80亿元、经营现金流只有6.84亿元，扩产和营运资本已经使现金与利润出现分化。{c('eoptolink_ar_2025')} {c('eoptolink_q1_2026')}

| 公司 | 历史实际期间 | 营业收入 | 归母净利润 | 经营现金流 |
|---|---|---:|---:|---:|
| 中际旭创 | 2025年 | 382.40 | 107.97 | 108.96 |
| 中际旭创 | 2026年第一季度 | 194.96 | 57.35 | 33.68 |
| 新易盛 | 2025年 | 248.42 | 95.32 | 77.01 |
| 新易盛 | 2026年第一季度 | 83.38 | 27.80 | 6.84 |

表中金额均为亿元人民币。它把两家公司历史盈利与现金转换放在同一口径下：2025年两家现金流都较强，但2026年第一季度新易盛现金流明显落后于利润，说明未来竞争冲击需要同时观察营运资本和资本开支。

独立基线对2026年后三个季度和长期利润率采取保守路径：中际旭创2026年收入800亿元、净利润236亿元，2031年收入1460亿元、净利润365亿元、自由现金流330亿元；新易盛2026年收入360亿元、净利润122亿元，2031年收入655亿元、净利润177亿元、自由现金流156亿元。行业仍增长，但公司净利率逐年回落，资本开支和营运资本继续占用现金。

外部聚合预测明显更高：中际旭创未来一年收入约1346.85亿元、隐含净利润约413.56亿元；新易盛收入约737.01亿元、隐含净利润约266.22亿元。{c('innolight_market_snapshot_202607')} {c('eoptolink_market_snapshot_202607')} 独立模型分别低约41%和43%、51%和54%。差异没有被强行抹平，因为外部预测缺乏逐产品、逐客户和逐季度底稿；真正需要核验的是1.6T在2026年后三季度的放量、上游瓶颈、产能和利润率，而不是让模型自动靠近市场。

## 进入后的盈利变化

下表把新进入者和架构变化通过收入份额、毛利率、现金转换和资本开支传入2031年。金额为亿元人民币；括号是相对独立基线的净利润变化。股权现金流价值采用11%回报要求、3%长期增长，只用于跨情景比较。

| 情景 | 中际旭创2031净利润 | 新易盛2031净利润 | 中际旭创现金流价值 | 新易盛现金流价值 |
|---|---:|---:|---:|---:|
| 独立经营基线 | 365（基准） | 176.9（基准） | 3399 | 1594 |
| 立讯形成规模、比亚迪仍偏区域 | 310.9（-14.8%） | 151.4（-14.4%） | 2928 | 1384 |
| 两家公司主要进入中国客户 | 333.4（-8.7%） | 162.0（-8.4%） | 3120 | 1470 |
| 至少一家成为全球重要第二供应商 | 269.0（-26.3%） | 131.6（-25.6%） | 2570 | 1224 |
| 两家公司全球突破并压价 | 198.3（-45.7%） | 98.1（-44.5%） | 1952 | 948 |
| CPO等架构加快、价值重新分配 | 262.1（-28.2%） | 128.1（-27.6%） | 2506 | 1195 |

敏感性分析显示，若2031年收入不变而额外毛利率压力每增加1个百分点，并按约75%的税后比例传导，中际旭创净利润约再下降11亿元，新易盛约再下降5亿元；若压力持续进入终值，估值影响会大于单年利润变化。反过来，若同代价格和毛利率压力比全球第二供应商情景少1个百分点，利润与现金流下修也会相应收窄。这个检验说明客户份额之外，毛利率是最能改变长期结论的第二个变量。

结果有三个重要含义。第一，中国客户局部进入对全球收入占比较高的龙头影响有限，不能把“中国形成供应”直接翻译成全球终值崩塌。第二，全球重要第二供应商情景的利润损失约四分之一，主要来自份额下降和毛利率额外下滑；这是最值得投入监控的中间情景。第三，接近45%的利润损失需要两家同时全球突破、低价和组合销售有效、需求无法完全吸收、上游不再紧缺且龙头防御不足，不能成为没有客户证据时的默认基线。

## 估值检验

截至2026年7月14日，中际旭创市值约13205亿元、滚动市盈率约88倍；新易盛约7931亿元、约74倍。{c('innolight_market_snapshot_202607')} {c('eoptolink_market_snapshot_202607')} 用独立2026年利润计算，市盈率约56倍和65倍。以9%—13%股权回报要求和2%—4%长期增长估算，中际旭创股权现金流价值约2529—5296亿元，新易盛约1183—2490亿元；中性参数为3399亿元和1594亿元，终值占比仍约67%。

这不是要把现金流模型当作唯一正确目标价。高成长硬件公司的早期利润和终值都高度敏感，市场可能在定价远高于独立基线的2026年与长期自由现金流。反向检验显示，若其他路径同比例放大，当前市值对应的2031年自由现金流约需达到中际旭创1282亿元、新易盛777亿元，远高于独立基线330亿元和156亿元。它说明当前定价的核心风险是增长、利润率、现金转换和回报要求共同下修，而不是只有比亚迪或立讯这一条变量。

## “低估值也不能买”何时成立

如果未来某一时点表面市盈率下降，但下降来自市场仍用高利润预测、而全球客户份额、同代ASP、毛利率和现金流已经出现持续恶化，那么低倍数可能是终值陷阱。相反，如果估值下降只是股价调整，而立讯仍停留小批量、比亚迪没有正式产品、龙头1.6T放量和现金流保持，则“新进入者导致终值崩塌”可能被过度定价。

判断不应使用单一市盈率阈值。需要同时观察：未来两年利润兑现率、市场资本化中终值占比、同代价格与正常降本的差额、客户份额、资本开支回报、经营现金流与净利润的比例，以及证据是否跨过全球客户和重复订单门槛。任何估值结论都要与这些经营触发条件绑定。
""",
            ["innolight_ar_2025", "innolight_q1_2026", "eoptolink_ar_2025", "eoptolink_q1_2026", "innolight_market_snapshot_202607", "eoptolink_market_snapshot_202607", "lightcounting_jan2026", "luxshare_ir_20260525"],
            70,
        ),
        _section(
            "red_team_and_monitoring",
            "反方检验与未来12—24个月监控",
            f"""
## 为什么当前结论可能高估风险

第一，高速光模块不是普通电子装配。产品需要光学设计、核心器件选择、耦合封装、固件、热管理、测试、可靠性和客户长期协同；Fabrinet披露的资格流程可能超过三至六个月，而且制造地点也需重新批准。{c('fabrinet_qualification')} 新进入者拥有工厂和自动化并不等于能快速复制高良率及多代交付。

第二，需求仍可能快于供给。LightCounting估计2026年AI集群光学市场约260亿美元，800G和1.6T保持高增长，上游供给一度落后需求约30%。{c('lightcounting_jan2026')} {c('lightcounting_apr2026')} 即使立讯取得份额，龙头收入仍可能因总量扩张而增长。只有份额损失与同代降价超过需求增量，利润才会显著恶化。

第三，全球客户不会只按价格选择供应商。地缘政策、数据安全、制造地点、可靠性、现场支持和过去交付记录可能限制比亚迪与立讯的海外渗透。NVIDIA当前公开生态既有CPO早期采用者，也继续列出中际旭创、新易盛等可插拔伙伴，说明架构变化并未把龙头一次性排除。{c('nvidia_cpo_202607')} {c('nvidia_cpo_pluggable_coexist')}

第四，现有龙头正在移动门槛。中际旭创确认1.6T量产逐步提高且订单充足，新易盛发布XPO、液冷可插拔及多种1.6T路线。{c('innolight_ir_20260424')} {c('eoptolink_xpo_2026')} 如果龙头能保持核心器件优先级、自动化和客户联合开发，新进入者更可能只获得低利润或局部市场。

## 为什么当前结论也可能低估风险

公开资料可能因客户保密而滞后于真实认证；公司在正式量产前通常不会披露客户名称和份额。立讯已有小批量、互操作和供应商合作，实际项目可能比财报分拆更靠前。比亚迪的大规模制造、AI服务器和系统级组合能力一旦获得产品团队和核心器件支持，进度可能非线性加快。客户也有降低单一供应商依赖和压低价格的持续动机。

此外，上游扩产、AAOI、鸿海和Jabil等新增供给意味着风险来源不止比亚迪与立讯。{c('veeco_inp_orders_2026')} {c('aaoi_1p6t_order')} {c('foxconn_q1_2026')} {c('jabil_1p6t_2025')} 如果器件供给在需求增速回落时集中释放，龙头可能同时面对更多第二供应商、同代价格下降和产能利用率回落。把研究范围只限于两家公司会低估系统性供给风险。

## 监控规则

| 监控信号 | 更新频率 | 触发条件 | 对判断的影响 |
|---|---|---|---|
| 比亚迪官方产品、展会与客户资料 | 每月及重大事件 | 首次出现800G/1.6T规格、互操作或客户侧资格 | 由邻近能力上调到产品或认证阶段 |
| 立讯批量、客户与收入 | 每季及重大事件 | 连续两个季度出现可核验批量、客户增加和收入分拆 | 提高全球进入概率，重跑份额与价格情景 |
| 上游器件与设备 | 每季 | InP、激光器、DSP交期恢复且扩产兑现 | 降低供给保护，提高竞争压力 |
| 龙头同代价格与份额 | 每季 | 同规格价格、毛利率或全球客户份额偏离正常路径 | 把进入新闻转化为实际财务损失证据 |
| 龙头现金转换 | 每季 | 经营现金流持续明显低于净利润，库存、预付款、应收或资本开支上升 | 提前下调自由现金流与终值 |
| CPO与新架构 | 每月及平台发布 | 从首批交换层扩展到更多网络层，龙头未进入相应光引擎生态 | 提高架构迁移损失；若龙头同步进入则下调 |

监控不自动改分。每个触发事件先核对主体、产品、日期、数量和来源独立性，再判断它改变的是产品成熟度、客户资格、供给能力、市场份额还是财务结果。产品发布只能更新早期里程碑；客户侧资格和重复订单才更新进入概率；龙头同代价格、利润率和现金流才更新损失幅度。

## 证实和证伪

“竞争格局已明显恶化”需要至少看到：立讯或比亚迪在全球头部客户形成重复订单；可验证的800G及以上产能和良率；客户份额不只是匿名描述；同代报价低于正常技术降价；中际旭创或新易盛的份额、毛利率、营运资本或现金流出现持续偏离。没有结果端证据时，只能称风险上升。

反过来，如果立讯到2027年仍只有小批量且客户不增加，比亚迪连续两轮财报和主要展会仍没有直接产品与客户证据，上游紧缺持续，而中际旭创、新易盛保持1.6T份额、毛利率和现金转换，则应下调进入和损失概率。若CPO扩展但龙头成为光引擎或新可插拔生态供应商，也应把“架构毁灭”改写为价值重新分配。

这一监控框架的目的不是制造更多字段，而是把每条新信息映射到明确的结论变化。最关键的五个可证伪信号依次是：客户侧资格、重复订单、专属产能与良率、同代价格、龙头现金流。招聘、专利、论坛和展会照片仍可用于发现线索，但不会单独触发投资结论。
""",
            ["fabrinet_qualification", "lightcounting_jan2026", "lightcounting_apr2026", "nvidia_cpo_202607", "nvidia_cpo_pluggable_coexist", "innolight_ir_20260424", "eoptolink_xpo_2026", "veeco_inp_orders_2026", "aaoi_1p6t_order", "foxconn_q1_2026", "jabil_1p6t_2025"],
            80,
        ),
        _section(
            "conclusion_and_next_evidence",
            "综合结论与继续提高可信度所需资料",
            f"""
## 对核心问题的最终回答

当前能够确认的是：立讯精密已具备直接的800G、1.6T和低功耗光模块产品、小批量与部分客户验证，并参加过可核验互操作；但客户数量、稳定产能、良率、重复订单、分拆收入和利润率尚未公开，公司最新仍称业务处于新进入阶段。{c('luxshare_ar_2025')} {c('luxshare_ir_20260525')} 比亚迪电子能够确认AI服务器、液冷、电源和高速互联业务增长，也有光通信招聘与车载光通信邻近能力；但截至执行日，没有可由官方、客户或供应商闭环的800G/1.6T数据中心光模块规格、资格、产线和收入。{c('byde_ar_2025')} {c('byd_recruitment_2026')}

因此，未来3年的主要新进入风险来自立讯，未来5年才需要把比亚迪制造与系统协同形成的尾部路径纳入更高权重。立讯3年和5年有意义进入概率为55%—75%和70%—88%，比亚迪为12%—25%和22%—42%。中国客户概率高于全球头部客户，尤其对比亚迪如此。至少一家进入很可能发生，但两家同时全球形成规模仍不是基准情景。

市场增长大概率能吸收一部分新增供给。AI集群光学市场、800G和1.6T端口仍处高增长，上游器件短缺也限制供给。{c('lightcounting_jan2026')} {c('lightcounting_feb2026')} 所以“参与者增加”首先表现为客户多源化和议价增强，不必然让龙头收入下降。真正危险的不是新玩家名字，而是全球客户资格、跨代产品、规模良率、低价或组合销售、上游瓶颈缓解和龙头结果端恶化同时出现。

对中际旭创和新易盛，基准竞争风险更可能使2031年利润下降约8%—26%，而不是直接下降45%以上。极端损失情景需要两家公司都全球突破并以价格和组合销售抢份额，且需求、上游与龙头防御同时不利。中际旭创和新易盛当前市场估值又显著高于本报告的保守现金流路径，因此估值风险既可能由竞争触发，也可能由市场增长、利润率、现金转换或回报要求下修触发。{c('innolight_market_snapshot_202607')} {c('eoptolink_market_snapshot_202607')}

“长期竞争格局已经恶化、低估值也不能买”在以下证据出现前仍是未完全证实的风险假设：至少一家新进入者获得全球头部客户正式资格并形成重复订单；专属产能、良率和跨代产品可验证；龙头同代ASP或份额偏离正常路径；毛利率和经营现金流持续受到影响。反过来，若新进入者停留小批量、龙头继续在1.6T和新架构领先、需求吸收新增供给，这一假设应被下调。

## 仍需补充什么

最有价值的补充不是再找更多转载，而是取得以下原始资料。第一，比亚迪电子800G及以上产品规格书、首次发布记录、客户或平台互操作、专属产线设备、量产良率、批量订单与分拆收入。第二，立讯1.6T连续季度出货、客户数量、正式资格、跨代重复订单、产能和良率，以及光模块收入和毛利率。第三，中际旭创、新易盛按速率、客户和地区拆分的销量、同代ASP、份额、核心器件供货、库存、应收与扩产回报。第四，CPO在不同网络层的实际端口渗透，以及龙头是否进入光引擎、外置激光和封装供应链。

招聘与人才还需要原始岗位ID、首次和最后可见日期、地点、职责、产品代际与客户关键词，并用专利发明人、会议讲者或后续产品交叉验证；当前公开证据不足以建立可信的人才流入时间序列。专利还需要完整受让人别名、同族去重、权利要求与法律状态；本轮已识别出比亚迪相关网络文章的主体错配，说明只按标题搜索会产生严重误判。

产能方面需要政府项目、设备供应商、招标、环评或公司披露明确映射到高速光模块，而不是使用公司整体资本开支。客户方面需要正式支持清单、联合公告、采购或可重复的供应商侧数量证据，不得把“国际客户”“头部客户”自动具名。价格方面需要同规格、同距离、同客户的报价或可复核毛利桥，混合ASP不能替代。

## 研究边界

本报告完成了广泛检索、原始来源追溯、冲突核验、独立模型和外部对账，但无法访问客户私有资格、付费行业逐年数据库、公司内部良率和全部历史招聘快照。公开资料滞后可能使真实进度被低估；营销材料、券商推断和网络传闻又可能使进度被高估。报告通过宽概率区间、分离中国与全球、把弱线索排除于核心输入以及将财务损失绑定结果端证据来处理这种双向偏误。

最终最稳健的判断是：**立讯成为有意义供应商的概率已经较高，但是否成为全球头部客户的重要第二供应商仍待验证；比亚迪是值得持续跟踪的中长期尾部竞争者，现阶段公开证据不支持“已经量产并规模出海”；龙头长期盈利会承压的概率不低，但利润大幅坍塌不是当前基准情景。** 后续更新应围绕客户资格、重复订单、良率、同代价格和现金流，而不是围绕新闻数量。
""",
            ["luxshare_ar_2025", "luxshare_ir_20260525", "byde_ar_2025", "byd_recruitment_2026", "lightcounting_jan2026", "lightcounting_feb2026", "innolight_market_snapshot_202607", "eoptolink_market_snapshot_202607", "byd_wrong_patent_800g", "nvidia_cpo_202607"],
            90,
        ),
    ]
    return sections


def _entity_sections() -> list[dict[str, Any]]:
    c = _cite
    return [
        _entity_section(
            "byd_entry_risk",
            "比亚迪电子：从AI基础设施邻近能力到高速光模块仍缺哪些环节",
            f"""
## 研究对象与业务归属

比亚迪集团内最接近AI数据中心硬件的上市主体是比亚迪电子，而不是比亚迪半导体。比亚迪电子由比亚迪股份控股并纳入合并报表，公开业务已覆盖服务器、液冷、电源和高速互联；比亚迪半导体的主要能力在功率半导体与汽车电子，不能因为名称中有“半导体”就把其技术自动并入数据中心光模块。{c('byde_ar_2025')} {c('byde_history')} 本研究因此以比亚迪电子作为经营与财务承载主体，同时把集团制造、资金和客户协同视为外部支持条件，而不是已实现的光模块能力。

2025年比亚迪电子AI基础设施收入9.43亿元，同比增长31.7%。这一数字证明数据中心方向已经商业化，但年报列示的产品是AI服务器、液冷、电源和高速互联，没有800G、1.6T、3.2T、OSFP、QSFP-DD、DR、FR、LPO或CPO的明确分拆。{c('byde_ar_2025')} 2026年3月投资者交流仍强调服务器、液冷、电源和高速互联新产品，不能从“高速互联”四个字反推光模块。{c('byd_ir_20260330')}

## 产品、展会与客户证据

比亚迪电子当前数据中心产品页仍以服务器、液冷和电源为主。2026年IDCE官方回顾展示AI服务器、液冷和NVIDIA 800V直流供电合作，没有列出800G或1.6T光模块。{c('byde_product_page')} {c('byde_idce_2026')} 因而网络文章关于“IDCE展示光模块”的说法与官方清单发生冲突。冲突处理不能在两者之间折中：官方展会材料优先，文章保留为待核线索。

公开资料还没有形成客户送样、实验室互操作、正式资格、设计定点、小批量、稳定量产、重复订单和跨代延续的链条。客户保密可能使公开进度滞后，但没有客户侧或供应商侧独立证据时，不能把“进入全球头部客户供应链”映射为具体CSP或高速光模块。该宽泛表述更可能覆盖服务器、电源、液冷或其他零部件。

## 招聘、专利与可迁移能力

2026届校园招聘材料出现光通信和光芯片光器件方向，说明集团可能在建立相邻人才能力；但公开材料没有专属业务主体、岗位ID、人数、产品代际、客户项目和持续时间序列。{c('byd_recruitment_2026')} 聚合招聘网站的重复发布不能被当作多人扩招，匿名职业履历也不宜用来推断私人流动。因此本轮把招聘用于提高补证优先级，没有将其直接变成量产概率。

比亚迪拥有车辆光通信系统相关专利，坪山区也披露车载光通信工作组活动。{c('byd_patent_vehicle_1')} {c('gov_vehicle_optics_2026')} 这类能力可能在光器件选型、可靠性、系统工程和批量制造上提供迁移基础，但数据中心800G/1.6T需要不同的速率、调制、封装、固件、互操作和客户质量体系。最关键的纠错是，网络文章经常引用的CN113514924A“800G光模块”实际属于苏州卓昱与亨通；另一项1.6T光引擎专利也属于武汉钧恒，不属于比亚迪。{c('byd_wrong_patent_800g')} 这些记录从直接技术证据中剔除。

## 为什么可能成功

比亚迪电子拥有大规模制造、自动化、供应链管理、服务器、液冷、电源和热管理能力。如果它获得成熟光学团队、稳定DSP与激光器供给，并以中国AI基础设施客户或集团方案切入，能够降低获客和系统集成成本。集团资金实力允许其容忍较长认证和较低早期毛利，组合销售也可能提高客户引入第二供应商的意愿。AI光互联市场仍高速增长，为试单和区域供货提供空间。{c('lightcounting_jan2026')}

## 为什么可能失败

高速光模块的门槛集中在光学设计、耦合良率、可靠性、固件、交换机互操作、客户联合验证和连续多代交付，而不是一般电子制造。上游InP、激光器、DSP和硅光平台在紧缺时还会优先供应已形成订单的厂商。客户资格可能需要三至六个月以上，制造地点和最终客户都可能单独批准。{c('fabrinet_qualification')} 比亚迪若错过1.6T窗口，随后直接面对3.2T或CPO架构切换，追赶难度会上升。

## 结论与触发条件

未来3年有意义进入概率12%—25%，5年22%—42%；中国客户为10%—22%和20%—38%，全球头部客户只有4%—12%和8%—22%。区间上沿承认集团协同和非线性投入，下沿反映产品、客户、产线和财务链条缺失。当前不能认为比亚迪已经量产800G或验证1.6T，也不能据此下调龙头基准盈利。

下一次显著上调需要四类证据中的至少两类共同出现：公司正式规格与产品页；客户或平台互操作和资格；专属设备、产线与可复核良率；批量订单、分拆收入和跨代产品。若未来两个主要展会与两轮财报仍无直接证据，应下调3年区间。最重要的未验证线索是2026年7月传闻簇中的月产、海外交付和展会展示；它们目前与官方材料冲突，不能成为结论。{c('byd_weak_rumor_202607')}
""",
            ["byde_ar_2025", "byde_history", "byd_ir_20260330", "byde_product_page", "byde_idce_2026", "byd_recruitment_2026", "byd_patent_vehicle_1", "gov_vehicle_optics_2026", "byd_wrong_patent_800g", "lightcounting_jan2026", "fabrinet_qualification", "byd_weak_rumor_202607"],
            110,
        ),
        _entity_section(
            "luxshare_entry_risk",
            "立讯精密：产品已形成，关键问题转向规模、客户和利润",
            f"""
## 主体与产品路线

立讯精密体系的高速光模块产品主要以Luxshare-Tech名义对外展示，并进入上市公司合并经营范围。2025年年报已经列出DPO、LPO、LRO、AOC及最高1.6T的产品矩阵，说明它不是只有招聘或专利的概念参与者。{c('luxshare_ar_2025')} 产品资料覆盖800G OSFP、硅光和多种低功耗路线，OFC 2025也展示1.6T与800G方案。{c('luxshare_product_matrix')} {c('luxshare_ofc_2025')}

公开信息的关键不是“有没有产品”，而是不同产品处于哪个阶段。2024年年报曾称800G通过AI客户测试并向国际客户批量交付；2025年最新年报仍将800G、1.6T整体描述为小批量，800G LRO为部分客户验证。{c('luxshare_ar_2024')} {c('luxshare_ar_2025')} 两个披露并非必然矛盾，可能对应不同客户、产品、距离或出货口径；但它们不能合并成“全部800G/1.6T已经稳定量产”。最新口径优先用于当前规模判断。

## 互操作、供应商与客户反查

Keysight和OIF材料确认立讯参加800G多厂商互操作，POET确认双方扩展AI网络产品合作。{c('keysight_luxshare_ofc2024')} {c('oif_luxshare_2024')} {c('poet_luxshare_2024')} 这些独立来源提高技术可用性和生态接近度，但互操作不等于最终客户资格。NVIDIA ConnectX-8特定支持清单中，800G模块列出其他厂商，立讯只出现200G DAC；这只能约束该平台版本，却足以说明公开资料没有形成“立讯800G已全面进入NVIDIA生态”的闭环。{c('nvidia_connectx8_list')}

欣强电子上市文件披露东莞讯滔采购800G和1.6T光模块PCB，从供应链侧证明制造活动。{c('xinqiang_supplier_ipo')} 但PCB采购无法确定最终客户、成品数量、良率和收入。公司在2026年5月没有确认投资者提问中的具体CSP数量和收入，明确称自己仍是新进入者，商业化和收入规模需要时间。{c('luxshare_ir_20260507')} {c('luxshare_ir_20260525')} 这是当前最重要的规模边界。

## 技术资产与核心器件

立讯拥有CPO结构、硅光外置激光和光发射组件等专利，并进入东莞硅光政府研发项目。{c('luxshare_patent_cpo')} {c('luxshare_patent_sipho')} {c('luxshare_siph_gov_project')} 这些资料支持封装、结构和系统研发方向，不证明核心硅光芯片所有权、产品良率或客户订单。公司最新交流也没有确认自研1.6T硅光芯片。

2025年11月投资者交流说明公司与Broadcom、Marvell等合作，自己更多承担后端模块制造、光学对准和测试。{c('luxshare_ir_20251126')} 这一分工可以发挥自动化和精密制造优势，但也使核心DSP、激光器和平台供给成为约束。上游紧缺时，既有大客户与成熟模块商可能拥有更高优先级；上游扩产缓解后，立讯则更有机会把制造能力转化为规模。

## 成功与失败路径

成功路径是：利用连接器、线缆、服务器与系统客户关系获取送样；依靠自动化降低模块制造和测试成本；通过800G和1.6T互操作取得正式资格；先成为中国或现有系统客户的第二供应商；再用连续两代产品和稳定良率进入全球头部客户。强AI需求给这一路径提供了客户多源化窗口。

失败路径是：产品长期停留在展示和小批量；核心器件供货或成本不具优势；客户资格推迟；良率、返工、售后和营运资本抵消低价；集团业务规模过大使管理层资源优先投向其他板块；或CPO等架构切换使当前产品窗口缩短。公司没有独立光模块收入和毛利率，也意味着投资者无法验证增长是否创造足够回报。

## 概率与财务含义

未来3年有意义进入概率55%—75%，5年70%—88%；中国客户50%—70%和65%—82%，全球头部客户20%—40%和35%—60%。该区间不是对全部产品统一赋值，而是对基准事件——可持续批量和足以影响行业定价的份额——进行判断。若只要求小批量，概率更高；若要求全球5%、多客户和连续两代，3年只有30%—50%。

立讯最可能先造成的是第二供应商和报价压力，而不是立即复制中际旭创、新易盛的高毛利。若客户资格、连续季度批量和收入分拆出现，龙头的2031年利润损失情景应从约8%—15%上移到约26%；只有低价、组合销售、全球份额和供给缓解共同发生，才进入约45%的极端损失。下一步最有价值的资料是客户侧资格、具体产品代际、重复订单、产线产能、良率和独立财务分拆。

还需要特别区分“立讯集团客户关系”与“光模块客户资格”。前者能降低送样和系统协同成本，后者仍需针对具体速率、形态、距离、固件和制造地点完成验证。只有后者转化为连续订单，才应进入份额与盈利测算；前者只能解释为什么立讯比普通新进入者更有机会。

综合来看，立讯已经跨过概念和样机门槛，但尚未跨过可由客户、收入和重复订单共同验证的规模门槛。当前最合理的结论不是“已经成为全球龙头”，也不是“只有展示没有能力”，而是把它视为产品真实、商业化概率较高、规模和利润仍需验证的新进入者。
""",
            ["luxshare_ar_2025", "luxshare_product_matrix", "luxshare_ofc_2025", "luxshare_ar_2024", "keysight_luxshare_ofc2024", "oif_luxshare_2024", "poet_luxshare_2024", "nvidia_connectx8_list", "xinqiang_supplier_ipo", "luxshare_ir_20260507", "luxshare_ir_20260525", "luxshare_patent_cpo", "luxshare_patent_sipho", "luxshare_siph_gov_project", "luxshare_ir_20251126"],
            120,
        ),
        _entity_section(
            "incumbent_profitability_risk",
            "中际旭创与新易盛：高景气、竞争压力和估值要求如何同时成立",
            f"""
## 当前经营基线

中际旭创和新易盛不是等待被动冲击的静态公司。中际旭创2025年收入382.40亿元、净利润107.97亿元、经营现金流108.96亿元，光模块毛利率42.61%；产能2806万只、产量2376万只、销量2109万只。{c('innolight_ar_2025')} 2026年一季度收入194.96亿元、净利润57.35亿元、综合毛利率约46.1%，公司4月又确认1.6T正在量产并逐步提升、订单充足。{c('innolight_q1_2026')} {c('innolight_ir_20260424')}

新易盛2025年收入248.42亿元、净利润95.32亿元、经营现金流77.01亿元，光模块毛利率47.81%；产能1747万只、产量1634万只、销量1603万只。{c('eoptolink_ar_2025')} 2026年一季度收入83.38亿元、净利润27.80亿元、毛利率约49.2%，但经营现金流仅6.84亿元，预付款、在建工程和购建长期资产支出上升。{c('eoptolink_q1_2026')} 这说明利润高增长与现金转换需要分别观察。

## 防御力来自哪里

两家龙头的主要壁垒是多代产品与头部客户共同开发、核心器件选择、光学耦合和测试良率、自动化量产、可靠性、固件与平台互操作，以及在供给紧张时获得关键器件的优先级。客户把新供应商从样机推进到正式资格和重复订单需要时间，制造地点变化也可能重走验证。{c('ethernet_alliance_qualification')} {c('fabrinet_qualification')}

产品迭代也在继续。中际旭创已推进1.6T并拥有大规模交付基线；新易盛发布XPO、12.8T液冷可插拔和多种1.6T路线，表明其可能在CPO和外置激光架构中继续参与，而不是被一次性替代。{c('eoptolink_xpo_2026')} NVIDIA当前CPO生态也同时保留中际旭创、新易盛等可插拔伙伴。{c('nvidia_cpo_pluggable_coexist')}

## 最危险的竞争组合

单个新玩家推出产品不会自动侵蚀长期利润。最危险的组合是：全球头部客户为了多源化给出正式资格；立讯或比亚迪获得稳定的DSP、激光器和硅光供给；专线和良率支持连续批量；低价或服务器、连接、液冷、电源组合销售使同代报价偏离正常降价；同时上游扩产和现有厂商扩产集中释放，需求增速回落；最后，龙头未能在1.6T、3.2T或CPO光引擎继续保持份额。

这个组合的领先指标不是新闻数量，而是全球客户重复订单、同代ASP、毛利率、份额、库存、应收、经营现金流和资本开支回报。中国客户局部进入对海外收入占比高的龙头影响较小；全球重要第二供应商才会把2031年净利润压低约四分之一；两家全球突破并压价的极端情景才接近45%。

## 现金流与估值

独立基线没有使用外部一致预期：中际旭创2026年收入800亿元、净利润236亿元，2031年净利润365亿元、自由现金流330亿元；新易盛2026年收入360亿元、净利润122亿元，2031年净利润177亿元、自由现金流156亿元。随后读取的市场聚合预测高出约40%—54%，说明当前价格更依赖2026年后三季度快速放量和更强长期路径。{c('innolight_market_snapshot_202607')} {c('eoptolink_market_snapshot_202607')}

以11%回报要求和3%长期增长计算，独立基线股权现金流价值约3399亿元和1594亿元；当前市值约13205亿元和7931亿元。差异巨大，但不能简单解释为“股票一定高估”，因为现金流模型对早期高成长和终值极敏感。正确用途是反推：市场需要更高的收入、利润率、现金转换或更低回报要求。竞争者进入会降低这些条件的安全边际，但不是唯一风险源。

新易盛风险区间略高，不是因为技术更弱，而是公司规模更小、市场预期更高且2026年一季度现金流与利润背离更明显。中际旭创规模、客户和现金流基线较强，但绝对市值同样要求长期高增长。两者都不应只看下一年市盈率；要同时看未来利润兑现、终值占比、客户份额和自由现金流。

## 条件化结论

当前经营证据支持“龙头仍强”，估值证据支持“市场隐含要求很高”，新进入者证据支持“立讯风险已经需要进入情景，比亚迪仍是尾部路径”。三者可以同时成立。若立讯获得全球重复订单且龙头同代价格和现金流恶化，应下调长期盈利；若新进入者停留小批量、需求继续超预期且龙头保持新架构份额，则市场可能过度担忧竞争。

进一步研究最需要的是按速率、客户和地区拆分的销量及ASP，核心器件供货份额，扩产后良率和利用率，库存与应收的客户结构，以及CPO各网络层的实际替代比例。没有这些资料时，报告保留宽情景，不把保守现金流价值直接当成目标价，也不把卖方高增长直接当成事实。

对两家公司还应分别校验正常降价与竞争压价。若混合ASP因1.6T占比提高而上升，同时同代800G价格下降，不能简单判定定价权增强或削弱。需要用产品组合、同代报价、毛利率和单位现金回报共同判断，才能避免把技术升级收益与竞争损失相互抵消后误读。
""",
            ["innolight_ar_2025", "innolight_q1_2026", "innolight_ir_20260424", "eoptolink_ar_2025", "eoptolink_q1_2026", "ethernet_alliance_qualification", "fabrinet_qualification", "eoptolink_xpo_2026", "nvidia_cpo_pluggable_coexist", "innolight_market_snapshot_202607", "eoptolink_market_snapshot_202607"],
            130,
        ),
    ]


def _sections_v2() -> list[dict[str, Any]]:
    c = _cite
    return [
        _section(
            "executive_summary_v2",
            "摘要",
            f"""
截至2026年7月22日，**立讯精密已经形成直接产品、工程互操作和中小客户小批量交付，但尚无公开证据证明其完成北美头部云服务商的规模商业化；比亚迪电子已进入AI服务器、液冷、电源和高速互联，却仍没有可核验的800G或1.6T数据中心光模块产品、客户资格、专属产线和收入闭环。** 立讯2025年8月明确说800G/1.6T主要交付中小型数据中心，尚未获得头部客户明确商务机会；2026年4月又披露2025年光模块收入约占0.1%，北美头部云客户仍在早期接洽，并否认“1000万只订单”。{c('luxshare_ir_20250828')} {c('luxshare_interactive_20260428')} 比亚迪电子2025年AI基础设施收入9.43亿元，但其年报和产品页没有800G/1.6T光模块，2026年IDCE官方回顾也未提及这类展品；该回顾并非完整展品目录。{c('byde_ar_2025')} {c('byde_product_page')} {c('byde_idce_2026')}

本报告把“有意义进入”限定为：在800G及以上AI数据中心光互联中，滚动12个月收入达到全球2%或中国客户体系5%，至少连续两个季度形成收入，并有正式客户资格、首个批量订单和相隔不少于90天的第二个商业订单；同时还要出现第二客户或下一代产品中的至少一项。3年和5年均为从2026年7月22日起计算的累计事件，分别截至2029年7月22日和2031年7月22日，较早发生的进入在较长期限仍记为已发生。按这个严格可复核的口径，中心判断和敏感性范围如下。括号内不是统计置信区间，而是改变产业状态、认证进度和证据可信度后的结果范围。

| 主体或事件 | 未来3年 | 未来5年 | 结论为什么不同 |
|---|---:|---:|---|
| 比亚迪电子形成有意义规模 | 17%（11%—25%） | 33%（22%—45%） | 有集团制造与AI基础设施协同，但直接产品、资格、专线和订单均未闭环。{c('byde_ar_2025')} {c('byde_product_page')} |
| 立讯精密形成有意义规模 | 63%（53%—75%） | 79%（68%—88%） | 产品、小批量、互操作真实；头部客户、重复订单、良率和收入规模仍缺证据。{c('luxshare_ar_2025')} {c('luxshare_interactive_20260428')} |
| 至少一家形成有意义规模 | 69%（57%—81%） | 85%（74%—93%） | 共享需求和上游供给使两家公司概率同向变化，不能当成独立事件 |
| 两家公司都形成有意义规模 | 12%（6%—20%） | 27%（16%—40%） | 比亚迪仍需跨越更多里程碑，压低两家同时兑现的概率 |
| 比亚迪进入中国 / 全球头部客户体系 | 15% / 8% | 28% / 16% | 中国客户协同更现实，全球资格还受产品、交付和供应链政策约束。{c('byd_ir_20260330')} |
| 立讯进入中国 / 全球头部客户体系 | 57% / 32% | 71% / 50% | 中小客户已有交付，但全球头部客户的公开商业闭环仍未出现。{c('luxshare_ir_20250828')} |

“中国客户体系”和“全球头部客户体系”都属于总进入事件的子集，但同一公司可能同时服务两类客户，所以不能直接相减。公开资料不足以判断交集，只能给出“仅中国”的可行范围：比亚迪约为3年7%—9%、5年12%—17%；立讯约为3年25%—31%、5年21%—29%。立讯5年下界低于3年，是因为全球进入概率随时间上升、与中国路径的重合可能扩大，并不表示中国业务倒退。

给定至少一家已经形成有意义规模，未来3年的中心分布是：温和竞争加剧62%、明显竞争恶化29%、严重结构性恶化9%；未来5年为53%、35%和12%。每个期限三项都合计100%。市场增长继续吸收新增供给时，3年分布变为70%/25%/5%；若上游产能集中释放且架构变化对现有模块厂不利，则变为55%/33%/12%。这说明，新增供应商最常见的结果是客户议价和第二供应商份额增加，不是龙头利润立即坍塌。

我们把“显著盈利受损”定义为2031年归母净利润或2026—2031年累计自由现金流至少一项较无新增进入者基线低20%。中心估计下，中际旭创和新易盛未来3年的显著受损概率均约26%，未来5年均约40%；敏感性范围分别为17%—36%和30%—51%。计算关系是“至少一家进入 × 进入后明显或严重竞争”，其中明显和严重两档已经把需求吸收、产品升级和现金转换能否抵消竞争压力计入，不再重复乘一个主观抵消系数。两个结果相同是因为当前公开数据不足以稳健区分两家公司跨过20%阈值的条件概率；两者在具体损失金额和现金流弹性上的差异仍保留在财务情景表中。

财务压力测试表明：如果两家公司主要停留在中国客户，2031年中际旭创和新易盛归母净利润分别约334亿元和162亿元，较无新增规模基线低8%—9%；若至少一家成为全球头部客户的重要第二供应商，降至273亿元和134亿元，约低25%；只有两家公司都完成全球突破、额外压价并且需求不能吸收供给时，才降至203亿元和100亿元，约低44%。因此，“明年市盈率下降也不能买”不是现阶段可以直接确认的结论。更准确的判断是：当前价格隐含的盈利要求很高，若全球客户复购、同代平均售价、毛利率和现金流同时恶化，长期竞争风险会被估值放大；若新进入者长期停留小批量，而龙头继续放量1.6T并进入新架构，市场也可能过度定价竞争恐惧。
""",
            ["luxshare_ir_20250828", "luxshare_interactive_20260428", "byde_ar_2025", "byde_product_page", "byde_idce_2026", "lightcounting_jan2026", "innolight_ar_2025", "eoptolink_ar_2025"],
            10,
        ),
        _section(
            "event_probability_method_v2",
            "事件定义与概率形成方法",
            f"""
本节回答两个问题：概率具体在算什么，以及为什么不是凭感觉报数。

份额分母采用800G及以上AI数据中心可插拔光模块、低功耗光学（LPO/LRO）模块和共封装光学（CPO）或近封装光学（NPO）光引擎的滚动12个月收入，排除传统电信相干、无源光网络、车载光通信和纯铜缆。全球事件要求达到2%收入份额，中国事件要求达到中国客户体系5%；严格口径提高到全球5%、至少两家正式客户和连续两代产品。这样可以避免把一次展会、一个产品页或一笔试单写成足以改变行业定价的进入。

由于公开市场没有一组同口径、足够大的历史新进入样本，本报告没有把少量案例包装成经验频率。我们先按商业阶段给出起始范围：多元制造企业尚无直接产品时，3年为5%—25%、5年为15%—45%；已有直接产品、小批量和部分客户验证时，3年为45%—80%、5年为60%—90%。这些范围参考了制造资格流程以及AOI、Jabil、鸿海等相邻案例，但属于未校准的专家判断。{c('fabrinet_qualification')} {c('aaoi_1p6t_order')} {c('jabil_1p6t_2025')} {c('foxconn_q1_2026')}

随后把证据放进九个商业里程碑。每一行都在模型底稿中绑定来源和评分理由；权重只表示该环节对最终商业化的重要性，不表示阶段顺序，也不是外部事实。由于不同产品和客户可以处于不同阶段，这张账本是跨产品成熟度检查，不能把某一代产品的小批量误写成全部产品已完成正式资格。立讯得分约66，主要来自直接产品、互操作、部分客户验证和小批量；比亚迪约7，主要来自尚未明确落到光模块的战略意愿和相邻团队线索。最终范围并非把分数机械换算成概率，而是在相应商业阶段的起始范围内，根据反证、证据滞后和共同产业状态收窄。

| 主体 | 当前最强里程碑 | 支持证据 | 直接反证 | 最终中心判断 |
|---|---|---|---|---:|
| 比亚迪电子 | AI基础设施和高速互联投入 | 服务器、液冷、电源、招聘和车载光通信邻近能力。{c('byde_ar_2025')} {c('byd_recruitment_2026')} {c('byd_patent_vehicle_1')} | 官方产品资料未提供800G/1.6T；网传800G专利属于苏州卓昱而非比亚迪。{c('byde_product_page')} {c('byd_wrong_patent_800g')} | 3年17%，5年33% |
| 立讯精密 | 中小客户小批量、部分验证和多厂商互操作 | 800G/1.6T产品、POET集成、Keysight和OIF互操作。{c('luxshare_ar_2025')} {c('poet_luxshare_2024')} {c('keysight_luxshare_ofc2024')} {c('oif_luxshare_2024')} | 2025年收入约0.1%，头部客户仍早期接洽；匿名POET订单不能归给立讯。{c('luxshare_interactive_20260428')} {c('poet_anonymous_order_boundary')} | 3年63%，5年79% |

联合概率使用三个共享产业状态：认证与器件约束偏强、产业条件中性、需求强且器件供给改善。在每个状态内分别估计两家公司进入概率，再计算同时进入，最后按状态权重加总。核心关系是：

**至少一家进入概率＝比亚迪进入概率＋立讯进入概率－两家公司同时进入概率。**

例如3年中心状态权重为30%/50%/20%，三个状态下比亚迪概率为8%/18%/30%，立讯为48%/65%/82%。中心值在给定共享状态后采用条件独立近似；共享状态本身已经让两家公司随需求、器件和认证窗口同向变化。加总后得到比亚迪17.4%、立讯63.3%、两家同时11.9%、至少一家68.8%。为检查状态内仍有共同客户或供应商这一遗漏，把“同时进入”从乘积向可行同向上界移动15%和30%后，3年两家同时进入升至12.7%和13.6%，至少一家降至68.0%和67.1%；5年分别由26.8%升至27.6%和28.5%。该移动比例只是依赖性敏感参数，不是相关系数。{c('lightcounting_apr2026')} {c('broadcom_sian3_20250325')} {c('coherent_capacity_2026')}

竞争程度也有明确结果阈值：在把需求吸收和龙头产品升级计入后，温和或可吸收表示2031年归母净利润和2026—2031年累计自由现金流均下降不足20%；明显表示至少一项下降20%—30%，且能由份额、同代额外降价、毛利率或现金转换中至少两项解释；严重表示至少一项下降30%以上且冲击持续两年以上。62%/29%/9%等条件分布仍是未校准专家判断，不是历史频率；它们依据需求是否吸收供给、器件是否释放、全球复购、同代价格和龙头新架构防御逐项改变。

区间的最大局限是权重没有经过足够历史样本校准，公开披露又可能落后于客户私有资格。为防止伪精确，公开结论取整数，并同时展示产业状态变化后的范围。任何新证据只更新它真正跨越的里程碑：招聘更新团队，样机更新产品，互操作更新工程成熟度，正式资格更新客户阶段，重复订单和跨代供货才更新有意义进入。
""",
            ["fabrinet_qualification", "aaoi_1p6t_order", "jabil_1p6t_2025", "foxconn_q1_2026", "byde_ar_2025", "byde_idce_2026", "byd_wrong_patent_800g", "luxshare_ar_2025", "luxshare_interactive_20260428", "poet_anonymous_order_boundary", "keysight_luxshare_ofc2024", "oif_luxshare_2024", "lightcounting_apr2026", "broadcom_sian3_20250325", "coherent_capacity_2026"],
            20,
        ),
        _section(
            "company_comparison_v2",
            "两家新进入者的真实进展",
            f"""
比亚迪和立讯不能被放在同一个“跨界巨头”标签下比较。比亚迪集团内最接近AI数据中心硬件的上市主体是比亚迪电子；比亚迪半导体的公开能力主要服务汽车电子和功率器件，车载光通信专利也不能跨主体、跨应用自动并入数据中心光模块。立讯的直接产品由Luxshare-Tech及相关合并主体承载，产品和工程证据已经明确，但仍需回到立讯精密合并报表判断收入和利润。

| 比较维度 | 比亚迪电子 | 立讯精密 | 对进入判断的影响 |
|---|---|---|---|
| 已确认业务 | AI服务器、液冷、电源、高速互联；2025年AI基础设施收入9.43亿元。{c('byde_ar_2025')} | 10G—1.6T光模块、AOC、DPO/LPO/LRO及硅光封装路线；2026年继续展示1.6T互连和12.8T液冷XPO光模块。{c('luxshare_ar_2025')} {c('luxshare_ofc_2026')} | 立讯已经跨过直接产品门槛，比亚迪仍处相邻业务到产品的迁移阶段 |
| 最高商业阶段 | 尚无可核验的数据中心高速光模块产品或客户资格。{c('byde_product_page')} | 800G/1.6T中小客户小批量，800G LRO部分客户验证。{c('luxshare_ir_20250828')} | 立讯的主要问题是规模和头部客户，比亚迪的主要问题仍是产品和主体 |
| 400G—3.2T | 官方资料没有可核验的直接产品矩阵。{c('byde_product_page')} | 400G和800G产品较完整，1.6T验证/小批量，3.2T NPO仍在研发。{c('luxshare_ar_2025')} | 不能把3.2T研发写成商业供给 |
| 核心器件 | 未披露DSP、激光器、硅光平台和FA/MT供应链。{c('byde_ar_2025')} | 与Broadcom、Marvell、POET等合作；公司更多承担模组、光学对准与测试。{c('luxshare_ir_20251126')} {c('poet_luxshare_2024')} | 立讯获得生态入口，也承担关键器件外购和供货优先级风险 |
| 工厂与良率 | 未找到可映射到高速光模块的专线、设备、良率或环评。{c('byde_ar_2025')} | 有中试、自动光耦和制造活动线索，但高端模块专属产能、良率和利用率未公开。{c('xinqiang_supplier_ipo')} | 两家公司都不能用集团总资本开支代替有效光模块产能 |
| 客户 | 宽泛的国际客户和AI基础设施客户不能映射为光模块客户。{c('byd_ir_20260330')} | 中小客户交付可确认；北美头部云客户仍早期接洽。{c('luxshare_interactive_20260428')} | 全球进入概率显著低于中国或一般市场概率 |
| 人才、专利与标准 | 集团招聘出现光通信方向，已找到的直接专利主要是车载光通信。{c('byd_recruitment_2026')} {c('byd_patent_vehicle_1')} | 美国招聘覆盖400G—1.6T认证；有硅光封装、CPO专利和OIF互操作。{c('luxshare_us_optical_recruitment')} {c('luxshare_patent_cpo')} {c('oif_luxshare_2024')} | 这些是领先指标和技术储备，不是订单或收入 |

比亚迪最重要的纠错是专利主体。市场文章引用的CN113514924A“800G光模块”申请人是苏州卓昱和亨通相关主体，不属于比亚迪。{c('byd_wrong_patent_800g')} 报告因此删除了“比亚迪已有直接800G专利”的概率输入；没有对应原始专利来源的其他主体说法也不再保留。

立讯最重要的纠错是商业化口径。2024年年报曾使用“头部客户测试”和“国际客户量产交付”的积极措辞，2025年8月却明确主要向中小客户交付，2026年4月又说尚未完成商业转化、北美头部客户仍早期接洽。{c('luxshare_ar_2024')} {c('luxshare_ir_20250828')} {c('luxshare_interactive_20260428')} 更稳妥的解释不是任选一句，而是区分不同SKU和客户：产品与中小客户交付成立，头部云客户规模复购没有公开闭环。

详细的产品、招聘、专利、产能和客户证据分别保留在两个研究对象页面；主报告只保留会改变跨公司概率的差异。
""",
            ["byde_ar_2025", "byde_history", "byd_wrong_patent_800g", "byd_recruitment_2026", "luxshare_ar_2025", "luxshare_ar_2024", "luxshare_ir_20250828", "luxshare_interactive_20260428", "luxshare_ir_20251126", "luxshare_us_optical_recruitment", "luxshare_patent_cpo", "oif_luxshare_2024", "luxshare_ofc_2026"],
            30,
        ),
        _section(
            "demand_supply_v2",
            "2026—2031年的需求、有效供给与价格压力",
            f"""
需求仍然很强，但不能用“GPU数量乘固定模块数”估算。NVIDIA B300参考架构在特定双平面配置下为每颗GPU提供两个400G计算网络端点；GB200 NVL72的机架内扩展互连却使用5000多根同轴铜缆；Meta又大量采用2×400G分支。{c('nvidia_b300_network_ra')} {c('nvidia_gb200_copper')} {c('meta_dsf_2025')} 因此需求模型采用：

**模块需求＝各类部署节点数 × 每节点网络端点数 × 光连接采用率 × 链路两端模块系数 ÷ 分支或双端口复用系数 ＋ 存储、汇聚和跨数据中心增量 － CPO替代的前面板可插拔数量。**

节点数和端点数可从参考架构获得；光连接比例、分支复用、网络超额配置和CPO替代率公开资料不足，只能用情景区间。LightCounting估计2026年AI集群以太网光学与CPO市场约260亿美元，800G继续快速增长、1.6T进入放量窗口，但该数字是行业预测，不是已完成订单。{c('lightcounting_jan2026')} {c('lightcounting_feb2026')}

为了让需求假设可以复算，模型只把2026年的260亿美元作为外部锚，2027—2031年则采用逐年放缓的独立情景，不冒充LightCounting的逐年预测。

| 年份 | AI集群光学市场情景 | 数据性质 | 主要判断 |
|---|---:|---|---|
| 2026 | 260亿美元 | 外部行业锚 | 800G继续扩张，1.6T进入放量窗口 |
| 2027 | 330亿美元 | 独立研究情景 | 1.6T成为增量主力，上游扩产开始释放 |
| 2028 | 390亿美元 | 独立研究情景 | 新进入者的量产、良率和复购开始可以验证 |
| 2029 | 450亿美元 | 独立研究情景 | 3.2T和CPO在部分网络层增加，增速开始回落 |
| 2030 | 500亿美元 | 独立研究情景 | 供给更加充分，同代价格和客户议价压力上升 |
| 2031 | 540亿美元 | 独立研究情景 | 可插拔、LPO/LRO、光引擎和CPO按网络层共存 |

**严重时效提醒：**GB200铜缆材料发布于2024年，只用于证明“机架内并非所有连接都采用光模块”这一架构反例，不能代表2026年的全部部署结构；当前需求判断同时使用B300、Meta分支架构和2026年市场资料更新。

供给端更不能把厂商总产能相加。有效供给的核心关系是：

**有效供给＝名义产能 × 客户资格覆盖率 × 可持续良率 × 关键器件到位率。**

| 厂商或平台 | 2026年公开可确认阶段 | 能否计入基准有效供给 | 主要限制 |
|---|---|---|---|
| 中际旭创 | 1.6T已量产并获得部分客户全年订单。{c('innolight_ir_20260424')} | 可以，属于强量产与订单证据 | 2800万只为全产品年化产能，不能当1.6T数量 |
| 新易盛 | 高速产品经营强、布局1.6T与XPO/NPO/CPO。{c('eoptolink_ar_2025')} {c('eoptolink_xpo_2026')} | 可以，但公开资料不足以拆1.6T件数 | 客户、代际销量和良率未披露 |
| AOI | 获得超过2亿美元1.6T批量订单，计划2026年第三季度开始发货。{c('aaoi_1p6t_order')} | 可从发货窗口起纳入，不应提前全年化 | 年末50万只/月是800G与1.6T合计能力目标 |
| 光迅科技 | 1.6T具备批量交付能力，3.2T NPO完成国内头部客户系统验证。{c('accelink_ir_20260514')} | 作为可交付候选，不能填精确份额 | 实际出货、客户、产能和良率未披露 |
| 华工正源 | 400G/800G/1.6T发货增长。{c('hgg_ir_2026q1')} | 只能定性纳入 | 各速率数量和客户不可得 |
| Ligent | 800G已量产；1.6T仍在送样，计划2026年下半年商业化。{c('ligent_hkex_20260305')} | 800G可以，1.6T仍按验证阶段 | 2716.9万只设计产能是全速率混合口径 |
| Jabil与鸿海 | 有1.6T产品、展会或准备量产证据。{c('jabil_1p6t_2025')} {c('foxconn_q1_2026')} | 只进入供给上行情景 | 缺模块订单、重复出货和专属产能 |
| 立讯精密 | 产品与中小客户小批量成立。{c('luxshare_ir_20250828')} | 以小批量纳入，不按头部客户规模纳入 | 2025年收入约0.1%，头部客户仍在接洽。{c('luxshare_interactive_20260428')} |
| 比亚迪电子 | 只有相邻业务和弱传闻。{c('byde_ar_2025')} {c('byd_weak_rumor_202607')} | 不计入基准有效供给 | 缺直接产品、客户资格、产线和订单 |

新增有效供给更可能在2026年下半年至2028年集中增加，而不是2026年初一步到位。AOI的订单交付、Ligent商业化、Tower硅光扩产、Coherent与Lumentum的InP和EML扩产都指向这个窗口。{c('aaoi_1p6t_order')} {c('ligent_hkex_20260305')} {c('tower_sipho_capacity_2026')} {c('coherent_capacity_2026')} {c('lumentum_eml_capacity_20260625')} TrendForce在2026年6月进一步估计EML与CW-DFB激光器合计月产能约5070万只、约为此前两倍。{c('trendforce_laser_capacity_202606')} 这个单位是激光器件，不是光模块，更不是已经通过客户资格的有效供给；它只说明瓶颈正在响应。当前紧缺保护龙头交付与议价，后续扩产又会为新进入者释放器件并增加价格压力，这两段方向相反，不能只取一边。

平均售价（ASP）同样分成正常技术降价和额外竞争压价。公开资料只有混合ASP，产品结构升级会让混合价格上升，即使同代产品在降价。{c('sourcephotonics_asp_mix')} 因此本报告没有把任何网传800G或1.6T单价写成事实。财务情景中的额外ASP压力是明确标注的压力参数；只有同规格、同距离、同客户的报价或龙头毛利桥出现后，才能把它升级为基准预测。
""",
            ["nvidia_b300_network_ra", "nvidia_gb200_copper", "meta_dsf_2025", "lightcounting_jan2026", "lightcounting_feb2026", "innolight_ir_20260424", "eoptolink_ar_2025", "aaoi_1p6t_order", "accelink_ir_20260514", "hgg_ir_2026q1", "ligent_hkex_20260305", "jabil_1p6t_2025", "foxconn_q1_2026", "luxshare_interactive_20260428", "byde_ar_2025", "tower_sipho_capacity_2026", "coherent_capacity_2026", "lumentum_eml_capacity_20260625", "trendforce_laser_capacity_202606", "sourcephotonics_asp_mix"],
            40,
        ),
        _section(
            "competition_mechanisms_v2",
            "新进入者为什么可能成功，也为什么可能失败",
            f"""
立讯和比亚迪真正可能改变竞争格局的路径，不是“会制造电子产品”，而是把系统客户、自动化和组合销售转成合格光学产品。成功路径需要五步连续成立：取得稳定DSP、激光器和硅光平台；把光学对准、耦合、固件、热和可靠性做成可重复良率；完成客户与制造地点资格；获得相隔至少90天的重复订单；用中国客户或中小客户的量产经验跨到全球头部客户和下一代产品。

立讯在这条路径上已经走到产品、小批量和工程互操作。POET确认真实光引擎集成，Keysight和OIF确认多厂商演示，美国招聘覆盖客户资格、可靠性和从工程验证到量产。{c('poet_luxshare_2024')} {c('keysight_luxshare_ofc2024')} {c('oif_luxshare_2024')} {c('luxshare_us_optical_recruitment')} 连接器、线缆、自动化和服务器客户关系可以降低导入成本；若客户希望增加第二供应商，立讯还有接受较低早期毛利的空间。比亚迪的优势更靠后：集团规模、服务器、液冷、电源和热管理可形成一站式方案，但它首先要证明光模块产品与团队本身存在。

**严重时效提醒：**POET、Keysight和OIF的上述材料均发布于2024年，只能证明当时已有工程集成和互操作能力，不能据此判断2026年的头部客户资格、量产良率或持续订单；当前商业阶段必须以2025年年报、2025年8月客户口径和2026年公司答复为准。

失败路径同样具体。第一，高速光模块的瓶颈是光学设计、耦合良率、可靠性、固件和持续交付，不是一般组装；制造资格常需要实验室、现场和制造地点多轮验证。{c('fabrinet_qualification')} 第二，核心DSP、EML、CW激光器、硅光和高端测试设备有供货优先级，新进入者即使有工厂也可能拿不到足够器件。Broadcom和Marvell虽提供两套1.6T DSP平台，但没有公开给任何新进入者的分配。{c('broadcom_sian3_20250325')} {c('marvell_ara_1p6t')} 第三，北美云客户还考虑供应链安全、地缘政策、制造地点和历史交付。第四，技术门槛在移动：中际已经量产1.6T，新易盛进入XPO、NPO和CPO路线；追上800G不代表能连续跨过1.6T和3.2T。{c('innolight_ir_20260424')} {c('eoptolink_xpo_2026')}

客户侧证据按“产品规划—样机—互操作—正式资格—小批量—重复订单—多客户多代”逐级处理。NVIDIA特定ConnectX-8支持清单没有列立讯800G光模块，只能约束该平台和版本，不能证明立讯在所有客户都未认证；同样，POET的匿名500万美元订单不能因为双方有合作就归给立讯。{c('nvidia_connectx8_list')} {c('poet_anonymous_order_boundary')} 这两种相反的归因错误都会扭曲概率。

低利润容忍度也不是无条件优势。新进入者为了取得第二供应商位置可以先用较低报价，但高端模块的返工、失效分析、现场支持、应收账款和备用产能会占用现金；关键器件又由外部平台供应，降价未必能由BOM成本同步消化。只有自动化真正改善耦合节拍和稳定良率，组合销售又能降低获客成本，低价才会成为可持续的份额工具。反过来，如果客户把第二供应商只作为价格谈判工具、订单长期停留在小批量，新进入者可能获得产品资格却无法获得足够资本回报。

现有证据更支持“需求增长与供应商扩散并存”。只有当上游紧缺缓解、新进入者完成全球客户复购、同代价格额外下降、龙头份额和毛利率持续下滑、现金转换同时恶化，行业才从温和多源化进入明显或严重恶化。任一环节缺失，都不应把极端财务情景当成基准。
""",
            ["poet_luxshare_2024", "keysight_luxshare_ofc2024", "oif_luxshare_2024", "luxshare_us_optical_recruitment", "fabrinet_qualification", "broadcom_sian3_20250325", "marvell_ara_1p6t", "innolight_ir_20260424", "eoptolink_xpo_2026", "nvidia_connectx8_list", "poet_anonymous_order_boundary", "lightcounting_apr2026"],
            50,
        ),
        _section(
            "entrant_group_financial_impact_v2",
            "立讯精密和比亚迪进入光模块后，对自身财务与产业链意味着什么",
            f"""
本节要回答的是：新业务即使进入成功，能否真正提高集团利润和资本回报？财务数据以两家上市公司2025年实际结果和Wind未来三年一致预期作为外部约束，项目收入不能直接等同上市公司归母利润：还要扣除早期低良率、核心器件采购、客户支持、专属资本开支、营运资金，以及非全资子公司的少数股东归属。立讯精密的潜在光模块业务在上市公司体系内直接归母；比亚迪的经营承载更可能在比亚迪电子，模型只把项目利润的65.76%计入比亚迪股份归母，集团合并收入仍按100%计入。

**立讯精密：短期先消耗利润和现金，长期才可能改善集团业务结构。** 在中国客户形成规模时，模型给出的2028年光模块收入、归母增量和项目自由现金流分别为60亿元、3亿元和-19亿元，2031年分别为180亿元、13.5亿元和-1亿元。成为全球重要第二供应商时，这三项在2028年为150亿元、12亿元和-34亿元，到2031年为500亿元、60亿元和28亿元；归母增量相当于2031年集团基线利润的14.3%。若以低价和组合销售扩张，2031年收入可达800亿元，归母增量却只比第二供应商路径多4亿元，自由现金流反而少12亿元。

立讯的关键不是收入能否做到几百亿元，而是净利率能否从导入期负值或接近零，提升到8%—12%，同时把新增收入约10%的营运资金和专属资本开支转成正现金流。低价组合销售能更快获得份额，却不一定比规模较小、利润率更高的全球第二供应商路径创造更多现金。短期上游受益者是DSP、激光器、硅光平台、光引擎、PCB、耦合和测试设备供应商；立讯自身要承担资格、返工、现场支持和备用产能。下游若把光模块与铜连接、服务器、液冷和电源一起验证，获客成本会下降，但客户也可能用整包采购压低单项利润率。{c('luxshare_ar_2025')} {c('luxshare_ir_20260525')} {c('poet_luxshare_2024')}

截至2026年7月22日，立讯市值4570亿元、PE TTM 26.55倍、PB 4.16倍，ROE TTM 19.37%、ROA TTM 6.35%，2025年权益乘数约2.95倍。{c('luxshare_market_snapshot_202607')} 立讯是资产和营运资金投入都重要的制造平台，PB—ROE可作有效参考。以2025年归母净资产849.21亿元为起点，代入本报告冻结的2026—2028年归母净利润210/260/310亿元、每年分配10%利润，简化权益桥得到期末净资产1551.21亿元和22.3%/22.5%/22.0%的ROE。当前4.16倍PB低于2021年以来月度PB中位数5.11倍，并处在约17.2%分位；这说明估值已有一定收缩，不代表历史中位数就是合理价值。{c('luxshare_pb_history_202607')} 光模块只有在利润率、资产周转和现金流高于集团新增资本成本时才改善PB支撑，低毛利配套收入反而可能拖累资本回报。

**比亚迪：战略协同可能真实，但对集团利润和估值的直接贡献更小。** 在中国客户形成规模时，模型给出的2028年光模块收入、比亚迪股份归母增量和项目自由现金流分别为20亿元、0.3亿元和-16亿元，2031年分别为120亿元、4.7亿元和-6亿元。成为全球重要第二供应商时，这三项在2028年为50亿元、1亿元和-33亿元，到2031年为300亿元、13.8亿元和-7亿元；归母增量只占2031年集团基线利润的1.8%。低价扩张即使把2031年收入推到500亿元，归母增量也只有16.4亿元，项目自由现金流仍约-22亿元。

比亚迪的模型净利率从导入期亏损逐步升至5%—7%，新增收入按12%占用营运资金；即使2031年收入达到300—500亿元，归属于比亚迪股份的利润增量也只有约14—16亿元。项目的意义更多在于把服务器、液冷、电源、高速连接和光模块形成组合，提高比亚迪电子在AI基础设施客户的项目深度，而不是改变比亚迪股份汽车、电池与海外业务主导的利润结构。若核心DSP、激光器和硅光平台仍外购，新增收入会先拉动上游，集团只捕获模组制造和系统集成利润；若没有客户复购，专属设备和库存反而压低项目回报。{c('byde_ar_2025')} {c('byd_ir_20260330')}

比亚迪当前市值8349亿元、PE TTM 30.31倍、PB 3.60倍，ROE TTM 11.02%、ROA TTM 3.71%，2025年权益乘数约3.42倍。{c('byd_market_snapshot_202607')} 比亚迪是重资产、强资本开支且对汽车价格周期敏感的制造企业，PB—ROE比单期PE更有参考意义，但不能脱离资产周转和现金流使用。以2025年归母净资产2462.75亿元为起点，代入本报告冻结的2026—2028年归母净利润400/480/560亿元、每年分配30%利润，简化权益桥得到期末净资产3470.75亿元和15.4%/16.5%/17.1%的ROE。当前3.60倍PB低于2021年以来月度PB中位数6.26倍，处在约2.2%分位；这只说明历史位置偏低，汽车价格、资本开支和自由现金流若继续承压，低分位仍可能合理。{c('byd_pb_history_202607')} 光模块成功只能小幅改善业务组合回报，不足以单独解释集团估值。

投资上，立讯的光模块进展具有改变集团利润结构的潜力，但需要全球客户、8%以上项目净利率和正自由现金流共同验证；比亚迪更适合作为低权重远期选择权观察，不应因为光模块传闻上调集团盈利。两家公司如果用低价进入，最先发生的可能是行业报价和上游采购变化，而不是自身归母利润立即增加。
""",
            [
                "luxshare_ar_2025", "luxshare_ir_20260525", "poet_luxshare_2024",
                "luxshare_market_snapshot_202607", "luxshare_pb_history_202607",
                "byde_ar_2025", "byd_ir_20260330",
                "byd_market_snapshot_202607", "byd_pb_history_202607",
            ],
            55,
        ),
        _section(
            "financial_model_v2",
            "中际旭创与新易盛的盈利、现金流和估值压力测试",
            f"""
财务模型先冻结独立预测，再读取外部一致预期。历史财务以公司年报和季报为最终口径，结构化快照用于复核；自由现金流统一按经营现金流减购建长期资产现金支出计算，归母净利润与集团总净利润严格分开。{c('innolight_market_snapshot_202607')} {c('eoptolink_market_snapshot_202607')} {c('innolight_ar_2025')} {c('innolight_q1_2026')} {c('eoptolink_ar_2025')} {c('eoptolink_q1_2026')}

本节要回答的问题是：比亚迪或立讯进入以后，竞争压力会怎样穿过收入、毛利率和现金流，并在什么条件下足以改变当前估值判断？

公开资料没有按800G、1.6T、3.2T及客户拆分的出货量、同代ASP、有效产能、良率和营运资本，无法支持完整产品量价模型。本报告因此采用财务桥接与条件压力测试：逐年列出收入、毛利率、净利率、现金转换率和资本开支假设，再检验竞争冲击如何传导；它不是完整三表预测，也不用于给出正式目标价。

下面分别列出两家公司的核心历史财务与未来三年独立预测，避免把不同规模和现金转换路径挤在一张表中。

**中际旭创历史财务与独立预测**

| 中际旭创历史与预测口径 | 营业收入（亿元） | 归母净利润（亿元） | 经营现金流（亿元） | 自由现金流（亿元） |
|---|---:|---:|---:|---:|
| 2023实际 | 107.18 | 21.74 | 18.97 | 1.93 |
| 2024实际 | 238.62 | 51.71 | 31.65 | 2.99 |
| 2025实际 | 382.40 | 107.97 | 108.96 | 81.36 |
| 2026年一季度实际 | 194.96 | 57.35 | 33.68 | 14.39 |
| 2026独立预测 | 800.00 | 236.00 | 224.20 | 179.20 |
| 2027独立预测 | 1000.00 | 288.00 | 279.36 | 233.36 |
| 2028独立预测 | 1180.00 | 330.40 | 323.79 | 277.79 |

**新易盛历史财务与独立预测**

| 新易盛历史与预测口径 | 营业收入（亿元） | 归母净利润（亿元） | 经营现金流（亿元） | 自由现金流（亿元） |
|---|---:|---:|---:|---:|
| 2023实际 | 30.98 | 6.88 | 12.46 | 6.92 |
| 2024实际 | 86.47 | 28.38 | 6.41 | -8.35 |
| 2025实际 | 248.42 | 95.32 | 77.01 | 63.81 |
| 2026年一季度实际 | 83.38 | 27.80 | 6.84 | 0.53 |
| 2026独立预测 | 360.00 | 122.40 | 104.04 | 79.04 |
| 2027独立预测 | 450.00 | 146.25 | 128.70 | 106.70 |
| 2028独立预测 | 530.00 | 164.30 | 149.51 | 130.51 |

核心传导不是直接给利润打折，而是：

**情景收入＝基线收入 ×（1－份额或销量损失）×（1－新进入者带来的额外ASP压力）×（1＋需求和产品组合缓冲）。**

**情景自由现金流＝情景净利润 ×（基线现金转换率－情景折损）－基线资本开支 × 扩产倍数。**

毛利率额外下降按75%的税后比例传到净利率。份额、额外ASP、毛利率、现金转换和资本开支参数都是压力测试假设，不是外部事实；公开资料不足以支持同速率、同客户的精确价格和份额预测。

模型使用的数值不是藏在公式后面。2031年六档情景的“份额或销量损失/额外ASP压力/需求与产品组合缓冲/毛利率额外下降/现金转换率折损/资本开支倍数”依次为：立讯形成规模时6%/4%/+1%/2.0个百分点/2.0个百分点/1.03倍；比亚迪形成规模时4%/3%/+1%/1.3个百分点/1.3个百分点/1.02倍；两家公司主要局限中国客户时3%/3%/+1%/1.2个百分点/1.5个百分点/1.02倍；至少一家成为全球重要第二供应商时10%/8%/+1%/3.5个百分点/4.0个百分点/1.05倍；两家公司全球突破并持续压价时18%/15%/+1%/7.0个百分点/8.0个百分点/1.10倍；光引擎和共封装加快时12%/8%/0%/3.2个百分点/5.0个百分点/1.08倍。中间年份按逐年路径递增，而不是到2031年一次跳变。

这些数值来自产品成熟度、客户范围、上游器件释放、龙头海外收入暴露和架构替代范围的联合压力判断，不是已发生事实。立讯已有产品与小批量，所以其单独形成规模的损失参数高于比亚迪；中国客户情景因两家龙头海外收入占比高而较轻；全球第二供应商和架构迁移才会同时打击份额、价格与现金转换。任何一项客户、同代报价或良率证据缺失，都不应把最严重一档移入基准。

单变量敏感性用于检查数量级：在2031年其他输入不变时，额外ASP每下降1%，中际旭创归母净利润约减少3.65亿元、新易盛约减少1.77亿元；毛利率每下降1个百分点并按75%税后传导，中际归母净利润约减少10.95亿元、新易盛约减少4.91亿元。若两项同时发生，影响接近相加但还会受收入基数联动；现金流还会受到转换率和资本开支的二次放大。这个敏感性说明，毛利率变化比单独1%的价格变化更能改变长期结论。

| 2031年条件情景 | 主体 | 收入（亿元） | 归母净利润（亿元） | 净利润较基线 | 当年自由现金流（亿元） | 2026—31累计自由现金流较基线 | 折现现金流比较值*（亿元） |
|---|---|---:|---:|---:|---:|---:|---:|
| 没有新增公司形成有意义规模 | 中际旭创 | 1460 | 365 | 0% | 330 | 0% | 3231 |
|  | 新易盛 | 655 | 177 | 0% | 156 | 0% | 1541 |
| 立讯形成规模，比亚迪仍处研发或区域供货 | 中际旭创 | 1331 | 313 | -14% | 270 | -9% | 2827 |
|  | 新易盛 | 597 | 152 | -14% | 129 | -9% | 1354 |
| 比亚迪形成规模，立讯影响有限 | 中际旭创 | 1373 | 330 | -10% | 290 | -6% | 2966 |
|  | 新易盛 | 616 | 160 | -9% | 138 | -6% | 1418 |
| 两家公司进入但主要局限于中国客户 | 中际旭创 | 1387 | 334 | -8% | 294 | -6% | 2988 |
|  | 新易盛 | 622 | 162 | -8% | 140 | -6% | 1429 |
| 至少一家成为全球头部客户的重要第二供应商 | 中际旭创 | 1221 | 273 | -25% | 226 | -17% | 2516 |
|  | 新易盛 | 548 | 134 | -25% | 109 | -16% | 1208 |
| 两家公司全球突破并用低价和组合方案抢份额 | 中际旭创 | 1028 | 203 | -44% | 148 | -30% | 1970 |
|  | 新易盛 | 461 | 100 | -43% | 74 | -29% | 953 |
| 光引擎和共封装加快，价值向平台与核心器件迁移 | 中际旭创 | 1182 | 267 | -27% | 216 | -18% | 2471 |
|  | 新易盛 | 530 | 130 | -26% | 104 | -17% | 1186 |

注：折现现金流比较值按2026年7月22日估值时点、11%股权回报要求、3%长期增长、15%长期可持续ROE和零净举债假设计算，并为长期增长保留20%的再投资率。缺少完整净现金、净举债、少数股东和三表桥，因此它只比较情景，不是目标市值。

截至2026年7月22日，中际旭创市值11830亿元、PE TTM 79.14倍、PB 34.16倍；新易盛市值7094亿元、PE TTM 66.05倍、PB 36.54倍。Wind FY1—FY3一致预期中，中际归母净利润为304/535/794亿元，新易盛为190/305/484亿元；按当前市值静态计算，对应市盈率分别降至39/22/15倍和37/23/15倍。独立预测到2028年分别只有330亿元和164亿元，差异集中在1.6T放量、有效产能、利润率和超高资产回报能维持多久，而不是数据源单位换算。{c('innolight_market_snapshot_202607')} {c('eoptolink_market_snapshot_202607')}

PB—ROE与PB—ROA在两家光模块龙头这里只承担诊断作用：当前高估值是否由可持续的资产回报和现金流支撑，而不是用历史PB直接生成目标价。中际旭创当前ROE TTM 42.01%、ROA TTM 33.44%，新易盛分别为52.70%和41.21%，2025年权益乘数都约1.43倍，高ROE主要来自高资产回报而不是高杠杆。{c('innolight_market_snapshot_202607')} {c('eoptolink_market_snapshot_202607')}

本报告使用已经冻结的独立利润而非一致预期重做简化权益桥。中际以2025年归母净资产297.65亿元为起点，代入2026—2028年净利润236/288/330亿元、每年分配10%利润，期末净资产约1066.61亿元，对应年度ROE约58.4%/45.0%/36.0%；新易盛以179.23亿元为起点，代入122/146/164亿元利润和相同分配率，期末净资产约568.88亿元，对应ROE约52.2%/41.2%/33.2%。2021年以来67个月末样本中，中际当前34.16倍PB位于约96.3%分位、历史中位数6.08倍；新易盛当前36.54倍位于约97.8%分位、中位数8.19倍。{c('innolight_pb_history_202607')} {c('eoptolink_pb_history_202607')} 结论不是把估值机械拉回中位数，而是当前价格要求超高ROE在净资产迅速扩大的同时仍能维持；全球客户份额、同代报价、毛利率和现金转换任何一项持续恶化，PB和盈利都可能同时收缩。未来总资产、ROA、负债结构和完整三表路径不足，因此这里不输出伪精确的未来ROA或正式PB目标。

估值方法因此分工明确：市盈率和反向市盈率解释市场需要什么归母净利润；PB—ROE/PB—ROA检验超额回报质量和杠杆来源；现金流模型因三表不完整降级为情景比较；企业价值倍数缺可审计净债务和少数股东预测而不作核心估值。没有把这些方法机械平均成一个目标价。

直接用今日市值除以2031年25/35/45倍市盈率，会得到中际473/338/263亿元、新易盛284/203/158亿元，但这种算法忽略了未来5.44年的时间价值，只能表示“维持今日名义市值”的利润，不能称为市场隐含要求。更完整的反推先用11%回报要求扣除2026—2031年显式自由现金流现值，再把剩余价值折算到2031年：中际在25/35/45倍下分别需要约757/541/421亿元归母净利润，新易盛需要约465/332/258亿元。若采用独立基线利润，2031年终端市盈率需要约52倍和66倍才能支持今日市值。这个结果不等于股票必然高估，但清楚说明当前价格依赖更高利润、更长增长期或更低回报要求；全球第二供应商和架构迁移会进一步压缩安全边际。
""",
            ["innolight_ar_2025", "innolight_q1_2026", "eoptolink_ar_2025", "eoptolink_q1_2026", "sourcephotonics_asp_mix", "innolight_market_snapshot_202607", "eoptolink_market_snapshot_202607", "innolight_pb_history_202607", "eoptolink_pb_history_202607"],
            60,
        ),
        _section(
            "monitoring_v2",
            "未来12—24个月怎样证实或证伪",
            f"""
后续监控只保留能够跨越商业里程碑或验证财务结果的信号。

监控方法是先把每条新信息映射到产品、资格、重复订单、有效供给、同代价格或结果端财务中的一个环节，再比较它是否跨过预先定义的阈值；没有跨过阈值就只更新证据，不自动修改概率和盈利。

| 观察问题 | 应看到的原始证据 | 多久检查 | 结论如何变化 |
|---|---|---|---|
| 比亚迪是否从相邻能力进入直接产品 | 官方规格书、可核验产品页、平台互操作或客户侧资格 | 每月及重大展会 | 首次跨过产品和互操作门槛才上调3年概率；招聘或专利不单独触发 |
| 立讯是否进入头部云客户 | 客户或平台支持清单、正式资格、相隔90天以上的重复订单、连续季度分拆收入 | 每季及重大事件 | 从中小客户小批量上调到全球重要第二供应商 |
| 新增供给是否真正释放 | AOI发货、Ligent商业化、光迅/华工数量、InP/EML/硅光扩产与良率 | 每季 | 同时提高可服务供给和额外价格压力；扩产延期则下调 |
| 龙头份额与价格是否恶化 | 同规格同距离报价、客户份额、800G/1.6T产品结构和毛利桥 | 每季 | 只有超过正常技术降价的部分计入竞争损失 |
| 现金流是否先于利润转弱 | 经营现金流/归母利润、库存、应收、预付款、资本开支和利用率 | 每季 | 连续两个季度偏离才把利润压力升级为终值下修 |
| CPO是否替代可插拔价值 | 从首批交换层扩到更多网络层、光引擎供应链、龙头是否进入同一生态 | 每月及平台发布 | 若龙头同步进入光引擎则是价值迁移；若被排除才是结构性损失 |

最关键的证实组合是：立讯或比亚迪获得全球头部客户正式资格并形成复购；专属产能和良率可验证；同代价格比正常降本路径更弱；中际或新易盛的份额、毛利率和现金流持续偏离。只有一项出现时，最多更新相应里程碑。

监控时必须保留时间和分母。客户资格要写清是哪一代产品、哪种形态和距离、直接供货还是经ODM/OEM间接供货；产能要区分全产品设计产能、高速产品能力、已完成资格的有效产能和实际出货；价格要比较同代、同距离和同客户，不能用1.6T占比提升后的混合ASP替代800G同代价格。现金流则至少观察两个连续季度，避免把备货或单季大额资本开支误判成永久恶化。

招聘、专利、展会和弱媒体仍有价值，但只负责发现早期变化。一个新岗位只能更新团队形成，一个专利只能更新技术方向，一次展会互通只能更新工程成熟度；它们都不能自动更新客户资格、市场份额或利润。相同措辞、数字和图片的转载应合并为一个线索簇。若公司正式材料与媒体冲突，先采用公司或客户原始资料，并把冲突保留到后续核验，而不是取两者平均。

供给端需要特别关注时间错位。设备订单、厂房建设和晶圆扩产通常领先有效供给数季到数年；客户订单也可能以完成资格为前提。AOI的1.6T订单预计从2026年第三季度开始交付，Ligent把1.6T商业化放在2026年下半年，Tower硅光满产启动延伸到2027年。{c('aaoi_1p6t_order')} {c('ligent_hkex_20260305')} {c('tower_sipho_capacity_2026')} 如果这些节点延期，2027年的竞争压力应下调；若三者同时兑现且龙头扩产也释放，价格和利用率压力会高于单一公司进入。

最关键的证伪组合是：立讯到2027年仍以中小客户和0.1%左右收入为主，比亚迪连续两轮财报和主要展会仍无直接产品；器件紧缺或资格延迟限制新增供给；中际与新易盛继续放量1.6T、进入新架构并保持现金转换。此时应下调进入后的严重竞争概率，而不是因为新闻数量增加维持高风险。
""",
            ["luxshare_interactive_20260428", "byde_idce_2026", "aaoi_1p6t_order", "ligent_hkex_20260305", "coherent_capacity_2026", "innolight_ir_20260424", "eoptolink_xpo_2026", "nvidia_cpo_202607", "nvidia_cpo_pluggable_coexist"],
            70,
        ),
        _section(
            "conclusion_boundary_v2",
            "综合结论与证据边界",
            f"""
根据当前证据，可以认为立讯在高速光模块上的真实进度明显领先比亚迪：它已经有产品、互操作、中小客户交付和供应商集成，未来3—5年形成有意义规模是基准风险；但把它写成已经完成北美头部云客户规模量产同样不成立。公司自己的最新答复显示收入仍小、头部客户仍处早期接洽。{c('luxshare_interactive_20260428')} 比亚迪拥有制造和AI基础设施协同选择权，未来5年的尾部风险不能忽略，但当前没有直接证据证明800G/1.6T产品、资格、专线和收入已经形成；官方展会回顾也没有为相关市场传闻提供旁证，但展会回顾并非完整展品目录，不能单凭缺项断言绝对不存在。{c('byde_idce_2026')} {c('byd_weak_rumor_202607')}

行业竞争会恶化，但更可能先表现为客户多源化、第二供应商份额和议价增强。2026年的强需求与器件短缺仍能吸收一部分新增供给；2026年下半年到2028年的客户资格完成和上游扩产叠加，才是更可信的压力窗口。3.2T和CPO不能简单看成现有模块厂的单向利空：它们会减少部分前面板可插拔模块，也会创造光引擎、外置激光、封装和新型可插拔价值，最终取决于龙头是否进入新生态。{c('nvidia_cpo_202607')} {c('nvidia_cpo_pluggable_coexist')}

对中际旭创和新易盛，2031年利润下降约8%—25%是比“立即腰斩”更可辩护的中间压力范围；约44%的极端损失需要两家公司全球突破、额外低价有效、上游供给释放、需求无法吸收、龙头产品防御不足和现金转换恶化同时成立。当前估值确实要求较强的未来利润，但报告没有足够三表和净现金数据给出正式目标价，也不会把现金流敏感值伪装成内在价值。

公开资料最大的缺口不是网页数量，而是客户私有资格、重复订单、同代ASP、高速产品专属产能与良率、关键器件分配，以及龙头按产品和客户拆分的份额和现金流。这些信息可能使公开研究低估真实进度；卖方转述、论坛和匿名产业链消息又可能高估进度。本报告保留一条重要但尚未验证的比亚迪量产传闻，只用于提高核验优先级，不进入概率账本或财务参数。

概率与财务结论需要分开理解。69%的“未来3年至少一家进入”只表示商业事件发生的可能性，不等于69%的收入损失；在事件已经发生的条件下，温和竞争仍是62%的中心结果。财务表也没有用69%给收入加权，而是逐一展示事件成立后的份额、价格、毛利率和现金流。只有投资者需要计算组合期望值时，才可以把两层结果相乘，而且必须保留没有进入、温和、明显和严重四种互斥状态。

时间上，2026年主要是需求强、器件紧和1.6T资格爬坡；2027—2028年是上游扩产、新进入者发货和客户多源化更可能重叠的阶段；2029—2031年才有足够时间观察3.2T、CPO与光引擎是否改变价值链。把这三段压成一个“未来五年竞争恶化”会掩盖短期盈利继续增长而终值风险上升的可能性。

最终判断是：**立讯构成未来3年的现实竞争变量，比亚迪主要构成未来5年的尾部变量；至少一家进入的概率高，但严重结构性恶化不是基准结果。真正改变投资判断的，不是新玩家出现，而是全球客户复购、额外降价和龙头结果端恶化是否形成同一条证据链。**

这也意味着研究结论可以被后续事实推翻：客户资格和复购会提高进入概率，同代价格、利润率与现金流则决定损失幅度；两类证据不能互相替代。
""",
            ["luxshare_interactive_20260428", "byde_idce_2026", "byd_weak_rumor_202607", "lightcounting_jan2026", "nvidia_cpo_202607", "nvidia_cpo_pluggable_coexist", "innolight_ar_2025", "eoptolink_ar_2025"],
            80,
        ),
    ]


def _entity_sections_v2() -> list[dict[str, Any]]:
    c = _cite
    return [
        _entity_section(
            "byd_entry_risk",
            "比亚迪电子：制造与系统协同尚未跨过光模块商业门槛",
            f"""
## 主体和当前阶段

本页要回答的问题是：比亚迪集团的相邻制造与光通信能力，是否已经转化为比亚迪电子可验证的数据中心高速光模块产品和商业收入？

比亚迪集团内最接近AI数据中心硬件的上市主体是比亚迪电子。2025年其AI基础设施收入9.43亿元，同比增长31.7%，产品集中在AI服务器、液冷、电源和高速互联。{c('byde_ar_2025')} 比亚迪半导体的公开定位是汽车电子和功率器件，不能把集团或汽车业务的能力直接记到比亚迪电子的数据中心光模块上。

截至2026年7月22日，公开资料不足以确认比亚迪电子已经形成800G、1.6T或3.2T数据中心光模块产品。2026年3月公司仍把电源和高速互联称为需要加快落地的新产品；当前产品页没有OSFP、QSFP-DD、LPO、LRO或CPO规格；IDCE官方回顾只列服务器、液冷和800V直流电源。{c('byd_ir_20260330')} {c('byde_product_page')} {c('byde_idce_2026')} 这里的800V是供电电压，不是800G传输速率。

## 招聘、专利、产线与客户

集团校园招聘出现光通信和光芯片光器件方向，说明相关人才需求存在；但公开页面没有用人主体、岗位ID、人数、地点、产品代际和客户项目，无法建立可信的扩招时间序列。{c('byd_recruitment_2026')} 经过公司招聘、公开职业资料、专利发明人和会议讲者反查，没有发现足以确认从中际、新易盛、光迅或国际光器件厂形成完整团队迁移的证据。

已找到的比亚迪直接光通信专利主要面向车辆网络。车辆可靠性和系统工程可能提供可迁移经验，却不能证明数据中心800G/1.6T的调制、封装、固件、互操作和客户质量体系。{c('byd_patent_vehicle_1')} 市场文章反复引用的CN113514924A“800G光模块”实际属于苏州卓昱和亨通相关主体，不属于比亚迪。{c('byd_wrong_patent_800g')} 因此本研究没有把它计入技术储备。

工厂、实验室、设备供应商、政府项目、招标和环评多方向检索后，仍未找到可以映射到比亚迪电子高速光模块的主动耦合、COB/COC、老化测试、FA/MT装配专线，也没有可核验的设计产能、良率和利用率。集团固定资产和资本开支覆盖大量业务，不能作为代理。客户侧同样没有产品代际、形态、距离和资格阶段清楚的记录；“国际客户”“AI客户”和“全球头部客户供应链”可能指服务器、电源、液冷或其他零件，不能擅自映射具体云客户。

本轮还反查了DSP、TIA、Driver、SerDes、EML、连续波激光器、VCSEL、硅光晶圆与光引擎、FA/MT、连接器、PCB、散热、主动耦合和测试设备。唯一可以确认的新增联系，是比亚迪股份持有VCSEL企业纵慧芯光1.121%股权；公告没有供货协议、产能预留或客户认证，因此只能说明产业接触，不能写成锁定激光器供应。{c('byd_vertilite_stake')} 对其他关键器件，没有找到比亚迪电子自研、自制、合资、收购或具名采购的闭环证据。上游清单的空白会同时降低产品成熟度和未来良率可见度。

标准和专利的方向也很一致。比亚迪参与的最新国家标准面向最高100Gbit/s车载光纤线束；另一件专利讨论车辆内部无源光网络和CPO、2.5D或3D光电集成。{c('byd_vehicle_optical_standard')} {c('byd_vehicle_cpo_patent')} 它们证明集团认真投入光通信和光电集成，不是“完全没有技术”；但车辆网络的距离、温度、协议、拓扑和认证体系与数据中心800G/1.6T不同。正确做法是把它们放在“可迁移基础”，而不是“直接产品”。

卖方材料多次转述800G量产准备、1.6T样品和月产能，但第一上海与招银国际很可能共享管理层沟通底层，只计一个证据组。后续公司年报、产品页和IDCE没有给出规格、客户、订单或收入闭环，因此这些材料只提高“内部项目可能存在”的判断，不提高到完成资格或规模出货。弱媒体在2026年7月重复同一批数字，也不能制造第二个独立来源。

若按合理时间线推演，比亚迪先要完成直接规格和核心器件选型，再做样机、互操作与可靠性，随后才是客户送样、正式资格、小批量和复购。即使集团资源投入很强，这些阶段仍受技术代际窗口约束；如果1.6T尚未完成时行业进入3.2T或CPO，项目可能被迫跨代重做。相反，若它能借中国AI服务器客户同步导入光模块，并用电源、液冷和高速连接进行联合验证，时间也可能非线性缩短。这正是5年概率明显高于3年、但全球概率仍较低的原因。

## 对比亚迪自身财务和产业链的影响

比亚迪2025年集团收入8039.65亿元、归母净利润326.19亿元。独立模型没有把光模块收入直接加到归母利润，而是先计算项目净利润，再按比亚迪股份对比亚迪电子65.76%的归属比例折算；新增收入还按12%占用营运资金，并单独扣除光耦、测试、老化和可靠性设备资本开支。{c('byd_market_snapshot_202607')} 因而“成为全球重要第二供应商”不是一开始就增厚利润：模型在2028年给出50亿元项目收入、5%项目净利率、1.64亿元项目利润和约0.99亿元比亚迪股份归母增量，但35亿元资本开支和新增营运资金使项目自由现金流约为-33亿元。

| 比亚迪光模块经营结果 | 2028年收入 | 2028年股份归母增量 | 2028年项目自由现金流 | 2031年收入 | 2031年股份归母增量 | 占2031年集团基线利润 | 2031年项目自由现金流 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 在中国客户形成规模 | 20亿元 | 0.3亿元 | -16亿元 | 120亿元 | 4.7亿元 | 0.6% | -6亿元 |
| 成为全球重要第二供应商 | 50亿元 | 1.0亿元 | -33亿元 | 300亿元 | 13.8亿元 | 1.8% | -7亿元 |
| 低价和组合销售快速扩张 | 80亿元 | 0.5亿元 | -56亿元 | 500亿元 | 16.4亿元 | 2.2% | -22亿元 |

这些数值不是外部预测，而是回答“多大规模才会影响集团”的条件测算。即使2031年收入达到300—500亿元，归母增量仍只有集团独立基线利润的约2%；低价扩张的收入更高，却因项目净利率较低、营运资金和扩产更重而产生更差现金流。短期真正受益的首先是DSP、激光器、硅光平台、光引擎、PCB、耦合与测试设备供应商；比亚迪自身要承担资格、返工、库存和备用产能。长期若服务器、液冷、电源、高速连接与光模块形成联合方案，项目可以提高比亚迪电子在AI基础设施客户中的份额，但仍不足以改变比亚迪股份由汽车、电池和海外业务主导的盈利结构。

截至2026年7月22日，比亚迪PB为3.60倍、ROE TTM为11.02%、ROA TTM为3.71%，2025年权益乘数约3.42倍。{c('byd_market_snapshot_202607')} 对这类重资产制造企业，PB—ROE是有效参考，但必须由资产周转、杠杆性质和自由现金流共同约束。以2025年归母净资产2462.75亿元为起点，代入冻结的2026—2028年归母净利润400/480/560亿元和30%分配率，简化权益桥得到期末净资产3470.75亿元，年度ROE约15.4%/16.5%/17.1%。当前PB位于2021年以来67个月末样本约2.2%分位，低于4.44倍的20%分位和6.26倍中位数。{c('byd_pb_history_202607')} 这提供了估值位置参照，但汽车价格竞争、资本开支和现金流若没有改善，不能据此直接判定低估。光模块只有形成高于集团资本成本的资产回报，才会小幅改善ROA与PB支撑；若只是低毛利配套收入，新增资产和营运资金会抵消增长。投资上不应因光模块传闻单独上调集团盈利或估值，至少要先看到正式规格、客户资格、重复订单和正项目自由现金流。

## 结论

比亚迪可能成功的原因是资金、大规模自动化、服务器和热管理协同，以及在中国客户体系内用组合方案导入第二供应商。可能失败的原因是没有直接产品和光学团队证据，关键器件分配与客户资格不能由一般制造能力替代，而且1.6T、3.2T和CPO门槛仍在移动。

中心判断为3年17%、5年33%；中国客户为15%和28%，全球头部客户为8%和16%。区间上沿承认保密和非线性投入，下沿反映公开产品、资格、产线与订单全都缺失。市场上关于800G月产、海外交付、1.6T验证和IDCE展示的传闻仍是重要但尚未验证的线索；官方展会回顾没有提供对应旁证，但也不是完整展品目录，因此该线索继续保留待核、不能进入当前概率或盈利模型。{c('byd_weak_rumor_202607')} {c('byde_idce_2026')}
""",
            ["byde_ar_2025", "byde_history", "byd_ir_20260330", "byde_product_page", "byde_idce_2026", "byd_recruitment_2026", "byd_patent_vehicle_1", "byd_wrong_patent_800g", "byd_vertilite_stake", "byd_vehicle_optical_standard", "byd_vehicle_cpo_patent", "byd_firstshanghai_202509", "byd_cmbi_202511", "byd_weak_rumor_202607", "byd_market_snapshot_202607", "byd_pb_history_202607"],
            110,
        ),
        _entity_section(
            "luxshare_entry_risk",
            "立讯精密：产品和中小客户交付已成立，头部客户规模复购仍待证明",
            f"""
## 产品与商业化时间线

本页要回答的问题是：立讯已经走到产品、客户资格和规模收入链条的哪一步，现有证据能否支持其进入全球头部云客户？概率估算沿用主报告的里程碑和共享产业状态方法，不根据网页数量加权。

立讯的高速光模块不是概念。官网和年报覆盖400G、800G、1.6T、AOC、DPO、LPO、LRO、硅光及CPO/NPO预研；2026年官方展会材料又增加1.6T互连和12.8T液冷XPO光模块。POET、Keysight和OIF分别从光引擎集成和互操作侧提供独立旁证。{c('luxshare_product_matrix')} {c('luxshare_ofc_2026')} {c('poet_luxshare_2024')} {c('keysight_luxshare_ofc2024')} {c('oif_luxshare_2024')}

真正需要拆开的是“量产”的客户口径。2025年8月公司称800G实现量产、1.6T处于验证，但同时明确两者主要向中小型数据中心客户交付，尚未获得头部客户明确商务机会。{c('luxshare_ir_20250828')} 2025年报把800G和1.6T写为小批量、800G LRO通过部分客户验证，3.2T NPO仍在研发。{c('luxshare_ar_2025')} 2026年4月公司进一步说光模块仍处导入早期、2025年收入约占0.1%、北美头部云客户仍早期接洽，并否认“1000万只订单”。{c('luxshare_interactive_20260428')} 因而当前最准确的阶段是：中小客户已有交付，头部云客户的正式资格、订单和复购未形成公开闭环。

## 器件、工厂、人才和专利

1.6T方案使用Marvell等外部数字信号处理器（DSP），POET参与部分光引擎，公司公开表述也把Broadcom、Marvell等核心器件厂放在价值链前端，立讯更多承担模组、光学对准和自动测试。{c('luxshare_ir_20251126')} {c('poet_luxshare_2024')} 这既是真实产品基础，也意味着关键器件所有权、供货优先级和利润捕获仍受外部平台约束。POET的500万美元匿名订单没有点名立讯，不能因双方合作而归入立讯收入。{c('poet_anonymous_order_boundary')}

产品层级需要进一步区分。400G产品和AOC的公开规格较完整；800G DPO已有产品、互操作和中小客户交付，可信度最高；800G LPO/LRO处于验证或导入；1.6T已经有样机、验证和小批量，但规模收入与具名客户不可确认；3.2T传统可插拔仍没有正式商业规格，年报只支持NPO研发；CPO、NPO与XPO有专利、标准参与和演示，尚无客户部署订单。这个矩阵说明立讯具备连续研发路线，但不能把每一行都写成同样的量产阶段。

供应商PCB文件能确认东莞讯滔是通信客户并存在800G/1.6T板级批量活动，但不能把终端客户或所有高速PCB收入逐笔映射给立讯。{c('xinqiang_supplier_ipo')} 公开资料支持中试、自动化光耦和精密制造能力，却仍没有800G/1.6T专属线数、有效产能、良率、利用率、返工率和老化设备清单。公司整体资本开支不能替代这些数据。

Milpitas首席光学工程师招聘覆盖400G/800G/1.6T、客户资格、从工程验证到量产、EML/DML/探测器/VCSEL/硅光、DSP/Driver/TIA和可靠性测试，说明美国工程与认证团队正在补强。{c('luxshare_us_optical_recruitment')} 招聘只证明组织意图，不证明客户授标或量产良率。专利方面，硅光外置激光、光发射组件和CPO结构形成连续技术资产；它们支持封装与热设计能力，不证明自制1.6T硅光芯片。{c('luxshare_patent_sipho')} {c('luxshare_patent_tx')} {c('luxshare_patent_cpo')}

经过官网招聘、LinkedIn、政府项目、供应商文件、专利发明人和会议资料交叉检索，没有找到可靠证据证明立讯从中际旭创、新易盛、光迅、Coherent或Lumentum整体挖入关键团队。现有岗位说明美国端客户工程和可靠性能力在建设，但无法形成招聘人数、首次和最后可见日期、薪酬与岗位去重后的完整时间序列。因此人才证据只更新团队和认证准备，不更新量产份额。

产能方面，政府与可持续发展材料支持东莞讯滔存在光模块中试和自研多轴光耦自动设备，证明自动化并非空白；但仍没有专属800G/1.6T线数、额定产能、真实良率、利用率、返修率、老化测试节拍或客户质量指标。年报和投资者交流中的整体资本开支覆盖连接器、线缆、汽车、消费电子和服务器，不能直接分配到光模块。缺少这些数字，使“低成本规模制造”仍是待验证优势，而不是财务模型里的确定利润率。

## 对立讯精密自身财务和产业链的影响

立讯精密2025年集团收入3323.44亿元、归母净利润166.00亿元。独立模型把光模块视为上市公司体系内的新项目：项目利润全额计入归母，但新增收入按10%占用营运资金，并另外扣除专属资本开支。{c('luxshare_market_snapshot_202607')} 在“全球重要第二供应商”情景中，2028年光模块收入150亿元、项目净利率8%、归母增量12亿元，相当于集团基线利润的3.9%；但35亿元资本开支和新增营运资金使当年项目自由现金流仍约为-34亿元。到2030年项目净利率达到11%、扩产下降后，自由现金流才转正。

| 立讯光模块经营结果 | 2028年收入 | 2028年归母增量 | 2028年项目自由现金流 | 2031年收入 | 2031年归母增量 | 占2031年集团基线利润 | 2031年项目自由现金流 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 在中国客户形成规模 | 60亿元 | 3亿元 | -19亿元 | 180亿元 | 13.5亿元 | 3.2% | -1亿元 |
| 成为全球重要第二供应商 | 150亿元 | 12亿元 | -34亿元 | 500亿元 | 60亿元 | 14.3% | 28亿元 |
| 低价和组合销售快速扩张 | 250亿元 | 15亿元 | -52亿元 | 800亿元 | 64亿元 | 15.2% | 16亿元 |

这组结果说明，立讯比比亚迪更可能让光模块成为集团利润结构中的重要增量，但“收入最大”并不等于“回报最好”。低价和组合销售路径到2031年收入比全球第二供应商路径高300亿元，归母利润只多4亿元，项目自由现金流反而低12亿元。上游DSP、激光器、硅光、光引擎、PCB、耦合和测试设备会在扩产期先受益；立讯只有在自动化改善良率、客户支持成本可控、产品跨代复购后，才会把制造规模转成ROA。下游客户可能通过服务器、铜连接、光模块和电源整包采购降低导入成本，也可能利用整包议价压低单项毛利。

截至2026年7月22日，立讯PB为4.16倍、ROE TTM为19.37%、ROA TTM为6.35%，2025年权益乘数约2.95倍。{c('luxshare_market_snapshot_202607')} 立讯的制造资产和营运资金会实质影响回报，因此PB—ROE可作有效参考。以2025年归母净资产849.21亿元为起点，代入冻结的2026—2028年归母净利润210/260/310亿元和10%分配率，简化权益桥得到期末净资产1551.21亿元，年度ROE约22.3%/22.5%/22.0%。当前4.16倍PB位于2021年以来67个月末样本约17.2%分位，略低于4.36倍的20%分位和5.11倍中位数。{c('luxshare_pb_history_202607')} 当前估值已经收缩，但复合业务、客户周期及约2.95倍权益乘数使历史分位不能直接转成目标PB。光模块只有在项目净利率稳定超过8%、资本开支回落且自由现金流转正时，才可能改善资产效率并提供新增估值支撑。投资上应把全球客户复购、独立收入和毛利率、专线良率及自由现金流转正作为共同触发条件。

## 客户和结论

客户证据最高只支持中小数据中心交付、部分客户验证和标准环境互操作。NVIDIA特定ConnectX-8清单没有列立讯800G光模块，只能作为该平台的反证；不能扩写为全球所有客户未通过。{c('nvidia_connectx8_list')} 同理，“国内外客户进展顺利”和“NPO有机会”没有客户名、数量或订单，只能证明项目推进。{c('luxshare_ir_20260420')}

立讯3年和5年形成有意义规模的中心概率为63%和79%，进入中国客户体系约57%和71%，进入全球头部客户约32%和50%。若出现具名平台资格、相隔90天以上的重复订单、连续季度收入、专属产能与良率以及下一代客户延续，全球概率应上调；若到2027年仍以中小客户和约0.1%收入为主，则应下调。
""",
            ["luxshare_product_matrix", "luxshare_ofc_2026", "poet_luxshare_2024", "keysight_luxshare_ofc2024", "oif_luxshare_2024", "luxshare_ir_20250828", "luxshare_ar_2025", "luxshare_interactive_20260428", "luxshare_ir_20251126", "poet_anonymous_order_boundary", "xinqiang_supplier_ipo", "luxshare_us_optical_recruitment", "luxshare_patent_sipho", "luxshare_patent_tx", "luxshare_patent_cpo", "nvidia_connectx8_list", "luxshare_ir_20260420", "luxshare_market_snapshot_202607", "luxshare_pb_history_202607"],
            120,
        ),
        _entity_section(
            "innolight_profitability_risk",
            "中际旭创：规模和现金流防御较强，但高估值放大长期竞争风险",
            f"""
## 当前经营基线与防御力

本页要回答的问题是：中际旭创现有规模、客户和现金流防御能吸收多大竞争冲击，什么条件会真正下修其长期盈利和估值？

中际旭创2025年收入382.40亿元、归母净利润107.97亿元、经营现金流108.96亿元，光模块毛利率42.61%；2026年第一季度收入194.96亿元、净利润57.35亿元，并确认1.6T量产逐步提升、部分客户订单覆盖全年。{c('innolight_ar_2025')} {c('innolight_q1_2026')} {c('innolight_ir_20260424')} 多代产品、头部客户联合开发、核心器件优先级、自动化良率和全球交付记录构成现实防御，因而新进入者有样机不等于中际立即丢失有效份额。

短期风险主要来自扩产与现金流。2026年第一季度购建长期资产支出约19.29亿元，若客户多源化恰好与上游供给释放和龙头扩产重叠，库存、应收、利用率和资本开支会比收入更早反映压力。中际2025年经营现金流接近净利润，起始缓冲强于新易盛，但相同相对冲击对应的绝对利润和现金损失更大。

## 不同竞争情景对中际旭创的影响

| 2031年条件情景 | 收入 | 归母净利润 | 相对基线利润 | 当年自由现金流 | 主要投资判断 |
|---|---:|---:|---:|---:|---|
| 无新增竞争冲击 | 1100亿元 | 365亿元 | 基线 | 330亿元 | 需要1.6T及后续产品持续放量 |
| 中国客户局部进入 | 1019亿元 | 334亿元 | -8% | 291亿元 | 海外份额较高，冲击仍可吸收 |
| 至少一家成为全球重要第二供应商 | 875亿元 | 273亿元 | -25% | 217亿元 | 份额、同代价格和毛利率同时承压 |
| 两家全球突破并持续压价 | 708亿元 | 203亿元 | -44% | 130亿元 | 只有客户复购、低价和供给缓解共同发生才成立 |

情景收入＝基线收入×（1－份额或销量损失）×（1－额外ASP压力）×（1＋需求和产品组合缓冲）。全球第二供应商情景在2031年使用14%份额/销量损失、8%额外ASP压力和0%缓冲，并另外下调3.0个百分点净利率、8个百分点现金转换率、把资本开支提高到基线的1.35倍；严重情景分别为22%、12%、-2%、5.5个百分点、14个百分点和1.75倍。参数是条件压力输入，不是已发生事实；必须由全球客户重复订单、同代报价、毛利率和现金流共同触发。

短期和长期还要分开。2026—2027年的主要矛盾是1.6T订单、关键器件分配与扩产兑现，强需求可以让中际旭创在新供应商出现时仍保持收入增长；此时竞争更可能体现在送样、客户议价和备用份额，而不是绝对收入下降。2028年以后，如果激光器、硅光和测试设备扩产缓解瓶颈，客户才更有条件把第二供应商从小批量推到稳定份额。模型因此让收入损失和额外降价逐年加深，没有把2031年的压力一次性前置到2026年。

上游变化对中际旭创并非单向不利。DSP、EML、连续波激光器和硅光产能紧张时，成熟客户关系和采购规模提高交付优先级；扩产后单位器件成本下降又可能改善毛利。但同一轮供给释放也会降低新进入者的物料门槛，因此必须比较成本下降带来的正贡献与报价竞争带来的负贡献。下游若继续增加每节点光端口、从800G升级1.6T，需求和产品组合可以抵消部分份额损失；若网络架构降低可插拔数量，新增价值又被交换芯片或光引擎平台拿走，防御就会变弱。{c('lightcounting_apr2026')} {c('nvidia_cpo_pluggable_coexist')}

证伪条件也应落到可观察结果。若立讯或比亚迪只停留在中小客户和小批量，而中际旭创的1.6T收入、同代毛利率、经营现金流和客户份额保持稳定，应把全球竞争情景下调；若新进入者出现相隔90天以上的全球客户复购，同时中际同代ASP偏离正常技术降价、库存应收上升且自由现金流连续两个季度弱于利润，则需要把局部竞争上调为长期盈利中枢风险。

## PB、ROE、ROA与估值结论

截至2026年7月22日，中际旭创市值约11830亿元、PE TTM 79.14倍、PB 34.16倍、ROE TTM 42.01%、ROA TTM 33.44%，2025年权益乘数约1.43倍。{c('innolight_market_snapshot_202607')} 高ROE主要来自资产回报而非高杠杆，但客户份额、产品代际和价格比账面资产更能解释公司价值，因此PB—ROE只作诊断。以2025年归母净资产297.65亿元为起点，代入已经冻结的2026—2028年归母净利润236/288/330亿元和10%分配率，简化权益桥得到期末净资产1066.61亿元，年度ROE约58.4%/45.0%/36.0%。当前34.16倍PB位于2021年以来67个月末样本约96.3%分位，显著高于6.08倍中位数和10.59倍的80%分位。{c('innolight_pb_history_202607')} 这不等于应把PB直接拉回历史中位数，而是说明当前估值要求高ROE、利润留存和现金转换在净资产快速扩张后仍然成立；未来ROA和负债路径数据不足，不能输出伪精确目标PB。

独立模型对利润和现金流更保守，11%回报要求下的折现现金流比较值明显低于当前市值，因此当前价格对增长持续时间、ROA和现金转换要求很高。投资上，未出现全球客户复购、同代价格额外下行以及经营现金流连续恶化前，不应把严重竞争情景当基准；一旦三者同时出现，即使未来一年PE下降，也可能代表长期盈利中枢被下修。CPO只有在中际未进入光引擎价值链且可插拔替代扩大时才构成净损失，当前NVIDIA生态仍保留其可插拔合作位置。{c('nvidia_cpo_pluggable_coexist')}
""",
            ["innolight_ar_2025", "innolight_q1_2026", "innolight_ir_20260424", "innolight_market_snapshot_202607", "innolight_pb_history_202607", "nvidia_cpo_pluggable_coexist", "sourcephotonics_asp_mix"],
            130,
        ),
        _entity_section(
            "eoptolink_profitability_risk",
            "新易盛：高利润率与新架构弹性并存，现金转换是更早的风险信号",
            f"""
## 当前经营基线与防御力

新易盛2025年收入248.42亿元、归母净利润95.32亿元、经营现金流77.01亿元，光模块毛利率47.81%；2026年第一季度收入83.38亿元、净利润27.80亿元、毛利率约49.2%。{c('eoptolink_ar_2025')} {c('eoptolink_q1_2026')} 公司在1.6T、XPO、NPO和CPO路线持续投入，说明架构变化既是替代风险，也可能是价值迁移机会。{c('eoptolink_xpo_2026')}

新易盛与中际旭创的风险结构不同。其光产品利润率更高、海外收入占比约96%，对全球客户份额和同代价格更敏感；2026年第一季度经营现金流只有6.84亿元，扣除资本开支后自由现金流约0.53亿元，预付款、在建工程和扩产使现金转换明显落后于利润。若竞争压力与扩产重叠，现金流可能先于净利润恶化。

## 不同竞争情景对新易盛的影响

计算方法是先冻结新易盛的收入、净利率、现金转换率和资本开支基线，再逐年代入份额或销量损失、额外ASP压力、净利率下调、现金转换折损与扩产倍数；这样可以把经营冲击与正常技术降价分开。

| 2031年条件情景 | 收入 | 归母净利润 | 相对基线利润 | 当年自由现金流 | 主要投资判断 |
|---|---:|---:|---:|---:|---|
| 无新增竞争冲击 | 515亿元 | 177亿元 | 基线 | 156亿元 | 需要高毛利和新架构份额延续 |
| 中国客户局部进入 | 477亿元 | 162亿元 | -8% | 137亿元 | 海外业务占比高，直接冲击有限 |
| 至少一家成为全球重要第二供应商 | 410亿元 | 134亿元 | -25% | 102亿元 | 全球份额和定价压力开始实质化 |
| 两家全球突破并持续压价 | 332亿元 | 100亿元 | -43% | 62亿元 | 现金转换与估值终值同时受压 |

模型沿用与中际相同的竞争参数，使差异只来自经营基线、利润率和现金转换，而不是人为给不同公司设置不同冲击。全球第二供应商情景在2031年使用14%份额/销量损失、8%额外ASP压力、3.0个百分点净利率下调、8个百分点现金转换率下调和1.35倍资本开支；严重情景分别为22%、12%、5.5个百分点、14个百分点和1.75倍。中国局部进入只使用4%份额损失和3%额外ASP压力，因此不会被夸大成全球盈利崩塌。

时间维度决定这些压力能否真正发生。2026—2027年，新易盛仍可能受益于1.6T放量和高速产品占比提高，混合ASP上升不代表同代产品没有降价；现阶段应把扩产现金占用与竞争压价分开。2028年以后，如果新进入者获得全球客户复购、上游器件释放、客户开始重新分配稳定份额，同代价格和利用率才更可能同时下行。模型按年度逐步增加损失，而不是把远期严重情景直接套在当期利润上。{c('sourcephotonics_asp_mix')}

上游和架构变化对新易盛也有双向作用。核心器件扩产可以降低采购成本并支持更高出货，却也帮助新玩家跨越供货门槛；CPO减少部分交换层的前面板可插拔需求，但XPO、NPO、光引擎、外置激光和液冷封装又可能形成新的价值位置。{c('eoptolink_xpo_2026')} 因而投资判断不应把“CPO放量”机械等同于新易盛收入损失，而要验证公司在新架构中的收入、毛利、客户资格和单位资本回报。

证伪条件同样需要结果闭环。若新易盛的经营现金流恢复、扩产利用率提高、1.6T及新架构收入继续增长，而立讯和比亚迪没有全球客户复购，严重竞争情景应明显下调。反之，若新进入者获得连续订单，新易盛同代ASP和毛利率额外下滑，预付款、库存、应收和资本开支继续快于收入，且这种组合持续两个季度，则现金流恶化不再只是扩产时点问题，而是长期回报下降的直接证据。

## PB、ROE、ROA与估值结论

截至2026年7月22日，新易盛市值约7094亿元、PE TTM 66.05倍、PB 36.54倍、ROE TTM 52.70%、ROA TTM 41.21%，2025年权益乘数约1.43倍。{c('eoptolink_market_snapshot_202607')} 高PB同样主要由资产回报而不是金融杠杆支撑，但公司处于高速产品放量和扩产期，PB—ROE只适合检查估值能否被净资产增长消化。以2025年归母净资产179.23亿元为起点，代入冻结的2026—2028年归母净利润122/146/164亿元和10%分配率，简化权益桥得到期末净资产568.88亿元，年度ROE约52.2%/41.2%/33.2%。当前36.54倍PB位于2021年以来67个月末样本约97.8%分位，高于8.19倍中位数和14.43倍的80%分位。{c('eoptolink_pb_history_202607')} 这要求利润和现金流在净资产扩张后继续兑现；不能把历史中位数直接当目标，也不能在缺少未来资产负债桥时硬外推ROA。

投资上需要把产品迭代和现金流放在一起判断。若XPO、NPO或CPO帮助新易盛保住客户价值，同时经营现金流恢复，架构变化未必降低终值；若全球新进入者复购成立、同代价格额外下行、预付款和资本开支继续高增，则高ROA和高PB会同时承压。相较只看净利润，连续两个季度的经营现金流、库存应收、扩产利用率和同代毛利率是更早、更可复核的风险信号。
""",
            ["eoptolink_ar_2025", "eoptolink_q1_2026", "eoptolink_xpo_2026", "eoptolink_market_snapshot_202607", "eoptolink_pb_history_202607", "sourcephotonics_asp_mix", "nvidia_cpo_pluggable_coexist"],
            140,
        ),
    ]


def build_pack() -> dict[str, Any]:
    intake_text = INTAKE_PATH.read_text(encoding="utf-8")
    intake = parse_markdown_intake_text(intake_text)
    research_question = str(intake["research_question"])
    model_hash = _sha256(MODEL_PATH)
    reconciliation_hash = _sha256(RECONCILIATION_PATH)
    model_script_hash = _sha256(ROOT / "tools" / "opportunity_lens" / "run13_financial_model.py")
    reconciliation_script_hash = _sha256(ROOT / "tools" / "opportunity_lens" / "run13_external_reconciliation.py")
    brief_hash = _sha256(RUN_DIR / "brief.json")

    builder = RunPackBuilder(
        slug="byd-luxshare-ai-optics-competition-risk-run13",
        display_title="比亚迪与立讯的光模块竞争风险",
        research_question=research_question,
        problem_statement="比亚迪集团（经营承载更可能在比亚迪电子）与立讯精密能否在未来3—5年成为高速光模块重要供应商，并实质削弱中际旭创、新易盛的长期盈利？",
        intake=intake,
        requested_by="user_run13_fresh_research",
        run_mode="c_hybrid",
        quality_profile="deep_research",
    )
    for source in SOURCES:
        builder.add_source(source)
    builder.data_points.extend(build_data_points())
    builder.claims.extend(build_claims())
    for entity in _entities():
        builder.add_entity(entity)
    builder.entity_sections.extend(_entity_sections_v2())
    builder.entity_investment_targets.extend(_targets())
    builder.sections.extend(_sections_v2())
    builder.search_plan.extend(_search_plan())
    builder.evidence_groups.update({str(item["ref"]): str(item["independence_key"]) for item in SOURCES})

    for skill_name in (
        "industry_supply_demand_modeling",
        "probability_scenario_modeling",
        "company_financial_modeling",
        "company_valuation_modeling",
    ):
        is_valuation = skill_name == "company_valuation_modeling"
        builder.modeling_records.append(
            {
                "skill_name": skill_name,
                "status": "completed",
                "input_artifact_hash": f"sha256:{brief_hash if skill_name in {'industry_supply_demand_modeling', 'probability_scenario_modeling'} else reconciliation_script_hash if is_valuation else model_script_hash}",
                "output_artifact_hash": f"sha256:{reconciliation_hash if is_valuation else model_hash}",
                "result_summary": "完成事件定义、供需与价格传导、独立盈利现金流、情景损失、估值诊断和外部对账。",
            }
        )
    builder.independent_model_freezes.append(
        {
            "model_ref": "Run13独立概率、经营与估值压力模型v4",
            "input_hash": f"sha256:{model_script_hash}",
            "output_hash": f"sha256:{model_hash}",
            "frozen_before_consensus": True,
            "frozen_at": "2026-07-23",
        }
    )
    builder.external_reconciliations.append(
        {
            "model_ref": "Run13独立概率、经营与估值压力模型v4",
            "benchmark_ref": "financial.db中的估值日行情、历史实际财务与FY1—FY3一致预期",
            "artifact_hash": f"sha256:{reconciliation_hash}",
            "status": "completed_with_gap",
            "summary": "独立预测先冻结，再与financial.db中的供应商数据逐项对账；外部预测没有反向覆盖独立模型，供应商原始记录也不复制进C轨数据库。",
        }
    )
    builder.supplement_requests.extend(
        [
            {
                "request_title": "比亚迪高速光模块产品、客户与产线原始资料",
                "request_detail": "需要官方规格、独立互操作、客户侧资格、专属设备与良率、批量订单或分拆收入中的至少两类原始资料。",
                "priority": "p0",
                "blocking_status": "limits_scoring",
                "review_status": "pending",
            },
            {
                "request_title": "立讯1.6T规模化与重复订单证明",
                "request_detail": "需要连续季度出货、客户数量、正式资格、产能良率、分拆收入或跨代重复订单。",
                "priority": "p1",
                "blocking_status": "non_blocking",
                "review_status": "pending",
            },
            {
                "request_title": "龙头按产品和客户拆分的价格、份额与现金流",
                "request_detail": "需要同代ASP、客户份额、产品结构、核心器件供货、库存应收和扩产回报，以验证竞争是否已经进入财务结果。",
                "priority": "p1",
                "blocking_status": "non_blocking",
                "review_status": "pending",
            },
        ]
    )
    pack = _exclude_dynamic_financial_records(
        builder.build(publication_mode="stage")
    )
    compiled_brief = json.loads((RUN_DIR / "brief.json").read_text(encoding="utf-8"))
    pack["prompt_requirements"] = [
        {
            "question": item["question"],
            "output_hint": "run_overview",
            "acceptance_criteria": item.get("acceptance_criteria")
            or "在公开正文中以证据、方法、分析和明确结论完整回答",
        }
        for item in compiled_brief.get("requirements", [])
    ]
    pack["open_search_statistics"] = {
        "source_count": len([
            item for item in SOURCES
            if str(item["ref"]) not in DYNAMIC_FINANCIAL_SOURCE_REFS
        ]),
        "independent_source_group_count": len({
            str(item["independence_key"]) for item in SOURCES
            if str(item["ref"]) not in DYNAMIC_FINANCIAL_SOURCE_REFS
        }),
        "parallel_data_point_count": len([
            item for item in builder.data_points
            if str(item.get("source_ref") or "") not in DYNAMIC_FINANCIAL_SOURCE_REFS
        ]),
        "weak_lead_count": 2,
        "weak_lead_group_count": 1,
        "same_origin_duplicate_count": 1,
        "unresolved_material_lead_count": 1,
        "unresolved_material_lead_disposition": "比亚迪2026年7月量产、海外交付和展会展示传闻保留为待核线索，不进入概率事实、评分或财务模型。",
    }
    report = validate_run_pack(pack, publication_mode="stage")
    report.raise_for_errors()
    return pack


def main() -> int:
    pack = build_pack()
    OUTPUT_PATH.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    validation = validate_run_pack(pack, publication_mode="stage")
    print(json.dumps({"output": str(OUTPUT_PATH), **validation.as_dict()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
