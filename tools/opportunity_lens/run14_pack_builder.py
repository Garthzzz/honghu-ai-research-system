from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from tools.opportunity_lens.intake_parser import parse_markdown_intake_text
from tools.opportunity_lens.run14_source_catalog import SOURCES, build_claims, build_data_points
from tools.opportunity_lens.run_pack_builder import RunPackBuilder
from tools.opportunity_lens.run_pack_contract import validate_run_pack


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = (
    ROOT
    / "opportunity_lens"
    / "research_outputs"
    / "20260724_huayou_nickel_cobalt_lithium_run14"
)
INTAKE_PATH = (
    ROOT
    / "opportunity_lens"
    / "intake_requests"
    / "Opportunity_Lens_用户研究请求_华友钴业与镍钴锂.md"
)
FINANCIAL_INPUT_PATH = OUTPUT_DIR / "independent_model_inputs.json"
FINANCIAL_OUTPUT_PATH = OUTPUT_DIR / "independent_model_output.json"
SUPPLY_INPUT_PATH = OUTPUT_DIR / "supply_demand_inputs.json"
SUPPLY_OUTPUT_PATH = OUTPUT_DIR / "supply_demand_output.json"
RECONCILIATION_PATH = OUTPUT_DIR / "external_reconciliation.json"
OUTPUT_PATH = OUTPUT_DIR / "run14_pack_stage.json"

SOURCE_BY_REF = {str(source["ref"]): source for source in SOURCES}
COMPANY_NAME = "华友钴业"
COMPANY_ROUTE = "/company/631"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _ev(ref: str) -> str:
    return f"source_ref:{ref}"


def _cite(ref: str) -> str:
    return f"^src:{_ev(ref)}"


def _link_company_mentions(body: str) -> str:
    """Link the first company mention in each prose paragraph."""
    blocks = re.split(r"(\n\s*\n)", body)
    linked: list[str] = []
    for block in blocks:
        stripped = block.lstrip()
        if (
            not stripped
            or stripped.startswith("#")
            or stripped.startswith("|")
            or stripped.startswith("```")
            or f"]({COMPANY_ROUTE})" in block
        ):
            linked.append(block)
            continue
        linked.append(
            re.sub(
                re.escape(COMPANY_NAME),
                f"[{COMPANY_NAME}]({COMPANY_ROUTE})",
                block,
                count=1,
            )
        )
    return "".join(linked)


def _section(
    key: str,
    title: str,
    body: str,
    refs: list[str],
    order: int,
) -> dict[str, Any]:
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


def _entity_section(
    key: str,
    title: str,
    body: str,
    refs: list[str],
    order: int,
) -> dict[str, Any]:
    row = _section(f"{key}_deep_research", title, body, refs, order)
    row["entity_key"] = key
    return row


def _factor(
    code: str,
    metric_name: str,
    score: float,
    coverage: float,
    confidence: float,
    value_summary: str,
    rationale: str,
    topic_analysis: str,
    analysis_points: list[str],
    refs: list[str],
) -> dict[str, Any]:
    information_points = []
    for index, ref in enumerate(refs, start=1):
        source = SOURCE_BY_REF[ref]
        excerpt = str(source.get("excerpt_zh") or source.get("excerpt") or "")
        information_points.append(
            {
                "evidence_ref": _ev(ref),
                "excerpt": excerpt,
                "interpretation": (
                    f"第{index}条证据由{source['publisher']}发布，"
                    f"用于约束“{metric_name}”：{excerpt}"
                ),
                "independence_key": source["independence_key"],
            }
        )
    return {
        "factor_code": code,
        "metric_name": metric_name,
        "unit": "分",
        "period": "截至2026-07-24，观察窗口为未来12—24个月及3—5年",
        "score_raw": score,
        "score_adjusted": score,
        "score_status": "complete",
        "coverage": coverage,
        "confidence": confidence,
        "score_rationale": rationale,
        "factor_value_summary": value_summary,
        "source_context_summary": (
            "评分以公司财报、监管或政府材料、国际机构数据、项目方披露和独立研究模型交叉约束；"
            "同一底层报告或转载只计一个独立证据组。"
        ),
        "factor_topic_analysis": topic_analysis,
        "theme_analysis_points": analysis_points,
        "evidence_ref_uri_list": [_ev(ref) for ref in refs],
        "information_points": information_points,
    }


def _research_point(
    ref: str,
    title: str,
    category: str,
    value_text: str,
    interpretation: str,
    research_use: str,
    order: int,
) -> dict[str, Any]:
    source = SOURCE_BY_REF[ref]
    excerpt = str(source.get("excerpt_zh") or source.get("excerpt") or "")
    return {
        "source_ref": ref,
        "data_point_title": title,
        "research_category": category,
        "metric": title,
        "period": "2025—2030",
        "as_of_date": "2026-07-24",
        "value_text": value_text,
        "unit": "研究数据点",
        "source_excerpt": excerpt,
        "source_excerpt_zh": excerpt,
        "source_context": f"该材料用于回答“{title}”的事实边界与方向。",
        "interpretation": interpretation,
        "research_use": research_use,
        "limitations": (
            "全球矿山产量、可出口有效供给、冶炼中间品和公司权益产量并非同一口径；"
            "本数据点只在其明确口径内使用。"
        ),
        "evidence_ref_uri": _ev(ref),
        "sort_order": order,
    }


def _theory_entity(
    key: str,
    canonical_name: str,
    display_name: str,
    description: str,
    question: str,
    literature_review: str,
    analysis: str,
    answer: str,
    conclusion: str,
    limitations: str,
    refs: list[str],
    points: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "key": key,
        "canonical_name": canonical_name,
        "display_name": display_name,
        "entity_type": "product_material",
        "taxonomy_level": "product_material",
        "description": description,
        "entity_research_mode": "theory_research",
        "external_ref_type": "opportunity_lens_entity",
        "maturation_status": "research_only",
        "readiness_score": 1.0,
        "readiness_reason": "已形成口径、来源、供需情景、反方和公司传导链，等待独立审稿。",
        "research_priority_label": "research_only_literature_review_complete",
        "source_count": len(refs),
        "independent_source_count": len(
            {SOURCE_BY_REF[ref]["independence_key"] for ref in refs}
        ),
        "candidate_reason": description,
        "evidence_ref_uri": _ev(refs[0]),
        "evidence_ref_uri_list": [_ev(ref) for ref in refs],
        "score_point": None,
        "score_grade": "unrated",
        "score_quality_label": "research_only",
        "score_band_low": None,
        "score_band_high": None,
        "coverage": 0.90,
        "confidence": 0.82,
        "factor_scores": [],
        "research_profile": {
            "entity_research_mode": "theory_research",
            "research_depth_status": "complete",
            "research_question": question,
            "research_scope": description,
            "methodology_note": (
                "先用USGS和IEA确定全球数量级，再用政府政策、公司项目和本地研报解释短期偏离；"
                "逐年供需路径是透明的研究情景，不伪装成官方预测。"
            ),
            "literature_review_markdown": literature_review,
            "data_collection_markdown": (
                "资料分别来自国际机构、矿业政策发布方、项目业主、华友钴业正式披露和本地行业报告；"
                "网页与研报两条链路分别检索，同源转载合并。"
            ),
            "analysis_markdown": analysis,
            "answer_markdown": answer,
            "conclusion_markdown": conclusion,
            "limitations_markdown": limitations,
            "evidence_ref_uri_list": [_ev(ref) for ref in refs],
        },
        "research_data_points": points,
    }


def _search_plan() -> list[dict[str, Any]]:
    axes = {
        "nickel_balance": "全球原生镍供需、印尼RKAB、HPAL/RKEF项目、成本曲线和电池/不锈钢需求",
        "cobalt_balance": "全球钴矿与有效出口供给、刚果（金）配额、印尼伴生钴和电池低钴化",
        "lithium_balance": "全球锂矿与锂盐供需、项目推迟和复产、LFP及储能需求、成本和价格",
        "huayou_segments": "华友钴业镍钴锂、前驱体、正极和贸易分部的收入、毛利、出货及内部交易",
        "huayou_projects": "华越、华飞、华科、Pomalaa、Sorowako、Arcadia、硫酸锂项目的产能、权益、并表与爬坡",
        "financial_cashflow": "华友钴业收入、归母利润、营运资金、资本开支、经营现金流、自由现金流和杠杆",
        "valuation_returns": "华友钴业PE/PB/EV-EBITDA、PB—ROE、PB—ROA、市场隐含利润和一致预期",
        "policy_esg": "印尼矿权与配额、刚果（金）出口政策、资源国本地化、环境许可与项目执行风险",
    }
    plan: list[dict[str, Any]] = []
    for key, topic in axes.items():
        plan.extend(
            [
                {
                    "axis_key": key,
                    "source_channel": "report",
                    "round": 1,
                    "query": f"本地研报与公司报告：{topic}",
                    "status": "completed",
                },
                {
                    "axis_key": key,
                    "source_channel": "web",
                    "round": 1,
                    "query": f"全球官方、政府、项目方和公司原始资料：{topic}",
                    "status": "completed",
                },
            ]
        )
    round_two = {
        "nickel_balance": "第一轮发现印尼配额总量仍在调整，补查政府原话、项目进度和宽松情景反证。",
        "cobalt_balance": "第一轮发现矿山产量与出口配额不可直接相减，补查有效供给口径、库存和配额执行。",
        "lithium_balance": "第一轮发现2025年仍宽松但中期项目响应可能不足，补查投产延后、复产和需求替代。",
        "huayou_projects": "第一轮发现名义产能、权益产能和并表收入容易混用，逐项目复核持股、完成时间与有效爬坡。",
        "financial_cashflow": "独立利润与外部预测有差异，复核归母、少数股东、营运资金、资本开支和项目投产时点。",
        "valuation_returns": "低PE与PB可能由周期高位利润或高杠杆造成，补做历史估值、多方法交叉与反向估值。",
        "policy_esg": "政策仍可能变化，补查否认、修订窗口和替代解释，避免把单一行政表态写成固定产量。",
    }
    for key, trigger in round_two.items():
        plan.append(
            {
                "axis_key": key,
                "source_channel": "web",
                "round": 2,
                "query": f"针对第一轮缺口补查原始来源、反证和替代解释：{axes[key]}",
                "gap_trigger": trigger,
                "status": "completed",
            }
        )
    return plan


def _entities() -> list[dict[str, Any]]:
    nickel_refs = [
        "w-usgs-mcs2026",
        "w-iea-critical-2026",
        "w-iea-outlook-2026",
        "w-indonesia-esdm",
        "w-indonesia-antara",
        "r-nickel-20260525",
        "r-nickel-20260718",
        "r-model-supply-demand",
        "w-vale-pomalaa",
    ]
    cobalt_refs = [
        "w-usgs-mcs2026",
        "w-iea-outlook-2026",
        "w-drc-quota",
        "w-iea-ev-2026",
        "r-cobalt-20260211",
        "r-cobalt-20260616",
        "r-model-supply-demand",
        "r-huayou-ar2025",
    ]
    lithium_refs = [
        "w-usgs-mcs2026",
        "w-iea-critical-2026",
        "w-iea-ev-2026",
        "r-lithium-20260614",
        "r-lithium-20260618",
        "r-model-supply-demand",
        "w-huayou-lithium",
        "w-huayou-arcadia",
        "w-sec-ewoyaa",
    ]
    company_refs = [
        "r-huayou-ar2025",
        "r-huayou-ar2024",
        "r-huayou-ar2023",
        "r-huayou-q12026",
        "w-vale-pomalaa",
        "w-vale-pomalaa-progress",
        "w-huayou-lithium",
        "w-huayou-precursor",
        "w-sec-ewoyaa",
        "r-model-financial",
        "r-model-supply-demand",
        "r-huachuang-20260515",
        "r-boc-20260430",
        "r-csc-20260525",
        "r-citi-20260721",
    ]

    nickel_points = [
        _research_point("w-usgs-mcs2026", "全球镍矿供应锚", "供给", "2025年约390万吨镍金属量", "印尼已经占全球矿山供给约三分之二，政策变化会放大短期价格弹性。", "校验全球供给数量级和印尼集中度。", 1),
        _research_point("w-usgs-mcs2026", "印尼镍矿供应锚", "地域集中", "2025年约260万吨镍金属量", "全球供给高度集中并不自动等于永久短缺；需要同时看配额和项目爬坡。", "进入政策与供给集中风险判断。", 2),
        _research_point("w-indonesia-esdm", "印尼RKAB仍可调整", "政策", "2026年总量尚未最终固定", "政府表态支持配额约束，但留有调整窗口。", "限制紧张情景的确定性。", 3),
        _research_point("w-indonesia-antara", "印尼配额目标区间", "政策", "公开表态约2.5—2.6亿湿吨矿石", "矿石湿吨不能直接与镍金属量相加，但能约束本地冶炼原料。", "解释镍价短期政策敏感度。", 4),
        _research_point("w-iea-outlook-2026", "中期镍需求方向", "需求", "至2040年需求增幅约50%—90%", "能源转型继续提供增量，但LFP会压低单位电池镍需求。", "设定需求情景而非直接套入公司收入。", 5),
        _research_point("r-nickel-20260525", "印尼项目与成本曲线", "成本", "行业报告显示低成本新增供给仍集中于印尼", "镍价反弹会激活高成本供给，限制长期极端价格。", "约束宽松和紧张两侧价格路径。", 6),
        _research_point("w-vale-pomalaa", "Pomalaa项目规模", "项目", "名义12万吨镍/年HPAL", "名义产能只有在投产、爬坡和权益归属后才能进入公司模型。", "连接行业供给与华友项目。", 7),
        _research_point("w-vale-pomalaa-progress", "Pomalaa建设进度", "项目执行", "2026年项目仍处建设阶段", "项目不能在2026年按满产计入有效供给。", "决定华友基准模型从2027年开始爬坡。", 8),
        _research_point("r-model-supply-demand", "镍供需基准余额", "模型", "2030年约宽松8万吨", "基准情景接近平衡，政策与项目兑现足以改变方向。", "用于价格和公司毛利的条件分析。", 9),
    ]
    cobalt_points = [
        _research_point("w-usgs-mcs2026", "全球钴矿供应锚", "供给", "2025年约31万吨钴", "矿山产量是资源端锚，不等于当年可出口有效供给。", "防止把不同供给口径直接相减。", 1),
        _research_point("w-usgs-mcs2026", "刚果（金）供应集中度", "地域集中", "2025年约23万吨钴", "供应高度集中使出口政策对短期价格的影响大于矿山需求小幅变化。", "进入政策冲击分析。", 2),
        _research_point("w-usgs-mcs2026", "印尼伴生钴增量", "替代供给", "2025年约4.4万吨钴", "印尼HPAL在中期提供替代供给，但也受镍项目节奏和副产品经济性影响。", "约束长期极端短缺。", 3),
        _research_point("w-drc-quota", "刚果（金）出口配额", "政策", "2026年配额约9.66万吨", "配额约束有效出口流量，不能与矿山产量按同一年度直接比较。", "设定2026—2027有效供应。", 4),
        _research_point("w-iea-outlook-2026", "中期钴缺口风险", "供需", "2035年配额情景缺口可能超过需求25%", "政策持续将使结构性缺口扩大，但情景对配额延续高度敏感。", "提供紧张情景上界。", 5),
        _research_point("w-iea-ev-2026", "电池化学体系替代", "需求结构", "LFP已占电动车电池过半并主导储能", "低钴和无钴体系削弱钴需求弹性，是供给政策的主要反方。", "限制钴价和公司利润外推。", 6),
        _research_point("r-cobalt-20260616", "库存和配额执行", "短期市场", "行业报告强调有效流量与库存释放", "价格不能只由配额名义数量解释。", "校验短期供需路径。", 7),
        _research_point("r-model-supply-demand", "钴供需基准余额", "模型", "2030年约缺口0.6万吨", "基准情景先紧后缓，长期不是单边短缺假设。", "连接钴价与华友钴分部毛利。", 8),
    ]
    lithium_points = [
        _research_point("w-usgs-mcs2026", "全球锂矿供应锚", "供给", "2025年约29万吨锂金属量", "按5.323换算仅用于碳酸锂当量数量级校验。", "校验行业模型起点。", 1),
        _research_point("w-usgs-mcs2026", "全球锂消费锚", "需求", "2025年约26.3万吨锂金属量", "2025年供给仍高于消费，不能把中期需求增长倒推为当期短缺。", "确定2026年仍偏宽松。", 2),
        _research_point("w-usgs-mcs2026", "锂用途结构", "需求结构", "电池约占锂消费88%", "电动车和储能决定中期需求，消费电子不是主要增量。", "构造需求增速。", 3),
        _research_point("w-iea-critical-2026", "中长期锂需求", "需求", "至2040年需求超过三倍", "锂是三种金属中需求斜率最高者，但价格仍取决于项目响应。", "提供中长期需求方向。", 4),
        _research_point("r-lithium-20260614", "锂项目响应与价格", "供给弹性", "低价推动项目延期或减产", "项目延后会让宽松市场更快转向平衡，但高价也会促使复产。", "建立双向供给弹性。", 5),
        _research_point("w-huayou-arcadia", "Arcadia资源与建设起点", "公司资源", "公司披露津巴布韦锂资源与项目建设", "资源量不等于可售锂盐，仍需采选、转化和爬坡。", "连接资源与华友锂分部。", 6),
        _research_point("w-huayou-lithium", "硫酸锂项目进展", "公司项目", "5万吨级硫酸锂项目已完成并首批发运", "项目进入商业验证，但完整利用率和成本曲线仍需财报确认。", "决定锂分部收入从2026年起增加。", 7),
        _research_point("w-sec-ewoyaa", "Ewoyaa交易状态", "项目边界", "拟议交易仍待交割", "未完成交易不能进入基准产量和资产价值。", "排除计划项目的提前计入。", 8),
        _research_point("r-model-supply-demand", "锂供需基准余额", "模型", "2030年约缺口40万吨碳酸锂当量", "该结果对项目延后和需求增速敏感，只作为中期条件情景。", "用于锂价与公司锂业务压力测试。", 9),
    ]

    return [
        _theory_entity(
            "nickel_market",
            "全球镍供需与华友传导",
            "全球镍供需",
            "研究全球原生镍的矿山、冶炼、政策、成本、需求与2026—2030年有效供需，不把矿石湿吨、MHP实物吨和镍金属量混用。",
            "未来3—5年全球镍供需、政策和成本如何变化，并怎样传导到华友钴业？",
            "USGS提供全球矿山供给和价格锚，IEA提供能源转型需求方向，印尼政府和官方通讯社用于核验RKAB政策，Vale项目材料与本地行业报告补足HPAL项目和成本曲线。资料共同说明：印尼供给集中是真实约束，但配额仍有调整窗口，长期需求又受到LFP替代和不锈钢周期影响。",
            "模型把供给与需求统一换算为千吨镍金属量，余额等于有效供应减需求。2026—2030年基准供给从390万吨增至462万吨，需求从380万吨增至454万吨；紧张情景假设印尼配额和项目许可持续约束，宽松情景假设HPAL/RKEF更快投产且电池级镍需求偏弱。三条路径不是价格预测，而是识别哪些条件会把市场从小幅宽松推向缺口。",
            "基准判断是未来3—5年镍大体接近平衡、短期受印尼政策驱动而波动，2030年约有8万吨小幅宽松。对华友而言，镍价适度回升和HPAL稳定爬坡最有利；极端高价会提高矿石和酸等成本，极端低价则压缩产品价差。Pomalaa只能在2027年以后按有效爬坡进入模型。",
            "镍不是确定性短缺资产。真正需要跟踪的是印尼年度配额、矿石品位和价格、硫酸与能源成本、HPAL投产率以及LFP/高镍三元份额。华友的优势来自低成本湿法、规模和伴生钴，不来自对镍价单向上涨的押注。",
            "公开资料无法统一获得每个印尼项目的真实良率、矿石品位、酸耗和现金成本；供需路径因此保留较宽情景，不能用于精确点价。",
            nickel_refs,
            nickel_points,
        ),
        _theory_entity(
            "cobalt_market",
            "全球钴供需与华友传导",
            "全球钴供需",
            "研究全球钴矿山、出口有效供给、库存、刚果（金）配额、印尼伴生钴和低钴化需求，不把矿山产量等同于可交易流量。",
            "未来3—5年全球钴供需和政策如何变化，华友钴业能否持续受益？",
            "USGS给出2025年31万吨全球矿山供应、刚果（金）23万吨和印尼4.4万吨；IEA与刚果（金）配额政策说明有效出口流量可能显著低于矿山产量；电动车展望和行业报告则提供LFP、低钴化、库存及印尼伴生钴反证。资料之间不是简单相加关系。",
            "模型先把矿山产量和出口有效供给分层，再按千吨钴金属量计算市场余额。基准情景中2026—2027年配额造成有效供给偏紧，2028年后假设配额部分放松、印尼伴生钴增长，缺口逐步收窄；紧张情景保持严格配额，宽松情景叠加库存释放、配额放松和低钴化。",
            "钴是三种金属中政策弹性最大的：基准情景2026年缺口约1.5万吨，2030年仍小幅缺口0.6万吨；但宽松情景会重新转为过剩。华友钴产品2025年毛利率高，短期受益于流量收紧；长期利润不能按峰值钴价外推，因为LFP和低钴化会降低单位需求，印尼伴生钴也会增加替代供给。",
            "对华友最有利的是配额有序、价格高于成本但不过度刺激替代；最不利的是配额突然放松叠加库存释放。公司应按钴产品销量、贸易库存、采购与销售定价时差以及毛利率验证盈利，而不是只看现货价格。",
            "刚果（金）配额执行、库存位置和贸易流量公开透明度有限；模型不把9.66万吨配额直接与23万吨矿山产量相减，也不输出伪精确价格。",
            cobalt_refs,
            cobalt_points,
        ),
        _theory_entity(
            "lithium_market",
            "全球锂供需与华友传导",
            "全球锂供需",
            "研究全球锂矿、锂盐、项目响应、电动车与储能需求、成本曲线及2026—2030年平衡，并区分锂金属量与碳酸锂当量。",
            "未来3—5年全球锂供需、价格和项目兑现怎样变化，华友钴业的锂业务处于什么阶段？",
            "USGS提供2025年矿山供应、消费、用途和价格锚，IEA提供长期电池需求方向，本地锂行业报告补充项目延期与复产弹性，华友和SEC材料用于核验Arcadia、硫酸锂及Ewoyaa交易边界。资料共同指向“短期仍宽松、中期取决于项目响应”的非单边路径。",
            "模型统一使用千吨碳酸锂当量，历史USGS锂金属量按5.323换算只做数量级校验。基准情景2026年供给225万吨、需求216万吨，仍有9万吨宽松；2027年以后需求增长和项目延后使余额转负。紧张与宽松情景分别改变项目投产、复产和需求斜率。",
            "锂的中期需求弹性最强，但2025年供应仍高于消费，不能把2030年潜在缺口写成2026年已短缺。华友的Arcadia资源与5万吨级硫酸锂项目提供产业链基础，2026年开始增加收入较合理；完整利用率、回收率、运输和转化成本尚未公开，不宜直接假设高利润率。Ewoyaa未交割，不进入基准模型。",
            "基准路径到2030年出现约40万吨碳酸锂当量缺口，是对项目延后和需求增长的条件估算，不是价格保证。投资上更关键的是华友锂产品销量、单位成本、项目利用率和自由现金流，而不是只看资源量或锂价方向。",
            "全球项目清单和真实成本曲线难以完全公开，模型对2028年以后高度敏感；高价会推动复产，低价会推迟项目，因此长期缺口不能线性外推。",
            lithium_refs,
            lithium_points,
        ),
        {
            "key": "huayou_integrated",
            "canonical_name": "华友钴业镍钴锂一体化经营与估值",
            "display_name": "华友钴业经营与估值",
            "entity_type": "company",
            "taxonomy_level": "company",
            "description": "研究华友钴业镍钴锂资源、冶炼中间品、前驱体和正极材料的项目、分部、归母利润、现金流、资本回报和估值。",
            "entity_research_mode": "market_linked",
            "score_point": 69,
            "score_band_low": 58,
            "score_band_high": 78,
            "coverage": 0.93,
            "confidence": 0.82,
            "evidence_ref_uri_list": [_ev(ref) for ref in company_refs],
            "factor_scores": [
                _factor(
                    "company.exposure_directness",
                    "镍钴锂及材料业务的直接经营暴露",
                    86,
                    0.98,
                    0.95,
                    "2025年财报直接披露镍、钴、锂、前驱体、正极和镍中间品的收入、毛利与出货，产业链暴露可核验。",
                    "86分表示公司与三种金属和材料加工高度直接相关；分数不代表所有产品对价格同方向敏感。",
                    "公司既有资源冶炼，也有材料加工和贸易，同一金属价格上涨会同时改变售价、成本、库存和加工价差。",
                    ["镍和镍中间品是最大收入与毛利来源。", "钴毛利率较高但收入占比有限，锂业务仍在爬坡。"],
                    ["r-huayou-ar2025", "r-huayou-ar2024", "r-huayou-ar2023", "r-huayou-q12026", "r-model-financial"],
                ),
                _factor(
                    "supply.raw_policy_constraint",
                    "资源国政策对盈利的约束",
                    82,
                    0.94,
                    0.88,
                    "刚果（金）钴出口配额和印尼镍矿RKAB同时影响原料、产量、产品价格和项目利用率。",
                    "82分反映政策可以显著改变短期价差，但政策仍有修订和执行弹性，不能当成固定产量。",
                    "华友跨刚果（金）、印尼和津巴布韦布局，降低单一资源风险，也提高许可、税费、社区与资本执行复杂度。",
                    ["钴配额收紧有利于产品价格，却可能限制可售量和贸易流。", "印尼矿石配额收紧支撑镍价，也可能提高HPAL原料成本。"],
                    ["w-drc-quota", "w-indonesia-esdm", "w-usgs-mcs2026", "w-iea-outlook-2026", "r-huayou-ar2025"],
                ),
                _factor(
                    "company.revenue_exposure_proxy",
                    "分部收入与毛利的可核验程度",
                    77,
                    0.96,
                    0.90,
                    "2025年主要分部口径可得，但内部交易抵销、产品跨分部流转和项目级归母贡献仍不能逐笔拆分。",
                    "77分确认经营基数足以建模，同时为内部交易、少数股东和贸易收入保留折扣。",
                    "模型按分部毛利汇总并在合并层处理费用、税和归母比例，避免把项目收入或100%产量直接当归母利润。",
                    ["镍产品、镍中间品、正极材料和贸易的收入规模大但利润率不同。", "外部预测只用于独立模型完成后的对账。"],
                    ["r-huayou-ar2025", "r-huayou-q12026", "r-model-financial", "r-huachuang-20260515", "r-citi-20260721"],
                ),
                _factor(
                    "company.capacity_readiness_window",
                    "项目投产与有效爬坡准备度",
                    69,
                    0.90,
                    0.80,
                    "华越、华飞、华科已有运营基线，Pomalaa仍在建设并按2027年爬坡，锂盐项目进入首批发运阶段。",
                    "69分反映已有项目成熟、新项目仍需爬坡；Sorowako和未交割Ewoyaa不进入基准产量。",
                    "名义产能只有在建设完成、原料保障、良率和利用率形成后才转成有效产量和现金流。",
                    ["Pomalaa的12万吨名义产能不在2026年按满产计入。", "硫酸锂首批发运证明链条启动，但不等于全年满产。"],
                    ["r-huayou-ar2025", "w-vale-pomalaa", "w-vale-pomalaa-progress", "w-huayou-lithium", "w-sec-ewoyaa"],
                ),
                _factor(
                    "supply.capacity_event_12m",
                    "未来一年新增产能与资本开支压力",
                    68,
                    0.89,
                    0.80,
                    "2026年主要事件是Pomalaa建设、锂项目爬坡和既有印尼资产提效，收益与资本占用并存。",
                    "68分表示项目进展能提高中期收入，但短期自由现金流仍可能为负。",
                    "2025年资本开支107.58亿元，2026年一季度已支出47.37亿元；项目越快，融资和营运资金压力越大。",
                    ["项目执行是收入增长的先决条件。", "高资本开支使净利润增长不能直接等同于股东可分配现金。"],
                    ["r-huayou-ar2025", "r-huayou-q12026", "w-vale-pomalaa-progress", "w-huayou-lithium"],
                ),
                _factor(
                    "demand.customer_capex_capacity_signal",
                    "电池与储能下游需求窗口",
                    64,
                    0.88,
                    0.78,
                    "电动车和储能继续增长，但LFP占比上升使镍钴需求弱于电池总量，正极材料海外爬坡也存在客户和成本约束。",
                    "64分承认需求长期增长，不把电池装机机械外推为三元材料或华友收入。",
                    "需求结构比总量更重要：LFP利好锂需求，却压低镍和钴的单位强度。",
                    ["锂需求受电动车与储能双轮驱动。", "镍钴需要高镍三元份额和客户产品结构支持。"],
                    ["w-iea-ev-2026", "w-iea-critical-2026", "r-huayou-ar2025"],
                ),
                _factor(
                    "company.financial_capture_quality",
                    "利润转化为经营现金流的质量",
                    63,
                    0.95,
                    0.88,
                    "2025年归母净利润61.10亿元、经营现金流40.12亿元、资本开支107.58亿元，自由现金流为负。",
                    "63分反映利润增长真实但现金转化被库存、应收和扩产拖累；2024年的强现金流不能直接外推。",
                    "资源一体化公司必须同时看归母比例、营运资金、资本开支、净债务和少数股东权益。",
                    ["2025年库存与应收增加占用现金。", "2026年一季度资本开支已高于经营现金流。"],
                    ["r-huayou-ar2025", "r-huayou-q12026", "r-model-financial"],
                ),
                _factor(
                    "supply.substitution_barrier",
                    "资源、冶炼和材料一体化壁垒",
                    61,
                    0.86,
                    0.76,
                    "资源、湿法冶炼、前驱体和正极协同降低外采与客户导入成本，但不消除商品价格、技术路线和海外执行风险。",
                    "61分表示一体化有成本和供应安全价值，却不能保证所有环节同时获得高回报。",
                    "LFP替代、客户自供、资源国本地化和竞争项目都会重新分配价值。",
                    ["一体化能稳定原料与产品组合。", "复杂项目和非全资权益会稀释上市公司归母回报。"],
                    ["r-huayou-ar2025", "w-huayou-precursor", "w-iea-ev-2026"],
                ),
                _factor(
                    "signal.material_price_momentum",
                    "镍钴锂价格与价差方向",
                    59,
                    0.82,
                    0.70,
                    "钴受配额支撑最强，镍接近平衡且受印尼政策扰动，锂短期宽松、中期对项目延后敏感。",
                    "59分代表价格组合对华友较2025年改善，但三种金属不同步且不保证加工价差同步扩大。",
                    "只看现货价格会遗漏采购与销售时差、库存重估、产品结构和内部交易抵销。",
                    ["钴价改善可能先体现在高毛利分部。", "镍和锂的供给弹性限制单边上涨外推。"],
                    ["w-usgs-mcs2026", "w-drc-quota", "r-model-supply-demand"],
                ),
                _factor(
                    "demand.output_consumption_proxy",
                    "销量和需求兑现代理",
                    66,
                    0.92,
                    0.84,
                    "2025年镍、钴、锂及材料出货增长，2026年一季度收入和利润继续提高。",
                    "66分反映现有产线需求和出货兑现，仍需用库存、应收和现金流判断销售质量。",
                    "销量增长可能来自新产能和低价放量，只有毛利、现金和资产回报同步才是高质量增长。",
                    ["镍产品出货约29.25万金属吨，是公司当前最大数量暴露。", "锂产品约5.44万吨，仍处相对早期规模。"],
                    ["r-huayou-ar2025", "r-huayou-q12026", "r-model-financial"],
                ),
                _factor(
                    "demand.application_intensity_change",
                    "电池化学体系的单位金属强度变化",
                    54,
                    0.85,
                    0.77,
                    "LFP提高锂需求但降低镍钴强度，高镍三元仍有高端和海外市场。",
                    "54分表示化学体系变化对组合业务有正有负，不能用单一电动车增速解释。",
                    "华友通过锂、三元材料和资源冶炼分散路线风险，但资产和客户转换需要时间。",
                    ["LFP占比上升压低钴和镍需求强度。", "储能扩张对锂更直接。"],
                    ["w-iea-ev-2026", "w-iea-critical-2026", "r-huayou-ar2025"],
                ),
                _factor(
                    "supply.expansion_cycle_bucket",
                    "全球供给扩张周期位置",
                    57,
                    0.82,
                    0.72,
                    "镍仍有较多印尼项目，钴受短期政策截流，锂项目对价格有明显停复产弹性。",
                    "57分表示三种金属不处于同一个供给周期，综合盈利不能套一个价格情景。",
                    "供给扩张与华友自身扩产叠加时，销量增长可能被价格和利用率抵消。",
                    ["镍中期供给响应仍强。", "锂项目延后可以改善中期平衡，但高价会促使复产。"],
                    ["w-iea-market-2026", "r-nickel-20260525", "r-lithium-20260614"],
                ),
                _factor(
                    "supply.supplier_structure_bucket",
                    "供应地域集中和项目组合",
                    65,
                    0.90,
                    0.83,
                    "钴集中于刚果（金）、镍集中于印尼，锂资源更分散；华友资产布局与行业集中风险高度重合。",
                    "65分表示资源区位提供规模和成本优势，也集中暴露于当地政策、许可和基础设施。",
                    "跨国项目组合需要按每个项目持股、并表和现金回流能力分析，不能以集团名义产能替代归母权益。",
                    ["镍与钴供应集中放大政策价值。", "锂资源多元化降低单一国家控制力。"],
                    ["w-usgs-mcs2026", "r-huayou-ar2025", "w-vale-pomalaa"],
                ),
                _factor(
                    "demand.downstream_price_momentum",
                    "下游材料价格和利润修复",
                    58,
                    0.80,
                    0.70,
                    "三元前驱体和正极材料需求增长，但LFP竞争、海外爬坡和客户议价限制利润率快速恢复。",
                    "58分代表材料环节处于修复而非全面高景气，资源端利润改善不必然同步传到正极材料。",
                    "正极材料2025年收入大但毛利率只有9.36%，是量大、回报需要继续验证的环节。",
                    ["产品结构升级可以改善毛利。", "海外产能利用率和客户认证仍影响资产回报。"],
                    ["r-huayou-ar2025", "w-huayou-precursor", "w-iea-ev-2026"],
                ),
            ],
        },
    ]


def _target_point(
    metric: str,
    category: str,
    value_text: str,
    unit: str,
    ref: str,
    period: str,
    value_num: float | None = None,
) -> dict[str, Any]:
    source = SOURCE_BY_REF[ref]
    point: dict[str, Any] = {
        "metric_name": metric,
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


def _targets() -> list[dict[str, Any]]:
    return [
        {
            "entity_key": "huayou_integrated",
            "target_name": "华友钴业",
            "ticker": "603799.SH",
            "market": "SH",
            "target_type": "security",
            "company_id": 631,
            "research_company_id": 631,
            "target_company_id": 631,
            "exposure_rationale": "华友钴业直接拥有或控制钴、镍、锂资源冶炼及前驱体、正极材料资产，是三种金属供需变化向上市公司利润和现金流传导的主要观察标的。",
            "evidence_ref_uri": _ev("r-huayou-ar2025"),
            "research_action": "按分部销量、毛利、项目有效产量、少数股东、营运资金和资本开支逐季复核，不用商品价格或名义产能替代归母利润。",
            "investment_view": "独立模型认为2026—2028年利润继续增长，但自由现金流在2026年仍受扩产压制；当前市值接近多方法估值区间下沿，存在一定安全边际但不是巨大错价。",
            "risk_note": "最大风险不是单一金属价格下跌，而是项目爬坡、资源国政策、材料利润率、营运资金和高资本开支同时不利。",
            "target_priority": "高：政策、项目和现金流均有可验证事件",
            "target_quality_label": "经营数据较完整，项目级归母和成本仍需持续验证",
            "relative_preference": "相较只持有单一矿种资产，公司组合更分散；相较轻资产材料公司，资本开支、杠杆和少数股东更重。",
            "confirmed_scenario_action": "若Pomalaa按计划爬坡、锂盐利用率提升、钴价差维持且经营现金流覆盖资本开支，可上调盈利与PB—ROE中枢。",
            "falsified_scenario_action": "若项目延期、镍锂价格与材料毛利同步走弱、库存应收继续快于收入且自由现金流连续为负，应下调ROE和估值区间。",
            "target_profile_markdown": _link_company_mentions(
                f"{COMPANY_NAME}2025年实现收入810.19亿元、归母净利润61.10亿元，镍产品出货约29.25万金属吨。{_cite('r-huayou-ar2025')} "
                "公司横跨资源、冶炼、前驱体和正极材料，经营弹性来自金属价格、加工价差、项目爬坡和产品结构共同作用。"
            ),
            "target_deep_research_markdown": _link_company_mentions(
                f"{COMPANY_NAME}2025年经营现金流40.12亿元，资本开支107.58亿元，自由现金流约-67.46亿元；"
                f"2026年一季度收入258.04亿元、归母净利润24.97亿元，但资本开支47.37亿元仍高于经营现金流11.75亿元。{_cite('r-huayou-ar2025')} {_cite('r-huayou-q12026')} "
                "独立基准预测2026—2028年收入958/1083/1228亿元、归母净利润88.2/105.6/123.4亿元，"
                "自由现金流为-36.1/26.3/79.5亿元。市场快照截至2026年7月23日为41.55元、786.76亿元市值、"
                "10.70倍滚动市盈率和1.59倍市净率。多方法估值的核心交集约779—970亿元，对应41.14—51.24元；"
                "当前价格接近下沿，但仍需现金流由负转正和项目兑现。"
            ),
            "entity_relation_markdown": "该标的是三种金属供需研究的上市公司承接主体；行业余额先影响价格与加工价差，再经项目权益、分部毛利、费用、税、少数股东和现金流传到股东价值。",
            "parent_research_relation_markdown": "镍、钴、锂三个市场分别建模，避免用其中一种金属的景气结论覆盖整个公司；公司估值采用PE、PB—ROE和EV/EBITDA交叉，而不做机械平均。",
            "conditional_investment_recommendation": "当前适合条件化跟踪而非仅凭低PE买入：41元附近需要确认现金流拐点，51元以上则需要基准利润、项目爬坡和较高ROE共同兑现。",
            "financial_data_status": "2021—2025年度、2026年一季度、当前市场估值、历史PB/PE和2026—2028一致预期已进入financial.db；项目级成本、真实良率、内部交易和客户级材料利润仍公开不足。",
            "link_status": "linked",
            "support_status": "supported",
            "sort_order": 10,
            "target_data_points": [
                _target_point("营业收入", "财务", "810.19亿元", "亿元人民币", "r-huayou-ar2025", "2025年", 810.19),
                _target_point("归母净利润", "财务", "61.10亿元", "亿元人民币", "r-huayou-ar2025", "2025年", 61.10),
                _target_point("经营现金流", "现金流", "40.12亿元", "亿元人民币", "r-huayou-ar2025", "2025年", 40.12),
                _target_point("资本开支", "现金流", "107.58亿元", "亿元人民币", "r-huayou-ar2025", "2025年", 107.58),
                _target_point("镍产品出货", "经营", "约29.25万金属吨", "万吨镍金属量", "r-huayou-ar2025", "2025年", 29.25),
                _target_point("锂产品出货", "经营", "约5.44万吨", "万吨产品", "r-huayou-ar2025", "2025年", 5.44),
                _target_point("Pomalaa名义产能", "项目", "12万吨镍/年，仍需建设完成和爬坡", "万吨镍金属量/年", "w-vale-pomalaa", "截至2026年", 12.0),
                _target_point("锂盐项目进度", "项目", "5万吨级硫酸锂项目完成并首批发运", "万吨产品/年", "w-huayou-lithium", "2026年", 5.0),
            ],
        }
    ]


def _sections() -> list[dict[str, Any]]:
    c = _cite
    return [
        _section(
            "summary",
            "摘要",
            f"""
**结论先行：未来3—5年，镍最接近平衡、钴最受政策驱动、锂的需求斜率最大但短期仍宽松。** 基准供需模型到2030年分别得到镍小幅宽松8万吨镍金属量、钴小幅缺口0.6万吨钴金属量、锂缺口40万吨碳酸锂当量。这些是把公开数量级、政策和项目进度统一口径后的研究情景，不是官方价格预测。USGS显示2025年全球镍矿供应约390万吨，其中印尼260万吨；钴矿供应约31万吨，其中刚果（金）23万吨、印尼4.4万吨；锂矿供应约29万吨锂金属量，高于26.3万吨消费。{c('w-usgs-mcs2026')} 因此不能把中期潜在缺口倒写成2026年三种金属都已经短缺。

钴的短期弹性最大。刚果（金）2026年出口配额约9.66万吨，约束的是有效出口流量，不等于矿山产量；IEA在配额延续情景下提示中期缺口风险，但LFP和低钴化同时削弱单位需求。{c('w-drc-quota')} {c('w-iea-outlook-2026')} 镍的核心变量是印尼RKAB、矿石品位、HPAL/RKEF爬坡和硫酸成本，政府仍保留配额调整窗口；锂在2025年供给仍偏宽松，中期是否转紧取决于项目延期、复产和电动车、储能需求之间的速度差。

[华友钴业](/company/631)是三种金属供需变化的综合承接者，但经营结果不能用“金属价格×名义产能”计算。2025年公司收入810.19亿元、归母净利润61.10亿元；镍产品、镍中间品、正极材料和贸易贡献最大收入，钴产品毛利率较高，锂业务仍在爬坡。{c('r-huayou-ar2025')} 华飞、华越等项目存在非全资权益，Pomalaa仍在建设，Ewoyaa拟议交易尚未完成；模型分别处理投产、有效产量、合并利润和归母比例，没有把100%项目产能算成股东产量。

独立基准模型预计公司2026—2028年收入约958/1083/1228亿元，归母净利润88.2/105.6/123.4亿元；经营现金流123.9/161.3/189.5亿元，资本开支160/135/110亿元，自由现金流为-36.1/26.3/79.5亿元。{c('r-model-financial')} 独立预测在读取外部一致预期前冻结，随后与Wind和四家卖方模型对账：收入低约3%—4%，利润低约6%—12%，主要因为不把钴价高位、Pomalaa满产和材料利润率快速修复同时放入基准。

截至2026年7月23日，公司股价41.55元、市值786.76亿元、滚动市盈率10.70倍、市净率1.59倍、滚动ROE 14.56%、ROA 6.97%。PE、PB—ROE和EV/EBITDA三种方法的核心交集约779—970亿元，对应41.14—51.24元。当前价格接近区间下沿，说明市场尚未给所有远期项目充分溢价；但2025年自由现金流约-67亿元、2026年一季度资本开支仍显著高于经营现金流，低倍数只有在项目兑现和现金流转正时才构成安全边际。

风险并不是三种金属同时下跌这一种情况。钴价格上涨而出口量不足，可能出现毛利率改善但销量和现金回收不及预期；镍价格上涨而矿石成本同步上升，可能只改善收入不改善单位利润；锂价反弹而新项目复产加快，远期缺口也可能重新收窄。公司层面若材料分部利用率低、少数股东占比较高或营运资金继续扩张，资源端改善仍会在归母利润和自由现金流之间被稀释。

未来12个月最有决策价值的顺序是：先看刚果（金）配额实际执行和华友钴产品销量，再看印尼矿石配额、现有HPAL利用率和Pomalaa关键建设节点，随后核验锂盐连续出货、材料分部毛利和经营现金流覆盖资本开支。只有行业、项目和现金三层同时改善，才应把当前低估值解释为持续的回报提升，而不是商品周期与重资产扩张的折价。
""",
            [
                "w-usgs-mcs2026",
                "w-drc-quota",
                "w-iea-outlook-2026",
                "r-huayou-ar2025",
                "r-model-financial",
            ],
            10,
        ),
        _section(
            "method_scope",
            "研究问题、口径与计算方法",
            f"""
本研究回答四个相互连接的问题：第一，镍、钴、锂未来3—5年的全球有效供需和价格压力分别是什么；第二，资源国政策、成本曲线、项目投产和电池路线怎样改变这些路径；第三，[华友钴业](/company/631)现有分部和项目怎样把行业变化转成收入、归母净利润与现金流；第四，当前市值隐含了什么利润和资本回报，是否与独立模型有显著分歧。

供需模型先统一计量单位。镍使用千吨镍金属量，钴使用千吨钴金属量，锂使用千吨碳酸锂当量。**供需余额＝有效供应－需求**，正数为宽松、负数为缺口。矿石湿吨、MHP实物吨、矿山金属量、出口配额和冶炼产品量不能相加。锂的USGS历史锂金属量按5.323换算成碳酸锂当量，只用于校验数量级，不替代逐项目有效供给。{c('w-usgs-mcs2026')}

公司模型从2025年八个经营分部出发：**分部收入＝2025年经营基数×销量、价格和产品结构的综合情景系数；合并毛利润＝各分部收入×各自毛利率之和。** 之后扣除税金及期间费用，加入投资收益、减值和营业外项目，得到合并净利润；再按归母比例计算归母净利润。经营现金流在合并净利润基础上加回折旧摊销和其他非现金项目，扣除营运资金占用；自由现金流等于经营现金流减资本开支。{c('r-model-financial')}

项目处理遵守三个边界。其一，华飞51%、华越60%等非全资项目不把100%利润归给上市公司；其二，Pomalaa的12万吨名义产能在2026年不按满产，基准从2027年开始爬坡；其三，Sorowako和未完成交易的Ewoyaa不进入基准产量。项目收入、合并利润、少数股东和上市公司归母利润分别计算，避免产能和利润重复。

估值不机械平均。PE使用2026年独立归母净利润88.2亿元与8—11倍区间；PB—ROE使用2026年末估计每股净资产30.47元、独立前瞻ROE约16.3%和1.35—1.75倍PB；EV/EBITDA使用2026年188亿元EBITDA、净债务430亿元和少数股东权益110亿元。PB—ROE的核心关系可以写成：可持续PB＝（预期ROE－长期增长率）÷（股权回报要求－长期增长率）。商品周期、资产重估和杠杆会使公式偏离实际交易倍数，因此它只作为有经济意义的交叉验证。

外部对账发生在独立模型冻结之后。Wind一致预期和卖方报告用于检查币种、财年、归母、项目节奏和利润率差异，不反向覆盖模型。网上传闻、论坛、转载和没有项目方确认的计划产能只用于寻找线索；本轮核心结论均回到公司财报、USGS、IEA、政府政策、项目业主或SEC文件。

资料的时间和权威层级也单独处理。2026年公司季报和项目更新用于当前经营与建设状态，2025年USGS和公司年报用于可比数量级，IEA的2035—2040年路径只用于方向和压力测试，不能替代2026—2030年的逐年供需。卖方报告对项目节奏、成本和一致预期有参考价值，但其利润数字不被当作经营事实。相同的USGS年度汇总、IEA专题页面或公司年报即使有多个网页入口，也只按一个底层证据组计算。

模型精度服从数据精度。全球供需只保留到万吨或十万吨级，公司财务按亿元展示，价格与倍数保留到足以对账的精度；公开不可得的项目良率、客户合同价、矿石品位和单位酸耗不用匿名转述补齐。对这些缺口，模型通过审慎、基准和积极情景改变销量、毛利和资本开支，而不制造看似精确的单点输入。所有可变市场快照保留在公司财务数据库，Opportunity Lens正文只引用冻结时点和计算结果。

最后，供需情景和财务情景不是机械一一对应。公司能够通过长协、库存、产品组合、伴生铜钴、内部加工和客户定价缓冲一部分现货波动；相反，扩产、少数股东和海外营运资金也可能放大行业改善尚未转成股东现金的时间差。因此行业余额先形成价格与价差条件，再通过分部和三表模型传导，不能把供需缺口比例直接乘公司利润。
""",
            [
                "w-usgs-mcs2026",
                "r-model-financial",
                "r-huayou-ar2025",
                "w-vale-pomalaa",
                "w-sec-ewoyaa",
            ],
            20,
        ),
        _section(
            "three_metals",
            "镍、钴、锂未来3—5年的供需判断",
            f"""
本节要回答的是：镍、钴、锂未来3—5年的有效供需分别会怎样变化，哪些条件可能推翻判断？三种金属不能用同一套“新能源需求增长”叙事。USGS的2025年数据提供了统一的起点：镍全球矿山供应约390万吨，印尼约260万吨，供应高度集中但项目响应仍强；钴全球矿山供应约31万吨，刚果（金）约23万吨，短期有效流量受出口配额直接约束；锂矿供应约29万吨锂金属量，消费约26.3万吨，2025年仍有现货宽松基础。{c('w-usgs-mcs2026')}

| 金属 | 2026年基准余额 | 2030年基准余额 | 主要上行条件 | 主要反方 |
|---|---:|---:|---|---|
| 镍 | +10万吨镍 | +8万吨镍 | 印尼配额收紧、HPAL延迟、矿石与硫酸成本上升 | 印尼项目加速、LFP和钠离子限制电池级镍 |
| 钴 | -1.5万吨钴 | -0.6万吨钴 | 刚果（金）配额严格、高镍三元与合金需求 | 配额放松、库存释放、印尼伴生钴和低钴化 |
| 锂 | +9万吨碳酸锂当量 | -40万吨碳酸锂当量 | 项目延期、电动车与储能持续高增 | 高价复产、新项目兑现、需求增速回落 |

镍的基准供给和需求在2026—2030年分别以约4.3%和4.5%复合增长，余额长期只占需求约2%。这意味着价格方向对政策和项目兑现非常敏感，而不是确定的大短缺。印尼政府在2026年仍表示年度总配额没有最终锁定，官方表态的2.5—2.6亿湿吨矿石也保留调整空间。{c('w-indonesia-esdm')} {c('w-indonesia-antara')} 因此紧张情景需要持续配额约束、项目延迟和需求不降同时成立；宽松情景则由更快投产和电池路线替代推动。

钴的关键是“有效出口”而非“矿山生产”。刚果（金）2026年配额约9.66万吨，不能直接与2025年23万吨矿山产量相减，因为时间、库存、国内转化和出口口径不同。{c('w-drc-quota')} 基准模型将2026—2027视为偏紧，2028年后随着配额部分放松和印尼伴生钴增加，缺口收窄；若严格配额延续，2030年缺口可明显扩大。反方是LFP已经占电动车电池过半并主导储能，高镍三元也持续降低单位钴用量。{c('w-iea-ev-2026')}

锂的供需转折更依赖项目响应。2026年仍有约9万吨碳酸锂当量宽松，但低价导致项目延期、减产和融资收缩后，基准从2027年转为缺口。IEA认为锂长期需求增长超过三倍，电池约占当前锂消费88%；但任何持续高价都会重新激活停产和边际项目，故2030年40万吨缺口不能线性转成目标价。{c('w-iea-critical-2026')} {c('w-usgs-mcs2026')}

综合判断是：未来一年钴政策最可能改善[华友钴业](/company/631)高毛利分部，镍提供较稳定的规模基盘，锂项目则决定2027年以后的增长弹性。公司组合降低了单一金属风险，但也使利润对三种不同周期、资源国政策和资本开支同时敏感。

成本曲线决定供需余额如何转成价格。镍的边际成本同时受矿石品位、矿价、能源和硫酸影响，印尼低成本项目增加会压低长期价格上沿；钴作为铜镍副产品，供给决策不完全由钴价决定，配额和主金属项目会使价格弹性更突兀；锂的独立矿山和盐湖项目对价格、融资和建设周期反应更直接。相同的5%供需缺口，在三种金属上不能使用相同价格弹性。

反证搜索也改变了结论。印尼并未把2026年配额宣布成永不调整的固定数，故镍紧张不应成为唯一基准；刚果（金）配额约束很强，但LFP和印尼伴生钴使钴长期严重缺口不能无条件成立；锂长期需求高增明确，但2025年供应仍高于消费且高价会触发复产。因此本报告的三个基准结论分别是“镍接近平衡”“钴先紧后缓”“锂短松中期趋紧”，而不是统一的资源牛市判断。
""",
            [
                "w-usgs-mcs2026",
                "w-indonesia-esdm",
                "w-indonesia-antara",
                "w-drc-quota",
                "w-iea-ev-2026",
                "w-iea-critical-2026",
                "r-model-supply-demand",
            ],
            30,
        ),
        _section(
            "business_projects",
            "华友钴业的分部、项目与归母传导",
            f"""
本节要回答的是：镍、钴、锂价格和项目投产怎样穿过分部结构，最终转成[华友钴业](/company/631)的归母利润与股东现金？公司2025年年报给出了建模起点：收入810.19亿元、毛利润141.54亿元、归母净利润61.10亿元。分部结构说明公司不是单一“钴股”：镍产品收入258.95亿元、毛利率19.70%，镍中间品收入117.81亿元、毛利率19.32%；正极材料收入149.69亿元但毛利率只有9.36%；钴产品收入50.30亿元、毛利率36.78%；锂产品收入34.41亿元、毛利率20.65%。{c('r-huayou-ar2025')}

| 2025年分部 | 收入（亿元） | 毛利率 | 对公司模型的作用 |
|---|---:|---:|---|
| 镍产品 | 258.95 | 19.70% | 最大资源冶炼基盘，受印尼矿石和镍价差影响 |
| 镍中间品 | 117.81 | 19.32% | 连接HPAL产量与材料客户，需防止内部交易重复 |
| 正极材料 | 149.69 | 9.36% | 收入大但回报低，取决于海外爬坡和客户结构 |
| 钴产品 | 50.30 | 36.78% | 短期受配额与价格改善最敏感 |
| 锂产品 | 34.41 | 20.65% | 基数较小，2026—2028项目爬坡弹性较大 |
| 前驱体 | 44.86 | 16.84% | 与三元路线、客户订单和海外制造相关 |
| 铜产品 | 45.27 | 26.01% | 伴生品利润缓冲，不能归入钴或镍重复计算 |
| 贸易及其他 | 97.09 | 4.42% | 收入规模大、利润率低，不应按资源分部倍数估值 |

2025年公司出货钴4.65万吨、铜6.53万吨、镍29.25万吨、锂5.44万吨、前驱体10.84万吨和正极材料11.64万吨。{c('r-huayou-ar2025')} 出货量用于校验经营规模，不直接乘现货价格生成收入：不同产品含量、结算基准、加工费、内部流转和销售时点均不同。

项目层需要区分名义产能、有效产量和归母权益。华越6万吨镍HPAL、华飞12万吨和华科4.5万吨构成现有印尼基盘；华飞由公司持有51%，华越持股在2025年末提高至60%。Pomalaa名义12万吨镍/年，项目方2026年仍披露建设进度，因此基准模型不在2026年计满产，从2027年开始爬坡。{c('w-vale-pomalaa')} {c('w-vale-pomalaa-progress')} Sorowako仍属于规划路径，不进入基准。

锂业务方面，Arcadia提供资源和采选基础，5万吨级硫酸锂项目已完成并出现首批发运，支持2026年开始贡献增量；但首批发运不等于全年满负荷，回收率、运输、转化成本和稳定客户仍要由后续财报验证。{c('w-huayou-lithium')} Ewoyaa拟议交易仍待完成，故不计入基准产量、利润或资产价值。{c('w-sec-ewoyaa')}

一体化的真实价值是稳定原料、提高伴生品回收、缩短客户链和优化产品组合，而不是每个环节都赚取峰值利润。镍、钴、铜等可能在同一矿冶项目产生，前驱体和正极又可能使用内部中间品；模型在合并收入和毛利层处理抵销，避免把同一吨金属沿产业链重复计算。少数股东使部分项目的合并利润不能全部归属上市公司，这也是独立模型归母比例约80%—82%、而非100%的原因。

项目对财务报表的影响也有时间差：建设期先增加在建工程、借款、预付款和资本开支，投产后才形成存货、应收、折旧和收入，稳定运行后才可能改善ROA与自由现金流。2026年的在建项目不能按成熟项目利润率估值；只有有效产量、单位成本、客户回款和归母现金同时出现，名义产能才真正转为股东价值。
""",
            [
                "r-huayou-ar2025",
                "w-vale-pomalaa",
                "w-vale-pomalaa-progress",
                "w-huayou-lithium",
                "w-sec-ewoyaa",
            ],
            40,
        ),
        _section(
            "financial_scenarios",
            "未来三年盈利、现金流与外部对账",
            f"""
本节要回答的是：在现有经营基数、在建项目和现金流约束下，[华友钴业](/company/631)未来三年的盈利能增长到什么程度，外部预测又比独立模型乐观在哪里？模型的直接数据起点是公司2025年年报中的分部收入、分部毛利率、归母净利润、经营现金流和资本开支，以及2026年一季报中的最新现金流和扩产支出。{c('r-huayou-ar2025')} {c('r-huayou-q12026')} 在此基础上，模型分别设置销量、价格、产品结构、项目投产、分部毛利、费用、税、归母比例、营运资金和资本开支。**归母净利润＝合并税后利润×归母比例；经营现金流＝净利润＋折旧摊销和其他非现金项目－营运资金占用；自由现金流＝经营现金流－资本开支。** 这种结构把商品景气、项目建设和股东现金回报分开。

| 情景 | 年份 | 收入（亿元） | 毛利率 | 归母净利润（亿元） | 经营现金流（亿元） | 资本开支（亿元） | 自由现金流（亿元） |
|---|---:|---:|---:|---:|---:|---:|---:|
| 审慎情景 | 2026 | 881.3 | 17.3% | 64.1 | 102.1 | 145 | -42.9 |
| 审慎情景 | 2028 | 1080.5 | 17.4% | 87.6 | 152.2 | 95 | 57.2 |
| 基准情景 | 2026 | 958.0 | 19.7% | 88.2 | 123.9 | 160 | -36.1 |
| 基准情景 | 2028 | 1228.0 | 19.8% | 123.4 | 189.5 | 110 | 79.5 |
| 积极情景 | 2026 | 1015.5 | 21.6% | 109.0 | 135.7 | 175 | -39.3 |
| 积极情景 | 2028 | 1399.9 | 21.7% | 162.0 | 220.4 | 135 | 85.4 |

基准收入增长来自三层：既有镍项目稳定运行；钴价格和毛利较2025年改善但不永久维持峰值；锂盐、海外前驱体和正极逐步爬坡。Pomalaa在2026年不计满产，2027年才开始贡献；这使2026年模型低于把名义产能提前计入的估算。审慎情景同时降低金属价差、材料利润率和项目利用率；积极情景提高销量与毛利，但也提高资本开支，故2026年自由现金流仍为负。{c('r-model-financial')}

[华友钴业](/company/631)2025年经营现金流40.12亿元，明显低于61.10亿元归母净利润；资本开支107.58亿元，自由现金流约-67.46亿元。库存和应收增加合计占用现金，2026年一季度经营现金流11.75亿元、资本开支47.37亿元，扩产压力尚未结束。{c('r-huayou-ar2025')} {c('r-huayou-q12026')} 因而2026年的关键不是净利润能否增长，而是营运资金释放和项目支出能否让自由现金流接近拐点。

独立模型冻结后再与外部预测对账。Wind一致预期2026—2028年收入约985/1130/1278亿元、归母净利润93.9/118.1/140.5亿元；独立收入低2.7%/4.2%/3.9%，利润低6.1%/10.6%/12.2%。华创、中银和中信建投的利润路径较高，花旗更保守；独立结果落在主要卖方区间内。{c('r-huachuang-20260515')} {c('r-boc-20260430')} {c('r-csc-20260525')} {c('r-citi-20260721')}

差异不是单位、币种、财年或归母口径错误，而是三个可解释判断：钴价改善后毛利率会回落；Pomalaa从2027年爬坡而不是2026年满产；正极和前驱体在LFP占比较高、海外产能成本未完全消化时不快速恢复至高利润率。因此当前不存在足以单独构成重大多空机会的预测分歧，真正的预期差要由现金流、项目有效产量和材料毛利持续验证。
""",
            [
                "r-model-financial",
                "r-huayou-ar2025",
                "r-huayou-q12026",
                "r-huachuang-20260515",
                "r-boc-20260430",
                "r-csc-20260525",
                "r-citi-20260721",
            ],
            50,
        ),
        _section(
            "valuation_investment",
            "估值、市场隐含预期与条件化投资结论",
            f"""
截至2026年7月23日，[华友钴业](/company/631)股价41.55元、总市值786.76亿元、滚动市盈率10.70倍、未来12个月市盈率7.32倍、市净率1.59倍、EV/EBITDA 7.74倍，滚动ROE 14.56%、ROA 6.97%。这些市场和财务供应商数据保存在公司财务数据库并可随时更新，研究包只冻结本次模型结论。

| 估值方法 | 核心输入 | 权益价值（亿元） | 每股价值（元） | 主要限制 |
|---|---|---:|---:|---|
| 2026年市盈率 | 归母净利润88.2亿元，8—11倍 | 706—970 | 37.26—51.24 | 商品周期利润不能直接使用高位倍数 |
| PB—ROE | 2026年末BPS 30.47元，1.35—1.75倍PB | 779—1010 | 41.14—53.33 | ROE受商品价格、杠杆和项目爬坡影响 |
| EV/EBITDA | EBITDA 188亿元，7—9倍，扣净债务和少数股东 | 776—1152 | 40.98—60.84 | 对净债务、少数股东和资本开支敏感 |
| 三种方法核心交集 | 不机械平均，只取共同支持区域 | 779—970 | 41.14—51.24 | 仍依赖基准利润和现金流兑现 |

PB—ROE对华友有经济意义，因为资源冶炼和材料制造需要大量净资产，但不能单独定价。独立模型前瞻ROE约16.3%，市场1.59倍PB隐含的可持续ROE约16.7%，两者接近；这说明市场对资产回报的要求并未显著低于独立基准。ROA只有约7%，而ROE高于ROA，说明杠杆和少数股东结构对股东回报有实质作用。若项目只增加资产和负债而未提升自由现金流，PB看似便宜也可能继续受压。

反向市盈率同样显示当前价格没有包含极端乐观假设。786.76亿元市值对应独立2026年利润约8.9倍，低于滚动市盈率，意味着市场已经在计入2026年利润增长，但没有按高成长材料公司给予溢价。若归母利润只达到审慎情景64.1亿元，当前市值约12.3倍；若达到积极情景109亿元，则约7.2倍。估值分歧主要来自盈利和现金流能否持续，而不是倍数本身。

投资判断分三层。第一，41元附近接近多方法区间下沿，若钴配额、现有印尼项目稳定、锂盐爬坡和营运资金改善共同成立，风险收益偏正。第二，进入46—51元区域后，市场开始要求基准利润和自由现金流转正，买点更依赖项目和现金验证。第三，超过核心区间上沿后，需要Pomalaa顺利爬坡、材料利润率改善和ROE保持在16%以上，不能只依赖金属价格。

最早的证伪信号不是单日金属价格，而是连续两个季度出现以下组合：项目有效产量低于计划、库存与应收继续快于收入、经营现金流低于净利润、资本开支不降、材料毛利率不改善以及净债务继续上升。相反，若Pomalaa按计划进入爬坡、锂产品销量与毛利同步增加、经营现金流覆盖资本开支并且ROA上升，应把当前估值由“周期低倍数”重新评估为“资产回报改善”。

PB—ROA提供额外约束。资源与材料项目先增加总资产，再经过产能利用、价差和费用形成净利润；若ROA停留在约7%，ROE要维持在16%以上就需要较高权益乘数或少数股东资本。这样的ROE质量弱于同样16%但由更高ROA形成的公司。未来若资产增速继续快于利润、在建工程转固后折旧增加且自由现金流没有改善，合理PB不应因为账面净资产增加而自动上调。

不同价格区间对应不同验证要求。接近41元时，市场价值约等于PB—ROE法下沿，主要风险是审慎利润和现金流继续恶化；接近46元时，需要基准归母利润和2027年自由现金流转正；接近51元时，需要项目爬坡、材料利润修复和ROE维持共同成立。这个框架不是短线交易指令，而是把买卖判断绑定到可以由财报和项目更新证伪的经营结果。

行业事件也可能使估值暂时偏离基本面。钴配额或镍配额消息会先改变商品价格与市场风险偏好，项目投产则更慢地改变EBITDA和现金流。研究结论因此区分市场交易区间和基本面价值：前者可以受政策预期快速扩张，后者必须由归母利润、ROA、净债务和自由现金流兑现。只有两者的差异能被明确经营变量解释，才构成有意义的预期差。
""",
            [
                "r-model-financial",
                "r-huayou-ar2025",
                "r-huayou-q12026",
                "w-vale-pomalaa-progress",
            ],
            60,
        ),
    ]


def _entity_sections() -> list[dict[str, Any]]:
    c = _cite
    return [
        _entity_section(
            "nickel_market",
            "全球镍：接近平衡的市场为何仍有很高政策弹性",
            f"""
## 问题

未来3—5年镍会形成结构性短缺，还是印尼新增供给继续压制价格？这个问题决定[华友钴业](/company/631)现有HPAL资产、Pomalaa爬坡和镍中间品的利润中枢。

## 证据与数据

USGS估计2025年全球镍矿供应约390万吨镍金属量，其中印尼约260万吨，平均价格约1.5万美元/吨。{c('w-usgs-mcs2026')} 这组数据说明供应集中度极高，但并不说明绝对供应不足。印尼政府2026年表示年度RKAB总量仍未最终决定，后续公开表态提出约2.5—2.6亿湿吨矿石的控制目标，同时保留根据市场与工业需要调整的空间。{c('w-indonesia-esdm')} {c('w-indonesia-antara')} 湿吨矿石不能和金属量直接相加，却能判断当地冶炼原料是否紧张。

IEA的长期方向是能源转型继续推升镍需求，但增幅低于锂，且区间受到电池化学体系显著影响。{c('w-iea-outlook-2026')} LFP和钠离子电池扩张会降低电池级镍需求，高镍三元、航空合金和不锈钢则维持需求。供应端除HPAL外，RKEF、不锈钢回收和非印尼项目在高价时也会响应。

## 计算与情景

模型使用千吨镍金属量，供需余额等于有效供应减需求。基准供给由2026年390万吨增至2030年462万吨，需求由380万吨增至454万吨，2030年小幅宽松8万吨。紧张情景假设印尼配额持续收紧、部分HPAL受许可和硫酸拖累，2030年缺口19万吨；宽松情景假设项目更快投产且电池级需求偏弱，2030年宽松68万吨。{c('r-model-supply-demand')}

这些路径最重要的含义是：基准余额只有需求的约2%，小的政策与项目偏差就能改变方向。镍价不会由一个五年总量数字决定，而会在“矿石配额—冶炼利用率—库存—不锈钢订单—电池路线”之间反复调整。低成本印尼湿法项目可能在中低价格下仍有竞争力，高成本硫化矿和边际项目则形成价格上方的供给响应。

## 对华友钴业的传导

[华友钴业](/company/631)2025年镍产品收入258.95亿元、镍中间品117.81亿元，毛利率均约19%—20%，是公司最大经营基盘。{c('r-huayou-ar2025')} 镍价适度上行且矿石成本受控时，现有HPAL项目利用率和价差改善；若配额过度收紧，产品售价上涨的同时矿石和酸成本也会增加。极端低价会压缩价差、延后行业项目，却也可能提高低成本资产的相对份额。

Pomalaa名义产能12万吨镍/年，但项目方2026年仍披露建设进度。{c('w-vale-pomalaa')} {c('w-vale-pomalaa-progress')} 基准模型不在2026年计入满产，2027年才开始爬坡。投资者应跟踪土建与设备完成、矿石保障、硫酸系统、首次产品、连续季度有效产量和现金成本；任何一个节点缺失，都不能把名义产能乘镍价加入利润。

## 价格、成本与利润率

镍价上涨并不按相同比例增加HPAL项目利润。收入通常随结算基准和产品含镍量变化，成本则包括矿石、硫酸、能源、石灰、人工、维护、尾矿处理、运输和折旧；印尼矿石配额收紧时，产品售价和矿石成本可能同步上升。对华友最有利的不是价格越高越好，而是MHP或镍产品价格改善快于矿石、酸和能源成本，并且装置稳定运行。

伴生钴和其他副产品还会改变单位镍经济性。相同镍产量下，钴回收率和钴价格改善可以降低综合现金成本，但钴出口或销售受限又可能占用库存和营运资金。公开财报没有连续披露每个HPAL项目的酸耗、回收率和副产品抵扣，因此模型使用分部毛利率而非伪造项目现金成本，并通过审慎与积极情景改变价差。

镍产品与镍中间品分部也可能存在内部流转。矿冶项目先产出中间品，再供给前驱体或对外销售；若把项目产值、中间品收入和材料收入全部相加，会重复计算同一金属。2025年合并分部收入已经包含抵销后的公开口径，模型从这一基数增长，而不重新用产量乘现货价搭建一个与合并报表不相容的收入总额。

## 上下游与竞争

上游最关键的是印尼矿石供应、当地冶炼竞争、硫酸和基础设施。更多HPAL项目投产既增加全球供给、压低镍价，也会争夺矿石、工程人员和配套资源。华友已有运营经验和规模采购可能降低单位成本，但新项目集中建设也会提高资本开支、承包和调试压力。

下游高镍三元、合金和不锈钢的需求周期不同。高镍三元对纯度和客户认证要求高，需求受电动车车型和电池路线影响；不锈钢体量大但价格竞争强；合金需求较稳却规模较小。华友同时向材料链和外部客户供货，产品组合能缓冲单一市场，但也使分部收入不能只由一个终端增速解释。

## 可验证的跟踪顺序

未来一年先看印尼正式配额与矿石升贴水，再看华友现有项目销量和镍分部毛利，然后看Pomalaa建设完成、首次产品和连续季度利用率。若镍价上涨而分部毛利、经营现金流和库存周转没有改善，应判断成本或营运资金吞噬了价格收益；若价格平稳但有效产量、单位成本和现金流改善，项目质量反而更强。

## 结论

未来3—5年镍更像“紧平衡与政策摆动”，不是确定的大短缺。对华友的核心价值来自已有低成本产能、伴生钴和项目执行，而不是单向看多镍价。基准情景可以支持镍业务规模和利润稳定，真正上修需要印尼配额、项目延期和需求同时偏紧；真正下修则是项目集中投产、LFP替代和不锈钢需求走弱共同发生。

结论的证伪条件也很清楚：若2027年前印尼有效供应持续高于基准、镍余额扩大到需求10%以上且华友分部毛利跌破审慎假设，应下调中期盈利；若配额收紧、行业项目延期而华友现有装置保持产量和成本，基准应向紧张情景移动。任何调整都必须同时满足行业余额和公司经营结果，不能只根据政策新闻。
""",
            [
                "w-usgs-mcs2026",
                "w-indonesia-esdm",
                "w-indonesia-antara",
                "w-iea-outlook-2026",
                "r-model-supply-demand",
                "r-huayou-ar2025",
                "w-vale-pomalaa",
                "w-vale-pomalaa-progress",
            ],
            110,
        ),
        _entity_section(
            "cobalt_market",
            "全球钴：出口配额改善短期价格，低钴化限制长期外推",
            f"""
## 问题

刚果（金）出口配额能否把钴从过剩推向持续短缺，[华友钴业](/company/631)的钴高毛利是否可以长期维持？

## 证据与口径

USGS估计2025年全球钴矿供应约31万吨，刚果（金）约23万吨、印尼约4.4万吨。{c('w-usgs-mcs2026')} 刚果（金）仍占约四分之三，印尼伴生钴已成为重要增量。资源集中使政策冲击很大，但矿山产量、库存、国内转化、出口配额和最终可交易流量不是同一口径。

2026年刚果（金）配额约9.66万吨，其中基础配额和战略配额分开管理。{c('w-drc-quota')} 这个数字约束出口流量，不能直接与2025年23万吨矿山产量相减，因为年度、库存和加工环节不同。IEA在配额延续情景下提示2035年钴缺口可能超过需求四分之一，说明政策若长期持续会形成结构性影响。{c('w-iea-outlook-2026')}

需求端的最大反方是LFP和低钴化。IEA显示LFP已占电动车电池过半，并在储能中占绝对主导；高镍NMC也减少单位钴用量。{c('w-iea-ev-2026')} 钴仍用于高能量密度电池、消费电子和合金，但需求增速不能直接跟随电池总量。

## 计算与情景

模型按千吨钴金属量计算有效供应。基准2026年供应22.5万吨、需求24万吨，缺口1.5万吨；2027年缺口扩大到3.4万吨，2028年后假设配额部分放松和印尼伴生钴增加，2030年缺口收窄至0.6万吨。紧张情景维持严格配额，2030年缺口11.2万吨；宽松情景叠加配额放松、库存释放和低钴化，2030年转为5.4万吨宽松。{c('r-model-supply-demand')}

这不是三条等概率预测。短期配额执行、库存回流和贸易路线决定实际可售量；中期印尼HPAL伴生钴、刚果（金）政策持续时间和电池化学体系决定余额。钴价格上涨也会推动节钴和回收，形成需求反作用。

## 对华友钴业的影响

[华友钴业](/company/631)2025年钴产品收入50.30亿元、毛利率36.78%，明显高于镍和材料分部；钴产品出货约4.65万吨。{c('r-huayou-ar2025')} 配额收紧最先改善的是库存价值、产品价格和钴分部毛利，但也可能限制采购和可售量。公司在刚果（金）的资源与冶炼能力提供供应链位置，印尼HPAL的伴生钴又提供地区分散；两边同时存在政策和项目执行风险。

独立模型在2026年提高钴分部毛利，但随后让毛利率逐步回落，没有把政策冲击后的高价永久化。{c('r-model-financial')} 这是独立利润低于部分卖方预测的原因之一。正确的验证方式是同时看钴销量、分部毛利、库存与应收、采购和销售结算时差，而不是只看钴现货价格。

## 价格、库存与现金流

配额先影响可出口流量，再通过贸易库存和冶炼库存影响现货价格。若配额实施前已有大量库存位于出口地或消费地，价格冲击可能弱于名义削减；若库存低且配额执行严格，买方会争夺有限流量。公开库存数据不完整，因此模型没有把配额比例直接当价格涨幅，而是让有效供应、毛利率和销量在不同情景中分别变化。

对华友而言，钴价上涨存在四条传导：自产或控制资源的产品价差改善；贸易库存可能产生重估；采购与销售定价时差可能带来阶段收益或损失；客户在高价下可能减少库存或转向低钴方案。前两条偏正，后两条会削弱持续性。若销量下降、应收增加或经营现金流没有跟随毛利改善，钴价上涨对股东的真实价值就低于利润表表面。

铜是部分刚果（金）项目的重要伴生品。2025年华友铜产品收入45.27亿元、毛利率26.01%，对钴业务提供利润和现金流缓冲。{c('r-huayou-ar2025')} 这类伴生收益不能归入钴价格弹性重复计算；在项目层面，它会影响综合成本和资本回报，在分部层面则以独立铜收入与毛利体现。

## 供应结构与长期反方

印尼HPAL项目带来的钴是镍生产的副产品，其供给决策可能由镍经济性驱动，即使钴价格较弱仍会增加。这是长期供给端最重要的反方。刚果（金）若维持严格配额，印尼份额会提高；若配额放松，两地供给叠加可能迅速重建过剩。华友同时布局两地能够分散单一区域，但也意味着公司利润会受到两套政策和项目周期共同影响。

需求端，LFP在储能和大众车型中的高占比压低单位钴用量，高镍三元也持续降钴；相对支撑来自高端长续航车型、消费电子和高温合金。因而钴需求可能增长，但很难与电池装机保持相同增速。价格越高，客户越有动力优化化学体系和库存，这使长期需求曲线具有明显反馈。

## 监控与情景切换

紧张情景需要四个结果共同出现：配额实际执行而非只停留在文件；出口和贸易流量下降；现货与长单价差扩大；华友销量和现金流没有被供应限制抵消。宽松情景则由配额放松、库存释放、印尼伴生钴增长和LFP份额上升共同触发。只出现其中一项时，应调整不确定性范围，不应直接切换整个五年判断。

公司层面的领先指标依次是钴产品销量、毛利率、存货和应收、经营现金流以及铜钴项目的现金回流。若毛利提高但库存和应收更快上升，可能只是价格重估；若销量、毛利和现金流同步改善，政策红利才进入高质量盈利。

## 结论

钴是未来12—24个月对华友利润最有利的变量，但不是可以无条件外推五年的永续红利。基准是先紧后缓：配额改善2026—2027年盈利，2028年后受到配额放松、印尼伴生钴和低钴化约束。若配额严格执行且公司销量没有下降，利润上修最有说服力；若价格上涨但库存、销量或现金流恶化，则收益可能只是账面和时点效应。

基准结论的最大偏差可能来自配额政策突然改变和库存位置不明。研究因此不把钴分部的高毛利用于永久终值，也不把严格配额下的严重缺口设成唯一情景。对华友的估值应承认短期盈利弹性，同时要求更高现金转换或更低倍数来吸收政策反转。
""",
            [
                "w-usgs-mcs2026",
                "w-drc-quota",
                "w-iea-outlook-2026",
                "w-iea-ev-2026",
                "r-model-supply-demand",
                "r-huayou-ar2025",
                "r-model-financial",
            ],
            120,
        ),
        _entity_section(
            "lithium_market",
            "全球锂：短期宽松与中期项目不足可以同时成立",
            f"""
## 问题

锂市场在经历低价和项目调整后，未来3—5年会重新短缺吗，[华友钴业](/company/631)的Arcadia与硫酸锂项目能贡献多少确定性增长？

## 证据与数据

USGS估计2025年全球锂矿供应29万吨锂金属量、消费26.3万吨，供应增长31%、需求增长20%，电池占消费约88%，平均价格约每吨9000美元。{c('w-usgs-mcs2026')} 这些数据说明2025年供给仍高于消费，短期宽松是事实基础；它们也说明需求仍高速增长，低价若持续会促使项目延期。

IEA预计锂到2040年的需求超过三倍，电动车和储能是主要驱动。{c('w-iea-critical-2026')} 但供给对价格具有双向弹性：低价压缩高成本矿山、延后融资和扩产，高价又会推动复产、盐湖提产和边际项目。长期缺口不能脱离价格反馈。

## 计算与情景

模型使用千吨碳酸锂当量。USGS锂金属量按5.323换算只用于校验2025年数量级，逐年路径来自公开项目、行业报告和需求情景。基准2026年供应225万吨、需求216万吨，宽松9万吨；2027年转为9万吨缺口，2030年缺口扩大至40万吨。紧张情景假设更多项目延迟且需求更强，宽松情景假设高价复产和新项目顺利，余额会显著改善。{c('r-model-supply-demand')}

2030年缺口不是一个精确预测。项目清单经常把设计产能当有效产量，资源量又可能多年不能转成商品；另一方面，模型也可能低估高价对非洲、南美、澳洲和中国项目的刺激。因此锂更适合用“项目兑现率和需求斜率”监控，而不是固定点价。

## 华友钴业的锂路径

[华友钴业](/company/631)2025年锂产品收入34.41亿元、毛利率20.65%、出货约5.44万吨，规模低于镍业务。{c('r-huayou-ar2025')} Arcadia为上游资源基础，公司披露资源升级和项目建设；5万吨级硫酸锂项目已经完成并出现首批发运。{c('w-huayou-arcadia')} {c('w-huayou-lithium')} 这支持2026年开始增加收入，但首批产品不能证明全年满产、稳定回收率、物流成本和客户结构。

独立模型让锂收入从2025年的34.4亿元逐步增长，而不是一次性按5万吨名义产能乘高价。锂分部毛利在不同情景下受价格、产量和单位成本共同影响。若项目利用率和产品质量稳定，即使锂价不回到历史高点，规模和成本下降也能增加利润；若价格继续低迷、回收率和物流成本偏高，收入增长可能难以转成ROA。

Ewoyaa拟议交易尚未完成，SEC文件披露的是交易安排而不是公司已经拥有的产量。{c('w-sec-ewoyaa')} 因此模型不计入基准。任何未交割资产、未建成转化线或未验证客户都不进入当前盈利。

## 成本、产品与项目兑现

锂资源转成可售产品至少经过采矿、选矿、运输、转化、提纯和客户认证。Arcadia资源量和品位提供上游基础，但资源量不是年度产量；采选精矿也不等同电池级锂盐。5万吨级硫酸锂项目连接了资源与材料链，首批发运证明流程开始运行，后续仍需连续产量、回收率、能耗、物流、品位和客户结算验证。

锂盐利润对价格和成本都敏感。低价时，高成本项目减产或延期，华友若能依靠自有资源和一体化降低成本，可能提高相对竞争力；但非洲矿山到转化工厂的物流、汇率、税费和营运资金也会侵蚀优势。高价时项目利润改善，同时行业复产和新融资加速，长期价格上沿被供给响应限制。

产品口径同样需要谨慎。锂精矿、粗制锂盐、硫酸锂、碳酸锂和正极材料中的锂价值不能重复相加。公司财报披露的锂产品收入和出货是合并后经营口径，独立模型从分部收入与毛利出发；资源量和名义转化产能只用于解释未来增长条件，不再生成第二套重复收入。

## 需求结构

锂与镍钴最大的不同是LFP也需要锂，因此电池路线从三元切换到LFP会削弱镍钴，却不消除锂需求。储能对成本敏感、单位系统用锂可观，是未来需求的重要增量。反方包括电动车增速回落、单车电池效率改善、钠离子在部分储能和低端车型替代，以及回收供应增加。

需求总量也不能直接映射华友销量。客户认证、产品纯度、交付稳定性、长期合同、价格机制和地区贸易要求决定可售量。公司若只能以折价销售或长时间占用应收，即使产量提高，ROA和自由现金流也可能不佳。

## 三种项目路径

审慎路径假设锂价偏弱、硫酸锂利用率缓慢提升、回收率和物流成本不理想，锂分部收入增长但毛利不扩张；基准路径假设2026年形成连续交付、2027年利用率提升并受中期供需改善支持；积极路径还需要价格回升、成本下降和客户结构改善。Ewoyaa只有在交易完成、资金安排清楚和建设计划可验证后才新增情景，不能提前并入积极路径。

这些路径对公司现金流的影响不同。建设和爬坡阶段需要库存、应收和资本开支，利润可能先于现金出现；稳定运行后，若资本开支回落且客户回款改善，锂业务才可能提高自由现金流。投资者应把锂分部毛利与项目现金回收一起看，不能只关注产能和首批发运。

## 可验证的信号

未来四个最重要的信号是连续季度锂产品销量、单位成本或分部毛利、硫酸锂项目利用率以及经营现金流。行业侧同时跟踪全球项目延迟和复产、碳酸锂与精矿价差、电动车和储能装机。若公司销量增长快于行业但毛利和现金流不改善，可能是低价抢量；若销量、毛利和现金同步改善，才说明一体化开始兑现。

## 结论

锂对华友是2027年以后最重要的新增弹性，但确定性低于现有镍资产。短期市场仍偏宽松，中期可能因需求和项目延后转紧。投资判断应优先看锂产品实际销量、回收率、单位成本、分部毛利和现金回收；只有这些指标共同改善，资源量和名义产能才转化为股东价值。

中期缺口路径若被大量复产和新项目打破，华友锂业务仍可能依靠成本和一体化获得增长，但估值倍数应更低；若行业转紧且公司产量、成本和客户同时兑现，锂才会从小分部变成利润和ROA的第二增长曲线。这两种结果的分界是经营数据，不是资源故事。
""",
            [
                "w-usgs-mcs2026",
                "w-iea-critical-2026",
                "r-model-supply-demand",
                "r-huayou-ar2025",
                "w-huayou-arcadia",
                "w-huayou-lithium",
                "w-sec-ewoyaa",
            ],
            130,
        ),
        _entity_section(
            "huayou_integrated",
            "华友钴业：一体化增长能否转成归母利润、现金流和估值",
            f"""
## 当前经营基线

[华友钴业](/company/631)2025年收入810.19亿元、毛利润141.54亿元、归母净利润61.10亿元；2026年一季度收入258.04亿元、归母净利润24.97亿元。{c('r-huayou-ar2025')} {c('r-huayou-q12026')} 2025年收入较2024年明显增长，利润也改善，但经营现金流40.12亿元低于净利润，资本开支107.58亿元，自由现金流约-67.46亿元。利润增长与股东现金回报尚未同步。

公司不是单一资源股。2025年镍产品和镍中间品合计收入376.76亿元，是最大规模来源；正极材料149.69亿元但毛利率仅9.36%；贸易及其他97.09亿元、毛利率4.42%；钴产品收入50.30亿元、毛利率36.78%；锂产品34.41亿元、毛利率20.65%。{c('r-huayou-ar2025')} 资源环节决定利润弹性，材料和贸易决定收入规模与客户关系，低毛利分部不能和资源分部使用同一估值倍数。

## 项目与归母利润

现有镍资产包括华越6万吨、华飞12万吨和华科4.5万吨名义产能。华飞持股51%，华越2025年末提高至60%；项目利润先进入合并报表，再扣少数股东才能得到归母。Pomalaa名义12万吨仍在建设，基准从2027年爬坡；Sorowako处于规划，不计基准。{c('w-vale-pomalaa')} {c('w-vale-pomalaa-progress')}

锂链从Arcadia采选向5万吨级硫酸锂转化延伸，项目完成和首批发运证明商业链条启动。{c('w-huayou-lithium')} 但真实利用率、品位、回收率、物流和客户价格没有完整公开。Ewoyaa交易未完成，不计入当前资产、产量和估值。{c('w-sec-ewoyaa')} 这些处理让模型不会因计划产能而提前放大利润。

## 独立财务模型

核心计算是：

**合并毛利润＝各分部收入×各分部毛利率之和。**

**归母净利润＝（毛利润－税金及期间费用＋其他收益与投资收益－减值和营业外净损失）×（1－所得税率）×归母比例。**

**自由现金流＝合并净利润＋折旧摊销和其他非现金项目－营运资金占用－资本开支。**

| 情景 | 2026收入 | 2026归母净利润 | 2026自由现金流 | 2028收入 | 2028归母净利润 | 2028自由现金流 |
|---|---:|---:|---:|---:|---:|---:|
| 审慎情景 | 881亿元 | 64亿元 | -43亿元 | 1081亿元 | 88亿元 | 57亿元 |
| 基准情景 | 958亿元 | 88亿元 | -36亿元 | 1228亿元 | 123亿元 | 80亿元 |
| 积极情景 | 1016亿元 | 109亿元 | -39亿元 | 1400亿元 | 162亿元 | 85亿元 |

积极情景2026年自由现金流仍比基准略弱，因为更快扩产需要更多资本开支和营运资金。{c('r-model-financial')} 这个结果纠正了“利润越高、现金一定越多”的直觉。2026年最重要的是现金流拐点，2027—2028年才是Pomalaa、锂盐和材料业务对收入与资产回报的验证。

## 外部预测与分歧

Wind一致预期2026—2028年归母净利润约93.9/118.1/140.5亿元，独立模型低6%/11%/12%。华创、中银和中信建投大体位于一致预期附近，花旗路径更保守。{c('r-huachuang-20260515')} {c('r-boc-20260430')} {c('r-csc-20260525')} {c('r-citi-20260721')} 独立模型没有因为对账而修改，差异来自钴毛利回落、Pomalaa爬坡时点和材料利润率，不是口径错误。

## PB—ROE、PB—ROA与多方法估值

截至2026年7月23日，公司市值786.76亿元、股价41.55元、PE TTM 10.70倍、PB 1.59倍、ROE TTM 14.56%、ROA TTM 6.97%。市场PB隐含可持续ROE约16.7%，独立前瞻ROE约16.3%，两者接近。ROE明显高于ROA，说明杠杆、非全资项目和负债融资对股东回报有实质影响；若只看ROE，会低估资产负担和资本开支。

2026年PE法以88.2亿元利润和8—11倍得到706—970亿元；PB—ROE以估计BPS 30.47元和1.35—1.75倍得到779—1010亿元；EV/EBITDA以188亿元EBITDA、7—9倍并扣净债务和少数股东得到776—1152亿元。共同支持区约779—970亿元，对应41.14—51.24元。PB—ROE适合作为资产回报约束，PE适合观察周期利润，EV/EBITDA能容纳资本结构；三者角色不同，不做简单平均。

## 投资结论

当前价格在核心区间下沿附近，估值不贵但必须由现金流和项目兑现证明。偏多条件是：钴配额维持、现有镍项目稳定、锂盐销量和毛利提升、Pomalaa按计划爬坡、经营现金流在2027年前覆盖资本开支。偏空条件是：印尼项目延期或成本上升、钴配额放松、锂价和材料利润率同步走弱、库存应收继续扩张、净债务上升且自由现金流连续为负。

投资者不应把10倍左右PE直接等同于便宜。若基准归母利润和16%左右ROE兑现，41元附近具有一定安全边际；若只达到审慎利润64亿元且现金流继续为负，当前市值相当于约12倍利润，低倍数会被资产负担抵消。51元以上则需要更强的项目、利润率和现金流共同兑现。
""",
            [
                "r-huayou-ar2025",
                "r-huayou-q12026",
                "w-vale-pomalaa",
                "w-vale-pomalaa-progress",
                "w-huayou-lithium",
                "w-sec-ewoyaa",
                "r-model-financial",
                "r-huachuang-20260515",
                "r-boc-20260430",
                "r-csc-20260525",
                "r-citi-20260721",
            ],
            140,
        ),
    ]


def _table_visual(
    key: str,
    title: str,
    subtitle: str,
    columns: list[str],
    rows: list[list[Any]],
    refs: list[str],
    order: int,
    long_columns: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "block_key": key,
        "block_type": "table",
        "title": title,
        "subtitle": subtitle,
        "data": {
            "what": title,
            "how_to_read": subtitle,
            "columns": columns,
            "rows": rows,
            "column_width_policy": {
                "long_columns": long_columns or columns[-2:],
            },
        },
        "display_data": {"columns": columns, "rows": rows},
        "print_fallback": {"columns": columns, "rows": rows},
        "evidence_ref_uri_list": [_ev(ref) for ref in refs],
        "support_status": "partially_supported",
        "red_flag_level": "none",
        "sort_order": order,
    }


def _visuals(
    supply: dict[str, Any],
    financial: dict[str, Any],
    reconciliation: dict[str, Any],
) -> list[dict[str, Any]]:
    commodity_names = {"nickel": "镍", "cobalt": "钴", "lithium": "锂"}
    balance_rows: list[list[Any]] = []
    for key, name in commodity_names.items():
        base_rows = supply["commodities"][key]["paths"]["base_case"]
        for row in (base_rows[0], base_rows[-1]):
            balance_rows.append(
                [
                    name,
                    row["year"],
                    row["supply"],
                    row["demand"],
                    row["balance"],
                    f"{row['balance_as_demand_pct']:.1f}%",
                ]
            )
    scenario_rows: list[list[Any]] = []
    for scenario_name, rows in financial["scenarios"].items():
        for row in rows:
            scenario_rows.append(
                [
                    scenario_name,
                    row["year"],
                    row["revenue_100m_cny"],
                    f"{row['gross_margin_pct']:.1f}%",
                    row["parent_net_income_100m_cny"],
                    row["operating_cash_flow_100m_cny"],
                    row["capex_100m_cny"],
                    row["free_cash_flow_100m_cny"],
                ]
            )
    compare_rows = [
        [
            row["year"],
            row["independent_revenue_100m_cny"],
            row["wind_consensus_revenue_100m_cny"],
            f"{row['revenue_difference_pct']:.1f}%",
            row["independent_parent_net_income_100m_cny"],
            row["wind_consensus_parent_net_income_100m_cny"],
            f"{row['profit_difference_pct']:.1f}%",
        ]
        for row in reconciliation["comparison"]
    ]
    valuation = financial["valuation"]
    method_by_name = {
        str(row["method"]): row for row in valuation["methods"]
    }
    valuation_rows = [
        [
            name,
            method_by_name[name]["equity_value_low_100m_cny"],
            method_by_name[name]["equity_value_high_100m_cny"],
            method_by_name[name]["price_low_cny"],
            method_by_name[name]["price_high_cny"],
            constraint,
        ]
        for name, constraint in (
            ("市盈率", "周期利润与倍数"),
            ("PB—ROE", "资产回报、杠杆与净资产"),
            ("EV/EBITDA", "净债务、少数股东与资本开支"),
        )
    ]
    valuation_rows.append(
        [
            "共同支持区域",
            valuation["core_value_range_100m_cny"][0],
            valuation["core_value_range_100m_cny"][1],
            valuation["core_price_range_cny"][0],
            valuation["core_price_range_cny"][1],
            "三种方法的交集，不做机械平均",
        ]
    )
    return [
        _table_visual(
            "commodity_balance",
            "三种金属基准供需余额",
            "正余额表示宽松、负余额表示缺口；镍和钴单位为千吨金属量，锂为千吨碳酸锂当量。",
            ["金属", "年份", "有效供应", "需求", "余额", "占需求"],
            balance_rows,
            ["r-model-supply-demand", "w-usgs-mcs2026"],
            10,
            ["金属"],
        ),
        _table_visual(
            "company_scenarios",
            "华友钴业2026—2028年独立财务情景",
            "积极情景也可能因扩产使短期自由现金流偏弱，不能只比较净利润。",
            ["情景", "年份", "收入", "毛利率", "归母净利润", "经营现金流", "资本开支", "自由现金流"],
            scenario_rows,
            ["r-model-financial", "r-huayou-ar2025"],
            20,
            ["情景"],
        ),
        _table_visual(
            "external_comparison",
            "独立模型与外部一致预期对账",
            "外部预测只在独立模型冻结后读取；差异没有反向覆盖研究假设。",
            ["年份", "独立收入", "外部收入", "收入差异", "独立归母净利润", "外部归母净利润", "利润差异"],
            compare_rows,
            ["r-model-financial", "r-huachuang-20260515", "r-boc-20260430", "r-csc-20260525", "r-citi-20260721"],
            30,
        ),
        _table_visual(
            "valuation_methods",
            "华友钴业多方法估值",
            "金额单位为亿元人民币、股价单位为元；共同支持区域用于总结，不代表四种结果等权。",
            ["方法", "权益价值下沿", "权益价值上沿", "股价下沿", "股价上沿", "主要约束"],
            valuation_rows,
            ["r-model-financial", "r-huayou-ar2025"],
            40,
            ["方法", "主要约束"],
        ),
    ]


def build_pack() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    intake = parse_markdown_intake_text(INTAKE_PATH.read_text(encoding="utf-8"))
    supply = _read_json(SUPPLY_OUTPUT_PATH)
    financial = _read_json(FINANCIAL_OUTPUT_PATH)
    reconciliation = _read_json(RECONCILIATION_PATH)

    builder = RunPackBuilder(
        slug="huayou-cobalt-nickel-lithium-cycle-run14",
        display_title="华友钴业与镍钴锂周期",
        research_question=str(intake["research_question"]),
        problem_statement="未来3—5年全球镍、钴、锂供需和政策如何变化，华友钴业的项目、盈利、现金流和估值将怎样传导？",
        intake=intake,
        requested_by="user_run14_deep_global_research",
        run_mode="c_hybrid",
        quality_profile="deep_research",
    )
    for source in SOURCES:
        builder.add_source(source)
    builder.data_points.extend(build_data_points())
    builder.claims.extend(build_claims())
    for entity in _entities():
        builder.add_entity(entity)
    builder.entity_sections.extend(_entity_sections())
    builder.entity_investment_targets.extend(_targets())
    builder.sections.extend(_sections())
    builder.visuals.extend(_visuals(supply, financial, reconciliation))
    builder.search_plan.extend(_search_plan())
    builder.evidence_groups.update(
        {str(source["ref"]): str(source["independence_key"]) for source in SOURCES}
    )

    supply_input_hash = _sha256(SUPPLY_INPUT_PATH)
    supply_output_hash = _sha256(SUPPLY_OUTPUT_PATH)
    financial_input_hash = _sha256(FINANCIAL_INPUT_PATH)
    financial_output_hash = _sha256(FINANCIAL_OUTPUT_PATH)
    reconciliation_hash = _sha256(RECONCILIATION_PATH)

    builder.modeling_records.extend(
        [
            {
                "skill_name": "industry_supply_demand_modeling",
                "status": "completed",
                "input_artifact_hash": f"sha256:{supply_input_hash}",
                "output_artifact_hash": f"sha256:{supply_output_hash}",
                "result_summary": "完成镍、钴、锂统一口径的2026—2030年供需基准、紧张和宽松情景，并检查政策与项目反方。",
            },
            {
                "skill_name": "company_financial_modeling",
                "status": "completed",
                "input_artifact_hash": f"sha256:{financial_input_hash}",
                "output_artifact_hash": f"sha256:{financial_output_hash}",
                "result_summary": "按分部、项目时点、归母比例、营运资金和资本开支完成2026—2028年收入、利润与现金流模型。",
            },
            {
                "skill_name": "company_valuation_modeling",
                "status": "completed",
                "input_artifact_hash": f"sha256:{financial_output_hash}",
                "output_artifact_hash": f"sha256:{reconciliation_hash}",
                "result_summary": "完成PE、PB—ROE、EV/EBITDA、市场隐含预期和外部对账，不对方法结果机械平均。",
            },
        ]
    )
    builder.independent_model_freezes.extend(
        [
            {
                "model_ref": "Run14镍钴锂供需情景模型v1",
                "input_hash": f"sha256:{supply_input_hash}",
                "output_hash": f"sha256:{supply_output_hash}",
                "frozen_before_consensus": True,
                "frozen_at": "2026-07-24",
            },
            {
                "model_ref": "Run14华友钴业独立财务与估值模型v1",
                "input_hash": f"sha256:{financial_input_hash}",
                "output_hash": f"sha256:{financial_output_hash}",
                "frozen_before_consensus": True,
                "frozen_at": "2026-07-24",
            },
        ]
    )
    builder.external_reconciliations.append(
        {
            "model_ref": "Run14华友钴业独立财务与估值模型v1",
            "benchmark_ref": "financial.db中的Wind一致预期及华创、中银、中信建投、花旗研究预测",
            "artifact_hash": f"sha256:{reconciliation_hash}",
            "status": "completed",
            "summary": "独立模型先冻结，再与外部预测逐年对账；差异来自项目时点和利润率判断，没有发现单位、财年或归母口径错误。",
        }
    )
    builder.supplement_requests.extend(
        [
            {
                "request_title": "印尼项目级有效产量、矿石品位与现金成本",
                "request_detail": "公开资料不足以连续获得华越、华飞、华科和Pomalaa的季度有效产量、矿石品位、酸耗、良率和现金成本，当前以分部毛利和项目进度约束。",
                "priority": "p1",
                "blocking_status": "non_blocking",
                "review_status": "pending",
            },
            {
                "request_title": "材料业务客户、产品结构与海外利用率",
                "request_detail": "前驱体和正极材料缺少客户级销量、产品结构、海外工厂利用率和单位资本回报，当前不假设快速恢复至历史高利润率。",
                "priority": "p1",
                "blocking_status": "non_blocking",
                "review_status": "pending",
            },
        ]
    )

    pack = builder.build(publication_mode="stage")
    pack["financial_data_boundary"] = {
        "database": "financial.db",
        "policy": (
            "Wind和Tushare的市场、财务、估值、历史带和一致预期记录只保存在financial.db；"
            "研究包只保存独立模型、对账结论和可公开复核的公司原始披露。"
        ),
        "company_id": 631,
        "financial_security_id": 612,
    }
    pack["prompt_requirements"] = [
        {
            "question": str(intake["research_question"]),
            "output_hint": "run_overview_and_entity_pages",
            "acceptance_criteria": "完整回答全球镍钴锂供需、政策成本、华友项目权益、分部、三表、估值与条件化投资结论。",
        }
    ]
    pack["open_search_statistics"] = {
        "source_count": len(SOURCES),
        "independent_source_group_count": len(
            {str(source["independence_key"]) for source in SOURCES}
        ),
        "parallel_data_point_count": len(builder.data_points),
        "weak_lead_count": 4,
        "weak_lead_group_count": 3,
        "same_origin_duplicate_count": 3,
        "unresolved_material_lead_count": 2,
        "unresolved_material_lead_disposition": (
            "对印尼最终配额和未完成资源交易仅保留条件描述；"
            "未得到政府最终文件或交易交割前，不进入基准供给、公司产量或估值。"
        ),
    }
    validation = validate_run_pack(pack, publication_mode="stage")
    validation.raise_for_errors()
    return pack


def main() -> int:
    pack = build_pack()
    OUTPUT_PATH.write_text(
        json.dumps(pack, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    validation = validate_run_pack(pack, publication_mode="stage")
    print(
        json.dumps(
            {"output": str(OUTPUT_PATH), **validation.as_dict()},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
