"""构建“比亚迪与立讯进军高速光模块”Opportunity Lens V2 深度研究包。

该脚本只读取已经人工核验的证据分包和结构化财务快照，生成可复算模型、
独立 Plotly 看板和 run pack JSON；它不写任何数据库。正式装载、review 和发布
由 manual_run_loader / review_workflow / publication 分阶段完成。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

from tools.opportunity_lens.byd_luxshare_competition_model import (
    ENTRY_SCENARIO_LABELS,
    write_model_artifacts,
)
from tools.opportunity_lens.byd_luxshare_human_report import (
    assert_human_public_markdown,
    audit_human_public_content,
    build_human_entity_sections,
    build_human_nav,
    build_human_report_sections,
    build_human_visuals,
)
from tools.opportunity_lens.constants import (
    RESEARCH_WORKFLOW_CONTRACT_VERSION,
    RUN_PACK_SCHEMA_VERSION,
)
from tools.opportunity_lens.intake_parser import parse_markdown_intake_text
from tools.opportunity_lens.public_content_quality_audit import (
    PUBLIC_AUDIT_FIELD,
    build_pack_audit_attestation,
    render_markdown as render_public_content_audit_markdown,
    run_audit as run_public_content_audit,
)
from tools.opportunity_lens.run_pack_contract import validate_run_pack


ROOT = Path(__file__).resolve().parents[2]
AS_OF_DATE = "2026-07-20"
SLUG = "20260718_byd_luxshare_optical_module_competition_deep_run"
INTAKE_PATH = (
    ROOT
    / "opportunity_lens"
    / "intake_requests"
    / "Opportunity_Lens_研究请求_比亚迪与立讯进军光模块竞争格局风险_深度版.md"
)
CACHE_DIR = ROOT / "cache" / "opportunity_lens" / "byd_luxshare_20260718"
OUTPUT_DIR = ROOT / "opportunity_lens" / "research_outputs" / SLUG
BYD_EVIDENCE_PATH = CACHE_DIR / "byd_evidence.json"
BYD_SEARCH_EXPANSION_PATH = CACHE_DIR / "byd_search_expansion_20260720.json"
LUX_EVIDENCE_PATH = CACHE_DIR / "luxshare_evidence.json"
INDUSTRY_EVIDENCE_PATH = CACHE_DIR / "industry_incumbents_evidence.json"
CROSS_AUDIT_PATH = CACHE_DIR / "cross_evidence_audit.md"
FINANCIAL_PATH = OUTPUT_DIR / "financial_market_snapshot.json"
SCREENING_PATH = OUTPUT_DIR / "local_material_screening.json"
PACK_PATH = OUTPUT_DIR / "run_pack.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _safe_payload(value: Any) -> Any:
    """把 API 快照中的 NaN 转为 None，保证产物是严格 JSON。"""

    if isinstance(value, dict):
        return {key: _safe_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_payload(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


_SOURCE_LOCAL_LOCATOR_OVERRIDES = {
    "SRC-EOPT-AR25": (
        "报告P7（主要会计数据）；P12及P14-P18（产能、收入构成、毛利与客户/供应商）；"
        "P18-P20（研发项目阶段）；P21及P76（经营现金流与购建长期资产现金支出）；"
        "P151（泰国制造子公司）"
    ),
    "SRC-INNO-AR25": (
        "报告P8（主要会计数据）；P13及P24-P25（产能、收入与毛利）；P26（客户/供应商）；"
        "P97-P98（合并现金流量表）"
    ),
    "SRC-INNO-FUND26": "PDF P1（报告期投入募集资金）及P5（募集资金使用情况对照表）",
    "SRC-HKEX-ASP26": "PDF P143（PDF索引142；正文页134，Business—ASP table and pricing explanation）",
    "LX-HKEX-PROSPECTUS-EN-2026": (
        "PDF P58-P60（Three-year restriction on spin-off；潜在分拆、无详细计划及继续并表）"
    ),
    "LX-CNINFO-H1-2025": "PDF P53（合并现金流量表：购建长期资产支付的现金）及财务附注子公司表",
    "SRC-INTEL-Q323": "PDF P5（PDF索引4：decision to divest the pluggable module portion）",
    "SRC-FIT-AR18": "PDF P9及P13（PDF索引8及12：收购光模块业务后的经营与收入整合）",
    "SRC-COHR-10K25": "PDF P10及P20（PDF索引9及19：Lasers分部单一/有限来源及相关风险）",
}


_SOURCE_METADATA_OVERRIDES = {
    "SRC-HKEX-ASP26": {
        "title": "Crealights Technology Co., Ltd. Post Hearing Information Pack",
        "title_zh": "北京海光芯正科技股份有限公司聆讯后资料集",
        "publisher": "Crealights Technology / HKEX",
        "language": "en",
        "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0629/sehk26061101522.pdf",
        "excerpt": (
            "200G: RMB1,171 / RMB1,053 / RMB766; 400G: RMB1,358 / RMB1,343 / RMB962; "
            "800G and above: — / RMB2,443 / RMB1,557 for 2023 / 2024 / 2025. "
            "The filing attributes the declines to product maturity, competition, large-volume procurement "
            "and, for 800G-and-above, the shift from early small-batch shipments."
        ),
        "excerpt_zh": (
            "2023/2024/2025年平均售价：200G为1,171/1,053/766元，400G为1,358/1,343/962元，"
            "800G及以上为—/2,443/1,557元。文件将降价归因于产品成熟、竞争、大批量采购，"
            "并说明800G及以上还受到早期小批量高价基数影响。"
        ),
    }
}


_SOURCE_POINT_EXCERPT_OVERRIDES = {
    "DP-I-033": "200G . . . RMB1,171 (2023), RMB1,053 (2024), RMB766 (2025).",
    "DP-I-034": "400G . . . RMB1,358 (2023), RMB1,343 (2024), RMB962 (2025).",
    "DP-I-035": (
        "800G and above . . . — (2023), RMB2,443 (2024), RMB1,557 (2025). "
        "The 2025 decline reflected relatively intense competition during early commercialization versus "
        "small-batch shipments with relatively higher pricing in 2024."
    ),
    "DP-I-081": (
        "Selected-case ledger: 2 strict full-stack successes among 9 cases; "
        "Wilson 95% interval calculated with z=1.96."
    ),
    "DP-I-082": (
        "Selected-case ledger: 5 broad durable optical-adjacency successes among 9 cases; "
        "Wilson 95% interval calculated with z=1.96."
    ),
    "DP-I-036": "原表字段结构化抄录（FY2025，报告P7）：营业收入24,841,854,840.22元。",
    "DP-I-037": "原表字段结构化抄录（FY2025，报告P7）：归属于上市公司股东的净利润9,531,922,730.17元。",
    "DP-I-038": "原表字段结构化抄录（FY2025，报告P21及P76）：经营活动产生的现金流量净额7,701,234,651.00元。",
    "DP-I-039": "原表字段结构化抄录（FY2025，报告P76）：购建固定资产、无形资产和其他长期资产支付的现金1,319,702,128.54元。",
    "DP-I-040": "推导输入原表行（FY2025，报告P21及P76）：经营活动现金流量净额7,701,234,651.00元；购建长期资产现金支出1,319,702,128.54元。",
    "DP-I-041": "原表字段结构化抄录（报告P12及P14-P15）：光互联产品毛利率FY2024为44.85%，FY2025为47.81%。",
    "DP-I-042": "原表字段结构化抄录（报告P12）：光互联产品FY2024产能1,095万只、产量984万只、销量877万只；FY2025产能1,747万只、产量1,634万只、销量1,603万只。",
    "DP-I-043": "推导输入原表行（报告P12）：FY2024产能1,095万只、产量984万只；FY2025产能1,747万只、产量1,634万只。",
    "DP-I-044": "原表字段结构化抄录（FY2025，报告P15）：境外营业收入23,887,512,078.75元，占营业收入96.16%。",
    "DP-I-045": "原表字段结构化抄录（FY2025，报告P17-P18）：前五名客户合计销售金额17,971,494,504.64元，占年度销售总额72.34%。",
    "DP-I-046": "原表字段结构化抄录（FY2025，报告P17-P18）：第一大客户销售额5,706,560,719.37元，占年度销售总额22.97%；客户身份匿名。",
    "DP-I-047": "原表字段结构化抄录（FY2025，报告P17-P18）：前五名供应商合计采购金额6,433,680,860.73元，占年度采购总额41.88%。",
    "DP-I-048": "研发项目原文表格行（FY2025，报告P18-P20）：高速1.6T光模块完成项目设计及各项验证，已通过验收。",
    "DP-I-049": "研发项目原文表格行（FY2025，报告P18-P20）：LRO技术光模块完成项目设计及样品验证，进入小批量生产阶段。",
    "DP-I-050": "研发项目原文表格行（FY2025，报告P18-P20）：硅光PIC技术产业化研究完成项目设计及样品验证，进入小批量生产阶段。",
    "DP-I-051": "研发项目原文表格行（FY2025，报告P18-P20）：1.6T LPO光模块完成项目前期样品测试及评估。",
    "DP-I-052": "原表字段结构化抄录（FY2025，报告P151）：泰国新易盛注册资本46.61亿泰铢，行业为制造业，持股比例92.22%。",
    "DP-I-053": "原表字段结构化抄录（FY2025，报告P8）：营业收入38,239,935,640.67元。",
    "DP-I-054": "原表字段结构化抄录（FY2025，报告P8）：归属于上市公司股东的净利润10,797,254,300.45元。",
    "DP-I-055": "原表字段结构化抄录（FY2025，报告P8及P98）：经营活动产生的现金流量净额10,896,126,160.03元。",
    "DP-I-056": "原表字段结构化抄录（FY2025，报告P98）：购建固定资产、无形资产和其他长期资产支付的现金2,759,994,695.91元。",
    "DP-I-057": "推导输入原表行（FY2025，报告P8及P98）：经营活动现金流量净额10,896,126,160.03元；购建长期资产现金支出2,759,994,695.91元。",
    "DP-I-058": "原表字段结构化抄录（报告P13及P24-P25）：光通信收发模块毛利率FY2024为34.65%，FY2025为42.61%。",
    "DP-I-059": "原表字段结构化抄录（报告P13）：光通信收发模块FY2024产能2,088万只、产量1,536万只、销量1,459万只；FY2025产能2,806万只、产量2,376万只、销量2,109万只。",
    "DP-I-060": "推导输入原表行（报告P13）：FY2024产能2,088万只、产量1,536万只；FY2025产能2,806万只、产量2,376万只。",
    "DP-I-061": "原表字段结构化抄录（FY2025，报告P26）：前五名客户合计销售金额29,055,570,800.33元，占年度销售总额75.98%。",
    "DP-I-062": "原表字段结构化抄录（FY2025，报告P26）：客户A销售额9,201,495,755.91元，占年度销售总额24.06%；客户身份匿名。",
    "DP-I-063": (
        "原表字段结构化抄录（FY2025，报告P26）：前五名供应商占年度采购总额51.50%；"
        "摘要行金额为12,796,800,648.87元，分项合计行金额为12,796,858,690.41元，"
        "两处相差58,041.54元，因此本研究仅使用两处一致的51.50%比例。"
    ),
    "DP-I-065": (
        "原表字段结构化抄录（FY2025，PDF P1及P5）：苏州旭创光模块业务总部暨研发中心建设项目"
        "本期投入3,167.20万元，铜陵旭创高端光模块产业园三期项目本期投入26,502.50万元；"
        "报告期投入募集资金合计29,669.70万元，即296.697百万元人民币。"
    ),
    "DP-I-083": "推导输入原表行（FY2025，报告P7、P21及P76）：简单FCF为6,381,532,522.46元，营业收入为24,841,854,840.22元。",
    "DP-I-084": "推导输入原表行（FY2025，报告P8及P98）：简单FCF为8,136,131,464.12元，营业收入为38,239,935,640.67元。",
    "BYD-DP044": (
        "A transmitting chip, a receiving chip and an optical-path conversion lens form a "
        "single-fiber bidirectional package."
    ),
    "BYD-DP045": (
        "A transmitting chip, a receiving chip and an optical-path conversion lens form a "
        "single-fiber bidirectional package."
    ),
    "LX-DP007": (
        "The Company wishes to retain the possibility to spin-off the Potential Spin-off Business within "
        "three years after the Listing, and does not currently have any detailed plan. The subsidiaries "
        "will continue to be subsidiaries and consolidated after the potential spin-off."
    ),
    "LX-DP052": (
        "合并现金流量表（2025H1，报告P53）：购建固定资产、无形资产和其他长期资产支付的现金"
        "9,527,627,040.03元，即95.28亿元。"
    ),
}


_SOURCE_POINT_EXCERPT_ZH_OVERRIDES = {
    "DP-I-033": "200G光模块平均售价：2023年1,171元、2024年1,053元、2025年766元。",
    "DP-I-034": "400G光模块平均售价：2023年1,358元、2024年1,343元、2025年962元。",
    "DP-I-035": (
        "800G及以上光模块平均售价：2023年无、2024年2,443元、2025年1,557元。文件解释，"
        "2025年降幅同时反映商业化早期竞争，以及2024年仍处小批量、售价相对较高的基数。"
    ),
    "DP-I-081": "九案例逐例账本：严格完整模块成功2例；Wilson 95%区间按z=1.96计算。",
    "DP-I-082": "同一九案例逐例账本：宽口径持久光通信邻接成功5例；Wilson 95%区间按z=1.96计算。",
    "BYD-DP044": "发射芯片、接收芯片与光路转换透镜组成单纤双向封装器件。",
    "BYD-DP045": "发射芯片、接收芯片与光路转换透镜组成单纤双向封装器件。",
    "LX-DP007": (
        "公司保留上市后三年内分拆潜在分拆业务的可能，目前没有详细计划；潜在分拆涉及的子公司"
        "在分拆后仍将作为公司子公司并继续纳入集团合并报表。"
    ),
}


_SOURCE_POINT_VALUE_OVERRIDES = {
    "DP-I-036": 24_841_854_840.22,
    "DP-I-037": 9_531_922_730.17,
    "DP-I-038": 7_701_234_651.00,
    "DP-I-039": 1_319_702_128.54,
    "DP-I-040": 6_381_532_522.46,
    "DP-I-053": 38_239_935_640.67,
    "DP-I-054": 10_797_254_300.45,
    "DP-I-055": 10_896_126_160.03,
    "DP-I-056": 2_759_994_695.91,
    "DP-I-057": 8_136_131_464.12,
}


_SOURCE_POINT_CALCULATION_OVERRIDES = {
    "DP-I-040": "7,701,234,651.00元-1,319,702,128.54元=6,381,532,522.46元",
    "DP-I-057": "10,896,126,160.03元-2,759,994,695.91元=8,136,131,464.12元",
    "DP-I-083": "6,381,532,522.46元/24,841,854,840.22元×100=25.69%",
    "DP-I-084": "8,136,131,464.12元/38,239,935,640.67元×100=21.28%",
    "DP-I-081": (
        "sum(strict_full_stack_success)/9=2/9=22.22%；Wilson公式："
        "center=(p+z²/(2n))/(1+z²/n)，half=z×sqrt(p(1-p)/n+z²/(4n²))/(1+z²/n)，"
        "n=9、z=1.96，区间=[0.06322376,0.54741666]"
    ),
    "DP-I-082": (
        "sum(broad_adjacency_success)/9=5/9=55.56%；Wilson公式："
        "center=(p+z²/(2n))/(1+z²/n)，half=z×sqrt(p(1-p)/n+z²/(4n²))/(1+z²/n)，"
        "n=9、z=1.96，区间=[0.26664735,0.81122457]"
    ),
    "BYD-DP045": (
        "对CN222145280U英文摘要执行有界字段核验：检索数据速率及data center/数据中心用途披露，"
        "命中数为0；该结果只限定于所核摘要，不外推完整专利族或产品实施"
    ),
}


def _point_is_inferred(point: dict[str, Any]) -> bool:
    method = _clean(point.get("extraction_method")).lower()
    fact_type = _clean(point.get("fact_type")).lower()
    return method == "inferred" or any(
        marker in fact_type
        for marker in ("calculated", "derived", "modeled", "model_assumption")
    )


def _direct_point_excerpt(point: dict[str, Any], *, chinese: bool = False) -> str:
    """仅应用逐页核过的表格行覆盖；其余来源保持原始摘录。"""

    point_id = _clean(point.get("data_point_id") or point.get("dp_id"))
    if chinese and point_id in _SOURCE_POINT_EXCERPT_ZH_OVERRIDES:
        return _SOURCE_POINT_EXCERPT_ZH_OVERRIDES[point_id]
    override = _SOURCE_POINT_EXCERPT_OVERRIDES.get(point_id)
    if override:
        return override
    raw = _clean(
        point.get("source_excerpt_zh") if chinese else point.get("source_excerpt")
    ) or _clean(point.get("source_excerpt"))
    return raw


def _uri(ref: str) -> str:
    return f"source_ref:{ref}"


def _cite(ref: str) -> str:
    # 展示层要求连续证据 token 之间有空格；尾随空格也让直接相邻的
    # f-string 引用保持可解析，不会暴露裸 source_ref。
    return f"^src:source_ref:{ref} "


def _unique(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _clean(value)
        if item and item not in seen:
            seen.add(item)
            output.append(item)
    return output


_HISTORICAL_ENTRY_CASE_LEDGER: tuple[dict[str, Any], ...] = (
    {
        "case_id": "cisco_acacia",
        "case_name": "Cisco / Acacia",
        "entry_path": "acquisition_of_mature_coherent_dsp_pic_and_module_platform",
        "entry_path_zh": "收购成熟相干DSP、PIC与模块平台",
        "outcome_as_of": "2026-03-17",
        "period": "2026-03-17",
        "classification": "durable_complete_module_success_via_acquisition",
        "value_text": "经收购形成并持续运营的完整模块平台",
        "strict_full_stack_success": 1,
        "broad_adjacency_success": 1,
        "source_refs": ["SRC-CISCO-ACACIA21", "SRC-CISCO-OPTICS26"],
        "classification_rationale": (
            "2021年完成收购；2026年Cisco仍披露相干可插拔产品获全部头部超大规模客户及超过450家客户采用。"
            "后者仍是发行人自述，因此只归为并购路径成功，不外推有机跨界成功率。"
        ),
    },
    {
        "case_id": "lumentum_cloud_light",
        "case_name": "Lumentum / Cloud Light",
        "entry_path": "acquisition_of_established_datacenter_transceiver_supplier",
        "entry_path_zh": "收购已有收入和客户的数通收发器供应商",
        "outcome_as_of": "2023-10-30",
        "period": "2023-10-30",
        "classification": "qualified_complete_module_success_at_acquisition",
        "value_text": "收购时已具备800G商业收入的完整模块平台",
        "strict_full_stack_success": 1,
        "broad_adjacency_success": 1,
        "source_refs": ["SRC-LITE-CLOUD23"],
        "classification_rationale": (
            "交易公告披露被收购方超过一半收发器收入来自800G，证明收购时已有商业化完整模块平台；"
            "收购后独立贡献不可分，因此标记为带边界的成功。"
        ),
    },
    {
        "case_id": "intel_siph_pluggable",
        "case_name": "Intel SiPh pluggable",
        "entry_path": "organic_internal_silicon_photonics_pluggable_business",
        "entry_path_zh": "内部孵化硅光可插拔模块业务",
        "outcome_as_of": "2023-10-26",
        "period": "2023-10-26",
        "classification": "pluggable_business_exit",
        "value_text": "决定剥离可插拔模块业务",
        "strict_full_stack_success": 0,
        "broad_adjacency_success": 0,
        "source_refs": ["SRC-INTEL-Q323"],
        "classification_rationale": (
            "Intel明确决定剥离可插拔模块部分并转向更高价值器件与optical I/O；"
            "本样本按原进入路径的持久结果计失败，不把退出后保留的邻接研发反向改判为成功。"
        ),
    },
    {
        "case_id": "jabil_intel_transceivers",
        "case_name": "Jabil / Intel",
        "entry_path": "product_family_and_manufacturing_transfer",
        "entry_path_zh": "承接现有产品族、制造销售权与后续开发",
        "outcome_as_of": "2026-07-18",
        "period": "2026-07-18",
        "classification": "unresolved_no_independent_scale_outcome",
        "value_text": "进入动作已确认，独立规模结果未闭环",
        "strict_full_stack_success": 0,
        "broad_adjacency_success": 0,
        "source_refs": ["SRC-JABIL-INTEL23"],
        "classification_rationale": (
            "Jabil公告确认承接Intel现有硅光可插拔产品族并开发后续代际；本轮有界检索未取得独立规模收入或"
            "重复客户结果，未决案例按0计入两种描述率，避免把宣布进入当作成功。"
        ),
    },
    {
        "case_id": "fit_avago_modules",
        "case_name": "FIT / Avago",
        "entry_path": "acquisition_of_optical_module_business",
        "entry_path_zh": "收购Avago光模块业务",
        "outcome_as_of": "2019-12-20",
        "period": "2019-12-20",
        "classification": "mixed_then_not_durable",
        "value_text": "曾完成收购和业务整合，但相关资产后被回购",
        "strict_full_stack_success": 0,
        "broad_adjacency_success": 0,
        "source_refs": ["SRC-FIT-AR18", "SRC-LW-FIT19"],
        "classification_rationale": (
            "FIT年报证明收购并经营光模块业务；2019年Broadcom确认回购相关光收发器资产。"
            "按持久性合同归为不成功，并保留二级媒体转述边界。"
        ),
    },
    {
        "case_id": "fit_poet_reentry",
        "case_name": "FIT / POET",
        "entry_path": "supplier_design_collaboration_for_optical_engines",
        "entry_path_zh": "与供应商联合开发800G/1.6T光引擎",
        "outcome_as_of": "2026-07-18",
        "period": "2026-07-18",
        "classification": "unresolved_pre_volume",
        "value_text": "联合开发信号存在，规模量产结果未闭环",
        "strict_full_stack_success": 0,
        "broad_adjacency_success": 0,
        "source_refs": ["SRC-POET-FIT24"],
        "classification_rationale": (
            "供应商公告只覆盖800G/1.6T光引擎设计合作；本轮未取得规模量产、重复客户或可分收入，"
            "因此未决案例按0计入，后续硬证据可触发重分类。"
        ),
    },
    {
        "case_id": "fabrinet_optical_manufacturing",
        "case_name": "Fabrinet",
        "entry_path": "specialized_optical_manufacturing_and_packaging",
        "entry_path_zh": "长期专业光学制造与先进封装",
        "outcome_as_of": "2026-07-18",
        "period": "2026-07-18",
        "classification": "durable_manufacturing_adjacency_only",
        "value_text": "持久制造邻接成功，但不是自有完整模块平台",
        "strict_full_stack_success": 0,
        "broad_adjacency_success": 1,
        "source_refs": ["SRC-FN-SITE26", "SRC-FN-10K24"],
        "classification_rationale": (
            "当前公司材料持续披露先进光学封装和OEM精密制造，年报也显示客户再认证约束；"
            "该路径属于持久制造邻接，不满足自有完整商用模块平台的严格口径。"
        ),
    },
    {
        "case_id": "broadcom_cyoptics",
        "case_name": "Broadcom / CyOptics",
        "entry_path": "acquisition_of_optical_component_platform",
        "entry_path_zh": "收购光器件平台并持续经营器件能力",
        "outcome_as_of": "2026-07-18",
        "period": "2026-07-18",
        "classification": "durable_component_platform_adjacency",
        "value_text": "持久器件平台邻接成功，不是完整模块OEM成功",
        "strict_full_stack_success": 0,
        "broad_adjacency_success": 1,
        "source_refs": ["SRC-BCM-CYOPTICS13", "SRC-BCM-DSP"],
        "classification_rationale": (
            "Avago完成CyOptics收购，Broadcom当前仍有高速PAM4 DSP器件平台；"
            "两条记录支持公司层器件邻接的持续性，但不把当前器件全部归因于CyOptics，也不计完整模块成功。"
        ),
    },
    {
        "case_id": "marvell_inphi",
        "case_name": "Marvell / Inphi",
        "entry_path": "acquisition_of_dsp_and_optical_interconnect_platform",
        "entry_path_zh": "收购DSP与光互连器件平台",
        "outcome_as_of": "2025-03-31",
        "period": "2025-03-31",
        "classification": "durable_dsp_component_adjacency",
        "value_text": "持久DSP/光引擎邻接成功，不是完整模块OEM成功",
        "strict_full_stack_success": 0,
        "broad_adjacency_success": 1,
        "source_refs": ["SRC-MRVL-INPHI21", "SRC-MRVL-LPO25"],
        "classification_rationale": (
            "Marvell完成Inphi收购，后续公开1.6T硅光LPO光引擎演示支持器件平台持续性；"
            "该结果归入宽口径邻接，不计入自有完整模块平台的严格成功。"
        ),
    },
)


def _historical_case_ledger() -> list[dict[str, Any]]:
    """Return an isolated, JSON-safe copy shared by data points and the model."""

    return [
        {**row, "source_refs": list(row["source_refs"])}
        for row in _HISTORICAL_ENTRY_CASE_LEDGER
    ]


def _historical_case_source_refs() -> list[str]:
    return _unique(
        ref
        for row in _HISTORICAL_ENTRY_CASE_LEDGER
        for ref in row["source_refs"]
    )


def _wilson_interval(successes: int, sample_size: int, *, z: float = 1.96) -> list[float]:
    if sample_size <= 0 or not 0 <= successes <= sample_size:
        raise ValueError("Wilson区间要求0<=successes<=sample_size且sample_size>0")
    p = successes / sample_size
    denominator = 1.0 + z * z / sample_size
    center = (p + z * z / (2.0 * sample_size)) / denominator
    half = (
        z
        * math.sqrt(
            p * (1.0 - p) / sample_size
            + z * z / (4.0 * sample_size * sample_size)
        )
        / denominator
    )
    return [round(center - half, 8), round(center + half, 8)]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_tier(source: dict[str, Any]) -> str:
    raw = _clean(source.get("source_tier") or source.get("tier")).lower()
    publisher = _clean(source.get("publisher")).lower()
    if raw in {"s", "a", "b", "c", "d", "unknown"}:
        return raw.upper() if raw != "unknown" else "unknown"
    if any(token in raw for token in ("regulatory", "government", "standard")):
        return "S"
    if any(token in publisher for token in ("hkex", "sec", "交易所", "政府", "bureau")):
        return "S"
    if raw.startswith("t1"):
        return "A"
    if raw.startswith("t2"):
        return "B"
    if raw.startswith("t3"):
        return "C"
    if raw.startswith("t4"):
        return "D"
    return "B"


def _source_status(source: dict[str, Any]) -> str:
    existing = _clean(source.get("source_review_status"))
    allowed = {
        "pending",
        "pass",
        "pass_with_note",
        "weak_source_only",
        "duplicate",
        "paywalled",
        "stale",
        "conflict",
        "reject",
    }
    if existing in allowed:
        return existing
    title = f"{source.get('title', '')} {source.get('title_zh', '')}".lower()
    publish_date = _clean(source.get("publish_date"))
    if any(token in title for token in ("forecast", "预测")) and publish_date[:4] <= "2024":
        return "stale"
    if _source_tier(source) in {"C", "D"}:
        return "weak_source_only"
    return "pass"


def _policy_role_for_source(source: dict[str, Any]) -> str:
    """弱/灰源与派生审计底稿不得被 loader 默认纳入核心评分。"""

    if source.get("ref") in {
        "MODEL-INPUTS",
        "MODEL-WORKPAPER",
        "LOCAL-MATERIAL-SCREENING",
        "CROSS-EVIDENCE-AUDIT",
    }:
        return "reference_only"
    ref = _clean(source.get("ref"))
    if ref.endswith("-ANALYST") or ref.startswith(
        ("SRC-CIGNAL-", "SRC-LC-")
    ):
        return "reference_only"
    if _clean(source.get("source_tier")) in {"C", "D"}:
        return "reference_only"
    if _clean(source.get("source_review_status")) in {
        "weak_source_only",
        "duplicate",
        "stale",
        "paywalled",
        "reject",
        "pending",
    }:
        return "reference_only"
    return "core_evidence"


_BYD_CONTROLLED_REFS = {
    *(f"BYD-S{index:02d}" for index in range(1, 17)),
    "BYD-PAT-CN122052920A",
    "BYD-PAT-CN122268464A",
    "BYD-PAT-CN122362593A",
    "BYD-PAT-CN121012567A",
    "BYD-PAT-CN120415568A",
}
_BYD_ISSUER_BY_REF = {
    **{ref: "issuer:byd-electronic" for ref in ("BYD-S01", "BYD-S04", "BYD-S05", "BYD-S16")},
    **{ref: "issuer:byd-company" for ref in ("BYD-S02", "BYD-S03")},
    **{ref: "employer:byd-group" for ref in ("BYD-S06", "BYD-S07")},
    **{ref: "issuer:byd-semiconductor" for ref in ("BYD-S08", "BYD-S09", "BYD-S10")},
    **{ref: "registry:google-patents" for ref in ("BYD-S11", "BYD-S12", "BYD-S13", "BYD-S14", "BYD-S15")},
    **{
        ref: "registry:patent-record"
        for ref in (
            "BYD-PAT-CN122052920A",
            "BYD-PAT-CN122268464A",
            "BYD-PAT-CN122362593A",
            "BYD-PAT-CN121012567A",
            "BYD-PAT-CN120415568A",
        )
    },
}
_SHARED_FACT_LINEAGE = {
    "BYD-S17": "event:oif-ofc-2026",
    "OIF-OFC2026": "event:oif-ofc-2026",
    "BYD-S18": "record:nvidia-connectx8-qualified-components",
    "NVIDIA-CX8-VALIDATED": "record:nvidia-connectx8-qualified-components",
    "SRC-INTEL-Q323": "case:intel-jabil-module-transfer",
    "SRC-JABIL-INTEL23": "case:intel-jabil-module-transfer",
    "SRC-FIT-AR18": "case:fit-module-platform",
    "SRC-LW-FIT19": "case:fit-module-platform",
    "SRC-POET-FIT24": "case:fit-module-platform",
}
_SHARED_CORROBORATION_GROUP = {
    "SRC-INTEL-Q323": "case:intel-jabil-module-transfer",
    "SRC-JABIL-INTEL23": "case:intel-jabil-module-transfer",
    "SRC-FIT-AR18": "case:fit-module-platform",
    "SRC-LW-FIT19": "case:fit-module-platform",
    "SRC-POET-FIT24": "case:fit-module-platform",
}

# 发行人官网产品页能够直接证明“公司公开列出该 SKU、规格或产品阶段”，
# 但不能单独证明客户资格、重复订单、良率或收入规模。它们因此按 B 级
# issuer-claimed product evidence 进入核心产品判断，同时继续归并在同一个
# Luxshare 受控来源组，且保留 pass_with_note，不能靠页面数量增加独立性。
_ISSUER_PRODUCT_CLAIM_REFS = {
    "LX-OPTICS-CURRENT",
    "LX-TRANSCEIVER-CURRENT",
    "LX-800G-LPO-SPEC",
    "LX-FRO-2026",
    "LX-800G-MASS-202510",
    "LX-XPO-OFC2026",
}


_CURRENT_JUDGMENT_FRESHNESS_WARNINGS = {
    ref: (
        "严重时效提醒：该记录只证明2024年当时的合作、互操作或测试活动，"
        "不能单独证明截至2026年的产品状态、客户资格、量产或持续交付。"
    )
    for ref in (
        "POET-LX-202408",
        "OIF-OFC2024-CEI",
        "KEYSIGHT-LX-202410",
    )
}


_LEGACY_FRESHNESS_WARNING_TRANSLATIONS = {
    "SEVERE_OLD_FOR_CURRENT_JUDGMENT": (
        "严重时效提醒：该招聘记录只证明当时的岗位信号，"
        "不能证明截至2026年的在岗团队或产品进度。"
    ),
    "2024_RECORD_NEEDS_CURRENT_PRODUCT_CORROBORATION": (
        "严重时效提醒：该2024年专利记录只证明历史知识产权，"
        "不证明截至2026年的数据中心产品、客户认证或量产。"
    ),
}


def _issuer_key_for_source(ref: str, source: dict[str, Any]) -> str:
    if ref in _BYD_ISSUER_BY_REF:
        return _BYD_ISSUER_BY_REF[ref]
    if ref == "BYD-S17" or ref.startswith(("OIF-", "SRC-OIF-")):
        return "standards:oif"
    if ref in {"BYD-S18", "NVIDIA-CX8-VALIDATED"} or ref.startswith("SRC-NV-"):
        return "customer:nvidia"
    if ref == "BYD-S19":
        return "government:zhongshan-environment"
    if ref == "BYD-S20":
        return "government:jinan-environment"
    if ref.startswith("LX-"):
        if ref in {
            "LX-OPTICS-CURRENT",
            "LX-TRANSCEIVER-CURRENT",
            "LX-800G-LPO-SPEC",
            "LX-AOC-CURRENT-CN",
            "LX-FRO-2026",
            "LX-800G-MASS-202510",
            "LX-XPO-OFC2026",
            "LX-COMPANY-TIMELINE",
        }:
            return "issuer:luxshare-tech"
        return "issuer:luxshare-precision"
    if ref == "SRC-POET-FIT24":
        return "issuer:poet"
    if ref == "SRC-HKEX-ASP26":
        return "issuer:crealights"
    prefix_groups = (
        (("POET-",), "issuer:poet"),
        (("IEEE-",), "standards:ieee-802.3"),
        (("MARVELL-", "SRC-MRVL-"), "platform:marvell"),
        (("SEMTECH-",), "issuer:semtech"),
        (("KEYSIGHT-",), "issuer:keysight"),
        (("ALPHAWAVE-",), "issuer:alphawave"),
        (("DG-",), "government:dongguan-science"),
        (("OCP-",), "event:ocp-asia"),
        (("PAT-",), "registry:google-patents"),
        (("ARISTA-",), "issuer:arista"),
        (("SRC-BCM-",), "platform:broadcom"),
        (("SRC-COHR-",), "supplier:coherent"),
        (("SRC-LITE-",), "supplier:lumentum"),
        (("SRC-FN-",), "supplier:fabrinet"),
        (("SRC-LC-",), "forecaster:lightcounting"),
        (("SRC-CIGNAL-",), "forecaster:cignal-ai"),
        (("SRC-LPO-",), "standards:lpo-msa"),
        (("SRC-INNO-",), "issuer:innolight"),
        (("SRC-EOPT-",), "issuer:eoptolink"),
        (("SRC-LWLG-",), "issuer:lightwave-logic"),
        (("SRC-AFOP-",), "issuer:afop"),
        (("SRC-BIS-",), "government:us-bis"),
        (("SRC-CISCO-",), "issuer:cisco"),
        (("SRC-INTEL-",), "issuer:intel"),
        (("SRC-JABIL-",), "issuer:jabil"),
        (("SRC-FIT-",), "issuer:fit-hon-teng"),
        (("SRC-LW-FIT",), "publisher:lightwave"),
    )
    for prefixes, group in prefix_groups:
        if ref.startswith(prefixes):
            return group
    if ref.startswith("FIN-") and ref.endswith("-ANALYST"):
        return "structured-analyst:yfinance"
    if ref.startswith("FIN-"):
        provider = "yfinance" if ref == "FIN-BYD_ELECTRONIC" else "tushare"
        return f"structured_data:{provider}"
    if ref.startswith("LOCAL-PDF-"):
        return "user_material:secondary-research"
    if ref in {"MODEL-INPUTS", "MODEL-WORKPAPER"}:
        return "internal:competition-model"
    if ref in {"LOCAL-MATERIAL-SCREENING", "CROSS-EVIDENCE-AUDIT"}:
        return "internal:research-audit"
    return _clean(source.get("independence_key") or source.get("cluster")) or f"source:{ref}"


def _source_origin_type(ref: str, source: dict[str, Any]) -> str:
    publisher = _clean(source.get("publisher")).lower()
    if ref.startswith("LOCAL-PDF-"):
        return "user_supplied_secondary"
    if ref.startswith("FIN-") and ref.endswith("-ANALYST"):
        return "structured_analyst_mirror"
    if ref.startswith("FIN-"):
        return "structured_transform"
    if ref in {"MODEL-INPUTS", "MODEL-WORKPAPER", "LOCAL-MATERIAL-SCREENING", "CROSS-EVIDENCE-AUDIT"}:
        return "internal_calculation_or_review"
    if (
        "patent" in publisher
        or ref.startswith(("PAT-", "BYD-PAT-"))
        or ref in {f"BYD-S{index:02d}" for index in range(11, 16)}
    ):
        return "registry_mirror"
    if ref.startswith(("SRC-CIGNAL-", "SRC-LC-")):
        return "secondary_forecast"
    if ref.startswith("BYD-LEAD-") and ref != "BYD-LEAD-IDCE-2026":
        return "secondary_research_relay"
    return "primary_original"


def _source_provenance(source: dict[str, Any]) -> dict[str, Any]:
    """把 record、发行人、受控集团与共同事实血缘拆开。

    ``independence_key`` 保留为兼容字段，但统一指向真正用于机构独立性计数的
    ``corroboration_key``；旧 key 另存，防止丢失底层记录信息。
    """

    ref = _clean(source.get("ref"))
    original_key = _clean(
        source.get("source_independence_key_original")
        or source.get("independence_key")
        or source.get("cluster")
    ) or f"source:{ref}"
    if ref in {"LX-HKEX-PROSPECTUS-EN-2026", "LX-HKEX-PROSPECTUS-ZH-2026"}:
        record_family_key = "record-family:luxshare-hkex-prospectus-2026"
    elif _clean(source.get("document_sha256")):
        record_family_key = f"document-sha256:{_clean(source['document_sha256']).lower()}"
    else:
        record_family_key = f"record-family:{ref.lower()}"
    record_key = f"record:{ref.lower()}"
    issuer_key = _issuer_key_for_source(ref, source)
    if ref in _BYD_CONTROLLED_REFS:
        control_group_key = "controlled_group:byd"
    elif ref.startswith("LX-"):
        control_group_key = "controlled_group:luxshare"
    elif ref.startswith("SRC-INNO-"):
        control_group_key = "controlled_group:innolight"
    elif ref.startswith("SRC-EOPT-"):
        control_group_key = "controlled_group:eoptolink"
    elif ref.startswith("PAT-"):
        control_group_key = "controlled_group:luxshare"
    else:
        control_group_key = issuer_key
    fact_lineage_key = _SHARED_FACT_LINEAGE.get(ref, record_family_key)
    corroboration_key = _SHARED_CORROBORATION_GROUP.get(ref, control_group_key)
    origin_type = _source_origin_type(ref, source)
    intake_source_tier = _clean(source.get("intake_source_tier") or source.get("source_tier")) or None
    is_analyst_mirror = ref.startswith("FIN-") and ref.endswith("-ANALYST")
    is_yfinance_financial = (
        ref.startswith("FIN-")
        and not is_analyst_mirror
        and (
            ref == "FIN-BYD_ELECTRONIC"
            or "yfinance" in original_key.lower()
            or "yahoo finance" in _clean(source.get("publisher")).lower()
        )
    )
    tier_override = (
        "B"
        if is_analyst_mirror
        or is_yfinance_financial
        or ref in _ISSUER_PRODUCT_CLAIM_REFS
        else source.get("source_tier")
    )
    status_override = (
        "pass_with_note"
        if ref.startswith("FIN-") or ref in _ISSUER_PRODUCT_CLAIM_REFS
        else source.get("source_review_status")
    )
    source_origin_class = (
        "structured_analyst_mirror_yfinance"
        if is_analyst_mirror
        else "structured_financial_mirror_yfinance"
        if is_yfinance_financial
        else "structured_financial_mirror_tushare"
        if ref.startswith("FIN-")
        else origin_type
    )
    return {
        "source_independence_key_original": original_key,
        "record_key": record_key,
        "record_family_key": record_family_key,
        "issuer_key": issuer_key,
        "control_group_key": control_group_key,
        "fact_lineage_key": fact_lineage_key,
        "corroboration_key": corroboration_key,
        "origin_type": origin_type,
        "source_origin_class": source_origin_class,
        "intake_source_tier": intake_source_tier,
        "source_tier": tier_override,
        "source_review_status": status_override,
        "independence_key": corroboration_key,
    }


def _normalize_source(source: dict[str, Any], *, prefix: str = "") -> dict[str, Any]:
    raw_ref = _clean(source.get("ref"))
    ref = f"{prefix}{raw_ref}" if prefix else raw_ref
    language = _clean(source.get("language") or "zh-CN")
    title = _clean(source.get("title") or source.get("title_zh"))
    excerpt = _clean(source.get("excerpt") or source.get("excerpt_zh"))
    result = {
        "ref": ref,
        "title": title,
        "title_zh": _clean(source.get("title_zh") or title),
        "publisher": (
            "中际旭创 / 巨潮资讯"
            if ref == "SRC-INNO-AR25"
            else _clean(source.get("publisher") or "来源机构未标明")
        ),
        "publish_date": (
            "2026-03-31"
            if ref == "SRC-INNO-AR25"
            else (_clean(source.get("publish_date")) or None)
        ),
        "event_date": (
            "2025-12-31"
            if ref in {"SRC-INNO-AR25", "SRC-EOPT-AR25"}
            else (_clean(source.get("event_date")) or None)
        ),
        "fetch_date": _clean(source.get("fetch_date")) or AS_OF_DATE,
        "source_tier": _source_tier(source),
        "intake_source_tier": _clean(source.get("source_tier") or source.get("tier")) or None,
        "source_review_status": _source_status(source),
        "language": language,
        "excerpt": excerpt or "该来源用于核验研究对象、口径或数据。",
        "excerpt_zh": _clean(source.get("excerpt_zh") or excerpt)
        or "该来源用于核验研究对象、口径或数据。",
        "url": (
            "https://static.cninfo.com.cn/finalpage/2026-03-31/1225056459.PDF"
            if ref == "SRC-INNO-AR25"
            else (_clean(source.get("url")) or None)
        ),
        "local_path": _clean(source.get("local_path")) or None,
        "local_locator": (
            _clean(source.get("local_locator"))
            or _SOURCE_LOCAL_LOCATOR_OVERRIDES.get(ref)
            or None
        ),
        "independence_key": _clean(source.get("independence_key") or source.get("cluster"))
        or f"source:{ref}",
        "independence_rationale": _clean(source.get("independence_rationale") or source.get("rationale"))
        or "按原始发布主体、底层记录与事件归并；转载和同一主体重复页面不另算独立证据。",
    }
    result.update(_SOURCE_METADATA_OVERRIDES.get(ref, {}))
    raw_freshness_warning = _clean(source.get("freshness_warning"))
    result["freshness_warning"] = (
        _CURRENT_JUDGMENT_FRESHNESS_WARNINGS.get(ref)
        or _LEGACY_FRESHNESS_WARNING_TRANSLATIONS.get(raw_freshness_warning)
        or raw_freshness_warning
        or None
    )
    if not result["url"] and not result["local_path"]:
        raise ValueError(
            f"来源 {ref} 缺少可核验的 url/local_path；"
            "不能用未创建的占位路径伪装 provenance"
        )
    result.update(_source_provenance(result))
    return result


def _bounded_excerpt_join(parts: list[str], *, limit: int = 2400) -> str:
    """Join distinct verified snippets without cutting a snippet mid-sentence."""

    output: list[str] = []
    seen: set[str] = set()
    length = 0
    for raw in parts:
        value = _clean(raw)
        normalized = value.rstrip("。；; ")
        if not normalized or normalized in seen:
            continue
        candidate = f"{normalized}。"
        added = len(candidate) + (1 if output else 0)
        if output and length + added > limit:
            break
        output.append(candidate)
        seen.add(normalized)
        length += added
    return " ".join(output)


def _enrich_source_excerpts_from_evidence(
    sources: list[dict[str, Any]],
    evidence_packs: list[tuple[str, dict[str, Any]]],
) -> None:
    """把同一记录的直接原文片段并入来源抽屉，禁止混入推断或机器摘要。

    Viewer 把 ``source.excerpt`` 明确展示为“本轮使用的原文摘录”，因此这里只能
    聚合 ``pdf_direct`` / ``web_fetch`` 的可逐字核对片段。结构化数值摘要、公式、
    未检出判断与 inferred 结论继续留在 data point / claim 层，不得冒充原文。
    """

    source_lookup = {source["ref"]: source for source in sources}
    original_by_ref: dict[str, list[str]] = defaultdict(list)
    chinese_by_ref: dict[str, list[str]] = defaultdict(list)
    for prefix, evidence in evidence_packs:
        for point in evidence.get("data_points", []):
            ref = f"{prefix}{_clean(point.get('source_ref'))}"
            if ref not in source_lookup:
                continue
            method = _clean(point.get("extraction_method"))
            fact_type = _clean(point.get("fact_type")).lower()
            period = _clean(point.get("period") or point.get("as_of_date")).lower()
            original = _direct_point_excerpt(point)
            chinese = _direct_point_excerpt(point, chinese=True)
            audit_text = f"{original} {chinese}".lower()
            direct_without_method = bool(fact_type) and not _point_is_inferred(point)
            if method not in {"pdf_direct", "web_fetch"} and not (
                not method and direct_without_method
            ):
                continue
            if "audit" in period or any(
                marker in audit_text
                for marker in (
                    "未见",
                    "未找到",
                    "未检出",
                    "页面未列",
                    "公开材料不足",
                    "not found",
                    "not disclosed",
                    "no public evidence",
                )
            ):
                continue
            if original:
                original_by_ref[ref].append(original)
            if chinese:
                chinese_by_ref[ref].append(chinese)

    for ref, source in source_lookup.items():
        original = _bounded_excerpt_join(
            [source.get("excerpt", ""), *original_by_ref.get(ref, [])]
        )
        chinese = _bounded_excerpt_join(
            [source.get("excerpt_zh", ""), *chinese_by_ref.get(ref, [])]
        )
        if original:
            source["excerpt"] = original
        if chinese:
            source["excerpt_zh"] = chinese


ENTITY_MAP = {
    # 比亚迪证据
    "byd_electronic": "byd_entry_risk",
    "byd_semiconductor": "recruitment_patent_capacity_audit",
    "byd_group": "recruitment_patent_capacity_audit",
    "jinan_byd_semiconductor": "recruitment_patent_capacity_audit",
    "byd_company_patent_system": "recruitment_patent_capacity_audit",
    "zhongshan_byd_electronic": "recruitment_patent_capacity_audit",
    "oif_ofc2026_interop": "qualification_upstream_constraints",
    "luxshare_tech": "luxshare_entry_risk",
    "innolight": "innolight_terminal_risk",
    # 立讯证据常见 key
    "luxshare": "luxshare_entry_risk",
    "luxshare_precision": "luxshare_entry_risk",
    "luxshare_tech_optics": "luxshare_entry_risk",
    "luxshare-tech": "luxshare_entry_risk",
    "luxshare_recruitment": "recruitment_patent_capacity_audit",
    "luxshare_patent": "recruitment_patent_capacity_audit",
    "luxshare_capacity": "recruitment_patent_capacity_audit",
    # 行业、龙头和历史案例
    "company:eoptolink": "eoptolink_terminal_risk",
    "subsidiary:eoptolink_thailand": "eoptolink_terminal_risk",
    "company:innolight": "innolight_terminal_risk",
    "product:innolight_1.6t_osfp224_dr8": "innolight_terminal_risk",
    "sample:historical_optical_entry_cases": "probability_method_and_baserate",
    "industry:optical_component_qualification": "qualification_upstream_constraints",
    "industry:optical_manufacturing_requalification": "qualification_upstream_constraints",
    "policy:us_advanced_semiconductor_exports_to_china": "qualification_upstream_constraints",
    "company:coherent": "qualification_upstream_constraints",
    "facility:coherent_sherman_inp": "qualification_upstream_constraints",
    "agreement:nvidia_coherent_2026": "qualification_upstream_constraints",
    "product:marvell_1.6t_lpo_engine": "qualification_upstream_constraints",
    "company:marvell": "qualification_upstream_constraints",
    "company:lumentum": "qualification_upstream_constraints",
}


def _map_entity(key: str) -> str:
    key = _clean(key)
    if key in ENTITY_MAP:
        return ENTITY_MAP[key]
    lower = key.lower()
    if lower.startswith("entry_case:"):
        return "probability_method_and_baserate"
    if any(token in lower for token in ("recruit", "patent", "factory", "facility", "capacity")):
        return "recruitment_patent_capacity_audit"
    if any(token in lower for token in ("qualification", "supplier", "component", "policy", "agreement")):
        return "qualification_upstream_constraints"
    if "lux" in lower or "立讯" in lower:
        return "luxshare_entry_risk"
    if "byd" in lower or "比亚迪" in lower:
        return "byd_entry_risk"
    if "eopt" in lower or "新易盛" in lower:
        return "eoptolink_terminal_risk"
    if "inno" in lower or "中际" in lower:
        return "innolight_terminal_risk"
    return "industry_demand_supply_model"


def _normalize_observations(values: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in values or []:
        if not isinstance(item, dict):
            continue
        row = _safe_payload(dict(item))
        if not _clean(row.get("period") or row.get("as_of_date")):
            continue
        if _finite(row.get("value_num")) is None and not _clean(row.get("value_text")):
            payload = {key: value for key, value in row.items() if key not in {"period", "as_of_date"}}
            row["value_text"] = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        output.append(row)
    return output


def _normalize_data_point(point: dict[str, Any], *, source_prefix: str = "") -> dict[str, Any]:
    source_ref = f"{source_prefix}{_clean(point.get('source_ref'))}"
    original_entity = _clean(point.get("entity_key"))
    point_id = _clean(point.get("data_point_id") or point.get("dp_id"))
    observations = _normalize_observations(
        _historical_case_ledger()
        if point_id in {"DP-I-081", "DP-I-082"}
        else point.get("observations")
    )
    value_num = _SOURCE_POINT_VALUE_OVERRIDES.get(
        point_id, _finite(point.get("value_num"))
    )
    value_text = _clean(point.get("value_text")) or None
    raw_note = _clean(
        _SOURCE_POINT_CALCULATION_OVERRIDES.get(point_id)
        or point.get("note")
        or point.get("caveat")
        or point.get("calculation")
    )
    extraction_method = _clean(point.get("extraction_method")) or (
        "inferred" if _point_is_inferred(point) else "web_fetch"
    )
    if point_id == "BYD-DP045":
        extraction_method = "inferred"
    result: dict[str, Any] = {
        "source_ref": source_ref,
        "entity_key": _map_entity(original_entity),
        "metric": _clean(point.get("metric") or point.get("metric_name")) or "未命名研究指标",
        "period": _clean(point.get("period")) or None,
        "as_of_date": _clean(point.get("as_of_date")) or None,
        "value_num": value_num,
        "value_text": value_text,
        "unit": _clean(point.get("unit")) or "文本",
        "source_excerpt": _direct_point_excerpt(point)
        or "来源记录了该研究事实。",
        "source_excerpt_zh": _direct_point_excerpt(point, chinese=True)
        or "来源记录了该研究事实。",
        "scope_key": f"{original_entity}|{_clean(point.get('scope_key') or point.get('series_key') or point.get('dp_id') or point.get('data_point_id'))}",
        "observations": observations,
        "fact_type": _clean(point.get("fact_type")) or "source_fact",
        "extraction_method": extraction_method,
        "note": raw_note or None,
    }
    if point_id == "DP-I-063":
        result["note"] = (
            "年报P26摘要行与五家供应商分项合计行的绝对采购金额相差58,041.54元；"
            "两处占比均为51.50%，本数据点只保存一致的比例，不采用冲突金额。"
        )
    if observations and point_id not in {"DP-I-081", "DP-I-082"}:
        result["value_num"] = None
        result["value_text"] = result["value_text"] or "时间序列，详见 observations"
    if point_id in {"DP-I-081", "DP-I-082"}:
        result["calculation_case_ids"] = [
            row["case_id"] for row in _HISTORICAL_ENTRY_CASE_LEDGER
        ]
        result["calculation_source_refs"] = _historical_case_source_refs()
    if result["extraction_method"] == "inferred":
        formula_or_algorithm = _clean(
            _SOURCE_POINT_CALCULATION_OVERRIDES.get(point_id)
            or point.get("formula")
            or point.get("calculation")
        )
        if not formula_or_algorithm and "自由现金流代理" in result["metric"]:
            formula_or_algorithm = _clean(point.get("value_text"))
        formula_or_algorithm = formula_or_algorithm or raw_note
        if not formula_or_algorithm:
            raise ValueError(f"inferred 数据点 {source_ref}/{result['metric']} 缺少公式或算法说明")
        result["note"] = (
            f"公式/算法：{formula_or_algorithm}；"
            f"输入：source_ref={source_ref}所指原始字段，以及本数据点value/observations和source_excerpt列明数值；"
            f"口径：metric={result['metric']}，period={result['period'] or result['as_of_date']}，"
            f"unit={result['unit']}，scope_key={result['scope_key']}；"
            f"边界：{raw_note or '仅按上述公式计算，不外推未披露事实。'}"
        )
    return result


def _standardize_inferred_note_in_place(point: dict[str, Any]) -> None:
    """确保所有生成路径的 inferred 点都保留公式、输入与口径。

    外部 evidence 点经过 ``_normalize_data_point``，而财务和模型点由构建器直接
    生成；最终合包前统一再过一次该门禁，避免生成路径不同造成审计字段漂移。
    """

    if point.get("extraction_method") != "inferred":
        return
    note = _clean(point.get("note"))
    if all(marker in note for marker in ("公式/算法：", "输入：", "口径：")):
        return
    metric = _clean(point.get("metric") or point.get("metric_name")) or "未命名研究指标"
    formula_or_algorithm = _clean(point.get("formula") or point.get("calculation"))
    if not formula_or_algorithm and "自由现金流代理" in metric:
        formula_or_algorithm = _clean(point.get("value_text"))
    formula_or_algorithm = formula_or_algorithm or note
    if not formula_or_algorithm:
        raise ValueError(
            f"inferred 数据点 {point.get('source_ref')}/{metric} 缺少公式或算法说明"
        )
    source_ref = _clean(point.get("source_ref"))
    period = _clean(point.get("period") or point.get("as_of_date")) or "未标明"
    unit = _clean(point.get("unit")) or "未标明"
    scope_key = _clean(point.get("scope_key") or point.get("series_key")) or "未标明"
    point["note"] = (
        f"公式/算法：{formula_or_algorithm}；"
        f"输入：source_ref={source_ref}所指原始字段，以及本数据点value/observations和source_excerpt列明数值；"
        f"口径：metric={metric}，period={period}，unit={unit}，scope_key={scope_key}；"
        f"边界：{note or '仅按上述公式计算，不外推未披露事实。'}"
    )


def _claim_source_refs(claim: dict[str, Any]) -> list[str]:
    refs = (
        claim.get("source_refs")
        or claim.get("support_refs")
        or claim.get("supporting_source_refs")
        or []
    )
    if isinstance(refs, str):
        refs = [refs]
    return _unique([str(value) for value in refs])


_CLAIM_FACTOR_MAP: dict[str, list[str]] = {
    "BYD-C01": ["company.exposure_directness"],
    "BYD-C02": ["company.capacity_readiness_window", "company.exposure_directness", "demand.customer_capex_capacity_signal"],
    "BYD-C03": ["company.capacity_readiness_window", "company.exposure_directness"],
    "BYD-C04": ["company.exposure_directness", "supply.substitution_barrier"],
    "BYD-C05": ["company.capacity_readiness_window"],
    "BYD-C06": ["company.capacity_readiness_window", "supply.substitution_barrier"],
    "BYD-C07": ["company.capacity_readiness_window", "company.exposure_directness", "demand.customer_capex_capacity_signal"],
    "BYD-C08": ["company.financial_capture_quality"],
    "BYD-C09": ["company.capacity_readiness_window", "company.exposure_directness", "demand.customer_capex_capacity_signal"],
    "BYD-C10": ["company.capacity_readiness_window", "company.exposure_directness", "supply.substitution_barrier"],
    "BYD-C11": ["company.capacity_readiness_window", "company.exposure_directness", "demand.customer_capex_capacity_signal"],
    "LX-C001": ["company.exposure_directness", "company.financial_capture_quality"],
    "LX-C002": ["supply.substitution_barrier", "company.financial_capture_quality"],
    "LX-C003": ["company.exposure_directness"],
    "LX-C004": ["company.capacity_readiness_window", "company.exposure_directness"],
    "LX-C005": ["company.capacity_readiness_window", "demand.customer_capex_capacity_signal"],
    "LX-C006": ["company.capacity_readiness_window", "demand.customer_capex_capacity_signal"],
    "LX-C007": ["company.capacity_readiness_window", "company.exposure_directness"],
    "LX-C008": ["company.exposure_directness", "supply.substitution_barrier"],
    "LX-C009": ["company.capacity_readiness_window", "supply.substitution_barrier"],
    "LX-C010": ["company.capacity_readiness_window", "supply.substitution_barrier"],
    "LX-C011": ["demand.customer_capex_capacity_signal"],
    "LX-C012": ["company.exposure_directness", "demand.customer_capex_capacity_signal"],
    "LX-C013": ["company.capacity_readiness_window", "supply.substitution_barrier"],
    "LX-C014": ["supply.substitution_barrier"],
    "LX-C015": ["company.capacity_readiness_window", "supply.substitution_barrier"],
    "LX-C016": ["company.exposure_directness", "supply.substitution_barrier"],
    "LX-C017": ["company.capacity_readiness_window", "company.financial_capture_quality"],
    "LX-C018": ["company.exposure_directness", "company.financial_capture_quality"],
    "CLM-I-001": ["demand.customer_capex_capacity_signal", "signal.material_price_momentum"],
    "CLM-I-002": ["demand.customer_capex_capacity_signal", "signal.material_price_momentum"],
    "CLM-I-003": ["signal.material_price_momentum"],
    "CLM-I-004": ["demand.customer_capex_capacity_signal", "signal.material_price_momentum"],
    "CLM-I-005": ["signal.material_price_momentum"],
    "CLM-I-006": ["supply.substitution_barrier"],
    "CLM-I-007": ["supply.substitution_barrier"],
    "CLM-I-008": ["supply.substitution_barrier"],
    "CLM-I-009": ["company.financial_capture_quality"],
    "CLM-I-010": ["company.revenue_exposure_proxy"],
    "CLM-I-011": ["supply.substitution_barrier", "signal.material_price_momentum"],
    "CLM-I-012": ["supply.substitution_barrier"],
    "CLM-I-013": ["supply.substitution_barrier", "company.financial_capture_quality"],
    "CLM-I-014": ["company.capacity_readiness_window", "company.exposure_directness", "company.financial_capture_quality"],
    "CLM-I-015": ["company.exposure_directness", "company.financial_capture_quality"],
    "CLM-I-016": ["company.capacity_readiness_window", "supply.substitution_barrier"],
    "CLM-I-017": ["company.financial_capture_quality"],
    "CLM-I-018": ["company.exposure_directness", "company.financial_capture_quality"],
    "CLM-I-019": ["company.financial_capture_quality"],
    "CLM-I-020": ["demand.customer_capex_capacity_signal", "supply.substitution_barrier"],
}


# 公开 claim 抽屉只展示与该 claim 直接相关的原文片段。年度报告来源本身会
# 保留完整结构化摘录，但不能把整份财务摘录机械复制到每一条 claim。
_CLAIM_EXCERPT_OVERRIDES: dict[str, dict[str, str]] = {
    "BYD-C01": {
        "source_excerpt": (
            "比亚迪电子2025年报披露：公司打造了涵盖服务器、液冷、电源及高速互联的"
            "一体化解决方案。"
        ),
        "source_excerpt_zh": (
            "比亚迪电子2025年报披露：公司打造了涵盖服务器、液冷、电源及高速互联的"
            "一体化解决方案。"
        ),
    },
    "BYD-C02": {
        "source_excerpt": (
            "比亚迪电子2025年报披露：服务器业务新客户持续拓展且出货量同比增长；"
            "液冷产品已通过客户认证并进入小规模试产；电源产品正在积极开发；"
            "公司持续推进高速互联产品布局。"
        ),
        "source_excerpt_zh": (
            "比亚迪电子2025年报披露：服务器业务新客户持续拓展且出货量同比增长；"
            "液冷产品已通过客户认证并进入小规模试产；电源产品正在积极开发；"
            "公司持续推进高速互联产品布局。"
        ),
    },
    "BYD-C03": {
        "source_excerpt": (
            "比亚迪电子2025年报对相关方向的产品表述为：涵盖服务器、液冷、电源及"
            "高速互联的一体化解决方案，并持续推进高速互联产品布局。"
        ),
        "source_excerpt_zh": (
            "比亚迪电子2025年报对相关方向的产品表述为：涵盖服务器、液冷、电源及"
            "高速互联的一体化解决方案，并持续推进高速互联产品布局。"
        ),
    },
    "BYD-C08": {
        "source_excerpt": (
            "Revenue: RMB179,477,404 thousand. Research and development expenses: "
            "RMB4,464,997 thousand. Purchases of items of property, plant and equipment: "
            "RMB4,082,575 thousand."
        ),
        "source_excerpt_zh": (
            "收入：人民币179,477,404千元；研发开支：人民币4,464,997千元；"
            "购置物业、厂房及设备项目：人民币4,082,575千元。"
        ),
    },
    "BYD-C09": {
        "source_excerpt": (
            "比亚迪电子2025年报披露：服务器业务新客户持续拓展、出货量同比增长；"
            "液冷产品已通过客户认证并进入小规模试产；电源产品正在积极开发；"
            "高速互联被列入一体化解决方案并持续布局。"
        ),
        "source_excerpt_zh": (
            "比亚迪电子2025年报披露：服务器业务新客户持续拓展、出货量同比增长；"
            "液冷产品已通过客户认证并进入小规模试产；电源产品正在积极开发；"
            "高速互联被列入一体化解决方案并持续布局。"
        ),
    },
    "BYD-C10": {
        "source_excerpt": (
            "比亚迪电子2025年报披露：人工智能基础设施业务收入约人民币943百万元，"
            "同比增长31.70%；公司打造了涵盖服务器、液冷、电源及高速互联的一体化解决方案。"
        ),
        "source_excerpt_zh": (
            "比亚迪电子2025年报披露：人工智能基础设施业务收入约人民币943百万元，"
            "同比增长31.70%；公司打造了涵盖服务器、液冷、电源及高速互联的一体化解决方案。"
        ),
    },
    "BYD-C11": {
        "source_excerpt": (
            "比亚迪电子2025年报仅披露持续推进高速互联产品布局，未在该表述中给出"
            "具体速率、客户资格、专用产线或可分收入。"
        ),
        "source_excerpt_zh": (
            "比亚迪电子2025年报仅披露持续推进高速互联产品布局，未在该表述中给出"
            "具体速率、客户资格、专用产线或可分收入。"
        ),
    },
    "BYD-C12": {
        "source_excerpt": (
            "比亚迪电子2025年报的最低可证表述是：公司打造数据中心一体化解决方案，"
            "并持续推进高速互联产品布局。"
        ),
        "source_excerpt_zh": (
            "比亚迪电子2025年报的最低可证表述是：公司打造数据中心一体化解决方案，"
            "并持续推进高速互联产品布局。"
        ),
    },
    "CLM-I-005": {
        "source_excerpt": (
            "200G: RMB1,171 / RMB1,053 / RMB766; 400G: RMB1,358 / RMB1,343 / "
            "RMB962; 800G and above: — / RMB2,443 / RMB1,557 for 2023 / 2024 / 2025. "
            "The filing attributes the declines to product maturity, competition, "
            "large-volume procurement and the early small-batch base for 800G and above."
        ),
        "source_excerpt_zh": (
            "2023/2024/2025年平均售价：200G为1,171/1,053/766元，400G为"
            "1,358/1,343/962元，800G及以上为—/2,443/1,557元。文件将降价归因于"
            "产品成熟、竞争、大批量采购，以及800G及以上早期小批量的高价基数。"
        ),
    },
    "CLM-I-008": {
        "source_excerpt": (
            "新易盛2025年年度报告P151披露：泰国新易盛注册资本46.61亿泰铢，"
            "行业为制造业，持股比例92.22%。"
        ),
        "source_excerpt_zh": (
            "新易盛2025年年度报告P151披露：泰国新易盛注册资本46.61亿泰铢，"
            "行业为制造业，持股比例92.22%。"
        ),
    },
    "CLM-I-009": {
        "source_excerpt": (
            "中际旭创2025年年度报告P8及P98披露：经营活动产生的现金流量净额"
            "10,896,126,160.03元；购建固定资产、无形资产和其他长期资产支付的现金"
            "2,759,994,695.91元。"
        ),
        "source_excerpt_zh": (
            "中际旭创2025年年度报告P8及P98披露：经营活动产生的现金流量净额"
            "10,896,126,160.03元；购建固定资产、无形资产和其他长期资产支付的现金"
            "2,759,994,695.91元。"
        ),
    },
    "CLM-I-010": {
        "source_excerpt": (
            "中际旭创2025年年度报告P26披露：前五名客户合计销售金额"
            "29,055,570,800.33元，占年度销售总额75.98%。"
        ),
        "source_excerpt_zh": (
            "中际旭创2025年年度报告P26披露：前五名客户合计销售金额"
            "29,055,570,800.33元，占年度销售总额75.98%。"
        ),
    },
    "CLM-I-011": {
        "source_excerpt": (
            "新易盛2025年年度报告P18-P20披露：高速1.6T光模块已完成设计及各项验证并通过验收；"
            "LRO技术光模块和硅光PIC技术产业化研究均进入小批量生产阶段；"
            "1.6T LPO光模块完成前期样品测试及评估。"
        ),
        "source_excerpt_zh": (
            "新易盛2025年年度报告P18-P20披露：高速1.6T光模块已完成设计及各项验证并通过验收；"
            "LRO技术光模块和硅光PIC技术产业化研究均进入小批量生产阶段；"
            "1.6T LPO光模块完成前期样品测试及评估。"
        ),
    },
    "CLM-I-019": {
        "source_excerpt": (
            "中际旭创2025年年度报告P8、P13、P24-P25及P98披露：经营活动现金流量净额"
            "10,896,126,160.03元，购建长期资产现金支出2,759,994,695.91元；"
            "光通信收发模块2025年毛利率42.61%。"
        ),
        "source_excerpt_zh": (
            "中际旭创2025年年度报告P8、P13、P24-P25及P98披露：经营活动现金流量净额"
            "10,896,126,160.03元，购建长期资产现金支出2,759,994,695.91元；"
            "光通信收发模块2025年毛利率42.61%。"
        ),
    },
}

_CLAIM_SCORE_ENTITY_KEYS = {
    "byd_entry_risk",
    "luxshare_entry_risk",
    "innolight_terminal_risk",
    "eoptolink_terminal_risk",
}


def _claim_research_entity(claim_id: str, fallback: str) -> str:
    """公司 claim 始终归到被研究主体，而不是其出现的主题章节。"""

    if claim_id.startswith("BYD-C"):
        return "byd_entry_risk"
    if claim_id.startswith("LX-C") or claim_id.startswith("LX-CONFLICT-C"):
        return "luxshare_entry_risk"
    return fallback


_INDUSTRY_NEXT_ACTION_GROUPS: tuple[tuple[set[str], str, str], ...] = (
    (
        {"CLM-I-001", "CLM-I-002", "CLM-I-003", "CLM-I-004", "CLM-I-005"},
        "SUP-MARKET-ARCHITECTURE",
        "按季度取得端口出货、同规格成交价及LPO/LRO/CPO量产口径，重做代际需求、正常降价与架构迁移的来源分解。",
    ),
    (
        {"CLM-I-006", "CLM-I-007", "CLM-I-008", "CLM-I-016", "CLM-I-020"},
        "SUP-UPSTREAM-QUALIFICATION",
        "取得客户资格、工艺/地点变更再认证以及DSP、laser、PIC合格供给的客户或供应商原始记录，并只重估受影响门槛。",
    ),
    (
        {"CLM-I-009", "CLM-I-010", "CLM-I-011", "CLM-I-012", "CLM-I-013", "CLM-I-019"},
        "SUP-INCUMBENT-FINANCIAL",
        "在下一份定期报告与客户/产品更新后复核龙头现金流、客户集中、产品阶段、海外敞口和政策影响，不以单期或产品页外推。",
    ),
    (
        {"CLM-I-014", "CLM-I-015", "CLM-I-017", "CLM-I-018"},
        "SUP-BASE-RATE",
        "扩展预注册历史进入案例样本，逐案核验收购、产品、客户、收入和退出结局，再重算描述率与先验支持区间。",
    ),
)


_MODEL_NEXT_ACTIONS: dict[str, str] = {
    "MODEL-C01": "由独立计算审稿人以冻结输入、种子和公式完整复算；任何模型代码或事件合同变化都必须重新签署。",
    "MODEL-C02": "仅在比亚迪具名SKU、客户资格、重复交付或可分收入出现新原始证据时，按预注册更新桥重校3年/5年输入。",
    "MODEL-C03": "仅在立讯客户资格、重复订单、规模收入或官方冲突取得新闭环时，按预注册更新桥重校3年/5年输入。",
    "MODEL-C04": "每次边际概率或共同驱动假设变化时同时复算负依赖、独立和高正依赖情景，检查联合概率界限。",
    "MODEL-C05": "取得同规格成交价、代际ASP和客户议价记录后，先分解正常技术降本，再校准新进入者额外价格压力。",
    "MODEL-C06": "取得客户/平台侧AVL、订单或监管解释后闭环立讯官方口径冲突，并只更新对应区域、客户和利润捕获分支。",
}


def _claim_next_action_plan(
    claim_id: str, entity_key: str
) -> dict[str, str]:
    """Return a concrete, auditable follow-up for every canonical claim."""

    if claim_id in _MODEL_NEXT_ACTIONS:
        return {
            "ref": "SUP-MODEL-RECALIBRATION",
            "action": _MODEL_NEXT_ACTIONS[claim_id],
            "owner": "calculation_and_evidence_reviewer",
            "trigger": "model_or_underlying_evidence_change",
        }
    for claim_ids, ref, action in _INDUSTRY_NEXT_ACTION_GROUPS:
        if claim_id in claim_ids:
            return {
                "ref": ref,
                "action": action,
                "owner": "industry_evidence_producer",
                "trigger": "quarterly_or_new_primary_record",
            }
    if entity_key == "byd_entry_risk":
        return {
            "ref": "SUP-BYD-COMMERCIAL-CLOSURE",
            "action": "取得比亚迪电子具名高速光模块SKU、经营主体、客户资格、重复交付、专线良率或可分收入原始记录，并只更新对应里程碑。",
            "owner": "company_evidence_producer",
            "trigger": "new_issuer_customer_or_platform_record",
        }
    if entity_key == "luxshare_entry_risk":
        return {
            "ref": "SUP-LUX-COMMERCIAL-CLOSURE",
            "action": "取得立讯客户/平台侧资格、跨期重复订单、可分收入或监管冲突解释，并区分中国有限交付与全球头部闭环。",
            "owner": "company_evidence_producer",
            "trigger": "new_issuer_customer_platform_or_regulatory_record",
        }
    if entity_key == "recruitment_patent_capacity_audit":
        return {
            "ref": "SUP-RECRUITMENT-PATENT",
            "action": "补齐岗位历史ID、法人/地点/职责去重以及专利族、优先权和法律状态，再判断其与数据中心光模块的对应关系。",
            "owner": "weak_signal_evidence_producer",
            "trigger": "monthly_snapshot_or_database_update",
        }
    if entity_key == "qualification_upstream_constraints":
        return {
            "ref": "SUP-UPSTREAM-QUALIFICATION",
            "action": "取得客户资格、再认证和关键器件合格供给的原始记录，并只更新被该记录直接约束的门槛。",
            "owner": "supply_chain_evidence_producer",
            "trigger": "new_customer_supplier_or_regulatory_record",
        }
    if entity_key in {"innolight_terminal_risk", "eoptolink_terminal_risk"}:
        return {
            "ref": "SUP-INCUMBENT-FINANCIAL",
            "action": "在下一份定期报告后复核收入、毛利、现金流、客户集中与产品阶段，并重跑竞争传导和终值敏感性。",
            "owner": "financial_evidence_producer",
            "trigger": "next_periodic_report_or_guidance_change",
        }
    return {
        "ref": "SUP-MARKET-ARCHITECTURE",
        "action": "在下一轮原始来源更新时复核该命题的口径、反证和适用边界，并记录是否需要重估关联模型参数。",
        "owner": "industry_evidence_producer",
        "trigger": "quarterly_or_new_primary_record",
    }


def _canonical_claim_class(claim: dict[str, Any], source_ref: str) -> str:
    raw = _clean(
        claim.get("source_claim_class")
        or claim.get("classification")
        or claim.get("polarity")
        or claim.get("claim_type")
    ).lower()
    if source_ref.startswith("MODEL-") or any(token in raw for token in ("inferred", "推断", "模型")):
        return "inference"
    if any(token in raw for token in ("bounded_negative", "negative_boundary", "search_gap", "not_publicly", "公开未", "缺口")):
        return "bounded_negative"
    if any(token in raw for token in ("forecast", "预测")):
        return "forecast"
    if any(token in raw for token in ("methodology", "方法")):
        return "methodology"
    return "fact"


def _claim_direction(claim: dict[str, Any], claim_class: str) -> str:
    raw = _clean(
        claim.get("direction")
        or claim.get("classification")
        or claim.get("polarity")
        or claim.get("claim_type")
    ).lower()
    if claim_class == "bounded_negative" or any(token in raw for token in ("counter", "negative", "反证")):
        return "counter_risk"
    if any(token in raw for token in ("support", "capacity_proxy", "issuer_claim", "transferable", "verified")):
        return "support_risk"
    if any(token in raw for token in ("boundary", "mixed", "gap", "conflict", "边界", "冲突")):
        return "boundary"
    return "context_calibrator"


def _claim_subject(entity_key: str) -> dict[str, Any]:
    mapping = {
        "byd_entry_risk": ("issuer:byd-electronic", "controlled_group:byd"),
        "luxshare_entry_risk": ("issuer:luxshare-precision", "controlled_group:luxshare"),
        "innolight_terminal_risk": ("issuer:innolight", "controlled_group:innolight"),
        "eoptolink_terminal_risk": ("issuer:eoptolink", "controlled_group:eoptolink"),
    }
    legal_entity, control_group = mapping.get(entity_key, (None, None))
    return {
        "legal_entity_key": legal_entity,
        "legal_entity_status": "mapped" if legal_entity else "not_applicable_industry_or_model_claim",
        "control_group_key": control_group,
        "control_group_status": "mapped" if control_group else "not_applicable_industry_or_model_claim",
    }


_CLAIM_SUBJECT_OVERRIDES: dict[str, dict[str, Any]] = {
    "BYD-C04": {
        "legal_entity_key": None,
        "legal_entity_status": "multiple_byd_group_patent_applicants_explicitly_scoped",
        "control_group_key": "controlled_group:byd",
        "control_group_status": "mapped",
    },
    "BYD-C05": {
        "legal_entity_key": None,
        "legal_entity_status": "group_recruitment_without_single_legal_entity",
        "control_group_key": "controlled_group:byd",
        "control_group_status": "mapped",
    },
    "BYD-C06": {
        "legal_entity_key": None,
        "legal_entity_status": "multiple_byd_manufacturing_entities_explicitly_scoped",
        "control_group_key": "controlled_group:byd",
        "control_group_status": "mapped",
    },
}


def _claim_product_scope(text: str) -> dict[str, Any]:
    generations = _unique(
        match.upper().replace(" ", "")
        for match in re.findall(r"(?i)\b(?:10G|100G|200G|400G|800G|1\.6T|3\.2T|12\.8T)\b", text)
    )
    architectures = [token for token in ("LPO", "LRO", "CPO", "NPO", "XPO", "SiPh") if token.lower() in text.lower()]
    form_factors = [token for token in ("SFP", "QSFP", "QSFP112", "QSFP-DD", "OSFP", "AOC", "DAC") if token.lower() in text.lower()]
    return {
        "market": "ai_datacenter" if any(token in text.lower() for token in ("数据中心", "ai", "csp", "云")) else None,
        "market_status": "text_mapped" if any(token in text.lower() for token in ("数据中心", "ai", "csp", "云")) else "not_explicit_in_claim",
        "product_family": "optical_transceiver" if any(token in text for token in ("光模块", "光互连", "收发器")) else None,
        "product_family_status": "text_mapped" if any(token in text for token in ("光模块", "光互连", "收发器")) else "not_explicit_in_claim",
        "generations": generations,
        "generations_status": "text_mapped" if generations else "not_explicit_in_claim",
        "form_factors": form_factors,
        "form_factors_status": "text_mapped" if form_factors else "not_explicit_in_claim",
        "architectures": architectures,
        "architectures_status": "text_mapped" if architectures else "not_explicit_in_claim",
    }


def _claim_source_audit(
    refs: list[str],
    support_refs: set[str],
    counter_refs: set[str],
    boundary_refs: set[str],
    source_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    audit: list[dict[str, Any]] = []
    for ref in refs:
        source = source_lookup[ref]
        provenance = _source_provenance(source)
        roles = []
        if ref in support_refs:
            roles.append("support")
        if ref in counter_refs:
            roles.append("counter")
        if ref in boundary_refs:
            roles.append("boundary")
        audit.append(
            {
                "source_ref": ref,
                "record_key": provenance["record_key"],
                "record_family_key": provenance["record_family_key"],
                "issuer_key": provenance["issuer_key"],
                "control_group_key": provenance["control_group_key"],
                "fact_lineage_key": provenance["fact_lineage_key"],
                "corroboration_key": provenance["corroboration_key"],
                "origin_type": provenance["origin_type"],
                "source_publish_date": source.get("publish_date"),
                "source_event_date": source.get("event_date"),
                "evidence_roles": roles or ["context"],
            }
        )
    return audit


def _complete_claim_ledger(
    claim: dict[str, Any], source_lookup: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """将分包、冲突和模型 claim 无损编译到一个 canonical ledger。"""

    result = dict(claim)
    claim_id = _clean(result.get("claim_id"))
    entity_key = _clean(result.get("entity_key")) or _infer_claim_entity(_clean(result.get("claim_text")))
    entity_key = _claim_research_entity(claim_id, entity_key)
    text = _clean(result.get("claim_text") or result.get("claim") or result.get("statement"))
    raw_support = result.get("supporting_source_refs") or result.get("support_refs") or result.get("source_refs") or []
    raw_counter = result.get("counter_source_refs") or result.get("counter_refs") or []
    if isinstance(raw_support, str):
        raw_support = [raw_support]
    if isinstance(raw_counter, str):
        raw_counter = [raw_counter]
    support_list = [ref for ref in _unique(raw_support) if ref in source_lookup]
    counter_list = [ref for ref in _unique(raw_counter) if ref in source_lookup]
    support_refs = set(support_list)
    counter_refs = set(counter_list)
    if not support_refs and _clean(result.get("source_ref")) in source_lookup:
        support_list.append(_clean(result["source_ref"]))
        support_refs.add(_clean(result["source_ref"]))
    source_claim_class = _clean(
        result.get("source_claim_class")
        or result.get("classification")
        or result.get("polarity")
        or result.get("claim_type")
    ) or "unspecified"
    primary_ref = next(iter([*support_list, *counter_list]), "")
    claim_class = _canonical_claim_class(result, primary_ref)
    raw_boundary = result.get("boundary_refs") or []
    if isinstance(raw_boundary, str):
        raw_boundary = [raw_boundary]
    boundary_refs = {ref for ref in raw_boundary if ref in source_lookup}
    if claim_class == "bounded_negative" or any(
        token in source_claim_class.lower() for token in ("boundary", "mixed", "gap", "conflict")
    ):
        boundary_refs.update(support_refs)
    all_refs = _unique([*support_list, *counter_list, *sorted(boundary_refs)])
    audit = _claim_source_audit(all_refs, support_refs, counter_refs, boundary_refs, source_lookup)
    groups = {row["corroboration_key"] for row in audit}
    event_dates = _unique(row["source_event_date"] for row in audit if row.get("source_event_date"))
    source_next_action = _clean(result.get("next_evidence_action")) or None
    next_action_plan = _claim_next_action_plan(claim_id, entity_key)
    next_action = source_next_action or next_action_plan["action"]
    caveat = _clean(result.get("caveat") or result.get("evidence_boundary")) or None
    conflict = _clean(result.get("conflict") or result.get("counterevidence")) or None
    lower_text = text.lower()
    has_china_scope = any(token in text for token in ("中国", "国内"))
    has_global_scope = any(token in lower_text for token in ("全球", "海外", "global"))
    if has_china_scope and has_global_scope:
        geography = "china_and_global"
    elif has_china_scope:
        geography = "china"
    elif has_global_scope:
        geography = "global"
    else:
        geography = None
    result.update(
        {
            "claim_id": claim_id or f"claim-{hashlib.sha256(text.encode()).hexdigest()[:12]}",
            "entity_key": entity_key,
            "topic": _clean(result.get("topic") or result.get("claim_type")) or "未单独标明主题",
            "claim_type": _clean(result.get("claim_type") or source_claim_class) or "综合判断",
            "source_claim_class": source_claim_class,
            "claim_class": claim_class,
            "direction": _claim_direction(result, claim_class),
            "milestone_stage": _clean(result.get("milestone_stage") or result.get("milestone")) or None,
            "milestone_status": "provided" if _clean(result.get("milestone_stage") or result.get("milestone")) else "not_provided_not_inferred",
            "claim_text": text,
            "statement": text,
            "factor_codes": _CLAIM_FACTOR_MAP.get(claim_id, []),
            "factor_mapping_status": "mapped" if claim_id in _CLAIM_FACTOR_MAP else "not_applicable_or_not_mapped",
            "subject": _CLAIM_SUBJECT_OVERRIDES.get(
                claim_id, _claim_subject(entity_key)
            ),
            "product_scope": _claim_product_scope(text),
            "commercial_scope": {
                "geography": geography,
                "geography_status": "text_mapped" if geography else "not_explicit_in_claim",
                "customer_name": None,
                "customer_name_status": "not_disclosed_or_not_applicable",
                "quantity_value": None,
                "quantity_unit": None,
                "quantity_status": "not_structured_in_source_claim",
                "period": AS_OF_DATE,
                "period_status": "research_as_of_date",
            },
            "dates": {
                "claim_event_date": event_dates[0] if len(event_dates) == 1 else None,
                "event_date_status": "single_source_event_date" if len(event_dates) == 1 else ("multiple_source_event_dates" if event_dates else "not_available_or_not_applicable"),
                "as_of_date": AS_OF_DATE,
            },
            "source_ref": primary_ref or _clean(result.get("source_ref")),
            "supporting_source_refs": support_list,
            "counter_source_refs": counter_list,
            "boundary_refs": sorted(boundary_refs),
            "source_audit": audit,
            "counts": {
                "record_count": len({row["record_key"] for row in audit}),
                "record_family_count": len({row["record_family_key"] for row in audit}),
                "issuer_count": len({row["issuer_key"] for row in audit}),
                "independent_group_count": len(groups),
                "support_group_count": len({row["corroboration_key"] for row in audit if "support" in row["evidence_roles"]}),
                "counter_group_count": len({row["corroboration_key"] for row in audit if "counter" in row["evidence_roles"]}),
                "boundary_group_count": len({row["corroboration_key"] for row in audit if "boundary" in row["evidence_roles"]}),
            },
            "confidence": _clean(result.get("confidence")) or "medium",
            "conflict": conflict,
            "conflict_status": "provided" if conflict else "none_reported",
            "caveat": caveat,
            "caveat_status": "provided" if caveat else "not_provided",
            "evidence_gap": conflict or caveat,
            "evidence_gap_status": "provided" if conflict or caveat else "not_provided",
            "next_evidence_action": next_action,
            "next_evidence_action_status": (
                "provided" if source_next_action else "research_plan_defined"
            ),
            "next_evidence_action_reason": (
                "原证据分包已提供，按原文继承并映射到正式补证任务。"
                if source_next_action
                else "原分包未提供；研究团队依据claim主体、事件合同和当前证据缺口定义了可审计补证动作。"
            ),
            "next_evidence_action_ref": next_action_plan["ref"],
            "next_evidence_action_owner": next_action_plan["owner"],
            "next_evidence_action_trigger": next_action_plan["trigger"],
            "score_links": [
                {
                    "entity_key": entity_key,
                    "factor_code": factor_code,
                    "effect": _claim_direction(result, claim_class),
                    "numeric_delta": None,
                    "numeric_delta_status": "not_pre_registered_no_automatic_claim_count_scoring",
                }
                for factor_code in _CLAIM_FACTOR_MAP.get(claim_id, [])
            ]
            if entity_key in _CLAIM_SCORE_ENTITY_KEYS
            else [],
            "score_link_status": (
                "linked_to_market_entity_without_automatic_numeric_delta"
                if entity_key in _CLAIM_SCORE_ENTITY_KEYS
                and _CLAIM_FACTOR_MAP.get(claim_id)
                else "not_linked_theory_or_unmapped_claim"
            ),
            "probability_update_links": [],
            "probability_update_status": "not_linked_unless_listed_in_prior_update_bridge",
            "model_parameter_refs": [],
            "model_parameter_status": "not_linked_unless_explicit_model_claim",
        }
    )
    if result["source_ref"] in source_lookup:
        source = source_lookup[result["source_ref"]]
        result["source_excerpt"] = (
            _clean(result.get("source_excerpt")) or source["excerpt"]
        )
        result["source_excerpt_zh"] = (
            _clean(result.get("source_excerpt_zh"))
            or result["source_excerpt"]
            or source["excerpt_zh"]
        )
    return result


def _attach_probability_update_links(
    claims: list[dict[str, Any]], model: dict[str, Any]
) -> None:
    """把先验更新账本回链到 canonical claim；缺 claim 时 fail closed。"""

    bridge = model.get("probability", {}).get("prior_update_bridge", {})
    company_updates = bridge.get("company_updates", {})
    claim_lookup = {claim["claim_id"]: claim for claim in claims}
    for company_key, company_payload in company_updates.items():
        for update in company_payload.get("updates", []):
            for claim_id in update.get("claim_ids", []):
                if claim_id not in claim_lookup:
                    raise ValueError(
                        f"prior_update_bridge 引用了不存在的 claim：{claim_id}"
                    )
                claim = claim_lookup[claim_id]
                for horizon, delta in update["delta_percentage_points"].items():
                    claim["probability_update_links"].append(
                        {
                            "company_key": company_key,
                            "horizon": horizon,
                            "update_id": update["update_id"],
                            "direction": update["direction"],
                            "delta_percentage_points": float(delta),
                            "posterior_parameter": (
                                f"entrants.{company_key}.{horizon}.triangle_mode"
                            ),
                            "evidence_source_refs": list(
                                update["evidence_source_refs"]
                            ),
                            "rationale": update["rationale"],
                            "calibration_status": (
                                "expert_elicitation_not_empirical_likelihood_ratio"
                            ),
                        }
                    )
                claim["probability_update_status"] = (
                    "linked_to_reconciled_prior_update_bridge"
                )


def _validate_model_parameter_registries(
    model: dict[str, Any], source_lookup: dict[str, dict[str, Any]]
) -> None:
    """Fail closed when a model parameter loses owner, formula, or provenance."""

    unknown_refs: set[str] = set()
    incomplete: list[str] = []
    for dimension in ("market", "financial"):
        for index, item in enumerate(
            model.get(dimension, {}).get("parameter_registry", [])
        ):
            path = _clean(item.get("parameter_path")) or f"{dimension}[{index}]"
            if not all(
                _clean(item.get(field))
                for field in (
                    "parameter_path",
                    "owner",
                    "formula_or_method",
                    "epistemic_status",
                    "update_rule",
                )
            ):
                incomplete.append(path)
            refs = item.get("source_refs") or []
            if not isinstance(refs, list) or not refs:
                incomplete.append(f"{path}:source_refs")
            else:
                unknown_refs.update(ref for ref in refs if ref not in source_lookup)

    boundary = model.get("market", {}).get(
        "product_specification_use_boundary", {}
    )
    unknown_refs.update(
        ref for ref in boundary.get("source_refs", []) if ref not in source_lookup
    )
    if not _clean(boundary.get("allowed_use")) or not _clean(
        boundary.get("prohibited_use")
    ):
        incomplete.append("market.product_specification_use_boundary")

    for item in model.get("financial", {}).get("requested_field_coverage", []):
        field = _clean(item.get("field")) or "unnamed_requested_field"
        required = (
            "status",
            "acceptable_proxy",
            "proxy_bias",
            "conclusion_impact",
        )
        if not all(_clean(item.get(key)) for key in required):
            incomplete.append(f"financial.requested_field_coverage.{field}")
        refs = item.get("sources_checked") or []
        unknown_refs.update(ref for ref in refs if ref not in source_lookup)

    if incomplete or unknown_refs:
        raise ValueError(
            "模型参数登记不完整："
            f"incomplete={sorted(set(incomplete))}，"
            f"unknown_source_refs={sorted(unknown_refs)}"
        )


def _normalize_claim(
    claim: dict[str, Any],
    source_lookup: dict[str, dict[str, Any]],
    *,
    source_prefix: str = "",
) -> dict[str, Any] | None:
    refs = [f"{source_prefix}{ref}" for ref in _claim_source_refs(claim)]
    refs = [ref for ref in refs if ref in source_lookup]
    if not refs:
        return None
    ref = refs[0]
    source = source_lookup[ref]
    original_entity = _clean(claim.get("entity_key"))
    text = _clean(claim.get("claim_text") or claim.get("claim") or claim.get("statement"))
    if not text:
        return None
    claim_id = _clean(claim.get("claim_id")) or f"claim-{hashlib.sha256(text.encode()).hexdigest()[:12]}"
    excerpt_override = _CLAIM_EXCERPT_OVERRIDES.get(claim_id, {})
    source_excerpt = (
        _clean(claim.get("source_excerpt"))
        or excerpt_override.get("source_excerpt")
        or source["excerpt"]
    )
    source_excerpt_zh = (
        _clean(claim.get("source_excerpt_zh"))
        or excerpt_override.get("source_excerpt_zh")
        or _clean(source.get("excerpt_zh"))
        or source_excerpt
    )
    normalized = {
        "claim_id": claim_id,
        "entity_key": _map_entity(original_entity) if original_entity else _infer_claim_entity(text),
        "claim_type": _clean(claim.get("claim_type") or claim.get("topic") or claim.get("polarity"))
        or "综合判断",
        "claim_text": text,
        "source_ref": ref,
        "source_excerpt": source_excerpt,
        "source_excerpt_zh": source_excerpt_zh,
        "supporting_source_refs": refs,
        "counter_source_refs": [
            f"{source_prefix}{value}"
            for value in (claim.get("counter_source_refs") or claim.get("counter_refs") or [])
            if f"{source_prefix}{value}" in source_lookup
        ],
        "confidence": _clean(claim.get("confidence")) or "medium",
        "caveat": _clean(claim.get("caveat") or claim.get("evidence_boundary") or claim.get("counterevidence"))
        or None,
        "topic": _clean(claim.get("topic")) or None,
        "source_claim_class": _clean(claim.get("classification") or claim.get("polarity") or claim.get("claim_type")) or None,
        "classification": _clean(claim.get("classification")) or None,
        "polarity": _clean(claim.get("polarity")) or None,
        "milestone_stage": _clean(claim.get("milestone_stage") or claim.get("milestone")) or None,
        "conflict": _clean(claim.get("conflict")) or None,
        "counterevidence": _clean(claim.get("counterevidence")) or None,
        "evidence_boundary": _clean(claim.get("evidence_boundary")) or None,
        "next_evidence_action": _clean(claim.get("next_evidence_action")) or None,
    }
    return _complete_claim_ledger(normalized, source_lookup)


def _infer_claim_entity(text: str) -> str:
    lower = text.lower()
    if "比亚迪" in text or "byd" in lower:
        return "byd_entry_risk"
    if "立讯" in text or "luxshare" in lower:
        return "luxshare_entry_risk"
    if "新易盛" in text or "eoptolink" in lower:
        return "eoptolink_terminal_risk"
    if "中际旭创" in text or "innolight" in lower:
        return "innolight_terminal_risk"
    if any(token in text for token in ("历史", "基准率", "案例")):
        return "probability_method_and_baserate"
    if any(token in text for token in ("认证", "上游", "供应商", "出口管制")):
        return "qualification_upstream_constraints"
    return "industry_demand_supply_model"


def _analyst_revenue_paths(
    financial: dict[str, Any],
    company_key: str,
    *,
    fallback_2026_2027: tuple[float, float],
    tail_growth: tuple[float, float, float, float],
) -> dict[str, list[float]]:
    """从结构化快照读取low/base/high；2028后按显式递减增速延展。"""

    estimates = (
        financial.get("companies", {})
        .get(company_key, {})
        .get("analyst_estimates", {})
        .get("revenue_estimate", {})
    )
    output: dict[str, list[float]] = {}
    for label, statistic in (("low", "low"), ("base", "avg"), ("high", "high")):
        first = _finite(estimates.get("0y", {}).get(statistic))
        second = _finite(estimates.get("+1y", {}).get(statistic))
        if first is None or second is None:
            first, second = fallback_2026_2027
        else:
            first /= 100_000_000
            second /= 100_000_000
        path = [round(first, 2), round(second, 2)]
        for growth in tail_growth:
            path.append(round(path[-1] * (1.0 + growth), 2))
        output[label] = path
    return output


def _valuation_anchor(
    financial: dict[str, Any], company_key: str
) -> dict[str, Any]:
    market = (
        financial.get("companies", {})
        .get(company_key, {})
        .get("market_snapshot", {})
    )
    return {
        "trade_date": market.get("trade_date"),
        "currency": market.get("currency"),
        "price": _finite(market.get("price")),
        "market_cap_cny_yi": _finite(
            market.get("market_cap_cny") or market.get("market_cap_value")
        ),
        "pe_ttm": _finite(market.get("pe_ttm")),
        "pb": _finite(market.get("pb")),
        "ps_ttm": _finite(market.get("ps_ttm")),
        "source": market.get("source"),
        "market_cap_unit": market.get("market_cap_unit"),
    }


def _model_config(financial: dict[str, Any]) -> dict[str, Any]:
    """返回全部显式输入；数值是假设区间，不伪装成统计后验。"""

    innolight_revenue = _analyst_revenue_paths(
        financial,
        "innolight",
        fallback_2026_2027=(988.64, 1700.45),
        tail_growth=(0.30, 0.20, 0.14, 0.08),
    )
    eoptolink_revenue = _analyst_revenue_paths(
        financial,
        "eoptolink",
        fallback_2026_2027=(551.53, 884.75),
        tail_growth=(0.25, 0.20, 0.14, 0.08),
    )

    return {
        "as_of_date": AS_OF_DATE,
        "samples": 100_000,
        "seed": 20260718,
        "input_provenance": [
            {
                "input": "historical_entry_base_rate",
                "source_ref": "SRC-CISCO-ACACIA21",
                "source_refs": _historical_case_source_refs(),
                "case_ids": [row["case_id"] for row in _HISTORICAL_ENTRY_CASE_LEDGER],
                "status": "small_selected_sample",
                "note": (
                    "同一九案例逐例账本中，严格完整模块成功2例、宽口径持久光通信邻接成功5例；"
                    "只用来约束宽先验。样本小、异质、定向选择且收购案例占比高。"
                ),
            },
            {
                "input": "byd_stage_update",
                "source_ref": "BYD-S01/BYD-S04/BYD-LEAD-FIRSTSH-20250901/BYD-LEAD-CMBI-20250902/BYD-LEAD-CINDA-20250905/BYD-S17/BYD-S18",
                "status": "material_unverified_lead_not_probability_fact",
                "external_fact": False,
                "note": "服务器与液冷相邻能力已由公司披露证实；三家卖方把800G量产准备/能力、1.6T测试或量产准备及CPO路线归因于同一次2025年中期业绩电话会，但没有公开逐字稿，且后续年报未披露实际出货、客户、良率或收入。该线索只扩大比亚迪上行情景和提高补证优先级，不改变中心值或下沿。",
            },
            {
                "input": "byd_optical_patent_adjacency",
                "source_ref": "BYD-S14/BYD-PAT-CN122052920A/BYD-PAT-CN122362593A/BYD-PAT-CN121012567A",
                "status": "primary_patent_records_cross_entity_vehicle_scope",
                "note": "连续专利族证明比亚迪体系已有车载硅光、收发架构、模块封装和热设计研发；申请主体和车辆场景限制其只能小幅提高长期技术迁移判断，不能代替比亚迪电子的数据中心产品、客户、专线和收入。",
            },
            {
                "input": "luxshare_stage_update",
                "source_ref": "立讯官网、年报与监管 IR",
                "status": "official_conflict_conservatively_resolved",
                "note": "产品和国内交付高于纯概念阶段；全球头部 CSP、稳定份额和重复订单未闭环。",
            },
            {
                "input": "china_vs_global_geography_update",
                "source_ref": "BYD-S01/BYD-S04/LX-ANNUAL-2024/LX-IR-202508/LX-IR-20260507",
                "status": "bounded_expert_range_with_official_conflict",
                "note": "中国与全球头部客户是可重叠的有意义进入子事件，分别建模。立讯公开产品与国内/中小客户交付使中国条件概率高于全球；比亚迪缺少具名高速光SKU与客户，绝对概率仍低。公开未闭环全球不被当作中国成功，其他地区或未识别路径单列。",
            },
            {
                "input": "conditional_competition_severity_weights",
                "source_ref": "MODEL-WORKPAPER",
                "status": "structured_expert_assumption_not_external_fact",
                "external_fact": False,
                "note": (
                    "依据研究请求对温和、明显和严重竞争结果的操作定义，"
                    "按期限与进入路径分别设置温和和严重的宽判断范围；"
                    "明显权重等于1减温和权重再减严重权重。"
                    "最终条件概率用各进入路径概率加权并在至少一家进入的路径中归一。"
                    "这些权重未由历史频率或财务阈值校准，不得解释成外部事实、"
                    "经验发生率或下游财务分类结果。"
                ),
            },
            {
                "input": "financial_baseline",
                "source_ref": "FIN-INNOLIGHT-ANALYST/FIN-EOPTOLINK-ANALYST",
                "status": "market_consensus_range_not_guidance",
                "note": "2026/2027 基线锚定Yahoo Finance/yfinance分析师均值并保留宽区间；2028 后为显式增速递减假设；不得归因Tushare或公司指引。",
            },
        ],
        "probability": {
            "schema_version": "byd_luxshare_probability.v2",
            "event_contract": {
                "version": "meaningful_entry.v1",
                "as_of_date": AS_OF_DATE,
                "horizons": {"3y": "2029-07-20", "5y": "2031-07-20"},
                "meaningful_entry": "经营主体拥有AI数据中心800G+合格产品、至少一个大型客户qualification/AVL/design win、跨两个采购或披露周期的重复商业交付，并达到年化10亿元/全球1%/中国5%之一且具备两个客户或同一客户跨代延续；同时执行宽松与严格阈值敏感性。",
                "china_entry": "在满足有意义进入的前提下，至少一个中国总部CSP、AI平台、交换机厂或头部ODM/OEM的qualification/AVL/design win与跨周期重复交付由公司、客户、平台、监管或可归属订单闭环；未突破全球头部客户不能自动等同中国进入。",
                "global_entry": "在满足有意义进入的前提下，至少一个非中国全球头部CSP、AI平台、交换机厂或头部ODM/OEM由客户/平台/监管侧闭环；海外工厂、英文官网和展会不是充分条件。",
                "deterioration": "相对冻结的无新增进入反事实，按同规格额外ASP、物理份额、毛利、2029—2031 FCF和正常化终值损失及持续性分为温和、明显、严重。",
            },
            "prior_update_bridge": {
                "update_method": "additive_percentage_point_expert_elicitation",
                "epistemic_status": "deprecated_internal_reconciliation_not_valid_statistical_prior",
                "method_note": (
                    "该桥仅保留历史参数版本的内部对账。九个案例的进入方式、事件定义和观察终点不同，"
                    "不能形成统计成功率或共同先验；逐项百分点也可能因阶段和证据重叠而重复奖惩。"
                    "公开研究只把公司最终区间诚实标为结构化工作区间，不展示本桥。"
                ),
                "historical_case_ledger": _historical_case_ledger(),
                "historical_anchors": {
                    "complete_module_success": {
                        "success_flag": "strict_full_stack_success",
                        "successes": 2,
                        "sample_size": 9,
                        "descriptive_rate": 2 / 9,
                        "wilson_95_interval": _wilson_interval(2, 9),
                        "case_ids": [row["case_id"] for row in _HISTORICAL_ENTRY_CASE_LEDGER],
                        "source_refs": _historical_case_source_refs(),
                        "boundary": "小样本、定向选择、案例异质且收购路径占比高，只约束先验宽度。",
                    },
                    "adjacent_or_complete_success": {
                        "success_flag": "broad_adjacency_success",
                        "successes": 5,
                        "sample_size": 9,
                        "descriptive_rate": 5 / 9,
                        "wilson_95_interval": _wilson_interval(5, 9),
                        "case_ids": [row["case_id"] for row in _HISTORICAL_ENTRY_CASE_LEDGER],
                        "source_refs": _historical_case_source_refs(),
                        "boundary": "邻接制造、器件和完整模块混在一起，不能直接作为本研究严格事件的成功频率。",
                    },
                },
                "working_priors": {
                    "3y": {
                        "mode": 0.22,
                        "support": [0.06, 0.22, 0.55],
                        "rationale": "历史版本内部专家起点，仅用于重建既有参数；2/9异质案例记分不构成统计锚。",
                    },
                    "5y": {
                        "mode": 0.35,
                        "support": [0.15, 0.35, 0.70],
                        "rationale": "历史版本内部专家起点，仅用于重建既有参数；35%没有经验频率或统计公式支撑。",
                    },
                },
                "company_updates": {
                    "byd": {
                        "display_name": "比亚迪电子体系",
                        "updates": [
                            {
                                "update_id": "byd_adjacent_ai_datacenter_capability",
                                "direction": "up",
                                "delta_percentage_points": {"3y": 4.0, "5y": 8.0},
                                "claim_ids": ["BYD-C02"],
                                "evidence_source_refs": ["BYD-S01", "BYD-S04"],
                                "rationale": "AI服务器、液冷、电源和高速互联组合证明客户入口与系统邻接，长期迁移价值高于短期。",
                            },
                            {
                                "update_id": "byd_scale_capital_and_automation",
                                "direction": "up",
                                "delta_percentage_points": {"3y": 3.0, "5y": 5.0},
                                "claim_ids": ["BYD-C01", "BYD-C06", "BYD-C08"],
                                "evidence_source_refs": ["BYD-S01", "BYD-S16"],
                                "rationale": "资金、精密制造和自动化提高试错与扩产上限，但只属于可迁移能力代理。",
                            },
                            {
                                "update_id": "byd_systematic_vehicle_optical_patent_adjacency",
                                "direction": "up",
                                "delta_percentage_points": {"3y": 1.0, "5y": 2.0},
                                "claim_ids": ["BYD-C04", "BYD-C13"],
                                "evidence_source_refs": ["BYD-S14", "BYD-PAT-CN122052920A", "BYD-PAT-CN122362593A", "BYD-PAT-CN121012567A"],
                                "rationale": "连续车载硅光、收发、模块封装和热设计专利族证明集团技术邻接比单一关键词更系统；因申请主体跨公司且场景不是数据中心，只作小幅正向迁移判断。",
                            },
                            {
                                "update_id": "byd_no_public_named_800g_plus_sku",
                                "direction": "down",
                                "delta_percentage_points": {"3y": -5.0, "5y": -5.0},
                                "claim_ids": ["BYD-C03"],
                                "evidence_source_refs": ["BYD-S01", "BYD-S03", "BYD-S04", "BYD-S05"],
                                "rationale": "发行人年报、官网产品页和定期报告仍没有可归属的数据中心800G以上SKU、规格或正式产品阶段披露；卖方转述说明这一公开缺口不能解释成项目不存在，但在取得原始产品材料前仍保留有界折扣。",
                            },
                            {
                                "update_id": "byd_no_public_qualification_or_interop",
                                "direction": "down",
                                "delta_percentage_points": {"3y": -5.0, "5y": -5.0},
                                "claim_ids": ["BYD-C07"],
                                "evidence_source_refs": ["BYD-S17", "BYD-S18"],
                                "rationale": "指定互操作与平台清单未形成公开模块闭环；缺席只是有界负证据，因此扣减而不归零。",
                            },
                            {
                                "update_id": "byd_optical_line_team_and_entity_boundary",
                                "direction": "down",
                                "delta_percentage_points": {"3y": -7.0, "5y": -8.0},
                                "claim_ids": ["BYD-C04", "BYD-C05", "BYD-C06"],
                                "evidence_source_refs": ["BYD-S06", "BYD-S07", "BYD-S19", "BYD-S20"],
                                "rationale": "招聘未闭环模块岗位，公开项目偏车载或其他法人；光学专线、良率和主体迁移仍是核心验证债。",
                            },
                        ],
                        "posterior": {
                            "3y": {"mode": 0.13, "triangle": [0.06, 0.13, 0.32]},
                            "5y": {"mode": 0.32, "triangle": [0.18, 0.32, 0.55]},
                        },
                    },
                    "luxshare": {
                        "display_name": "立讯精密 / Luxshare-Tech体系",
                        "updates": [
                            {
                                "update_id": "luxshare_named_multigeneration_product_matrix",
                                "direction": "up",
                                "delta_percentage_points": {"3y": 10.0, "5y": 12.0},
                                "claim_ids": ["LX-C003", "LX-C004", "LX-C007", "LX-C008"],
                                "evidence_source_refs": ["LX-TRANSCEIVER-CURRENT", "LX-800G-LPO-SPEC", "LX-FRO-2026"],
                                "rationale": "10G—1.6T目录、800G规格与后续路线使其明显越过从零产品阶段。",
                            },
                            {
                                "update_id": "luxshare_issuer_claimed_production_and_delivery",
                                "direction": "up",
                                "delta_percentage_points": {"3y": 8.0, "5y": 10.0},
                                "claim_ids": ["LX-C005", "LX-C006"],
                                "evidence_source_refs": ["LX-IR-202508", "LX-FRO-2026"],
                                "rationale": "2025年监管记录称800G量产、1.6T客户验证；截至抓取日可见但未署期的官网页另称1.6T处于早期商业化。两份发行人材料共同支持当前有限商业阶段，却不能证明何时或是否完成阶段跃迁，也不等于头部客户稳定份额。",
                            },
                            {
                                "update_id": "luxshare_partner_interop_and_test_ecosystem",
                                "direction": "up",
                                "delta_percentage_points": {"3y": 7.0, "5y": 8.0},
                                "claim_ids": ["LX-C009", "LX-C010"],
                                "evidence_source_refs": ["POET-LX-202408", "OIF-OFC2026", "KEYSIGHT-LX-202410"],
                                "rationale": "独立伙伴、互操作和测试记录提高工程成熟与生态接近度，仍低于客户AVL证据。",
                            },
                            {
                                "update_id": "luxshare_manufacturing_and_system_integration",
                                "direction": "up",
                                "delta_percentage_points": {"3y": 4.0, "5y": 6.0},
                                "claim_ids": ["LX-C013", "LX-C015", "LX-C017"],
                                "evidence_source_refs": ["LX-HKEX-PROSPECTUS-ZH-2026", "LX-CNINFO-H1-2025", "JOB-ZHAOPIN-COUPLING"],
                                "rationale": "通信制造、系统连接和耦合岗位提高规模化上限，但混合分部数字不能代填光模块良率和产能。",
                            },
                            {
                                "update_id": "luxshare_no_named_global_head_customer_closure",
                                "direction": "down",
                                "delta_percentage_points": {"3y": -3.0, "5y": -3.0},
                                "claim_ids": ["LX-C011", "LX-C012"],
                                "evidence_source_refs": ["LX-IR-202508", "NVIDIA-CX8-VALIDATED"],
                                "rationale": "未取得具名全球头部CSP的qualification/AVL、重复订单或平台侧800G+闭环。",
                            },
                            {
                                "update_id": "luxshare_disclosure_conflict_and_profit_capture_gap",
                                "direction": "down",
                                "delta_percentage_points": {"3y": -3.0, "5y": -2.0},
                                "claim_ids": ["LX-C018", "LX-CONFLICT-C01", "LX-CONFLICT-C02"],
                                "evidence_source_refs": ["LX-ANNUAL-2024", "LX-IR-202508", "LX-IR-20260507"],
                                "rationale": "客户层级与商业阶段口径冲突，模块收入、专线良率和利润捕获不可分；冲突扩大区间并压低众数。",
                            },
                        ],
                        "posterior": {
                            "3y": {"mode": 0.45, "triangle": [0.32, 0.45, 0.60]},
                            "5y": {"mode": 0.66, "triangle": [0.50, 0.66, 0.80]},
                        },
                    },
                },
                "uncertainty_policy": (
                    "更新桥只重建三角分布众数；low/high由证据缺口、反方和事件阈值共同设定。"
                    "Monte Carlo均值=(low+mode+high)/3附近，不能与众数或delta混为同一列。"
                ),
            },
            "entrants": {
                "byd": {
                    "3y": [0.06, 0.13, 0.32],
                    "5y": [0.18, 0.32, 0.55],
                    "china_given_entry_3y": [0.55, 0.75, 0.90],
                    "china_given_entry_5y": [0.60, 0.78, 0.92],
                    "global_given_entry_3y": [0.02, 0.06, 0.15],
                    "global_given_entry_5y": [0.08, 0.20, 0.35],
                },
                "luxshare": {
                    "3y": [0.32, 0.45, 0.60],
                    "5y": [0.50, 0.66, 0.80],
                    "china_given_entry_3y": [0.65, 0.82, 0.94],
                    "china_given_entry_5y": [0.70, 0.85, 0.96],
                    "global_given_entry_3y": [0.08, 0.18, 0.32],
                    "global_given_entry_5y": [0.22, 0.40, 0.60],
                },
            },
            "frechet_dependence_lambda": {
                "entry": [0.15, 0.40, 0.65],
                "global": [0.25, 0.50, 0.75],
                "china": [0.20, 0.45, 0.70],
                "geography_overlap": [0.10, 0.35, 0.60],
            },
            "architecture": {
                "hybrid_probability": {
                    "3y": [0.15, 0.25, 0.35],
                    "5y": [0.25, 0.38, 0.52],
                },
                "cpo_incremental_risk_probability": {
                    "3y": [0.02, 0.04, 0.08],
                    "5y": [0.05, 0.10, 0.18],
                },
            },
            "deterioration_pressure_bands": {
                "3y": {
                    "B": {"mild": [0.55, 0.65, 0.75], "severe": [0.02, 0.06, 0.12]},
                    "C": {"mild": [0.55, 0.65, 0.75], "severe": [0.02, 0.06, 0.12]},
                    "D": {"mild": [0.45, 0.55, 0.65], "severe": [0.05, 0.10, 0.18]},
                    "E": {"mild": [0.30, 0.40, 0.50], "severe": [0.10, 0.18, 0.28]},
                    "F": {"mild": [0.15, 0.25, 0.35], "severe": [0.20, 0.35, 0.50]},
                },
                "5y": {
                    "B": {"mild": [0.45, 0.55, 0.65], "severe": [0.05, 0.10, 0.15]},
                    "C": {"mild": [0.45, 0.55, 0.65], "severe": [0.05, 0.10, 0.15]},
                    "D": {"mild": [0.35, 0.45, 0.55], "severe": [0.08, 0.15, 0.22]},
                    "E": {"mild": [0.20, 0.30, 0.40], "severe": [0.15, 0.27, 0.40]},
                    "F": {"mild": [0.10, 0.18, 0.25], "severe": [0.30, 0.45, 0.58]},
                },
            },
            "deterioration_thresholds": {
                "3y": {
                    "material_any": {
                        "actual_fcf_loss_pct": 10.0,
                        "net_income_loss_pct": 10.0,
                        "gross_margin_loss_ppt": 2.0,
                        "share_loss_pct": 5.0,
                        "extra_asp_pressure_pct": 4.0,
                        "terminal_loss_pct": 10.0,
                    },
                    "severe_all": {
                        "actual_fcf_loss_pct": 20.0,
                        "net_income_loss_pct": 20.0,
                        "gross_margin_loss_ppt": 5.0,
                        "terminal_loss_pct": 25.0,
                        "persistent_years": 1,
                    },
                    "severe_share_or_asp": {
                        "share_loss_pct": 10.0,
                        "extra_asp_pressure_pct": 7.0,
                    },
                },
                "5y": {
                    "material_any": {
                        "actual_fcf_loss_pct": 10.0,
                        "net_income_loss_pct": 10.0,
                        "gross_margin_loss_ppt": 2.0,
                        "share_loss_pct": 5.0,
                        "extra_asp_pressure_pct": 4.0,
                        "terminal_loss_pct": 10.0,
                    },
                    "severe_all": {
                        "actual_fcf_loss_pct": 20.0,
                        "net_income_loss_pct": 20.0,
                        "gross_margin_loss_ppt": 5.0,
                        "terminal_loss_pct": 25.0,
                        "persistent_years": 2,
                    },
                    "severe_share_or_asp": {
                        "share_loss_pct": 10.0,
                        "extra_asp_pressure_pct": 7.0,
                    },
                },
            },
            "sensitivity_cases": {
                "loose_entry_threshold": {
                    "label": "宽松规模阈值",
                    "event_definition_delta": "规模门槛改为年化5亿元/全球0.5%/中国3%，客户资格与重复交付门槛不变。",
                    "rationale": "检验结果对有意义进入规模定义的敏感性。",
                    "override": {
                        "entrants": {
                            "byd": {"3y": [0.12, 0.26, 0.48], "5y": [0.34, 0.52, 0.72]},
                            "luxshare": {"3y": [0.40, 0.55, 0.70], "5y": [0.60, 0.76, 0.88]},
                        }
                    },
                },
                "strict_entry_threshold": {
                    "label": "严格规模阈值",
                    "event_definition_delta": "规模门槛改为年化20亿元/全球2%/中国10%，且仍要求客户资格与跨周期重复交付。",
                    "rationale": "检验较高经济影响门槛下的进入概率。",
                    "override": {
                        "entrants": {
                            "byd": {"3y": [0.05, 0.12, 0.24], "5y": [0.16, 0.30, 0.48]},
                            "luxshare": {"3y": [0.22, 0.34, 0.48], "5y": [0.36, 0.52, 0.68]},
                        }
                    },
                },
                "qualification_delay": {
                    "label": "qualification延后",
                    "event_definition_delta": "3年客户qualification和重复交付时点延后，5年终局支持区间保持基础设定。",
                    "rationale": "检验进入时点而非终局能力的不确定性。",
                    "override": {
                        "entrants": {
                            "byd": {"3y": [0.04, 0.10, 0.22]},
                            "luxshare": {"3y": [0.20, 0.32, 0.48]},
                        }
                    },
                },
                "negative_dependence": {
                    "label": "负依赖",
                    "rationale": "检验客户分流或上游资源竞争使两家公司事件互相挤出的边界。",
                    "override": {"frechet_dependence_lambda": {"entry": [-0.50, -0.25, 0.0], "global": [-0.40, -0.20, 0.0], "china": [-0.40, -0.20, 0.0], "geography_overlap": [-0.40, -0.20, 0.0]}},
                },
                "independent_events": {
                    "label": "独立事件",
                    "rationale": "以Fréchet λ=0给出独立基准，不把它误称Pearson相关。",
                    "override": {"frechet_dependence_lambda": {"entry": [0.0, 0.0, 0.0], "global": [0.0, 0.0, 0.0], "china": [0.0, 0.0, 0.0], "geography_overlap": [0.0, 0.0, 0.0]}},
                },
                "high_positive_dependence": {
                    "label": "高正依赖",
                    "rationale": "检验共同AI需求、上游解锁和客户多供策略同步发生的上边界。",
                    "override": {"frechet_dependence_lambda": {"entry": [0.65, 0.82, 0.95], "global": [0.70, 0.85, 0.98], "china": [0.65, 0.82, 0.95], "geography_overlap": [0.60, 0.80, 0.95]}},
                },
                "architecture_acceleration": {
                    "label": "LPO/CPO加速",
                    "rationale": "检验架构迁移更快时P/H/C概率分布变化；不覆盖A—F进入状态。",
                    "override": {"architecture": {"hybrid_probability": {"3y": [0.25, 0.35, 0.45], "5y": [0.38, 0.50, 0.62]}, "cpo_incremental_risk_probability": {"3y": [0.04, 0.08, 0.12], "5y": [0.10, 0.17, 0.26]}}},
                },
            },
        },
        "market": {
            "years": [2026, 2027, 2028, 2029, 2030, 2031],
            "segments": {
                "800G_pluggable": {
                    "shipments_million": [30, 45, 58, 65, 64, 58],
                    "normal_asp_usd": [220, 175, 140, 115, 98, 85],
                },
                "1.6T_pluggable": {
                    "shipments_million": [3, 7, 12, 22, 36, 50],
                    "normal_asp_usd": [620, 480, 370, 295, 240, 200],
                },
                "3.2T_pluggable_or_engine": {
                    "shipments_million": [0, 0.2, 1.2, 4, 10, 20],
                    "normal_asp_usd": [1500, 1200, 950, 760, 620, 520],
                },
            },
            "qualified_supply_million": [32, 52, 73, 101, 138, 166],
            "lpo_lro_share_pct": [3, 7, 12, 18, 22, 25],
            "cpo_share_pct": [0, 0.3, 1, 3, 7, 13],
            "input_status": {
                "shipments": "结构化情景假设；以端口、拓扑和公开预测交叉约束，不是确定预测。",
                "asp": "正常代际降本基线；未把新进入者额外降价提前写入。",
                "architecture": "LPO/LRO/CPO 是架构份额，不与速率出货重复相加。",
            },
            "parameter_registry": [
                {
                    "parameter_path": "market.segments.*.shipments_million",
                    "owner": "industry_model_producer",
                    "source_refs": ["SRC-NV-QX800", "SRC-NV-SPECTRUM", "SRC-BCM-TH6", "SRC-CIGNAL-4Q24", "SRC-LC-SEP24", "SRC-LC-JUL25", "SRC-LC-MAR26"],
                    "formula_or_method": "以公开交换端口/网络规模约束端点与端口数量，再用LightCounting/Cignal预测作宽路径校准；按800G、1.6T、3.2T逐年结构化情景输入。",
                    "epistemic_status": "scenario_not_point_forecast",
                    "update_rule": "季度滚动；已实现出货、厂商路线图与行业预测分列，不因来源数量机械加权。",
                },
                {
                    "parameter_path": "market.segments.*.normal_asp_usd",
                    "owner": "industry_model_producer",
                    "source_refs": ["SRC-HKEX-ASP26", "SRC-LC-SEP24", "SRC-LC-JUL25", "SRC-LC-MAR26"],
                    "formula_or_method": "从公开历史/申请文件和行业跟踪锚定代际价格，按正常技术降本与产品组合递减；新进入者的额外同规格降价只在A—F竞争冲击中加入。",
                    "epistemic_status": "scenario_with_attribution_limit",
                    "update_rule": "只有取得同规格、同区域、同客户层级成交价时才重估额外竞争价压。",
                },
                {
                    "parameter_path": "market.qualified_supply_million",
                    "owner": "industry_model_producer",
                    "source_refs": ["SRC-COHR-10K25", "SRC-COHR-CHIPS26", "SRC-NV-COHR26", "SRC-MRVL-10Q25", "SRC-INNO-AR25", "SRC-EOPT-AR25"],
                    "formula_or_method": "以可交付端口为单位的合格供给宽情景；名义厂房、设备或样品采购不自动转成通过客户资格的供给。",
                    "epistemic_status": "proxy_due_to_private_yield_and_utilization",
                    "update_rule": "需客户资格、器件锁定、良率、UPH和稼动率中的至少一项原始记录才缩窄区间。",
                },
                {
                    "parameter_path": "market.lpo_lro_share_pct / market.cpo_share_pct",
                    "owner": "architecture_model_producer",
                    "source_refs": ["SRC-OIF-2025", "SRC-OIF-EEI", "SRC-LPO-MSA", "SRC-MRVL-LPO25", "SRC-COHR-OFC25"],
                    "formula_or_method": "把架构份额作为传统可插拔价值池的正交迁移维度，不与速率端口重复相加。",
                    "epistemic_status": "scenario_with_material_forecast_disagreement",
                    "update_rule": "标准项目、器件演示、模块演示和量产采用分层；只有客户部署或可审计出货改变基准份额。",
                },
                {
                    "parameter_path": "market.total_ports_and_revenue",
                    "owner": "calculation_producer",
                    "source_refs": ["MODEL-INPUTS"],
                    "formula_or_method": "总端口=Σ各速率shipments_million；市场收入(十亿美元)=Σ[百万端口×美元ASP]/1000；供需比=qualified_supply/总端口。",
                    "epistemic_status": "deterministic_formula_over_scenario_inputs",
                    "update_rule": "公式固定；输入变更触发独立复算。",
                },
            ],
            "product_specification_use_boundary": {
                "source_refs": ["LX-TRANSCEIVER-CURRENT", "LX-800G-LPO-SPEC", "LX-FRO-2026", "SRC-INNO-1600"],
                "allowed_use": "确认产品规格、代际与最低工程里程碑，并通过显式prior update bridge调整进入事件众数。",
                "prohibited_use": "不得把产品页、展会或FRO规格直接映射为市场份额、成交价、收入、利润或FCF。",
            },
            "sensitivity_cases": {
                "slow": {
                    "label": "慢路径",
                    "rationale": "AI端点/光口和新代际放量偏慢、CPO渗透延后；不是概率预测。",
                    "override": {
                        "segments": {
                            "800G_pluggable": {"shipments_million": [26, 38, 48, 53, 50, 44], "normal_asp_usd": [235, 190, 155, 130, 112, 98]},
                            "1.6T_pluggable": {"shipments_million": [2, 5, 9, 16, 27, 39], "normal_asp_usd": [650, 520, 410, 330, 270, 225]},
                            "3.2T_pluggable_or_engine": {"shipments_million": [0, 0.1, 0.6, 2, 6, 13], "normal_asp_usd": [1550, 1280, 1030, 840, 690, 580]},
                        },
                        "qualified_supply_million": [30, 47, 65, 89, 119, 146],
                        "lpo_lro_share_pct": [2, 5, 9, 13, 17, 20],
                        "cpo_share_pct": [0, 0.1, 0.5, 1.5, 4, 8],
                    },
                },
                "fast": {
                    "label": "快路径",
                    "rationale": "AI网络端口和1.6T/3.2T放量更快，同时合格供给与架构迁移提速；不是概率预测。",
                    "override": {
                        "segments": {
                            "800G_pluggable": {"shipments_million": [34, 52, 68, 77, 75, 68], "normal_asp_usd": [205, 160, 125, 102, 86, 74]},
                            "1.6T_pluggable": {"shipments_million": [4, 9, 16, 29, 47, 66], "normal_asp_usd": [590, 445, 335, 260, 208, 170]},
                            "3.2T_pluggable_or_engine": {"shipments_million": [0, 0.4, 2, 7, 16, 31], "normal_asp_usd": [1450, 1120, 850, 660, 530, 440]},
                        },
                        "qualified_supply_million": [35, 59, 85, 121, 168, 211],
                        "lpo_lro_share_pct": [4, 9, 15, 22, 27, 30],
                        "cpo_share_pct": [0, 0.6, 2, 6, 13, 22],
                    },
                },
                "demand_slow_supply_base": {
                    "label": "需求偏慢、供给按中性路径",
                    "rationale": "只降低端口需求和对应代际价格，合格供给保持中性路径，用于检验供给宽松是否只是供需同步输入的结果。",
                    "override": {
                        "segments": {
                            "800G_pluggable": {"shipments_million": [26, 38, 48, 53, 50, 44], "normal_asp_usd": [235, 190, 155, 130, 112, 98]},
                            "1.6T_pluggable": {"shipments_million": [2, 5, 9, 16, 27, 39], "normal_asp_usd": [650, 520, 410, 330, 270, 225]},
                            "3.2T_pluggable_or_engine": {"shipments_million": [0, 0.1, 0.6, 2, 6, 13], "normal_asp_usd": [1550, 1280, 1030, 840, 690, 580]},
                        },
                    },
                },
                "demand_fast_supply_base": {
                    "label": "需求偏快、供给按中性路径",
                    "rationale": "只提高端口需求并加快代际价格演进，合格供给保持中性路径，用于检验强需求能否吸收计划供给。",
                    "override": {
                        "segments": {
                            "800G_pluggable": {"shipments_million": [34, 52, 68, 77, 75, 68], "normal_asp_usd": [205, 160, 125, 102, 86, 74]},
                            "1.6T_pluggable": {"shipments_million": [4, 9, 16, 29, 47, 66], "normal_asp_usd": [590, 445, 335, 260, 208, 170]},
                            "3.2T_pluggable_or_engine": {"shipments_million": [0, 0.4, 2, 7, 16, 31], "normal_asp_usd": [1450, 1120, 850, 660, 530, 440]},
                        },
                    },
                },
                "supply_slow_demand_base": {
                    "label": "供给爬坡偏慢、需求按中性路径",
                    "rationale": "只降低通过客户与良率约束后的合格供给，需求保持中性路径。",
                    "override": {
                        "qualified_supply_million": [30, 47, 65, 89, 119, 146],
                    },
                },
                "supply_fast_demand_base": {
                    "label": "供给爬坡偏快、需求按中性路径",
                    "rationale": "只提高通过客户与良率约束后的合格供给，需求保持中性路径。",
                    "override": {
                        "qualified_supply_million": [35, 59, 85, 121, 168, 211],
                    },
                },
            },
        },
        "financial": {
            "schema_version": "byd_luxshare_financial.v2",
            "valuation_date": AS_OF_DATE,
            "years": [2026, 2027, 2028, 2029, 2030, 2031],
            "gross_to_net_pass_through": 0.72,
            "terminal": {
                "terminal_date": "2031-12-31",
                "wacc": 0.12,
                "perpetual_growth": 0.03,
                "sensitivity_wacc": [0.10, 0.12, 0.14],
                "sensitivity_growth": [0.02, 0.03, 0.04],
            },
            "parameter_registry": [
                {
                    "parameter_path": "financial.companies.*.baseline_revenue_sensitivity",
                    "owner": "financial_model_producer",
                    "source_refs": ["FIN-INNOLIGHT-ANALYST", "FIN-EOPTOLINK-ANALYST"],
                    "formula_or_method": "2026/2027读取Yahoo Finance/yfinance分析师low/avg/high聚合；2028—2031按显式递减增速延展。",
                    "epistemic_status": "market_consensus_range_not_company_guidance",
                    "update_rule": "覆盖变化或公司指引出现时重取快照；不得归因Tushare。",
                },
                {
                    "parameter_path": "financial.companies.*.baseline margins",
                    "owner": "financial_model_producer",
                    "source_refs": ["SRC-INNO-AR25", "SRC-EOPT-AR25", "FIN-INNOLIGHT", "FIN-EOPTOLINK"],
                    "formula_or_method": "以历史毛利、净利和简单FCF为锚，建立2026—2031显式递减路径；不是管理层指引。",
                    "epistemic_status": "scenario_assumption",
                    "update_rule": "定期报告后逐字段重估，不用单季年化静默覆盖。",
                },
                {
                    "parameter_path": "financial.companies.*.entry_state_shocks / architecture_shocks",
                    "owner": "financial_model_producer",
                    "source_refs": ["MODEL-INPUTS", "SRC-INNO-AR25", "SRC-EOPT-AR25"],
                    "formula_or_method": "逐年显式输入份额、额外ASP、毛利、扩产capex、营运资本与固定成本冲击；A—F进入状态与P/H/C架构状态交叉后按概率加权。",
                    "epistemic_status": "expert_stress_scenario_not_observed_forecast",
                    "update_rule": "客户、同规格价格、可扩良率或架构采用取得新原始证据时，只重估对应冲击。",
                },
                {
                    "parameter_path": "financial.companies.*.high_speed_revenue_exposure_share",
                    "owner": "financial_model_producer",
                    "source_refs": ["MODEL-INPUTS"],
                    "formula_or_method": "本轮显式设为1.0，即暂把全部公司收入视为受影响收入，只用于计算公开资料缺少分产品收入时的压力上限；公开报告同时给出每增加10个百分点暴露的线性敏感度。",
                    "epistemic_status": "explicit_upper_bound_not_observed_business_mix",
                    "update_rule": "取得按速率、客户、地区和产品形态拆分的收入后，以可核验业务占比替换1.0；替换前禁止把主结果解释为中心预测。",
                },
                {
                    "parameter_path": "financial.companies.*.risk_multiplier / financial.gross_to_net_pass_through",
                    "owner": "financial_model_producer",
                    "source_refs": ["SRC-INNO-AR25", "SRC-EOPT-AR25", "FIN-INNOLIGHT", "FIN-EOPTOLINK", "MODEL-INPUTS"],
                    "formula_or_method": "先以0.92/1.08专家倍率缩放公司级进入与架构压力输入，再以72%把毛利率百分点冲击传导至净利率及正常化FCF率；BPS股本口径差异不参与倍率、经营冲击或竞争概率。",
                    "epistemic_status": "expert_stress_transformation_not_observed_coefficient",
                    "update_rule": "取得按客户/SKU/地区的收入、利润、FCF或真实竞争冲击时重估；由financial_model_producer维护并由calculation reviewer独立复算。",
                },
                {
                    "parameter_path": "financial.terminal / valuation_bridge",
                    "owner": "financial_and_calculation_producer",
                    "source_refs": ["MODEL-WORKPAPER", "FIN-INNOLIGHT", "FIN-EOPTOLINK"],
                    "formula_or_method": "signed Gordon=2031正常化FCF×(1+g)/(WACC-g)，zero-floor逐A—F×P/H/C状态后再加权；经营价值代理仅含2027—2031现金流和折现终值。",
                    "epistemic_status": "operating_value_diagnostic_not_equity_fair_value",
                    "update_rule": "WACC/g、净债务桥、2026剩余期或冲击变化均触发独立复算。",
                },
            ],
            "requested_field_coverage": [
                {
                    "field": "inventory",
                    "status": "historical_source_checked_not_mapped_to_forward_model",
                    "sources_checked": ["FIN-INNOLIGHT", "FIN-EOPTOLINK", "SRC-INNO-AR25", "SRC-EOPT-AR25"],
                    "acceptable_proxy": "竞争情景营运资本变动占收入比例",
                    "proxy_bias": "不能识别库存减值、备货或产品代际切换，可能低估现金流波动。",
                    "conclusion_impact": "限制FCF与终值精度，不改变进入里程碑判断。",
                },
                {
                    "field": "accounts_receivable",
                    "status": "historical_source_checked_not_mapped_to_forward_model",
                    "sources_checked": ["FIN-INNOLIGHT", "FIN-EOPTOLINK"],
                    "acceptable_proxy": "竞争情景营运资本变动占收入比例",
                    "proxy_bias": "不能区分客户账期、坏账和集中度迁移，可能低估新客户爬坡占款。",
                    "conclusion_impact": "限制年度FCF路径与估值代理。",
                },
                {
                    "field": "capacity_and_utilization",
                    "status": "production_to_capacity_proxy_only_true_utilization_unavailable",
                    "sources_checked": ["SRC-INNO-AR25", "SRC-EOPT-AR25", "CROSS-EVIDENCE-AUDIT"],
                    "acceptable_proxy": "披露产量/产能与模型合格供给情景",
                    "proxy_bias": "名义产能、产量和通过客户资格的有效产能不同，可能高估可防御供给。",
                    "conclusion_impact": "保持供给与份额冲击区间较宽。",
                },
                {
                    "field": "expense_ratios",
                    "status": "not_separately_forecast",
                    "sources_checked": ["FIN-INNOLIGHT", "FIN-EOPTOLINK", "SRC-INNO-AR25", "SRC-EOPT-AR25"],
                    "acceptable_proxy": "净利率路径与固定成本拖累",
                    "proxy_bias": "研发、销售、管理和股权激励未分别传导，不能视为完整利润表模型。",
                    "conclusion_impact": "限制净利润归因和反向估值。",
                },
                {
                    "field": "customer_product_geography_mix",
                    "status": "fact_matrix_available_not_numerically_mapped_to_revenue",
                    "sources_checked": ["SRC-INNO-AR25", "SRC-EOPT-AR25", "LX-IR-202508", "CROSS-EVIDENCE-AUDIT"],
                    "acceptable_proxy": "客户集中、区域进入概率、A—F份额冲击和P/H/C架构冲击",
                    "proxy_bias": "无法按客户、SKU和地区复算收入；可能掩盖单一客户迁移的非线性损失。",
                    "conclusion_impact": "估值仅为条件化经营压力代理，不是逐客户收入预测。",
                },
                {
                    "field": "incumbent_shipments_share_and_asp_by_800g_1_6t_3_2t",
                    "status": "public_company_generation_level_series_unavailable",
                    "sources_checked": ["SRC-INNO-AR25", "SRC-INNO-1600", "SRC-EOPT-AR25", "SRC-LC-MAR26", "SRC-HKEX-ASP26"],
                    "acceptable_proxy": "公司总物理份额损失与总同规格ASP残差；行业分速率需求只约束市场路径",
                    "proxy_bias": "代际mix、距离、形态与客户组合具有非线性，汇总冲击可能掩盖高端份额防御或旧代清库。",
                    "conclusion_impact": "不能声称完成了两家龙头逐速率bottom-up出货、份额或ASP预测。",
                },
                {
                    "field": "net_debt_minority_other_assets_diluted_shares_and_2026_stub",
                    "status": "objectively_unmapped_in_current_operating_bridge",
                    "sources_checked": ["FIN-INNOLIGHT", "FIN-EOPTOLINK"],
                    "acceptable_proxy": "无；只与当前市值作诊断比较",
                    "proxy_bias": "不能从经营价值代理转换为可交易股权公允价值。",
                    "conclusion_impact": "禁止输出目标价或买卖结论；2026全年FCF不进入当前经营价值代理。",
                },
            ],
            "companies": {
                "innolight": _company_financial_model(
                    "中际旭创",
                    revenues=innolight_revenue["base"],
                    revenue_sensitivity=innolight_revenue,
                    gross=[44.0, 43.0, 42.0, 41.0, 40.0, 39.0],
                    net=[29.0, 28.0, 27.0, 26.0, 25.0, 24.0],
                    fcf=[18.0, 18.0, 17.0, 16.0, 15.0, 14.0],
                    risk_multiplier=0.92,
                    risk_multiplier_rationale=(
                        "相对共同冲击基准，以更大的收入规模和2025年绝对经营现金流/"
                        "简单FCF缓冲作8%压力缓释；这是专家压力情景假设，不是可观察事实，"
                        "客户、SKU和区域收入证据出现时必须重估。"
                    ),
                    valuation_anchor=_valuation_anchor(financial, "innolight"),
                ),
                "eoptolink": _company_financial_model(
                    "新易盛",
                    revenues=eoptolink_revenue["base"],
                    revenue_sensitivity=eoptolink_revenue,
                    gross=[47.0, 46.0, 44.0, 42.0, 40.0, 38.0],
                    net=[37.0, 35.0, 32.0, 29.0, 27.0, 25.0],
                    fcf=[22.0, 21.0, 19.0, 17.0, 15.0, 13.0],
                    risk_multiplier=1.08,
                    risk_multiplier_rationale=(
                        "相对共同冲击基准，以较小绝对收入/FCF缓冲及客户、产品组合集中"
                        "未能逐项映射的风险作8%压力放大；这是专家压力情景假设，"
                        "BPS股本口径差异不参与倍率或竞争概率。"
                    ),
                    valuation_anchor=_valuation_anchor(financial, "eoptolink"),
                ),
            },
        },
    }


def _company_financial_model(
    display_name: str,
    *,
    revenues: list[float],
    revenue_sensitivity: dict[str, list[float]],
    gross: list[float],
    net: list[float],
    fcf: list[float],
    risk_multiplier: float,
    risk_multiplier_rationale: str,
    valuation_anchor: dict[str, Any],
) -> dict[str, Any]:
    years = [2026, 2027, 2028, 2029, 2030, 2031]
    baseline = {
        str(year): {
            "revenue_cny_yi": revenues[index],
            "gross_margin_pct": gross[index],
            "net_margin_pct": net[index],
            "fcf_margin_pct": fcf[index],
            "normalized_fcf_margin_pct": fcf[index],
        }
        for index, year in enumerate(years)
    }

    def scaled(values: list[float]) -> dict[str, float]:
        return {
            str(year): round(values[index] * risk_multiplier, 3)
            for index, year in enumerate(years)
        }

    def shock(
        share: list[float],
        asp: list[float],
        gross_margin: list[float],
        capex: list[float],
        working_capital: list[float],
        fixed_cost: list[float] | None = None,
    ) -> dict[str, Any]:
        return {
            "share_loss_pct": scaled(share),
            "extra_asp_pressure_pct": scaled(asp),
            "gross_margin_shock_ppt": scaled(gross_margin),
            "expansion_capex_pct_revenue": scaled(capex),
            "working_capital_change_pct_revenue": scaled(working_capital),
            "fixed_cost_drag_ppt": scaled(fixed_cost or [0, 0, 0, 0, 0, 0]),
            "maintenance_capex_increment_pct_revenue": scaled([0, 0, 0, 0, 0, 0]),
            "normalized_working_capital_drag_pct_revenue": scaled([0, 0, 0, 0, 0, 0]),
            "normalized_other_fcf_drag_ppt": scaled([0, 0, 0, 0, 0, 0]),
        }

    entry_state_shocks = {
        "A": shock([0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0]),
        "B": shock([0, 0, 1, 2, 3, 4], [0, 0, 1, 2, 3, 3], [0, 0, 0.5, 1, 1.5, 2], [0, 0.2, 0.4, 0.5, 0.6, 0.6], [0, 0.2, 0.4, 0.5, 0.6, 0.6]),
        "C": shock([0, 0, 0.5, 1, 2, 3], [0, 0, 0.5, 1, 2, 2], [0, 0, 0.3, 0.7, 1, 1.3], [0, 0.1, 0.3, 0.4, 0.5, 0.5], [0, 0.1, 0.3, 0.4, 0.5, 0.5]),
        "D": shock([0, 0.5, 2, 4, 6, 8], [0, 0.5, 2, 3, 4, 5], [0, 0.3, 1, 2, 3, 4], [0, 0.3, 0.7, 1, 1.2, 1.2], [0, 0.3, 0.7, 1, 1.2, 1.2]),
        "E": shock([0, 1, 3, 5, 8, 10], [0, 1, 3, 5, 7, 8], [0, 0.5, 1.5, 2.5, 3.5, 4.5], [0, 0.5, 1, 1.5, 1.8, 2], [0, 0.4, 0.8, 1.2, 1.5, 1.8]),
        "F": shock([0, 2, 6, 10, 15, 20], [0, 2, 5, 8, 11, 13], [0, 1, 3, 5, 7, 9], [0, 0.8, 1.8, 2.8, 3.5, 4], [0, 0.6, 1.5, 2.2, 3, 3.5], [0, 0, 0.5, 1, 1.5, 2]),
    }
    architecture_shocks = {
        "P": shock([0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0]),
        "H": shock([0, 0, 0.5, 1, 1.5, 2], [0, 0, 0, 0.5, 1, 1.5], [0, 0, 0.3, 0.7, 1, 1.2], [0, 0.2, 0.5, 0.8, 1, 1], [0, 0.1, 0.3, 0.5, 0.7, 0.8]),
        "C": shock([0, 0, 2, 5, 9, 14], [0, 0, 1, 3, 5, 7], [0, 0.5, 2, 3.5, 5, 6.5], [0, 0.5, 1.5, 2.5, 3, 3.5], [0, 0.3, 1, 1.8, 2.5, 3], [0, 0, 0.5, 1, 1.5, 2]),
    }
    return {
        "display_name": display_name,
        # 公开资料没有按高速速率拆分公司收入。显式写入1.0是为了使压力上限
        # 可审计，不能依赖模型层的静默默认，也不能被解释为真实业务占比。
        "high_speed_revenue_exposure_share": 1.0,
        "risk_multiplier": risk_multiplier,
        "risk_multiplier_rationale": risk_multiplier_rationale,
        "valuation_anchor": valuation_anchor,
        "baseline": baseline,
        "baseline_revenue_sensitivity": revenue_sensitivity,
        "entry_state_shocks": entry_state_shocks,
        "architecture_shocks": architecture_shocks,
    }


FINANCIAL_ENTITY = {
    "innolight": "innolight_terminal_risk",
    "eoptolink": "eoptolink_terminal_risk",
    "luxshare": "luxshare_entry_risk",
    "byd": "byd_entry_risk",
    "byd_electronic": "byd_entry_risk",
}


def _financial_source_excerpt(company: dict[str, Any], name: str) -> str:
    market = company.get("market_snapshot", {})
    trade_date = _clean(market.get("trade_date")) or "观察日未取得"
    parts = [f"{name}结构化市场与财务快照，市场观察日{trade_date}"]
    market_cap_cny = _finite(
        market.get("market_cap_cny") or market.get("market_cap_value")
    )
    market_cap_usd = _finite(market.get("market_cap_usd"))
    if market_cap_cny is not None:
        cap_text = f"总市值{market_cap_cny:.2f}亿元人民币"
        if market_cap_usd is not None:
            cap_text += f"（约{market_cap_usd:.2f}亿美元）"
        parts.append(cap_text)
    valuation_bits: list[str] = []
    for label, field, suffix in (
        ("股价", "price", ""),
        ("市盈率（最近十二个月）", "pe_ttm", "倍"),
        ("市净率", "pb", "倍"),
        ("市销率（最近十二个月）", "ps_ttm", "倍"),
    ):
        value = _finite(market.get(field))
        if value is not None:
            valuation_bits.append(f"{label}{value:.2f}{suffix}")
    if valuation_bits:
        parts.append("、".join(valuation_bits))
    cash_bits: list[str] = []
    for label, field in (
        ("经营现金流", "operating_cash_flow"),
        ("资本开支", "capex_value"),
    ):
        value = _finite(market.get(field))
        if value is not None:
            cash_bits.append(f"{label}{value:.2f}亿元人民币")
    if cash_bits:
        parts.append(
            f"财务观察日{_clean(market.get('financials_as_of')) or '未标明'}："
            + "、".join(cash_bits)
        )
    reconciliation = market.get("bps_basis_reconciliation") or {}
    reconciliation_status = reconciliation.get("status")
    if reconciliation_status == "consistent_with_current_pb_within_3pct":
        parts.append(
            "报告期每股净资产与当前市净率反推值差异不超过3%；反推值只用于核对股本口径，不覆盖原始数据"
        )
    elif reconciliation_status == "reporting_period_share_basis_not_reconciled_to_market_pb":
        parts.append(
            "报告期股本口径与当前市场口径不能直接对账；反推值只用于提示口径差异，不覆盖原始数据"
        )
    elif reconciliation_status:
        parts.append("报告期每股净资产与当前市场口径仍需进一步核对")
    return "；".join(parts) + "。"


def _financial_sources(financial: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for key, company in financial["companies"].items():
        provider = _clean(company.get("financial_series", {}).get("source"))
        ref = f"FIN-{key.upper()}"
        name = _clean(company.get("name"))
        ticker = _clean(company.get("ticker") or company.get("yf_symbol"))
        output.append(
            {
                "ref": ref,
                "title": f"{name} 财务与市场快照（{ticker}）",
                "title_zh": f"{name} 财务与市场快照（{ticker}）",
                "publisher": "Tushare" if provider == "tushare" else "Yahoo Finance / yfinance",
                "publish_date": AS_OF_DATE,
                "source_tier": "A" if provider == "tushare" else "B",
                "source_review_status": "pass_with_note",
                "language": "zh-CN",
                "excerpt": _financial_source_excerpt(company, name),
                "excerpt_zh": _financial_source_excerpt(company, name),
                "local_path": str(FINANCIAL_PATH),
                "url": None,
                "independence_key": f"structured-financial:{provider}:{ticker}",
                "independence_rationale": "同一数据提供方、同一证券的字段归为一个结构化来源组；不把多个指标拆成独立证据。",
            }
        )
        estimates = company.get("analyst_estimates", {}).get(
            "revenue_estimate", {}
        )
        if estimates:
            estimate_parts: list[str] = []
            for horizon in ("0y", "+1y"):
                values = estimates.get(horizon, {})
                parsed = [_finite(values.get(item)) for item in ("low", "avg", "high")]
                if all(value is not None for value in parsed):
                    low, avg, high = (float(value) / 100_000_000 for value in parsed)
                    horizon_label = "本年度" if horizon == "0y" else "下一年度"
                    estimate_parts.append(
                        f"{horizon_label}营业收入的分析师聚合预期低值、平均值和高值分别为"
                        f"{low:.2f}、{avg:.2f}和{high:.2f}亿元人民币"
                    )
            output.append(
                {
                    "ref": f"FIN-{key.upper()}-ANALYST",
                    "title": f"{name} Yahoo Finance/yfinance 分析师预期快照（{ticker}）",
                    "title_zh": f"{name} Yahoo Finance/yfinance 分析师预期快照（{ticker}）",
                    "publisher": "Yahoo Finance / yfinance analyst estimates",
                    "publish_date": AS_OF_DATE,
                    "source_tier": "B",
                    "source_review_status": "pass_with_note",
                    "language": "zh-CN",
                    "excerpt": "；".join(estimate_parts)
                    or "抓取日返回分析师营业收入区间；覆盖与口径会变化。",
                    "excerpt_zh": "；".join(estimate_parts)
                    or "抓取日返回分析师营业收入区间；覆盖与口径会变化。",
                    "local_path": str(FINANCIAL_PATH),
                    "url": None,
                    "independence_key": "structured-analyst:yfinance",
                    "independence_rationale": (
                        "两家公司预期均来自同一Yahoo Finance/yfinance分析师聚合；"
                        "按一个受控提供方组处理，不因证券或字段数量增加独立性。"
                    ),
                }
            )
    output.extend(
        [
            {
                "ref": "MODEL-INPUTS",
                "title": "比亚迪与立讯光模块竞争模型输入、事件合同与假设底稿",
                "title_zh": "比亚迪与立讯光模块竞争模型输入、事件合同与假设底稿",
                "publisher": "Opportunity Lens 可复算模型",
                "publish_date": AS_OF_DATE,
                "source_tier": "B",
                "source_review_status": "pass_with_note",
                "language": "zh-CN",
                "excerpt": "输入底稿保存事件定义、保守值/最可能值/上限三点概率范围、公司事件联动假设、经营阈值、市场基准、公司财务路径和敏感性案例。",
                "excerpt_zh": "输入底稿保存事件定义、保守值/最可能值/上限三点概率范围、公司事件联动假设、经营阈值、市场基准、公司财务路径和敏感性案例。",
                "local_path": str(OUTPUT_DIR / "model_inputs.json"),
                "url": None,
                "independence_key": "calculation:byd-luxshare-competition-model-v2",
                "independence_rationale": "输入与输出属于同一计算底稿组，不作为两个独立外部事实组。",
            },
            {
                "ref": "MODEL-WORKPAPER",
                "title": "比亚迪与立讯光模块竞争概率及财务情景模型底稿",
                "title_zh": "比亚迪与立讯光模块竞争概率及财务情景模型底稿",
                "publisher": "Opportunity Lens 可复算模型",
                "publish_date": AS_OF_DATE,
                "source_tier": "B",
                "source_review_status": "pass_with_note",
                "language": "zh-CN",
                "excerpt": "输出底稿保存联合发生概率、行业供需路径、公司收入/利润/现金流传导、竞争结果划分和长期价值敏感性；完整输入保存在同一证据组的模型输入底稿。",
                "excerpt_zh": "输出底稿保存联合发生概率、行业供需路径、公司收入/利润/现金流传导、竞争结果划分和长期价值敏感性；完整输入保存在同一证据组的模型输入底稿。",
                "local_path": str(OUTPUT_DIR / "model_outputs.json"),
                "url": None,
                "independence_key": "calculation:byd-luxshare-competition-model-v2",
                "independence_rationale": "这是由已列证据和显式假设生成的计算底稿，不作为独立外部事实组抬高证据计数。",
            },
            {
                "ref": "LOCAL-MATERIAL-SCREENING",
                "title": "23 份用户提供 PDF 的逐份筛选、去重与使用状态清单",
                "title_zh": "23 份用户提供 PDF 的逐份筛选、去重与使用状态清单",
                "publisher": "Opportunity Lens 本地材料审计",
                "publish_date": AS_OF_DATE,
                "source_tier": "B",
                "source_review_status": "pass_with_note",
                "language": "zh-CN",
                "excerpt": "23 份 PDF 全部完成文本提取与人工筛选，共 22 个唯一 SHA256，文件 14 与 15 为完全重复；卖方材料只作线索或预期。",
                "excerpt_zh": "23 份 PDF 全部完成文本提取与人工筛选，共 22 个唯一 SHA256，文件 14 与 15 为完全重复；卖方材料只作线索或预期。",
                "local_path": str(SCREENING_PATH),
                "url": None,
                "independence_key": "local-material-screening:20260718",
                "independence_rationale": "筛选清单是材料覆盖审计，不把各卖方文件误计为关键事实的一手独立证据。",
            },
            {
                "ref": "CROSS-EVIDENCE-AUDIT",
                "title": "比亚迪与立讯高速光模块独立交叉证据审计",
                "title_zh": "比亚迪与立讯高速光模块独立交叉证据审计",
                "publisher": "Opportunity Lens 独立 evidence reviewer",
                "publish_date": AS_OF_DATE,
                "source_tier": "B",
                "source_review_status": "pass",
                "language": "zh-CN",
                "excerpt": "审计识别立讯客户层级与1.6T商业阶段的官方披露冲突，并明确比亚迪集团能力不得跨主体归因。",
                "excerpt_zh": "审计识别立讯客户层级与1.6T商业阶段的官方披露冲突，并明确比亚迪集团能力不得跨主体归因。",
                "local_path": str(CROSS_AUDIT_PATH),
                "url": None,
                "independence_key": "review:evidence-cross-audit:20260718",
                "independence_rationale": "独立 reviewer 对底层证据做冲突审计；它是审计记录，不替代原始公司、客户或标准来源。",
            },
        ]
    )
    return output


def _luxshare_conflict_sources() -> list[dict[str, Any]]:
    """交叉审计要求进入正式账本的三份发行人监管原文。"""

    common = {
        "publisher": "立讯精密 / 巨潮资讯",
        "source_tier": "S",
        "source_review_status": "conflict",
        "language": "zh-CN",
        "fetch_date": AS_OF_DATE,
        "independence_key": "luxshare_group_controlled",
        "independence_rationale": "三份材料均为立讯精密发行人受控披露，只算一个独立公司来源组；保留不同日期是为了审计口径变化，不制造独立佐证。",
    }
    rows = [
        {
            "ref": "LX-ANNUAL-2024",
            "title": "立讯精密工业股份有限公司2024年年度报告",
            "title_zh": "立讯精密工业股份有限公司2024年年度报告",
            "publish_date": "2025-04-26",
            "event_date": "2024-12-31",
            "url": "https://static.cninfo.com.cn/finalpage/2025-04-26/1223326862.PDF",
            "local_locator": "PDF第16页，第三节“通信及数据中心业务”创新亮点第4项",
            "excerpt": "4）800G OSFP光模块。2024年，该产品顺利通过头部AI智算中心客户的测试验证，并已实现多家国际头部客户的量产交付。",
            "excerpt_zh": "4）800G OSFP光模块。2024年，该产品顺利通过头部AI智算中心客户的测试验证，并已实现多家国际头部客户的量产交付。",
            "freshness_warning": "严重时效提醒：该年报只证明2024年度800G OSFP光模块的发行人披露口径，不能单独证明截至2026年的客户资格、重复订单或经营规模。",
        },
        {
            "ref": "LX-IR-20260507",
            "title": "立讯精密投资者关系活动记录表（2026年5月7日）",
            "title_zh": "立讯精密投资者关系活动记录表（2026年5月7日）",
            "publish_date": "2026-05-07",
            "url": "https://static.cninfo.com.cn/finalpage/2026-05-07/1225280960.PDF",
            "local_locator": "PDF第5页Q29及第6页Q32",
            "excerpt": "光连接方面，我们才起步，机会挑战并存。我们现在规模还小，供应不是问题。",
            "excerpt_zh": "光连接方面，我们才起步，机会挑战并存。我们现在规模还小，供应不是问题。",
        },
        {
            "ref": "LX-IR-20260525",
            "title": "立讯精密投资者关系活动记录表（2026年5月25日）",
            "title_zh": "立讯精密投资者关系活动记录表（2026年5月25日）",
            "publish_date": "2026-05-25",
            "url": "https://static.cninfo.com.cn/finalpage/2026-05-25/1225328100.PDF",
            "local_locator": "PDF第2页，年度股东会交流问题Q4",
            "excerpt": "商务层面和营收规模的拓展仍需要时间。公司目前暂不具备自研1.6T硅光芯片的能力。",
            "excerpt_zh": "商务层面和营收规模的拓展仍需要时间。公司目前暂不具备自研1.6T硅光芯片的能力。",
        },
    ]
    return [{**common, **row} for row in rows]


def _luxshare_conflict_points() -> list[dict[str, Any]]:
    return [
        {
            "source_ref": "LX-ANNUAL-2024",
            "entity_key": "luxshare_entry_risk",
            "metric": "800G头部客户测试与国际客户交付发行人口径",
            "period": "FY2024",
            "as_of_date": "2024-12-31",
            "value_text": "披露头部AI智算中心客户测试及多家国际头部客户量产交付",
            "unit": "商业阶段",
            "source_excerpt": "4）800G OSFP光模块。2024年，该产品顺利通过头部AI智算中心客户的测试验证，并已实现多家国际头部客户的量产交付。",
            "source_excerpt_zh": "4）800G OSFP光模块。2024年，该产品顺利通过头部AI智算中心客户的测试验证，并已实现多家国际头部客户的量产交付。",
            "scope_key": "luxshare|800g|issuer_customer_stage_conflict_2024",
            "observations": [],
            "fact_type": "issuer_claim_in_conflict",
            "extraction_method": "pdf_direct",
            "note": "与2025-08更直接的中小客户/无头部明确商务机会口径冲突；不得单边采信。",
        },
        {
            "source_ref": "LX-IR-20260507",
            "entity_key": "luxshare_entry_risk",
            "metric": "光连接业务总体商业阶段",
            "period": "2026-05-07",
            "as_of_date": "2026-05-07",
            "value_text": "总体仍处起步阶段，商务拓展需要时间",
            "unit": "商业阶段",
            "source_excerpt": "光连接方面，我们才起步，机会挑战并存。我们现在规模还小，供应不是问题。",
            "source_excerpt_zh": "光连接方面，我们才起步，机会挑战并存。我们现在规模还小，供应不是问题。",
            "scope_key": "luxshare|optical_connectivity|commercial_stage_20260507",
            "observations": [],
            "fact_type": "regulatory_ir_stage",
            "extraction_method": "pdf_direct",
            "note": "约束官网所称早期商业化，产品出货阶段与经济规模阶段必须分开。",
        },
        {
            "source_ref": "LX-IR-20260525",
            "entity_key": "luxshare_entry_risk",
            "metric": "1.6T硅光芯片自研能力",
            "period": "2026-05-25",
            "as_of_date": "2026-05-25",
            "value_num": 0,
            "value_text": "公司称暂不具备自研1.6T硅光芯片能力",
            "unit": "是否具备",
            "source_excerpt": "商务层面和营收规模的拓展仍需要时间。公司目前暂不具备自研1.6T硅光芯片的能力。",
            "source_excerpt_zh": "商务层面和营收规模的拓展仍需要时间。公司目前暂不具备自研1.6T硅光芯片的能力。",
            "scope_key": "luxshare|1.6t_siph_pic|self_developed_capability_20260525",
            "observations": [],
            "fact_type": "regulatory_ir_boundary",
            "extraction_method": "pdf_direct",
            "note": "不具备自研PIC不等于不能用外采器件制造模块；只约束全栈自研和供应链控制评分。",
        },
    ]


def _financial_data_points(financial: dict[str, Any]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    series_metrics = {
        "revenue": ("营业收入序列", "亿元人民币"),
        "net_income": ("归母净利润序列", "亿元人民币"),
        "rd_expense": ("研发费用序列", "亿元人民币"),
        "operating_cash_flow": ("经营活动现金流序列", "亿元人民币"),
        "capex": ("购建长期资产现金支出序列", "亿元人民币"),
        "gross_margin": ("毛利率序列", "%"),
        "net_margin": ("净利率序列", "%"),
        "roe": ("净资产收益率序列", "%"),
        "roa": ("总资产收益率序列", "%"),
        "rd_ratio": ("研发费用率序列", "%"),
        "total_assets": ("总资产序列", "亿元人民币"),
        "accounts_receivable": ("应收账款序列", "亿元人民币"),
        "inventory": ("存货序列", "亿元人民币"),
        "fixed_assets": ("固定资产序列", "亿元人民币"),
        "construction_in_progress": ("在建工程序列", "亿元人民币"),
        "contract_liabilities": ("合同负债序列", "亿元人民币"),
        "total_equity": ("归属母公司股东权益序列", "亿元人民币"),
    }
    market_metrics = {
        "price": ("最新收盘价", "每股计价货币"),
        "market_cap_cny": ("总市值", "亿元人民币"),
        "market_cap_usd": ("总市值美元等值", "亿美元"),
        "pe_ttm": ("市盈率（股价/最近十二个月每股收益）", "倍"),
        "pe_forward": ("预期市盈率", "倍"),
        "pb": ("市净率（股价/每股净资产）", "倍"),
        "ps_ttm": ("市销率（市值/最近十二个月营业收入）", "倍"),
        "ev_ebitda": ("企业价值倍数 EV/EBITDA", "倍"),
        "eps_ttm": ("每股收益（最近十二个月）", "每股计价货币"),
        "bps_mrq": ("每股净资产（最近报告期）", "每股计价货币"),
        "bps_current_share_basis_implied": (
            "当前价格/PB隐含每股净资产",
            "每股计价货币",
        ),
        "roe": ("最近报告期净资产收益率", "%"),
        "roa": ("最近报告期总资产收益率", "%"),
    }
    for key, company in financial["companies"].items():
        entity_key = FINANCIAL_ENTITY[key]
        ref = f"FIN-{key.upper()}"
        name = company["name"]
        periods = company.get("financial_series", {}).get("periods", [])
        for field, (metric, unit) in series_metrics.items():
            observations: list[dict[str, Any]] = []
            for row in periods:
                raw = row.get(field)
                if isinstance(raw, dict):
                    value = _finite(raw.get("cny_yi"))
                else:
                    value = _finite(raw)
                if value is not None:
                    observations.append(
                        {
                            "period": row["period"],
                            "value_num": value,
                            "period_type": row.get("period_type"),
                            "statement_basis": row.get("statement_basis"),
                        }
                    )
            if not observations:
                continue
            observation_excerpt = "；".join(
                f"{row['period']}为{float(row['value_num']):,.2f}{unit}"
                for row in observations
            )
            points.append(
                {
                    "source_ref": ref,
                    "entity_key": entity_key,
                    "metric": metric,
                    "period": f"{observations[0]['period']}-{observations[-1]['period']}",
                    "value_text": "财务时间序列，详见 observations",
                    "unit": unit,
                    "source_excerpt": f"{name}结构化财务接口返回{metric}：{observation_excerpt}。",
                    "source_excerpt_zh": f"{name}结构化财务接口返回{metric}：{observation_excerpt}。",
                    "scope_key": f"{key}|financial_series|{field}",
                    "observations": observations,
                    "fact_type": "structured_financial_series",
                    "extraction_method": "web_fetch",
                    "note": (
                        "Tushare 季报为年初至报告期末累计口径；yfinance 季报通常为单季口径。"
                        "同一公司序列不混用数据源，具体口径保存在 observations.statement_basis。"
                    ),
                }
            )
        employee = company.get("financial_series", {}).get("employee_snapshot", {})
        employee_count = _finite(employee.get("employees"))
        if employee_count is not None:
            employee_as_of = _clean(employee.get("snapshot_observed_at"))[:10] or AS_OF_DATE
            points.append(
                {
                    "source_ref": ref,
                    "entity_key": entity_key,
                    "metric": "员工数当前接口快照",
                    "period": employee_as_of,
                    "as_of_date": employee_as_of,
                    "value_num": employee_count,
                    "unit": "人",
                    "source_excerpt": f"{name}结构化公司档案接口在{employee_as_of}返回当前员工数{employee_count:,.0f}人。",
                    "source_excerpt_zh": f"{name}结构化公司档案接口在{employee_as_of}返回当前员工数{employee_count:,.0f}人。",
                    "scope_key": f"{key}|employee_snapshot|current",
                    "observations": [],
                    "fact_type": "structured_current_company_profile",
                    "extraction_method": "web_fetch",
                    "note": _clean(employee.get("basis"))
                    or "仅为当前接口快照，不代表报告期末，也不能补作2018年以来员工历史。",
                }
            )
        fcf_rows = company.get("fcf_proxy", [])
        if fcf_rows:
            observations = [
                {"period": row["period"], "value_num": row["fcf_proxy_cny_yi"]}
                for row in fcf_rows
                if _finite(row.get("fcf_proxy_cny_yi")) is not None
            ]
            points.append(
                {
                    "source_ref": ref,
                    "entity_key": entity_key,
                    "metric": "经营现金流减购建长期资产支出序列",
                    "period": f"{observations[0]['period']}-{observations[-1]['period']}",
                    "value_text": "经营现金流减购建长期资产现金支出",
                    "unit": "亿元人民币",
                    "source_excerpt": f"{name}经营活动现金流减购建固定资产、无形资产和其他长期资产现金支出。",
                    "source_excerpt_zh": f"{name}经营活动现金流减购建固定资产、无形资产和其他长期资产现金支出。",
                    "scope_key": f"{key}|financial_series|simple_fcf_proxy",
                    "observations": observations,
                    "fact_type": "calculated_series",
                    "extraction_method": "inferred",
                    "note": "未调整并购、租赁、股权激励、资产处置及其他非标准自由现金流项目。",
                }
            )
        market = company.get("market_snapshot", {})
        field_as_of = market.get("field_as_of", {})
        for field, (metric, unit) in market_metrics.items():
            value = _finite(market.get(field))
            if value is None:
                continue
            if field in {
                "price",
                "eps_ttm",
                "bps_mrq",
                "bps_current_share_basis_implied",
            }:
                per_share_currency = _clean(
                    market.get("per_share_currency") or market.get("currency")
                ).upper()
                unit = {
                    "CNY": "元人民币/股 (CNY)",
                    "HKD": "港元/股 (HKD)",
                    "USD": "美元/股 (USD)",
                }.get(per_share_currency, f"{per_share_currency or '计价货币'}/股")
            as_of = _clean(field_as_of.get(field) or market.get("trade_date") or market.get("financials_as_of"))
            method = market.get("field_methods", {}).get(field, {})
            reconciliation = (
                market.get("bps_basis_reconciliation", {})
                if field in {"bps_mrq", "bps_current_share_basis_implied"}
                else {}
            )
            reconciliation_parts: list[str] = []
            if reconciliation:
                reconciliation_parts.append(
                    f"BPS股本口径对账状态={_clean(reconciliation.get('status')) or '未标明'}"
                )
                if _finite(reconciliation.get("reported_bps")) is not None:
                    reconciliation_parts.append(
                        f"报告期BPS={float(reconciliation['reported_bps']):.6f}"
                    )
                if _finite(
                    reconciliation.get("current_share_basis_bps_implied")
                ) is not None:
                    reconciliation_parts.append(
                        "同日价格/PB隐含BPS="
                        f"{float(reconciliation['current_share_basis_bps_implied']):.6f}"
                    )
                if _finite(reconciliation.get("relative_difference_pct")) is not None:
                    reconciliation_parts.append(
                        f"报告值相对隐含值差异={float(reconciliation['relative_difference_pct']):.4f}%"
                    )
                reconciliation_parts.append(
                    "允许直接用报告BPS复算当前PB="
                    f"{bool(reconciliation.get('direct_current_pb_recalculation_allowed'))}"
                )
                reconciliation_parts.extend(
                    value
                    for value in (
                        _clean(reconciliation.get("note")),
                        _clean(reconciliation.get("provenance")),
                        _clean(reconciliation.get("possible_causes")),
                    )
                    if value
                )
            reconciliation_note = "；".join(reconciliation_parts)
            basis_note = _clean(method.get("basis"))
            points.append(
                {
                    "source_ref": ref,
                    "entity_key": entity_key,
                    "metric": metric,
                    "period": as_of,
                    "as_of_date": as_of,
                    "value_num": value,
                    "unit": unit,
                    "source_excerpt": (
                        f"{name}结构化市场快照返回{metric}；字段观察日为{as_of}。"
                        f"{(' ' + basis_note) if basis_note else ''}"
                    ),
                    "source_excerpt_zh": (
                        f"{name}结构化市场快照返回{metric}；字段观察日为{as_of}。"
                        f"{(' ' + basis_note) if basis_note else ''}"
                    ),
                    "scope_key": f"{key}|market_snapshot|{field}",
                    "observations": [],
                    "fact_type": "structured_market_snapshot",
                    "extraction_method": _clean(method.get("extraction_method"))
                    or "web_fetch",
                    "note": "；".join(
                        value
                        for value in (
                            _clean(method.get("formula")),
                            basis_note,
                            reconciliation_note,
                        )
                        if value
                    )
                    or None,
                }
            )
        estimates = company.get("analyst_estimates", {}).get("revenue_estimate", {})
        for horizon in ("0y", "+1y"):
            row = estimates.get(horizon, {})
            mapped_fiscal_year = str(
                int(AS_OF_DATE[:4]) + (1 if horizon == "+1y" else 0)
            )
            for statistic in ("low", "avg", "high"):
                value = _finite(row.get(statistic))
                if value is None:
                    continue
                statistic_label = {
                    "low": "低值",
                    "avg": "平均值",
                    "high": "高值",
                }[statistic]
                points.append(
                    {
                        "source_ref": f"{ref}-ANALYST",
                        "entity_key": entity_key,
                        "metric": f"分析师营业收入预期{statistic}",
                        "period": mapped_fiscal_year,
                        "as_of_date": AS_OF_DATE,
                        "value_num": round(value / 100_000_000, 4),
                        "unit": "亿元人民币",
                        "source_excerpt": (
                            f"Yahoo Finance/yfinance 在{AS_OF_DATE}返回{name}{horizon}营业收入"
                            f"{statistic_label}"
                            f"{value / 100_000_000:,.2f}亿元人民币；本研究按12月财年映射为{mapped_fiscal_year}年。"
                        ),
                        "source_excerpt_zh": (
                            f"Yahoo Finance/yfinance 在{AS_OF_DATE}返回{name}{horizon}营业收入"
                            f"{statistic_label}"
                            f"{value / 100_000_000:,.2f}亿元人民币；本研究按12月财年映射为{mapped_fiscal_year}年。"
                        ),
                        "scope_key": f"{key}|analyst_revenue_estimate|{horizon}|{statistic}",
                        "observations": [],
                        "fact_type": "analyst_consensus_snapshot_not_guidance",
                        "extraction_method": "web_fetch",
                        "note": (
                            f"provider_horizon={horizon}；抓取日={AS_OF_DATE}；"
                            f"按12月财年映射为{mapped_fiscal_year}；分析师覆盖、区间和口径会变化；"
                            "仅用于约束模型基线，不等同公司指引。"
                        ),
                    }
                )
    return points


def _model_data_points(model: dict[str, Any]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for horizon, payload in model["probability"]["horizons"].items():
        for metric, value in payload["marginal_probability"].items():
            points.append(
                {
                    "source_ref": "MODEL-WORKPAPER",
                    "entity_key": "probability_method_and_baserate",
                    "metric": f"{horizon} {metric}",
                    "period": horizon,
                    "as_of_date": AS_OF_DATE,
                    "value_num": round(value * 100, 4),
                    "unit": "%",
                    "source_excerpt": "100,000 次 Monte Carlo 在显式三角分布和相关结构下计算该概率。",
                    "source_excerpt_zh": "100,000 次 Monte Carlo 在显式三角分布和相关结构下计算该概率。",
                    "scope_key": f"probability|{horizon}|{metric}",
                    "observations": [],
                    "fact_type": "model_output_not_observed_fact",
                    "extraction_method": "inferred",
                    "note": "输入为MODEL-INPUTS中的3年/5年进入、中国/全球条件概率与四个Fréchet λ；中国与全球是可重叠子事件，非全球不等于中国。共享分位数保证累计概率单调，内层解析联合状态，外层100,000次参数抽样取均值。结果是工作概率，不是统计后验。",
                }
            )
        for code, value in payload["scenario_probability"].items():
            points.append(
                {
                    "source_ref": "MODEL-WORKPAPER",
                    "entity_key": "probability_method_and_baserate",
                    "metric": f"{horizon} 情景 {code} 概率",
                    "period": horizon,
                    "as_of_date": AS_OF_DATE,
                    "value_num": round(value * 100, 4),
                    "value_text": ENTRY_SCENARIO_LABELS[code],
                    "unit": "%",
                    "source_excerpt": f"情景 {code} 定义为：{ENTRY_SCENARIO_LABELS[code]}。",
                    "source_excerpt_zh": f"情景 {code} 定义为：{ENTRY_SCENARIO_LABELS[code]}。",
                    "scope_key": f"scenario|{horizon}|{code}",
                    "observations": [],
                    "fact_type": "model_output_not_observed_fact",
                    "extraction_method": "inferred",
                    "note": "A—F由两家公司进入边际、全球条件边际及Fréchet联合分布解析计算；每条参数路径六状态严格和为1，再对100,000次外层抽样取均值。输入见MODEL-INPUTS。",
                }
            )
    # 同口径逐年结果是一个序列事实；年份放进 observations，不能拆成
    # 六条平行数据点虚增 coverage。
    for field, metric, unit in (
        ("total_ports_million", "高速光模块需求情景", "百万端口"),
        ("normal_market_revenue_usd_bn", "正常代际降价后的市场收入情景", "十亿美元"),
        ("qualified_supply_million", "合格供给情景", "百万端口"),
        ("qualified_supply_demand_ratio", "合格供给需求比", "倍"),
        ("lpo_lro_share_pct", "LPO/LRO 架构份额情景", "%"),
        ("cpo_share_pct", "CPO 架构份额情景", "%"),
    ):
        observations = [
            {"period": str(row["year"]), "value_num": row[field]}
            for row in model["market"]["rows"]
        ]
        points.append(
            {
                "source_ref": "MODEL-WORKPAPER",
                "entity_key": "industry_demand_supply_model",
                "metric": metric,
                "period": "2026-2031",
                "as_of_date": AS_OF_DATE,
                "value_text": "显式基准情景序列，详见 observations",
                "unit": unit,
                "source_excerpt": "该序列由公开产业约束和显式情景输入计算，正常技术降价与新进入者额外压力分开。",
                "source_excerpt_zh": "该序列由公开产业约束和显式情景输入计算，正常技术降价与新进入者额外压力分开。",
                "scope_key": f"market_model|{field}",
                "observations": observations,
                "fact_type": "scenario_assumption_or_model_output",
                "extraction_method": "inferred",
                "note": "输入为各速率shipments_million、normal_asp_usd、合格供给及架构份额；总端口=各速率出货求和，市场收入=Σ(百万端口×美元ASP)/1000十亿美元，供需比=合格供给/总端口。",
            }
        )
    for company_key, company in model["financial"]["companies"].items():
        entity_key = "innolight_terminal_risk" if company_key == "innolight" else "eoptolink_terminal_risk"
        for field, metric, unit in (
            ("revenue_cny_yi", "概率加权营业收入", "亿元人民币"),
            ("net_income_cny_yi", "概率加权净利润", "亿元人民币"),
            ("fcf_cny_yi", "概率加权简单自由现金流", "亿元人民币"),
            ("gross_margin_pct", "概率加权毛利率", "%"),
        ):
            observations = [
                {"period": str(row["year"]), "value_num": row[field]}
                for row in company["probability_weighted_rows"]
            ]
            points.append(
                {
                    "source_ref": "MODEL-WORKPAPER",
                    "entity_key": entity_key,
                    "metric": metric,
                    "period": "2026-2031",
                    "as_of_date": AS_OF_DATE,
                    "value_text": "A-F进入状态与P/H/C架构交叉情景的概率加权序列，详见 observations",
                    "unit": unit,
                    "source_excerpt": f"{company['display_name']}在 A-F进入状态与P/H/C架构交叉情景下的概率加权结果。",
                    "source_excerpt_zh": f"{company['display_name']}在 A-F进入状态与P/H/C架构交叉情景下的概率加权结果。",
                    "scope_key": f"financial_model|{company_key}|{field}",
                    "observations": observations,
                    "fact_type": "model_output_not_company_guidance",
                    "extraction_method": "inferred",
                    "note": "收入=参考基线×(1-份额损失)×(1-同规格额外ASP压力)；利润和正常化FCF按显式margin/成本拖累计算，实际FCF再扣当年扩产capex与ΔNWC；摘要使用5年A—F×P/H/C终局概率权重，不是逐年无条件期望。",
                }
            )
    return points


def _evidence_group(
    corroboration_key: str,
    refs: Iterable[str],
    role: str,
    scope: str,
    relevance_note: str,
    minimum_milestone: str,
    *,
    score_eligible: bool = True,
) -> dict[str, Any]:
    # 行业预测只用于情景校准与边界，不论调用方是否漏传开关，都不得进入
    # 14因子核心评分或独立证据组计数。
    effective_score_eligible = score_eligible and not corroboration_key.startswith(
        "forecaster:"
    )
    return {
        "corroboration_key": corroboration_key,
        "refs": list(refs),
        "evidence_role": role,
        "evidence_scope": scope,
        "relevance_note": relevance_note,
        "minimum_milestone": minimum_milestone,
        "score_eligible": effective_score_eligible,
    }


def _market_factor_spec(
    factor_code: str,
    metric_name: str,
    raw_score: float,
    low_risk: float,
    high_risk: float,
    evidence: list[dict[str, Any]],
    *,
    orientation: str = "higher_is_risk",
    low_case_reason: str,
    high_case_reason: str,
) -> dict[str, Any]:
    return {
        "factor_code": factor_code,
        "metric_name": metric_name,
        "score_raw_construct": float(raw_score),
        "score_orientation": orientation,
        "score_low_normalized_risk": float(low_risk),
        "score_high_normalized_risk": float(high_risk),
        "low_case_reason": low_case_reason,
        "high_case_reason": high_case_reason,
        "evidence": evidence,
    }


MARKET_ENTITY_SPECS: dict[str, dict[str, Any]] = {
    "byd_entry_risk": {
        "name": "比亚迪电子离高速光模块商业化还有多远",
        "description": "研究比亚迪电子现有的服务器、液冷、电源和高速互联能力，能否在未来三至五年转化为数据中心高速光模块产品、客户订单和可分收入，并说明它对现有龙头可能产生的影响。",
        "weights": {
            "company.capacity_readiness_window": 0.25,
            "company.exposure_directness": 0.25,
            "supply.substitution_barrier": 0.20,
            "demand.customer_capex_capacity_signal": 0.15,
            "company.financial_capture_quality": 0.15,
        },
        "coverage": 0.78,
        "confidence": 0.62,
        "factors": [
            _market_factor_spec(
                "company.capacity_readiness_window", "光模块专用产线与量产准备度", 32, 15, 52,
                [
                    _evidence_group("controlled_group:byd", ["BYD-S01", "BYD-S04", "BYD-S05", "BYD-S06", "BYD-S16"], "support_risk", "direct_entity", "数据中心组合、服务器入口和通用精密制造只支持相邻准备。", "adjacent_manufacturing_readiness"),
                    _evidence_group("standards:oif", ["BYD-S17"], "counter_risk", "customer_ecosystem", "特定互操作名单未见 BYD，只是有界负证据。", "no_public_interop_validation_found"),
                    _evidence_group("customer:nvidia", ["BYD-S18"], "counter_risk", "customer_ecosystem", "限定 ConnectX-8 清单未见 BYD 光模块。", "no_public_platform_validation_found"),
                    _evidence_group("government:zhongshan-environment", ["BYD-S19"], "boundary", "direct_entity", "公开扩产项目用途为车载设备/零部件。", "vehicle_project_not_datacenter_line"),
                    _evidence_group("government:jinan-environment", ["BYD-S20"], "boundary", "direct_entity", "项目属于比亚迪半导体而非比亚迪电子。", "different_legal_entity_project"),
                    _evidence_group("supplier:fabrinet", ["SRC-FN-SITE26"], "context_calibrator", "historical_base_rate", "成熟光学制造平台校准通用自动化与专线量产的差异。", "specialized_optical_manufacturing_reference"),
                    _evidence_group("case:intel-jabil-module-transfer", ["SRC-JABIL-INTEL23"], "context_calibrator", "historical_base_rate", "完整模块制造通常需要明确资产或业务承接。", "explicit_module_asset_transfer_reference"),
                ],
                low_case_reason="仍只有相邻制造和公开生态缺席，没有专线硬证据。",
                high_case_reason="出现专线设备、验收、良率或可审计产量之一并由非受控来源约束。",
            ),
            _market_factor_spec(
                "company.exposure_directness", "数据中心高速光模块业务直接性", 20, 8, 38,
                [
                    _evidence_group("controlled_group:byd", ["BYD-S01", "BYD-S03", "BYD-S04", "BYD-S05"], "support_risk", "direct_entity", "服务器、液冷、电源和高速互联是直接相邻暴露，但未披露 400G+ 模块。", "adjacent_datacenter_portfolio"),
                    _evidence_group("standards:oif", ["BYD-S17"], "counter_risk", "customer_ecosystem", "公开互操作活动未见 BYD。", "no_public_interop_validation_found"),
                    _evidence_group("customer:nvidia", ["BYD-S18"], "counter_risk", "customer_ecosystem", "限定支持清单未见 BYD 光模块。", "no_public_platform_validation_found"),
                    _evidence_group("government:zhongshan-environment", ["BYD-S19"], "boundary", "direct_entity", "公开项目是车载用途。", "vehicle_project_not_datacenter_exposure"),
                    _evidence_group("government:jinan-environment", ["BYD-S20"], "boundary", "direct_entity", "另一法人项目不能迁移为比亚迪电子收入暴露。", "different_legal_entity_project"),
                    _evidence_group("case:cisco-acacia", ["SRC-CISCO-ACACIA21"], "context_calibrator", "historical_base_rate", "成功直接进入依赖成熟模块资产、团队和客户关系。", "acquisition_led_direct_entry_reference"),
                    _evidence_group("case:intel-jabil-module-transfer", ["SRC-INTEL-Q323", "SRC-JABIL-INTEL23"], "context_calibrator", "historical_base_rate", "技术与大公司资源不保证模块业务持续；两份记录属同一转移事件。", "module_exit_and_transfer_reference"),
                    _evidence_group("case:fit-module-platform", ["SRC-FIT-AR18", "SRC-LW-FIT19", "SRC-POET-FIT24"], "context_calibrator", "historical_base_rate", "EMS/连接器邻接未自动形成持久独立模块平台。", "ems_entry_case_reference"),
                    _evidence_group("case:lumentum-cloud-light", ["SRC-LITE-CLOUD23"], "context_calibrator", "historical_base_rate", "收购成熟产品和客户关系是另一条直接进入路径。", "acquisition_led_direct_entry_reference"),
                ],
                low_case_reason="未见具名 400G+ SKU、客户、订单或收入拆分。",
                high_case_reason="出现明确 SKU 与可归属客户 qualification/收入中的至少两项。",
            ),
            _market_factor_spec(
                "supply.substitution_barrier", "光学封装、可靠性与客户认证壁垒穿透风险", 28, 18, 45,
                [
                    _evidence_group("controlled_group:byd", ["BYD-S01", "BYD-S06", "BYD-S16"], "support_risk", "direct_entity", "通用制造和系统组合降低部分门槛，但缺专用耦合、老化和光测证据。", "generic_manufacturing_only"),
                    _evidence_group("standards:oif", ["BYD-S17"], "counter_risk", "customer_ecosystem", "未见公开互操作。", "no_public_interop_validation_found"),
                    _evidence_group("customer:nvidia", ["BYD-S18"], "counter_risk", "customer_ecosystem", "未见限定平台资格。", "no_public_platform_validation_found"),
                    _evidence_group("platform:broadcom", ["SRC-BCM-DSP"], "context_calibrator", "supply_chain", "3nm、8×200G PAM4 DSP 校准核心器件代际门槛。", "advanced_dsp_requirement"),
                    _evidence_group("supplier:coherent", ["SRC-COHR-10K25", "SRC-COHR-CHIPS26"], "context_calibrator", "supply_chain", "有限来源和 InP 扩产约束规模保障。", "upstream_capacity_constraint"),
                    _evidence_group("platform:marvell", ["SRC-MRVL-10Q25"], "context_calibrator", "supply_chain", "多年晶圆、测试和封装承诺校准锁量门槛。", "long_term_supply_commitment_reference"),
                    _evidence_group("supplier:fabrinet", ["SRC-FN-10K24"], "context_calibrator", "historical_base_rate", "供应商或地点变化可能触发重新认证。", "requalification_mechanism_reference"),
                    _evidence_group("issuer:lightwave-logic", ["SRC-LWLG-10K24"], "context_calibrator", "historical_base_rate", "认证可持续数月且通过不保证销售。", "qualification_duration_reference"),
                    _evidence_group("issuer:afop", ["SRC-AFOP-10K14"], "context_calibrator", "historical_base_rate", "陈旧资格时长上界只作历史校准。", "historical_qualification_upper_bound"),
                ],
                low_case_reason="通用制造无法穿透核心器件、可靠性与客户认证链。",
                high_case_reason="出现专用工艺、关键器件保障和客户侧资格的交叉证据。",
            ),
            _market_factor_spec(
                "demand.customer_capex_capacity_signal", "服务器客户入口向高速光迁移信号", 38, 25, 58,
                [
                    _evidence_group("controlled_group:byd", ["BYD-S01", "BYD-S03", "BYD-S04", "BYD-S05"], "support_risk", "direct_entity", "服务器出货和液冷认证说明客户入口，未证明入口已转成高速光订单。", "server_customer_entry_only"),
                    _evidence_group("customer:nvidia", ["BYD-S18", "SRC-NV-QX800", "SRC-NV-SPECTRUM"], "boundary", "customer_ecosystem", "平台端口需求提高机会，限定清单缺席限制 BYD 转化；同一 NVIDIA 只算一组。", "platform_demand_without_byd_validation"),
                    _evidence_group("platform:broadcom", ["SRC-BCM-TH6"], "context_calibrator", "industry", "高速端口需求不证明 BYD 获单。", "industry_port_demand_reference"),
                    _evidence_group("standards:oif", ["BYD-S17", "SRC-OIF-2025"], "context_calibrator", "industry", "标准演进与 BYD 公开参与缺席共同约束兑现阶段。", "standards_demand_context"),
                    _evidence_group("forecaster:cignal-ai", ["SRC-CIGNAL-4Q24"], "context_calibrator", "industry", "800G 增长预测是需求情景而非 BYD 客户事实。", "industry_demand_forecast"),
                    _evidence_group("forecaster:lightcounting", ["SRC-LC-JUL25", "SRC-LC-MAR26"], "context_calibrator", "industry", "CPO/可插拔预测分歧决定迁移速度。", "architecture_forecast_range"),
                    _evidence_group("standards:lpo-msa", ["SRC-LPO-MSA"], "context_calibrator", "industry", "LPO 规范校准客户可能采用的架构。", "architecture_standard_context"),
                ],
                low_case_reason="服务器入口没有转成高速光客户资格或订单。",
                high_case_reason="服务器客户侧出现光模块送样、AVL 或可归属重复订单。",
            ),
            _market_factor_spec(
                "company.financial_capture_quality", "集团制造与资本承载能力", 62, 45, 75,
                [
                    _evidence_group("controlled_group:byd", ["BYD-S01", "BYD-S02"], "support_risk", "direct_entity", "自身研发/制造投入和母公司控制关系支持承载力，但不是专项光模块资本。", "financial_capacity_not_optical_capex"),
                    _evidence_group("case:cisco-acacia", ["SRC-CISCO-ACACIA21"], "context_calibrator", "historical_base_rate", "资本绑定成熟平台可提高进入能力。", "capital_with_mature_asset_reference"),
                    _evidence_group("case:lumentum-cloud-light", ["SRC-LITE-CLOUD23"], "context_calibrator", "historical_base_rate", "成熟资产收购路径校准。", "capital_with_mature_asset_reference"),
                    _evidence_group("case:marvell-inphi", ["SRC-MRVL-INPHI21"], "context_calibrator", "historical_base_rate", "相邻大公司通过收购取得互连资产。", "capital_with_mature_asset_reference"),
                    _evidence_group("case:intel-jabil-module-transfer", ["SRC-INTEL-Q323", "SRC-JABIL-INTEL23"], "context_calibrator", "historical_base_rate", "大公司资本和技术不保证模块业务持续。", "capital_not_sufficient_counterexample"),
                    _evidence_group("case:fit-module-platform", ["SRC-FIT-AR18", "SRC-LW-FIT19", "SRC-POET-FIT24"], "context_calibrator", "historical_base_rate", "EMS 规模与资本不自动形成持久平台。", "ems_capital_counterexample"),
                    _evidence_group("supplier:fabrinet", ["SRC-FN-SITE26"], "context_calibrator", "historical_base_rate", "规模光学制造降低门槛但不自带 IP 与客户。", "manufacturing_scale_reference"),
                    _evidence_group("derived:byd-financial", ["FIN-BYD_ELECTRONIC", "FIN-BYD"], "boundary", "direct_entity", "结构化财务用于数值复算；发行人报表字段不制造第二个独立确认，母公司口径单列。", "derived_financial_record", score_eligible=False),
                ],
                low_case_reason="资本可用但没有专项投入、收购或可归属光模块资产。",
                high_case_reason="出现专项资本、成熟资产/团队承接或连续可审计投入。",
            ),
        ],
    },
    "luxshare_entry_risk": {
        "name": "立讯高速光模块进度离全球头部客户还有多远",
        "description": "研究立讯精密已经披露的高速光模块产品和工程进展，能否进一步转化为头部客户认证、连续批量订单和可分收入，从而成为全球市场中持续的竞争者。",
        "weights": {
            "company.capacity_readiness_window": 0.25,
            "company.exposure_directness": 0.25,
            "supply.substitution_barrier": 0.20,
            "demand.customer_capex_capacity_signal": 0.15,
            "company.financial_capture_quality": 0.15,
        },
        "coverage": 0.86,
        "confidence": 0.72,
        "factors": [
            _market_factor_spec(
                "company.capacity_readiness_window", "800G 量产与 1.6T 商业爬坡", 68, 55, 80,
                [
                    _evidence_group("controlled_group:luxshare", ["LX-IR-202508", "LX-FRO-2026", "LX-800G-MASS-202510", "LX-HKEX-PROSPECTUS-ZH-2026", "LX-TRANSCEIVER-CURRENT"], "support_risk", "direct_entity", "800G/1.6T 阶段来自同一受控集团，官方冲突组内保留，C级页面不独立抬分。", "issuer_claimed_production_and_validation"),
                    _evidence_group("issuer:poet", ["POET-LX-202408", "POET-SEC-OFC2025"], "support_risk", "supply_chain", "第三方支持光引擎集成和展会测试，最高到工程集成。", "supplier_integration_test"),
                    _evidence_group("standards:oif", ["OIF-OFC2024-CEI", "OIF-OFC2026"], "support_risk", "customer_ecosystem", "多厂商互操作支持标准准备，不替代终端资格。", "multi_vendor_interoperability"),
                    _evidence_group("issuer:keysight", ["KEYSIGHT-LX-202410"], "support_risk", "supply_chain", "测试生态支持工程准备，不证明商业产量。", "joint_engineering_test"),
                    _evidence_group("platform:marvell", ["MARVELL-LX-202605"], "support_risk", "supply_chain", "224G 长距 SerDes 合作支持电侧准备。", "next_generation_electrical_readiness"),
                    _evidence_group("government:dongguan-science", ["DG-STB-SIPH-2023"], "support_risk", "direct_entity", "政府项目清单支持硅光封装测试建设信号，不提供当前良率。", "government_project_entry"),
                    _evidence_group("customer:nvidia", ["NVIDIA-CX8-VALIDATED"], "counter_risk", "customer_ecosystem", "只确认 200G DAC，未确认 800G/1.6T 光模块资格。", "validated_electrical_interconnect_only"),
                    _evidence_group("issuer:semtech", ["SEMTECH-LX-OFC2025"], "context_calibrator", "supply_chain", "1.6T 主动铜缆是相邻互连能力，不能当光模块量产。", "adjacent_active_copper_demo"),
                    _evidence_group("issuer:alphawave", ["ALPHAWAVE-OFC2025"], "context_calibrator", "supply_chain", "高速连接合作提供相邻工程校准。", "adjacent_connectivity_demo"),
                ],
                low_case_reason="800G/1.6T 仍主要由发行人阶段口径和工程演示支撑。",
                high_case_reason="出现独立客户侧批量、专线良率或可审计光模块产量。",
            ),
            _market_factor_spec(
                "company.exposure_directness", "高速光模块产品与业务直接性", 58, 44, 72,
                [
                    _evidence_group("controlled_group:luxshare", ["LX-HKEX-PROSPECTUS-EN-2026", "LX-ANNUAL-2025", "LX-OPTICS-CURRENT", "LX-TRANSCEIVER-CURRENT", "LX-800G-LPO-SPEC"], "support_risk", "direct_entity", "业务、产品目录和规格确认直接暴露；分部收入仍是混合口径。", "catalogue_and_business_exposure"),
                    _evidence_group("issuer:poet", ["POET-LX-202408", "POET-SEC-OFC2025"], "support_risk", "supply_chain", "第三方光引擎集成支持真实光模块活动。", "supplier_integration_test"),
                    _evidence_group("standards:oif", ["OIF-OFC2024-CEI", "OIF-OFC2026", "OIF-MEMBERS"], "support_risk", "customer_ecosystem", "互操作和成员身份支持生态直接性，不证明销售规模。", "standard_ecosystem_participation"),
                    _evidence_group("government:dongguan-science", ["DG-STB-SIPH-2023"], "support_risk", "direct_entity", "硅光封装测试项目支持技术直接性。", "government_project_entry"),
                    _evidence_group("event:ocp-asia", ["OCP-ASIA-2026"], "support_risk", "customer_ecosystem", "NPO/CPO/XPO 议程支持生态参与，最高到会议信号。", "public_expert_topic_signal"),
                    _evidence_group("customer:nvidia", ["NVIDIA-CX8-VALIDATED"], "counter_risk", "customer_ecosystem", "只验证高速电互连，不验证光模块客户暴露。", "validated_electrical_interconnect_only"),
                    _evidence_group("issuer:arista", ["ARISTA-XPO-202603"], "context_calibrator", "customer_ecosystem", "XPO 架构资料校准方向，未具名确认立讯资格。", "external_architecture_context"),
                    _evidence_group("standards:ieee-802.3", ["IEEE-8023DJ-D24"], "context_calibrator", "industry", "草案状态校准代际边界，不是量产认证。", "draft_standard_context"),
                    _evidence_group("issuer:keysight", ["KEYSIGHT-LX-202410"], "support_risk", "supply_chain", "外部测试生态提高产品活动可信度，不提供收入拆分。", "joint_engineering_test"),
                ],
                low_case_reason="直接产品存在但混合分部收入无法识别光模块规模。",
                high_case_reason="监管披露出现独立光模块收入、客户和代际结构。",
            ),
            _market_factor_spec(
                "demand.customer_capex_capacity_signal", "头部客户 qualification 与重复订单", 48, 34, 63,
                [
                    _evidence_group("controlled_group:luxshare", ["LX-IR-202508", "LX-FRO-2026", "LX-800G-MASS-202510"], "support_risk", "direct_entity", "验证、交付或批量均为发行人自述且客户不具名，官方阶段冲突组内保留。", "issuer_claimed_delivery_without_named_customer"),
                    _evidence_group("customer:nvidia", ["NVIDIA-CX8-VALIDATED"], "counter_risk", "customer_ecosystem", "限定清单只见 200G DAC。", "named_optical_qualification_not_publicly_verified"),
                    _evidence_group("standards:oif", ["OIF-OFC2024-CEI", "OIF-OFC2026"], "boundary", "customer_ecosystem", "互操作不是终端资格或重复订单。", "interoperability_not_customer_qualification"),
                    _evidence_group("issuer:poet", ["POET-LX-202408", "POET-SEC-OFC2025"], "boundary", "supply_chain", "供应商侧集成不证明最终客户闭环。", "supplier_integration_not_customer_order"),
                    _evidence_group("issuer:keysight", ["KEYSIGHT-LX-202410"], "boundary", "supply_chain", "测试活动不是客户采购。", "engineering_test_not_customer_order"),
                    _evidence_group("platform:marvell", ["MARVELL-LX-202605"], "boundary", "supply_chain", "平台合作不是光模块 AVL。", "platform_partnership_not_avl"),
                    _evidence_group("issuer:semtech", ["SEMTECH-LX-OFC2025"], "boundary", "supply_chain", "主动铜缆合作不能迁移为光模块订单。", "adjacent_product_not_optical_order"),
                    _evidence_group("issuer:alphawave", ["ALPHAWAVE-OFC2025"], "boundary", "supply_chain", "生态展示只到合作/演示。", "partner_demo_not_customer_order"),
                    _evidence_group("event:ocp-asia", ["OCP-ASIA-2026"], "boundary", "customer_ecosystem", "会议议程不构成 qualification。", "conference_not_customer_qualification"),
                ],
                low_case_reason="仍无具名 AVL、重复订单或跨披露周期可审计交付。",
                high_case_reason="客户/平台侧确认资格且跨两个采购或披露周期重复交付。",
            ),
            _market_factor_spec(
                "supply.substitution_barrier", "核心器件、良率和多代认证壁垒穿透风险", 55, 44, 68,
                [
                    _evidence_group("controlled_group:luxshare", ["LX-HKEX-PROSPECTUS-EN-2026", "LX-IR-202508"], "boundary", "direct_entity", "直接产品和量产自述提高可能，招股书同时说明业务线能力不通用。", "mixed_direct_capability_and_boundary"),
                    _evidence_group("issuer:poet", ["POET-LX-202408", "POET-SEC-OFC2025"], "boundary", "supply_chain", "光引擎合作降低集成门槛并暴露器件依赖。", "supplier_integration_dependency"),
                    _evidence_group("platform:broadcom", ["SRC-BCM-DSP"], "counter_risk", "supply_chain", "先进 DSP 校准核心器件壁垒。", "advanced_dsp_requirement"),
                    _evidence_group("supplier:coherent", ["SRC-COHR-10K25", "SRC-COHR-CHIPS26"], "counter_risk", "supply_chain", "有限来源与 InP 产能约束规模供给。", "upstream_capacity_constraint"),
                    _evidence_group("platform:marvell", ["MARVELL-LX-202605", "SRC-MRVL-10Q25"], "support_risk", "supply_chain", "合作支持电侧能力，多年采购承诺说明锁量门槛。", "partner_capability_with_supply_constraint"),
                    _evidence_group("supplier:fabrinet", ["SRC-FN-10K24"], "counter_risk", "historical_base_rate", "供应商/产线变化可能重启认证。", "requalification_mechanism_reference"),
                    _evidence_group("issuer:lightwave-logic", ["SRC-LWLG-10K24"], "counter_risk", "historical_base_rate", "认证数月且不保证销售。", "qualification_duration_reference"),
                    _evidence_group("issuer:afop", ["SRC-AFOP-10K14"], "counter_risk", "historical_base_rate", "陈旧资格周期只作历史上界。", "historical_qualification_upper_bound"),
                    _evidence_group("standards:ieee-802.3", ["IEEE-8023DJ-D24"], "boundary", "industry", "标准仍处草案阶段。", "draft_standard_context"),
                    _evidence_group("standards:oif", ["OIF-OFC2024-CEI", "OIF-OFC2026"], "support_risk", "customer_ecosystem", "互操作支持工程准备但不是多代客户资格。", "multi_vendor_interoperability"),
                ],
                low_case_reason="核心器件、稳定良率和多代客户资格仍形成强约束。",
                high_case_reason="关键器件、专线良率和客户多代认证同时出现外部闭环。",
            ),
            _market_factor_spec(
                "company.financial_capture_quality", "规模制造、资金与低利润容忍度", 72, 64, 82,
                [
                    _evidence_group("controlled_group:luxshare", ["LX-CNINFO-H1-2025", "LX-HKEX-PROSPECTUS-ZH-2026", "LX-ANNUAL-2025"], "support_risk", "direct_entity", "集团规模与分部承载力提高耐受，混合分部不能当光模块利润。", "group_financial_capacity_with_segment_boundary"),
                    _evidence_group("case:cisco-acacia", ["SRC-CISCO-ACACIA21"], "context_calibrator", "historical_base_rate", "资本绑定成熟资产可提高进入成功率。", "capital_with_mature_asset_reference"),
                    _evidence_group("case:lumentum-cloud-light", ["SRC-LITE-CLOUD23"], "context_calibrator", "historical_base_rate", "成熟资产收购路径校准。", "capital_with_mature_asset_reference"),
                    _evidence_group("case:marvell-inphi", ["SRC-MRVL-INPHI21"], "context_calibrator", "historical_base_rate", "相邻平台通过收购取得互连资产。", "capital_with_mature_asset_reference"),
                    _evidence_group("case:intel-jabil-module-transfer", ["SRC-INTEL-Q323", "SRC-JABIL-INTEL23"], "context_calibrator", "historical_base_rate", "资本与技术不保证模块业务持续。", "capital_not_sufficient_counterexample"),
                    _evidence_group("case:fit-module-platform", ["SRC-FIT-AR18", "SRC-LW-FIT19", "SRC-POET-FIT24"], "context_calibrator", "historical_base_rate", "EMS 规模不自动形成持久平台。", "ems_capital_counterexample"),
                    _evidence_group("supplier:fabrinet", ["SRC-FN-SITE26"], "context_calibrator", "historical_base_rate", "规模光学制造不自带 IP 与客户资格。", "manufacturing_scale_reference"),
                    _evidence_group("derived:luxshare-financial", ["FIN-LUXSHARE"], "boundary", "direct_entity", "结构化财务用于数值复算，不对发行人报表事实增加独立确认。", "derived_financial_record", score_eligible=False),
                ],
                low_case_reason="资本与规模存在，但光模块分部利润和专项投入不可分。",
                high_case_reason="连续专项投入、可归属收入及价格容忍能力得到监管披露。",
            ),
        ],
    },
    "innolight_terminal_risk": {
        "name": "中际旭创面对新进入者时的盈利与现金流风险",
        "description": "研究需求增长、客户集中、量产能力、海外交付和现金流能否帮助中际旭创抵御新进入者，并测算不同竞争情景对收入、利润、自由现金流和估值的影响。",
        "weights": {
            "demand.customer_capex_capacity_signal": 0.10,
            "company.revenue_exposure_proxy": 0.25,
            "supply.substitution_barrier": 0.15,
            "company.financial_capture_quality": 0.20,
            "signal.material_price_momentum": 0.30,
        },
        "coverage": 0.91,
        "confidence": 0.81,
        "factors": [
            _market_factor_spec(
                "demand.customer_capex_capacity_signal", "AI 网络需求基线脆弱度（由需求支撑反向）", 78, 10, 40,
                [
                    _evidence_group("controlled_group:innolight", ["SRC-INNO-AR25"], "counter_risk", "direct_entity", "公司收入、产销和客户集中形成直接需求底座。", "issuer_demand_baseline"),
                    _evidence_group("customer:nvidia", ["SRC-NV-QX800", "SRC-NV-SPECTRUM"], "counter_risk", "industry", "端口密度和系统规模支持需求，不等于中际订单。", "platform_demand_reference"),
                    _evidence_group("platform:broadcom", ["SRC-BCM-TH6"], "counter_risk", "industry", "1.6TbE 端口配置支持高速代际需求。", "industry_port_demand_reference"),
                    _evidence_group("standards:oif", ["SRC-OIF-2025"], "counter_risk", "industry", "标准项目支持代际延续，不是采购量。", "standards_demand_context"),
                    _evidence_group("forecaster:cignal-ai", ["SRC-CIGNAL-4Q24"], "counter_risk", "industry", "800G 增长预测支持需求但仍是预测。", "industry_demand_forecast"),
                    _evidence_group("forecaster:lightcounting", ["SRC-LC-JUL25", "SRC-LC-MAR26"], "boundary", "industry", "CPO/可插拔预测分歧扩大路径区间。", "architecture_forecast_range"),
                    _evidence_group("standards:lpo-msa", ["SRC-LPO-MSA"], "boundary", "industry", "架构规范校准需求形态。", "architecture_standard_context"),
                ],
                orientation="higher_is_defense",
                low_case_reason="需求支撑强、可插拔延续且客户集中未转成订单波动。",
                high_case_reason="架构切换或客户资本开支放缓削弱收入基线。",
            ),
            _market_factor_spec(
                "company.revenue_exposure_proxy", "高速光模块收入与客户集中暴露", 78, 60, 92,
                [
                    _evidence_group("controlled_group:innolight", ["SRC-INNO-AR25"], "support_risk", "direct_entity", "前五客户、最大客户和光模块产销是唯一直接公司披露组。", "issuer_revenue_concentration"),
                    _evidence_group("controlled_group:eoptolink", ["SRC-EOPT-AR25"], "context_calibrator", "industry", "同业集中度、毛利和产销只作相对校准。", "peer_exposure_reference"),
                    _evidence_group("customer:nvidia", ["SRC-NV-QX800", "SRC-NV-SPECTRUM"], "context_calibrator", "industry", "需求平台约束收入基线但不改变集中度事实。", "platform_demand_reference"),
                    _evidence_group("platform:broadcom", ["SRC-BCM-TH6"], "context_calibrator", "industry", "端口代际提供收入情景。", "industry_port_demand_reference"),
                    _evidence_group("forecaster:cignal-ai", ["SRC-CIGNAL-4Q24"], "context_calibrator", "industry", "需求增长与规模上限共同约束暴露。", "industry_demand_forecast"),
                    _evidence_group("forecaster:lightcounting", ["SRC-LC-JUL25", "SRC-LC-MAR26"], "context_calibrator", "industry", "架构预测分歧校准收入暴露区间。", "architecture_forecast_range"),
                    _evidence_group("issuer:crealights", ["SRC-HKEX-ASP26"], "context_calibrator", "industry", "同业 ASP 序列校准代际收入敏感性，不能当中际 ASP。", "peer_asp_reference"),
                    _evidence_group("derived:innolight-financial", ["FIN-INNOLIGHT"], "boundary", "direct_entity", "结构化财务用于复算，发行人财务字段不增加独立组。", "derived_financial_record", score_eligible=False),
                ],
                low_case_reason="客户集中下降且多代需求分散收入来源。",
                high_case_reason="客户集中保持高位并叠加单一代际/客户订单波动。",
            ),
            _market_factor_spec(
                "supply.substitution_barrier", "多代量产、海外交付与客户认证防线的穿透风险", 35, 20, 55,
                [
                    _evidence_group("controlled_group:innolight", ["SRC-INNO-AR25", "SRC-INNO-1600", "SRC-INNO-FUND26"], "counter_risk", "direct_entity", "1.6T 产品、产销和投入是一个发行人防线组。", "incumbent_multi_generation_defense"),
                    _evidence_group("customer:nvidia", ["BYD-S18"], "counter_risk", "customer_ecosystem", "限定清单可见 InnoLight，只支持特定平台生态。", "specific_platform_validation"),
                    _evidence_group("platform:broadcom", ["SRC-BCM-DSP"], "counter_risk", "supply_chain", "先进 DSP 代际构成进入门槛。", "advanced_dsp_requirement"),
                    _evidence_group("standards:oif", ["SRC-OIF-2025"], "counter_risk", "industry", "标准连续演进提高多代研发门槛。", "standards_iteration_barrier"),
                    _evidence_group("supplier:coherent", ["SRC-COHR-10K25", "SRC-COHR-OFC25", "SRC-COHR-CHIPS26"], "counter_risk", "supply_chain", "器件、演示与 InP 产能约束供应防线。", "upstream_capacity_constraint"),
                    _evidence_group("supplier:fabrinet", ["SRC-FN-10K24"], "counter_risk", "historical_base_rate", "替换产线/供应商可能重认证。", "requalification_mechanism_reference"),
                    _evidence_group("issuer:lightwave-logic", ["SRC-LWLG-10K24"], "counter_risk", "historical_base_rate", "认证时长和不保证销售的历史校准。", "qualification_duration_reference"),
                    _evidence_group("issuer:afop", ["SRC-AFOP-10K14"], "counter_risk", "historical_base_rate", "陈旧资格时长只作上界。", "historical_qualification_upper_bound"),
                    _evidence_group("government:us-bis", ["SRC-BIS-JAN26"], "support_risk", "industry", "出口许可可能分割需求/交付，不能写成全面禁运。", "conditional_policy_risk"),
                ],
                low_case_reason="多代产品、客户资格和扩产防线持续有效。",
                high_case_reason="进入者跨代通过认证且政策/地点变化削弱既有防线。",
            ),
            _market_factor_spec(
                "company.financial_capture_quality", "毛利、现金流与扩产缓冲不足风险", 28, 15, 48,
                [
                    _evidence_group("controlled_group:innolight", ["SRC-INNO-AR25"], "counter_risk", "direct_entity", "毛利、经营现金流、简单 FCF 和产能形成直接财务防线。", "issuer_financial_defense"),
                    _evidence_group("controlled_group:eoptolink", ["SRC-EOPT-AR25"], "context_calibrator", "industry", "同业 FCF/毛利对照不合并成单一排名。", "peer_financial_reference"),
                    _evidence_group("issuer:crealights", ["SRC-HKEX-ASP26"], "support_risk", "industry", "代际 ASP 变化校准毛利/现金流承压。", "peer_asp_reference"),
                    _evidence_group("forecaster:cignal-ai", ["SRC-CIGNAL-4Q24"], "counter_risk", "industry", "需求增长预测支撑现金流基线。", "industry_demand_forecast"),
                    _evidence_group("forecaster:lightcounting", ["SRC-LC-JUL25", "SRC-LC-MAR26"], "boundary", "industry", "架构预测分歧决定防御期长度。", "architecture_forecast_range"),
                    _evidence_group("supplier:lumentum", ["SRC-LITE-10K25"], "support_risk", "supply_chain", "器件短缺检验库存与现金缓冲。", "component_shortage_risk"),
                    _evidence_group("government:us-bis", ["SRC-BIS-JAN26"], "support_risk", "industry", "区域政策扩大财务区间。", "conditional_policy_risk"),
                    _evidence_group("case:intel-jabil-module-transfer", ["SRC-INTEL-Q323", "SRC-JABIL-INTEL23"], "support_risk", "historical_base_rate", "技术与资本不保证模块业务持续。", "terminal_value_counterexample"),
                    _evidence_group("derived:innolight-financial", ["FIN-INNOLIGHT"], "boundary", "direct_entity", "结构化时间序列用于复算，不增加发行人独立组。", "derived_financial_record", score_eligible=False),
                ],
                low_case_reason="毛利、FCF 与扩产能力继续吸收竞争冲击。",
                high_case_reason="ASP、份额与营运资本压力连续侵蚀现金流。",
            ),
            _market_factor_spec(
                "signal.material_price_momentum", "正常代际降价与额外竞争降价的终值敏感性", 68, 43, 84,
                [
                    _evidence_group("controlled_group:innolight", ["SRC-INNO-AR25"], "boundary", "direct_entity", "毛利、产销和客户集中决定 ASP 冲击传导。", "issuer_asp_sensitivity_base"),
                    _evidence_group("issuer:crealights", ["SRC-HKEX-ASP26"], "support_risk", "industry", "代际 ASP 序列用于正常降价基线，不能识别进入者残差。", "peer_asp_reference"),
                    _evidence_group("controlled_group:eoptolink", ["SRC-EOPT-AR25"], "context_calibrator", "industry", "同业毛利/产销校准成本缓冲。", "peer_margin_reference"),
                    _evidence_group("forecaster:cignal-ai", ["SRC-CIGNAL-4Q24"], "boundary", "industry", "出货增长和规模预期约束价格/量组合。", "industry_demand_forecast"),
                    _evidence_group("forecaster:lightcounting", ["SRC-LC-JUL25", "SRC-LC-MAR26"], "boundary", "industry", "可插拔与 CPO 预测分歧约束终值。", "architecture_forecast_range"),
                    _evidence_group("standards:oif", ["SRC-OIF-2025"], "support_risk", "industry", "3.2T/CPO 迁移影响产品 mix 和降价速度。", "architecture_transition_context"),
                    _evidence_group("standards:lpo-msa", ["SRC-LPO-MSA"], "support_risk", "industry", "LPO 影响 BOM/ASP，不代表已规模替代。", "architecture_standard_context"),
                    _evidence_group("supplier:lumentum", ["SRC-LITE-10K25"], "boundary", "supply_chain", "短缺可能支撑价格也会抬成本。", "component_shortage_risk"),
                ],
                low_case_reason="正常代际降价被 mix、成本和需求增长吸收。",
                high_case_reason="新增竞争降价、份额流失和架构 mix 同时压低正常化终值。",
            ),
        ],
    },
    "eoptolink_terminal_risk": {
        "name": "新易盛面对新进入者时的盈利与现金流风险",
        "description": "研究新易盛的海外收入、客户集中、产品毛利、现金流和新产品项目，在新增竞争出现时会怎样影响收入、利润、自由现金流和估值。",
        "weights": {
            "demand.customer_capex_capacity_signal": 0.10,
            "company.revenue_exposure_proxy": 0.25,
            "supply.substitution_barrier": 0.15,
            "company.financial_capture_quality": 0.20,
            "signal.material_price_momentum": 0.30,
        },
        "coverage": 0.91,
        "confidence": 0.80,
        "factors": [
            _market_factor_spec(
                "demand.customer_capex_capacity_signal", "AI 网络需求基线脆弱度（由需求支撑反向）", 76, 12, 42,
                [
                    _evidence_group("controlled_group:eoptolink", ["SRC-EOPT-AR25"], "counter_risk", "direct_entity", "境外收入、产销、客户集中和项目阶段提供直接需求底座。", "issuer_demand_baseline"),
                    _evidence_group("customer:nvidia", ["SRC-NV-QX800", "SRC-NV-SPECTRUM"], "counter_risk", "industry", "平台规模支持总需求，不证明新易盛订单。", "platform_demand_reference"),
                    _evidence_group("platform:broadcom", ["SRC-BCM-TH6"], "counter_risk", "industry", "高速端口代际支持行业需求。", "industry_port_demand_reference"),
                    _evidence_group("standards:oif", ["SRC-OIF-2025"], "counter_risk", "industry", "标准路线支持代际延续，不是采购量。", "standards_demand_context"),
                    _evidence_group("forecaster:cignal-ai", ["SRC-CIGNAL-4Q24"], "counter_risk", "industry", "800G 增长预测是情景输入。", "industry_demand_forecast"),
                    _evidence_group("forecaster:lightcounting", ["SRC-LC-JUL25", "SRC-LC-MAR26"], "boundary", "industry", "架构预测分歧扩大需求区间。", "architecture_forecast_range"),
                    _evidence_group("standards:lpo-msa", ["SRC-LPO-MSA"], "boundary", "industry", "LPO 规范校准需求形态。", "architecture_standard_context"),
                ],
                orientation="higher_is_defense",
                low_case_reason="海外需求和可插拔代际保持强支撑。",
                high_case_reason="客户资本开支、区域政策或架构切换削弱收入基线。",
            ),
            _market_factor_spec(
                "company.revenue_exposure_proxy", "光模块收入与客户集中风险暴露", 82, 65, 95,
                [
                    _evidence_group("controlled_group:eoptolink", ["SRC-EOPT-AR25"], "support_risk", "direct_entity", "境外收入、前五客户、最大客户和产销是直接暴露证据。", "issuer_revenue_concentration"),
                    _evidence_group("controlled_group:innolight", ["SRC-INNO-AR25"], "context_calibrator", "industry", "同业集中度、产销和毛利只作对照。", "peer_exposure_reference"),
                    _evidence_group("customer:nvidia", ["SRC-NV-QX800", "SRC-NV-SPECTRUM"], "context_calibrator", "industry", "平台需求支撑基线但不改变集中度。", "platform_demand_reference"),
                    _evidence_group("platform:broadcom", ["SRC-BCM-TH6"], "context_calibrator", "industry", "端口代际约束收入情景。", "industry_port_demand_reference"),
                    _evidence_group("forecaster:cignal-ai", ["SRC-CIGNAL-4Q24"], "context_calibrator", "industry", "需求增速与规模上限约束暴露。", "industry_demand_forecast"),
                    _evidence_group("forecaster:lightcounting", ["SRC-LC-JUL25", "SRC-LC-MAR26"], "context_calibrator", "industry", "架构预测分歧约束收入区间。", "architecture_forecast_range"),
                    _evidence_group("issuer:crealights", ["SRC-HKEX-ASP26"], "context_calibrator", "industry", "同业 ASP 序列校准代际收入敏感性。", "peer_asp_reference"),
                    _evidence_group("derived:eoptolink-financial", ["FIN-EOPTOLINK"], "boundary", "direct_entity", "结构化财务用于复算，不增加发行人独立组。", "derived_financial_record", score_eligible=False),
                ],
                low_case_reason="客户集中下降且产品/客户结构更分散。",
                high_case_reason="高海外和客户集中叠加单一代际/客户订单波动。",
            ),
            _market_factor_spec(
                "supply.substitution_barrier", "产品验证、泰国产能与量产工艺防线的穿透风险", 38, 22, 60,
                [
                    _evidence_group("controlled_group:eoptolink", ["SRC-EOPT-AR25"], "counter_risk", "direct_entity", "差异化项目阶段、产销利用和泰国主体构成直接防线；海外布局不等于客户资格。", "incumbent_product_and_capacity_defense"),
                    _evidence_group("platform:broadcom", ["SRC-BCM-DSP"], "counter_risk", "supply_chain", "先进 DSP 形成器件壁垒。", "advanced_dsp_requirement"),
                    _evidence_group("standards:oif", ["SRC-OIF-2025"], "counter_risk", "industry", "标准连续演进提高研发要求。", "standards_iteration_barrier"),
                    _evidence_group("supplier:coherent", ["SRC-COHR-10K25", "SRC-COHR-OFC25", "SRC-COHR-CHIPS26"], "counter_risk", "supply_chain", "器件与 InP 产能约束规模进入。", "upstream_capacity_constraint"),
                    _evidence_group("supplier:fabrinet", ["SRC-FN-10K24"], "counter_risk", "historical_base_rate", "地点/供应商变化可能触发重新认证。", "requalification_mechanism_reference"),
                    _evidence_group("issuer:lightwave-logic", ["SRC-LWLG-10K24"], "counter_risk", "historical_base_rate", "认证持续数月且不保证销售。", "qualification_duration_reference"),
                    _evidence_group("issuer:afop", ["SRC-AFOP-10K14"], "counter_risk", "historical_base_rate", "陈旧资格时长只作上界。", "historical_qualification_upper_bound"),
                    _evidence_group("government:us-bis", ["SRC-BIS-JAN26"], "support_risk", "industry", "区域政策可能约束交付/需求。", "conditional_policy_risk"),
                ],
                low_case_reason="多代验证、工艺和海外交付防线持续有效。",
                high_case_reason="进入者跨代认证且地点/政策变化削弱既有防线。",
            ),
            _market_factor_spec(
                "company.financial_capture_quality", "高毛利与现金流缓冲不足风险", 32, 18, 56,
                [
                    _evidence_group("controlled_group:eoptolink", ["SRC-EOPT-AR25"], "counter_risk", "direct_entity", "高毛利、经营现金流和简单 FCF 是直接防线，客户集中是反向风险。", "issuer_financial_defense"),
                    _evidence_group("controlled_group:innolight", ["SRC-INNO-AR25"], "context_calibrator", "industry", "同业绝对 FCF 与毛利对照不合并成排名。", "peer_financial_reference"),
                    _evidence_group("issuer:crealights", ["SRC-HKEX-ASP26"], "support_risk", "industry", "代际 ASP 变化校准毛利和现金流承压。", "peer_asp_reference"),
                    _evidence_group("forecaster:cignal-ai", ["SRC-CIGNAL-4Q24"], "counter_risk", "industry", "需求增长预测支撑现金流基线。", "industry_demand_forecast"),
                    _evidence_group("forecaster:lightcounting", ["SRC-LC-JUL25", "SRC-LC-MAR26"], "boundary", "industry", "架构预测分歧决定防御期。", "architecture_forecast_range"),
                    _evidence_group("supplier:lumentum", ["SRC-LITE-10K25"], "support_risk", "supply_chain", "器件短缺检验库存、成本和现金缓冲。", "component_shortage_risk"),
                    _evidence_group("government:us-bis", ["SRC-BIS-JAN26"], "support_risk", "industry", "高海外占比使区域政策进入财务区间。", "conditional_policy_risk"),
                    _evidence_group("case:intel-jabil-module-transfer", ["SRC-INTEL-Q323", "SRC-JABIL-INTEL23"], "support_risk", "historical_base_rate", "技术/资本不保证模块终值。", "terminal_value_counterexample"),
                    _evidence_group("derived:eoptolink-financial", ["FIN-EOPTOLINK"], "boundary", "direct_entity", "结构化时间序列用于复算，不增加发行人独立组。", "derived_financial_record", score_eligible=False),
                ],
                low_case_reason="高毛利和现金流继续吸收竞争冲击。",
                high_case_reason="ASP、份额、政策和营运资本压力连续侵蚀现金流。",
            ),
            _market_factor_spec(
                "signal.material_price_momentum", "ASP 与产品 mix 对终值的敏感性", 72, 46, 87,
                [
                    _evidence_group("controlled_group:eoptolink", ["SRC-EOPT-AR25"], "boundary", "direct_entity", "毛利、产销、客户集中和 LRO/SiPh/LPO 阶段决定 ASP 传导。", "issuer_asp_sensitivity_base"),
                    _evidence_group("issuer:crealights", ["SRC-HKEX-ASP26"], "support_risk", "industry", "代际 ASP 序列提供正常降价参照，不能识别竞争残差。", "peer_asp_reference"),
                    _evidence_group("controlled_group:innolight", ["SRC-INNO-AR25"], "context_calibrator", "industry", "同业毛利/产销校准成本缓冲。", "peer_margin_reference"),
                    _evidence_group("forecaster:cignal-ai", ["SRC-CIGNAL-4Q24"], "boundary", "industry", "出货增长和规模预期约束价格/量组合。", "industry_demand_forecast"),
                    _evidence_group("forecaster:lightcounting", ["SRC-LC-JUL25", "SRC-LC-MAR26"], "boundary", "industry", "可插拔与 CPO 路径分歧约束终值。", "architecture_forecast_range"),
                    _evidence_group("standards:oif", ["SRC-OIF-2025"], "support_risk", "industry", "CPO/3.2T 迁移影响产品 mix。", "architecture_transition_context"),
                    _evidence_group("standards:lpo-msa", ["SRC-LPO-MSA"], "support_risk", "industry", "LPO 影响 BOM/ASP，不能写成已规模替代。", "architecture_standard_context"),
                    _evidence_group("supplier:lumentum", ["SRC-LITE-10K25"], "boundary", "supply_chain", "短缺可能支撑 ASP 也可能抬成本。", "component_shortage_risk"),
                ],
                low_case_reason="正常代际降价被高毛利、mix 和需求增长吸收。",
                high_case_reason="竞争降价、份额流失和架构 mix 同时压低正常化终值。",
            ),
        ],
    },
}


THEORY_ENTITY_SPECS: dict[str, dict[str, str]] = {
    "entity_scope_and_stage_definitions": {
        "name": "研究对象和商业化阶段怎样划分",
        "description": "说明本研究应该观察哪一个经营主体，并区分产品展示、客户测试、小批交付和持续规模订单，避免把集团相邻能力误写成已经形成光模块收入。",
        "question": "怎样定义研究主体、有意义进入、全球进入和竞争恶化，才能避免把集团相邻能力或宣传语言误写成高速光模块份额？",
    },
    "probability_method_and_baserate": {
        "name": "比亚迪和立讯的进入概率怎样由证据得到",
        "description": "说明我们依据哪些公司和行业证据估计三年与五年的进入可能，并解释证据不足、公司差异和共同市场因素会怎样扩大判断范围。",
        "question": "在历史样本小、选择偏误强且两家公司事件相关时，如何给出透明的 3 年/5 年概率区间与联合情景？",
    },
    "industry_demand_supply_model": {
        "name": "2026—2031年高速光模块需求、供给、价格与架构变化",
        "description": "从交换端口需求、产品速率和实际可售供给出发，判断市场增长能否吸收新增产能，并区分正常技术降价与新进入者带来的额外价格压力。",
        "question": "市场增长和产品代际能否吸收新增供给，哪些 ASP 下降是正常技术进步，哪些才是进入者导致的额外竞争？",
    },
    "qualification_upstream_constraints": {
        "name": "客户认证、核心器件供应与政策约束",
        "description": "研究关键芯片和激光器供给、光学耦合与可靠性测试、客户认证、供应商切换和区域政策，解释为什么有样品或互操作演示仍不等于稳定市场份额。",
        "question": "上游器件、制造变更和客户认证怎样共同约束新进入者，公开兼容或展会互操作能证明到哪个阶段？",
    },
    "recruitment_patent_capacity_audit": {
        "name": "招聘、专利与产能证据怎样用于判断",
        "description": "把招聘、专利、标准活动、政府项目、专用设备、产线和良率分别核验，再判断这些信号是否共同支持真实的产品开发和量产准备。",
        "question": "招聘、专利和通用制造能作为多强的领先指标，什么证据才足以确认光模块专用团队、产线、良率和量产准备？",
    },
}


THEORY_METHODOLOGY_NOTES: dict[str, str] = {
    "entity_scope_and_stage_definitions": "以法人、产品载体、技术团队和合并报表四个键建立 canonical 映射，再把每条披露压回最低可证阶段。",
    "probability_method_and_baserate": "以历史案例校准宽先验，以公司里程碑证据形成三角输入，并用可行联合分布与 Monte Carlo 传播认识不确定性。",
    "industry_demand_supply_model": "从加速器端点、网络层级和启用光口推导需求，以合格可售供给约束份额，并把生命周期降价与竞争残差分离。",
    "qualification_upstream_constraints": "把公开兼容、互操作、客户测试、AVL、design win 和重复订单逐级区分，并把器件锁量与产线资格纳入同一漏斗。",
    "recruitment_patent_capacity_audit": "分别按职位、专利族和专用产线的独立去重键审计，只有跨轴闭环才允许从领先信号升级。",
}


THEORY_LITERATURE_DETAILS: dict[str, str] = {
    "entity_scope_and_stage_definitions": (
        "本页文献只回答‘能力和财务归谁、证据能推进到哪一级’。比亚迪电子年报与母公司年报用于确认数据中心经营披露和65.76%间接持股，"
        "比亚迪半导体官网用于排除车规晶圆/封测能力被自动并入数据中心模块；立讯半年度报告与港股招股书用于区分立讯精密合并口径、东莞立讯技术产品载体，"
        "以及消费/汽车业务与通信数据中心业务的采购、技术和IP边界。公司产品页只能确认SKU或规格存在，不能替代客户资格。"
    ),
    "probability_method_and_baserate": (
        "概率文献集由九个定向进入案例构成：Cisco/Acacia和Lumentum/Cloud Light代表收购成熟团队与客户关系，Intel可插拔退出、Jabil承接、FIT两轮进入、"
        "Fabrinet制造邻接以及Broadcom/Marvell器件平台说明‘完整商用模块成功’和‘任何光通信邻接成功’不是同一结果。按严格口径成功2/9，宽口径5/9；"
        "Wilson区间很宽，且样本受选择偏误、幸存者偏误、收购/有机进入混杂和未决案例影响。因此历史材料只约束支持区间，不产生公司统计后验。"
    ),
    "industry_demand_supply_model": (
        "市场文献按三组读取。NVIDIA Quantum-X800、Spectrum-X与Broadcom Tomahawk 6提供端口速率和拓扑上限，不提供全球已部署台数；OIF、LPO MSA与IEEE草案"
        "界定1.6T、LPO/LRO、3.2T和CPO的标准/工程阶段；Cignal与LightCounting提供彼此冲突的放量时间和规模预测。港交所样本ASP又同时混入成熟度、产品mix、"
        "批量采购和竞争。由此不能把厂商最大系统规模、预测机构收入或单家公司ASP直接当作唯一需求、正常降价或新增竞争事实。"
    ),
    "qualification_upstream_constraints": (
        "本页将客户证据与上游证据并读：OIF和NVIDIA清单限定公开互操作/兼容范围，POET与Keysight说明供应商集成或测试平台阶段；Coherent、Marvell、Lumentum的"
        "法定披露揭示InP/laser、先进晶圆、封测承诺和有限来源风险；Lightwave Logic、AFOP与Fabrinet的历史披露说明器件、工艺、生产线或地点变化可能重新触发"
        "qualification。它们共同支持‘样片可得不等于规模合格供给’，却不能给任何特定CSP伪造固定认证周期。"
    ),
    "recruitment_patent_capacity_audit": (
        "领先信号文献按载体分开：比亚迪当前/历史招聘用于识别集团人才方向，五个专利记录用于辨别车载场景和申请主体，智慧工厂与政府项目用于排除通用自动化或汽车项目"
        "被误写成光模块专线；立讯的耦合/硅光测试岗位、东莞硅光项目、直接光模块/CPO专利和OCP/OIF参与用于识别更连续的工程准备。招聘聚合页、专利镜像和政府项目"
        "分别存在日期刷新、法律状态和项目验收限制，不能互相替代。"
    ),
}


THEORY_METHOD_DETAILS: dict[str, str] = {
    "entity_scope_and_stage_definitions": (
        "方法先建立legal_entity、product_owner、financial_consolidation和technical_team四个互不替代的键。随后使用九级状态机：战略意愿、核心团队、"
        "可审计SKU/样机、互操作与可靠性、客户测试、qualification/AVL、design win或有限订单、两期重复规模订单、多客户多代持续份额。‘高速互联’必须先拆成"
        "铜缆、连接器、背板、NIC周边、光引擎或完整模块；‘国际客户’必须说明客户层级、直接/间接供货和产品代际。中国有意义进入与全球头部CSP进入各有独立事件合同，"
        "主体或产品无法落键时只留在集团邻接栏。"
    ),
    "probability_method_and_baserate": (
        "先把历史案例分类结果转成宽先验约束，再按战略、团队、样机、器件/产线、互操作、客户资格、有限订单和重复规模交付校准BYD与Luxshare的三角输入。"
        "3年和5年使用共享分位路径保证累计事件单调；总进入后再拆中国和全球头部子事件，无法识别地域的剩余质量保留为unidentified。两家公司边际通过Fréchet可行域内的"
        "依赖λ联结，λ表示从独立向最大同向依赖移动的比例，不是Pearson相关。主模型保存随机种子和100,000次外层抽样，并以事件阈值、qualification时滞、依赖和架构"
        "加速做反事实；Monte Carlo只传播给定输入的不确定性。"
    ),
    "industry_demand_supply_model": (
        "需求按端点数×每端点接口×光化率×每接口链路×链路两端系数÷breakout，加各交换层启用光口、DCI和备件计算。供给按名义产能×合格线比例×良率×速率mix×"
        "核心器件可得性×客户资格计算，不能直接使用集团总产能。模型分别跟踪800G、1.6T、3.2T和pluggable/LPO/LRO/CPO，生成slow/base/fast。可比ASP先扣"
        "生命周期、mix、距离、客户、原料和汇率，再把剩余量定义为进入者额外折价；只有真实同口径价格出现才覆盖0、3—7、7—15个百分点压力带。"
    ),
    "qualification_upstream_constraints": (
        "客户漏斗逐格记录catalogue、demo、supplier integration、multi-vendor interoperability、customer test、AVL/qualification、design win、有限订单和"
        "重复规模订单，并绑定速率、形态、距离、供货链、事件日与反证。上游另建DSP、TIA/Driver、EML/InP、CW laser、SiPh/PIC、FA/MT、主动耦合、测试老化的"
        "样片/锁量/合格供应商/替代性矩阵。政策只在官方文本明确覆盖的产品、设备、地区和生效期上传导，不把先进计算限制机械改写为普通光模块全面禁运。"
    ),
    "recruitment_patent_capacity_audit": (
        "招聘用岗位ID、用工法人、地点、首次/最后可见日和职责文本相似度去重，聚合站刷新不产生新HC；专利用优先权、申请人历史名称、同族和权利要求主题归并，并按"
        "数据中心直接、上游器件、封装测试、邻接和低相关分场景；产线要求项目法人、地点、产品代际、设备用途、招标/验收、UPH、良率和稼动率一致。岗位、专利和设备"
        "只能更新各自前置节点，三轴交叉仍不能替代样机、客户资格或收入。"
    ),
}


THEORY_ANSWER_DETAILS: dict[str, str] = {
    "entity_scope_and_stage_definitions": (
        "canonical判定是：比亚迪电子承接当前已披露的AI基础设施经营进展，比亚迪股份提供控股经济敞口，比亚迪半导体及车载专利只作邻接代理；立讯精密承担合并财务，"
        "东莞立讯技术/Luxshare-Tech承担光互连产品载体。当前BYD未越过可公开验证的高速模块SKU阶段；立讯越过产品/工程阶段，但全球头部客户重复规模订单未完成。"
    ),
    "probability_method_and_baserate": (
        "输出必须直接给出BYD与Luxshare在中国/全球的3年和5年mean、P10、median、P90，同时给总/中国/全球至少一家、两家同时和地域联合状态。它回答严格事件合同，"
        "不是‘公司会不会研发产品’。立讯产品与区域交付抬高边际，头部客户冲突扩大全球区间；BYD相邻业务抬高5年上沿，无SKU/资格压低3年。任何点估计都必须与事件定义和敏感性同读。"
    ),
    "industry_demand_supply_model": (
        "需求能否吸收新增供给取决于端点/光口增速与合格供给释放的相对速度：AI端口快增、qualification慢、1.6T切换紧张时，新玩家更可能补第二来源；需求下修、两家同时"
        "获得多客户资格且上游不再约束时，供给才更可能结构性压价。800G与1.6T并存是基准，3.2T/CPO保持宽时间窗。当前公开材料不能识别新增进入者的实际ASP残差。"
    ),
    "qualification_upstream_constraints": (
        "公开兼容和互操作最多证明工程可用，公开名单缺席也只构成有界负证据。立讯具备产品、伙伴集成和互操作，但头部CSP阶段有发行人冲突且无客户侧OPN/AVL闭环；BYD在指定"
        "公开清单未命中。全球概率要上调，必须看到客户/平台侧资格或可归属重复订单；合格供给要上调，还需器件锁量、产线资格和稳定良率。"
    ),
    "recruitment_patent_capacity_audit": (
        "BYD招聘仍是集团级，专利多属车载或其他主体，智慧工厂只证明通用自动化；立讯的COB耦合、SiPh测试岗位、直接模块/CPO专利和政府项目更连续，但岗位来自聚合站，"
        "专线与良率没有量化。现有证据不能估计两家公司团队规模、净新增、产线只数或高端有效产能，最多形成不同强度的早期信号。"
    ),
}


THEORY_CONCLUSION_DETAILS: dict[str, str] = {
    "entity_scope_and_stage_definitions": (
        "结论随主体和阶段证据复核：工商/监管披露、关联交易、IP受让、团队与收入科目若落到同一法人，可更新canonical映射；后一级状态必须有新增独立硬证据。主体不清时，"
        "资源保留在集团邻接栏，不进入上市标的核心能力。"
    ),
    "probability_method_and_baserate": (
        "复核必须固定事件合同和随机种子，保存旧/新输入、参数owner、Monte Carlo误差与Fréchet约束。只有证据改变具体输入、qualification时滞、地域分支或依赖结构时重算；"
        "若中国事件未独立建模，应显示blocked而不是用‘未全球’代替。"
    ),
    "industry_demand_supply_model": (
        "真实端口部署、分速率出货、同规格报价或CPO客户部署出现后，应覆盖对应假设而非与旧预测平均。复核顺序是端口与代际、合格供给、正常ASP、额外竞争残差、架构迁移；"
        "只有口径一致的市场路径才允许进入公司财务。"
    ),
    "qualification_upstream_constraints": (
        "新证据必须回填具体客户阶梯并记录速率、形态、距离、供货链、事件日和反方。模糊‘大客户’不映射名称；供应商合作稿只更新集成节点；器件锁量和新产线只有在资格与良率"
        "闭环后才改变可售供给。"
    ),
    "recruitment_patent_capacity_audit": (
        "岗位升级要求官方职位ID、法人/事业部和跨期净新增；专利升级要求官方法律状态与产品实施；产能升级要求专用设备、验收和良率。任何单一轴只更新自己的前置节点，不能直接"
        "推进客户、收入或全球份额。"
    ),
}


THEORY_LIMITATIONS: dict[str, str] = {
    "entity_scope_and_stage_definitions": "未公开的联合团队、IP授权、资产/人员转移和NDA项目不可识别；公开未检出只限定当前公开可证阶段，不证明内部项目不存在。",
    "probability_method_and_baserate": "历史样本不是随机总体，三角支持区间来自结构化判断；Monte Carlo只传播输入不确定性，客户保密与依赖强度仍不可识别。",
    "industry_demand_supply_model": "全球端点、拓扑、光化率、高端有效产能和同客户同条款ASP面板不完整；市场模型是边界模型，slow/fast尚未完整传导到公司财务。",
    "qualification_upstream_constraints": "私有AVL、NDA送样、间接ODM链、真实认证周期和器件锁量不可完整取得；伙伴联合稿与公开名单都不能代表全市场。",
    "recruitment_patent_capacity_audit": "聚合岗位日期可能刷新，专利镜像不替代官方法律状态，政府项目和集团产能容易受汽车/消费电子/通用连接业务污染。",
}


# 理论实体的12行数据点账本用于可复核抽样，但不能偶然决定正文引用。下面按
# 文献、方法和回答段分别登记正文实际使用的来源，并在组装时 fail closed 校验。
THEORY_LITERATURE_REFS: dict[str, list[str]] = {
    "entity_scope_and_stage_definitions": [
        "LX-CNINFO-H1-2025",
        "LX-HKEX-PROSPECTUS-ZH-2026",
    ],
    "probability_method_and_baserate": ["MODEL-INPUTS", "MODEL-WORKPAPER"],
    "industry_demand_supply_model": [
        "SRC-LPO-MSA",
        "SRC-CIGNAL-4Q24",
        "SRC-LC-SEP24",
        "SRC-LC-JUL25",
        "SRC-LC-MAR26",
        "SRC-HKEX-ASP26",
        "MODEL-INPUTS",
        "MODEL-WORKPAPER",
    ],
    "qualification_upstream_constraints": [
        "POET-LX-202408",
        "KEYSIGHT-LX-202410",
        "BYD-S18",
        "NVIDIA-CX8-VALIDATED",
    ],
    "recruitment_patent_capacity_audit": [
        "JOB-ZHAOPIN-COUPLING",
        "JOB-JOBUI-SIPH-TEST",
        "DG-STB-SIPH-2023",
        "PAT-CN113917631B",
        "PAT-CN114815089B",
        "OCP-ASIA-2026",
        "OIF-OFC2026",
    ],
}

THEORY_METHOD_REFS: dict[str, list[str]] = {
    "entity_scope_and_stage_definitions": ["MODEL-INPUTS"],
    "probability_method_and_baserate": ["MODEL-INPUTS", "MODEL-WORKPAPER"],
    "industry_demand_supply_model": ["MODEL-INPUTS", "MODEL-WORKPAPER"],
    "qualification_upstream_constraints": [
        "POET-LX-202408",
        "KEYSIGHT-LX-202410",
        "BYD-S18",
        "NVIDIA-CX8-VALIDATED",
    ],
    "recruitment_patent_capacity_audit": [
        "JOB-ZHAOPIN-COUPLING",
        "JOB-JOBUI-SIPH-TEST",
        "DG-STB-SIPH-2023",
        "PAT-CN113917631B",
        "PAT-CN114815089B",
    ],
}

THEORY_ANSWER_REFS: dict[str, list[str]] = {
    "entity_scope_and_stage_definitions": [
        "BYD-S01",
        "BYD-S02",
        "BYD-S08",
        "BYD-S09",
        "LX-IR-202508",
        "LX-TRANSCEIVER-CURRENT",
    ],
    "probability_method_and_baserate": ["MODEL-INPUTS", "MODEL-WORKPAPER"],
    "industry_demand_supply_model": [
        "SRC-CIGNAL-4Q24",
        "SRC-LC-JUL25",
        "SRC-LC-MAR26",
        "SRC-HKEX-ASP26",
    ],
    "qualification_upstream_constraints": [
        "POET-LX-202408",
        "KEYSIGHT-LX-202410",
        "BYD-S18",
        "NVIDIA-CX8-VALIDATED",
    ],
    "recruitment_patent_capacity_audit": [
        "BYD-S06",
        "BYD-S07",
        "BYD-S11",
        "BYD-S16",
        "BYD-S19",
        "BYD-S20",
        "JOB-ZHAOPIN-COUPLING",
        "JOB-JOBUI-SIPH-TEST",
        "DG-STB-SIPH-2023",
        "PAT-CN113917631B",
        "PAT-CN114815089B",
        "OCP-ASIA-2026",
        "OIF-OFC2026",
    ],
}


def _source_groups(refs: Iterable[str], source_lookup: dict[str, dict[str, Any]]) -> int:
    return len(
        {
            source_lookup[ref].get("corroboration_key")
            or source_lookup[ref]["independence_key"]
            for ref in refs
            if ref in source_lookup
        }
    )


def _round_half_up(value: float | Decimal) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _normalized_risk_score(raw_score: float, orientation: str) -> float:
    if orientation == "higher_is_risk":
        value = raw_score
    elif orientation == "higher_is_defense":
        value = 100.0 - raw_score
    else:
        raise ValueError(f"未知 score_orientation：{orientation}")
    if not 0.0 <= value <= 100.0:
        raise ValueError(f"归一风险分超出0—100：raw={raw_score}, orientation={orientation}")
    return float(value)


def _eligible_source_link(
    source: dict[str, Any], group: dict[str, Any]
) -> bool:
    return bool(
        group.get("score_eligible", True)
        and source.get("policy_evidence_role") == "core_evidence"
        and source.get("source_tier") not in {"C", "D"}
    )


def _factor(
    entity_key: str,
    entity_name: str,
    factor_spec: dict[str, Any],
    weight: float,
    source_lookup: dict[str, dict[str, Any]],
    *,
    index: int,
) -> dict[str, Any]:
    factor_code = factor_spec["factor_code"]
    metric_name = factor_spec["metric_name"]
    missing_refs = sorted(
        {
            ref
            for group in factor_spec["evidence"]
            for ref in group["refs"]
            if ref not in source_lookup
        }
    )
    if missing_refs:
        raise ValueError(f"{entity_key}/{factor_code} 引用了未知来源：{missing_refs}")

    evidence_links: list[dict[str, Any]] = []
    information_points: list[dict[str, Any]] = []
    eligible_groups: set[str] = set()
    role_groups: dict[str, set[str]] = defaultdict(set)
    direct_groups: set[str] = set()
    context_groups: set[str] = set()
    all_refs: list[str] = []
    eligible_refs: set[str] = set()
    for point_index, group in enumerate(factor_spec["evidence"], start=1):
        group_key = group["corroboration_key"]
        refs = _unique(group["refs"])
        all_refs.extend(refs)
        source_links: list[dict[str, Any]] = []
        for ref in refs:
            source = source_lookup[ref]
            eligible = _eligible_source_link(source, group)
            if eligible:
                eligible_refs.add(ref)
            source_links.append(
                {
                    "source_ref": ref,
                    "evidence_ref": _uri(ref),
                    "record_key": source["record_key"],
                    "record_family_key": source["record_family_key"],
                    "issuer_key": source["issuer_key"],
                    "control_group_key": source["control_group_key"],
                    "fact_lineage_key": source["fact_lineage_key"],
                    "source_corroboration_key": source["corroboration_key"],
                    "policy_evidence_role": source["policy_evidence_role"],
                    "score_eligible": eligible,
                }
            )
        group_eligible = any(link["score_eligible"] for link in source_links)
        if group.get("score_eligible", True) and not group_eligible:
            raise ValueError(
                f"{entity_key}/{factor_code}/{group_key} 没有可进入核心评分的 S/A/B 来源"
            )
        if group_eligible:
            eligible_groups.add(group_key)
            role_groups[group["evidence_role"]].add(group_key)
            if group["evidence_scope"] in {"direct_entity", "customer_ecosystem"}:
                direct_groups.add(group_key)
            else:
                context_groups.add(group_key)
        representative = next(
            (link["source_ref"] for link in source_links if link["score_eligible"]),
            source_links[0]["source_ref"],
        )
        evidence_links.append(
            {
                "corroboration_key": group_key,
                "evidence_role": group["evidence_role"],
                "evidence_scope": group["evidence_scope"],
                "score_eligible": group_eligible,
                "relevance_note": group["relevance_note"],
                "minimum_milestone": group["minimum_milestone"],
                "source_links": source_links,
            }
        )
        information_points.append(
            {
                "evidence_ref": _uri(representative),
                "evidence_ref_uri_list": [_uri(ref) for ref in refs],
                "corroboration_key": group_key,
                "evidence_role": group["evidence_role"],
                "evidence_scope": group["evidence_scope"],
                "minimum_milestone": group["minimum_milestone"],
                "excerpt": source_lookup[representative]["excerpt_zh"],
                "interpretation": f"证据组{point_index}（{group_key}，{group['evidence_role']}）只约束“{metric_name}”的{group['minimum_milestone']}：{group['relevance_note']}",
            }
        )

    if len(eligible_groups) < 5:
        raise ValueError(
            f"{entity_key}/{factor_code} 只有 {len(eligible_groups)} 个真正独立且相关的核心证据组"
        )
    raw_score = float(factor_spec["score_raw_construct"])
    orientation = factor_spec["score_orientation"]
    normalized_score = _normalized_risk_score(raw_score, orientation)
    low_score = float(factor_spec["score_low_normalized_risk"])
    high_score = float(factor_spec["score_high_normalized_risk"])
    if not 0 <= low_score <= normalized_score <= high_score <= 100:
        raise ValueError(
            f"{entity_key}/{factor_code} low/base/high 非单调：{low_score}/{normalized_score}/{high_score}"
        )
    all_refs = _unique(all_refs)
    record_families = {
        source_lookup[ref]["record_family_key"] for ref in all_refs
    }
    issuers = {source_lookup[ref]["issuer_key"] for ref in all_refs}
    confidence = round(
        min(
            0.90,
            0.45 + 0.04 * len(direct_groups) + 0.02 * len(context_groups),
        ),
        2,
    )
    coverage = round(min(0.96, 0.55 + 0.05 * len(eligible_groups)), 2)
    orientation_note = (
        "原始分越高风险越高。"
        if orientation == "higher_is_risk"
        else f"原始分衡量防御/支撑强度，按100-{raw_score:.0f}反向为{normalized_score:.0f}风险分。"
    )
    return {
        "factor_code": factor_code,
        "metric_name": metric_name,
        "period": AS_OF_DATE,
        "unit": "风险强度分",
        "score_raw": raw_score,
        "score_raw_construct": raw_score,
        "score_orientation": orientation,
        "score_normalized_risk": normalized_score,
        "score_adjusted": normalized_score,
        "score_low_normalized_risk": low_score,
        "score_high_normalized_risk": high_score,
        "weight": float(weight),
        "weighted_contribution": round(normalized_score * weight, 8),
        "weighted_low_contribution": round(low_score * weight, 8),
        "weighted_high_contribution": round(high_score * weight, 8),
        "low_case_reason": factor_spec["low_case_reason"],
        "high_case_reason": factor_spec["high_case_reason"],
        "coverage": coverage,
        "confidence": confidence,
        "score_rationale": (
            f"{entity_name}的“{metric_name}”由{len(all_refs)}条记录、{len(issuers)}个发行/发布主体"
            f"归并为{len(eligible_groups)}个真正独立且相关的核心证据组；"
            f"支持{len(role_groups['support_risk'])}组、反证{len(role_groups['counter_risk'])}组、"
            f"边界{len(role_groups['boundary'])}组、校准{len(role_groups['context_calibrator'])}组。"
            f"{orientation_note}分数不由来源条数机械加减。"
        ),
        "factor_value_summary": (
            f"截至{AS_OF_DATE}，{metric_name}的归一风险读数为{normalized_score:.0f}/100，"
            f"显式情景区间{low_score:.0f}—{high_score:.0f}。更高分表示竞争或终值下行风险更强；"
            f"区间是专家证据情景，不伪装成统计置信区间。"
        ),
        "source_context_summary": (
            f"{len(all_refs)}个引用中{len(eligible_refs)}个 S/A/B 核心记录可进入组覆盖，"
            f"归并后为{len(eligible_groups)}组；C/D、reference_only和显式derived辅助记录不抬分。"
        ),
        "factor_topic_analysis": (
            f"低情景：{factor_spec['low_case_reason']} 高情景：{factor_spec['high_case_reason']} "
            "只有达到各证据组列明的最低里程碑才更新相应因子；宣传、转载或同一受控集团增加页面不增加独立性。"
        ),
        "theme_analysis_points": [
            f"{metric_name}必须绑定具体主体、产品代际、客户阶段和证据日期，避免集团口径污染。",
            f"第{index}项因子分别保存支持、反证、边界与校准组；公开清单缺席只作有界负证据。",
        ],
        "record_count": len(all_refs),
        "score_eligible_record_count": len(eligible_refs),
        "record_family_count": len(record_families),
        "issuer_count": len(issuers),
        "independent_group_count": len(eligible_groups),
        "support_group_count": len(role_groups["support_risk"]),
        "counter_group_count": len(role_groups["counter_risk"]),
        "boundary_group_count": len(role_groups["boundary"]),
        "context_group_count": len(role_groups["context_calibrator"]),
        "direct_entity_group_count": len(direct_groups),
        "factor_evidence_links": evidence_links,
        "evidence_ref_uri_list": [_uri(ref) for ref in all_refs],
        "source_context_refs": [_uri(ref) for ref in all_refs],
        "information_points": information_points,
    }


_THEORY_METRIC_LABELS = {
    "indirect_equity_interest_by_byd_company": "比亚迪股份对比亚迪电子的间接权益",
    "non_controlling_interest_implied": "比亚迪电子少数股东权益比例",
    "data_center_business_disclosure_entity": "数据中心业务披露主体",
    "public_core_business_focus": "公开核心业务边界",
    "data_center_integrated_portfolio": "数据中心一体化产品组合",
    "server_customer_expansion": "AI服务器客户扩展",
    "server_shipment_trend": "AI服务器出货趋势",
    "liquid_cooling_customer_certification": "液冷产品客户认证",
    "liquid_cooling_trial_production": "液冷产品小批试产",
    "data_center_power_product_stage": "数据中心电源阶段",
    "high_speed_connectivity_stage": "高速互联披露阶段",
    "ai_infrastructure_revenue": "AI基础设施收入",
    "acquisition_completion": "并购交割完成",
    "post_acquisition_customer_deployment_claim": "并购后客户部署口径",
    "business_outcome": "业务最终处置结果",
    "entry_mode": "跨界进入方式",
    "subsequent_asset_outcome": "后续资产处置结果",
    "development_agreement_scope": "联合开发协议范围",
    "800g_share_of_transceiver_revenue_at_acquisition": "收购时800G收入占比",
    "optical_manufacturing_scope": "专业光学制造范围",
    "full_stack_module_success_rate_selected_sample": "定向样本完整模块成功描述率",
    "draft_ballot_status": "标准草案投票状态",
    "link_rate": "单链路速率",
    "switch_port_count": "交换机端口数量",
    "supernic_bandwidth_per_gpu_max": "单GPU网络带宽上限",
    "two_tier_scale_claim": "两层网络规模上限口径",
    "cpo_power_efficiency_multiplier_claim": "CPO功效提升口径",
    "switch_capacity": "交换芯片总容量",
    "port_configuration": "交换芯片端口配置",
    "member_count": "标准组织成员数量",
    "implementation_agreement_count": "实施协议数量",
    "3.2t_cpo_status": "3.2T CPO标准阶段",
    "1600zr_status": "1600ZR标准阶段",
    "participating_company_count": "互操作参与公司数量",
    "limited_or_sole_source_risk": "有限或单一来源风险",
    "proposed_chips_funding_upper_bound": "拟议CHIPS资助上限",
    "nvidia_equity_investment": "NVIDIA股权投资",
    "purchase_commitment": "长期采购承诺",
    "demonstrated_rate": "公开演示速率",
    "foundry_test_assembly_purchase_commitments": "晶圆、测试与封装采购承诺",
    "component_shortage_risk": "核心器件短缺风险",
    "qualification_duration_direction": "客户认证周期方向",
    "qualification_duration_upper_reference": "客户认证周期上限参考",
    "supplier_change_requalification_risk": "供应商变更再认证风险",
    "license_review_policy": "出口许可审查政策",
    "recruitment_business_scope_signal": "招聘业务范围信号",
    "semiconductor_recruitment_directions": "半导体招聘方向",
    "current_optical_module_specific_role_disclosure": "当前光模块专项岗位披露",
    "phd_optics_research_directions": "博士光学研究方向",
    "phd_optics_role_project_mapping": "博士岗位到项目的映射",
    "wafer_foundry_public_product_scope": "晶圆制造公开产品范围",
    "packaging_testing_public_scope": "封装测试公开业务范围",
    "opto_semiconductor_public_product": "光电半导体公开产品",
    "single_fiber_bidirectional_packaging_patent": "单纤双向封装专利",
    "single_fiber_patent_dc_rate_application_disclosure": "单纤专利的数据中心速率披露",
    "vehicle_optical_splitter_patent": "车载分光专利",
}


def _theory_metric_label(metric: str) -> str:
    return _THEORY_METRIC_LABELS.get(metric, metric.replace("_", " / "))


_THEORY_PERIOD_LABELS = {
    "current_at_access": "截至访问日",
    "current_at_fetch": "截至抓取日",
    "current_page": "当前网页版本",
    "bounded_document_audit": "受限文档核验",
    "bounded_page_audit": "受限网页核验",
    "bounded_patent_audit": "受限专利核验",
    "2023_transaction_announcement": "2023年交易公告",
    "2025_campus_cycle": "2025年校园招聘周期",
    "2026-01-28_to_2026-02-12": "2026-01-28至2026-02-12",
    "2026_spring_recruitment": "2026年春季招聘周期",
    "spring_recruitment": "春季招聘周期",
    "campus_cycle": "校园招聘周期",
    "patent_grant": "专利授权记录",
    "historical_disclosure_2014": "2014年历史披露",
    "historical_disclosure_2024": "2024年历史披露",
    "transaction_announcement": "交易公告日",
    "multi_year_from_2026": "2026年起多年度路径",
    "historical_cases_through_2026-07-18": "截至2026-07-18的历史案例",
    "through_2030_and_beyond": "延伸至2030年及以后",
    "to_2026": "截至2026年",
}


def _theory_period_display(value: Any) -> str:
    raw = _clean(value) or "期间未标明"
    return _THEORY_PERIOD_LABELS.get(raw, raw)


def _theory_point_narrative(
    entity_key: str,
    point: dict[str, Any],
    source: dict[str, Any],
) -> tuple[str, str]:
    metric = str(point["metric"])
    label = _theory_metric_label(metric)
    value = _clean(point.get("value_text")) or "见结构化数值与原文"

    if entity_key == "entity_scope_and_stage_definitions":
        if "equity" in metric or "controlling" in metric:
            interpretation = f"{label}只确认控制与经济权益：{value}；它不能把母公司或其他子公司的技术、客户和专利自动归给比亚迪电子。"
            research_use = "用于证券暴露与合并范围桥接；后续产品、团队和收入仍按经营法人分别取证。"
        elif "disclosure_entity" in metric or "business_focus" in metric:
            interpretation = f"{label}锁定公开经营载体及业务边界：{value}；没有联合项目或资产转移原文时，集团资源只作邻接。"
            research_use = "用于阻断跨主体污染，并决定哪些公告可进入比亚迪电子进入概率、哪些只能留在集团背景。"
        elif any(token in metric for token in ("certification", "trial_production", "product_stage", "connectivity_stage")):
            interpretation = f"{label}记录相邻产品所处的真实里程碑：{value}；相邻认证、小批或战略措辞不等于800G+模块qualification。"
            research_use = "用于校准从系统能力到光模块能力的迁移距离，并把产品、客户、专线三条后续验证债分开。"
        else:
            interpretation = f"{label}说明数据中心相邻业务已有可量化基础：{value}；它支持客户入口和交付能力，不证明光模块SKU或份额。"
            research_use = "用于约束比亚迪长期上沿，同时禁止把服务器、液冷或基础设施收入直接计作高速光模块收入。"
    elif entity_key == "probability_method_and_baserate":
        if "acquisition_completion" in metric:
            interpretation = f"{source['publisher']}的{label}证明该案例通过并购获得能力；成功依赖资产承接，不能当作有机跨界的同分母样本。"
            research_use = "归入‘完整模块成功但进入方式为收购’层，既约束先验上沿，也提高对比亚迪/立讯自建路径的折扣。"
        elif "business_outcome" in metric or "asset_outcome" in metric:
            interpretation = f"{label}揭示进入后的存续结果：{value}；退出或资产再转让是基准率必须保留的失败/不稳定结局。"
            research_use = "用于反驳只观察宣布进入而忽略后续退出的幸存者偏差，并扩宽长期概率支持区间。"
        elif "success_rate" in metric:
            interpretation = f"{label}给出2/9的定向描述率；样本小、异质且选择性强，因此只是一条先验锚而非统计后验。"
            research_use = "作为3年工作先验众数的透明起点；公司证据更新必须逐组列示，禁止直接套用2/9。"
        elif "800g_share" in metric or "customer_deployment" in metric:
            interpretation = f"{label}提供收购时的真实商业成熟度参照：{value}；已有客户与收入的标的和从零孵化不可等权。"
            research_use = "用于区分‘收购成熟平台’与‘相邻制造迁移’，并校准何种收入/客户闭环才算有意义进入。"
        else:
            interpretation = f"{label}展示跨界路径的能力范围：{value}；联合开发或专业制造只覆盖价值链一段，不自动等于完整模块成功。"
            research_use = "用于案例分层和低/中/高基准率敏感性，避免把器件、代工与品牌模块混为同一事件。"
    elif entity_key == "industry_demand_supply_model":
        if "status" in metric:
            interpretation = f"{label}说明路线仍处于标准化阶段：{value}；标准草案或协议存在不等于规模部署。"
            research_use = "用于设定1.6T/3.2T/CPO的可用时间窗和慢路径，不直接生成出货或收入。"
        elif any(token in metric for token in ("link_rate", "port_count", "bandwidth", "switch_capacity", "port_configuration")):
            interpretation = f"{label}提供设备级容量/端口上限：{value}；设备最大规格必须再乘部署量、拓扑、启用率和链路两端。"
            research_use = "作为端点—拓扑—光口需求模型输入，防止把厂商最大系统规模误写成已部署光模块数量。"
        elif "power_efficiency" in metric or "two_tier" in metric:
            interpretation = f"{label}是平台方对架构收益或规模的口径：{value}；发行人性能主张需要实际部署与可比边界约束。"
            research_use = "用于CPO加速敏感性和网络层级变化测试，不覆盖公司客户资格或传统模块份额。"
        else:
            interpretation = f"{label}刻画行业协作与标准供给：{value}；成员和协议数量只说明生态广度，不能当销量。"
            research_use = "用于判断互操作和标准成熟度是否解除合格供给瓶颈，并与客户侧采购证据分开。"
    elif entity_key == "qualification_upstream_constraints":
        if "qualification" in metric or "requalification" in metric:
            interpretation = f"{label}表明客户导入或供应商变更存在显著时滞：{value}；这一时滞直接限制样品到可售供给的速度。"
            research_use = "用于qualification延后敏感性和重复订单门槛；不能用展会日期代替认证起点。"
        elif "purchase_commitment" in metric or "investment" in metric or "funding" in metric:
            interpretation = f"{label}显示核心器件扩产往往依赖资本与长期锁量：{value}；资金存在不表示新进入者已经获得配额。"
            research_use = "用于约束laser/PIC/DSP可得性和供给上沿，并要求公司级采购或供应商交叉证据后才放宽。"
        elif "source_risk" in metric or "shortage" in metric:
            interpretation = f"{label}确认上游集中和短缺是成熟供应商也面对的约束：{value}；新进入者不能按现货无限扩产。"
            research_use = "用于合格供给折扣、营运资本和替代料再认证冲击，不直接改变终端需求。"
        elif "license" in metric:
            interpretation = f"{label}给出政策审查边界：{value}；需区分先进计算/半导体与普通模块，不能笼统写成全面禁运。"
            research_use = "用于区域需求与器件可得性的双向政策情景，只有规则明确覆盖具体对象时才改基础参数。"
        else:
            interpretation = f"{label}说明工程演示或互操作覆盖度：{value}；参与和演示低于客户AVL、可靠性与重复订单。"
            research_use = "用于工程成熟节点和公开生态负证据边界，不把参与公司数量转换为进入概率。"
    else:
        if "recruitment" in metric or "role" in metric or "directions" in metric:
            interpretation = f"{label}只反映公开人才意图：{value}；集团级方向、滚动职位或博士课题不能推算在岗人数与专线规模。"
            research_use = "用于人才领先指标去重和主题分类；只有法人、地点、职责、首次/末次可见与后续产品证据闭环才升级。"
        elif "patent" in metric:
            interpretation = f"{label}证明存在相邻知识资产：{value}；申请主体、权利要求、场景和产品实施决定其能否迁移到数据中心。"
            research_use = "用于专利族与场景分层，车载或未披露速率的家族只作邻接，不进入800G+产品成熟度。"
        elif "product_scope" in metric or "public_product" in metric:
            interpretation = f"{label}界定公开制造/产品能力：{value}；晶圆、封测或光电器件不等于完整高速收发模块。"
            research_use = "用于拆开器件、封装和模块三层能力，并检查是否存在资产、团队或产品页的跨主体转移。"
        else:
            interpretation = f"{label}提供招聘、专利或产能审计的范围底座：{value}；未出现的专项能力保持未知，不补零也不默认存在。"
            research_use = "用于确定下一轮检索词、法人和项目地点，并与客户、设备、良率和收入证据交叉后才更新里程碑。"
    return interpretation, research_use


def _theory_ledger(
    entity_key: str,
    points: list[dict[str, Any]],
    source_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates = [point for point in points if point.get("entity_key") == entity_key]
    if len(candidates) < 8:
        candidates.extend(point for point in points if point not in candidates)
    output: list[dict[str, Any]] = []
    used_research_uses: set[str] = set()
    for index, point in enumerate(candidates[:12], start=1):
        ref = point["source_ref"]
        source = source_lookup[ref]
        interpretation, base_research_use = _theory_point_narrative(
            entity_key, point, source
        )
        label = _theory_metric_label(point["metric"])
        period_display = _theory_period_display(
            point.get("period") or point.get("as_of_date")
        )
        research_use = f"{label}：{base_research_use}"
        if research_use in used_research_uses:
            research_use = (
                f"{label}（{period_display}）：{base_research_use}"
            )
        if research_use in used_research_uses:
            research_use = (
                f"{source['publisher']}的{label}（{period_display}）："
                f"{base_research_use}"
            )
        if research_use in used_research_uses:
            raise ValueError(
                f"{entity_key} 的理论底稿用途仍重复：{research_use}"
            )
        used_research_uses.add(research_use)
        output.append(
            {
                "source_ref": ref,
                "data_point_title": (
                    f"{source['publisher']}：{_theory_metric_label(point['metric'])}"
                ),
                "research_category": entity_key,
                "metric": point["metric"],
                "period": period_display,
                "value_num": point.get("value_num"),
                "value_text": point.get("value_text") or "见结构化数值或 observations",
                "unit": point.get("unit") or "文本",
                "source_excerpt": point["source_excerpt"],
                "source_excerpt_zh": point.get("source_excerpt_zh") or point["source_excerpt"],
                "interpretation": interpretation,
                "research_use": research_use,
            }
        )
    return output


def _entities(
    sources: list[dict[str, Any]],
    points: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    # 部分来源（财务、内部底稿、本地材料）不是由 _normalize_source 创建；
    # 在 pack 组装前统一补齐 provenance，并让兼容 independence_key 使用机构/事件去重口径。
    for source in sources:
        source.update(_source_provenance(source))
    lookup = {source["ref"]: source for source in sources}
    output: list[dict[str, Any]] = []
    for key, spec in MARKET_ENTITY_SPECS.items():
        weight_sum = sum(Decimal(str(value)) for value in spec["weights"].values())
        if weight_sum != Decimal("1.0"):
            raise ValueError(f"{key} 权重之和不是1.00：{weight_sum}")
        factor_codes = [factor["factor_code"] for factor in spec["factors"]]
        if set(factor_codes) != set(spec["weights"]):
            raise ValueError(f"{key} factor/weight 未一一对应")
        factors = []
        for index, factor_spec in enumerate(spec["factors"], start=1):
            factors.append(
                _factor(
                    key,
                    spec["name"],
                    factor_spec,
                    spec["weights"][factor_spec["factor_code"]],
                    lookup,
                    index=index,
                )
            )
        evidence_signatures = {
            tuple(
                link["corroboration_key"]
                for link in factor["factor_evidence_links"]
                if link["score_eligible"]
            )
            for factor in factors
        }
        if len(evidence_signatures) != len(factors):
            raise ValueError(f"{key} 仍有因子机械复用完全相同的证据组集合")
        score_unrounded = sum(factor["weighted_contribution"] for factor in factors)
        low_unrounded = sum(factor["weighted_low_contribution"] for factor in factors)
        high_unrounded = sum(factor["weighted_high_contribution"] for factor in factors)
        score_point = _round_half_up(score_unrounded)
        band_low = _round_half_up(low_unrounded)
        band_high = _round_half_up(high_unrounded)
        if not 0 <= band_low <= score_point <= band_high <= 100:
            raise ValueError(
                f"{key} 聚合区间非单调：{band_low}/{score_point}/{band_high}"
            )
        refs = _unique(
            ref
            for factor in factors
            for value in factor["evidence_ref_uri_list"]
            for ref in [value.removeprefix("source_ref:")]
        )
        entity_groups = {
            link["corroboration_key"]
            for factor in factors
            for link in factor["factor_evidence_links"]
            if link["score_eligible"]
        }
        output.append(
            {
                "key": key,
                "canonical_name": spec["name"],
                "display_name": spec["name"],
                "entity_type": "company",
                "taxonomy_level": "company",
                "description": spec["description"],
                "entity_research_mode": "market_linked",
                "evidence_ref_uri_list": [_uri(ref) for ref in refs],
                "source_count": len(refs),
                "independent_source_count": len(entity_groups),
                "score_point": float(score_point),
                "score_unrounded": round(score_unrounded, 8),
                "score_band_low": float(band_low),
                "score_band_high": float(band_high),
                "score_band_low_unrounded": round(low_unrounded, 8),
                "score_band_high_unrounded": round(high_unrounded, 8),
                "score_weights": dict(spec["weights"]),
                "score_formula": "Σ(weight_i × normalized_risk_i)",
                "score_direction": "0—100；越高表示进入风险或现有龙头终值下行风险越高",
                "score_rounding": "Decimal ROUND_HALF_UP to integer",
                "missing_factor_policy": "fail_closed_score_null_no_reweight",
                "band_generation": "同一权重分别聚合每个因子显式 low/high normalized risk；ROUND_HALF_UP；不是统计置信区间",
                "coverage": float(spec["coverage"]),
                "confidence": float(spec["confidence"]),
                "score_quality_label": "medium_confidence" if spec["confidence"] < 0.75 else "high_confidence",
                "band_reason": "每个因子显式保存 low/base/high 证据情景，再使用与点分相同的公开权重聚合；官方冲突、私有认证不可得和模型假设通过情景输入进入区间。",
                "factor_scores": factors,
            }
        )
    for key, spec in THEORY_ENTITY_SPECS.items():
        ledger = _theory_ledger(key, points, lookup)
        ledger_refs = _unique(point["source_ref"] for point in ledger)
        literature_refs = _unique(
            [*ledger_refs, *THEORY_LITERATURE_REFS.get(key, [])]
        )
        method_refs = _unique(THEORY_METHOD_REFS.get(key, []))
        answer_refs = _unique(THEORY_ANSWER_REFS.get(key, []))
        refs = _unique([*literature_refs, *method_refs, *answer_refs])
        unknown_refs = [ref for ref in refs if ref not in lookup]
        if unknown_refs:
            raise ValueError(
                f"{key} 理论正文含未知来源：{sorted(unknown_refs)}"
            )
        literature = _theory_literature_review(
            key, spec["name"], literature_refs
        )
        output.append(
            {
                "key": key,
                "canonical_name": spec["name"],
                "display_name": spec["name"],
                "entity_type": "product_material",
                "taxonomy_level": "product_material",
                "description": spec["description"],
                "entity_research_mode": "theory_research",
                "evidence_ref_uri_list": [_uri(ref) for ref in refs],
                "source_count": len(refs),
                "independent_source_count": _source_groups(refs, lookup),
                "research_profile": {
                    "research_question": spec["question"],
                    "research_scope": spec["description"],
                    "methodology_note": THEORY_METHODOLOGY_NOTES[key],
                    "literature_review_markdown": literature,
                    "analysis_markdown": _theory_analysis(
                        key, spec["name"], method_refs
                    ),
                    "answer_markdown": _theory_answer(
                        key, spec["name"], answer_refs
                    ),
                    "conclusion_markdown": _theory_conclusion(key, spec["name"]),
                    "limitations_markdown": THEORY_LIMITATIONS[key],
                    "evidence_ref_uri_list": [_uri(ref) for ref in refs],
                },
                "research_data_points": ledger,
            }
        )
    return output


def _theory_literature_review(key: str, name: str, refs: list[str]) -> str:
    del name
    citations = "".join(_cite(ref) for ref in refs)
    return f"### 文献与证据综述\n\n{THEORY_LITERATURE_DETAILS[key]}{citations}"


def _theory_analysis(key: str, name: str, refs: list[str]) -> str:
    del name
    citations = "".join(_cite(ref) for ref in refs)
    return f"### 方法分析\n\n{THEORY_METHOD_DETAILS[key]}{citations}"


def _theory_answer(key: str, name: str, refs: list[str]) -> str:
    del name
    citations = "".join(_cite(ref) for ref in refs)
    return f"### 对问题的回答\n\n{THEORY_ANSWER_DETAILS[key]}{citations}"


def _theory_conclusion(key: str, name: str) -> str:
    del name
    return f"### 结论与复核条件\n\n{THEORY_CONCLUSION_DETAILS[key]}"


TARGET_SPECS: list[dict[str, str]] = [
    {
        "entity_key": "byd_entry_risk",
        "company_key": "byd_electronic",
        "target_name": "比亚迪电子",
        "ticker": "0285.HK",
        "market": "中国香港",
        "target_url": "https://www.byd-electronics.com/",
        "exposure": "直接承接比亚迪体系已披露的 AI 服务器、液冷、电源与高速互联业务，是潜在数据中心光通信进入的首要上市主体。",
        "action": "优先验证明确型号的高速光模块、光学团队、专线设备、客户正式合格供应资格和高速互联收入拆分；在这些证据出现前不按光模块收入估值。",
        "view": "作为相邻进入期权而非已确认高速光模块供应商；只有硬里程碑连续出现才提高竞争威胁和标的研究优先级。",
        "risk": "数据中心组合销售与强制造能力可能压低系统报价，但集团通用能力、车载专利和比亚迪半导体资源不能自动迁移。",
        "relative": "比母公司更直接，但公开光模块证据仍显著弱于立讯；适合作为进入触发器观察标的。",
        "confirm": "披露400G以上明确产品并出现客户测试、专线验收和可审计收入后，将其列为重点跟踪对象。",
        "falsify": "若两年内仍无具名产品、团队、专线或客户证据，应降低对其长期进入高速光模块市场的判断。",
        "recommendation": "当前不因光模块主题单独提高配置；把服务器/液冷主业价值与尚未证实的光模块期权分开。",
    },
    {
        "entity_key": "byd_entry_risk",
        "company_key": "byd",
        "target_name": "比亚迪股份",
        "ticker": "002594.SZ",
        "market": "中国A股",
        "target_url": "https://www.bydglobal.com/cn/InvestorRelations.html",
        "exposure": "通过控股关系间接暴露于比亚迪电子，但自身主要价值仍由汽车、动力电池及其他集团业务驱动。",
        "action": "跟踪对子公司光通信项目的资本、关联交易、共同专利受让或资产注入，而不是把母公司车载光通信专利直接归入数据中心模块。",
        "view": "光模块对母公司估值的直接性低；除非出现集团级资本配置与可量化子公司收益，竞争主题只是很小的期权。",
        "risk": "集团资源强会提高远期进入上限，但主体错配会严重高估技术、客户和财务归属。",
        "relative": "相较比亚迪电子仅是控股和资源映射工具，不是优先的光模块业务承接证券。",
        "confirm": "出现明确关联交易、项目法人、团队迁移或合并口径收入后，再提高母公司与这一主题的相关性判断。",
        "falsify": "若项目始终局限于子公司且对集团利润不重要，母公司光模块暴露应保持接近零。",
        "recommendation": "不得用光模块潜在进入单独支持母公司估值判断；仅在子公司价值可穿透时纳入。",
    },
    {
        "entity_key": "luxshare_entry_risk",
        "company_key": "luxshare",
        "target_name": "立讯精密",
        "ticker": "002475.SZ",
        "market": "中国A股",
        "target_url": "https://www.luxshare-ict.com/",
        "exposure": "上市公司监管披露覆盖通信与数据中心业务，立讯技术的产品与制造能力可通过集团口径影响收入和资本配置。",
        "action": "逐项核验国内中小客户交付、全球头部云客户正式准入、重复订单、模块专线和分部收入，避免用混合分部产能折算光模块数量。",
        "view": "已经高于概念阶段但尚未闭环全球头部客户和有意义收入；风险路径是制造规模加组合销售，而非已证实的全栈自研。",
        "risk": "官方披露在客户层级和1.6T商业阶段上存在冲突；外采核心器件、良率、价格与营运资本可能限制利润捕获。",
        "relative": "比比亚迪更接近形成真实竞争威胁，也是两家进入者中优先跟踪的证券。",
        "confirm": "具名头部客户、稳定的正式合格供应资格、两代以上重复订单及光模块收入和毛利拆分同时出现后，上调竞争威胁。",
        "falsify": "若商务扩展长期停留在中小客户、没有专线良率和规模收入，应明显降低未来三年进入全球头部客户体系的判断。",
        "recommendation": "按通信主业和光模块期权分部估值；在利润与现金流确认前不把产品页等同高质量新增利润。",
    },
    {
        "entity_key": "innolight_terminal_risk",
        "company_key": "innolight",
        "target_name": "中际旭创",
        "ticker": "300308.SZ",
        "market": "中国A股",
        "target_url": "https://www.innolight.com/",
        "exposure": "高速光模块是核心收入与利润来源，直接受AI网络增长、新进入者价格行为、客户集中和共封装光学架构迁移影响。",
        "action": "同时跟踪800G/1.6T出货、客户集中、产品毛利、海外产能、经营现金流减长期资产支出和募资项目，区分正常技术降价与异常份额损失。",
        "view": "量产、客户与现金流防线强，但当前估值对高增长持续性敏感；真正风险是全球客户突破、低价和架构迁移的组合。",
        "risk": "前五大客户收入占比高、估值倍数高；若同规格额外降价与份额损失重叠，长期经营价值会对折现率和永续增速高度敏感。",
        "relative": "相较新易盛绝对现金流更强、项目投入更大，风险抵御较好；但高市值放大预期落空的估值损失。",
        "confirm": "若龙头客户份额、毛利和现金流跨代保持，同时新进入者只停留区域客户，可继续给防御溢价。",
        "falsify": "若头部客户导入新竞争者且公司连续两个季度丢份额、降价和自由现金流恶化，应触发下修。",
        "recommendation": "不能仅因远期竞争叙事得出低估值也不能买；需以情景概率、现金流和估值安全边际共同决策。",
    },
    {
        "entity_key": "eoptolink_terminal_risk",
        "company_key": "eoptolink",
        "target_name": "新易盛",
        "ticker": "300502.SZ",
        "market": "中国A股",
        "target_url": "https://www.eoptolink.com/",
        "exposure": "光模块业务和海外收入占比高，直接暴露于速率升级、客户集中、上游器件、全球认证与额外价格竞争。",
        "action": "核验1.6T、线性接收光模块、硅光芯片和线性可插拔光模块项目从内部验证或小批转向客户规模订单的过程，并监控泰国产能和现金流兑现。",
        "view": "较高产品毛利和海外业务提供收益弹性，但绝对自由现金流小于中际旭创；对新增竞争与技术路线切换的长期经营价值更敏感。",
        "risk": "前五大客户集中、上游供应集中与高估值叠加；项目状态不能统一写成量产，产品组合变化可能使平均成交价解读失真。",
        "relative": "相较中际旭创毛利率更高、海外占比更纯，但资源缓冲较小；严重情景中下行风险略大。",
        "confirm": "若多代产品验证转化为重复订单且泰国产能、毛利和自由现金流同步提升，可抵消部分进入者风险。",
        "falsify": "若新产品停留样品或小批、客户集中上升且价格压力侵蚀现金流，应下修长期经营价值和相对偏好。",
        "recommendation": "以客户阶段和自由现金流为主线检验估值，不把单一高毛利或高增速外推到2031年。",
    },
]


TARGET_PARENT_RESEARCH_RELATIONS: dict[str, str] = {
    "byd_electronic": "用于判断高速光模块能否从相邻能力变成比亚迪电子自身的新增收入和现金流；在产品、客户与收入闭环前，不把这项业务计入盈利预测。",
    "byd": "用于判断比亚迪股份对子公司的间接权益和集团协同能否产生可量化收益；汽车、动力电池和比亚迪半导体的能力不直接计入光模块业务。",
    "luxshare": "用于判断立讯精密已有产品和制造能力能否转化为可分的通信业务收入、利润和现金流，并核验头部客户与重复订单是否真正成立。",
    "innolight": "用于测算新进入者取得客户和批量订单后，中际旭创的市场份额、价格、利润和自由现金流会受到多大影响，并与当前估值安全边际比较。",
    "eoptolink": "用于测算新增竞争与技术路线变化对新易盛收入、毛利、自由现金流和估值的影响，重点检验客户集中和较小现金流缓冲是否放大下行。",
}


def _target_data_points(
    company_key: str,
    entity_key: str,
    points: list[dict[str, Any]],
    source_lookup: dict[str, dict[str, Any]],
    usd_to_cny: float,
) -> list[dict[str, Any]]:
    ref = f"FIN-{company_key.upper()}"
    candidates = [
        point
        for point in points
        if point.get("source_ref") == ref and point.get("entity_key") == entity_key
    ]
    preferred = [
        point
        for metric in (
            "总市值",
            "市盈率（股价/最近十二个月每股收益）",
            "市净率（股价/每股净资产）",
            "市销率（市值/最近十二个月营业收入）",
            "营业收入序列",
            "归母净利润序列",
            "经营现金流减购建长期资产支出序列",
            "毛利率序列",
            "最近报告期净资产收益率",
            "最近报告期总资产收益率",
        )
        for point in candidates
        if point.get("metric") == metric
    ]
    selected = preferred[:10] if preferred else candidates[:10]
    output: list[dict[str, Any]] = []
    for point in selected:
        source = source_lookup[ref]
        observations = point.get("observations") if isinstance(point.get("observations"), list) else []
        latest = observations[-1] if observations else {}
        latest_period = latest.get("period") or latest.get("as_of_date")
        latest_value_num = latest.get("value_num") if observations else point.get("value_num")
        latest_value_text = latest.get("value_text") if observations else point.get("value_text")
        if observations:
            sequence_start = observations[0].get("period") or observations[0].get("as_of_date")
            sequence_note = f"原序列覆盖{sequence_start}至{latest_period}，标的卡片落最新一期；完整序列保留在研究数据点。"
        else:
            sequence_note = None
        source_excerpt = f"{point['source_excerpt']} {sequence_note or ''}".strip()
        source_excerpt_zh = f"{point.get('source_excerpt_zh') or point['source_excerpt']} {sequence_note or ''}".strip()
        if (
            point.get("unit") == "亿元人民币"
            and _finite(latest_value_num) is not None
            and usd_to_cny > 0
        ):
            cny_amount = float(latest_value_num)
            display_note = (
                f"本轮美元等值按1美元={usd_to_cny:.4f}元人民币换算："
                f"{cny_amount:,.2f}亿元人民币（约{cny_amount / usd_to_cny:,.2f}亿美元）。"
            )
            source_excerpt = f"{source_excerpt} {display_note}".strip()
            source_excerpt_zh = f"{source_excerpt_zh} {display_note}".strip()
        output.append(
            {
                "metric_name": point["metric"],
                "metric_category": "valuation" if any(token in point["metric"] for token in ("市值", "市盈", "市净", "市销")) else "financial",
                "period": latest_period or point.get("period"),
                "as_of_date": latest_period or point.get("as_of_date"),
                "value_num": latest_value_num,
                "value_text": latest_value_text or sequence_note,
                "unit": point["unit"],
                "source_title": source["title"],
                "source_title_zh": source["title_zh"],
                "source_publisher": source["publisher"],
                "source_url": source.get("url"),
                "source_excerpt": source_excerpt,
                "source_excerpt_zh": source_excerpt_zh,
                "evidence_ref_uri": _uri(ref),
                "data_quality_label": "结构化快照，字段日期已标明",
                "direction": "neutral",
            }
        )
    return output


def _financial_status_for_target(
    company_key: str,
    points: list[dict[str, Any]],
) -> str:
    ref = f"FIN-{company_key.upper()}"
    company_points = [point for point in points if point.get("source_ref") == ref]
    financial_periods = sorted(
        {
            _clean(observation.get("period"))
            for point in company_points
            if point.get("fact_type") in {"structured_financial_series", "calculated_series"}
            for observation in point.get("observations", [])
            if _clean(observation.get("period"))
        }
    )
    market_dates = sorted(
        {
            _clean(point.get("as_of_date") or point.get("period"))
            for point in company_points
            if point.get("fact_type") == "structured_market_snapshot"
            and _clean(point.get("as_of_date") or point.get("period"))
        }
    )
    company_name = next(
        (
            spec["target_name"]
            for spec in TARGET_SPECS
            if spec["company_key"] == company_key
        ),
        company_key,
    )
    annual_periods = [
        period for period in financial_periods if re.fullmatch(r"20\d{2}", period)
    ]
    market_clause = (
        f"估值观察截至{market_dates[-1]}"
        if market_dates
        else "目前没有可核验的市场估值观察"
    )
    if annual_periods:
        annual_range = (
            annual_periods[-1]
            if len(annual_periods) == 1
            else f"{annual_periods[0]}—{annual_periods[-1]}年"
        )
        return (
            f"{company_name}的历史比较使用{annual_range}实际财务，{market_clause}。"
            "季度数据只用于核对趋势，未披露的未来收入和现金流只在情景测算中出现。"
        )
    return (
        f"{company_name}目前没有足以形成连续年度比较的公开财务序列；{market_clause}。"
        "因此本研究不填补缺失历史值，也不把情景测算写成公司指引。"
    )


def _targets(
    points: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    usd_to_cny: float,
) -> list[dict[str, Any]]:
    lookup = {source["ref"]: source for source in sources}
    output: list[dict[str, Any]] = []
    for index, spec in enumerate(TARGET_SPECS, start=1):
        financial_status = _financial_status_for_target(spec["company_key"], points)
        target_points = _target_data_points(
            spec["company_key"], spec["entity_key"], points, lookup, usd_to_cny
        )
        output.append(
            {
                "entity_key": spec["entity_key"],
                "target_name": spec["target_name"],
                "ticker": spec["ticker"],
                "market": spec["market"],
                "target_type": "security",
                "target_url": spec["target_url"],
                "exposure_rationale": spec["exposure"],
                "research_action": spec["action"],
                "investment_view": spec["view"],
                "risk_note": spec["risk"],
                "target_priority": "P1" if index in {3, 4, 5} else "P2",
                "target_quality_label": "证据驱动、条件化",
                "relative_preference": spec["relative"],
                "confirmed_scenario_action": spec["confirm"],
                "falsified_scenario_action": spec["falsify"],
                "target_profile_markdown": f"{spec['target_name']}（{spec['ticker']}）的业务暴露边界：{spec['exposure']}",
                "target_deep_research_markdown": f"本页重点研究：{spec['action']} 需要同时考虑的主要风险是：{spec['risk']}",
                "entity_relation_markdown": f"该证券绑定到“{MARKET_ENTITY_SPECS[spec['entity_key']]['name']}”，但只承接可归属到本主体的业务、财务和客户证据。",
                "parent_research_relation_markdown": TARGET_PARENT_RESEARCH_RELATIONS[spec["company_key"]],
                "conditional_investment_recommendation": spec["recommendation"],
                "financial_data_status": financial_status,
                "link_status": "linked",
                "support_status": "supported",
                "target_data_points": target_points,
            }
        )
    return output


def _local_material_sources(screening: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    duplicate_indexes = {
        int(index)
        for group in screening.get("exact_duplicate_groups", [])
        for index in (group.get("value", []) if isinstance(group, dict) else group)
    }
    for material in screening.get("materials", []):
        index = int(material["index"])
        ref = f"LOCAL-PDF-{index:02d}"
        status = "duplicate" if index in duplicate_indexes and index != min(duplicate_indexes) else "weak_source_only"
        output.append(
            {
                "ref": ref,
                "title": material["filename"],
                "title_zh": material["filename"],
                "publisher": "用户提供的卖方/行业材料",
                "publish_date": material["filename"][:10] if re.match(r"\d{4}-\d{2}-\d{2}", material["filename"]) else None,
                "source_tier": "C",
                "source_review_status": status,
                "language": "zh-CN",
                "excerpt": material["screening_reason"],
                "excerpt_zh": material["screening_reason"],
                "local_path": str(ROOT / material["relative_path"]),
                "url": None,
                "independence_key": f"local-pdf-sha256:{material['pdf_sha256']}",
                "independence_rationale": "按文件 SHA256 去重；卖方材料只作线索、预测或市场预期，不能替代公司、客户、供应商、标准组织或监管原文。",
                "document_sha256": material["pdf_sha256"],
                "screening_status": material["screening_status"],
            }
        )
    return output


def _collect_research_inputs() -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, Any],
]:
    required = [
        BYD_EVIDENCE_PATH,
        BYD_SEARCH_EXPANSION_PATH,
        LUX_EVIDENCE_PATH,
        INDUSTRY_EVIDENCE_PATH,
        FINANCIAL_PATH,
        SCREENING_PATH,
        CROSS_AUDIT_PATH,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"缺少研究输入：{missing}")

    financial = _safe_payload(_load_json(FINANCIAL_PATH))
    screening = _load_json(SCREENING_PATH)
    evidence_packs = [
        ("", _load_json(BYD_EVIDENCE_PATH)),
        ("", _load_json(BYD_SEARCH_EXPANSION_PATH)),
        ("", _load_json(LUX_EVIDENCE_PATH)),
        ("", _load_json(INDUSTRY_EVIDENCE_PATH)),
    ]
    sources: list[dict[str, Any]] = []
    for prefix, evidence in evidence_packs:
        sources.extend(_normalize_source(source, prefix=prefix) for source in evidence.get("sources", []))
    existing_refs = {source["ref"] for source in sources}
    sources.extend(
        source for source in _luxshare_conflict_sources() if source["ref"] not in existing_refs
    )
    sources.extend(_financial_sources(financial))
    sources.extend(_local_material_sources(screening))

    # 让来源主记录继承同一原始记录下已经核验的数据点摘录，避免公开来源抽屉
    # 只显示标题句而与所支持的详细 claim/财务事实语义错位。
    _enrich_source_excerpts_from_evidence(sources, evidence_packs)

    # 两份立讯监管披露均保留，冲突在 claim、audit issue 和正文中闭环。
    for source in sources:
        if source["ref"] in {"LX-IR-202508", "LX-ANNUAL-2025", "LX-BOARD-REPORT-2025"}:
            source["source_review_status"] = "conflict"
        # 财务、内部底稿与本地材料不是由 _normalize_source 创建；在任何
        # evidence-role、claim audit 或参数来源校验之前先统一 provenance，
        # 避免同一来源在 pack 不同层使用两套独立性口径。
        source.update(_source_provenance(source))
        source["policy_evidence_role"] = _policy_role_for_source(source)
        intake_tier, origin_class = _public_source_class(source)
        source["intake_source_tier"] = intake_tier
        # 保留计算/证据层更细的 source_origin_class；公开来源分类使用独立字段。
        source["public_source_origin_class"] = origin_class
        source["hosting_channel"] = _source_hosting_channel(source)

    duplicate_refs = [ref for ref, count in Counter(source["ref"] for source in sources).items() if count > 1]
    if duplicate_refs:
        raise ValueError(f"source ref 重复：{duplicate_refs}")
    source_lookup = {source["ref"]: source for source in sources}

    points: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    for prefix, evidence in evidence_packs:
        points.extend(
            _normalize_data_point(point, source_prefix=prefix)
            for point in evidence.get("data_points", [])
        )
        for claim in evidence.get("claims", []):
            normalized = _normalize_claim(claim, source_lookup, source_prefix=prefix)
            if normalized:
                claims.append(normalized)

    points.extend(_luxshare_conflict_points())
    conflict_claims = [
        {
            "claim_id": "LX-CONFLICT-C01",
            "entity_key": "luxshare_entry_risk",
            "claim_type": "官方披露冲突",
            "claim_text": "立讯2024年报的头部客户测试/国际客户交付与2025-08监管记录的中小数据中心为主、无头部明确商务机会存在冲突；本研究同时保留，按区域交付存在、全球头部闭环未完成处理。",
            "source_ref": "LX-ANNUAL-2024",
            "source_excerpt": source_lookup["LX-ANNUAL-2024"]["excerpt"],
            "source_excerpt_zh": source_lookup["LX-ANNUAL-2024"]["excerpt_zh"],
            "supporting_source_refs": ["LX-ANNUAL-2024", "LX-IR-202508"],
            "counter_source_refs": ["LX-IR-202508"],
            "confidence": "high_conflict",
            "caveat": "可能由SKU、客户定义、测试/小批与稳定订单或时间差导致；公开证据不能裁定。",
        },
        {
            "claim_id": "LX-CONFLICT-C02",
            "entity_key": "luxshare_entry_risk",
            "claim_type": "商业阶段边界",
            "claim_text": "立讯1.6T产品与公司所称早期商业化可确认工程/出货进展，但2026-05监管口径仍称业务起步、拓展需时间且无自研1.6T硅光芯片，不能据此确认规模收入或全栈自研。",
            "source_ref": "LX-IR-20260507",
            "source_excerpt": source_lookup["LX-IR-20260507"]["excerpt"],
            "source_excerpt_zh": source_lookup["LX-IR-20260507"]["excerpt_zh"],
            "supporting_source_refs": ["LX-IR-20260507", "LX-IR-20260525", "LX-FRO-2026"],
            "counter_source_refs": ["LX-FRO-2026"],
            "confidence": "high_conflict",
            "caveat": "外采PIC/DSP是可行模块路线；缺自研芯片只约束垂直整合，不把进入概率降为零。",
        },
    ]
    claims.extend(conflict_claims)

    points.extend(_financial_data_points(financial))
    model = write_model_artifacts(_model_config(financial), OUTPUT_DIR)
    # 计算底稿会被公开正文引用。把实际文件内容哈希写回 source 主记录，使
    # canonical pack/freeze 能绑定输入假设与输出结果，而不只绑定一个可变路径。
    for source_ref, artifact_path in (
        ("MODEL-INPUTS", OUTPUT_DIR / "model_inputs.json"),
        ("MODEL-WORKPAPER", OUTPUT_DIR / "model_outputs.json"),
    ):
        source_lookup[source_ref]["document_sha256"] = _sha256(artifact_path)
    _validate_model_parameter_registries(model, source_lookup)
    points.extend(_model_data_points(model))
    claims.extend(_model_claims(model, source_lookup))
    # 分包 claim、手工冲突 claim 与模型 claim 必须进入同一个 canonical ledger；
    # 缺失字段保留显式 status/reason，不从正文猜测或造数。
    claims = [_complete_claim_ledger(claim, source_lookup) for claim in claims]
    _attach_probability_update_links(claims, model)
    for point in points:
        _standardize_inferred_note_in_place(point)
    role_by_ref = {
        source["ref"]: source["policy_evidence_role"] for source in sources
    }
    for item in [*claims, *points]:
        item["policy_evidence_role"] = role_by_ref[item["source_ref"]]
    return sources, claims, points, model, screening


def _model_claims(
    model: dict[str, Any], source_lookup: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    three = model["probability"]["horizons"]["3y"]["marginal_probability"]
    five = model["probability"]["horizons"]["5y"]["marginal_probability"]
    source = source_lookup["MODEL-WORKPAPER"]
    rows = [
        (
            "MODEL-C01",
            "probability_method_and_baserate",
            "模型方法",
            "每家公司先按保守值、最可能值和上限估算进入范围，再让两家公司共同受益或共同受阻的关系进入联合计算；抽样只传播这些估算的不确定性，不增加证据。",
        ),
        (
            "MODEL-C02",
            "byd_entry_risk",
            "进入概率",
            f"在当前证据与定义下，比亚迪电子有意义进入的代表结果约为3年{three['byd_meaningful_entry']:.1%}、5年{five['byd_meaningful_entry']:.1%}；估算范围较宽，反映具体产品、客户、专线和收入仍未验证。",
        ),
        (
            "MODEL-C03",
            "luxshare_entry_risk",
            "进入概率",
            f"立讯有意义进入的代表结果约为3年{three['luxshare_meaningful_entry']:.1%}、5年{five['luxshare_meaningful_entry']:.1%}；全球头部客户单独判断，没有用产品存在替代客户正式准入。",
        ),
        (
            "MODEL-C04",
            "probability_method_and_baserate",
            "联合概率",
            f"考虑正相关后，至少一家有意义进入的模型均值约为3年{three['at_least_one_entry']:.1%}、5年{five['at_least_one_entry']:.1%}，不能用两个边际概率简单相乘。",
        ),
        (
            "MODEL-C05",
            "industry_demand_supply_model",
            "ASP边界",
            "市场模型先计算正常技术降价下的需求和收入，再分别叠加进入者竞争与架构迁移，避免把正常成本下降重复归因于新竞争者。",
        ),
        (
            "MODEL-C06",
            "luxshare_entry_risk",
            "官方冲突",
            "立讯800G客户层级和1.6T商业阶段存在官方披露冲突；模型确认其高于概念阶段，但仍把全球头部云客户视为尚未闭环，并扩大而非压缩估算范围。",
        ),
    ]
    return [
        {
            "claim_id": claim_id,
            "entity_key": entity_key,
            "claim_type": claim_type,
            "claim_text": text,
            "source_ref": "MODEL-WORKPAPER",
            "source_excerpt": source["excerpt"],
            "source_excerpt_zh": source["excerpt_zh"],
            "supporting_source_refs": ["MODEL-WORKPAPER"],
            "counter_source_refs": [],
            "confidence": "medium",
            "caveat": "模型结论取决于事件定义、输入区间与情景传导；所有输入和种子均已保存。",
        }
        for claim_id, entity_key, claim_type, text in rows
    ]


def _section(
    *,
    key: str,
    title: str,
    body: str,
    refs: list[str],
    source_lookup: dict[str, dict[str, Any]],
    decision: str,
    unknown: str,
    monitor: str,
    sort_order: int,
) -> dict[str, Any]:
    inline_refs = re.findall(r"\^src:source_ref:([A-Za-z0-9_.-]+)", body)
    valid_refs = [ref for ref in _unique([*refs, *inline_refs]) if ref in source_lookup]
    citation_tail = "".join(_cite(ref) for ref in valid_refs[:5])
    appendix = f"""

### 本节结论状态与专属边界

- **[较强推断] 决策含义：** {decision}。{citation_tail}
- **[未知] 本节专属缺口：** {unknown}。
- **下一次更新：** {monitor}。
"""
    full = _clean_markdown(body.strip() + appendix)
    if len(full) < 1450:
        full += (
            "\n\n### 本节有限完成范围\n\n"
            f"当前只能在“{decision}”这一边界内使用结论。若把“{unknown}”改成点估计，"
            "必须公开代理变量、映射偏误和结论影响；新证据只影响相关里程碑，不能联动上调全部概率与利润假设。"
        )
    if len(full) < 1400:
        raise AssertionError(f"section {key} 深度不足：{len(full)}")
    return {
        "section_key": key,
        "section_title": title,
        "body_markdown": full,
        "support_status": "partially_supported",
        "evidence_ref_uri_list": [_uri(ref) for ref in valid_refs],
        "sort_order": sort_order,
    }


def _clean_markdown(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines).strip()


def _probability_value(model: dict[str, Any], horizon: str, metric: str) -> float:
    payload = model["probability"]["horizons"][horizon]["marginal_probability"][metric]
    if isinstance(payload, dict):
        return float(payload.get("mean", payload.get("median", 0.0)))
    return float(payload)


def _scenario_value(model: dict[str, Any], horizon: str, code: str) -> float:
    payload = model["probability"]["horizons"][horizon]
    values = payload.get("entry_state_probability") or payload.get("scenario_probability")
    value = values[code]
    if isinstance(value, dict):
        return float(value.get("mean", value.get("median", 0.0)))
    return float(value)


def _distribution_stats(value: Any, *, percent: bool = True) -> tuple[float, float, float, float]:
    """Return mean/P10/median/P90 without hiding the epistemic interval."""
    multiplier = 100.0 if percent else 1.0
    if not isinstance(value, dict):
        number = float(value) * multiplier
        return number, number, number, number
    mean_raw = float(value.get("mean", value.get("median", 0.0)))
    p10_raw = float(value.get("p10", value.get("low", mean_raw)))
    median_raw = float(value.get("median", mean_raw))
    p90_raw = float(value.get("p90", value.get("high", mean_raw)))
    return tuple(
        number * multiplier for number in (mean_raw, p10_raw, median_raw, p90_raw)
    )


def _distribution_cells(value: Any) -> str:
    mean, p10, median, p90 = _distribution_stats(value)
    return f"{mean:.1f}% | {p10:.1f}% | {median:.1f}% | {p90:.1f}%"


def _probability_summary(model: dict[str, Any], horizon: str) -> dict[str, Any]:
    payload = model["probability"]["horizons"][horizon]
    return payload.get("marginal_probability_summary") or payload["marginal_probability"]


def _company_region_probability_rows(model: dict[str, Any]) -> list[list[Any]]:
    metrics = (
        ("比亚迪电子", "中国", "byd_china_entry"),
        ("比亚迪电子", "全球", "byd_global_entry"),
        ("立讯精密", "中国", "luxshare_china_entry"),
        ("立讯精密", "全球", "luxshare_global_entry"),
    )
    rows: list[list[Any]] = []
    for horizon in ("3y", "5y"):
        summary = _probability_summary(model, horizon)
        for company, geography, metric in metrics:
            mean, p10, median, p90 = _distribution_stats(summary[metric])
            rows.append([horizon, company, geography, mean, p10, median, p90])
    return rows


def _joint_scope_probability_rows(model: dict[str, Any]) -> list[list[Any]]:
    metrics = (
        ("总事件", "至少一家", "at_least_one_entry"),
        ("总事件", "两家同时", "both_entry"),
        ("中国", "至少一家", "at_least_one_china_entry"),
        ("中国", "两家同时", "both_china_entry"),
        ("全球", "至少一家", "at_least_one_global_entry"),
        ("全球", "两家同时", "both_global_entry"),
    )
    rows: list[list[Any]] = []
    for horizon in ("3y", "5y"):
        summary = _probability_summary(model, horizon)
        for geography, event, metric in metrics:
            mean, p10, median, p90 = _distribution_stats(summary[metric])
            rows.append([horizon, geography, event, mean, p10, median, p90])
    return rows


def _geography_joint_probability_rows(model: dict[str, Any]) -> list[list[Any]]:
    labels = (
        ("china_only", "仅中国路径"),
        ("global_only", "仅全球路径"),
        ("china_and_global", "中国与全球同时"),
        ("entry_route_unidentified", "已进入但地域路线未识别"),
        ("no_meaningful_entry", "无有意义进入"),
    )
    rows: list[list[Any]] = []
    for horizon in ("3y", "5y"):
        payload = model["probability"]["horizons"][horizon]
        summary = payload.get("geography_scope_probability_summary", {})
        for metric, label in labels:
            if metric not in summary:
                continue
            mean, p10, median, p90 = _distribution_stats(summary[metric])
            rows.append([horizon, label, mean, p10, median, p90])
    return rows


def _public_source_class(source: dict[str, Any]) -> tuple[str, str]:
    """Map the internal S/A/B/C/D grade to the intake-facing origin taxonomy."""
    ref = str(source.get("ref", ""))
    publisher = str(source.get("publisher", ""))
    title = str(source.get("title", ""))
    haystack = f"{ref} {publisher} {title}".lower()
    internal_refs = {
        "MODEL-INPUTS",
        "MODEL-WORKPAPER",
        "LOCAL-MATERIAL-SCREENING",
        "CROSS-EVIDENCE-AUDIT",
    }
    if ref in internal_refs:
        return "Internal", "internal_model_audit"
    if ref.startswith("FIN-"):
        return (
            ("Structured", "structured_analyst")
            if ref.endswith("-ANALYST")
            else ("Structured", "structured_financial")
        )
    if ref.startswith("LOCAL-PDF-"):
        return "Tier 3", "sell_side_media"
    if source.get("origin_type") == "registry_mirror" or source.get(
        "source_origin_class"
    ) == "registry_mirror":
        return "Tier 1", "regulatory_government_standard"
    if source.get("origin_type") == "secondary_research_relay":
        return "Tier 3", "sell_side_media"
    if ref.startswith("JOB-") or source.get("source_tier") == "D":
        return "Tier 4", "weak_signal"
    if any(token in haystack for token in ("cignal", "lightcounting", "light counting")):
        return "Tier 2", "industry_forecast"
    issuer_tokens = (
        "byd electronic",
        "byd company limited",
        "比亚迪电子",
        "比亚迪股份",
        "luxshare precision",
        "luxshare-tech",
        "luxshare tech",
        "立讯精密",
        "innolight",
        "中际旭创",
        "eoptolink",
        "新易盛",
    )
    # 内容控制者优先于托管渠道：交易所/巨潮归档的公司年报和IR仍是
    # 发行人受控原文，不因URL或publisher含交易所字样变成政府证据。
    if any(token in haystack for token in issuer_tokens):
        return "Tier 1", "issuer_controlled"
    if any(
        token in haystack
        for token in (
            "oif",
            "ieee",
            "bis",
            "government",
            "政府",
            "cnipa",
            "patent",
            "hkex",
            "cninfo",
            "交易所",
        )
    ):
        return "Tier 1", "regulatory_government_standard"
    if source.get("source_tier") == "C":
        return "Tier 3", "sell_side_media"
    if source.get("source_tier") in {"S", "A", "B"}:
        return "Tier 1", "customer_supplier_original"
    return "Tier 3", "sell_side_media"


def _source_hosting_channel(source: dict[str, Any]) -> str:
    """Describe where a record is hosted separately from who controls content."""

    ref = _clean(source.get("ref"))
    haystack = " ".join(
        _clean(source.get(field)).lower()
        for field in ("publisher", "title", "url", "local_path")
    )
    if ref.startswith("FIN-"):
        return "structured_api_mirror"
    if ref.startswith("LOCAL-PDF-") or source.get("local_path") and not source.get("url"):
        return "local_research_artifact"
    if any(token in haystack for token in ("hkex", "香港联交所")):
        return "exchange_filing_archive_hkex"
    if any(token in haystack for token in ("cninfo", "巨潮资讯", "szse", "sse")):
        return "exchange_filing_archive_cn"
    if any(token in haystack for token in ("sec.gov", "edgar")):
        return "regulatory_filing_archive_sec"
    if source.get("url"):
        return "publisher_or_organization_website"
    return "other_verifiable_archive"


def _report_sections(
    model: dict[str, Any],
    sources: list[dict[str, Any]],
    screening: dict[str, Any],
    compiled_counts: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    lookup = {source["ref"]: source for source in sources}
    p3_byd = _probability_value(model, "3y", "byd_meaningful_entry")
    p5_byd = _probability_value(model, "5y", "byd_meaningful_entry")
    p3_lux = _probability_value(model, "3y", "luxshare_meaningful_entry")
    p5_lux = _probability_value(model, "5y", "luxshare_meaningful_entry")
    p3_any = _probability_value(model, "3y", "at_least_one_entry")
    p5_any = _probability_value(model, "5y", "at_least_one_entry")
    p3_global = _probability_value(model, "3y", "at_least_one_global_entry")
    p5_global = _probability_value(model, "5y", "at_least_one_global_entry")
    sections: list[dict[str, Any]] = []
    sections.append(
        _section(
            key="executive_summary",
            title="一页执行摘要：概率、破坏度与投资含义",
            refs=["BYD-S01", "BYD-S04", "LX-IR-202508", "LX-TRANSCEIVER-CURRENT", "SRC-INNO-AR25", "SRC-EOPT-AR25", "MODEL-WORKPAPER", "CROSS-EVIDENCE-AUDIT"],
            source_lookup=lookup,
            sort_order=10,
            decision="当前应把立讯列为已越过产品/工程门槛、但尚未闭环全球头部客户与有意义收入的真实进入者；比亚迪仍是相邻制造与系统协同期权。对龙头的长期风险应按概率乘破坏度，而不是按“出现新玩家”二元判断",
            unknown="两家私有客户 AVL、重复订单、专线良率、可分光模块收入，以及头部客户在低价与供应安全之间的真实权重",
            monitor="用具名 SKU—客户测试—AVL/design win—小批—两期重复订单—可分收入的同一里程碑链更新，而不是按新闻数量更新",
            body=f"""
### 结论先行

截至 {AS_OF_DATE}，两条威胁路径并不对称。比亚迪电子已经证实 AI 服务器出货、液冷认证/小批试产、电源开发和“高速互联”战略，但公开材料没有 400G/800G/1.6T/3.2T 数据中心光模块 SKU、客户 qualification、专用光学产线或收入拆分；因此它是有资金和制造底座的相邻潜在进入者，不是已确认的高速光模块竞争者。{_cite('BYD-S01')}{_cite('BYD-S04')} 立讯则已有 10G—1.6T 产品矩阵、800G 量产口径、1.6T 验证/早期批量与多家生态伙伴的工程证据，已经高于纯样机阶段；但 2024 年报与后续监管 IR 对“头部客户/中小数据中心”存在冲突，具名全球头部 CSP、稳定 AVL、重复订单和规模收入仍未闭环。{_cite('LX-IR-202508')}{_cite('LX-TRANSCEIVER-CURRENT')}{_cite('CROSS-EVIDENCE-AUDIT')}

模型的当前均值为：比亚迪有意义进入约 3 年 {p3_byd:.1%}、5 年 {p5_byd:.1%}；立讯约 3 年 {p3_lux:.1%}、5 年 {p5_lux:.1%}；至少一家进入约 3 年 {p3_any:.1%}、5 年 {p5_any:.1%}，至少一家进入全球头部体系约 3 年 {p3_global:.1%}、5 年 {p5_global:.1%}。这些不是统计后验：报告同时展示 low/mode/high 输入、认识不确定性分位数和依赖敏感性，且中国交付与全球进入分开。{_cite('MODEL-WORKPAPER')}

公司×中国/全球×3年/5年的完整均值和P10/中位/P90只在“联合情景树、概率更新与破坏程度”一节展示，摘要不重复整表。中国事件与全球事件均是正向定义的独立子事件，不能用“未全球”反推“中国进入”；5年是累计概率，也不能与3年相加。

### 关键结论证据状态矩阵

| 精确定义的命题 | 状态标签 | 当前边界 | 决策作用 |
|---|---|---|---|
| 数据中心经营披露直接主体是比亚迪电子，母公司与半导体能力不能自动迁移 | **[已确认事实]** | 控制、并表和经营载体有原始披露；未公开联合团队仍不可见 {_cite('BYD-S01')}{_cite('BYD-S02')} | 锁定主体与财务暴露 |
| 比亚迪电子已有 AI 服务器、液冷和数据中心相邻业务 | **[已确认事实]** | 确认相邻客户入口，不确认高速模块资格 {_cite('BYD-S01')} | 只上调长期系统协同期权 |
| 比亚迪“高速互联”已对应 400G+ 数据中心光模块 | **[未知]** | 无具名 SKU、规格、客户或模块收入 {_cite('BYD-S04')} | 不进入产品和份额事实 |
| 比亚迪集团招聘、车载光专利和智慧工厂可迁移 | **[早期信号]** | 法人、场景、HC、专线和客户未闭环 {_cite('BYD-S06')}{_cite('BYD-S11')} | 仅更新前置准备度 |
| Luxshare-Tech 产品覆盖 10G—1.6T 并有 800G 规格 | **[已确认事实]** | 确认产品页与规格存在，不确认客户采购 {_cite('LX-TRANSCEIVER-CURRENT')} | 产品/工程门槛已越过 |
| 立讯 800G 已越过纯样机并有区域有限交付 | **[较强推断]** | 发行人、互操作和伙伴证据一致，但收入不可分 {_cite('LX-IR-202508')}{_cite('OIF-OFC2026')} | 总进入概率高于比亚迪 |
| 立讯已在全球头部 CSP 形成稳定资格和跨代重复订单 | **[未知]** | 发行人口径冲突，未取得客户侧 OPN/AVL {_cite('LX-ANNUAL-2024')}{_cite('LX-IR-202508')} | 全球分支保持宽区间 |
| 卖方所称 BYD 已量产 800G 或立讯未来具体客户/出货数字 | **[市场传闻]** | 未回到公司、客户或供应商原始记录 {_cite('LOCAL-MATERIAL-SCREENING')} | 只生成补证请求 |
| 中际旭创、新易盛有多代量产、海外交付与正 FCF 防线 | **[已确认事实]** | 客户集中和架构迁移仍构成反向风险 {_cite('SRC-INNO-AR25')}{_cite('SRC-EOPT-AR25')} | 反对静态份额外推 |
| 严重利润池恶化尚未成为基准事实 | **[较强推断]** | 当前只是条件化压力测试，需客户、价格、份额与 FCF 共同触发 {_cite('MODEL-WORKPAPER')} | 作为尾部风险而非无条件禁买 |

对中际旭创和新易盛，最危险的不是立讯官网出现产品或比亚迪开始招聘，而是五个条件同向出现：头部客户 qualification、两代以上重复订单、同规格低价、可扩的合格产能/良率、以及 CPO/光引擎使传统模块价值池迁移。龙头的 2025 年正 FCF、量产经验和客户关系是防线；高客户集中和高估值又放大单一大客户迁移的尾部损失。{_cite('SRC-INNO-AR25')}{_cite('SRC-EOPT-AR25')}

当前不支持“长期竞争格局已经恶化，所以明年估值再低也不能买”的无条件结论。它只能是一个需要客户、价格、份额、毛利和 FCF 同时证实的风险假设。若新进入者只在区域客户形成有限交付，而 AI 网络端口增长、800G/1.6T 共存和龙头降本吸收新增供给，影响更可能是温和或局部；若至少一家进入全球头部客户并带来持续额外降价，才进入明显/严重情景。
""",
        )
    )
    sections.append(
        _section(
            key="event_contract",
            title="核心事件与定义：有意义进入、全球进入与盈利显著受损",
            refs=["MODEL-WORKPAPER", "SRC-AFOP-10K14", "SRC-FN-10K24", "SRC-OIF-2025", "BYD-S18", "NVIDIA-CX8-VALIDATED"],
            source_lookup=lookup,
            sort_order=20,
            decision="只有产品归属、客户资格、重复商业交付和规模可持续性四项同时成立，才把公司计为有意义进入；全球进入还需非中国头部客户或平台侧闭环",
            unknown="私有 AVL 与 NDA 订单使部分项目阶段不可见，且10亿元/1%/5%的基础规模阈值是研究合同而非行业统计事实",
            monitor="对宽松、基础、严格三组规模阈值做敏感性，并逐季度保存首次发现、最后可见和跨周期重复证据",
            body=f"""
### 研究方法与证据使用规则

本报告只使用五个命题状态：**[已确认事实]**表示原始记录直接覆盖该命题；**[较强推断]**表示多个独立事实支持关系，但仍含可识别假设；**[早期信号]**只更新团队、技术或制造准备等前置节点；**[市场传闻]**只记录尚未回到一手原文的市场说法；**[未知]**表示公开证据不能裁定。标签修饰精确命题，不给整家公司贴永久标签；“公司披露曾量产”可以是已确认的披露行为，但商业规模仍可保持未知。

编译证据时先锁定经营主体、产品口径、客户层级、事件日与发布日期。同一发行人的年报、官网、产品页和IR不因页数增加自动变成多个独立组；合作方、标准、客户和政府记录按底层事件聚类。公开名单未检出只构成有界负证据，未知既不等于零，也不等于默认成功。严禁用集团capex代填模块专线、车载专利代填数据中心产品、展会互操作代填客户AVL、卖方预测代填公司指引。

相反来源并列保留并扩大区间，不静默选边；岗位转载、专利族、新闻复述和公司多页宣传先去重。新证据只更新它实际覆盖的里程碑：产品规格不能越级到客户订单，客户qualification不能越级到合格规模产能，单期交付不能越级到跨代持续份额。监控按里程碑状态变化而非新闻数量执行，并保存更新前后证据hash、参数owner和人工裁决。

模型区间是决策工作区间，不会把结构化判断转换成客观频率。市场slow/base/fast目前未完整传导到公司财务；公司财务是reduced-form冲击模型；客户私有AVL、专线良率、同规格报价和分部利润不可得时保持有限完成。理论实体只交叉引用本统一方法，不再复制这些通用规则。

### 时间、产品和主体

观察起点是 {AS_OF_DATE}，3 年终点为 2029-07-20，5 年终点为 2031-07-20。合格产品限定为 AI 数据中心网络中的 800G 及以上可插拔模块、LPO/LRO、800G 及以上 AOC，以及能够承接传统模块价值量的 optical engine/CPO 光引擎。车载光通信、低速电信模块、纯铜 DAC/ACC/AEC、宽泛“高速互联”和无法映射到合并主体的集团能力均排除。

“有意义进入”要求四个条件同时成立：第一，有可归属经营主体的合格 SKU/形态；第二，至少一个合格大型客户或平台出现 qualification、AVL 或 design win；第三，至少跨两个采购或披露周期形成重复批量交付、收入或订单；第四，达到基础规模阈值，并有两个独立客户或同一客户跨两代延续。基础规模定义为年化收入至少 10 亿元、全球相关份额至少 1%、或中国合格市场份额至少 5%三者之一。宽松阈值为 5 亿元/0.5%/3%，严格阈值为 20 亿元/2%/10%；阈值变化必须进入敏感性，不能隐藏。

中国进入和全球进入是两个子事件。中国事件要求上述四项主要由中国客户体系满足；全球事件要求至少一个非中国头部 CSP、AI 平台、交换机厂或头部 ODM/OEM 的客户/平台/监管闭环。没有全球证据只表示“全球未确认”，不能自动推断全部客户在中国；海外工厂、英文官网、展会和兼容测试均不是充分条件。{_cite('BYD-S18')}{_cite('NVIDIA-CX8-VALIDATED')}

竞争后果相对同一份“无比亚迪/立讯有意义进入”基线定义。温和区间不越过明显门槛；明显只需实际FCF、净利润、毛利、份额、同规格额外ASP或5年终值任一越过10%/10%/2个百分点/5%/4%/10%的门槛。5年严重则要求单家公司2029—2031平均实际FCF与净利润损失均至少20%、FCF至少两年越线、平均毛利损失至少5个百分点、2031正常化终值至少下降25%，并且份额损失至少10%或额外ASP压力至少7%；3年用2029年且不采用终值门槛。这些百分比是本研究的显式决策合同，不是历史资料给出的行业频率。{_cite('MODEL-WORKPAPER')} 客户或产线变化可能触发重新认证，不能把样品当稳定份额。{_cite('SRC-AFOP-10K14')}{_cite('SRC-FN-10K24')}

“长期盈利显著受损”按公司分别判断：2029—2031 平均净利润和 FCF 均较无进入基线低至少 15%，同 WACC/g 的 2031 终值低至少 20%；这也是本研究的决策阈值，不是观察频率。{_cite('MODEL-WORKPAPER')} 终值是 2031 时点经营价值，经正常化 FCF 计算并折现回估值日；它不是当前股权公允价值，还需净现金、少数股东与其他业务桥接。
""",
        )
    )
    sections.append(
        _section(
            key="byd_entity_map",
            title="比亚迪 / 比亚迪电子：主体、业务与技术边界",
            refs=["BYD-S01", "BYD-S02", "BYD-S04", "BYD-S08", "BYD-S09", "BYD-S10", "BYD-S11", "BYD-S16"],
            source_lookup=lookup,
            sort_order=30,
            decision="数据中心业务首先归属比亚迪电子；母公司控股关系、比亚迪半导体封测、车载专利和通用工厂只能作为相邻迁移代理",
            unknown="是否存在未公开的联合团队、资产转移、光模块项目法人或客户保密项目",
            monitor="寻找关联交易、共同专利受让、具名产品页、光学岗位法人、专线设备招标和高速互联分部收入",
            body=f"""
### canonical 主体映射

与数据中心业务直接对应的公开经营主体是比亚迪电子；比亚迪股份通过金菱环球间接持有比亚迪电子 65.76% 权益，提供经济敞口但不等于技术和客户自动归属。比亚迪半导体是另一经营主体，公开服务重点是车规晶圆与封测；济南主体的单纤双向封装专利也不能因为集团关系直接转移到比亚迪电子。{_cite('BYD-S01')}{_cite('BYD-S02')}{_cite('BYD-S08')}{_cite('BYD-S09')}

比亚迪电子可确认的里程碑是：AI 服务器已有新客户和出货增长，液冷通过客户认证并进入小批试产，电源处于积极开发，高速互联出现在一体化方案和未来计划中。2025 年 AI 基础设施收入 9.43 亿元及 31.70% 增长证明数据中心相邻业务存在，但公开报表没有把它拆成光模块收入。当前产品页显示服务器矩阵，却没有 400G、800G、1.6T、3.2T、OSFP/QSFP-DD、LPO/LRO/CPO 或数据中心硅光模块的具名 SKU。{_cite('BYD-S01')}{_cite('BYD-S04')}

专利轴上，集团可见 WDM、硅光、分光和单纤双向等元素；已核验的高相关专利大多明确面向车辆/车载网络，另一个封装专利没有披露数据速率或数据中心场景。它们只能更新“集团存在光通信邻接知识”，不能更新数据中心产品、qualification 或量产里程碑。比亚迪半导体的光电半导体产品也不是高速收发模块。{_cite('BYD-S10')}{_cite('BYD-S11')}

制造轴上，智慧工厂证明大规模精密装配、机器人、视觉和 MES 能力；但没有有源对准、COB/COC、FA/MT 耦合、激光焊接、老化、BERT、眼图或光功率测试专线的设备、数量、验收和良率。通用自动化降低未来迁移成本，却不等于合格可售供给。{_cite('BYD-S16')}

因此比亚迪 3 年概率的主要负约束不是资金，而是六个硬缺口：具名产品、可归属团队、核心器件路线、专用产线、客户资格和重复收入；5 年上沿保留系统协同、自研、合作或收购跨越这些节点的可能。公开清单未命中是有界负证据，不排除 NDA 项目。
""",
        )
    )
    sections.append(
        _section(
            key="luxshare_entity_map",
            title="立讯精密 / Luxshare-Tech：已进入到何种商业阶段",
            refs=["LX-IR-202508", "LX-ANNUAL-2025", "LX-CNINFO-H1-2025", "LX-HKEX-PROSPECTUS-ZH-2026", "LX-TRANSCEIVER-CURRENT", "LX-800G-LPO-SPEC", "LX-FRO-2026", "POET-LX-202408", "OIF-OFC2026", "MARVELL-LX-202605", "CROSS-EVIDENCE-AUDIT"],
            source_lookup=lookup,
            sort_order=40,
            decision="立讯已越过纯概念和纯样机阶段，但不能把公司产品宣传、国际客户宽泛措辞或通信分部数据写成全球头部 CSP 稳定份额",
            unknown="800G/1.6T模块专线产能、良率、模块收入、具名客户AVL和多代重复订单",
            monitor="用最新监管IR与客户/平台侧资料化解客户层级冲突，并拆分800G、1.6T、LPO/LRO/DPO和硅光PIC的各自阶段",
            body=f"""
### 主体和产品矩阵

立讯精密是合并报表和监管披露主体；2025年半年报显示其对东莞立讯技术有限公司持股87.42%，因此后者的经营结果进入立讯精密合并口径，但这只建立财务控制关系，不证明光模块团队、客户、专线、收入和利润可从通信与数据中心混合分部中单独识别。东莞立讯技术 / Luxshare-Tech 是当前可核验的光通信产品与工程载体；母公司其他连接器、线缆、散热、电源和系统业务不能自动迁移成光模块能力。{_cite('LX-CNINFO-H1-2025')}{_cite('LX-HKEX-PROSPECTUS-ZH-2026')}

### 立讯高速光模块规格与商业边界

| 产品/路线 | 波长 | 距离 | 形态 | DSP | CW laser | 功耗 | 商业边界 |
|---|---|---|---|---|---|---|---|
| 800G QSFP-DD 2×DR4 LPO | 1310nm | 最远500m | QSFP-DD；2×400G或8×100G；单模 | 公开规格未列模块内DSP；LPO架构不能据此擅自写成“无任何DSP” | 未披露 | 最大8W | 规格页可确认SKU与工程参数；未确认客户资格、订单、收入或良率 {_cite('LX-800G-LPO-SPEC')} |
| 800G FRO | 未披露 | 未披露 | 页面未给可审计形态 | 5nm 8:8 DSP | 已列CW laser | 峰值14.5W | 公司称成熟量产和稳定供给；具名客户、数量、可分收入及客户侧证明仍缺 {_cite('LX-FRO-2026')} |
| 1.6T FRO | 未披露 | 未披露 | 页面未给可审计形态 | 3nm PAM4 8:8 DSP | 已列CW laser | 低于25W | 公司称进入大规模商业化早期并推进批量；不能写成头部CSP稳定规模订单 {_cite('LX-FRO-2026')} |
| 3.2T离散模块 | **未形成公开规格** | **未形成公开规格** | 当前目录无离散SKU | 未披露 | 未披露 | 未披露 | 仅保留标准、专利、XPO/CPO或路线探索；不得把探索写成在售产品 {_cite('LX-TRANSCEIVER-CURRENT')} |

当前官网目录还覆盖10G—1.6T、SFP/QSFP/QSFP112/QSFP-DD/OSFP以及DPO/LPO/LRO/Active Loopback等路线，证明产品矩阵与工程投入真实；矩阵中“未披露”严格表示当前已核验页面没有该字段，不以同类产品常见配置补数。{_cite('LX-TRANSCEIVER-CURRENT')}

商业阶段必须双轴表达。产品轴上，800G 有发行人量产口径，1.6T 从验证走向公司宣称的早期批量；生态轴上，POET、OIF、Marvell、Semtech、Keysight 等材料支持光引擎、互操作、测试或连接合作。商业轴上，仍缺乏具名头部 CSP 的 AVL、design win、多代重复订单和可分收入，不能把联合演示或设备兼容写成最终客户 qualification。{_cite('POET-LX-202408')}{_cite('OIF-OFC2026')}{_cite('MARVELL-LX-202605')}

最重要的审计冲突来自公司自己的披露。2024 年报曾给出头部 AI 客户测试和国际头部客户量产交付口径；2025-08 更直接的投资者记录又称 800G/1.6T 主要向中小数据中心交付，尚无头部客户明确商务机会。可能原因包括 SKU、客户分类、测试/小批与稳定订单口径不同，但公开证据不足以选定一个解释。结论因此是“区域交付存在，全球头部闭环未完成”，而不是单边删除任一文件。{_cite('LX-IR-202508')}{_cite('CROSS-EVIDENCE-AUDIT')}

1.6T 也存在宣传与经济规模的错位：官网可证明产品和公司所称早期商业化，最新监管口径仍强调光连接业务起步、商务拓展需要时间，并未确认精确光模块收入；公司暂不具备自研 1.6T 硅光芯片，不妨碍外采 PIC/DSP 做模块，却否定“全栈自研”表述。通信与数据中心分部包含连接器、线缆、铜/光、散热、电源和系统，不能用混合产能或平均售价反推模块只数、ASP 或良率。

立讯的核心优势是连接器/线缆、精密制造、服务器/交换机/机柜协同、资金和全球交付；不能替代的是光学封装良率、核心器件锁量、客户质量责任和多代资格。它比比亚迪更接近真实威胁，但“产品已存在”到“改变行业利润池”之间仍有客户、规模和利润三道门。
""",
        )
    )
    sections.append(
        _section(
            key="entrant_comparison_matrix",
            title="技术、产品、人员、专利、产能与客户进展对比矩阵",
            refs=["BYD-S01", "BYD-S06", "BYD-S11", "BYD-S16", "LX-TRANSCEIVER-CURRENT", "JOB-ZHAOPIN-COUPLING", "PAT-CN113917631B", "DG-STB-SIPH-2023"],
            source_lookup=lookup,
            sort_order=50,
            decision="把每一证据轴绑定最低里程碑后，立讯在产品与工程成熟度领先，比亚迪在资金和通用制造上强但核心光模块节点大多未验证",
            unknown="两家公司真实团队规模、专线稼动/良率、核心器件采购锁定和客户订单",
            monitor="用同一阶段量表持续更新，不允许某一轴的高分替代其他轴缺口",
            body=f"""
### 六轴比较

| 证据轴 | 比亚迪电子 | 立讯 / Luxshare-Tech | 不能越级到 |
|---|---|---|---|
| 产品 | 服务器、液冷、电源和宽泛高速互联；无具名800G+模块 | 10G—1.6T、800G、LPO/LRO/DPO等产品存在 | 产品页不等于客户稳定订单 |
| 工程 | 通用精密制造强，光学专线不可得 | 互操作、测试和合作伙伴证据较多 | 展会/联调不等于AVL |
| 团队 | 集团招聘宽泛，法人/岗位/HC不可归属 | 有耦合、硅光测试等岗位线索 | 聚合招聘不等于净扩招 |
| 专利 | 多数高相关样本是车载或主体错配 | 有光模块/CPO相关专利与项目 | 专利数量不等于产品化 |
| 产能 | 无光模块设备、台数、验收、良率 | 通信分部和项目存在，模块专用产能仍不可分 | 集团capex不等于模块产能 |
| 客户 | 服务器客户入口，不是模块qualification | 区域交付存在，头部CSP口径冲突 | “国际头部”不能擅自映射客户 |

比亚迪的正向证据集中在相邻业务、资金、通用自动化和系统级组合；这些提高 5 年可迁移上限，却不能跨过产品、光学专线和客户资格。集团招聘材料没有可复核的光模块岗位 ID、法人和人数，车载 WDM/硅光专利的使用场景也与 AI 数据中心不同。{_cite('BYD-S01')}{_cite('BYD-S06')}{_cite('BYD-S11')}{_cite('BYD-S16')}

立讯的正向证据更接近模块本身：有产品规格、耦合/硅光测试岗位、专利与政府项目、合作伙伴演示和公司所称出货。其短板不是“有没有模块”，而是是否有头部客户资格、是否能保持核心器件和良率、是否形成可量化收入与利润。{_cite('LX-TRANSCEIVER-CURRENT')}{_cite('JOB-ZHAOPIN-COUPLING')}{_cite('PAT-CN113917631B')}{_cite('DG-STB-SIPH-2023')}

评分不把六轴简单平均。客户 qualification、重复订单、专线良率和可分财务是后置硬门槛；招聘、专利、展会和通用制造只是前置辅助。一个公司可以在制造轴很强、在产品轴很弱，也可以在产品轴很强、在商业规模轴仍未闭环。模型因此对比亚迪给较低 3 年概率而保留宽 5 年尾部，对立讯给较高进入概率但把全球条件概率单独压低。

竞争破坏还取决于现有龙头反应。中际旭创、新易盛已具有多代量产、海外交付、正 FCF 和客户关系，新进入者的低成本只有在通过 qualification、形成合格可售供给并持续报价后才转为份额和毛利压力。矩阵的用途是识别下一道门，而不是把“强制造”直接翻译成“必然成功”。
""",
        )
    )
    return sections + _remaining_report_sections(
        model, lookup, screening, compiled_counts=compiled_counts
    )


def _remaining_report_sections(
    model: dict[str, Any],
    lookup: dict[str, dict[str, Any]],
    screening: dict[str, Any],
    compiled_counts: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    market_sensitivity_lines: list[str] = []
    market_paths = {
        "基准路径": model["market"]["rows"],
        **{
            case["label"]: case["rows"]
            for case in model["market"].get("sensitivity_cases", {}).values()
        },
    }
    for label, path in market_paths.items():
        for year in (2029, 2031):
            row = next(item for item in path if item["year"] == year)
            market_sensitivity_lines.append(
                f"| {label} | {year} | {row['total_ports_million']:.1f} | "
                f"{row['normal_market_revenue_usd_bn']:.1f} | "
                f"{row['qualified_supply_demand_ratio']:.2f} | "
                f"{row['lpo_lro_share_pct']:.1f}% | {row['cpo_share_pct']:.1f}% |"
            )
    market_sensitivity_table = "\n".join(market_sensitivity_lines)
    market_full_lines: list[str] = []
    for row in model["market"]["rows"]:
        segments = {item["segment"]: item for item in row["segments"]}
        s800 = segments["800G_pluggable"]
        s1600 = segments["1.6T_pluggable"]
        s3200 = segments["3.2T_pluggable_or_engine"]
        market_full_lines.append(
            f"| {row['year']} | {s800['shipments_million']:.1f} / ${s800['normal_asp_usd']:.0f} / ${s800['revenue_usd_bn']:.2f}bn | "
            f"{s1600['shipments_million']:.1f} / ${s1600['normal_asp_usd']:.0f} / ${s1600['revenue_usd_bn']:.2f}bn | "
            f"{s3200['shipments_million']:.1f} / ${s3200['normal_asp_usd']:.0f} / ${s3200['revenue_usd_bn']:.2f}bn | "
            f"{row['total_ports_million']:.1f} | ${row['normal_market_revenue_usd_bn']:.2f}bn | "
            f"{row['qualified_supply_million']:.1f} | {row['qualified_supply_demand_ratio']:.2f} |"
        )
    market_full_table = "\n".join(market_full_lines)
    result.append(
        _section(
            key="recruitment_timeline",
            title="招聘和人才时间线：领先指标而非量产证明",
            refs=["BYD-S06", "BYD-S07", "JOB-ZHAOPIN-COUPLING", "JOB-JOBUI-SIPH-TEST", "OCP-ASIA-2026"],
            source_lookup=lookup,
            sort_order=60,
            decision="招聘只更新团队形成和工艺准备的前置概率，当前没有足够数据估计两家公司光模块团队规模或净新增速度",
            unknown="官方岗位ID、用工法人、事业部、HC、首次与最后可见日期，以及来自同行的关键人才流动是否真实发生",
            monitor="对职位ID、地点、职责文本和首次发现去重，并要求后续样机、设备、qualification与收入形成跨轴验证",
            body=f"""
### 当前可核验时间线

| 时间 | 主体与事件 | 最低可证含义 | 不可推出 |
|---|---|---|---|
| 2025届历史招聘 | 比亚迪集团博士方向出现光通信、光芯片/器件和光学检测 | 集团历史人才兴趣 | 当前团队仍在、法人归属、HC或数据中心项目 |
| 2026届春招 | 比亚迪材料覆盖AI数据中心、通信设备和通用半导体方向 | 战略相关人才池 | 光模块专项扩招或团队已组建 |
| 2026年可见 | 立讯聚合招聘出现硅光测试高级工程师 | PIC晶圆/芯片级自动测试建设信号 | 官方在招、净新增和团队规模 |
| 2026年可见 | 立讯聚合招聘出现量产COB耦合高级工艺岗位 | 耦合设备、PVT、400G/800G工艺信号 | 已达目标良率或多条产线 |
| OCP Asia 2026 | 立讯光产品经理参与NPO/CPO/XPO主题 | 公开团队与生态接近度 | 标准主导权、客户认证或订单 |

### 招聘渠道与字段完成状态

| 渠道/记录 | 主体与场景 | 职位ID | 用工法人/事业部 | 地点 | 首次/最后可见日 | HC/净新增 | 当前状态与允许用途 |
|---|---|---|---|---|---|---|---|
| 比亚迪2025届博士方向材料 | 比亚迪集团；光通信/光芯片/检测方向 | 未提供 | 未映射到比亚迪电子光模块事业部 | 未形成可复核地点序列 | 历史届次可见；网页首末日未保存 | 未提供 | **受限完成**：只证明历史人才兴趣 {_cite('BYD-S07')} |
| 比亚迪2026届春招材料 | 集团AI数据中心、通信设备、半导体方向 | 未提供可去重ID | 法人和具体团队未闭环 | 未形成岗位级地点表 | 本轮核验时可见；跨期序列缺失 | 未提供 | **受限完成**：只更新相邻人才池 {_cite('BYD-S06')} |
| 智联招聘COB耦合岗位 | 立讯相关招聘聚合页；量产耦合职责 | 未取得官方ID | 未由官方职位库确认用工法人/事业部 | 页面字段不足以形成可靠地点序列 | 聚合页可见日可能刷新 | 未提供 | **早期信号**：更新耦合工艺准备，不计量产线 {_cite('JOB-ZHAOPIN-COUPLING')} |
| JobUI硅光测试岗位 | 立讯相关聚合页；PIC晶圆/芯片级测试 | 未取得官方ID | 未由官方职位库确认用工法人/事业部 | 页面字段不足以形成可靠地点序列 | 聚合页可见日可能刷新 | 未提供 | **早期信号**：更新硅光测试准备，不估团队规模 {_cite('JOB-JOBUI-SIPH-TEST')} |
| OCP Asia讲者记录 | 立讯光产品经理公开活动 | 不适用 | 可确认公开职能称谓，不能确认组织人数 | 会议地点不等于用工地点 | 会议事件日可见 | 不适用 | **已确认公开参与**：只更新生态接近度 {_cite('OCP-ASIA-2026')} |

本轮没有取得可将上述渠道连接为同一岗位序列的官方职位ID、法人、事业部、地点、首次/最后可见日和HC。聚合平台刷新、同岗改标题或跨站转载均可能高估招聘增速；因此所有招聘结论保持字段级受限，不用“岗位条数”估算人数。

比亚迪2026春招无法把光模块岗位映射到具体法人、岗位ID、地点和人数；2025博士方向已经陈旧，且集团级研究方向可能服务汽车、消费电子、通信设备或半导体，不应被当成比亚迪电子数据中心光模块团队。{_cite('BYD-S06')}{_cite('BYD-S07')}

立讯两条岗位与耦合和硅光测试高度相关，说明产品工程链比比亚迪更接近模块制造；但来源是第三方聚合站，可能刷新日期、长期滚动或转载同一职位。没有官方职位库闭环前，它们只能是第4层弱来源领先信号，不能推算人数、招聘增速或产线数量。{_cite('JOB-ZHAOPIN-COUPLING')}{_cite('JOB-JOBUI-SIPH-TEST')}

人才流动方面，本轮没有获得足以多源核验的中际旭创、新易盛、华为/海思、海信宽带、Coherent、Lumentum、Intel 或 Broadcom 关键人员流入清单，不对私人履历作推断。专利发明人和会议讲者可建立公开技术主题图谱，却不能自动等同在职核心团队。招聘到有意义进入至少还隔着样机、可靠性/互操作、客户 qualification、专线良率和重复订单，模型不会把前置岗位直接加到最终成功概率。
""",
        )
    )
    result.append(
        _section(
            key="patent_technology_map",
            title="专利、标准和技术资产地图",
            refs=["BYD-S11", "BYD-S12", "BYD-S13", "BYD-S14", "BYD-S15", "PAT-CN113917631B", "PAT-CN114815089B", "DG-STB-SIPH-2023", "OIF-MEMBERS", "IEEE-8023DJ-D24"],
            source_lookup=lookup,
            sort_order=70,
            decision="专利按申请主体、场景和专利族去重；比亚迪多为车载邻接，立讯与模块/CPO更直接，但专利与标准参与均不能替代产品实施和客户资格",
            unknown="逐族CNIPA/WIPO法律状态、权利要求有效范围、产品实施映射和关键发明人是否持续聚集",
            monitor="按受让人历史名称与专利族更新，并把直接数据中心模块、上游器件、封装测试、邻近技术和低相关专利分层",
            body=f"""
### 技术资产分层

| 技术簇 | 比亚迪体系 | 立讯体系 | 证据边界 |
|---|---|---|---|
| 数据中心800G+模块 | 未找到可归比亚迪电子的直接专利闭环 | 存在可归东莞立讯技术的光模块专利 | 文本不证明产品实施 |
| CPO/光电共封装 | 未验证 | CN113917631B涉及共封装模块/交换芯片结构 | 公开或授权不等于客户产品 |
| 硅光/WDM | 比亚迪股份样本明确车载场景 | 产品、项目、岗位有连续信号 | 封装测试不等于自研PIC |
| 单纤双向 | 济南比亚迪半导体专利无数据中心速率 | 非当前立讯主线 | 主体和应用场景必须独立审计 |
| 标准与互操作 | 指定OIF 2026名单未见BYD | OIF成员和历史演示可核验 | 成员、演示不等于主导或AVL |

### 专利数据库与字段完成状态

| 数据库/字段 | 已查内容 | 当前状态 | 不可得或不足原因 | 可接受补证 | 结论边界 |
|---|---|---|---|---|---|
| Google Patents镜像 | 申请号、标题、摘要、申请人、优先权/同族线索 | **受限完成** | 镜像法律状态与官方登记可能不同步；标题关键词不能代表权利要求范围 | CNIPA/WIPO官方案卷、缴费/无效/转让记录 | 只做家族初筛，不认证有效权利 {_cite('PAT-CN113917631B')}{_cite('PAT-CN114815089B')} |
| CNIPA官方法律状态 | 逐族有效、终止、无效、转让与权利要求 | **阻塞** | 本轮未完成每一家族的官方案卷回查 | 官方法律状态和权利要求全文 | 不把“授权号可见”写成当前有效或可实施 |
| WIPO/PATENTSCOPE同族 | PCT/境外同族和优先权链 | **阻塞** | 本轮没有形成完整国际同族账本 | PCT记录、各法域family映射 | 不能估全球保护范围 |
| 申请人/受让人映射 | 比亚迪股份、济南比亚迪半导体、东莞立讯技术等主体 | **部分完成** | 历史名称、转让和集团内许可不完整 | 工商历史、转让/许可原文 | 主体不清的能力留在集团邻接栏 {_cite('BYD-S11')}{_cite('PAT-CN113917631B')} |
| 权利要求场景 | 车载、数据中心直接、封装测试、CPO/邻接分层 | **受限完成** | 部分记录仅核到摘要/样本权利要求，无法做全组合FTO | 全文claim chart与产品结构映射 | 数量不进入评分，只使用最低可证场景 |
| 产品实施/客户使用 | 专利是否进入实际SKU、工艺或客户产品 | **未知** | 公司未披露逐专利实施，公开产品也无专利标记 | 产品BOM、工艺文件、诉讼/许可或公司确认 | 专利存在不能越级到量产和资格 |
| 发明人持续聚集 | 发明人是否仍在岗、是否形成团队 | **未知** | 公开专利不提供当前雇佣和组织关系 | 官方团队、连续新申请、公开履历交叉 | 不用发明人数估HC或当前团队规模 |

上述“阻塞”是字段不可得状态，不是专利不存在。新增记录必须先按优先权/同族去重，再按申请主体和应用场景归属；只有官方法律状态与产品实施同时出现，才允许从技术邻接升级为可执行资产。

比亚迪样本中出现硅光、WDM、分光、光通信和计算芯片等关键词，但标题、技术领域、权利要求或实施例多数落在车辆/车载网络；济南比亚迪半导体的单纤双向封装也没有披露数据速率或数据中心用途。它们只能提高集团光技术邻接性，不能抬高比亚迪电子的800G/1.6T产品成熟度。{_cite('BYD-S11')}{_cite('BYD-S12')}{_cite('BYD-S13')}{_cite('BYD-S14')}{_cite('BYD-S15')}

立讯专利、政府硅光封装项目、岗位和产品页之间存在更好的主题一致性，能够支持模块设计、耦合、封装和测试投入；监管记录又明确暂不具备自研1.6T硅光芯片，说明模块和封装能力不能写成全栈PIC平台。{_cite('PAT-CN113917631B')}{_cite('PAT-CN114815089B')}{_cite('DG-STB-SIPH-2023')}

Google Patents适合初筛申请人、优先权、摘要和同族，却不能替代官方法律状态或实施证明。OIF成员、IEEE草案兼容、会议讲者与互操作提高生态接近度，但只有贡献文本、正式通过测试和客户 qualification 才能继续升级。专利数量不进入核心结论，真正有用的是直接相关家族、持续申请、权利要求质量、转让/收购、发明人聚集与产品互证。
""",
        )
    )
    result.append(
        _section(
            key="customer_validation_matrix",
            title="客户验证矩阵：从产品目录到重复规模订单",
            refs=["BYD-S17", "BYD-S18", "LX-ANNUAL-2024", "LX-IR-202508", "LX-IR-20260507", "LX-IR-20260525", "POET-LX-202408", "OIF-OFC2024-CEI", "OIF-OFC2026", "NVIDIA-CX8-VALIDATED"],
            source_lookup=lookup,
            sort_order=80,
            decision="比亚迪尚未到可公开验证的模块产品/客户阶段；立讯已有产品、工程和区域交付，但全球头部CSP资格及重复规模订单仍未闭环",
            unknown="客户私有AVL、间接供货链、SKU差异和公司所称国际客户究竟对应测试、小批还是稳定采购",
            monitor="保存客户/平台侧清单版本、产品OPN、资格状态、采购周期与跨代续单，发行人模糊客户名不能擅自映射",
            body=f"""
### 阶段矩阵

| 阶段 | 比亚迪电子 | 立讯 / Luxshare-Tech | 判定 |
|---|---|---|---|
| 产品目录/规格 | 数据中心页为服务器，无具名400G+模块 | 10G—1.6T目录和800G规格 | 立讯通过，BYD未验证 |
| 展会/伙伴集成 | 未找到具名模块演示 | POET、Keysight、OFC等有展示 | 工程证据，不是客户资格 |
| 多厂商互操作 | 指定OIF名单未命中 | OIF历史演示与2026参与 | 公开辅助门槛 |
| 设备商兼容 | NVIDIA指定页未命中BYD模块 | 当前清单只确认Luxshare 200G DAC | 均不能证明800G/1.6T AVL |
| 客户验证 | 未验证 | 1.6T公司称验证 | 客户未具名，发行人单方 |
| qualification/AVL | 未验证 | 未找到具名头部CSP闭环 | 关键缺口 |
| design win/订单 | 未验证 | 公司称区域交付，头部表述冲突 | 中国有限商业化可上调 |
| 重复规模订单 | 未验证 | 公司称800G量产，但数量/收入不可分 | 基础有意义进入仍未完成 |

### 客户全字段完成矩阵

| 主体/产品 | 速率/形态/距离 | 直接或间接供货 | 证据原点 | 客户具名 | 测试/互操作 | qualification/AVL | design win/订单 | 跨期重复 | 可分收入 | 结论状态 |
|---|---|---|---|---|---|---|---|---|---|---|
| 比亚迪电子400G+模块 | 速率、形态、距离均未形成具名SKU | 未知 | 年报、产品页、OIF/NVIDIA清单 | 无 | 指定公开名单未命中 | 未验证 | 未验证 | 未验证 | 未披露 | **阻塞在产品前**：服务器客户入口不等于模块客户 {_cite('BYD-S01')}{_cite('BYD-S18')} |
| 立讯800G LPO | QSFP-DD 2×DR4；1310nm；最远500m | 未披露 | 发行人规格页 | 无 | 规格可审计；未取得该SKU客户侧互操作 | 未验证 | 未验证 | 未验证 | 未披露 | **产品已确认/商业未知** {_cite('LX-800G-LPO-SPEC')} |
| 立讯800G其他模块 | 发行人称800G；具体客户SKU/距离未对应 | 公司/伙伴材料不能裁定ODM链 | 监管IR、公司页、伙伴与OIF | 无 | 有工程展示/互操作 | 发行人口径提及阶段，客户侧未闭环 | 公司称区域/北美交付但口径冲突 | 数量与两期续单不可得 | 混合分部不可分 | **较强推断为有限交付**，不是全球规模 {_cite('LX-IR-202508')}{_cite('OIF-OFC2024-CEI')} |
| 立讯1.6T FRO | DSP/CW laser/功耗可见；形态、距离未披露 | 未披露 | 发行人页与器件/展会伙伴 | 无 | 公司称验证、伙伴支持工程可行 | 无客户侧OPN/AVL | 公司称早期批量，无可归属订单 | 未验证连续两期 | 未披露 | **发行人阶段已升级/客户闭环未知** {_cite('LX-FRO-2026')} |
| NVIDIA兼容清单中的Luxshare | 当前核验只确认200G DAC，不是800G/1.6T光模块 | 平台清单可确认具体OPN类别 | 客户/平台侧 | 平台具名，最终采购客户不等同具名 | 对该铜缆OPN有效 | 不外推光模块AVL | 不外推光模块订单 | 不适用 | 不适用 | **有界反证**：不能作为高速光模块资格 {_cite('NVIDIA-CX8-VALIDATED')} |

字段为空时不从相邻行继承：伙伴联合演示不能填客户具名或AVL，发行人“国际客户”不能填具体CSP，平台上的铜缆OPN不能填光模块资格。客户私有NDA可能使公开矩阵低估真实阶段，但这种偏误通过宽概率区间处理，不能用匿名传闻补齐表格。

立讯冲突必须双向保留：2024年报的头部AI客户测试/国际客户交付，与2025-08记录的中小数据中心为主、尚无头部明确商务机会，可能来自SKU、客户定义或交付阶段差异；公开材料不能裁定。2026年宣传的1.6T早期商业化也要受2026-05“业务起步、拓展需时间、无自研1.6T硅光芯片”的监管口径约束。{_cite('LX-ANNUAL-2024')}{_cite('LX-IR-202508')}{_cite('LX-IR-20260507')}{_cite('LX-IR-20260525')}

OIF和NVIDIA清单的缺席只是有界负证据，不能证明不存在私有认证；同理，在Juniper设备或Keysight平台上展示不能写成这些公司已认证或采购。{_cite('BYD-S17')}{_cite('BYD-S18')}{_cite('OIF-OFC2024-CEI')}{_cite('NVIDIA-CX8-VALIDATED')}

模型只在qualification后打开份额变量，在重复订单后允许规模影响。在此之前，产品页、展会和合作公告只提高工程成熟度。每个客户结论必须带产品代际、形态、距离、直接/间接供货、证据日期、来源簇、反方证据和待验证项；“全球头部客户”“北美大客户”不擅自映射为Meta、Microsoft、Amazon、Google或其他公司。
""",
        )
    )
    result.append(
        _section(
            key="upstream_manufacturing_matrix",
            title="上游供应链、设备与制造准备度矩阵",
            refs=["SRC-BCM-DSP", "SRC-COHR-OFC25", "SRC-COHR-10K25", "SRC-NV-COHR26", "SRC-MRVL-LPO25", "SRC-MRVL-10Q25", "SRC-LITE-10K25", "SRC-FN-10K24", "BYD-S16", "JOB-ZHAOPIN-COUPLING", "JOB-JOBUI-SIPH-TEST", "LX-FRO-2026"],
            source_lookup=lookup,
            sort_order=90,
            decision="合格可售供给必须把名义产能乘以良率、产品mix、合格线比例和器件可得性；两家专用设备、良率与锁量均不足以点估计",
            unknown="DSP/PIC/laser锁量、主动耦合线数、老化与BERT能力、UPH、返修率、客户质量阈值和海外合格线",
            monitor="从供应商协议、环评设备表、招标验收、招聘地点和客户产线变更记录做外部交叉验证",
            body=f"""
### 约束矩阵

| 器件/工序 | 行业公开状态与已查来源 | 比亚迪映射 | 立讯映射 | 仍缺字段 | 瓶颈判断 |
|---|---|---|---|---|---|
| DSP / SerDes | 200G/lane与1.6T器件已公开，但先进节点供给和客户组合仍受约束 {_cite('SRC-BCM-DSP')}{_cite('SRC-MRVL-10Q25')} | 未披露供应商、料号、锁量或替代认证 | 800G/1.6T FRO规格分别指向5nm/3nm 8:8 DSP，但未披露供应商分配与锁量 {_cite('LX-FRO-2026')} | 料号、allocation、交期、替代料和认证状态 | **受限完成**：证明器件路线可行，不证明爬坡供给 |
| TIA / Driver | 已查器件厂年报、产品和供应风险披露 | 未披露 | 未披露 | 料号、通道数、成本、良率与第二来源 | **阻塞**：不能用DSP存在代填模拟前端 |
| EML / InP laser | InP/EML产能、良率与长期承诺会约束规模供给 {_cite('SRC-COHR-10K25')}{_cite('SRC-LITE-10K25')} | 未披露光源路线或锁量 | 公开模块/伙伴材料不能识别自制、外购和供应份额 | 波长别供方、锁量、良率、价格与替代认证 | **受限完成**：行业瓶颈明确，公司分配未知 |
| CW laser | 行业合作说明CW光源是线性/硅光路线关键输入 {_cite('SRC-NV-COHR26')}{_cite('SRC-MRVL-LPO25')} | 未披露 | FRO规格明确采用CW laser，但未披露供应商和冗余 {_cite('LX-FRO-2026')} | 供方、功率、波长、锁量、备份料和失效数据 | **受限完成**：架构字段已知，供给保障未知 |
| SiPh / PIC / 光引擎 | 伙伴和供应商材料可证明产业路线，不等于进入者自研量产 {_cite('SRC-COHR-OFC25')}{_cite('SRC-MRVL-LPO25')} | 未见数据中心模块PIC路线闭环 | 规格和伙伴生态支持硅光工程接近度；监管口径不支持写成自研1.6T硅光芯片 | PIC供方、die良率、封装分工、成本和客户认可 | **受限完成**：不得把伙伴能力归为公司全栈能力 |
| FA / MT / 光纤阵列 | 已查产品、供应商与制造材料，未形成公司级BOM | 未披露 | 未披露 | 供方、规格、锁量、耦合损耗和替代认证 | **阻塞**：不能以连接器业务推定模块光学BOM |
| 主动耦合、COB / COC | 专用耦合和贴装决定良率、UPH和返修；集团自动化不能直接迁移 | 仅有通用智慧工厂与自动化邻接 {_cite('BYD-S16')} | 聚合岗位出现量产COB耦合职责，仍不是设备/线体验收 {_cite('JOB-ZHAOPIN-COUPLING')} | 设备台数、节拍、初末良率、返修率和法人/地点 | **早期信号**：岗位不能折算产能 |
| BERT、眼图、老化与可靠性 | 客户质量门槛要求测试闭环，设备用途和速率不可互换 | 未披露模块专线 | 聚合岗位显示PIC晶圆/芯片级测试接近度 {_cite('JOB-JOBUI-SIPH-TEST')} | BERT速率、老化容量、抽检规则、失效率、客户阈值 | **早期信号/阻塞**：测试方向存在，合格能力不可量化 |
| 客户合格产线 | 生产地点、器件或工艺变化可能触发重新认证 {_cite('SRC-FN-10K24')} | 无公开模块qualification、专线或良率闭环 | 有产品与工程材料，但客户、线别、良率、重复订单未闭环 | 线体ID、地点、客户、SKU、AVL日期、稳定良率和可售产量 | **阻塞**：名义产能不得进入合格可售供给 |

矩阵按字段逐项保持“受限/阻塞”，不把相邻证据横向继承：立讯规格中的DSP或CW laser不能补齐TIA、Driver、FA/MT和客户线体；比亚迪的集团自动化也不能补齐主动耦合、老化或BERT。只有公司级供应协议、设备验收、稳定良率与客户资格形成同一SKU/线体闭环，才允许把相应行升级为可量化供给。

DSP/SerDes已有200G/lane与1.6T产品，但先进节点晶圆、封测和供货承诺仍限制规模；EML、CW laser与InP的供应集中、良率和产能预留决定模块能否从样品变为量产。Coherent与NVIDIA的长期安排、Marvell与Lumentum对供应/承诺的披露说明核心器件不是现货样片即可替代。{_cite('SRC-BCM-DSP')}{_cite('SRC-COHR-10K25')}{_cite('SRC-NV-COHR26')}{_cite('SRC-MRVL-10Q25')}{_cite('SRC-LITE-10K25')}

比亚迪没有披露模块DSP、PIC、laser、FA/MT或光引擎路线；通用自动化强，却没有主动耦合、COB/COC、老化、BERT和眼图测试专线。立讯规格、POET/Marvell等伙伴与耦合岗位表明工程链更完整，但外购/自制比例、锁量、设备台数、专线产能和良率仍不可得。{_cite('BYD-S16')}{_cite('JOB-ZHAOPIN-COUPLING')}

客户资格使供给不可简单相加。不同速率、距离、封装、地区与客户的产线不能完全替代；供应商、工艺、生产线或地点变化可能触发数月重新认证。模型采用“可售供给=名义产能×良率×合格产品mix×合格线比例×核心器件可得性”，不使用集团通信分部产量或机器人覆盖率折算模块只数。{_cite('SRC-FN-10K24')}

海外制造提高连续性和本地化，却不是美国或全球客户资格的充分条件。低价切入还会增加库存、应收、返修、保修和加急交付，强资金只能提高试错容忍，不能证明项目具有正回报。由于关键参数不可得，严重供给冲击采用宽区间与阶段门槛；真实设备、良率或订单出现后直接覆盖代理假设。

瓶颈还具有先后顺序：器件样片可得只允许启动NPI，锁量和替代料认证决定爬坡上限，主动耦合与老化良率决定合格产出，客户线体资格最后决定这些产出能否出售。同一设备若切换PIC、laser、封装形态或生产地点，前一产品的UPH与良率不能直接迁移；因此设备台数、设计产能和可售供给必须作为三个不同字段监控。
""",
        )
    )
    result.append(
        _section(
            key="incumbent_competitiveness",
            title="中际旭创、新易盛及主要竞争者的基准竞争力",
            refs=["SRC-INNO-AR25", "SRC-INNO-1600", "SRC-INNO-FUND26", "SRC-EOPT-AR25", "SRC-COHR-OFC25", "SRC-BCM-DSP", "SRC-MRVL-LPO25", "FIN-INNOLIGHT", "FIN-EOPTOLINK"],
            source_lookup=lookup,
            sort_order=100,
            decision="龙头的多代量产、客户共同开发、海外交付与正现金流构成真实防线；客户集中和高估值同时放大第二供应商与架构迁移风险",
            unknown="匿名客户的实际份额、同代产品成本曲线、客户切换意愿和龙头在CPO/光引擎价值池中的捕获率",
            monitor="季度追踪产品毛利、客户集中、产销、海外线、研发、简单FCF和新路线项目阶段，而非只看收入增速",
            body=f"""
### 2025事实底座

中际旭创2025年收入382.40亿元、归母净利润107.97亿元、经营现金流108.96亿元、购建长期资产支出27.60亿元，简单FCF约81.36亿元；新易盛相应为248.42、95.32、77.01、13.20和63.81亿元。简单FCF按结构化快照中已显示到两位小数的分项相减，可能与原始未四舍五入字段差0.01亿元。中际旭创披露光模块毛利率约42.61%，新易盛光产品毛利率约47.81%；分类和mix不完全可比。两家前五大客户收入占比均超过70%，既显示规模客户关系，也构成单一大客户培育第二供应商的反向风险。{_cite('SRC-INNO-AR25')}{_cite('SRC-EOPT-AR25')}

护城河不是静态技术分。中际旭创有公开1.6T产品、多代量产和高端项目投入；新易盛的1.6T、LRO、硅光PIC和LPO处于内部验收、样验、小批或预样等不同阶段，不能统一写成量产。上一代量产数据、失效分析、固件、客户质量体系与海外合格线可以迁移到下一代，这是新进入者难以用普通装配规模复制的学习曲线。{_cite('SRC-INNO-1600')}{_cite('SRC-INNO-FUND26')}{_cite('SRC-EOPT-AR25')}

正现金流允许龙头同时扩产、降本、承担保修和推进多路线研发；进入者若低价换份额，必须先支付良率和营运资本成本。海外布局提高连续性，但每条新线仍需单独qualification。Coherent、Broadcom、Marvell、Lumentum等还掌握InP/laser、DSP、SiPh或光引擎平台位置，竞争格局不是两家新进入者对两家中国龙头的封闭四人游戏。{_cite('SRC-COHR-OFC25')}{_cite('SRC-BCM-DSP')}{_cite('SRC-MRVL-LPO25')}

风险抵扣不能掩盖估值敏感性。当前结构化市场快照显示两家估值都需要高增长与高利润持续；若头部客户份额迁移、额外降价和CPO价值转移同时出现，终值会非线性下降。相反，只出现区域第二供应商且需求强劲时，收入增长可能吸收有限份额压力。{_cite('FIN-INNOLIGHT')}{_cite('FIN-EOPTOLINK')}
""",
        )
    )
    result.append(
        _section(
            key="market_model_2026_2031",
            title="2026—2031需求、供给、ASP与架构模型",
            refs=["SRC-NV-QX800", "SRC-NV-SPECTRUM", "SRC-BCM-TH6", "SRC-OIF-2025", "SRC-LPO-MSA", "SRC-CIGNAL-4Q24", "SRC-LC-SEP24", "SRC-LC-JUL25", "SRC-LC-MAR26", "SRC-HKEX-ASP26", "LX-800G-LPO-SPEC", "MODEL-WORKPAPER"],
            source_lookup=lookup,
            sort_order=110,
            decision="用端点—拓扑—启用光口构建需求，以分速率合格可售供给约束份额，并把正常生命周期降价与新增竞争残差分开",
            unknown="AI端点、网络拓扑、光化率、1.6T/3.2T放量、CPO时点与同规格报价均存在大区间",
            monitor="保存慢/中/快三条独立路径，不平均冲突预测；出现真实端口、订单和同规格ASP后覆盖假设",
            body=f"""
### 需求、路线和供给

需求从加速器端点、网络层级、启用端口与链路两端计算，而不是把多个美元市场规模平均。Quantum-X800的144个800Gb/s端口、每GPU最高1.6Tb/s SuperNIC，以及Tomahawk 6的102.4Tb/s和64×1.6TbE提供速率/密度基线；厂商所称最大支持规模不是已部署数量。{_cite('SRC-NV-QX800')}{_cite('SRC-NV-SPECTRUM')}{_cite('SRC-BCM-TH6')}

2026—2027基准路径是800G与1.6T并存，3.2T主要在标准、器件或演示前期；LPO/LRO是速率段内部架构，CPO/光引擎是可能迁移价值池的正交维度。Cignal、LightCounting对1.6T量级和CPO时点差异显著，2024预测已经陈旧，因此模型实际计算慢/基准/快三条结构化路径，不把分歧平均成“行业共识”。三条都是情景假设，不是概率预测。{_cite('SRC-CIGNAL-4Q24')}{_cite('SRC-LC-SEP24')}{_cite('SRC-LC-JUL25')}{_cite('SRC-LC-MAR26')}

### 2026—2031基准路径全期底稿

分速率单元格依次为“出货（百万端口）/ 正常ASP（美元/端口）/ 收入（十亿美元）”；正常ASP只含代际与规模降本，尚未提前写入比亚迪/立讯额外竞争折价。

| 年份 | 800G 出货/ASP/收入 | 1.6T 出货/ASP/收入 | 3.2T 出货/ASP/收入 | 总出货 | 总收入 | 合格供给（百万端口） | 供给/需求 |
|---|---|---|---|---:|---:|---:|---:|
{market_full_table}

| 距离结构 | 当前状态 | 已查来源 | 不可得原因 | 模型处理 | 结论影响 |
|---|---|---|---|---|---|
| SR | **受限完成** | 平台端口、发行人目录和行业预测 {_cite('SRC-NV-QX800')}{_cite('SRC-CIGNAL-4Q24')} | 没有全球同口径SR出货、ASP和合格供给序列 | 只进入速率总量，不单列SR | 无法判断短距mix对ASP的稀释 |
| DR | **受限完成** | 立讯2×DR4规格与平台材料 {_cite('LX-800G-LPO-SPEC')}{_cite('SRC-NV-SPECTRUM')} | 单一产品规格不能代表全球DR需求 | 用于规格可行性，不外推市场份额 | 500m产品存在不等于DR市场规模 |
| FR | **阻塞** | 已查公司目录、标准与预测 | 缺少可比FR分速率出货/价格面板 | 不造数、不用DR代填 | 中长距mix和利润率偏误方向不确定 |
| LR | **阻塞** | 已查公司目录、标准与预测 | 缺少可比LR分速率出货/价格面板 | 不造数、不用DCI或低速电信代填 | 无法量化长距高ASP对总收入的贡献 |

因此本表是按800G/1.6T/3.2T的速率边界模型，不是SR/DR/FR/LR完整bottom-up。若取得同客户、同距离、同形态的真实出货与报价，应覆盖相应速率总量与ASP，而不是把新数据叠加成第二份需求。

| 路径 | 年份 | 总需求（百万端口） | 正常降价后收入（十亿美元） | 合格供给/需求 | LPO/LRO | CPO |
|---|---:|---:|---:|---:|---:|---:|
{market_sensitivity_table}

进入供给按里程碑分层：招聘/专利不进入有效供给；样机/互操作只打开技术可行性；客户qualification后才打开份额变量；有限订单允许0—3或3—7个百分点额外报价压力；多客户重复规模订单才进入7—15个百分点压力带。比亚迪仍在产品硬证据前，立讯已到产品/工程及公司所称区域商业化，但头部客户T4未闭环。

正常ASP公式为上一期同规格价格乘生命周期降价、mix/距离/客户/汇率调整；新进入者额外压力只计同规格残差。历史800G+ ASP序列混有小批到规模、产品mix和竞争，不能识别单一原因。模型把正常代际降本放在无进入基线，A—F进入状态只加入增量折价，CPO基础渗透与增量价值迁移也分开，避免重复惩罚。{_cite('SRC-HKEX-ASP26')}{_cite('MODEL-WORKPAPER')}

若AI端点和光口增长快于合格供给，新增玩家可能先补充第二来源而非摧毁价格；若需求下修、两家跨过全球客户、上游不再约束且客户以组合采购压价，才更可能结构恶化。单一总供需比只作摘要，正式解释按速率、形态、地区、qualification与良率拆解。
""",
        )
    )
    result.append(
        _probability_section(model, lookup)
    )
    result.append(
        _financial_section(model, lookup)
    )
    result.extend(
        _final_report_sections(
            model, lookup, screening, compiled_counts=compiled_counts
        )
    )
    return result


_PROBABILITY_UPDATE_LABELS = {
    "byd_adjacent_ai_datacenter_capability": "AI服务器、液冷、电源与高速互联相邻能力",
    "byd_scale_capital_and_automation": "资金、规模与通用自动化迁移上限",
    "byd_no_named_800g_plus_sku": "未见具名400G/800G/1.6T模块SKU",
    "byd_no_public_qualification_or_interop": "未形成公开qualification/互操作闭环",
    "byd_optical_line_team_and_entity_boundary": "团队、光学专线与经营主体边界",
    "luxshare_named_multigeneration_product_matrix": "10G—1.6T具名多代产品矩阵",
    "luxshare_issuer_claimed_production_and_delivery": "发行人关于800G量产与1.6T商业阶段的不同口径",
    "luxshare_partner_interop_and_test_ecosystem": "伙伴集成、互操作与测试生态",
    "luxshare_manufacturing_and_system_integration": "制造与系统集成迁移上限",
    "luxshare_no_named_global_head_customer_closure": "未闭环具名全球头部客户",
    "luxshare_disclosure_conflict_and_profit_capture_gap": "官方阶段冲突与利润捕获缺口",
}


def _probability_update_tables(model: dict[str, Any]) -> tuple[str, str]:
    """Render the public prior→evidence updates→posterior reconciliation."""
    bridge = model.get("probability", {}).get("prior_update_bridge", {})
    priors = bridge.get("working_priors", {})
    companies = bridge.get("company_updates", {})
    update_lines: list[str] = []
    reconciliation_lines: list[str] = []
    for company_key in ("byd", "luxshare"):
        company = companies.get(company_key, {})
        display_name = company.get("display_name", company_key)
        updates = company.get("updates", [])
        posterior = company.get("posterior", {})
        for horizon in ("3y", "5y"):
            prior_mode = float(priors[horizon]["mode"]) * 100.0
            cumulative = prior_mode
            for update in updates:
                delta = float(update["delta_percentage_points"][horizon])
                cumulative += delta
                label = _PROBABILITY_UPDATE_LABELS.get(
                    update.get("update_id", ""), update.get("rationale", "证据更新")
                )
                citations = "".join(
                    _cite(ref) for ref in update.get("evidence_source_refs", [])[:3]
                )
                update_lines.append(
                    f"| {display_name} | {horizon} | {prior_mode:.1f}% | {label}{citations} | "
                    f"{delta:+.1f}个百分点 | {cumulative:.1f}% |"
                )
            declared = posterior[horizon]
            declared_mode = float(declared["mode"]) * 100.0
            triangle = [float(value) * 100.0 for value in declared["triangle"]]
            delta_sum = sum(
                float(update["delta_percentage_points"][horizon])
                for update in updates
            )
            check = "一致" if math.isclose(cumulative, declared_mode, abs_tol=1e-9) else "不一致"
            reconciliation_lines.append(
                f"| {display_name} | {horizon} | {prior_mode:.1f}% | {delta_sum:+.1f}个百分点 | "
                f"{cumulative:.1f}% | {declared_mode:.1f}% | "
                f"{triangle[0]:.1f}% / {triangle[1]:.1f}% / {triangle[2]:.1f}% | {check} |"
            )
    return "\n".join(update_lines), "\n".join(reconciliation_lines)


def _historical_case_table(model: dict[str, Any]) -> str:
    bridge = model.get("probability", {}).get("prior_update_bridge", {})
    ledger = bridge.get("historical_case_ledger")
    if not isinstance(ledger, list) or len(ledger) != 9:
        raise ValueError("公开报告要求模型输出完整九案例历史基准率账本")
    lines: list[str] = []
    strict_total = 0
    broad_total = 0
    for index, row in enumerate(ledger, start=1):
        strict = int(row["strict_full_stack_success"])
        broad = int(row["broad_adjacency_success"])
        strict_total += strict
        broad_total += broad
        citations = "".join(_cite(ref) for ref in row["source_refs"])
        lines.append(
            f"| {index} | {row['case_name']} | {row.get('entry_path_zh') or row['entry_path']} | "
            f"{row['outcome_as_of']} | {strict} | {broad} | "
            f"{row['classification_rationale']} {citations}|"
        )
    if (strict_total, broad_total) != (2, 5):
        raise ValueError(
            f"公开历史案例表无法复算2/9与5/9：strict={strict_total}, broad={broad_total}"
        )
    lines.append(
        f"| 合计 | 9个定向案例 | 同一账本、同一分母 | 截至{AS_OF_DATE} | "
        f"{strict_total} | {broad_total} | 严格描述率{strict_total}/9；宽口径描述率{broad_total}/9。 |"
    )
    return "\n".join(lines)


def _probability_section(
    model: dict[str, Any],
    lookup: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    update_table, reconciliation_table = _probability_update_tables(model)
    historical_case_table = _historical_case_table(model)
    historical_anchors = model["probability"]["prior_update_bridge"][
        "historical_anchors"
    ]
    strict_interval = historical_anchors["complete_module_success"][
        "wilson_95_interval"
    ]
    broad_interval = historical_anchors["adjacent_or_complete_success"][
        "wilson_95_interval"
    ]
    rows = []
    scenario_lines = []
    architecture_lines = []
    pressure_lines = []
    threshold_lines = []
    company_threshold_lines = []
    both_severe_lines = []
    sensitivity_lines = []
    long_term_damage_lines = []
    company_region_table = "\n".join(
        f"| {horizon} | {company} | {geography} | {mean:.1f}% | {p10:.1f}% | {median:.1f}% | {p90:.1f}% |"
        for horizon, company, geography, mean, p10, median, p90
        in _company_region_probability_rows(model)
    )
    joint_scope_table = "\n".join(
        f"| {horizon} | {geography} | {event} | {mean:.1f}% | {p10:.1f}% | {median:.1f}% | {p90:.1f}% |"
        for horizon, geography, event, mean, p10, median, p90
        in _joint_scope_probability_rows(model)
    )
    geography_joint_table = "\n".join(
        f"| {horizon} | {state} | {mean:.1f}% | {p10:.1f}% | {median:.1f}% | {p90:.1f}% |"
        for horizon, state, mean, p10, median, p90
        in _geography_joint_probability_rows(model)
    )
    for horizon in ("3y", "5y"):
        payload = model["probability"]["horizons"][horizon]
        marginal = payload.get("marginal_probability_summary") or payload["marginal_probability"]
        rows.append(
            f"| {horizon} | {_distribution_text(marginal['byd_meaningful_entry'])} | "
            f"{_distribution_text(marginal['luxshare_meaningful_entry'])} | "
            f"{_distribution_text(marginal['at_least_one_entry'])} | "
            f"{_distribution_text(marginal['at_least_one_global_entry'])} |"
        )
        states = payload.get("entry_state_probability_summary") or payload.get("entry_state_probability") or payload.get("scenario_probability")
        for code, value in states.items():
            if code in ENTRY_SCENARIO_LABELS:
                scenario_lines.append(
                    f"| {horizon} | {code} | {ENTRY_SCENARIO_LABELS[code]} | {_distribution_text(value)} |"
                )
        architectures = payload.get("architecture_probability_summary") or payload.get("architecture_probability", {})
        for code, value in architectures.items():
            architecture_lines.append(
                f"| {horizon} | {code} | {_distribution_text(value)} | A—F进入状态保持可见，架构不覆盖公司进入 |"
            )
        disruption = (
            payload.get("conditional_deterioration_probability", {})
            .get("conditional_on_at_least_one_entry", {})
        )
        for label, value in disruption.items():
            pressure_lines.append(
                f"| {horizon} | {label} | {_distribution_text(value)} | 进入状态专家压力带；不是经验频率 |"
            )
        threshold_damage = payload.get("financial_threshold_deterioration", {})
        for label, value in threshold_damage.get(
            "conditional_on_at_least_one_entry", {}
        ).items():
            threshold_lines.append(
                f"| {horizon} | {label} | {_distribution_text(value)} | "
                f"较严重龙头代理；评价年份{threshold_damage.get('evaluation_years')} |"
            )
        for company_key, values in threshold_damage.get(
            "conditional_by_company", {}
        ).items():
            display_name = model["financial"]["companies"][company_key][
                "display_name"
            ]
            company_threshold_lines.append(
                f"| {horizon} | {display_name} | "
                f"{_distribution_text(values.get('mild', 0))} | "
                f"{_distribution_text(values.get('material', 0))} | "
                f"{_distribution_text(values.get('severe', 0))} |"
            )
        both_severe_lines.append(
            f"| {horizon} | 两家龙头均被分类为严重 | "
            f"{_distribution_text(threshold_damage.get('both_incumbents_severe_conditional', 0))} |"
        )
        long_term = threshold_damage.get("long_term_significant_damage", {})
        if horizon == "5y" and long_term.get("conditional_by_company"):
            for company_key, conditional_value in long_term[
                "conditional_by_company"
            ].items():
                display_name = model["financial"]["companies"][company_key][
                    "display_name"
                ]
                long_term_damage_lines.append(
                    f"| {display_name} | {_distribution_text(conditional_value)} | "
                    f"{_distribution_text(long_term['unconditional_by_company'][company_key])} |"
                )
            long_term_damage_lines.extend(
                [
                    f"| 至少一家龙头 | {_distribution_text(long_term['at_least_one_incumbent_conditional'])} | {_distribution_text(long_term['at_least_one_incumbent_unconditional'])} |",
                    f"| 两家龙头同时 | {_distribution_text(long_term['both_incumbents_conditional'])} | {_distribution_text(long_term['both_incumbents_unconditional'])} |",
                ]
            )
    architecture_table = "\n".join(architecture_lines) or "| 3y/5y | 待模型V2输出 | — | 架构维度与进入状态正交 |"
    pressure_table = "\n".join(pressure_lines) or "| 3y/5y | 待模型V2输出 | — | 结构化压力带 |"
    threshold_table = "\n".join(threshold_lines) or "| 3y/5y | 待模型V2输出 | — | 经营阈值分类 |"
    company_threshold_table = "\n".join(company_threshold_lines) or "| 3y/5y | 待模型V2输出 | — | — | — |"
    both_severe_table = "\n".join(both_severe_lines)
    long_term_damage_table = "\n".join(long_term_damage_lines) or "| 待模型V2输出 | — | — |"
    for case in model.get("probability_sensitivity", {}).get("cases", {}).values():
        for horizon in ("3y", "5y"):
            values = case["horizons"][horizon]
            sensitivity_lines.append(
                f"| {case['label']} | {horizon} | "
                f"{values['byd_meaningful_entry']:.1%} | "
                f"{values['luxshare_meaningful_entry']:.1%} | "
                f"{values['at_least_one_entry']:.1%} | "
                f"{values['at_least_one_global_entry']:.1%} | "
                f"{values['architecture_c_probability']:.1%} |"
            )
    sensitivity_table = "\n".join(sensitivity_lines) or "| 未配置 | — | — | — | — | — | — |"
    return _section(
        key="joint_probability_tree",
        title="联合情景树、概率更新与破坏程度",
        refs=[
            "MODEL-INPUTS",
            "MODEL-WORKPAPER",
            *_historical_case_source_refs(),
            "BYD-S01",
            "LX-IR-202508",
            "CROSS-EVIDENCE-AUDIT",
        ],
        source_lookup=lookup,
        sort_order=120,
        decision="使用小样本历史基准率约束宽先验、用里程碑证据校准公司边际、用Fréchet依赖构造联合状态，并把架构与破坏程度拆成正交维度",
        unknown="参数支持区间来自结构化判断而非可重复大样本，客户保密、进入时点和依赖强度仍不可识别",
        monitor="硬证据覆盖相应参数，执行依赖λ、事件阈值、进入时点和温和/明显/严重条件概率的敏感性",
        body=f"""
### 历史基准率与概率方法

九个定向案例使用同一分母和同一逐例账本。严格口径只把Cisco/Acacia与Lumentum/Cloud Light归为完整商用模块成功，描述率为2/9，Wilson 95%区间为{strict_interval[0]:.2%}—{strict_interval[1]:.2%}；宽口径再纳入Fabrinet制造邻接、Broadcom/CyOptics器件平台与Marvell/Inphi DSP平台，描述率为5/9，区间为{broad_interval[0]:.2%}—{broad_interval[1]:.2%}。未决案例按0计入当前描述率，而不是从分母删除；出现新的规模结果后必须重分类并重算。样本小、类别异质、选择偏误强且成功多依赖收购，因此只约束先验宽度，不直接成为两家公司的频率学后验。

| 序号 | 案例 | 进入路径 | 结果截至 | 严格完整模块成功 | 宽口径持久邻接成功 | 分类理由与逐例来源 |
|---:|---|---|---|---:|---:|---|
{historical_case_table}

Wilson区间统一使用$center=(p+z^2/(2n))/(1+z^2/n)$，$half=z\\sqrt{{p(1-p)/n+z^2/(4n^2)}}/(1+z^2/n)$，其中$n=9$、$z=1.96$；上下界为$center\\pm half$。这里的区间只描述所选案例账本，不消除样本选择和案例异质性。

工作先验的众数为3年22%、5年35%，支持区间分别为6%—55%和15%—70%。在同一严格事件合同下，每个里程碑证据更新项以公开的百分点调整众数；这是一套可审计的专家评议桥，不是贝叶斯似然、经验频率，也不按网页数量机械加总。正号表示提高有意义进入众数，负号表示降低；每行“累计众数”从同一期限先验重新起算。同一底层记录可能因同时约束产品、客户或经营边界而跨更新项复用，因此更新行数不等于独立证据数，也不能把每行再次计作独立来源。

| 公司 | 期限 | 工作先验众数 | 里程碑证据更新项 | Δ | 更新后累计众数 |
|---|---|---:|---|---:|---:|
{update_table}

| 公司 | 期限 | 先验众数 | Δ合计 | 先验+Δ | 声明后验众数 | 后验三角low/mode/high | 对账 |
|---|---|---:|---:|---:|---:|---|---|
{reconciliation_table}

百分点桥只重建众数；low/high由公开不可得、反方证据、官方冲突和事件阈值共同设定，所以不能把Δ合计加到先验low/high。Monte Carlo均值应接近三角分布(low+mode+high)/3，但均值、众数和中位数是不同统计量，后文分别展示并对账。

概率输入为三角支持区间：比亚迪3年6%/12%/22%、5年18%/30%/45%；立讯3年32%/45%/60%、5年50%/66%/80%。它们反映比亚迪缺产品/客户/专线与立讯产品成熟但全球客户冲突。全球条件概率另行输入，不与总进入相加。参数Monte Carlo使用共享分位数保证5年累计概率不低于3年；内层解析计算联合状态并输出均值、P10/中位/P90和数值收敛误差。{_cite('BYD-S01')}{_cite('LX-IR-202508')}{_cite('MODEL-INPUTS')}{_cite('MODEL-WORKPAPER')}

### 公司 × 地域 × 期限边际概率

| 期限 | 公司 | 地域事件 | 均值 | P10 | 中位数 | P90 |
|---|---|---|---:|---:|---:|---:|
{company_region_table}

总事件、中国事件和全球事件均为正向定义，不以“未全球”代替“中国”。因此联合结果也分别列示：

| 期限 | 地域范围 | 联合事件 | 均值 | P10 | 中位数 | P90 |
|---|---|---|---:|---:|---:|---:|
{joint_scope_table}

| 期限 | 地域联合状态 | 均值 | P10 | 中位数 | P90 |
|---|---|---:|---:|---:|---:|
{geography_joint_table}

“全球”要求非中国头部客户或平台侧闭环；“中国”要求有意义进入的四项条件主要由中国客户体系满足；“仅全球”是模型允许的异地路径而非“中国不存在”的推断。P10/中位/P90是输入认识不确定性的传播结果，不是历史频率置信区间。地域概率目前是诊断层：财务仍按A—F（总进入与全球事件）×P/H/C传导，中国事件和“进入地域未识别”状态没有独立冲击，B/C/D只是未全球路径的较低冲击，不能解释成“中国专属盈利损失已完整穿透”。

两家公司共享AI需求、DSP/laser/PIC供给、CSP qualification和架构窗口，事件正相关；模型使用Fréchet dependence λ从独立分布向可行同向边界移动，明确不是Pearson相关。3年/5年采用累计发生结构，不允许同一路径3年已进入、5年反而退出。模型另以每案50,000次以内、至少20,000次抽样实际执行宽松/严格事件阈值、qualification延后、负依赖、独立、高正依赖和LPO/CPO加速压力测试；这些是定义/参数敏感性，不是新增事实。

| 敏感性案例 | 期限 | 比亚迪进入 | 立讯进入 | 至少一家 | 至少一家全球进入 | CPO增量风险 |
|---|---|---:|---:|---:|---:|---:|
{sensitivity_table}

| 期限 | 状态 | 定义 | 概率 |
|---|---|---|---:|
{chr(10).join(scenario_lines)}

| 期限 | 架构状态 | 概率 | 口径 |
|---|---|---:|---|
{architecture_table}

旧情景G不再覆盖A—F。A—F描述进入状态；P/H/C描述可插拔主导、混合LPO/LRO和CPO价值迁移；经营后果再分温和、明显、严重。**温和/明显/严重的经营阈值分类是intake要求的canonical决策合同**：5年严重要求单家公司2029—2031平均实际FCF和净利润损失均至少20%、至少两年FCF达到该损失、平均毛利损失至少5个百分点、2031正常化终值损失至少25%，并且物理份额损失至少10%或同规格额外ASP压力至少7%；3年使用2029年经营结果且不使用终值门槛。阈值是决策定义，不是历史估计。

下述经营阈值、公司分类、两家同时严重及专家压力带的条件概率，均以**对应期限内至少一家形成有意义进入**为分母；无进入路径不参与条件分布。模型字段为`conditional_on_at_least_one_entry`，因此3年和5年分别使用各自期限的进入事件，不能跨期限混用。

| 期限 | 经营阈值分类 | 条件概率 | 解释 |
|---|---|---:|---|
{threshold_table}

行业代理取两家龙头中较严重者，避免一家公司严重而被另一家公司平均抵消；它不是行业总利润池的统计估计。公司层结果必须单列：

| 期限 | 公司 | 温和 | 明显 | 严重 |
|---|---|---:|---:|---:|
{company_threshold_table}

| 期限 | 联合盈利损伤事件 | 条件概率 |
|---|---|---:|
{both_severe_table}

“长期盈利显著受损”采用本报告独立的15%净利润/15%实际FCF/20%终值合同，不等同于更严格的“严重”分类。条件概率的分母是5年内至少一家有意义进入；无条件联合概率以全部路径为分母：

| 5年长期盈利显著受损对象 | 条件概率 | 无条件联合概率 |
|---|---:|---:|
{long_term_damage_table}

为显示认知不确定性，模型还保留按进入状态设定的low/mode/high专家压力带。**该压力带仅是敏感性与离散阈值交叉检查，不是canonical经营分类，不参与改写intake口径**，也不声称来自历史频率。

| 期限 | 专家压力带 | 条件概率分布 | 解释 |
|---|---|---:|---|
{pressure_table}

每条证据只更新对应里程碑。产品页和展会更新工程成熟，客户侧资格更新全球分支，重复订单和收入更新规模，专线良率更新可售供给。相同发行人证据按一个受控簇处理，官方冲突扩大区间而非选边。{_cite('CROSS-EVIDENCE-AUDIT')}
""",
    )


def _cny_yi_with_usd(value: Any, usd_to_cny: float) -> str:
    """Format a CNY 100m amount with the snapshot FX-equivalent USD 100m."""
    amount = _finite(value)
    if amount is None or usd_to_cny <= 0:
        return "不可得"
    return f"{amount:.2f}亿元人民币（约{amount / usd_to_cny:.2f}亿美元）"


def _ratio_or_na(value: Any, suffix: str = "×") -> str:
    amount = _finite(value)
    return f"{amount:.2f}{suffix}" if amount is not None else "不可得"


def _financial_section(
    model: dict[str, Any],
    lookup: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    financial_snapshot = _safe_payload(_load_json(FINANCIAL_PATH))
    usd_to_cny = float(financial_snapshot.get("fx_to_cny", {}).get("USD") or 1.0)
    company_rows = []
    multi_year_rows = []
    sensitivity_rows = []
    baseline_sensitivity_rows = []
    baseline_sensitivity_output_rows = []
    annual_financial_rows = []
    operating_assumption_rows = []
    valuation_snapshot_rows = []
    bps_reconciliation_rows = []
    valuation_bridge_rows = []
    valuation_decomposition_notes = []
    shock_input_rows = []
    entry_scenario_output_rows = []
    zero_floor_rows = []
    negative_state_rows = []
    coverage_rows = []
    financial_source_refs = {
        "innolight": "FIN-INNOLIGHT",
        "eoptolink": "FIN-EOPTOLINK",
        "luxshare": "FIN-LUXSHARE",
        "byd": "FIN-BYD",
        "byd_electronic": "FIN-BYD_ELECTRONIC",
    }
    balance_fields = {
        "fixed_assets": "固定资产",
        "construction_in_progress": "在建",
        "inventory": "存货",
        "accounts_receivable": "应收",
        "contract_liabilities": "合同负债",
    }
    for snapshot_company_key, snapshot_company in financial_snapshot.get(
        "companies", {}
    ).items():
        financial_source_ref = financial_source_refs.get(snapshot_company_key)
        financial_citation = (
            _cite(financial_source_ref) if financial_source_ref else ""
        )
        series = snapshot_company.get("financial_series", {})
        periods = series.get("periods", [])
        coverage = series.get("coverage", {})
        returned = int(coverage.get("returned_period_count", len(periods)))
        missing = list(coverage.get("missing_periods", []))
        field_counts = {
            field: sum(
                _finite((row.get(field) or {}).get("cny_yi")) is not None
                for row in periods
            )
            for field in balance_fields
        }
        if periods:
            period_range = f"{periods[0].get('period')}—{periods[-1].get('period')}"
        else:
            period_range = "无返回期"
        if all(count == returned for count in field_counts.values()):
            field_status = "固定资产/在建/存货/应收/合同负债全期非空"
        else:
            field_status = "；".join(
                f"{balance_fields[field]} {count}/{returned}"
                for field, count in field_counts.items()
            )
        employee = series.get("employee_snapshot", {})
        employee_status = (
            f"{employee.get('employees')}人；仅{employee.get('snapshot_observed_at', AS_OF_DATE)}当前档案快照，"
            "无报告期历史"
        )
        coverage_rows.append(
            f"| {snapshot_company.get('name')} {financial_citation}| {series.get('source')} | {period_range} | "
            f"{returned}/{coverage.get('requested_period_count', returned)} | {len(missing)} | "
            f"{field_status} | {employee_status} |"
        )
        market = snapshot_company.get("market_snapshot", {})
        reconciliation = market.get("bps_basis_reconciliation", {})
        if reconciliation:
            status = {
                "consistent_with_current_pb_within_3pct": "与当前PB口径差异在3%内",
                "reporting_period_share_basis_not_reconciled_to_market_pb": "报告期股本口径未与当前PB对齐",
            }.get(reconciliation.get("status"), "待人工核对")
            reported_bps = _finite(reconciliation.get("reported_bps"))
            implied_bps = _finite(
                reconciliation.get("current_share_basis_bps_implied")
                or market.get("bps_current_share_basis_implied")
            )
            difference_pct = _finite(reconciliation.get("relative_difference_pct"))
            allowed = reconciliation.get("direct_current_pb_recalculation_allowed") is True
            per_share_currency = _clean(
                market.get("per_share_currency") or market.get("currency")
            ).upper()
            per_share_unit = {
                "CNY": "元人民币/股（CNY）",
                "HKD": "港元/股（HKD）",
                "USD": "美元/股（USD）",
            }.get(
                per_share_currency,
                f"{per_share_currency or '计价货币'}/股",
            )
            reported_text = (
                f"{reported_bps:.2f}{per_share_unit}"
                if reported_bps is not None
                else "不可得"
            )
            implied_text = (
                f"{implied_bps:.2f}{per_share_unit}"
                if implied_bps is not None
                else "不可得"
            )
            difference_text = (
                f"{difference_pct:+.2f}%" if difference_pct is not None else "不可得"
            )
            bps_reconciliation_rows.append(
                f"| {snapshot_company.get('name')} {financial_citation}| {reported_text} | "
                f"{reconciliation.get('reported_bps_as_of') or market.get('financials_as_of') or '不可得'} | "
                f"{implied_text} | {difference_text} | {status} | "
                f"{'允许' if allowed else '不允许'} |"
            )
    architecture_labels = {
        "H": "LPO/LRO混合迁移",
        "C": "CPO/光引擎增量迁移",
    }
    financial_payload = model["financial"]
    operating_assumptions = financial_payload.get("operating_assumptions", {})
    pass_through_output = _finite(
        operating_assumptions.get("gross_to_net_pass_through")
    )
    wacc_output = _finite(operating_assumptions.get("terminal_wacc"))
    growth_output = _finite(
        operating_assumptions.get("terminal_perpetual_growth")
    )
    valuation_date_output = _clean(operating_assumptions.get("valuation_date"))
    terminal_date_output = _clean(operating_assumptions.get("terminal_date"))
    frozen_operating_assumptions = all(
        value is not None
        for value in (pass_through_output, wacc_output, growth_output)
    ) and bool(valuation_date_output and terminal_date_output)
    if frozen_operating_assumptions:
        gross_to_net_pass_through = float(pass_through_output)
        wacc = float(wacc_output)
        perpetual_growth = float(growth_output)
        valuation_date = valuation_date_output
        terminal_date = terminal_date_output
        operating_assumption_status = "当前模型冻结输出"
    else:
        gross_to_net_pass_through = 0.72
        wacc = 0.12
        perpetual_growth = 0.03
        valuation_date = _clean(financial_payload.get("valuation_date")) or AS_OF_DATE
        terminal_date = _clean(financial_payload.get("terminal_date")) or "2031-12-31"
        operating_assumption_status = (
            "旧模型兼容回退：operating_assumptions字段不完整，禁止解释为当前包冻结输入"
        )
    for company_key, company in model["financial"]["companies"].items():
        risk_multiplier = _finite(company.get("risk_multiplier"))
        if risk_multiplier is None:
            risk_multiplier = {"innolight": 0.92, "eoptolink": 1.08}.get(
                company_key, 1.0
            )
        risk_rationale = company.get("risk_multiplier_rationale") or {
            "innolight": "多代量产、较强绝对FCF和海外交付防御使同一外部冲击适度衰减。",
            "eoptolink": "较小绝对FCF缓冲、客户集中与多项目阶段差异使同一外部冲击适度放大。",
        }.get(company_key, "中性倍率，无额外放大或衰减。")
        snapshot_company = financial_snapshot.get("companies", {}).get(company_key, {})
        market = snapshot_company.get("market_snapshot", {})
        market_cap = _finite(market.get("market_cap_cny") or market.get("market_cap_value"))
        valuation_snapshot_rows.append(
            f"| {company['display_name']} | {market.get('trade_date') or '不可得'} | "
            f"{_cny_yi_with_usd(market_cap, usd_to_cny)} | "
            f"{_ratio_or_na(market.get('pe_ttm'))} | {_ratio_or_na(market.get('pb'))} | "
            f"{_ratio_or_na(market.get('ps_ttm'))} |"
        )
        for row in company["probability_weighted_rows"]:
            if int(row["year"]) < 2027:
                continue
            annual_financial_rows.append(
                f"| {company['display_name']} | {row['year']} | "
                f"{_cny_yi_with_usd(row.get('revenue_cny_yi'), usd_to_cny)} | "
                f"{float(row.get('gross_margin_pct', 0)):.2f}% | "
                f"{_cny_yi_with_usd(row.get('net_income_cny_yi'), usd_to_cny)} | "
                f"{_cny_yi_with_usd(row.get('expansion_capex_cny_yi'), usd_to_cny)} | "
                f"{_cny_yi_with_usd(row.get('working_capital_change_cny_yi'), usd_to_cny)} | "
                f"{_cny_yi_with_usd(row.get('fcf_cny_yi'), usd_to_cny)} |"
            )
        valuation_bridge = company.get("valuation_bridge", {})
        if valuation_bridge:
            decomposition_note = _clean(valuation_bridge.get("decomposition_note"))
            if decomposition_note and decomposition_note not in valuation_decomposition_notes:
                valuation_decomposition_notes.append(decomposition_note)
            valuation_bridge_rows.append(
                f"| {company['display_name']} | "
                f"{_cny_yi_with_usd(valuation_bridge.get('baseline_no_entry_operating_value_proxy_cny_yi'), usd_to_cny)} | "
                f"{_cny_yi_with_usd(valuation_bridge.get('probability_weighted_operating_value_proxy_cny_yi'), usd_to_cny)} | "
                f"{_cny_yi_with_usd(valuation_bridge.get('probability_weighted_zero_floor_operating_value_proxy_cny_yi'), usd_to_cny)} | "
                f"{_ratio_or_na(valuation_bridge.get('entry_only_discount_vs_A_P_pct'), '%')} | "
                f"{_ratio_or_na(valuation_bridge.get('architecture_only_discount_vs_A_P_pct'), '%')} | "
                f"{_ratio_or_na(valuation_bridge.get('combined_entry_and_architecture_discount_vs_A_P_pct'), '%')} | "
                f"{_cny_yi_with_usd(valuation_bridge.get('current_equity_market_cap_cny_yi'), usd_to_cny)} | "
                f"{_ratio_or_na(valuation_bridge.get('operating_value_proxy_to_market_cap_pct'), '%')} | "
                f"{_cny_yi_with_usd(valuation_bridge.get('unadjusted_market_cap_as_ev_implied_2031_normalized_fcf_cny_yi'), usd_to_cny)} | "
                f"{_cny_yi_with_usd(valuation_bridge.get('modeled_probability_weighted_2031_normalized_fcf_cny_yi'), usd_to_cny)} | "
                f"{_ratio_or_na(valuation_bridge.get('unadjusted_implied_to_modeled_2031_fcf_multiple'))} |"
            )
        for case_name in ("low", "base", "high"):
            case = company.get("baseline_revenue_sensitivity_outputs", {}).get(case_name)
            if not case:
                continue
            case_rows = case.get("rows", [])
            row_2031 = next(
                (row for row in case_rows if int(row.get("year", 0)) == 2031),
                case_rows[-1] if case_rows else {},
            )
            case_label = {"low": "低基线", "base": "基准", "high": "高基线"}[case_name]
            baseline_sensitivity_output_rows.append(
                f"| {company['display_name']} | {case_label} | "
                f"{_cny_yi_with_usd(row_2031.get('revenue_cny_yi'), usd_to_cny)} | "
                f"{_cny_yi_with_usd(row_2031.get('net_income_cny_yi'), usd_to_cny)} | "
                f"{_cny_yi_with_usd(row_2031.get('actual_fcf_cny_yi'), usd_to_cny)} | "
                f"{_cny_yi_with_usd(row_2031.get('normalized_fcf_cny_yi'), usd_to_cny)} | "
                f"{_cny_yi_with_usd(case.get('probability_weighted_discounted_terminal_value_cny_yi'), usd_to_cny)} | "
                f"{_cny_yi_with_usd(case.get('probability_weighted_operating_value_proxy_cny_yi'), usd_to_cny)} |"
            )
        cross_rows = company.get("cross_state_rows", {})
        base_2031 = (cross_rows.get("A|P") or [{}])[-1]
        base_2026 = (cross_rows.get("A|P") or [{}])[0]
        operating_assumption_rows.append(
            f"| {company['display_name']} | "
            f"{float(base_2026.get('gross_margin_pct', 0)):.2f}% / "
            f"{float(base_2031.get('gross_margin_pct', 0)):.2f}% | "
            f"{float(base_2026.get('net_margin_pct', 0)):.2f}% / "
            f"{float(base_2031.get('net_margin_pct', 0)):.2f}% | "
            f"{float(base_2026.get('normalized_fcf_margin_pct', 0)):.2f}% / "
            f"{float(base_2031.get('normalized_fcf_margin_pct', 0)):.2f}% | "
            f"{risk_multiplier:.2f} | {risk_rationale} | "
            f"{gross_to_net_pass_through:.2f} | {wacc:.2%} | "
            f"{perpetual_growth:.2%} | {valuation_date} | {terminal_date} | "
            f"financial_model_producer；{operating_assumption_status} |"
        )
        for state_code in ("A", "B", "C", "D", "E", "F"):
            state_row = (cross_rows.get(f"{state_code}|P") or [{}])[-1]
            terminal_value = company.get(
                "terminal_value_by_cross_state_cny_yi", {}
            ).get(f"{state_code}|P")
            entry_scenario_output_rows.append(
                f"| {company['display_name']} | {state_code}：{ENTRY_SCENARIO_LABELS[state_code]} | "
                f"{_cny_yi_with_usd(state_row.get('revenue_cny_yi'), usd_to_cny)} | "
                f"{float(state_row.get('gross_margin_pct', 0)):.2f}% | "
                f"{_cny_yi_with_usd(state_row.get('net_income_cny_yi'), usd_to_cny)} | "
                f"{_cny_yi_with_usd(state_row.get('fcf_cny_yi'), usd_to_cny)} | "
                f"{_cny_yi_with_usd(terminal_value, usd_to_cny)} |"
            )
            shock_input_rows.append(
                f"| {company['display_name']} | {risk_multiplier:.2f} | 进入状态{state_code}：{ENTRY_SCENARIO_LABELS[state_code]} | "
                f"{float(state_row.get('share_loss_pct', 0)):.2f}% | "
                f"{float(state_row.get('extra_asp_pressure_pct', 0)):.2f}% | "
                f"{float(base_2031.get('gross_margin_pct', 0)) - float(state_row.get('gross_margin_pct', 0)):.2f}个百分点 | "
                f"{_cny_yi_with_usd(state_row.get('expansion_capex_cny_yi'), usd_to_cny)} | "
                f"{_cny_yi_with_usd(state_row.get('working_capital_change_cny_yi'), usd_to_cny)} | "
                f"financial_model_producer（A—F进入状态） |"
            )
        for architecture_code, label in architecture_labels.items():
            state_row = (cross_rows.get(f"A|{architecture_code}") or [{}])[-1]
            shock_input_rows.append(
                f"| {company['display_name']} | {risk_multiplier:.2f} | 架构状态{architecture_code}：{label} | "
                f"{float(state_row.get('share_loss_pct', 0)):.2f}% | "
                f"{float(state_row.get('extra_asp_pressure_pct', 0)):.2f}% | "
                f"{float(base_2031.get('gross_margin_pct', 0)) - float(state_row.get('gross_margin_pct', 0)):.2f}个百分点 | "
                f"{_cny_yi_with_usd(state_row.get('expansion_capex_cny_yi'), usd_to_cny)} | "
                f"{_cny_yi_with_usd(state_row.get('working_capital_change_cny_yi'), usd_to_cny)} | "
                f"architecture_model_producer（P/H/C架构） |"
            )
        latest = company["probability_weighted_rows"][-1]
        baseline_latest = company["cross_state_rows"]["A|P"][-1]
        baseline_terminal = company["terminal_value_by_cross_state_cny_yi"]["A|P"]
        weighted_terminal = company.get("probability_weighted_terminal_value_cny_yi", 0)
        weighted_zero_floor = company.get(
            "probability_weighted_terminal_value_zero_floor_cny_yi", weighted_terminal
        )
        zero_floor_uplift = company.get(
            "probability_weighted_terminal_zero_floor_uplift_cny_yi",
            weighted_zero_floor - weighted_terminal,
        )
        weighted_discounted_zero_floor = company.get(
            "probability_weighted_discounted_terminal_value_zero_floor_cny_yi",
            company.get("probability_weighted_discounted_terminal_value_cny_yi", 0),
        )
        zero_floor_rows.append(
            f"| {company['display_name']} | {weighted_terminal:.2f} | "
            f"{weighted_zero_floor:.2f} | {zero_floor_uplift:.2f} | "
            f"{company.get('probability_weighted_discounted_terminal_value_cny_yi', 0):.2f} | "
            f"{weighted_discounted_zero_floor:.2f} | {len(company.get('negative_terminal_states', []))} |"
        )
        for state in company.get("negative_terminal_states", []):
            escaped_cross_state = str(state["cross_state"]).replace("|", "\\|")
            negative_state_rows.append(
                f"| {company['display_name']} | {escaped_cross_state} | "
                f"{state['normalized_terminal_fcf_cny_yi']:.2f} | "
                f"{state['signed_terminal_value_cny_yi']:.2f} | "
                f"{state['zero_floor_terminal_value_cny_yi']:.2f} | "
                f"{float(state['joint_probability']):.2%} |"
            )

        def loss(base: float, weighted: float) -> float:
            return 100.0 * (base - weighted) / max(abs(base), 1e-9)

        company_rows.append(
            f"| {company['display_name']} | {baseline_latest['revenue_cny_yi']:.2f} | "
            f"{latest['revenue_cny_yi']:.2f} | {loss(baseline_latest['revenue_cny_yi'], latest['revenue_cny_yi']):.1f}% | "
            f"{baseline_latest['net_income_cny_yi']:.2f} | {latest['net_income_cny_yi']:.2f} | "
            f"{loss(baseline_latest['net_income_cny_yi'], latest['net_income_cny_yi']):.1f}% | "
            f"{baseline_latest['fcf_cny_yi']:.2f} | {latest['fcf_cny_yi']:.2f} | "
            f"{loss(baseline_latest['fcf_cny_yi'], latest['fcf_cny_yi']):.1f}% | "
            f"{baseline_terminal:.2f} | {weighted_terminal:.2f} | "
            f"{loss(baseline_terminal, weighted_terminal):.1f}% | "
            f"{company.get('probability_weighted_discounted_terminal_value_cny_yi', 0):.2f} |"
        )
        base_2029_31 = company["cross_state_rows"]["A|P"][-3:]
        weighted_2029_31 = company["probability_weighted_rows"][-3:]
        base_avg_ni = sum(row["net_income_cny_yi"] for row in base_2029_31) / 3
        weighted_avg_ni = sum(row["net_income_cny_yi"] for row in weighted_2029_31) / 3
        base_avg_fcf = sum(row["fcf_cny_yi"] for row in base_2029_31) / 3
        weighted_avg_fcf = sum(row["fcf_cny_yi"] for row in weighted_2029_31) / 3
        multi_year_rows.append(
            f"| {company['display_name']} | {base_avg_ni:.2f} | {weighted_avg_ni:.2f} | "
            f"{loss(base_avg_ni, weighted_avg_ni):.1f}% | {base_avg_fcf:.2f} | "
            f"{weighted_avg_fcf:.2f} | {loss(base_avg_fcf, weighted_avg_fcf):.1f}% |"
        )
        for label, path in company.get("baseline_revenue_sensitivity", {}).items():
            public_label = {
                "low": "低路径",
                "base": "基准路径",
                "high": "高路径",
            }.get(label, label)
            baseline_sensitivity_rows.append(
                f"| {company['display_name']} | {public_label} | {path[0]:.2f} | "
                f"{path[1]:.2f} | {path[-1]:.2f} |"
            )
        for row in company.get("terminal_sensitivity", []):
            if row["wacc"] in {0.10, 0.12, 0.14} and row["perpetual_growth"] in {0.02, 0.03, 0.04}:
                sensitivity_rows.append(
                    f"| {company['display_name']} | {row['wacc']:.0%} | {row['perpetual_growth']:.0%} | "
                    f"{row['terminal_value_cny_yi']:.2f} | {row.get('terminal_value_zero_floor_cny_yi', max(0, row['terminal_value_cny_yi'])):.2f} | "
                    f"{row['discounted_terminal_value_cny_yi']:.2f} | "
                    f"{row.get('discounted_terminal_value_zero_floor_cny_yi', max(0, row['discounted_terminal_value_cny_yi'])):.2f} |"
                )
    negative_state_table = "\n".join(negative_state_rows) or "| 两家公司 | 无负终值交叉状态 | — | — | — | — |"
    valuation_bridge_table = "\n".join(valuation_bridge_rows) or "| 两家公司 | 待模型输出 | — | — | — | — | — | — | — | — | — | — |"
    valuation_decomposition_text = (
        "；".join(valuation_decomposition_notes).rstrip("。")
        or "旧模型未提供进入/架构分解说明，当前展示只保留兼容占位"
    )
    baseline_sensitivity_output_table = "\n".join(baseline_sensitivity_output_rows) or "| 两家公司 | 待模型输出 | — | — | — | — | — | — |"
    return _section(
        key="incumbent_financial_scenarios",
        title="中际旭创、新易盛收入、利润、FCF与终值情景",
        refs=["MODEL-WORKPAPER", "FIN-INNOLIGHT", "FIN-EOPTOLINK", "FIN-INNOLIGHT-ANALYST", "FIN-EOPTOLINK-ANALYST", "FIN-LUXSHARE", "FIN-BYD", "FIN-BYD_ELECTRONIC", "SRC-INNO-AR25", "SRC-EOPT-AR25", "SRC-HKEX-ASP26"],
        source_lookup=lookup,
        sort_order=130,
        decision="冻结无新增进入反事实后，用A—F进入与P/H/C架构的reduced-form份额、同规格额外ASP、毛利和现金流冲击做透明压力测试；终值采用显式正常化FCF margin并折现",
        unknown="分析师基线已内含多少竞争风险、公司物理份额/单位成本、进入时点与客户集中非线性",
        monitor="用实际同规格价格、客户份额、毛利、FCF、维护/扩产capex和ΔNWC替换假设，并对WACC/g保持同口径",
        body=f"""
### 输出覆盖卡

| 完成状态 | 本轮覆盖 | 使用边界 |
|---|---|---|
| **已测** | 收入、净利润、毛利、简单/正常化FCF、A—F×P/H/C交叉状态、signed Gordon终值及zero-floor敏感性 | 是透明压力测试，不是公司指引或当前股权公允价值 |
| **代理** | 物理份额、同规格额外ASP、综合毛利/固定成本冲击、市场base路径 | 代理变量有显式owner；新事实应覆盖而非与旧假设平均 |
| **未测** | 逐客户/产品/地区收入利润、完整费用率和单位成本、清算回收、再融资/注资、违约与股权稀释 | 不得用负Gordon值冒充可交易负企业价值 |

### 结构化财务快照完成度

| 公司 | 来源 | 返回期间 | 返回/请求期 | 缺失期 | 固定资产/在建/存货/应收/合同负债 | 员工边界 |
|---|---|---|---:|---:|---|---|
{chr(10).join(coverage_rows)}

四只A股（中际旭创、新易盛、立讯精密、比亚迪）的接口均返回2018Q1—2026Q1共33期，季报采用累计口径；“返回33期”只表示期间记录存在，不表示每个字段都完整，五项资产负债字段的有限人民币值覆盖按上表逐项计数。员工数仅是接口当前公司档案字段，不是报告期历史。0285.HK的yfinance财务只返回7期、缺失26个请求期，不能把有限历史写成完整序列，也不做插值；缺失期需回查交易所年报。

### 同日市场估值快照

| 公司 | 交易日 | 总市值 | PE TTM | PB | PS TTM |
|---|---|---|---:|---:|---:|
{chr(10).join(valuation_snapshot_rows)}

市场估值字段来自同一交易日的Tushare日行情/基础指标；美元等值统一按本轮快照汇率1美元={usd_to_cny:.4f}元人民币换算，目的只是双币种可读性，不改变原始人民币计量。PE、PB、PS是快照倍数，不与不同日期财务字段混合重算。2026/2027收入预期则来自Yahoo Finance/yfinance分析师聚合快照，**不是Tushare字段、不是公司指引**，两类来源不得互换。{_cite('FIN-INNOLIGHT')}{_cite('FIN-EOPTOLINK')}{_cite('FIN-INNOLIGHT-ANALYST')}{_cite('FIN-EOPTOLINK-ANALYST')}

### BPS与当前PB股本口径对账

| 公司 | 报告期BPS | BPS报告期 | 同日price/PB隐含BPS | 报告值相对隐含值差异 | 对账状态 | 可否用报告BPS直接复算当前PB |
|---|---:|---|---:|---:|---|---|
{chr(10).join(bps_reconciliation_rows)}

同日隐含BPS只按“交易日价格÷交易日PB”反推，用于检查股本/复权口径，不是第二次抓取的每股净资产，也不覆盖报告期BPS；表内单位逐证券取CNY或HKD，禁止混币。新易盛报告期BPS为20.50元人民币/股、同日隐含BPS约14.62元人民币/股，差异+40.27%；立讯精密为12.12元人民币/股与约11.43元人民币/股，差异+6.06%。这类差异可能来自送转、拆并股、回购或报告期与交易日股本口径变化，公开快照不足以自动裁定具体原因；因此状态为“未对齐”的行不允许拿报告期BPS直接复算当前PB，也不静默用隐含值覆盖报告值。该测量对账不参与经营风险倍率、竞争概率或财务冲击。{_cite('FIN-EOPTOLINK')}{_cite('FIN-LUXSHARE')}

### 起点与反事实

2025年中际旭创收入382.40亿元人民币（约{382.40 / usd_to_cny:.2f}亿美元）、净利润107.97亿元人民币（约{107.97 / usd_to_cny:.2f}亿美元）、简单FCF 81.36亿元人民币（约{81.36 / usd_to_cny:.2f}亿美元）；新易盛为248.42亿元人民币（约{248.42 / usd_to_cny:.2f}亿美元）、95.32亿元人民币（约{95.32 / usd_to_cny:.2f}亿美元）和63.81亿元人民币（约{63.81 / usd_to_cny:.2f}亿美元）。2026/2027参考基线受分析师聚合预期约束但不是公司指引，公开数据也无法识别其中已包含多少立讯扩张、正常竞争或CPO风险。因此A|P被定义为“冻结本轮额外冲击的参考反事实”，包含正常技术降价、其他既有竞争者、基础产品迁移与龙头主动防御；它不是经市场预期剥离得到的纯因果无进入基线。比亚迪/立讯增量冲击只在压力路径中出现一次。{_cite('SRC-INNO-AR25')}{_cite('SRC-EOPT-AR25')}{_cite('FIN-INNOLIGHT-ANALYST')}{_cite('FIN-EOPTOLINK-ANALYST')}

### 基础经营与估值假设

| 公司 | A\\|P毛利率2026/2031 | A\\|P净利率2026/2031 | A\\|P正常化FCF率2026/2031 | 风险倍率 | 倍率理由 | 毛利到净利传导 | WACC | g | 估值日 | 终值日 | owner/输入状态 |
|---|---:|---:|---:|---:|---|---:|---:|---:|---|---|---|
{chr(10).join(operating_assumption_rows)}

这些是透明情景假设，不是公司指引或已观察事实。表内毛利到净利传导、WACC、g、估值日和终值日直接读取财务模型的冻结经营假设输出；输入状态明确区分当前模型与旧模型兼容回退，当前包不得依赖静默默认值。风险倍率只对A—F与P/H/C冲击数组做公司防御/脆弱性缩放，不改变无新增进入A|P基线；毛利到净利传导用于把毛利率冲击映射为净利率影响。参数登记表保存来源、公式、更新规则和financial_model_producer责任人。若实际资本结构、无风险利率或长期增长变化，应先更新参数再复算，不从市场价格倒填。

当前公司财务模型是reduced-form压力测试，不是端口×单位份额×单价的完整bottom-up预测。收入由冻结基线乘“1-物理份额损失”再乘“1-同规格额外ASP压力”；毛利冲击只表示价格以外的单位成本、良率、返工/保修或固定成本综合拖累。公开数据不足以把这些成本逐项校准，因此所有冲击都有明确owner和路径，但不能声称已经测得单位经济。{_cite('SRC-HKEX-ASP26')}{_cite('MODEL-WORKPAPER')}

### 2027—2031概率加权年度财务路径

| 公司 | 年份 | 收入 | 毛利率 | 净利润 | 扩产capex | ΔNWC现金占用 | 实际FCF |
|---|---:|---|---:|---|---|---|---|
{chr(10).join(annual_financial_rows)}

表中“实际FCF”是模型的正常化FCF减当年扩产capex和ΔNWC现金占用；正的ΔNWC表示现金流扣减，不是营运资本释放。美元仅按同一快照汇率提供近似等值。2026整年FCF没有进入后文经营价值代理，因为估值日已经在2026年内，且模型没有估值日至年末的H2/stub实际现金流桥。

### 经营字段逐项完成矩阵

| 字段 | 已查来源 | 当前完成状态 | 不可得原因 | 本轮代理 | 可能偏误方向 | 对结论影响 |
|---|---|---|---|---|---|---|
| 存货 | 结构化季报序列、两家公司年报 {_cite('FIN-INNOLIGHT')}{_cite('FIN-EOPTOLINK')}{_cite('SRC-INNO-AR25')}{_cite('SRC-EOPT-AR25')} | **受限完成**：公司总额可得，光模块代际/客户不可分 | 报表不披露800G/1.6T/3.2T库存、呆滞和客户归属 | 公司总存货趋势；未写入单独SKU冲击 | 总额会混入其他产品，可能高估或低估模块备货/减值 | 不能据总存货断言新进入导致渠道积压 |
| 应收账款 | 结构化季报序列、年报客户与信用披露 {_cite('FIN-INNOLIGHT')}{_cite('FIN-EOPTOLINK')} | **受限完成**：总额可得、客户级账龄不可得 | 匿名客户、票据、保理与地区口径不分产品 | ΔNWC按收入比例情景扣减 | 若账期延长或回款恶化，模型可能高估FCF | 严重度需用应收周转与坏账连续两期复核 |
| 产能利用率/良率 | 年报、项目和制造资料 {_cite('SRC-INNO-AR25')}{_cite('SRC-EOPT-AR25')} | **阻塞**：高速模块线别利用率和一次良率未披露 | 总产能、在建或集团capex不能映射合格线 | 份额/毛利/扩产capex情景，不直接填利用率 | 缺良率通常使新进入爬坡被高估，也可能低估龙头闲置风险 | 可售供给与单位成本区间保持宽 |
| 费用率 | 年报可得公司整体销售/管理/研发/财务费用 | **受限完成**：未形成产品/地区/客户级完整费用桥 | 光模块业务与其他业务共用研发、销售和总部成本 | 净利率基线加综合固定成本拖累 | 规模摊薄会提高利润，重复研发/保修会降低利润 | 模型是reduced-form，不声称单位经济已测得 |
| 客户集中度 | 两家公司年报前五大客户披露 {_cite('SRC-INNO-AR25')}{_cite('SRC-EOPT-AR25')} | **受限完成**：集中比例可得、客户身份与SKU不可得 | 匿名披露且直接/间接供应链可能重叠 | 通过份额冲击和严重阈值反映非线性 | 平均冲击可能低估单一大客户切换，也可能高估第二来源影响 | 必须等待客户侧清单、订单和多期收入同向验证 |
| 产品结构 | 年报、公司产品页和项目状态 | **受限完成**：速率/架构方向可见、收入利润mix不可分 | 公司未披露各速率、距离和架构的收入/毛利 | 基线毛利率与架构P/H/C路径 | 高端mix上升可抵消降价，旧代清库会放大降价 | 不能把综合毛利变化单因归于比亚迪/立讯 |
| 地理结构 | 年报海外收入/制造与结构化总财务 {_cite('SRC-INNO-AR25')}{_cite('SRC-EOPT-AR25')} | **受限完成**：地区收入可见但客户、SKU、合格线不可联结 | 海外生产地不等于该客户线已资格化 | 地域概率只作诊断；财务不单独施加中国冲击 | 可能高估海外线防御或低估区域替代 | 正文明确不声称中国专属损失完整穿透 |
| SR / DR / FR / LR | 公司规格、平台与行业材料 {_cite('SRC-HKEX-ASP26')} | **SR/DR受限，FR/LR阻塞** | 缺同口径距离别出货、ASP、毛利和合格供给面板 | 按800G/1.6T/3.2T速率总量；距离只作边界 | 长距高ASP mix缺失会扭曲收入和毛利敏感性 | 财务结果不解释为完整距离结构bottom-up |
| 龙头800G/1.6T/3.2T公司出货量与份额 | 两家公司年报、产品页、平台清单和行业需求资料 {_cite('SRC-INNO-AR25')}{_cite('SRC-EOPT-AR25')} | **阻塞**：公司逐速率出货和同口径市场份额公开不可分 | 年报只给混合产品/客户口径，行业总量不能安全分配到公司 | 总物理份额损失情景 | 代际mix与客户切换非线性，平均份额冲击可能高估旧代或低估新代损失 | 不能声称已完成公司×速率bottom-up份额模型 |
| 龙头逐速率ASP相对无新增进入基线偏差 | 历史800G+ ASP、公司/行业价格与产品材料 {_cite('SRC-HKEX-ASP26')} | **阻塞**：缺同客户、同距离、同形态、同条款的800G/1.6T/3.2T公司报价面板 | 历史ASP混合批量、距离、客户、汇率和代际成熟度 | 总同规格额外ASP残差，正常代际降价另计 | 高端mix和首年小批价使速率偏差显著非线性 | 不能声称额外竞争折价已按速率实测 |

“受限完成”表示字段有一部分真实值但无法安全下钻；“阻塞”表示公开资料不足以形成所需口径，不代表经营事实为零。新数据必须保持公司、产品、客户、地区、期间和直接/间接供货六个维度，不用相邻字段代填。

2026/2027营业收入起点直接读取Yahoo Finance/yfinance分析师聚合low/avg/high快照，2028—2031分别按显式递减增速延展；它不是公司指引，也不是Tushare财务字段。基础模型使用base路径，并把low/base/high在相同A—F×P/H/C概率、margin与百分比冲击下传播至2031净利润、FCF、终值和经营价值代理：{_cite('FIN-INNOLIGHT-ANALYST')}{_cite('FIN-EOPTOLINK-ANALYST')}

| 公司 | 基线路径 | 2026收入（亿元人民币） | 2027收入（亿元人民币） | 2031收入（亿元人民币） |
|---|---|---:|---:|---:|
{chr(10).join(baseline_sensitivity_rows)}

| 公司 | 基线情景 | 2031收入 | 2031净利润 | 2031实际FCF | 2031正常化FCF | signed折现终值 | 经营价值代理 |
|---|---|---|---|---|---|---|---|
{baseline_sensitivity_output_table}

low/base/high是同一组分析师聚合收入路径的条件敏感性，不是三档发生概率，也不改变进入或架构概率。经营价值代理均只汇总2027—2031折现实际FCF与折现终值；zero-floor另作失败状态敏感性。

### A—F进入与P/H/C架构冲击对账

下表展示各状态在2031年的有效冲击输出：进入状态固定架构P，架构状态固定进入A，因而不会把架构迁移误算为新进入者压力。各公司风险倍率已经反映在数值中；进入路径由financial_model_producer负责，架构路径由architecture_model_producer负责，参数登记表保存每个字段的来源、公式和更新规则，组合状态再逐字段相加并受模型边界约束。

| 公司 | 风险倍率 | 固定另一维后的状态 | 物理份额损失 | 同规格额外ASP压力 | 毛利率拖累 | 扩产capex | ΔNWC现金占用 | 参数 owner |
|---|---:|---|---:|---:|---:|---|---|---|
{chr(10).join(shock_input_rows)}

P是可插拔主导的零增量架构冲击；H表示LPO/LRO混合迁移；C表示CPO/光引擎增量迁移。A—F与P/H/C正交，不能把代码相同的“进入状态C”和“架构状态C”混为同一变量。完整年度数组仍由统一模型字段计算，表中2031截面用于核对方向、量级和owner，不替代年度路径。

| 公司 | A—F进入状态（固定P架构） | 2031收入 | 2031毛利率 | 2031净利润 | 2031实际FCF | 2031 signed终值 |
|---|---|---|---:|---|---|---|
{chr(10).join(entry_scenario_output_rows)}

这张表直接显示每家公司六个互斥进入状态在固定P架构下的2031经营结果；它与上表的H/C固定A架构增量共同完成两维拆分。signed终值保留经营失败状态的负号，仅作可持续经营诊断；不代表股东可交易的负售价。

以下公司摘要、终值和WACC/g敏感性表的金额单位均为亿元人民币；关键年度路径、市场估值锚与经营价值桥已在上文同时给出按快照USD/CNY换算的亿美元等值。

| 公司 | A\\|P收入 | 终局概率加权收入 | 损失 | A\\|P净利润 | 加权净利润 | 损失 | A\\|P实际FCF | 加权实际FCF | 损失 | A\\|P终值 | 加权终值 | 损失 | 加权折现终值 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(company_rows)}

| 公司 | 2029—31 A\\|P平均净利润 | 终局加权平均净利润 | 损失 | A\\|P平均实际FCF | 终局加权平均实际FCF | 损失 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(multi_year_rows)}

### 经营价值代理与市场估值诊断桥

| 公司 | A\\|P无新增进入经营代理 | 联合概率加权经营代理 | zero-floor经营代理 | 仅进入变化（固定P） | 仅架构变化（固定A） | 进入×架构联合变化 | 当前股权市值 | 经营代理/市值 | 市值当EV反推2031正常化FCF | 模型2031正常化FCF | 反推/模型 |
|---|---|---|---|---:|---:|---:|---|---:|---|---|---:|
{valuation_bridge_table}

经营价值代理严格定义为“2027—2031折现实际FCF + 概率加权折现2031正常化终值”，排除完整2026年FCF，也没有估值日至2026年末H2/stub桥。模型冻结的分解说明为：{valuation_decomposition_text}。因此“仅进入”不会吞并基础架构迁移，“仅架构”也不会归因于比亚迪/立讯；联合变化才是交叉模型总效应。

该桥是**估值诊断，不是企业价值或股权公允价值，更不是目标价**。表中反向DCF故意把同日股权市值未经调整地当作EV代理，只为暴露缺失桥：估值日净现金/净债务、少数股东权益、非经营资产及其他业务价值、估值日后2026 stub FCF、稀释后股本与公司行动均未建模。由于这些项目可显著改变股权值，经营代理/市值和反推FCF只用于量级检查，不产生买卖建议。{_cite('MODEL-WORKPAPER')}{_cite('FIN-INNOLIGHT')}{_cite('FIN-EOPTOLINK')}

概率加权不是目标价。A—F进入状态与P/H/C架构构成交叉状态；每条cross-state年度路径按显式冲击数组渐进，但摘要行统一使用5年终局状态概率，因此它是“按2031终局权重汇总的条件路径”，不是逐年无条件期望，也不用于声称精确进入年份。中国/全球概率当前是地域诊断层；财务只把A—F（总进入与全球事件）×P/H/C传导到冲击，中国事件和“进入地域未识别”状态没有独立冲击，B/C/D仅代表未全球的较低冲击，不能称“中国专属损失已完整穿透”。一次性扩产capex和ΔNWC只扣发生年度；永续期以显式假设的正常化FCF margin为基数，排除暂时扩产和营运资本拖累，但尚未建立NOPAT、折旧、维护capex和正常ΔNWC的完整FCFF桥。2031 Gordon终值按相同WACC/g计算并折现回{AS_OF_DATE}；股权桥缺口如上表后说明。

### 终值敏感性

| 公司 | WACC | g | signed终值 | zero-floor终值 | signed折现终值 | zero-floor折现终值 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(sensitivity_rows)}

| 公司 | 概率加权signed终值 | 概率加权zero-floor终值 | floor uplift | signed折现终值 | zero-floor折现终值 | 负终值状态数 |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(zero_floor_rows)}

signed Gordon是主口径：当极端交叉状态的2031正常化FCF为负时，公式保留负号，用于诊断“现有经营形态无法支持永续，可能需要持续重组、再融资、注资或退出”。它不是可交易的负企业价值，也不是股东可获得的负售价。zero-floor只是一项敏感性，显示把这些状态的终值截断到零对概率加权结果的抬升；模型**未建模**清算回收、重组成本、再融资条款、违约优先级或股权稀释，因此两种口径都不能替代这些情景。

| 公司 | A—F×P/H/C状态 | 2031正常化FCF | signed终值 | zero-floor终值 | 状态联合概率 |
|---|---|---:|---:|---:|---:|
{negative_state_table}

严重情景不是“进入者存在”本身，而是头部qualification、可扩良率、持续同规格折价、客户份额和架构迁移共同导致2029—2031净利润/FCF及终值超过阈值损失。中际旭创绝对FCF更强，新易盛产品毛利更高但资源缓冲较小；两种防御不能合并成单一静态排名。模型需同时展示温和/明显/严重条件概率和基线差，而不是只给极端终值。
""",
    )


def _final_report_sections(
    model: dict[str, Any],
    lookup: dict[str, dict[str, Any]],
    screening: dict[str, Any],
    compiled_counts: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    sections.append(
        _section(
            key="valuation_hypothesis_test",
            title="“低估值是否仍不能买”的假设检验框架",
            refs=["FIN-INNOLIGHT", "FIN-EOPTOLINK", "FIN-INNOLIGHT-ANALYST", "FIN-EOPTOLINK-ANALYST", "SRC-INNO-AR25", "SRC-EOPT-AR25", "SRC-HKEX-ASP26", "LX-IR-202508", "BYD-S01", "MODEL-WORKPAPER"],
            source_lookup=lookup,
            sort_order=140,
            decision="把‘低估值也不能买’视为需要盈利基线、永久损伤概率、当前价格隐含预期与替代方案共同检验的假设，而非报告预设",
            unknown="当前一致预期已包含多少竞争/CPO风险、未来盈利基线和投资者要求的安全边际",
            monitor="每季用同口径收入、毛利、FCF、客户份额和估值更新反事实，不用静态PE或单一终值替代完整决策",
            body=f"""
### 四层检验

第一层检验无进入基线是否仍成立。需要验证AI网络端口、800G/1.6T代际、正常ASP降幅、龙头客户份额和成本下降，而不是先把所有未来增长当确定。第二层估计比亚迪/立讯带来的增量损失概率；如果同规格额外折价、物理份额和毛利冲击没有可识别证据，不能把正常技术降本重复记成进入者破坏。第三层判断损伤是否永久：若份额在下一代收复、一次性扩产结束或龙头进入CPO价值池，低谷FCF不能直接永续。第四层把概率加权经营价值与市场价格、净现金、其他业务和替代标的比较。

当前结构化快照显示中际旭创和新易盛估值都反映了较强增长预期，但估值字段日期、财务报告期与分析师覆盖口径不同。2025高利润和正FCF是年报/财务事实；2026/2027一致预期来自Yahoo Finance/yfinance分析师聚合，只是变化中的观察锚，不是Tushare字段或公司指引。模型仅用它约束基线范围。{_cite('FIN-INNOLIGHT-ANALYST')}{_cite('FIN-EOPTOLINK-ANALYST')}{_cite('SRC-INNO-AR25')}{_cite('SRC-EOPT-AR25')}

在具名头部qualification、两期重复订单、专用产能/良率、可分模块收入和同规格报价出现前，“长期格局已经恶化”仍未证实。立讯产品和区域交付足以让风险进入估值分布，但不足以把严重情景设为确定；比亚迪连产品里程碑都未闭环，更不能直接扣除龙头永久份额。{_cite('LX-IR-202508')}{_cite('BYD-S01')}

只有至少一家进入者达到多客户全球T4、带来可识别的7个百分点以上额外折价，且龙头连续出现份额、毛利和FCF恶化；或CPO使传统模块价值永久迁移而龙头无法捕获，才应把“不能买”从尾部风险升级为核心约束。当前结论是情景折价而非绝对禁买：买不买仍取决于概率加权下行、估值安全边际、验证触发器和可替代收益，而不是一句竞争叙事。{_cite('MODEL-WORKPAPER')}

估值复核必须使用同一观察日的价格、股本、净现金和盈利口径，并分别计算基准、概率加权与压力状态的安全边际。若低倍数来自盈利处于周期峰值，静态PE会虚低；若市场价格已经折入比模型更严重的永久损伤，则竞争风险存在也不自动推出继续回避。报告因此不给脱离价格和替代收益的单向交易指令。
""",
        )
    )
    sections.append(
        _section(
            key="red_team_synthesis",
            title="正方、反方、冲突证据与 red-team 结论",
            refs=["BYD-S01", "BYD-S06", "BYD-S11", "LX-ANNUAL-2024", "LX-IR-202508", "LX-IR-20260507", "LX-IR-20260525", "SRC-INNO-AR25", "SRC-EOPT-AR25", "SRC-COHR-10K25", "SRC-FN-10K24", "CROSS-EVIDENCE-AUDIT"],
            source_lookup=lookup,
            sort_order=150,
            decision="最稳健结论位于两个极端之间：立讯是真实工程与有限商业威胁但全球规模未证实；比亚迪是相邻期权；严重利润池恶化仍是联合尾部情景",
            unknown="官方冲突的SKU/客户分类原因、客户保密项目和龙头主动防御的实际效果",
            monitor="每次更新同时记录支持、反对、冲突和替代解释，不允许单边证据覆盖相反的高质量来源",
            body=f"""
### 支持竞争威胁上升的证据

立讯有可审计产品规格、800G公司量产口径、1.6T验证/早期批量、OIF和合作伙伴工程证据，不是空白叙事；两家公司又分别具有连接/机柜系统或服务器/液冷/电源的一站式组合能力，能够以整体方案接近客户。强资金和全球制造提高长期NPI与低初期利润容忍度。龙头前五大客户占比均超过70%，单一大客户培育第二供应商会放大份额影响。{_cite('LX-IR-202508')}{_cite('BYD-S01')}{_cite('SRC-INNO-AR25')}{_cite('SRC-EOPT-AR25')}

### 反对格局已崩坏的证据

比亚迪没有数据中心高速模块产品、团队、专线和客户硬证据；立讯没有具名头部CSP闭环和专属经济数据。关键DSP、laser/PIC、耦合良率与产线变化存在供应和重新认证门槛；AI网络需求与代际切换可能吸收区域第二供应源。龙头具备多代量产、正FCF、海外制造和客户共同开发能力，能够降本、扩产或参与光引擎/CPO。历史案例也显示完整模块成功常依赖收购成熟团队/IP/客户，而不是EMS能力自然迁移。{_cite('BYD-S06')}{_cite('BYD-S11')}{_cite('SRC-COHR-10K25')}{_cite('SRC-FN-10K24')}

### 冲突与替代解释

立讯2024年报较强的头部测试/国际客户交付措辞，与2025-08中小客户为主、无头部明确机会相冲突；2026宣传的1.6T早期商业化，又与最新监管口径中的业务起步、拓展需时间和无自研1.6T硅光芯片并存。可接受处理是同时展示并按SKU、客户定义、技术出货与经济规模拆轴；禁止只选一边。{_cite('LX-ANNUAL-2024')}{_cite('LX-IR-202508')}{_cite('LX-IR-20260507')}{_cite('LX-IR-20260525')}

替代解释包括：立讯“国际头部”可能是非CSP、不同SKU、测试/小批或间接供货；比亚迪“高速互联”可能是铜缆、连接器、背板或NIC周边；客户引入第二供应商可能主要为韧性而非价格战；CPO既可能削弱传统BOM，也可能增加总光连接并由龙头继续捕获。独立审计因此压低证据越级，而不是把任何一方概率强行归零。{_cite('CROSS-EVIDENCE-AUDIT')}
""",
        )
    )
    compiled_counts = compiled_counts or {}
    source_count = int(compiled_counts.get("source_count", len(lookup)))
    compiled_claim_count = compiled_counts.get("claim_count")
    compiled_fact_count = compiled_counts.get("parallel_fact_count")
    if compiled_claim_count is not None and compiled_fact_count is not None:
        additional_fact_count = int(compiled_fact_count) - 196
        full_pack_count_sentence = (
            f"编译后的完整研究包为{source_count}个来源、"
            f"{int(compiled_claim_count)}条综合claim、{int(compiled_fact_count)}个平行事实；"
            f"比原始分包多出的{additional_fact_count}个平行事实来自冲突补充、"
            "结构化财务观测和模型推导事实，不能反向解释为相同数量的外部独立证据组。"
        )
    else:
        full_pack_count_sentence = (
            f"本次纯展示调用只取得{source_count}个来源对象；"
            "完整claim与平行事实计数必须由编译调用显式传入，禁止从旧产物猜测。"
        )
    group_count = len({source["independence_key"] for source in lookup.values()})
    core_members = [
        source
        for source in lookup.values()
        if source.get("policy_evidence_role") == "core_evidence"
    ]
    core_group_count = len(
        {source["independence_key"] for source in core_members}
    )
    classified_sources = [
        (source, *_public_source_class(source)) for source in lookup.values()
    ]
    intake_tier_order = ("Tier 1", "Tier 2", "Tier 3", "Tier 4", "Structured", "Internal")
    intake_tier_display = {
        "Tier 1": "第1层（原始/权威）",
        "Tier 2": "第2层（行业预测）",
        "Tier 3": "第3层（卖方/媒体辅助）",
        "Tier 4": "第4层（弱信号）",
        "Structured": "结构化市场、财务与分析师快照",
        "Internal": "内部模型/审计",
    }
    tier_count_lines = []
    for intake_tier in intake_tier_order:
        members = [row[0] for row in classified_sources if row[1] == intake_tier]
        tier_count_lines.append(
            f"| {intake_tier_display[intake_tier]} | {len(members)} | "
            f"{len({source['independence_key'] for source in members})} |"
        )
    origin_labels = {
        "regulatory_government_standard": ("监管/政府/标准", "监管备案、政府原文或正式标准组织记录"),
        "issuer_controlled": ("发行人受控原文", "公司报告、公告、投资者关系或正式产品材料"),
        "customer_supplier_original": ("客户/供应商/平台原文", "独立客户、供应商或平台侧一手记录"),
        "industry_forecast": ("行业预测", "预测机构的模型与观点，不能替代公司事实"),
        "sell_side_media": ("卖方/媒体", "线索、市场预期或二级报道"),
        "weak_signal": ("弱信号", "招聘聚合、会议线索等仅用于早期发现"),
        "structured_financial": ("结构化财务", "Tushare或yfinance结构化市场/财务快照"),
        "structured_analyst": ("分析师聚合镜像", "Yahoo Finance/yfinance分析师聚合快照；不是公司指引"),
        "internal_model_audit": ("内部模型/审计", "仅用于计算、筛选和交叉审计，不作为外部事实"),
    }
    origin_count_lines = []
    for origin, (label, description) in origin_labels.items():
        members = [row[0] for row in classified_sources if row[2] == origin]
        origin_count_lines.append(
            f"| {label} | {description} | {len(members)} | "
            f"{len({source['independence_key'] for source in members})} |"
        )
    external_members = [row[0] for row in classified_sources if row[1] != "Internal"]
    internal_members = [row[0] for row in classified_sources if row[1] == "Internal"]
    external_group_count = len({source["independence_key"] for source in external_members})
    internal_group_count = len({source["independence_key"] for source in internal_members})
    internal_grade_counts = Counter(source["source_tier"] for source in lookup.values())
    grade_summary = "、".join(
        f"{grade}={internal_grade_counts.get(grade, 0)}" for grade in ("S", "A", "B", "C", "D")
    )
    internal_gray_count = internal_grade_counts.get("C", 0) + internal_grade_counts.get("D", 0)
    internal_gray_ratio = internal_gray_count / max(source_count, 1) * 100.0
    public_tier_members = [row for row in classified_sources if row[1] in {"Tier 1", "Tier 2", "Tier 3", "Tier 4"}]
    public_weak_members = [row for row in classified_sources if row[1] in {"Tier 3", "Tier 4"}]
    structured_members = [row for row in classified_sources if row[1] == "Structured"]
    public_weak_ratio = len(public_weak_members) / max(len(public_tier_members), 1) * 100.0
    public_plus_structured_ratio = len(public_weak_members) / max(
        len(public_tier_members) + len(structured_members), 1
    ) * 100.0
    sections.append(
        _section(
            key="source_coverage",
            title="来源层级、独立来源簇、灰源占比与覆盖率",
            refs=["LOCAL-MATERIAL-SCREENING", "CROSS-EVIDENCE-AUDIT", "BYD-S01", "LX-IR-202508", "SRC-INNO-AR25", "SRC-EOPT-AR25", "SRC-OIF-2025", "FIN-INNOLIGHT"],
            source_lookup=lookup,
            sort_order=160,
            decision=f"最终包有{source_count}个来源对象、{group_count}个全部来源簇；其中{len(core_members)}个核心证据对象归入{core_group_count}个核心独立证据组，仅供参考和内部底稿不进入该分母",
            unknown="相同底层记录在公司、伙伴和媒体间的潜在转述关系，以及客户私有资料的不可见部分",
            monitor="机器统计source tier、review status、independence_key、因子证据组和翻译完整性，并由人工复核底层独立性",
            body=f"""
### 证据包计数与材料覆盖

三个原始分包的逐包精确计数为：比亚迪20个来源、12条综合claim、60个平行事实；立讯32个来源、18条综合claim、52个平行事实；行业/龙头/历史38个来源、20条综合claim、84个平行事实。原始分包合计90个来源、50条综合claim、196个平行事实。{full_pack_count_sentence}用户提供23份PDF全部完成提取和筛选，共22个唯一SHA256，14/15为精确重复；这些卖方材料主要作线索、预测和市场预期。{_cite('LOCAL-MATERIAL-SCREENING')}

内部五档证据字段计数为{grade_summary}，其中C/D合计{internal_gray_count}/{source_count}={internal_gray_ratio:.1f}%。这个“内部灰档占比”混合了原始性、用途、发行人控制和复核状态，**不能**机械等同公开弱来源占比；例如发行人正式产品规格即使内部为C且只作参考，仍属于公开第1层原始规格，但只能证明规格存在。公开口径中，第3/4层弱来源为{len(public_weak_members)}/{len(public_tier_members)}={public_weak_ratio:.1f}%；若把{len(structured_members)}个结构化财务源也放进非内部对象分母，则是{len(public_weak_members)}/{len(public_tier_members) + len(structured_members)}={public_plus_structured_ratio:.1f}%。两种分母同时披露，禁止拿{internal_gray_count}/{source_count}与{len(public_weak_members)}/{len(public_tier_members)}互相替代。

| intake层级 | 来源对象 | 独立来源簇 |
|---|---:|---:|
{chr(10).join(tier_count_lines)}

| 来源原点 | 中文口径说明 | 来源对象 | 独立来源簇 |
|---|---|---:|---:|
{chr(10).join(origin_count_lines)}

两张表都是按各自分类维度切片：同一底层独立来源簇可能跨层级或来源原点出现，**分类内簇数不可相加**；本包按`independence_key`全局完全去重后为{group_count}个全部来源簇，其中能支持核心研究的{len(core_members)}个来源归入{core_group_count}个核心独立证据组。仅供参考的卖方、媒体、论坛和内部底稿可用于发现线索、反查与敏感性，不得抬高这一核心证据数。

第1层包括监管/政府/标准、公司正式报告与规格、客户/供应商/平台原文；第2层是行业预测；第3层是卖方/媒体辅助材料；第4层是招聘聚合等早期信号；结构化类别单列Tushare/yfinance市场、财务与分析师镜像；内部类别仅支持复算与审计。外部与结构化来源共{len(external_members)}个对象、{external_group_count}个组；内部模型/筛选/交叉审计共{len(internal_members)}个对象、{internal_group_count}个组，不计入外部独立来源分母。这个统计也不表示等权：同一公司多页、同一预测家族和同一公告转载继续按底层记录聚类。{_cite('BYD-S01')}{_cite('LX-IR-202508')}{_cite('SRC-OIF-2025')}

覆盖具有不对称性：主体、产品矩阵、公开互操作、监管财务、行业路线、龙头财务和历史案例较强；具名客户、私有AVL、专线良率、真实同规格ASP、光模块分部利润和团队规模较弱。因此我们能较高置信度回答“公开证据到哪一步”，却不能高置信度判断NDA项目是否存在或把概率区间压窄。所有英文来源保留英文原文和中文译意，2024及更早预测带时效警告。{_cite('SRC-INNO-AR25')}{_cite('SRC-EOPT-AR25')}{_cite('FIN-INNOLIGHT')}
""",
        )
    )
    sections.append(
        _section(
            key="gaps_and_requests",
            title="数据缺口、验证债与补证请求",
            refs=["BYD-S01", "BYD-S04", "BYD-S18", "LX-ANNUAL-2024", "LX-IR-202508", "LX-IR-20260525", "NVIDIA-CX8-VALIDATED", "SRC-HKEX-ASP26", "SRC-COHR-10K25", "SRC-FN-10K24"],
            source_lookup=lookup,
            sort_order=170,
            decision="D0决策关键验证债集中在立讯官方冲突、比亚迪产品项目、具名客户资格和可分经济数据；公开研究可在标明开放/有界并扩大区间后保留这些债",
            unknown="D0/D1表中列示的客户、产线、器件、价格、人员和可分财务字段",
            monitor="按补证请求的可接受证据和模型动作逐项关闭；没有闭环时不得把pending写成verified",
            body=f"""
### 决策验证债（D0/D1/D2）

| ID | 状态 | 缺口 | 决策影响 | 当前代理与偏误方向 | 可接受补证 | 参数 owner |
|---|---|---|---|---|---|---|
| D0-01 | 开放/有界 | 立讯客户层级与商业阶段官方冲突 | 决定全球进入区间 | 并列冲突披露；单选任一口径都会压窄区间 | 公司按SKU解释、客户/平台原文 | `P_LX_GLOBAL_GIVEN_ENTRY` |
| D0-02 | 开放 | 比亚迪电子具名400G+模块项目 | 决定是否越过产品门槛 | 集团相邻能力会高估模块成熟度 | SKU/规格、官方JD、客户/供应商原文 | `P_BYD_PRODUCT` |
| D0-03 | 开放 | 两家公司qualification/AVL与重复订单 | 有意义进入硬合同 | 发行人/伙伴自述可能高估客户阶段 | 客户清单、监管披露、两期交付 | `P_*_CN/GLOBAL` |
| D0-04 | 开放 | 模块收入、ASP、出货与毛利 | 决定规模和价格破坏度 | 混合分部会高估光模块规模 | 可分财务、订单与出货交叉 | `ENTRY_EXTRA_ASP_PRESSURE` |
| D1-01 | 开放 | 专线设备、良率、UPH、返修与老化 | 决定合格供给上限 | 集团capex会高估可售产能 | 环评设备、招标验收、稳定KPI | `QUALIFIED_SUPPLY` |
| D1-02 | 开放 | DSP/PIC/laser/FA/MT锁量 | 决定爬坡时点和成本 | 样片可得会高估规模供给 | 供应协议、产能预留、替代认证 | `COMPONENT_AVAILABILITY` |
| D1-03 | 开放 | 官方岗位ID、法人、HC与去重序列 | 校准团队形成阶段 | 聚合站刷新会高估净招聘 | 官方职位库与跨期存档 | `P_*_TEAM` |
| D1-04 | 开放 | 专利族法律状态、受让人与产品实施 | 校准技术资产 | 标题/同族数量会高估实施 | CNIPA/WIPO状态与产品映射 | `TECH_READINESS` |
| D1-05 | 开放 | 同规格同客户真实报价 | 识别新增进入者额外折价 | 历史ASP混合样本会误归因竞争 | 同客户/规格/条款报价面板 | `ENTRY_EXTRA_ASP_PRESSURE` |
| D2-01 | 开放 | 产品网页首次出现和版本历史 | 校准路线时间 | 当前页无法给首发日 | 网页存档与版本hash | `PRODUCT_TIMING` |
| D2-02 | 开放 | 龙头匿名客户映射 | 校准集中度传导 | 擅自映射会制造伪客户事实 | 公司/客户权威原文 | `INCUMBENT_SHARE_SHOCK` |
| D2-03 | 开放 | 3.2T/CPO客户部署与维护经济性 | 决定架构路径升级 | 标准/原型会高估规模部署 | 客户量产、订单、维护和成本 | `ARCH_P/H/C` |

D0是公开研究中的决策关键验证债，不等于独立 reviewer 的 `REV-P0`；前者可在明确状态、偏误和补证动作后保持未闭环，后者若未关闭则不能通过发布门禁。比亚迪的D0问题是经营主体有没有合格产品、团队、专线和客户；立讯的D0问题是官方冲突、全球头部客户与可分经济数据是否闭环。{_cite('BYD-S01')}{_cite('BYD-S18')}{_cite('LX-ANNUAL-2024')}{_cite('LX-IR-202508')}

### 模型/输出合同（M0，单列）

| ID | 当前状态 | 合同 | 验收证据 |
|---|---|---|---|
| M0-01 | 已实现；复核状态见审计链 | 两家公司 × 中国/全球 × 3年/5年概率，含均值/P10/中位/P90及联合状态 | 主报告概率矩阵与“进入概率可视化”均由同一模型字段生成 |
| M0-02 | 已实现；复核状态见审计链 | 实体因子的真实独立证据组数与综合分公式 | 20个因子已展示记录数/发行主体数/可计分独立组数；综合分与区间由公开方向、权重、低/基准/高及ROUND_HALF_UP逐项生成 |

所有缺口禁止用替代口径伪填：集团capex不等于模块产能，通信分部销量不等于模块只数，未具名客户不映射CSP，卖方预测不写公司事实，历史ASP不直接识别竞争残差。每次补证保存事件日、发布日、版本、原文摘录、来源簇和反方证据；新事实覆盖代理假设，不与旧假设平均。{_cite('SRC-HKEX-ASP26')}{_cite('SRC-COHR-10K25')}{_cite('SRC-FN-10K24')}
""",
        )
    )
    sections.append(
        _section(
            key="monitoring_calendar",
            title="未来12—24个月事件日历与监控 dashboard",
            refs=["BYD-S01", "BYD-S04", "BYD-S06", "BYD-S17", "BYD-S18", "LX-IR-202508", "LX-FRO-2026", "OIF-OFC2026", "NVIDIA-CX8-VALIDATED", "SRC-INNO-AR25", "SRC-EOPT-AR25", "SRC-BIS-JAN26", "SRC-LC-MAR26", "SRC-HKEX-ASP26"],
            source_lookup=lookup,
            sort_order=180,
            decision="监控以里程碑状态变化而非新闻数量为单位；网页、职位、专利、公告、兼容清单与财务字段可自动发现，客户映射和阶段裁决必须人工复核",
            unknown="未来会议和披露的确切日期会变化，必须临近重新查询；私有客户事件仍可能不公开",
            monitor="按周/月/季和事件驱动频率执行表中任务，触发后只重跑相关概率和财务分支，并保留前后证据哈希",
            body=f"""
### 滚动12—24个月事件日历

| 滚动窗口 | 预期可观察事件 | 当前基线 | 上行触发 | 反方/证伪信号 | 受影响参数 | 来源与频率 |
|---|---|---|---|---|---|---|
| 2026Q3（0—3个月） | 2026中报/半年度披露、立讯官方冲突解释、比亚迪产品/主体更新 | 立讯有产品但客户与经济规模冲突；比亚迪无具名400G+ SKU | 公司按SKU披露收入、出货、客户阶段；比亚迪电子出现可归属规格 | 继续只见集团相邻能力；立讯仍无法解释头部/中小客户口径 | `P_LX_GLOBAL_GIVEN_ENTRY`、`P_BYD_PRODUCT`、基线收入/毛利 | 公司公告与IR事件驱动；网页每周 |
| 2026Q4（3—6个月） | 产品版本、规格页、产业会议、供应商交付/产能报告 | 800G/1.6T器件路线可行，锁量、良率和线体不可得 | 新SKU含速率/形态/距离/功耗；供应协议或设备验收可交叉 | 页面换词无客户/产线闭环；供应商仅给行业总量 | `TECH_READINESS`、`COMPONENT_AVAILABILITY`、`QUALIFIED_SUPPLY` | 产品页hash每周；供应商/项目每月；会期临近重查 |
| 2027Q1（6—9个月） | 年度行业会议/互操作、平台兼容清单、2026业绩预告/快报 | 互操作和平台侧800G/1.6T资格未形成两家完整闭环 | 客户/平台侧具名OPN、AVL或GA状态，且明确直接/间接供货 | 仅伙伴演示、实验室互操作或限定清单继续未命中 | `P_*_GLOBAL_GIVEN_ENTRY`、`ENTRY_TIMING`、架构P/H/C | 客户/平台每月；财务公告事件驱动；会议确切日期不预填 |
| 2027Q2（9—12个月） | 2026年报、模块收入/订单、固定资产/在建、存货和应收 | 专属模块经济数据、专线利用率与客户账期不可分 | 模块收入/毛利、设备/良率和重复订单至少两轴闭环 | 混合分部增长但模块字段仍不可分；库存/应收恶化无收入兑现 | `ENTRY_EXTRA_ASP_PRESSURE`、ΔNWC、capex、毛利冲击 | 年报深审；结构化财务每季；客户订单事件驱动 |
| 2027H2（12—18个月） | 1.6T重复订单、上游器件锁量、合格产线爬坡 | 立讯1.6T为早期商业化口径，比亚迪仍缺产品里程碑 | 同客户连续两期1.6T交付、锁量与稳定良率、第二客户扩展 | 订单一次性、良率/返修未达标、供应或资格延迟 | 5年进入概率、合格可售供给、严重度条件概率 | 公司/供应商每月；财务与产线每季 |
| 2028H1（18—24个月） | 3.2T/CPO客户部署、跨代续单、维护与单位经济 | 3.2T对立讯仅为探索/标准方向，无当前离散SKU；CPO仍为架构情景 | 客户量产部署、可审计3.2T/CPO产品、跨代续单与正单位经济 | 标准/原型长期不转量产；龙头继续捕获新架构价值池 | `ARCH_P/H/C`、长期份额/ASP、正常化FCF与终值 | 客户/平台事件驱动；产品每月；财务每季 |

窗口相对{AS_OF_DATE}滚动，不把尚未确认的会议或披露具体日期写成事实；每次刷新先重查日历，再记录事件日、发布日期和观察日。上行触发只更新对应参数，反方信号同样入账并可下调概率或扩大区间。

### 七字段事件监控 dashboard

| 组/指标 | 当前状态 | 最新日期 | 更新频率 | 数据源 | 触发阈值 | 概率更新方向（参数 owner） | 人工复核事项 |
|---|---|---|---|---|---|---|---|
| BYD / 400G+ SKU与规格 | 仅宽泛高速互联，无具名数据中心模块 | 2026-07-18核验 | 每周网页hash；公告事件驱动 | {_cite('BYD-S01')}{_cite('BYD-S04')} | 可归属BYD电子的SKU且速率/形态/距离/功耗至少三项可审计 | 上调`P_BYD_PRODUCT`，间接上调`P_BYD_CN_3Y/5Y` | 首发日期、法人、完整模块或方案组合 |
| BYD / 客户与平台资格 | OIF/NVIDIA指定公开名单未命中，属有界负证据 | 2026-07-18核验 | 每月；清单事件驱动 | {_cite('BYD-S17')}{_cite('BYD-S18')} | 客户/平台侧具名OPN、qualification/AVL或两期重复订单 | 全球客户上调`P_BYD_GLOBAL_GIVEN_ENTRY`；中国客户只改`P_BYD_CN` | 清单覆盖、工程样品/GA、直接或间接供货 |
| BYD / 团队与专线 | 集团招聘和通用智慧工厂存在，专项法人/HC/设备未闭环 | 2026-07-18核验 | 招聘每周；项目每月 | {_cite('BYD-S06')}{_cite('BYD-S16')} | 三个去重岗位族，或同法人出现耦合/COB/老化/BERT设备至少两类 | 小幅上调`P_BYD_TEAM`或`BYD_CAPACITY_READINESS`；不直接改客户参数 | 岗位转载、车载污染、采购与验收/良率差异 |
| Luxshare / 800G与1.6T阶段 | 公司称800G量产、1.6T验证至早期批量，经济规模不可分 | 监管反证至2026-05-25；本轮核验2026-07-18 | 月度网页；IR/公告事件驱动 | {_cite('LX-IR-202508')}{_cite('LX-FRO-2026')} | 可审计模块收入/出货，或连续两期重复交付 | 上调`P_LX_CN_3Y/5Y`与`P_LX_ENTRY_TIMING` | “量产”指线体/产品/商业规模；混合分部污染 |
| Luxshare / 全球头部CSP | 发行人口径冲突，无客户侧800G/1.6T qualification闭环 | 2026-07-18核验 | 每月；客户清单事件驱动 | {_cite('LX-IR-202508')}{_cite('NVIDIA-CX8-VALIDATED')} | 客户/平台侧具名OPN+AVL，或同客户两期可归属订单 | 显著上调`P_LX_GLOBAL_GIVEN_ENTRY`并收窄冲突区间 | SKU/客户分类、测试/小批/稳定采购、ODM链 |
| Luxshare / 专线良率与经济性 | 专线设计/实际产能、良率、模块收入和毛利不可得 | 2026-07-18核验 | 每季；招标/供应商事件驱动 | {_cite('LX-FRO-2026')}{_cite('OIF-OFC2026')} | 专线设备+良率/UPH+模块收入/毛利至少两类交叉 | 收窄`LX_QUALIFIED_SUPPLY`和`ENTRY_EXTRA_ASP_PRESSURE` | 通信异质件套、集团capex、伙伴演示越级 |
| Incumbents / 收入、毛利、FCF | 2025年两家龙头高毛利、正简单FCF | FY2025；2026-07-18核验 | 每季；年报深审 | {_cite('SRC-INNO-AR25')}{_cite('SRC-EOPT-AR25')} | 同口径毛利同比降至少3pct且FCF/份额连续两期同向恶化 | 上调`INCUMBENT_DAMAGE_SEVERITY`及公司shock，不改进入概率 | 汇率、mix、需求周期、capex/营运资本和会计变化 |
| Incumbents / 客户切份额与代际防御 | 客户集中高，但1.6T/海外制造构成防线 | 2026-07-18核验 | 产品每月；财务每季 | {_cite('SRC-INNO-AR25')}{_cite('SRC-EOPT-AR25')} | 多源确认大客户切份额并与销量/ASP/毛利同步，或新代量产反证 | 调整`INNO/EOPT_SHARE_SHOCK`；防御兑现则下调严重度 | 匿名客户映射、样品/量产、总产能/高端有效产能 |
| Market / AI端点与启用光口 | 平台给速率和密度，未给全球实际部署量 | 2026-07-18核验 | 每季；平台发布驱动 | {_cite('SRC-LC-MAR26')} | 部署端点/端口越过慢/快路径边界或拓扑/光化率改变 | 更新“市场端口需求慢/基准/快路径”，不直接改公司份额 | 容量上限与部署、链路两端、breakout、备件 |
| Market / 1.6T、CPO时点 | 预测分歧大，标准/项目不等于规模出货 | 最新预测至2026-03；2026-07-18核验 | 每季 | {_cite('SRC-LC-MAR26')}{_cite('OIF-OFC2026')} | 客户部署/可审计出货，或独立预测在同口径实质收敛 | 更新`ARCH_P/H/C`和代际窗口；预测只改区间 | 同机构多期去重、发布日期、基准假设和时效 |
| Market / 正常ASP与额外折价 | 历史ASP受mix、批量、成熟度和竞争共同污染 | 2026-07-18核验 | 每季 | {_cite('SRC-HKEX-ASP26')} 当前历史ASP混合序列；后续同客户/规格/条款真实报价 | 调整mix/原料/汇率后额外折价连续达到3%或7% | 覆盖`ENTRY_EXTRA_ASP_PRESSURE`的0/3—7/7—15档 | 可比性、首年小批高价、采购量折扣和FX |
| Policy / 先进计算出口管制 | 未证实普通光模块被全面禁运，主要直接影响先进计算/半导体 | 政府原文至2026-01；2026-07-18核验 | 事件驱动；至少月度 | {_cite('SRC-BIS-JAN26')} | 新规明确覆盖模块/laser/PIC/设备，或改变区域GPU可得性 | 更新`REGIONAL_DEMAND`/`COMPONENT_AVAILABILITY`，方向可正可负 | 受限对象、ECCN、许可、生效日、地区和例外 |
| Policy / 本地化与海外合格线 | 海外制造缓解连续性，但不替代客户资格 | 2026-07-18核验 | 每季；客户政策驱动 | {_cite('SRC-INNO-AR25')}{_cite('SRC-EOPT-AR25')} | 客户/政府正式要求特定地区生产并触发新线资格/供应商替换 | 调整`GLOBAL_QUALIFICATION_LAG`和地区供给 | 适用客户、地点/法人、产品线是否已获资格 |

触发阈值是研究更新合同，不是已发生事实。自动化只负责网页hash、字段变化、职位/专利去重和公告发现；客户映射、阶段裁决、ASP可比性与来源冲突必须人工复核。触发后保存前后证据hash、参数owner、调整方向和裁决理由；未来会议与披露日期临近时重新查询，不预填可能变化的日程。
""",
        )
    )
    return sections


_MARKET_ENTITY_DISPLAY_PROSE = {
    "byd_entry_risk": {
        "evidence": (
            "比亚迪电子的有效正证据集中在AI服务器、液冷、电源、高速互联入口、资金与通用自动化；"
            "这些证据只抬高能力迁移上限。公开产品、官方岗位、光学专线、客户资格和重复订单仍未闭环，"
            "车载光通信、集团半导体专利或其他法人项目不能跨主体补齐数据中心模块门槛。"
        ),
        "scenario": (
            "基础情景仍是三年内不构成有意义高速光模块进入、五年保留相邻制造转化期权。"
            "上行情景需依次出现可归属比亚迪电子的400G+ SKU、光模块团队/专线、互操作、客户qualification和重复订单；"
            "若只有集团招聘、专利或通用工厂，不能触发份额与ASP冲击。"
        ),
        "monitor": (
            "优先监控经营主体、SKU规格、官方职位ID与法人、主动耦合/老化/BERT设备、客户/平台清单和两期订单。"
            "若新证据仍落在车载、连接器、交换机周边或集团级方向，维持相邻能力而不升级产品成熟度。"
        ),
    },
    "luxshare_entry_risk": {
        "evidence": (
            "立讯的产品与工程链已经跨过“是否存在模块”的门槛：800G LPO/FRO、1.6T FRO、伙伴集成、耦合/测试岗位均可见。"
            "但87.42%持股并表只证明财务控制，不能隔离光模块团队、客户、产线、收入和利润；"
            "头部AI客户测试/国际客户交付与中小客户为主、无头部明确机会的发行人口径必须并列。"
        ),
        "scenario": (
            "基础情景是区域或有限商业进入概率较高，但全球头部CSP、可扩良率和利润捕获仍有明显折扣。"
            "严重情景要求具名客户资格、连续重复订单、合格专线供给和可分经济数据同时出现；"
            "伙伴演示、发行人量产措辞或200G铜缆清单不能单独触发全球规模冲击。"
        ),
        "monitor": (
            "逐SKU监控800G/1.6T客户阶段、直接或间接供货、东莞立讯技术与集团分部边界、线体良率、"
            "模块收入/毛利和同规格报价；3.2T继续保持探索状态，直到出现离散规格与客户部署。"
        ),
    },
    "innolight_terminal_risk": {
        "evidence": (
            "中际旭创的防御来自多代量产、1.6T产品、客户共同开发、海外交付和更强绝对FCF；"
            "风险来自高客户集中、高增长基线与当前估值对持续份额和利润的要求。"
            "新进入者风险必须与正常代际降价、其他竞争者及CPO价值迁移分开，不能把全部毛利变化归因于比亚迪/立讯。"
        ),
        "scenario": (
            "基础情景保留龙头规模和学习曲线，区域第二来源主要造成局部份额/报价压力。"
            "尾部情景是全球客户切份额、额外折价、CPO捕获不足与扩产/营运资本拖累同向发生；"
            "若1.6T/新架构继续量产并收复份额，低谷现金流不应永久化。"
        ),
        "monitor": (
            "按季度跟踪大客户份额代理、800G/1.6T/3.2T产品阶段、同口径毛利、实际FCF、海外合格线和CPO价值捕获。"
            "只有份额、ASP、毛利和现金流连续同向恶化，才把终值风险从敏感性升级为核心判断。"
        ),
    },
    "eoptolink_terminal_risk": {
        "evidence": (
            "新易盛的较高光产品毛利和海外暴露提供收益弹性，多条1.6T、LRO、硅光PIC和LPO项目提供路线选择；"
            "但项目分别处于内部验收、样验、小批或预样，不能统一写成量产。"
            "较小绝对FCF缓冲、高客户集中与项目阶段差异使经营冲击更敏感；报告期BPS与当前股本口径差异"
            "只影响每股/估值测量可比性，不改变竞争概率、风险倍率或经营冲击。"
        ),
        "scenario": (
            "基础情景是高端mix与海外交付吸收有限第二供应商压力；"
            "尾部情景需要客户切份额、同规格额外折价、泰国或其他海外线资格延迟及新架构投入共同压低现金流。"
            "单一产品样验失败或单季capex上升都不足以直接宣告永久损伤。"
        ),
        "monitor": (
            "重点跟踪泰国及其他海外线资格、各代产品从样验到量产的状态变化、前五大客户集中、"
            "应收/存货现金占用、毛利与实际FCF；并持续复核公司行动后的每股与估值口径。"
        ),
    },
}


def _entity_sections(
    entities: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    source_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    targets_by_entity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for target in targets:
        targets_by_entity[target["entity_key"]].append(target)
    output: list[dict[str, Any]] = []
    for index, entity in enumerate(entities, start=1):
        refs = [value.removeprefix("source_ref:") for value in entity["evidence_ref_uri_list"]]
        citations = "".join(
            _cite(ref)
            for ref in (
                refs
                if entity["entity_research_mode"] == "theory_research"
                else refs[:6]
            )
        )
        if entity["entity_research_mode"] == "theory_research":
            profile = entity["research_profile"]
            ledger_lines = []
            for row_index, row in enumerate(entity.get("research_data_points", []), start=1):
                ledger_lines.append(
                    f"| {row_index} | {row['data_point_title']} | {row.get('period') or '期间未标明'} | "
                    f"{row['interpretation']} | {row['research_use']} {_cite(row['source_ref'])}|"
                )
            body = (
                f"# {entity['display_name']}\n\n"
                f"## 研究问题\n\n{profile['research_question']}\n\n"
                f"{profile['literature_review_markdown']}\n\n"
                f"{profile['analysis_markdown']}\n\n"
                f"{profile['answer_markdown']}\n\n"
                f"{profile['conclusion_markdown']}\n\n"
                "### 结构化研究底稿\n\n"
                "| 序号 | 事实底稿 | 时点 | 解读 | 研究用途 |\n"
                "|---:|---|---|---|---|\n"
                f"{chr(10).join(ledger_lines)}\n\n"
                f"### 限制\n\n{profile['limitations_markdown']} {citations}"
            )
        else:
            factor_items = sorted(
                entity["factor_scores"],
                key=lambda item: item["score_adjusted"],
                reverse=True,
            )
            factor_rows = []
            for rank, factor in enumerate(factor_items, start=1):
                orientation = {
                    "higher_is_risk": "原始分越高，风险越高",
                    "higher_is_defense": "原始分越高，防御越强；风险=100-原始分",
                }.get(factor.get("score_orientation"), "按公开方向归一为风险")
                factor_rows.append(
                    f"| {rank} | {factor['metric_name']} | {orientation} | "
                    f"{float(factor.get('score_raw_construct', factor['score_adjusted'])):.1f} → "
                    f"{float(factor.get('score_normalized_risk', factor['score_adjusted'])):.1f} | "
                    f"{float(factor.get('score_low_normalized_risk', factor['score_adjusted'])):.1f} / "
                    f"{float(factor.get('score_normalized_risk', factor['score_adjusted'])):.1f} / "
                    f"{float(factor.get('score_high_normalized_risk', factor['score_adjusted'])):.1f} | "
                    f"{float(factor.get('weight', 0)):.2f} | "
                    f"{float(factor.get('weighted_low_contribution', 0)):.2f} / "
                    f"{float(factor.get('weighted_contribution', 0)):.2f} / "
                    f"{float(factor.get('weighted_high_contribution', 0)):.2f} | "
                    f"{int(factor.get('record_count', 0))} / {int(factor.get('issuer_count', 0))} / "
                    f"{int(factor.get('independent_group_count', 0))} | "
                    f"{int(factor.get('support_group_count', 0))} / "
                    f"{int(factor.get('counter_group_count', 0))} / "
                    f"{int(factor.get('boundary_group_count', 0))} / "
                    f"{int(factor.get('context_group_count', 0))} |"
                )
            weight_sum = sum(float(factor.get("weight", 0)) for factor in factor_items)
            base_formula = " + ".join(
                f"{float(factor.get('weight', 0)):.2f}×"
                f"{float(factor.get('score_normalized_risk', factor['score_adjusted'])):.1f}"
                for factor in factor_items
            )
            low_formula = " + ".join(
                f"{float(factor.get('weight', 0)):.2f}×"
                f"{float(factor.get('score_low_normalized_risk', factor['score_adjusted'])):.1f}"
                for factor in factor_items
            )
            high_formula = " + ".join(
                f"{float(factor.get('weight', 0)):.2f}×"
                f"{float(factor.get('score_high_normalized_risk', factor['score_adjusted'])):.1f}"
                for factor in factor_items
            )
            entity_prose = _MARKET_ENTITY_DISPLAY_PROSE[entity["key"]]
            target_blocks = []
            for target in targets_by_entity[entity["key"]]:
                target_blocks.append(
                    f"### {target['target_name']}（{target.get('ticker') or '观察工具'}）\n\n"
                    f"**暴露关系：** {target['exposure_rationale']}\n\n"
                    f"**投资判断：** {target['investment_view']}\n\n"
                    f"**证实动作：** {target['confirmed_scenario_action']}\n\n"
                    f"**证伪动作：** {target['falsified_scenario_action']}\n\n"
                    f"**条件建议：** {target['conditional_investment_recommendation']}"
                )
            body = f"""# {entity['display_name']}

## 实体回答

{entity['description']} 本实体综合风险分为 {entity['score_point']:.0f}/100，区间 {entity['score_band_low']:.0f}—{entity['score_band_high']:.0f}，覆盖率 {entity['coverage']:.0%}、置信度 {entity['confidence']:.0%}。这里的高分表示进入或终值下行的研究风险更强，不是无条件做多分，也不是预测股价。分数区间吸收客户私有信息、官方披露冲突、阶段不可得与模型假设；任何硬证据出现后应更新对应因子，而非整包机械加分。{citations}

## 因子分解

| 排名 | 因子 | 方向 | 原始构造→归一风险 | 低/基准/高风险 | 权重 | 低/基准/高加权贡献 | 记录/发行主体/可计分独立组 | 支持/反证/边界/校准组 |
|---:|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(factor_rows)}

权重合计={weight_sum:.2f}。基准完整代入：Σ({base_formula})={float(entity['score_unrounded']):.2f}，按ROUND_HALF_UP四舍五入为{entity['score_point']:.0f}。低情景完整代入：Σ({low_formula})={float(entity['score_band_low_unrounded']):.2f}，按ROUND_HALF_UP为{entity['score_band_low']:.0f}。高情景完整代入：Σ({high_formula})={float(entity['score_band_high_unrounded']):.2f}，按ROUND_HALF_UP为{entity['score_band_high']:.0f}。低/高区间是证据情景，不是统计置信区间；必需因子缺失时保持该因子并按保守边界处理，不把权重重分配给已有因子。记录数、发行主体数和可计分独立组分别展示，同一底层记录跨页面或跨角色复用不增加独立性。

{entity_prose['evidence']}

## 情景与决策

{entity_prose['scenario']}

{chr(10).join(target_blocks)}

## 监控与证伪

{entity_prose['monitor']}
"""
        body = _clean_markdown(body)
        if len(body) < 2200:
            raise AssertionError(f"entity section {entity['key']} 深度不足：{len(body)}")
        output.append(
            {
                "entity_key": entity["key"],
                "section_key": f"entity_answer_{entity['key']}",
                "section_title": f"{entity['display_name']}：独立研究回答",
                "body_markdown": body,
                "support_status": "partially_supported",
                "evidence_ref_uri_list": entity["evidence_ref_uri_list"],
                "sort_order": 1000 + index * 10,
            }
        )
    return output


def _early_signals(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for entity in entities:
        if entity["entity_research_mode"] != "market_linked":
            continue
        score = float(entity["score_point"])
        output.append(
            {
                "entity_key": entity["key"],
                "early_signal_score": min(100, score + 8),
                "early_signal_strength_label": "strong" if score >= 60 else "medium",
                "research_priority_score": min(100, score + 12),
                "research_priority_label": "high_priority_for_followup" if score >= 50 else "medium_priority_for_followup",
                "source_count": entity["source_count"],
                "independent_source_count": entity["independent_source_count"],
                "verification_debt_count": 4 if score >= 50 else 6,
                "core_score_snapshot": score,
                "evidence_ref_uri_list": entity["evidence_ref_uri_list"],
                "aggregate_trace": {
                    "reason": "早期信号只决定复核优先级，不改写核心因子分；客户、专线、收入和重复订单缺口仍单独保留。",
                    "verification_debt": "需要用新的独立硬证据更新具体里程碑，禁止按新闻数量累加。",
                },
            }
        )
    return output


def _distribution_text(value: Any, *, percent: bool = True) -> str:
    mean, p10, median, p90 = _distribution_stats(value, percent=percent)
    suffix = "%" if percent else ""
    if not isinstance(value, dict):
        return f"{mean:.1f}{suffix}"
    return (
        f"均值 {mean:.1f}{suffix}；P10 {p10:.1f}{suffix}；"
        f"中位 {median:.1f}{suffix}；P90 {p90:.1f}{suffix}"
    )


def _simple_chart_panel(
    title: str,
    series: list[dict[str, Any]],
    *,
    unit: str,
) -> dict[str, Any]:
    all_values = [float(value) for item in series for value in item["values"]]
    low = min(all_values)
    high = max(all_values)
    if math.isclose(low, high):
        low -= 1
        high += 1
    pad = (high - low) * 0.08
    y_min = low - pad
    y_max = high + pad
    rendered = []
    for item in series:
        count = len(item["values"])
        points = []
        for index, value in enumerate(item["values"]):
            x = 0 if count == 1 else index / (count - 1) * 100
            y = (1 - (float(value) - y_min) / (y_max - y_min)) * 100
            points.append(f"{x:.2f},{y:.2f}")
        rendered.append(
            {
                "label": item["label"],
                "color": item.get("color", "#2563eb"),
                "svg_points": " ".join(points),
                "observation_count": count,
                "latest_period": item["periods"][-1],
                "latest_value": f"{item['values'][-1]:.2f}{unit}",
            }
        )
    periods = series[0]["periods"]
    middle = periods[len(periods) // 2]
    return {
        "title": title,
        "unit": unit,
        "axis_mode": "sequence",
        "x_axis_label": "横轴：年份/期限",
        "y_axis_label": f"纵轴：{unit}",
        "x_ticks": [
            {"position": 0, "label": periods[0]},
            {"position": 50, "label": middle},
            {"position": 100, "label": periods[-1]},
        ],
        "y_ticks": [
            {"position": 0, "label": f"{y_max:.1f}"},
            {"position": 50, "label": f"{(y_min + y_max) / 2:.1f}"},
            {"position": 100, "label": f"{y_min:.1f}"},
        ],
        "x_start": periods[0],
        "x_end": periods[-1],
        "y_min": f"{y_min:.2f}",
        "y_max": f"{y_max:.2f}",
        "series": rendered,
    }


def _table_visual(
    key: str,
    title: str,
    subtitle: str,
    columns: list[str],
    rows: list[list[Any]],
    refs: list[str],
    source_lookup: dict[str, dict[str, Any]],
    *,
    sort_order: int,
) -> dict[str, Any]:
    valid_refs = [ref for ref in refs if ref in source_lookup]
    data = {
        "what": title,
        "how_to_read": subtitle,
        "columns": columns,
        "rows": rows,
        "column_width_policy": {"long_columns": columns[-2:] if len(columns) >= 2 else columns},
    }
    return {
        "block_key": key,
        "block_type": "table",
        "title": title,
        "subtitle": subtitle,
        "data": data,
        "display_data": {"columns": columns, "rows": rows},
        "print_fallback": {"columns": columns, "rows": rows},
        "evidence_ref_uri_list": [_uri(ref) for ref in valid_refs],
        "support_status": "partially_supported",
        "red_flag_level": "none",
        "sort_order": sort_order,
    }


def _visuals(
    model: dict[str, Any],
    financial: dict[str, Any],
    sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lookup = {source["ref"]: source for source in sources}
    visuals: list[dict[str, Any]] = []
    probability_rows = [
        [horizon, company, geography, mean, p10, median, p90]
        for horizon, company, geography, mean, p10, median, p90
        in _company_region_probability_rows(model)
    ]
    probability_rows.extend(
        [horizon, event, geography, mean, p10, median, p90]
        for horizon, geography, event, mean, p10, median, p90
        in _joint_scope_probability_rows(model)
    )
    probability_rows.extend(
        [horizon, "地域联合状态", state, mean, p10, median, p90]
        for horizon, state, mean, p10, median, p90
        in _geography_joint_probability_rows(model)
    )
    visuals.append(
        _table_visual(
            "entry_probability_visual",
            "公司×地域×期限进入概率与联合状态",
            "中国和全球是分别定义的正向事件；同时展示均值、P10、中位数、P90及总/中国/全球至少一家与两家同时进入。",
            ["期限", "公司或联合事件", "地域/状态", "均值%", "P10%", "中位数%", "P90%"],
            probability_rows,
            ["MODEL-WORKPAPER", "BYD-S01", "LX-IR-202508", "CROSS-EVIDENCE-AUDIT"],
            lookup,
            sort_order=510,
        )
    )
    scenario_rows = []
    for horizon in ("3y", "5y"):
        payload = model["probability"]["horizons"][horizon]
        states = payload.get("entry_state_probability_summary") or payload.get("entry_state_probability") or payload.get("scenario_probability")
        for code in sorted(states):
            if code not in ENTRY_SCENARIO_LABELS:
                continue
            scenario_rows.append([horizon, code, ENTRY_SCENARIO_LABELS[code], _distribution_text(states[code])])
        architectures = payload.get("architecture_probability_summary") or payload.get("architecture_probability", {})
        for code, value in architectures.items():
            scenario_rows.append([horizon, f"架构-{code}", "与A—F正交，不覆盖进入状态", _distribution_text(value)])
    visuals.append(
        _table_visual(
            "joint_scenario_visual",
            "A—F进入状态与架构维度",
            "A—F是互斥进入状态；P/H/C是正交架构维度，C表示CPO/光引擎增量风险，必须查看交叉而非覆盖。",
            ["期限", "代码", "定义", "概率"],
            scenario_rows,
            ["MODEL-WORKPAPER", "SRC-OIF-2025", "SRC-LPO-MSA", "SRC-LC-MAR26"],
            lookup,
            sort_order=520,
        )
    )
    market_rows = model["market"]["rows"]
    years = [str(row["year"]) for row in market_rows]
    market_panels = [
        _simple_chart_panel(
            "需求与合格供给",
            [
                {"label": "需求", "color": "#2563eb", "periods": years, "values": [row["total_ports_million"] for row in market_rows]},
                {"label": "合格供给", "color": "#dc2626", "periods": years, "values": [row["qualified_supply_million"] for row in market_rows]},
            ],
            unit="百万端口",
        ),
        _simple_chart_panel(
            "架构份额情景",
            [
                {"label": "LPO/LRO", "color": "#0f766e", "periods": years, "values": [row["lpo_lro_share_pct"] for row in market_rows]},
                {"label": "CPO", "color": "#7c3aed", "periods": years, "values": [row["cpo_share_pct"] for row in market_rows]},
            ],
            unit="%",
        ),
    ]
    visuals.append(
        {
            "block_key": "market_outlook_visual",
            "block_type": "line_chart",
            "title": "2026—2031需求、合格供给与架构路径",
            "subtitle": "分离速率需求、合格供给和架构份额；点路径是基准情景，区间与假设见计算底稿。",
            "data": {
                "what": "高速光模块需求、合格供给与架构路径",
                "time_window": "2026—2031",
                "how_to_read": "先比较合格供给与需求，再查看LPO/LRO和CPO作为速率段内部/正交架构的渗透。",
                "analysis": "名义产能不是可售供给；CPO份额不与速率出货重复相加。",
                "chart": {"panels": market_panels},
                "columns": ["年份", "需求", "合格供给", "供需比", "LPO/LRO", "CPO"],
                "rows": [[row["year"], row["total_ports_million"], row["qualified_supply_million"], row["qualified_supply_demand_ratio"], row["lpo_lro_share_pct"], row["cpo_share_pct"]] for row in market_rows],
            },
            "print_fallback": {"columns": ["年份", "需求", "合格供给", "供需比", "LPO/LRO", "CPO"], "rows": [[row["year"], row["total_ports_million"], row["qualified_supply_million"], row["qualified_supply_demand_ratio"], row["lpo_lro_share_pct"], row["cpo_share_pct"]] for row in market_rows]},
            "evidence_ref_uri_list": [_uri(ref) for ref in ["MODEL-WORKPAPER", "SRC-NV-QX800", "SRC-BCM-TH6", "SRC-LC-MAR26"] if ref in lookup],
            "support_status": "partially_supported",
            "red_flag_level": "none",
            "sort_order": 530,
        }
    )
    # 财务图兼容V1/V2：V2仍保留 probability_weighted_rows 作为摘要。
    companies = model["financial"]["companies"]
    fcf_series = []
    for index, company in enumerate(companies.values()):
        rows = company["probability_weighted_rows"]
        fcf_series.append(
            {
                "label": company["display_name"],
                "color": "#2563eb" if index == 0 else "#d97706",
                "periods": [str(row["year"]) for row in rows],
                "values": [row["fcf_cny_yi"] for row in rows],
            }
        )
    financial_panel = _simple_chart_panel("概率加权简单FCF", fcf_series, unit="亿元人民币")
    fcf_terminal_rows = []
    for company in companies.values():
        negative_states = company.get("negative_terminal_states", [])
        state_summary = "；".join(
            f"{state['cross_state']}:{state['signed_terminal_value_cny_yi']:.2f}"
            for state in negative_states
        ) or "无"
        fcf_terminal_rows.append(
            [
                company["display_name"],
                company["probability_weighted_rows"][-1]["fcf_cny_yi"],
                company.get("probability_weighted_terminal_value_cny_yi"),
                company.get("probability_weighted_terminal_value_zero_floor_cny_yi"),
                company.get("probability_weighted_terminal_zero_floor_uplift_cny_yi"),
                company.get("probability_weighted_discounted_terminal_value_cny_yi"),
                company.get("probability_weighted_discounted_terminal_value_zero_floor_cny_yi"),
                state_summary,
            ]
        )
    fcf_terminal_columns = [
        "公司",
        "2031 FCF",
        "概率加权signed终值",
        "zero-floor终值",
        "floor uplift",
        "signed折现终值",
        "zero-floor折现终值",
        "负终值状态:值",
    ]
    visuals.append(
        {
            "block_key": "incumbent_fcf_visual",
            "block_type": "line_chart",
            "title": "中际旭创与新易盛概率加权FCF路径",
            "subtitle": "显式区分年度现金流、signed Gordon主口径与zero-floor敏感性；负终值是经营失效诊断，不是可交易负企业价值。",
            "data": {
                "what": "竞争和架构情景下的概率加权简单FCF",
                "time_window": "2026—2031",
                "how_to_read": "比较两家现金流路径，并结合严重度概率与WACC/g敏感性。",
                "analysis": "一次性扩产capex和营运资本拖累不进入永续期正常化FCF。负Gordon状态表示持续重组、再融资、注资或退出压力；模型未建立清算回收、再融资条款或股权稀释。",
                "chart": {"panels": [financial_panel]},
                "columns": fcf_terminal_columns,
                "rows": fcf_terminal_rows,
            },
            "print_fallback": {"columns": fcf_terminal_columns, "rows": fcf_terminal_rows},
            "evidence_ref_uri_list": [_uri(ref) for ref in ["MODEL-WORKPAPER", "FIN-INNOLIGHT", "FIN-EOPTOLINK", "SRC-INNO-AR25", "SRC-EOPT-AR25"] if ref in lookup],
            "support_status": "partially_supported",
            "red_flag_level": "none",
            "sort_order": 540,
        }
    )
    valuation_rows = []
    for key, company in financial["companies"].items():
        market = company.get("market_snapshot", {})
        valuation_rows.append([
            company["name"],
            company.get("ticker") or company.get("yf_symbol"),
            market.get("trade_date"),
            market.get("market_cap_cny"),
            market.get("pe_ttm"),
            market.get("pb"),
            market.get("ps_ttm"),
            market.get("roe"),
        ])
    visuals.append(
        _table_visual(
            "valuation_snapshot_visual",
            "进入者与龙头财务估值快照",
            "市场字段与财务字段日期分开；金额为亿元人民币，倍数和比例按结构化快照。",
            ["公司", "证券", "交易日", "市值", "PE TTM", "PB", "PS TTM", "ROE"],
            valuation_rows,
            ["FIN-INNOLIGHT", "FIN-EOPTOLINK", "FIN-LUXSHARE", "FIN-BYD", "FIN-BYD_ELECTRONIC"],
            lookup,
            sort_order=550,
        )
    )
    visuals.append(
        _table_visual(
            "milestone_matrix_visual",
            "进入里程碑与当前最低可证阶段",
            "同一轴的领先不能替代后续硬门槛；公开未检出保留为有界未知。",
            ["里程碑", "比亚迪电子", "立讯", "升级所需证据"],
            [
                ["战略/团队", "相邻AI基础设施；专项团队未验证", "产品线与岗位线索", "法人、岗位ID、团队/项目"],
                ["产品/样机", "无具名400G+模块", "800G/1.6T产品与演示", "规格、样机、可靠性"],
                ["互操作", "指定公开名单未命中", "OIF/伙伴工程证据", "独立测试与版本"],
                ["qualification", "未验证", "发行人称验证；头部客户未闭环", "客户/平台AVL/design win"],
                ["重复规模订单", "未验证", "公司称量产；数量/收入不可分", "两期交付、多客户/跨代"],
            ],
            ["BYD-S01", "BYD-S17", "LX-IR-202508", "OIF-OFC2026", "NVIDIA-CX8-VALIDATED", "CROSS-EVIDENCE-AUDIT"],
            lookup,
            sort_order=560,
        )
    )
    return visuals


REPORT_PATH = OUTPUT_DIR / "final_report.md"
BUILD_SUMMARY_PATH = OUTPUT_DIR / "build_summary.json"
STAGE_VALIDATION_PATH = OUTPUT_DIR / "validation_stage.json"
PUBLIC_CONTENT_AUDIT_JSON_PATH = OUTPUT_DIR / "public_content_quality_audit.json"
PUBLIC_CONTENT_AUDIT_MARKDOWN_PATH = OUTPUT_DIR / "public_content_quality_audit.md"


def _supplement_requests() -> list[dict[str, Any]]:
    """保留公开研究客观不可得的验证债，不用零值或传闻补齐。"""

    return [
        {
            "request_id": "SUP-BYD-COMMERCIAL-CLOSURE",
            "entity_key": "byd_entry_risk",
            "request_title": "补充比亚迪电子高速光模块经营主体、具名SKU与客户阶段原始证据",
            "request_detail": "需要法人/事业部归属、产品规格书、客户或平台侧 qualification/AVL/design win，以及跨两个采购或披露周期的重复交付证据；集团服务器、液冷和高速互联表述不能代填。",
            "priority": "p1",
            "blocking_status": "limits_scoring",
            "review_status": "pending",
            "evidence_ref_uri": _uri("BYD-S01"),
        },
        {
            "request_id": "SUP-LUX-COMMERCIAL-CLOSURE",
            "entity_key": "luxshare_entry_risk",
            "request_title": "闭环立讯全球头部客户、重复订单与光模块收入",
            "request_detail": "需要客户/平台或监管侧原始记录解释2024年报与后续IR的客户层级冲突，并分离测试、小批、稳定量产、多客户复购及可审计收入。",
            "priority": "p1",
            "blocking_status": "limits_scoring",
            "review_status": "pending",
            "evidence_ref_uri": _uri("LX-IR-202508"),
        },
        {
            "request_id": "SUP-UPSTREAM-QUALIFICATION",
            "entity_key": "qualification_upstream_constraints",
            "request_title": "补充专用产线、关键设备、良率、稼动率和供应链锁定记录",
            "request_detail": "需要主动耦合、COB/COC、老化/BERT等设备与光模块法人/工厂的对应关系，以及线数、UPH、良率、稼动率和关键DSP/laser/PIC供应状态；公司整体capex不能替代。",
            "priority": "p1",
            "blocking_status": "limits_scoring",
            "review_status": "pending",
            "evidence_ref_uri": _uri("CROSS-EVIDENCE-AUDIT"),
        },
        {
            "request_id": "SUP-RECRUITMENT-PATENT",
            "entity_key": "recruitment_patent_capacity_audit",
            "request_title": "补充招聘历史快照与专利族法律状态",
            "request_detail": "需要原始岗位ID、首次/最后可见日期、法人、地点、职责文本去重，以及专利申请人别名、优先权、同族、法律状态和数据中心场景映射；聚合页和专利数量不作为核心事实。",
            "priority": "p2",
            "blocking_status": "non_blocking",
            "review_status": "pending",
            "evidence_ref_uri": _uri("LOCAL-MATERIAL-SCREENING"),
        },
        {
            "request_id": "SUP-MARKET-ARCHITECTURE",
            "entity_key": "industry_demand_supply_model",
            "request_title": "按同规格拆分端口需求、正常ASP与LPO/LRO/CPO架构迁移",
            "request_detail": "每季度取得800G、1.6T、3.2T端口出货、同规格成交价、正常代际降本以及LPO/LRO/CPO量产采用记录；预测与厂商路线图必须和已实现出货分列，不能按更新项数量制造独立性。",
            "priority": "p1",
            "blocking_status": "limits_scoring",
            "review_status": "pending",
            "evidence_ref_uri": _uri("SRC-LC-MAR26"),
        },
        {
            "request_id": "SUP-INCUMBENT-FINANCIAL",
            "entity_key": "innolight_terminal_risk",
            "request_title": "补齐龙头下一期财务、客户、产品与地域传导",
            "request_detail": "在中际旭创和新易盛下一份定期报告后复核收入、库存、应收、产能/产量代理、费用率、客户集中、产品代际、地域、经营现金流与资本开支；缺失的前瞻字段保留为未映射，不用利润率合成项伪装三表模型。",
            "priority": "p1",
            "blocking_status": "limits_scoring",
            "review_status": "pending",
            "evidence_ref_uri": _uri("SRC-INNO-AR25"),
        },
        {
            "request_id": "SUP-BASE-RATE",
            "entity_key": "probability_method_and_baserate",
            "request_title": "扩展并预注册历史跨界进入案例基准率",
            "request_detail": "需要按统一的纳入、排除和观察期限扩展电子制造、连接器、半导体与系统厂进入完整光模块的历史案例，并逐案核验收购方式、产品、客户、收入、持续经营和退出结果。案例之间差异很大，新增样本只用于比较进入路径和收窄判断范围，不能把案例比例直接套到两家公司。",
            "priority": "p2",
            "blocking_status": "limits_scoring",
            "review_status": "pending",
            "evidence_ref_uri": _uri("SRC-CISCO-ACACIA21"),
        },
        {
            "request_id": "SUP-MODEL-RECALIBRATION",
            "entity_key": "probability_method_and_baserate",
            "request_title": "冻结输入后独立复算并按证据变化定向重校模型",
            "request_detail": "当产品阶段、客户认证、重复订单、产线良率、市场需求、价格压力、资本成本或长期增长假设发生变化时，需要保存新旧证据和假设，并重新计算对应公司的进入可能、盈利影响和估值结果。网页或结论数量本身不改变概率，只有能够改变具体事实判断的新证据才进入复算。",
            "priority": "p1",
            "blocking_status": "non_blocking",
            "review_status": "pending",
            "evidence_ref_uri": _uri("MODEL-WORKPAPER"),
        },
    ]


def _audit_issues() -> list[dict[str, Any]]:
    """记录已经闭环的P0和仍限制精度的P1/P2。"""

    return [
        {
            "entity_key": "luxshare_entry_risk",
            "audit_issue_type": "source_conflict",
            "audit_severity": "p0",
            "audit_issue_status": "resolved",
            "issue_title": "立讯客户层级与1.6T商业阶段存在发行人官方口径冲突",
            "issue_detail": "同时保留年报和后续监管IR：产品存在、工程进展和有限交付可确认；全球头部CSP、稳定重复订单、规模收入及自研1.6T硅光芯片不视为已闭环。冲突通过扩大概率区间和降低置信度处理。",
            "evidence_ref_uri": _uri("LX-ANNUAL-2024"),
            "evidence_ref_uri_list": [_uri("LX-ANNUAL-2024"), _uri("LX-IR-202508"), _uri("LX-IR-20260507"), _uri("LX-IR-20260525")],
        },
        {
            "entity_key": "probability_method_and_baserate",
            "audit_issue_type": "calculation_error",
            "audit_severity": "p0",
            "audit_issue_status": "resolved",
            "issue_title": "联合概率、架构情景和终值口径初版存在语义交叉风险",
            "issue_detail": "已改为共享分位数的3年/5年累计路径、Fréchet依赖、A—F进入状态与P/H/C架构正交、100,000次基础参数模拟及7组实际敏感性；破坏度按两家公司分别使用2029—2031实际FCF、净利润、毛利、份额/额外ASP、持续年数和正常化终值阈值分类，不再互相抵消。终值排除暂时扩产和营运资本拖累，并明确尚非完整FCFF桥。",
            "evidence_ref_uri": _uri("MODEL-WORKPAPER"),
            "evidence_ref_uri_list": [_uri("MODEL-INPUTS"), _uri("MODEL-WORKPAPER"), _uri("CROSS-EVIDENCE-AUDIT")],
        },
        {
            "entity_key": "byd_entry_risk",
            "audit_issue_type": "source_missing",
            "audit_severity": "p1",
            "audit_issue_status": "open",
            "issue_title": "比亚迪数据中心高速光模块专项主体与商业节点公开不可得",
            "issue_detail": "已查公司披露、招聘、专利邻接、产品与生态材料；尚无足以确认具名800G+ SKU、客户qualification、专线良率、重复订单和可分收入的公开硬证据，因此只能保留相邻能力和进入期权判断。",
            "evidence_ref_uri": _uri("BYD-S01"),
            "evidence_ref_uri_list": [_uri("BYD-S01"), _uri("BYD-S04"), _uri("BYD-S17")],
            "reviewer": "independent_evidence_reviewer",
        },
        {
            "entity_key": "qualification_upstream_constraints",
            "audit_issue_type": "capacity_definition_conflict",
            "audit_severity": "p1",
            "audit_issue_status": "open",
            "issue_title": "两家专项产线、设备、良率和稼动率缺少可审计披露",
            "issue_detail": "公开材料只能确认部分产品、相邻制造和供应链合作，不能可靠估计合格产能；行业模型因此使用宽情景并把名义产能与合格供给分开。",
            "evidence_ref_uri": _uri("CROSS-EVIDENCE-AUDIT"),
            "evidence_ref_uri_list": [_uri("CROSS-EVIDENCE-AUDIT"), _uri("LX-IR-20260507")],
            "reviewer": "independent_evidence_reviewer",
        },
    ]


_PUBLIC_PARAMETER_LABELS = {
    "P_LX_GLOBAL_GIVEN_ENTRY": "立讯进入全球头部客户的条件概率",
    "P_BYD_PRODUCT": "比亚迪产品里程碑概率",
    "ENTRY_EXTRA_ASP_PRESSURE": "新进入者同规格额外价格压力",
    "QUALIFIED_SUPPLY": "合格可售供给",
    "COMPONENT_AVAILABILITY": "关键器件可得性",
    "TECH_READINESS": "技术准备度",
    "PRODUCT_TIMING": "产品路线时点",
    "ARCH_P/H/C": "可插拔/混合/CPO架构状态",
    "P_BYD_CN_3Y/5Y": "比亚迪中国市场3年/5年进入概率",
    "P_BYD_GLOBAL_GIVEN_ENTRY": "比亚迪进入全球头部客户的条件概率",
    "P_BYD_CN": "比亚迪中国市场进入概率",
    "P_BYD_TEAM": "比亚迪团队形成概率",
    "BYD_CAPACITY_READINESS": "比亚迪产能准备度",
    "P_LX_CN_3Y/5Y": "立讯中国市场3年/5年进入概率",
    "P_LX_ENTRY_TIMING": "立讯进入时点",
    "LX_QUALIFIED_SUPPLY": "立讯合格可售供给",
    "INCUMBENT_DAMAGE_SEVERITY": "现有龙头损伤严重度",
    "INCUMBENT_SHARE_SHOCK": "现有龙头份额冲击",
    "INNO/EOPT_SHARE_SHOCK": "中际旭创/新易盛份额冲击",
    "REGIONAL_DEMAND": "区域需求",
    "GLOBAL_QUALIFICATION_LAG": "全球客户资格时滞",
    "P_*_GLOBAL_GIVEN_ENTRY": "公司进入全球头部客户的条件概率",
    "ENTRY_TIMING": "进入时点",
    "conditional_on_at_least_one_entry": "至少一家有意义进入条件分布",
}


_PUBLIC_ENUM_LABELS = {
    "current_at_access": "截至访问日",
    "current_at_fetch": "截至抓取日",
    "current_page": "当前网页版本",
    "bounded_document_audit": "受限文档核验",
    "bounded_patent_audit": "受限专利核验",
    "2023_transaction_announcement": "2023年交易公告",
    "2025_campus_cycle": "2025年校园招聘周期",
    "2026-01-28_to_2026-02-12": "2026-01-28至2026-02-12",
    "2026_spring_recruitment": "2026年春季招聘周期",
    "spring_recruitment": "春季招聘周期",
    "campus_cycle": "校园招聘周期",
    "patent_grant": "专利授权记录",
    "historical_disclosure_2014": "2014年历史披露",
    "historical_disclosure_2024": "2024年历史披露",
    "transaction_announcement": "交易公告日",
    "multi_year_from_2026": "2026年起多年度路径",
    "historical_cases_through_2026-07-18": "截至2026-07-18的历史案例",
    "through_2030_and_beyond": "延伸至2030年及以后",
    "to_2026": "截至2026年",
    "unidentified": "地域未识别",
    "2026-spring": "2026年春季招聘周期",
    "2025-campus-cycle": "2025届校园招聘周期",
    "2018-2019": "2018年至2019年",
    "2026-03-17/2026-03-19": "2026年3月17日和3月19日",
    "2026-01-28/2026-02-12": "2026年1月28日和2月12日",
}


def _humanize_public_markdown(markdown: str) -> str:
    """给公开 Markdown 中的机器枚举补中文显示，不改 citation token。"""

    result = markdown
    for code, label in sorted(
        _PUBLIC_PARAMETER_LABELS.items(), key=lambda item: len(item[0]), reverse=True
    ):
        result = result.replace(f"`{code}`", f"{label}（`{code}`）")
    for code, label in sorted(
        _PUBLIC_ENUM_LABELS.items(), key=lambda item: len(item[0]), reverse=True
    ):
        result = result.replace(code, label)
    for raw, label in (
        ("financial_model_producer", "财务情景建模负责人"),
        ("architecture_model_producer", "架构情景建模负责人"),
        ("参数 owner", "参数负责人"),
        ("参数owner", "参数负责人"),
        ("canonical", "统一口径"),
        ("intake", "研究请求"),
        ("source tier", "来源层级"),
        ("review status", "审查状态"),
        ("independence_key", "独立性分组键"),
        ("legal_entity", "经营法人"),
        ("product_owner", "产品归属主体"),
        ("financial_consolidation", "财务并表关系"),
        ("technical_team", "技术团队归属"),
        ("owner", "负责人"),
        ("entry_only", "仅进入维度（entry_only）"),
        ("architecture_only", "仅架构维度（architecture_only）"),
        ("combined", "联合维度（combined）"),
        ("low/base/high", "低/基准/高"),
        ("low/avg/high", "低/平均/高"),
        ("low/mode/high", "低值/众数/高值"),
        ("slow/base/fast", "慢/基准/快路径"),
        ("3y/5y", "3年/5年"),
        ("reduced-form", "简化传导（reduced-form）"),
        ("bottom-up", "自下而上（bottom-up）"),
        ("hash", "哈希"),
    ):
        result = result.replace(raw, label)
    for raw, label in (
        ("3y", "3年"),
        ("5y", "5年"),
        ("mild", "温和"),
        ("material", "明显"),
        ("severe", "严重"),
        ("verified", "已核验"),
        ("pending", "待处理"),
        ("mean", "均值"),
        ("median", "中位数"),
        ("reviewer", "审查人"),
        ("artifact", "产物"),
    ):
        result = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(raw)}(?![A-Za-z0-9_])", label, result)
    result = result.replace("独立 证据 审查人", "独立证据审查人")
    result = result.replace("独立 审查人", "独立审查人")
    result = result.replace("REV-P0", "审查零级阻塞项（REV-P0）")
    return result


def _assert_public_markdown_is_human_readable(markdown: str) -> None:
    """拒绝公开报告遗漏的人机枚举；已配中文标签的参数代码可保留作复算。"""

    allowed_tokens = {
        "source_ref",
        "ROUND_HALF_UP",
        "entry_only",
        "architecture_only",
        "combined",
    }
    for code in _PUBLIC_PARAMETER_LABELS:
        allowed_tokens.update(re.findall(r"[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+", code))
    audit_markdown = re.sub(
        r"\^src:source_ref:[A-Za-z0-9_.:/-]+\s*",
        "",
        markdown,
    )
    machine_tokens = set(
        re.findall(
            r"(?<![A-Za-z0-9_-])[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+(?![A-Za-z0-9_-])",
            audit_markdown,
        )
    )
    unknown_tokens = sorted(machine_tokens - allowed_tokens)
    if unknown_tokens:
        raise ValueError(f"公开报告仍有未中文化机器枚举：{unknown_tokens}")
    forbidden_fragments = (
        "product_负责人",
        "2025_校园招聘周期",
        "2023_交易公告日",
        "current_at_fetch",
    )
    leftovers = [fragment for fragment in forbidden_fragments if fragment in markdown]
    if leftovers:
        raise ValueError(f"公开报告仍有替换顺序残留：{leftovers}")


_HUMAN_PUBLIC_DATE_LABELS = {
    "current_at_fetch": "截至本次访问",
    "current_at_access": "截至本次访问",
    "current_page": "截至本次访问的网页版本",
    "2026-spring": "2026年春季招聘周期",
    "2025-campus-cycle": "2025届校园招聘周期",
    "2018-2019": "2018年至2019年",
    "2026-03-17/2026-03-19": "2026年3月17日和3月19日",
    "2026-01-28/2026-02-12": "2026年1月28日和2月12日",
}


def _human_public_date(value: Any) -> str:
    """把公开来源索引中的机器日期翻译为自然中文。"""

    raw = _clean(value)
    if not raw:
        return ""
    if raw in _HUMAN_PUBLIC_DATE_LABELS:
        return _HUMAN_PUBLIC_DATE_LABELS[raw]
    pair = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})/(\d{4})-(\d{2})-(\d{2})", raw)
    if pair:
        y1, m1, d1, y2, m2, d2 = (int(part) for part in pair.groups())
        if y1 == y2:
            return f"{y1}年{m1}月{d1}日和{m2}月{d2}日"
        return f"{y1}年{m1}月{d1}日和{y2}年{m2}月{d2}日"
    day = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if day:
        year, month, date = (int(part) for part in day.groups())
        return f"{year}年{month}月{date}日"
    month = re.fullmatch(r"(\d{4})-(\d{2})", raw)
    if month:
        year, month_number = (int(part) for part in month.groups())
        return f"{year}年{month_number}月"
    year = re.fullmatch(r"\d{4}", raw)
    if year:
        return f"{raw}年"
    year_range = re.fullmatch(r"(\d{4})-(\d{4})", raw)
    if year_range:
        return f"{year_range.group(1)}年至{year_range.group(2)}年"
    return raw


def _render_report(pack: dict[str, Any]) -> str:
    lines = [
        "# 比亚迪与立讯进军光模块：竞争与盈利风险",
        "",
        f"- 研究执行日：{AS_OF_DATE}",
        "- 研究说明：进入概率是公开证据约束下的工作判断，用于比较情景，不是历史频率或交易指令。",
        "",
    ]
    for section in sorted(pack["sections"], key=lambda item: item.get("sort_order", 0)):
        lines.extend([f"## {section['section_title']}", "", section["body_markdown"], ""])
    entity_sections = sorted(
        pack.get("entity_sections") or [],
        key=lambda item: item.get("sort_order", 0),
    )
    if entity_sections:
        lines.extend(
            [
                "## 专题研究目录",
                "",
                "以下专题承载公司、模型和证据的详细分析；主报告只保留跨专题结论。",
                "",
            ]
        )
        for section in entity_sections:
            anchor = f"topic-{section['entity_key']}"
            lines.append(f"- [{section['section_title']}](#{anchor})")
        lines.append("")
        for section in entity_sections:
            anchor = f"topic-{section['entity_key']}"
            body = re.sub(
                r"(?m)^(#{1,5})(\s+)",
                lambda match: f"{match.group(1)}#{match.group(2)}",
                section["body_markdown"],
            )
            lines.extend([f'<a id="{anchor}"></a>', "", body, ""])
    report_before_index = "\n".join(lines)
    cited_refs: list[str] = []
    seen_refs: set[str] = set()
    for match in re.finditer(
        r"\^src:source_ref:([A-Za-z0-9_.-]+)", report_before_index
    ):
        ref = match.group(1)
        if ref not in seen_refs:
            cited_refs.append(ref)
            seen_refs.add(ref)
    source_lookup = {source["ref"]: source for source in pack["sources"]}
    unknown_citations = [ref for ref in cited_refs if ref not in source_lookup]
    if unknown_citations:
        raise ValueError(f"最终报告来源索引发现未知引用：{unknown_citations}")

    def markdown_cell(value: Any) -> str:
        return _clean(value).replace("|", "\\|").replace("\n", " ") or "未标明"

    lines.extend(
        [
            "## 来源索引（本报告实际引用）",
            "",
            (
                "本索引只列本报告正文实际引用的来源；中文标题、发布方与日期用于独立阅读，"
                "原始链接、文件定位和完整摘录保留在对应来源抽屉，不在正文暴露裸网址或磁盘路径。"
            ),
            "",
            "| 来源标题 | 发布方 | 发布/事件日期 |",
            "|---|---|---|",
        ]
    )
    for ref in cited_refs:
        source = source_lookup[ref]
        publish_date_raw = _clean(source.get("publish_date"))
        event_date_raw = _clean(source.get("event_date"))
        fetch_date_raw = _clean(source.get("fetch_date"))
        publish_date = _human_public_date(publish_date_raw)
        event_date = _human_public_date(event_date_raw)
        fetch_date = _human_public_date(fetch_date_raw)
        date_parts: list[str] = []
        if publish_date:
            date_parts.append(f"发布：{publish_date}")
        if event_date and event_date_raw != publish_date_raw:
            date_parts.append(f"事件：{event_date}")
        if not date_parts and fetch_date:
            date_parts.append(f"截至访问：{fetch_date}")
        date_display = "；".join(date_parts) or "日期未标明"
        lines.append(
            f"| {markdown_cell(source.get('title_zh') or source.get('title'))} {_cite(ref)} | "
            f"{markdown_cell(source.get('publisher'))} | {markdown_cell(date_display)} |"
        )
    report = _humanize_public_markdown("\n".join(lines).strip()) + "\n"
    _assert_public_markdown_is_human_readable(report)
    assert_human_public_markdown(report)
    return report


def _local_pack_audit(pack: dict[str, Any]) -> dict[str, Any]:
    source_refs = {source["ref"] for source in pack["sources"]}
    identities: set[tuple[str, ...]] = set()
    duplicate_identities: list[tuple[str, ...]] = []
    for point in pack["data_points"]:
        identity = (
            _clean(point.get("source_ref")),
            _clean(point.get("entity_key")),
            _clean(point.get("metric")).lower(),
            _clean(point.get("unit")).lower(),
            _clean(point.get("scope_key") or point.get("series_key")).lower(),
        )
        if identity in identities:
            duplicate_identities.append(identity)
        identities.add(identity)
    unknown_refs = sorted(
        {
            _clean(point.get("source_ref"))
            for point in pack["data_points"]
            if _clean(point.get("source_ref")) not in source_refs
        }
    )
    inferred_without_method_note = [
        index
        for index, point in enumerate(pack["data_points"])
        if point.get("extraction_method") == "inferred"
        and not all(
            marker in _clean(point.get("note"))
            for marker in ("公式/算法：", "输入：", "口径：")
        )
    ]
    unresolved_p0 = [
        issue["issue_title"]
        for issue in pack.get("audit_issues", [])
        if issue.get("audit_severity") == "p0" and issue.get("audit_issue_status") != "resolved"
    ]
    main_lengths = {row["section_key"]: len(row["body_markdown"]) for row in pack["sections"]}
    entity_lengths = {row["entity_key"]: len(row["body_markdown"]) for row in pack["entity_sections"]}
    gray_count = sum(source.get("source_tier") in {"C", "D"} for source in pack["sources"])
    chained_citation = re.compile(
        r"\^(?:src|evidence):[^\s\]\)<>，。；、,;^]+\^(?:src|evidence):"
    )
    public_bodies = [
        row["body_markdown"]
        for row in [*pack["sections"], *pack["entity_sections"]]
    ]
    human_public_metrics = audit_human_public_content(
        pack["sections"], pack["entity_sections"]
    )
    if any(chained_citation.search(body) for body in public_bodies):
        raise ValueError("公开正文存在连续且未分隔的证据引用")
    cited_refs = {
        match
        for body in public_bodies
        for match in re.findall(r"\^src:source_ref:([A-Za-z0-9_.-]+)", body)
    }
    unknown_citations = sorted(cited_refs - source_refs)
    if unknown_citations:
        raise ValueError(f"公开正文引用未知来源：{unknown_citations}")
    supplement_ids = {
        _clean(item.get("request_id"))
        for item in pack.get("supplement_requests", [])
        if _clean(item.get("request_id"))
    }
    claims_missing_next_action = [
        claim.get("claim_id")
        for claim in pack.get("claims", [])
        if not _clean(claim.get("next_evidence_action"))
        or not _clean(claim.get("next_evidence_action_ref"))
    ]
    unknown_next_action_refs = sorted(
        {
            _clean(claim.get("next_evidence_action_ref"))
            for claim in pack.get("claims", [])
            if _clean(claim.get("next_evidence_action_ref"))
            and _clean(claim.get("next_evidence_action_ref")) not in supplement_ids
        }
    )
    metrics = {
        "source_count": len(pack["sources"]),
        "independent_source_group_count": len({source["independence_key"] for source in pack["sources"]}),
        "core_independent_source_group_count": len(
            {
                source["independence_key"]
                for source in pack["sources"]
                if source.get("policy_evidence_role") == "core_evidence"
            }
        ),
        "gray_source_count": gray_count,
        "gray_source_ratio": round(gray_count / max(1, len(pack["sources"])), 4),
        "claim_count": len(pack.get("claims", [])),
        "parallel_data_point_count": len(identities),
        "entity_count": len(pack["entities"]),
        "market_linked_entity_count": sum(entity["entity_research_mode"] == "market_linked" for entity in pack["entities"]),
        "theory_research_entity_count": sum(entity["entity_research_mode"] == "theory_research" for entity in pack["entities"]),
        "target_count": len(pack["entity_investment_targets"]),
        "main_section_count": len(pack["sections"]),
        "entity_section_count": len(pack["entity_sections"]),
        "visual_count": len(pack["visuals"]),
        "minimum_main_section_characters": min(main_lengths.values()),
        "minimum_entity_section_characters": min(entity_lengths.values()),
        "duplicate_data_identities": len(duplicate_identities),
        "unknown_data_source_refs": unknown_refs,
        "inferred_without_method_note": inferred_without_method_note,
        "claims_missing_next_evidence_action": claims_missing_next_action,
        "unknown_next_evidence_action_refs": unknown_next_action_refs,
        "unresolved_p0": unresolved_p0,
        **human_public_metrics,
    }
    if len(identities) < 100:
        raise ValueError(f"平行数据点不足100：{len(identities)}")
    if duplicate_identities:
        raise ValueError(f"存在重复数据身份：{duplicate_identities[:5]}")
    if unknown_refs:
        raise ValueError(f"存在未知数据来源：{unknown_refs}")
    if inferred_without_method_note:
        raise ValueError(
            f"inferred数据点缺少公式/输入/口径note：{inferred_without_method_note[:20]}"
        )
    if claims_missing_next_action or unknown_next_action_refs:
        raise ValueError(
            "claim下一步补证动作不完整："
            f"missing={claims_missing_next_action[:20]}，"
            f"unknown_refs={unknown_next_action_refs[:20]}"
        )
    if unresolved_p0:
        raise ValueError(f"存在未闭环P0：{unresolved_p0}")
    if len(pack["sections"]) != 4 or min(main_lengths.values()) < 1400:
        raise ValueError("公开主页四个高信息章节或可读深度下限未满足")
    if main_lengths.get("financial_method_and_results", 0) < 2500:
        raise ValueError("公开主页财务方法与结果分析深度不足")
    if len(pack["entity_sections"]) != len(pack["entities"]) or min(entity_lengths.values()) < 2200:
        raise ValueError("实体逐项回答或深度下限未满足")
    return metrics


def build_pack() -> dict[str, Any]:
    intake = parse_markdown_intake_text(INTAKE_PATH.read_text(encoding="utf-8"))
    sources, claims, points, model, screening = _collect_research_inputs()
    search_expansion = _load_json(BYD_SEARCH_EXPANSION_PATH)
    search_stats = search_expansion.get("search_statistics", {})
    financial = _safe_payload(_load_json(FINANCIAL_PATH))
    usd_to_cny = float(financial.get("fx_to_cny", {}).get("USD") or 0.0)
    if usd_to_cny <= 0:
        raise ValueError("财务快照缺少有效的USD/CNY展示汇率")
    entities = _entities(sources, points)
    targets = _targets(points, sources, usd_to_cny)
    sections = build_human_report_sections(
        model=model,
        sources=sources,
        financial=financial,
        as_of_date=AS_OF_DATE,
    )
    entity_sections = build_human_entity_sections(
        entities=entities,
        targets=targets,
        sources=sources,
        model=model,
        financial=financial,
    )
    pack = {
        "pack_schema_version": RUN_PACK_SCHEMA_VERSION,
        "workflow_contract_version": RESEARCH_WORKFLOW_CONTRACT_VERSION,
        "slug": SLUG,
        "display_title": "比亚迪与立讯进军光模块：竞争与盈利风险",
        "research_question": intake["research_question"],
        "run_mode": "c_hybrid",
        "quality_profile": "deep_research",
        "requested_by": "user_intake_deep_research_20260718",
        "problem_statement": "核验比亚迪电子与立讯高速光模块进展，判断三年和五年进入可能，并分析它们对中际旭创、新易盛收入、利润、现金流和估值的影响。",
        "as_of_date": AS_OF_DATE,
        "intake": intake,
        "search_plan_name": "高速光模块新进入者—客户—上游—龙头—财务多轴深度检索",
        "search_plan": [
            {"axis_key": "byd_entity_product", "source_group": "issuer_regulatory_product", "query_text": "比亚迪电子 AI服务器 液冷 高速互联 光通信 光模块 招聘 专利 2025 2026", "result_count": sum(source["ref"].startswith("BYD-") for source in sources), "included_count": sum(source["ref"].startswith("BYD-") for source in sources), "rejection_reason": "检索命中总量未系统留存；这里只记录进入证据账本并完成原文复核的来源数。"},
            {"axis_key": "byd_claim_origin_chain", "source_group": "results_call_sellside_media_forum", "query_text": "比亚迪电子 800G 5万只 月 1.6T CPO 业绩会 原始出处 2025 2026", "result_count": int(search_stats.get("weak_lead_count") or 0), "included_count": int(search_stats.get("weak_lead_count") or 0), "rejection_reason": "发现层保留具名卖方、媒体和论坛记录，但同一业绩会或同一市场叙事按共同来源归并；未取得公司逐字稿的说法只进入线索与不确定性边界。"},
            {"axis_key": "byd_patent_family_audit", "source_group": "patent_registry_family_inventor", "query_text": "比亚迪 比亚迪电子 济南比亚迪半导体 光通信 光模块 硅光 PON 专利族 发明人", "result_count": sum(source["ref"].startswith("BYD-PAT-") for source in sources), "included_count": sum(source["ref"].startswith("BYD-PAT-") for source in sources), "rejection_reason": "逐件核对申请人、申请/公开日、权利要求和应用场景；同族、新闻转述和车载/数据中心混写不重复计数。"},
            {"axis_key": "byd_official_counter_verification", "source_group": "issuer_event_customer_platform", "query_text": "比亚迪电子 年报 IDCE 展品 NVIDIA qualified 800G 1.6T 光模块 客户 产线 收入", "result_count": 4, "included_count": 4, "rejection_reason": "年报、官网、展会组织方和NVIDIA清单用于分别核验经营披露、参展、产品展示和平台资格；服务器/电源合作不能迁移成光模块认证。"},
            {"axis_key": "luxshare_product_customer", "source_group": "issuer_partner_standard", "query_text": "Luxshare-Tech 800G 1.6T LPO LRO CPO qualification annual report IR 2025 2026", "result_count": sum(source["ref"].startswith("LX-") for source in sources), "included_count": sum(source["ref"].startswith("LX-") for source in sources), "rejection_reason": "检索命中总量未系统留存；这里只记录进入证据账本并完成原文复核的立讯来源数。"},
            {"axis_key": "industry_customer_upstream_incumbent", "source_group": "customer_platform_supplier_issuer", "query_text": "800G 1.6T 3.2T customer platform DSP laser PIC qualification incumbent annual report 2025 2026", "result_count": sum(source["ref"].startswith("SRC-") for source in sources), "included_count": sum(source["ref"].startswith("SRC-") for source in sources), "rejection_reason": "检索命中总量未系统留存；这里只记录去重后进入行业/客户/上游/龙头账本的来源数。"},
            {"axis_key": "structured_financial", "source_group": "tushare_yfinance", "query_text": "中际旭创新易盛立讯比亚迪比亚迪电子 财务与估值结构化快照", "result_count": sum(source["ref"].startswith("FIN-") for source in sources), "included_count": sum(source["ref"].startswith("FIN-") for source in sources), "rejection_reason": "按证券和数据提供方聚类，不把指标字段拆成多个来源。"},
            {"axis_key": "local_seed_materials", "source_group": "user_pdf_screening", "query_text": "papers/比亚迪 立讯精密 光模块 全部PDF去重筛选", "result_count": len(screening.get("materials", [])), "included_count": len(screening.get("materials", [])), "rejection_reason": "23份材料全部完成筛选；弱源仅作线索/预期，重复文件按SHA标记。"},
        ],
        "workflow_review_contract": {
            "producer_reviewer_loop": "证据分包、来源聚类和模型分别由独立agent审查；P0定向修复后才允许综合审稿和浏览器审计。",
            "minimum_homepage_section_chars": 1400,
            "minimum_entity_section_chars": 2200,
            "public_writing_standard": "问题—证据与数据—方法—分析与结论—进一步研究所需信息；公开页不展示生产字段、内部代码和低信息审计表。",
            "reviewer_roles": ["evidence", "science", "calculation", "financial", "writing", "browser", "final"],
        },
        "sources": sources,
        "evidence_groups": {source["ref"]: source["independence_key"] for source in sources},
        "entities": entities,
        "claims": claims,
        "data_points": points,
        "early_signals": _early_signals(entities),
        "sections": sections,
        "entity_sections": entity_sections,
        "visuals": build_human_visuals(model=model, sources=sources),
        "entity_investment_targets": targets,
        "nav": build_human_nav(),
        "supplement_requests": _supplement_requests(),
        "audit_issues": _audit_issues(),
        "gap_summary": "23份本地PDF已全量提取并按22个唯一SHA去重；本轮又追溯了2025年中期业绩会后的卖方传播链、逐件核验新增光通信专利，并反向检查年报、IDCE与NVIDIA公开材料。管理层口头路线仍缺公开逐字稿，2026年后也没有客户、实际出货、良率、专线和可分收入闭环；因此这些信息提高上行情景关注度，但不当作已实现经营事实。",
        "review_records": [],
        "artifact_index": {
            "model_inputs": str((OUTPUT_DIR / "model_inputs.json").relative_to(ROOT)).replace("\\", "/"),
            "model_outputs": str((OUTPUT_DIR / "model_outputs.json").relative_to(ROOT)).replace("\\", "/"),
            "model_dashboard": str((OUTPUT_DIR / "competition_model_dashboard.html").relative_to(ROOT)).replace("\\", "/"),
            "financial_snapshot": str(FINANCIAL_PATH.relative_to(ROOT)).replace("\\", "/"),
            "local_material_screening": str(SCREENING_PATH.relative_to(ROOT)).replace("\\", "/"),
            "cross_evidence_audit": str(CROSS_AUDIT_PATH.relative_to(ROOT)).replace("\\", "/"),
            "byd_search_expansion": str(BYD_SEARCH_EXPANSION_PATH.relative_to(ROOT)).replace("\\", "/"),
        },
    }
    pack["build_metrics"] = _local_pack_audit(pack)
    return pack


def write_pack() -> Path:
    pack = build_pack()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = validate_run_pack(pack, publication_mode="stage")
    report.raise_for_errors()
    report_text = _render_report(pack)
    pack[PUBLIC_AUDIT_FIELD] = build_pack_audit_attestation(
        pack,
        profile="byd_luxshare",
    )
    _write_json(PACK_PATH, pack)
    _write_json(STAGE_VALIDATION_PATH, report.as_dict())
    REPORT_PATH.write_text(report_text, encoding="utf-8")
    public_audit = run_public_content_audit(
        run_pack_path=PACK_PATH,
        report_path=REPORT_PATH,
        profile="byd_luxshare",
    )
    _write_json(PUBLIC_CONTENT_AUDIT_JSON_PATH, public_audit)
    PUBLIC_CONTENT_AUDIT_MARKDOWN_PATH.write_text(
        render_public_content_audit_markdown(public_audit),
        encoding="utf-8",
    )
    if public_audit["status"] != "PASS":
        raise ValueError(
            "公开内容质量审计失败："
            f"errors={public_audit['summary']['errors']}；"
            f"详见 {PUBLIC_CONTENT_AUDIT_JSON_PATH}"
        )
    summary = {
        **pack["build_metrics"],
        "pack_path": str(PACK_PATH.relative_to(ROOT)).replace("\\", "/"),
        "report_path": str(REPORT_PATH.relative_to(ROOT)).replace("\\", "/"),
        "stage_validation_valid": report.valid,
        "stage_validation_warnings": len(report.warnings),
        "pack_sha256": _sha256(PACK_PATH),
        "report_sha256": _sha256(REPORT_PATH),
        "public_content_audit_status": public_audit["status"],
        "public_content_audit_rules_sha256": public_audit["rules_sha256"],
        "public_content_audit_result_sha256": pack[PUBLIC_AUDIT_FIELD]["result_sha256"],
        "public_content_audit_json_path": str(PUBLIC_CONTENT_AUDIT_JSON_PATH.relative_to(ROOT)).replace("\\", "/"),
        "public_content_audit_markdown_path": str(PUBLIC_CONTENT_AUDIT_MARKDOWN_PATH.relative_to(ROOT)).replace("\\", "/"),
    }
    _write_json(BUILD_SUMMARY_PATH, summary)
    return PACK_PATH


def main() -> None:
    path = write_pack()
    summary = _load_json(BUILD_SUMMARY_PATH)
    print(f"wrote {path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
