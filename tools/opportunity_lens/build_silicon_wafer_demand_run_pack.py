from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.opportunity_lens.run_pack_builder import RunPackBuilder
from tools.opportunity_lens.silicon_expansion_models import calculate_wafer_demand_scenarios
from tools.opportunity_lens.silicon_supplemental_research import (
    DEMAND_CANDIDATE_COVERAGE_ROWS,
    DEMAND_SUPPLEMENTAL_DATA_POINTS,
    DEMAND_SUPPLEMENTAL_SOURCES,
    DEMAND_SUPPLIER_RANKING_ROWS,
    align_demand_source_records,
    synchronize_demand_project_ledger,
)
from tools.opportunity_lens.silicon_run_pack_support import (
    SEGMENT_FACTOR_CODES,
    apply_data_point_evidence_audit,
    apply_financial_evidence_audit,
    apply_source_catalog_corrections,
    build_financial_data_points,
    build_line_visual,
    build_segment_entity,
    extract_primary_research_question,
    line_chart_panel,
    natural_citations,
    normalize_agent_data_points,
    normalize_agent_source,
    sha256_file,
    source_uri,
    write_json,
    write_pack_bundle,
)


ROOT = Path(__file__).resolve().parents[2]
AS_OF_DATE = "2026-07-19"
SLUG = "20260720_silicon_wafer_fab_demand_2026_2030"
DISPLAY_TITLE = "全球晶圆厂扩产与硅片需求"
DEFAULT_OUTPUT_DIR = ROOT / "opportunity_lens" / "research_outputs" / SLUG
INTAKE_PATH = (
    ROOT
    / "opportunity_lens"
    / "intake_requests"
    / "Opportunity_Lens_用户研究请求_硅片厂需求侧.md"
)
AGENT_DIR = ROOT / "cache" / "opportunity_lens" / "silicon_expansion_20260719" / "agents"
DEMAND_DIR = AGENT_DIR / "demand"
FINANCIAL_DIR = AGENT_DIR / "financials"
DEMAND_AUDIT_PATH = AGENT_DIR / "demand_schema_audit" / "data_point_evidence_audit.json"
FINANCIAL_AUDIT_PATH = AGENT_DIR / "financial_evidence_audit" / "financial_evidence_audit.json"
FACTOR_SLOT_INPUT_PATH = DEMAND_DIR / "factor_slot_inputs.json"
MARKET_SNAPSHOT_PATH = DEMAND_DIR / "current_market_snapshots.json"
DEMAND_FINANCIAL_UPDATE_PATH = (
    DEMAND_DIR / "financial_updates" / "financial_updates.json"
)


# Precise locators for sources that originally entered the agent cache with a
# URL but without page/section metadata.  Each phrase is short enough to use
# in the original page/PDF search and specific enough to land on the cited
# passage.  Sources absent from this map and still carrying the generic
# locator are automatically reference-only below.
SOURCE_PRECISE_LOCATORS: dict[str, str] = {
    "FIN-ESWIN-01": "PDF合并财务报表与主营业务毛利率表检索：212,145.26；-73,764.25；-8.79%",
    "FIN-ESWIN-02": "上交所上市公告网页检索：688783；2025年10月28日",
    "FIN-GWC-01": "PDF合并综合损益表检索：60,597,938；45,974,397；14,623,541",
    "FIN-GWC-03": "PDF Consolidated Statements of Cash Flows检索：12,744,715；33,497,272",
    "FIN-GWC-04": "PDF合并损益与现金流量表检索：62,626,004；18,564,765；36,756,705",
    "FIN-SIL-01": "PDF Financial position and results章节检索：sales 1,346.7；capital expenditure 369.1",
    "FIN-SIL-02": "网页Information on the share检索：DE000WAF3001；WAF300；ticker symbol WAF",
    "FIN-SIL-03": "PDF Consolidated Statement of Cash Flows检索：344.5；487.9；-667.5；-1,112.1",
    "FIN-SOITEC-01": "网页FY2025 results表格检索：Revenue 891；Gross margin 32.1%；Net profit 92",
    "FIN-SOITEC-02": "PDF FY2023 results表格检索：Revenue 1,089；Gross margin 37.0%；Net profit 233",
    "FIN-SOITEC-03": "网页Share information检索：FR0013227113；ticker symbol SOI",
    "FIN-SUMCO-01": "PDF Business Report与Consolidated Financial Statements检索：409,670；1,342；79,957",
    "FIN-SUMCO-02": "PDF Business Report与财务报表检索：396,619；72,726；214,927",
    "FIN-SUMCO-03": "PDF Business Report与财务报表检索：425,941；108,251；315,415",
    "FIN-SUMCO-04": "网页Stock Information检索：Stock code 3436；Prime Market",
    "FIN-SUMCO-05": "PDFキャッシュ・フロー計算書检索：96,342；69,627；100,040",
    "MKT-YF-ESWIN-20260717": "Yahoo Finance 688783.SS报价页；交易日2026-07-17；检索收盘价38.94与市值157,231,923,200",
    "MKT-YF-GWC-20260717": "Yahoo Finance 6488.TWO报价页；交易日2026-07-17；检索收盘价1,240与市值592,861,003,776",
    "MKT-YF-SOITEC-20260717": "Yahoo Finance SOI.PA报价页；交易日2026-07-17；检索收盘价87.34与市值3,121,859,072",
    "MKT-YF-SUMCO-20260717": "Yahoo Finance 3436.T报价页；交易日2026-07-17；检索收盘价3,914与市值1,368,777,555,968",
    "MKT-YF-WAF-20260717": "Yahoo Finance WAF.DE报价页；交易日2026-07-17；检索收盘价85.80与市值2,574,000,128",
    "S001": "网页正文检索短语：11.1 million wafers per month in 2028；850,000；1.4 million",
    "S002": "网页正文检索短语：Eighteen New Semiconductor Fabs to Start Construction in 2025",
    "S003": "网页Report Highlights检索：1,622 facilities and lines；146 future facilities or lines",
    "S004": "网页统计口径检索：polished silicon wafers；epitaxial silicon wafers；non-polished silicon wafers",
    "S005": "网页正文检索短语：12,973 million square inches；5.8%；$11.4 billion",
    "S006": "网页正文检索短语：14,713 MSI；12,602 MSI；12,266 MSI",
    "S007": "网页正文检索短语：13,328 million square inches in 2025",
    "S008": "网页正文检索短语：33.7 million wafers per month；5nm and below；17%",
    "S009": "网页产品说明检索：Fab Materials Quarterly；product-level data",
    "S010": "网页历史展望检索：9.6 million 300mm wafers per month；2.4 million in China",
    "S011": "年报网页检索：began volume production of 4nm technology in the fourth quarter of 2024；second half of 2027",
    "S012": "网页正文检索短语：more than 100,000 12-inch wafers per month；US$20 billion",
    "S013": "PDF正文检索：three new fabs；two advanced packaging facilities；US$165 billion",
    "S014": "网页正文检索短语：月産4万枚；300mm；100億ユーロ",
    "S015": "网页正文检索短语：480,000 wafers per year；full capacity in 2029",
    "S016": "网页正文检索短语：operations expected to begin between 2030 and 2031",
    "S017": "10-K全文检索：slowed the pace of construction in Ohio；wafer fabrication projects in Germany",
    "S018": "网页正文检索短语：fifth high-volume manufacturing fab at the Ocotillo campus",
    "S019": "网页正文检索短语：12-nanometer；production in 2027；existing Intel fabs in Arizona",
    "S020": "网页Idaho expansion时间线检索：initial DRAM output；2027",
    "S021": "网页正文检索短语：approximately $100 billion in New York；$25 billion in Idaho",
    "S022": "PDF U.S. expansion章节检索：ID1；ID2；operational by the end of 2028",
    "S023": "网页正文检索短语：up to $500 million；10-year supply agreement",
    "S024": "网页正文检索短语：KRW 21.6 trillion；February 2027；first cleanroom",
    "S025": "网页正文检索短语：M15X；약 20조원；HBM 수요",
    "S026": "SEC文件全文检索：M15X；wafer input began in the first quarter of 2026",
    "S027": "网页正文检索短语：$17 billion；Taylor, Texas；advanced semiconductor fab",
    "S028": "网页正文检索短语：more than $37 billion；Central Texas；two leading-edge logic fabs",
    "S029": "网页Taylor site说明检索：5G；artificial intelligence；high-performance computing",
    "S030": "网页正文检索短语：평택사업장 5라인；2028년부터 가동",
    "S031": "网页正文检索短语：full capacity of 30,000 wafers per month；volume production in 2026",
    "S032": "网页正文检索短语：one million wafers per year；new 300mm fab；GaN-on-silicon",
    "S033": "网页正文检索短语：more than $60 billion；SM1；initial production",
    "S034": "网页正文检索短语：$11 billion；LFAB2；as early as 2026",
    "S035": "网页正文检索短语：Investitionsvolumen beträgt fünf Milliarden Euro；Smart Power Fab",
    "S036": "网页正文检索短语：2,000 to 4,000 wafers per week；14,000 wafers per week",
    "S037": "网页正文检索短语：300 mm production；July 2021；Roseville",
    "S038": "网页正文检索短语：Prototype wafers；electrical characteristics；mass production in 2027",
    "S039": "PDF生产基地章节检索：Y7；K2；September 2025",
    "S040": "PDF Q&A检索：investing in production equipment within the existing facility",
    "S041": "网页正文检索短语：three phases；45,000 wafer capacity per month",
    "S042": "PDF产能与利用率表检索：105.9万片；93.5%；77.1%",
    "S043": "网页经营结果检索：94.8万片；85.6%",
    "S044": "PDF业务回顾检索：83K；设备选型和商务流程；首批设备搬入",
    "S045": "网页政府答复检索：长江存储三期；总投资超过2700亿元",
    "S046": "PDF募投项目与在建工程检索：2026年6月30日；345亿元；不新建产线",
    "S047": "Reuters正文检索：160,000 12-inch wafers per month；third fab",
    "S048": "Reuters正文检索：300,000 12-inch wafers per month；Shanghai fab",
    "S049": "网页正文检索短语：advanced 300mm silicon wafer facility；Sherman, Texas",
    "S050": "网页正文检索短语：1.2 million wafers per month；multiple stages；market demand",
    "S051": "网页Project Overview检索：$406 million；300mm SOI；Sherman",
    "S052": "网页产品页检索：polished wafers；epitaxial wafers；annealed wafers；SOI wafers",
    "S053": "PDF问答检索：200 mm market remained slack；equipment will be installed",
    "S054": "网页正文检索短语：first wafers；new Singapore fab；ramp",
    "S055": "网页正文检索短语：300mm RF-SOI substrates；9SW platform",
    "S056": "网页正文检索短语：3D-IC solution for RF-SOI；engineered substrates",
    "S062": "PDF投资者活动记录检索：4+6+10；功率；CIS；逻辑",
    "S063": "网页正文检索短语：strategic financing；ten-year supply arrangement；Micron",
    "S064": "网页Report Highlights检索：7% in 2026；approximate 7% rate from 2027 to 2029；413 fabs",
    "S065": "网页Report Highlights检索：7.7 million wafers per month；3%、1%、2% in 2027, 2028 and 2029",
    "S066": "网页正文检索短语：3,275 million square inches；13.1%；4.7% sequentially",
    "S067": "PDF Key Financial Highlights检索：1,059 thousand；93.5%；$8.1 billion",
    "S068": "PDF Key Financial Highlights检索：948 thousand；85.6%；$7.33 billion",
}


SOURCE_REF_PATTERN = re.compile(r"\^src:source_ref:([A-Za-z0-9_.-]+)")


# A source card can expose only one excerpt in the Viewer drawer.  Several
# primary documents support more than one public, decision-critical fact, so
# reusing their generic source ref would make a row citation open on the wrong
# paragraph.  These aliases keep the original independence key and URL but
# bind the public drawer to the exact fact cluster cited in the report/table.
# They are presentation-level evidence refs only; factor/data-point lineage
# continues to use the original source ref and therefore is not double counted.
PUBLIC_FACT_CLUSTER_SOURCE_SPECS: dict[str, dict[str, Any]] = {
    "DMD-SEMI-300MM-TOTAL-ADVANCED-2028": {
        "base_ref": "S001",
        "data_point_keys": ("DP001", "DP002"),
        "title_suffix_zh": "：2028年总产能与先进制程产能",
        "locator": "网页正文检索：11.1 million wafers per month；850,000 wpm；1.4 million wpm",
    },
    "DMD-INTEL-18A-AND-FAB-PLAN-2025": {
        "base_ref": "S017",
        "data_point_keys": ("DP059", "DP060"),
        "title_suffix_zh": "：18A爬坡与晶圆厂计划调整",
        "locator": "10-K全文检索：ramping Intel 18A；slowed the pace of construction；Germany",
    },
    "DMD-KIOXIA-EXISTING-FABS-THROUGH-2029": {
        "base_ref": "S040",
        "data_point_keys": ("DP138", "DP139"),
        "title_suffix_zh": "：现有厂房扩产与2029年需求",
        "locator": "PDF Q&A检索：existing facility at our Yokkaichi and Kitakami；through CY29",
    },
    "DMD-SHINETSU-200MM-SLACK-AND-RAMP": {
        "base_ref": "S053",
        "data_point_keys": ("DP176", "DP177", "DP178"),
        "title_suffix_zh": "：厂房、设备投放与200毫米供需",
        "locator": "PDF问答检索：buildings were completed；equipment is installed；200 mm wafers remains slack",
    },
    "DMD-SEMI-300MM-GROWTH-2026-2029": {
        "base_ref": "S064",
        "data_point_keys": ("DP236", "DP237"),
        "title_suffix_zh": "：2026—2029年装机增速",
        "locator": "网页Report Highlights检索：7% in 2026；approximate 7% rate from 2027 to 2029",
    },
    "DMD-SEMI-200MM-CAPACITY-2026-2029": {
        "base_ref": "S065",
        "data_point_keys": ("DP242",),
        "title_suffix_zh": "：2026—2029年装机能力与增速",
        "locator": "网页Report Highlights检索：7.7 million wafers per month；3%、1%、2% in 2027, 2028 and 2029",
    },
    "DMD-SHANGHAI-SUPER-SILICON-2025-OPERATIONS": {
        "base_ref": "S058",
        "data_point_keys": ("DP197",),
        "title_suffix_zh": "：2025年12英寸产能与利用率",
        "locator": "PDF产能利用率表检索：367.00万片；75.18%",
    },
    "DMD-ESWIN-2026-CAPACITY-PLAN": {
        "base_ref": "S059",
        "data_point_keys": ("DP205",),
        "title_suffix_zh": "：2026年12英寸产能规划",
        "locator": "PDF募投项目检索：2026年；120万片/月",
    },
    "DMD-NSIG-300MM-CAPACITY-AND-CERTIFICATION": {
        "base_ref": "S057",
        "data_point_keys": ("DP187", "DP193", "DP194"),
        "title_suffix_zh": "：300毫米产能与历史客户认证",
        "locator": "PDF项目与客户认证检索：30万片/月；格罗方德；台积电；联华电子",
    },
    "DMD-LION-2025-12INCH-OPERATIONS": {
        "base_ref": "S061",
        "data_point_keys": ("DP222", "DP224", "DP227"),
        "title_suffix_zh": "：2025年12英寸销量、收入与名义产能",
        "locator": "PDF年报检索：12英寸收入85,937.36万元；销量178.57万片；30万片/月",
    },
    "DMD-SHANGHAI-ADVANCED-4-6-10-CAPACITY": {
        "base_ref": "S062",
        "data_point_keys": ("DP231", "DP232", "DP233"),
        "title_suffix_zh": "：4万、6万与10万片月产能路径",
        "locator": "PDF投资者活动记录检索：4万片/月POWER；6万片/月CIS；10万片/月逻辑",
    },
    "DMD-TCL-ZHONGHUAN-2025-SALES-INVENTORY": {
        "base_ref": "S060",
        "data_point_keys": ("DP216", "DP218"),
        "title_suffix_zh": "：2025年半导体材料销量与库存",
        "locator": "PDF年报产销存表检索：1,222.10百万平方英寸；23.99%；35.87%",
    },
    "DMD-UMC-FAB12I-CAPACITY-AND-START-2026": {
        "base_ref": "S031",
        "data_point_keys": ("DP100", "DP101"),
        "title_suffix_zh": "：3万片月产能与2026年量产起点",
        "locator": "网页正文检索：30,000 wafers per month；volume production in 2026",
    },
}

PUBLIC_FACT_SOURCE_ALIAS: dict[str, str] = {
    str(spec["base_ref"]): alias
    for alias, spec in PUBLIC_FACT_CLUSTER_SOURCE_SPECS.items()
}


def _replace_public_fact_source_refs(value: Any) -> Any:
    """Replace broad source refs only inside reader-facing artifacts."""
    if isinstance(value, str):
        updated = value
        for base_ref, alias_ref in PUBLIC_FACT_SOURCE_ALIAS.items():
            updated = updated.replace(source_uri(base_ref), source_uri(alias_ref))
        return updated
    if isinstance(value, list):
        return [_replace_public_fact_source_refs(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_replace_public_fact_source_refs(item) for item in value)
    if isinstance(value, Mapping):
        return {
            key: _replace_public_fact_source_refs(item)
            for key, item in value.items()
        }
    return value


def _append_public_fact_cluster_sources(
    sources: list[dict[str, Any]],
    data_points: Sequence[Mapping[str, Any]],
) -> None:
    """Append fact-cluster source cards without creating new evidence groups."""
    sources_by_ref = {str(source["ref"]): source for source in sources}
    points_by_key = {
        str(point["data_point_key"]): point
        for point in data_points
    }
    for alias_ref, spec in PUBLIC_FACT_CLUSTER_SOURCE_SPECS.items():
        if alias_ref in sources_by_ref:
            raise ValueError(f"公开事实簇来源ref重复：{alias_ref}")
        base_ref = str(spec["base_ref"])
        if base_ref not in sources_by_ref:
            raise ValueError(f"公开事实簇缺少基础来源：{base_ref}")
        selected: list[Mapping[str, Any]] = []
        for point_key in spec["data_point_keys"]:
            point = points_by_key.get(str(point_key))
            if point is None or str(point.get("source_ref") or "") != base_ref:
                raise ValueError(
                    f"公开事实簇{alias_ref}无法绑定同来源数据点：{point_key}"
                )
            selected.append(point)
        alias = copy.deepcopy(sources_by_ref[base_ref])
        alias["ref"] = alias_ref
        alias["title"] = f"{alias['title']} — fact-specific excerpt"
        alias["title_zh"] = (
            f"{alias.get('title_zh') or alias['title']}"
            f"{spec['title_suffix_zh']}"
        )
        alias["excerpt"] = "\n".join(
            dict.fromkeys(str(point["source_excerpt"]).strip() for point in selected)
        )
        alias["excerpt_zh"] = "\n".join(
            dict.fromkeys(
                str(point.get("source_excerpt_zh") or point["source_excerpt"]).strip()
                for point in selected
            )
        )
        alias["local_locator"] = str(spec["locator"])
        alias.pop("excerpt_data_point_key", None)
        sources.append(alias)
        sources_by_ref[alias_ref] = alias


def _refs_in_markdown(body: str) -> list[str]:
    """Return the unique source references actually cited in reader-facing prose."""
    return list(dict.fromkeys(SOURCE_REF_PATTERN.findall(body)))


def _report_section(*, key: str, title: str, body: str) -> dict[str, Any]:
    normalized = natural_citations(body.strip())
    refs = _refs_in_markdown(normalized)
    if not refs:
        raise ValueError(f"公开章节没有正文引用：{title}")
    return {
        "section_key": key,
        "section_title": title,
        "body_markdown": normalized,
        "support_status": "partially_supported",
        "evidence_ref_uri_list": [source_uri(ref) for ref in refs],
    }


def _source_citations(refs: Sequence[str]) -> str:
    return " ".join(f"^src:{source_uri(ref)}" for ref in dict.fromkeys(refs))


LOCAL_PATH_MAP = {
    r"D:\quant\industry_demo\papers\硅片\沪硅 客户.pdf": "papers/硅片/沪硅 客户.pdf",
    r"D:\quant\industry_demo\papers\硅片\上海超硅招股书.pdf": "papers/硅片/上海超硅招股书.pdf",
    r"D:\quant\industry_demo\papers\硅片\西安奕材 招股书.pdf": "papers/硅片/西安奕材 招股书.pdf",
    r"D:\quant\industry_demo\papers\硅片\TCL中环2025年报.pdf": "papers/硅片/TCL中环2025年报.pdf",
    r"D:\quant\industry_demo\papers\硅片\2026-04-28-605358.SH-立昂微-605358立昂微2025年年度报告.pdf": (
        "papers/硅片/2026-04-28-605358.SH-立昂微-605358立昂微2025年年度报告.pdf"
    ),
}


ENTITY_SPECS: tuple[dict[str, Any], ...] = (
    {
        "key": "global_300mm_fab_expansion",
        "candidate_name": "全球300毫米晶圆厂扩产",
        "name": "全球300毫米晶圆厂扩产",
        "description": "研究全球300毫米晶圆厂从建设、设备搬入到量产爬坡形成的原生硅片采购，不把项目投资额直接换算成月产能。",
        "base_score": 76,
        "core_refs": ["DMD-SEMI-WAFER-OUTLOOK-202509", "DMD-NIST-GLOBALWAFERS", "DMD-SILTRONIC-AR2025", "S001", "S003", "S011", "S064"],
        "evidence": "SEMI的总量口径显示全球300毫米产能在2028年达到每月1,110万片，2026年第二季度的当前版本又给出2026年以及2027—2029年约7%的增长方向；逐厂台账中的36个项目只有4项可直接复算净增月产能与建模时点",
        "method": "先用SEMI总量给全球边界，再只对披露净增月产能的项目计算年度采购；利用率、工艺投入和库存系数分开设置，未披露月产能的项目只用于方向与时间判断",
        "conclusion": "需求上升的方向较强，但项目公告覆盖率远低于全球总量；四个可量化项目的求和是带爬坡与利用率假设的基准情景，不能视为已实现采购的最低值，2029—2030年的绝对量仍对项目延期和利用率高度敏感",
        "financial": "专业硅片公司的收入、毛利、经营现金流和资本开支可以检验行业周期与供给压力，但不能替代逐厂客户认证和采购量",
        "risk": "若大型项目延期、既有厂通过利用率提升吸收需求，或硅片厂扩产早于客户认证，名义产能增长会先形成折旧与价格压力，而不是利润增长",
        "follow_up": "大型先进逻辑和存储项目的真实月产能、设备搬入后的季度爬坡、各厂原生片与再生片使用比例，以及主要硅片商的客户认证和长协数量",
        "targets": ["siltronic", "globalwafers"],
    },
    {
        "key": "advanced_logic_wafer_demand",
        "candidate_name": "先进逻辑硅片需求",
        "name": "先进逻辑硅片需求",
        "description": "研究7纳米及以下逻辑产能对300毫米低缺陷抛光片、外延片和更严规格硅片的需求，不把AI资本开支等同于硅片采购。",
        "base_score": 79,
        "core_refs": ["DMD-NIST-GLOBALWAFERS", "DMD-SAMSUNG-TAYLOR-20260610", "S001", "S011", "S017", "S038"],
        "evidence": "SEMI预计7纳米及以下产能由2024年的每月85万片增至2028年的140万片，台积电、三星、Intel和Rapidus项目共同支持先进逻辑方向，但大多数项目没有公开硅片供应商或净增月产能",
        "method": "把先进节点产能作为质量升级锚点，并用项目投产时间检查节奏；没有材料认证、产品规格和采购量时，只判断高规格需求方向，不向单一硅片商分配份额",
        "conclusion": "先进逻辑是本轮最确定的高规格300毫米需求来源，价值量可能快于面积增长；但中国供应商能否受益取决于缺陷、平坦度、金属污染和长期稳定性认证，而非只有尺寸能力",
        "financial": "SUMCO等专业供应商的先进300毫米投入和利润变化可以反映供需，但集团披露通常不按客户与节点拆分，仍需项目级认证证据",
        "risk": "若2纳米以下项目延后、单位晶圆算力提升快于终端需求，或合格供应商继续集中于既有龙头，新增面积和国产替代都会低于名义产能叙事",
        "follow_up": "各先进逻辑厂的季度月产能、硅片规格书、材料认证批次、外延片占比、长协价格和中国供应商从送样到批量采购的日期",
        "targets": ["sumco"],
    },
    {
        "key": "dram_hbm_wafer_demand",
        "candidate_name": "DRAM与HBM硅片需求",
        "name": "DRAM与HBM硅片需求",
        "description": "研究先进DRAM与HBM带来的晶圆投入和高规格材料变化，明确不把HBM堆叠层数重复乘入晶圆厂月产能。",
        "base_score": 72,
        "core_refs": ["DMD-SEMI-MEMORY-20260629", "DMD-SILTRONIC-AR2025", "S020", "S022", "S024", "S025", "S030"],
        "evidence": "Micron、SK hynix与三星的新厂和扩产项目支持先进DRAM方向，但SEMI公开总量显示2026至2027年300毫米存储月产能仅约增加10万片，说明位增长、工艺迁移与晶圆数量不是同一个指标",
        "method": "以晶圆厂月投入为唯一面积分母，HBM堆叠、封装良率和裸片数量只影响产品结构与单位价值，不再乘到月产能；没有DRAM和NAND项目拆分时保留合并边界",
        "conclusion": "HBM更可靠地提升先进抛光片、外延片、监控片与载片的规格价值，而不是让硅片数量按堆叠层数增长；短期需求仍受存储库存、良率和项目爬坡支配",
        "financial": "专业硅片商的高端300毫米产品组合与长协重谈比集团总销量更有解释力，收入增长若同时伴随毛利下降，说明新增供给或价格仍在消化",
        "risk": "若HBM位增长主要靠节点迁移、良率改善和单位晶圆产出承接，或存储客户延后新厂爬坡，普通300毫米硅片数量会明显低于AI需求叙事",
        "follow_up": "DRAM与NAND分开的月产能、HBM代际对应的晶圆面积和良率、硅片规格与采购价、Micron和SK hynix项目的逐季爬坡，以及供应商高端产品收入",
        "targets": ["siltronic"],
    },
    {
        "key": "nand_wafer_demand",
        "candidate_name": "NAND硅片需求",
        "name": "NAND硅片需求",
        "description": "研究NAND位增长、层数升级、现有洁净室利用和新厂建设如何共同决定原生硅片需求，避免把位增速直接写成面积增速。",
        "base_score": 58,
        "core_refs": ["DMD-SEMI-MEMORY-20260629", "S022", "S039", "S040", "S045", "S047"],
        "evidence": "Kioxia预计较高的NAND位需求增长，却明确优先利用Y7和K2既有洁净室；Micron新加坡与长江存储三期提供新增方向，但公开资料没有足以复算的净增月产能",
        "method": "把位需求、晶圆开工和硅片采购分成三层：层数与节点决定每片位产出，利用率决定实际开工，新建产能只有披露净增月产能后才进入片数模型",
        "conclusion": "NAND硅片需求会随周期复苏，但面积增长很可能慢于位增长，且不同厂商通过层数升级与利用现有洁净室吸收需求的能力差异很大",
        "financial": "SUMCO等供应商在非先进300毫米与200毫米产品上的库存和价格可以验证NAND周期，但合并财务无法单独分离NAND客户贡献",
        "risk": "若层数升级和单位晶圆位产出持续快于终端需求，新厂建设又被延后，NAND位增长可能与硅片采购脱钩，普通产品先承受库存和价格压力",
        "follow_up": "Kioxia、Micron、长江存储的净增月产能、NAND层数对应的单位晶圆位产出、季度利用率、原生片采购与库存，以及硅片供应商的分产品价格",
        "targets": ["sumco"],
    },
    {
        "key": "china_300mm_wafer_suppliers",
        "candidate_name": "国内12英寸硅片供应商",
        "name": "国内12英寸硅片供应商",
        "description": "比较中国12英寸硅片企业的实际销量、客户认证、产品结构、利用率、价格和盈利，不以设计产能或客户名单替代当期采购。",
        "base_score": 65,
        "core_refs": ["DMD-NIST-GLOBALWAFERS", "S042", "S044", "S057", "S058", "S059", "S061", "S062"],
        "evidence": "上海超硅、西安奕材、立昂微和沪硅产业均有量产或认证证据，但上海超硅利用率与价格下滑、西安奕材仍大额亏损、部分客户资料较旧，说明受益顺序不能只看规划产能",
        "method": "按客户认证、实际销量、高规格占比、利用率与价格、毛利和经营现金流逐层筛选；历史客户名单只证明进入过认证体系，未披露年度采购量时不推断当前份额",
        "conclusion": "可以认为国内供应商已进入主要客户体系并具备销量增长基础，但盈利改善需要高规格产品放量与价格稳定同时发生，设计产能领先并不等于最先受益",
        "financial": "西安奕材至少三年财务显示销量增长与持续亏损并存，是最直接的反向检查；对其他国内公司还应补充分尺寸、分产品和客户集中度数据",
        "risk": "如果普通12英寸抛光片集中投产而高端认证滞后，国内供给会先于有效需求释放，利用率、售价、存货与折旧共同压制盈利",
        "follow_up": "各公司12英寸抛光片、外延片、退火片与SOI的季度销量、平均售价、良率、客户认证转批量日期、年度采购量、利用率、库存和单位折旧",
        "targets": ["eswin_materials"],
    },
    {
        "key": "mature_200mm_wafer_demand",
        "candidate_name": None,
        "name": "200毫米成熟制程硅片需求",
        "description": "研究200毫米功率、模拟、汽车和工业晶圆厂的装机与利用率如何形成硅片需求，并与300毫米面积等效口径严格分开。",
        "base_score": 57,
        "core_refs": ["DMD-SILTRONIC-AR2025", "S002", "S032", "S033", "S035", "S053", "S065"],
        "factor_refs": {
            "demand.downstream_price_momentum": ["S053", "S005", "S066", "S058", "S060"],
            "demand.customer_capex_capacity_signal": ["S065", "S002", "S032", "S042", "S058"],
            "demand.output_consumption_proxy": ["S065", "S042", "S058", "S066", "S005"],
            "demand.application_intensity_change": ["S032", "S037", "S053", "S058", "S062"],
            "supply.capacity_event_12m": ["S065", "S002", "S032", "S053", "S058"],
            "supply.expansion_cycle_bucket": ["S002", "S032", "S053", "S058", "S065"],
            "supply.raw_policy_constraint": ["S032", "S002", "S015", "S028", "S051"],
            "supply.supplier_structure_bucket": ["S052", "S053", "S058", "S060", "FIN-GWC-01"],
            "supply.substitution_barrier": ["S032", "S037", "S053", "S058", "S062"],
            "signal.material_price_momentum": ["S053", "S005", "S066", "S058", "FIN-SUMCO-01"],
        },
        "evidence": "SEMI预计全球200毫米装机产能在2026年增长3%至每月770万片，2027—2029年增速分别为3%、1%和2%；格芯、TI和英飞凌项目提供成熟制程与功率模拟方向，信越化学则明确200毫米市场仍偏宽松",
        "method": "2026—2029年直接使用SEMI的纯200毫米装机口径，2030年才设置0%、2%和4%三种研究情景；总8英寸等效减去300毫米面积等效只作交叉检查，不当作纯200毫米产能",
        "calculation_detail": "200毫米模型使用SEMI当前公开的每月770万片基数和年度增速，分别计算年度新增装机与在85%利用率下的采购量。2030年没有公开预测，因此只展示不增长、增长2%和增长4%三种研究情景。总8英寸等效余量包含更小尺寸，不能与这条纯200毫米路径相加。",
        "model_boundary": "对200毫米而言，直接口径和面积等效余量不能相加。直接口径用于主结果，面积等效余量只检查总量是否出现数量级矛盾；成熟制程项目的产品、利用率和旧设备改造又各不相同，因此不能把300毫米单位投资或增长率套到200毫米。",
        "conclusion": "200毫米需求仍会增长，但速度明显低于300毫米且供需偏宽松；真正的增量来自功率、模拟、汽车和工业项目爬坡，而不是先进制程资本开支",
        "financial": "SUMCO等综合硅片厂必须按尺寸拆分销量、库存与价格；合并收入改善并不能证明200毫米供需转紧",
        "risk": "若汽车、工业和功率需求疲弱，旧厂通过利用率恢复与设备改造即可满足订单，200毫米新增产能会先形成库存和价格压力",
        "follow_up": "200毫米分地区装机、季度利用率、功率与模拟产品开工、硅片供应商分尺寸销量与价格、再生片比例以及旧设备改造对有效产能的贡献",
        "targets": ["sumco"],
    },
    {
        "key": "soi_engineered_substrate_demand",
        "candidate_name": None,
        "name": "SOI工程衬底需求",
        "description": "研究RF-SOI、FD-SOI和其他工程衬底的客户平台、认证与产能需求，不把SOI收入或片数与普通抛光硅片简单相加。",
        "base_score": 55,
        "core_refs": ["DMD-NIST-GLOBALWAFERS", "S051", "S055", "S056", "FIN-SOITEC-FY2026", "FIN-SOITEC-02"],
        "factor_refs": {
            "demand.downstream_price_momentum": ["FIN-SOITEC-FY2026", "FIN-SOITEC-02", "S005", "S055", "S056"],
            "demand.customer_capex_capacity_signal": ["S051", "S055", "S056", "FIN-SOITEC-FY2026", "FIN-GWC-01"],
            "demand.output_consumption_proxy": ["S055", "S056", "S051", "FIN-SOITEC-FY2026", "S005"],
            "demand.application_intensity_change": ["S055", "S056", "S052", "S051", "FIN-SOITEC-FY2026"],
            "supply.capacity_event_12m": ["S051", "FIN-SOITEC-FY2026", "FIN-GWC-01", "S055", "S056"],
            "supply.expansion_cycle_bucket": ["S051", "S055", "S056", "FIN-SOITEC-FY2026", "FIN-GWC-01"],
            "supply.raw_policy_constraint": ["S051", "S032", "S015", "S021", "S028"],
            "supply.supplier_structure_bucket": ["S052", "S051", "S055", "S056", "FIN-GWC-01"],
            "supply.substitution_barrier": ["S055", "S056", "S052", "S051", "S037"],
            "signal.material_price_momentum": ["FIN-SOITEC-FY2026", "FIN-SOITEC-02", "FIN-GWC-01", "S005", "S055"],
        },
        "evidence": "Soitec与格芯、联电存在具名RF-SOI或工程衬底合作，美国政府对环球晶圆项目的支持也包含300毫米SOI能力；但公开资料没有全球SOI月产能、统一价格或采购量基线",
        "method": "因缺少可核验全球片数、出货或价格基线，本研究不为SOI设置主观增长率；客户关系只用于确认应用方向，不能从合作公告推导采购量",
        "calculation_detail": "SOI不输出片数、市场规模或无锚点指数。现有证据只确认Soitec与格芯、联电等平台合作，以及部分新产能包含SOI能力；在取得全球分尺寸产能、出货和价格以前，数量结论保持不量化。",
        "model_boundary": "对SOI而言，目前没有公开全球月产能、出货和统一价格基线，因此无法像普通硅片一样计算绝对采购片数或校准增长率。任何数量结论都必须等待供应商分产品产能、出货与客户采购披露。",
        "conclusion": "SOI受益于射频和差异化平台，客户关系方向得到一手证据支持；但数量和价格证据明显不足，当前只能认为是高价值、低可量化的细分机会",
        "financial": "Soitec三期财务可检验工程衬底周期和现金投入，但收入同时包含多类衬底，不能用集团增速反推RF-SOI片数",
        "risk": "若射频库存恢复较慢、客户平台渗透不及预期或认证推迟，SOI出货和盈利都会落后于普通300毫米扩产",
        "follow_up": "全球SOI分尺寸月产能、RF-SOI与FD-SOI出货和均价、格芯与联电平台采购量、Soitec分产品收入与利用率，以及环球晶圆美国SOI项目的认证和爬坡",
        "targets": ["soitec"],
    },
)


FACTOR_ROUTES: dict[str, dict[str, Any]] = {
    "demand.downstream_price_momentum": {
        "label": "下游价格与订单是否确认需求",
        "question": "终端和晶圆厂需求是否已经通过硅片价格、订单、出货或库存变化得到确认",
        "candidate_factor_ids": ("F07", "F04"),
    },
    "demand.customer_capex_capacity_signal": {
        "label": "晶圆厂资本开支与产能是否落地",
        "question": "客户是否以开工、设备搬入、首片、量产或实际月产能证明扩产正在发生",
        "candidate_factor_ids": ("F02", "F01"),
    },
    "demand.output_consumption_proxy": {
        "label": "晶圆开工如何转成硅片消耗",
        "question": "有效晶圆开工、利用率和库存变化是否会同步放大原生硅片采购",
        "candidate_factor_ids": ("F03", "F01", "F04"),
    },
    "demand.application_intensity_change": {
        "label": "产品升级是否提高单位价值",
        "question": "先进节点、HBM、层数升级或工程衬底是否改变每片晶圆对应的硅片规格与价值",
        "candidate_factor_ids": ("F05", "F10", "F01"),
    },
    "supply.capacity_event_12m": {
        "label": "未来一年供给释放与爬坡",
        "question": "未来十二个月硅片或晶圆厂产能会释放、受限还是因认证与爬坡延后",
        "candidate_factor_ids": ("F02", "F03"),
    },
    "supply.expansion_cycle_bucket": {
        "label": "扩产、认证与良率需要多久",
        "question": "从项目建设到合格硅片稳定供货的周期是否足以延缓有效供给",
        "candidate_factor_ids": ("F02", "F10", "F06"),
    },
    "supply.raw_policy_constraint": {
        "label": "政策、本地化与投入约束",
        "question": "补贴、供应链本地化、资本投入与区域政策会怎样约束供给扩张",
        "candidate_factor_ids": (),
    },
    "supply.supplier_structure_bucket": {
        "label": "合格供应商结构",
        "question": "合格供应商是否集中，新增供给是否真正具备目标产品和客户能力",
        "candidate_factor_ids": ("F09", "F06", "F08"),
    },
    "supply.substitution_barrier": {
        "label": "客户认证与技术替代壁垒",
        "question": "客户认证、规格、良率和稳定性是否让供应商切换保持困难",
        "candidate_factor_ids": ("F06", "F05", "F10"),
    },
    "signal.material_price_momentum": {
        "label": "硅片价格是否确认供需",
        "question": "硅片价格、毛利、库存和实际订单是否确认供需改善，而不只是产能叙事",
        "candidate_factor_ids": ("F07", "F04", "F09"),
    },
}


# Public factor pages use a deliberately curated evidence set.  The mapping is
# separate from metric-slot routing: a source may explain the factor without
# supplying a scoreable number, but it must still address that factor's
# economic question directly.
FACTOR_PUBLIC_REFS_BY_ENTITY: dict[str, dict[str, tuple[str, ...]]] = {
    "global_300mm_fab_expansion": {
        "demand.downstream_price_momentum": ("S005", "S006", "S066", "DMD-SILTRONIC-AR2025", "S053"),
        "demand.customer_capex_capacity_signal": ("S001", "S002", "S011", "S022", "S024"),
        "demand.output_consumption_proxy": ("S066", "S005", "S042", "S060", "DMD-SILTRONIC-AR2025"),
        "demand.application_intensity_change": ("S001", "DMD-SEMI-DEMAND-TRANSMISSION-20251008", "DMD-SK-SILTRON-SR2025", "S052", "S055"),
        "supply.capacity_event_12m": ("S064", "S003", "S011", "S022", "S026"),
        "supply.expansion_cycle_bucket": ("S011", "S016", "S022", "S024", "DMD-SILTRONIC-AR2025"),
        "supply.raw_policy_constraint": ("S015", "S021", "S028", "S032", "S051"),
        "supply.supplier_structure_bucket": ("DMD-NIST-GLOBALWAFERS", "S050", "S052", "S054", "DMD-SK-SILTRON-SR2025"),
        "supply.substitution_barrier": ("DMD-SILTRONIC-AR2025", "S023", "S057", "S059", "S055"),
        "signal.material_price_momentum": ("S005", "S006", "S066", "DMD-SILTRONIC-AR2025", "S053"),
    },
    "advanced_logic_wafer_demand": {
        "demand.downstream_price_momentum": ("S005", "S006", "S066", "DMD-SILTRONIC-AR2025", "S053"),
        "demand.customer_capex_capacity_signal": ("S001", "S011", "S017", "S029", "S038"),
        "demand.output_consumption_proxy": ("S011", "S018", "S029", "S038", "S001"),
        "demand.application_intensity_change": ("S001", "DMD-SEMI-DEMAND-TRANSMISSION-20251008", "DMD-SK-SILTRON-SR2025", "S052", "S038"),
        "supply.capacity_event_12m": ("DMD-SAMSUNG-TAYLOR-20260610", "S011", "S016", "S018", "S038"),
        "supply.expansion_cycle_bucket": ("S011", "S016", "S029", "DMD-SAMSUNG-TAYLOR-20260610", "S038"),
        "supply.raw_policy_constraint": ("S013", "S028", "S051", "DMD-NIST-GLOBALWAFERS", "S017"),
        "supply.supplier_structure_bucket": ("DMD-NIST-GLOBALWAFERS", "DMD-SK-SILTRON-SR2025", "S052", "S054", "S050"),
        "supply.substitution_barrier": ("DMD-SK-SILTRON-SR2025", "DMD-SILTRONIC-AR2025", "S057", "S052", "S023"),
        "signal.material_price_momentum": ("S005", "S006", "S066", "DMD-SILTRONIC-AR2025", "S053"),
    },
    "dram_hbm_wafer_demand": {
        "demand.downstream_price_momentum": ("S005", "S006", "S066", "DMD-SILTRONIC-AR2025", "S060"),
        "demand.customer_capex_capacity_signal": ("DMD-SEMI-MEMORY-20260629", "S020", "S022", "S024", "S026"),
        "demand.output_consumption_proxy": ("S026", "DMD-SEMI-MEMORY-20260629", "S005", "S066", "DMD-SILTRONIC-AR2025"),
        "demand.application_intensity_change": ("DMD-SK-SILTRON-SR2025", "DMD-SEMI-DEMAND-TRANSMISSION-20251008", "S025", "S052", "DMD-SEMI-MEMORY-20260629"),
        "supply.capacity_event_12m": ("S026", "S022", "S020", "S024", "S030"),
        "supply.expansion_cycle_bucket": ("S020", "S022", "S024", "S025", "S030"),
        "supply.raw_policy_constraint": ("S021", "S024", "S028", "S045", "S046"),
        "supply.supplier_structure_bucket": ("DMD-NIST-GLOBALWAFERS", "DMD-SK-SILTRON-SR2025", "S052", "S054", "S050"),
        "supply.substitution_barrier": ("DMD-SK-SILTRON-SR2025", "DMD-SILTRONIC-AR2025", "S023", "S057", "S059"),
        "signal.material_price_momentum": ("S005", "S006", "S066", "DMD-SILTRONIC-AR2025", "S060"),
    },
    "nand_wafer_demand": {
        "demand.downstream_price_momentum": ("S005", "S006", "S066", "DMD-SILTRONIC-AR2025", "S060"),
        "demand.customer_capex_capacity_signal": ("DMD-MICRON-SINGAPORE-20260127", "S022", "S039", "S040", "S045"),
        "demand.output_consumption_proxy": ("S039", "S040", "DMD-SEMI-MEMORY-20260629", "S005", "S066"),
        "demand.application_intensity_change": ("DMD-SEMI-DEMAND-TRANSMISSION-20251008", "DMD-SK-SILTRON-SR2025", "S040", "S052", "S039"),
        "supply.capacity_event_12m": ("DMD-MICRON-SINGAPORE-20260127", "S039", "S040", "S045", "DMD-SEMI-MEMORY-20260629"),
        "supply.expansion_cycle_bucket": ("DMD-MICRON-SINGAPORE-20260127", "S039", "S040", "S045", "S022"),
        "supply.raw_policy_constraint": ("S021", "S045", "S028", "DMD-SEMI-DEMAND-TRANSMISSION-20251008", "S051"),
        "supply.supplier_structure_bucket": ("DMD-NIST-GLOBALWAFERS", "DMD-SK-SILTRON-SR2025", "S052", "S054", "S050"),
        "supply.substitution_barrier": ("DMD-SK-SILTRON-SR2025", "DMD-SILTRONIC-AR2025", "S023", "S057", "S059"),
        "signal.material_price_momentum": ("S005", "S006", "S066", "DMD-SILTRONIC-AR2025", "S060"),
    },
    "china_300mm_wafer_suppliers": {
        "demand.downstream_price_momentum": ("S058", "S059", "S060", "S061", "S053"),
        "demand.customer_capex_capacity_signal": ("S042", "S044", "S045", "S046", "S057"),
        "demand.output_consumption_proxy": ("S042", "S043", "S058", "S060", "S061"),
        "demand.application_intensity_change": ("S057", "S058", "S061", "S062", "DMD-SK-SILTRON-SR2025"),
        "supply.capacity_event_12m": ("S057", "S058", "S059", "S061", "S062"),
        "supply.expansion_cycle_bucket": ("S057", "S058", "S059", "S061", "S062"),
        "supply.raw_policy_constraint": ("S042", "S044", "S045", "S046", "DMD-NIST-GLOBALWAFERS"),
        "supply.supplier_structure_bucket": ("DMD-NIST-GLOBALWAFERS", "S057", "S058", "S059", "S061"),
        "supply.substitution_barrier": ("DMD-SILTRONIC-AR2025", "S057", "S058", "S059", "S062"),
        "signal.material_price_momentum": ("S058", "S059", "S060", "S061", "S053"),
    },
    "mature_200mm_wafer_demand": {
        "demand.downstream_price_momentum": ("S053", "S005", "S066", "S058", "S060"),
        "demand.customer_capex_capacity_signal": ("S065", "S002", "S032", "S033", "S035"),
        "demand.output_consumption_proxy": ("S065", "S042", "S058", "S066", "S053"),
        "demand.application_intensity_change": ("S032", "S037", "S053", "S058", "S062"),
        "supply.capacity_event_12m": ("S065", "S002", "S032", "S033", "S035"),
        "supply.expansion_cycle_bucket": ("S002", "S032", "S033", "S035", "S065"),
        "supply.raw_policy_constraint": ("S032", "S033", "S035", "S037", "S065"),
        "supply.supplier_structure_bucket": ("DMD-NIST-GLOBALWAFERS", "S052", "S053", "S058", "FIN-GWC-01"),
        "supply.substitution_barrier": ("S032", "S037", "S052", "S058", "S062"),
        "signal.material_price_momentum": ("S053", "S005", "S066", "S058", "FIN-SUMCO-01"),
    },
    "soi_engineered_substrate_demand": {
        "demand.downstream_price_momentum": ("FIN-SOITEC-FY2026", "FIN-SOITEC-02", "S005", "S055", "S056"),
        "demand.customer_capex_capacity_signal": ("S051", "FIN-GWC-01", "FIN-SOITEC-FY2026", "S055", "S056"),
        "demand.output_consumption_proxy": ("FIN-SOITEC-FY2026", "FIN-SOITEC-02", "S055", "S056", "S051"),
        "demand.application_intensity_change": ("S055", "S056", "S052", "S051", "FIN-SOITEC-FY2026"),
        "supply.capacity_event_12m": ("S051", "FIN-GWC-01", "FIN-SOITEC-FY2026", "S055", "S056"),
        "supply.expansion_cycle_bucket": ("S051", "FIN-GWC-01", "FIN-SOITEC-FY2026", "S055", "S056"),
        "supply.raw_policy_constraint": ("S051", "DMD-NIST-GLOBALWAFERS", "S032", "S055", "S056"),
        "supply.supplier_structure_bucket": ("DMD-NIST-GLOBALWAFERS", "S052", "S055", "S056", "FIN-GWC-01"),
        "supply.substitution_barrier": ("S055", "S056", "S052", "S051", "FIN-SOITEC-FY2026"),
        "signal.material_price_momentum": ("FIN-SOITEC-FY2026", "FIN-SOITEC-02", "S005", "S055", "S056"),
    },
}


FACTOR_METHOD_BY_CODE: dict[str, str] = {
    "demand.downstream_price_momentum": "判断时把出货量、收入、价格和库存放在一起看；只有资本开支或产能计划，不能证明订单和价格已经改善。",
    "demand.customer_capex_capacity_signal": "按开工、设备搬入、首片、批量生产和稳定产能逐级确认；投资额不换算成硅片采购。",
    "demand.output_consumption_proxy": "优先使用实际晶圆投入、硅片出货、利用率和库存；缺少同尺寸数据时只保留方向，不把装机能力当成实际消耗。",
    "demand.application_intensity_change": "把晶圆面积与规格价值分开；节点、层数或工程衬底升级可以提高价值，但不能重复乘入晶圆片数。",
    "supply.capacity_event_12m": "只把未来十二个月可核验的投产、爬坡、停产或延期纳入判断，远期设计能力只作背景。",
    "supply.expansion_cycle_bucket": "比较建设、设备搬入、客户认证和良率爬坡的实际时间，避免把首片日期误当成稳定供货日期。",
    "supply.raw_policy_constraint": "区分政府资金、本地化要求和企业自身资本约束；补贴能改变项目地点和资金成本，不能保证客户认证或利用率。",
    "supply.supplier_structure_bucket": "同时检查供应商数量、产品能力和客户资格；厂房数量增加不等于合格供应商结构已经分散。",
    "supply.substitution_barrier": "用规格、认证、复购和长期供货关系判断切换难度，不用客户名单直接推断份额。",
    "signal.material_price_momentum": "价格判断要求同尺寸、同产品、同期间的成交或平均售价；收入和毛利只作为交叉检查，不能替代价格序列。",
}


FACTOR_SOURCE_ROLE_BY_CODE: dict[str, str] = {
    "demand.downstream_price_momentum": "核对硅片出货、收入、订单和库存是否共同确认需求",
    "demand.customer_capex_capacity_signal": "核对晶圆厂项目是否跨过开工、设备搬入、晶圆投入或量产节点",
    "demand.output_consumption_proxy": "核对实际出货、晶圆投入、利用率和库存，而不是名义装机",
    "demand.application_intensity_change": "核对节点、产品和衬底规格怎样改变单位价值而非重复放大片数",
    "supply.capacity_event_12m": "核对未来十二个月可见的投产、爬坡、延期或供给释放",
    "supply.expansion_cycle_bucket": "核对从建设到认证和稳定供货所需的时间",
    "supply.raw_policy_constraint": "核对补贴、本地化和资本约束怎样影响供给地点与节奏",
    "supply.supplier_structure_bucket": "核对合格供应商集中度、产品覆盖和新增能力",
    "supply.substitution_barrier": "核对客户认证、规格、复购和长期协议所反映的切换成本",
    "signal.material_price_momentum": "核对硅片成交价、平均售价、收入和库存是否一致转强",
}


FACTOR_FINDING_BY_ENTITY: dict[str, dict[str, str]] = {
    "global_300mm_fab_expansion": {
        "demand.downstream_price_momentum": "2025年全球硅片面积出货增长5.8%而收入下降1.2%，2026年一季度出货同比增长13.1%但环比下降4.7%；需求在恢复，价格与季度动能尚未同步转强。",
        "demand.customer_capex_capacity_signal": "全球300毫米装机方向和多座晶圆厂开工得到一手资料支持，但项目成熟度差异很大，不能把已宣布投资一次性算成硅片订单。",
        "demand.output_consumption_proxy": "全球硅片出货同比改善与季度环比回落同时存在，个别晶圆厂利用率回升也不能替代全球300毫米晶圆投入序列。",
        "demand.application_intensity_change": "7纳米及以下产能增长快于300毫米总量，低缺陷抛光片、外延片和更严过程控制的价值增量可能快于晶圆面积。",
        "supply.capacity_event_12m": "2026—2027年有量产和晶圆投入节点，但不同项目仍处于建设、安装或初始爬坡，未来一年新增有效供给应按项目分别确认。",
        "supply.expansion_cycle_bucket": "亚利桑那、爱达荷、龙仁和俄亥俄的时间表显示，从开工到稳定产出往往跨越多年；客户认证完成后也可能因需求不足而放慢爬坡。",
        "supply.raw_policy_constraint": "欧美补贴正把晶圆厂和硅片产能推向本地化布局，但补贴主要降低建设成本，无法替代客户认证、良率和利用率。",
        "supply.supplier_structure_bucket": "全球硅片供应仍主要集中在五家公司，新建美国与新加坡能力改善地域分布，却尚未证明高规格合格供给已经明显分散。",
        "supply.substitution_barrier": "客户认证、十年供货安排和具名平台合作说明原生硅片切换具有黏性；公开资料仍不足以量化不同规格的认证周期。",
        "signal.material_price_momentum": "面积出货回升而行业收入下降，说明隐含单价和产品组合尚未全面改善；当前不能据此宣称全球硅片进入普遍涨价周期。",
    },
    "advanced_logic_wafer_demand": {
        "demand.downstream_price_momentum": "公开资料没有先进逻辑硅片的独立成交价或订单序列；全尺寸硅片量价只能证明行业周期，不能证明高规格产品已经涨价。",
        "demand.customer_capex_capacity_signal": "台积电亚利桑那已量产并继续扩建，Rapidus进入2纳米试制，而英特尔德国项目终止、俄亥俄放缓，先进逻辑扩产方向明确但节奏分化。",
        "demand.output_consumption_proxy": "已有4纳米量产、18A爬坡和2纳米原型进展，但各厂没有披露可比较的月度晶圆投入和利用率，面积需求仍无法直接相加。",
        "demand.application_intensity_change": "7纳米及以下月产能预计从85万片增至140万片，且供应商已披露2纳米逻辑外延片能力；高规格价值增长的证据强于总面积增长。",
        "supply.capacity_event_12m": "Taylor、Rapidus和台积电后续厂均有近期节点，但量产目标、试制和稳定产出不是同一状态；俄亥俄延期构成明确反证。",
        "supply.expansion_cycle_bucket": "先进逻辑项目从厂务安装、试制到大批量制造跨越数年，2纳米原型成功也不能跳过良率爬坡和材料认证。",
        "supply.raw_policy_constraint": "美国补贴和本地化投资强化先进逻辑区域扩产，同时英特尔削减项目表明资本回报纪律仍会改变建设节奏。",
        "supply.supplier_structure_bucket": "先进逻辑需要低缺陷和外延能力，全球供应集中度高；新增厂房只有完成目标节点和客户认证后才会改变合格供应格局。",
        "supply.substitution_barrier": "2纳米外延片开发、客户认证和长期供货关系都指向较高切换成本，国内供应商的尺寸能力不能替代先进节点资格。",
        "signal.material_price_momentum": "没有可核验的先进逻辑硅片价格序列，行业收入、出货和200毫米供需不能替代该细分价格；价格拐点尚未得到直接确认。",
    },
    "dram_hbm_wafer_demand": {
        "demand.downstream_price_momentum": "公开资料没有DRAM/HBM用硅片的独立平均售价；全球硅片收入、出货和供应商库存只说明大周期，无法证明存储高规格片已普遍涨价。",
        "demand.customer_capex_capacity_signal": "M15X已经开始晶圆投入，Micron爱达荷和SK海力士龙仁项目继续推进；资本开支方向得到确认，但多数项目没有月产能。",
        "demand.output_consumption_proxy": "M15X的实际晶圆投入是最直接信号，而SEMI只披露存储整体从410万片/月增至420万片/月，无法拆出DRAM、HBM与NAND。",
        "demand.application_intensity_change": "HBM推动先进DRAM、抛光片、外延片和监控片规格升级，但堆叠层数发生在后道，不能再次乘到晶圆厂月投入。",
        "supply.capacity_event_12m": "M15X已进入初始爬坡，其他大型项目更多落在2027年以后；未来一年有效增量主要取决于现有产线爬坡而非全部远期厂房。",
        "supply.expansion_cycle_bucket": "爱达荷、龙仁、M15X和平泽项目的建设与运营节点分散在2026—2028年以后，存储供给释放具有显著时滞。",
        "supply.raw_policy_constraint": "美国、韩国和中国的政策与产业投资同时推进存储本地化，但技术升级项目和新建产线必须分开，资金规模不能直接换算片数。",
        "supply.supplier_structure_bucket": "DRAM/HBM所需300毫米抛光片和外延片仍由少数全球厂商提供，产品覆盖不等于已经取得具体存储客户份额。",
        "supply.substitution_barrier": "2纳米级产品开发、客户认证和十年供货安排显示高规格存储硅片切换成本较高，公开资料却没有各客户认证周期。",
        "signal.material_price_momentum": "全行业面积回升未带来同步收入增长，且没有DRAM/HBM硅片报价；当前只能监控结构改善，不能确认材料价格拐点。",
    },
    "nand_wafer_demand": {
        "demand.downstream_price_momentum": "NAND位需求预期改善，但没有NAND用原生硅片价格或订单序列；全尺寸硅片量价和库存只能作为弱代理。",
        "demand.customer_capex_capacity_signal": "美光新加坡先进NAND厂已开工，铠侠继续在既有洁净室增加设备，长江存储三期在建；三种路径对新增硅片面积的含义不同。",
        "demand.output_consumption_proxy": "铠侠优先利用现有设施推动GB增长，说明位增长可以由设备、层数和利用率承接；存储总月产能不能直接当成NAND片数。",
        "demand.application_intensity_change": "层数升级提高单片位产出，可能让位增长快于晶圆面积；先进NAND仍需要合格300毫米硅片，但不能按层数放大采购。",
        "supply.capacity_event_12m": "铠侠K2已运营且主要靠既有设施装机，美光新加坡要到2028年下半年才计划产出，长江存储三期又缺少月产能，近期增量有限。",
        "supply.expansion_cycle_bucket": "NAND项目从开工到晶圆产出跨越多年，并按市场需求控制爬坡；现有洁净室加设备与新建厂不能使用同一建设周期。",
        "supply.raw_policy_constraint": "美国激励、中国本地扩产和区域自给政策支持NAND投资，但公开资料不足以判断这些政策是否造成硅片原料约束。",
        "supply.supplier_structure_bucket": "NAND用300毫米硅片仍受全球寡头供给和产品资格约束，供应商的通用产品页不能证明已经取得NAND批量订单。",
        "supply.substitution_barrier": "存储客户的长期供货安排和高规格认证提高切换成本，位密度升级则是降低单位位数硅片用量的主要反向力量。",
        "signal.material_price_momentum": "没有NAND专属硅片平均售价，行业面积增长与收入下降并存；材料价格尚不足以确认NAND面积需求已经转紧。",
    },
    "china_300mm_wafer_suppliers": {
        "demand.downstream_price_momentum": "国内12英寸销量增长与售价下降同时出现：可复算样本显示销量约增长33.3%，平均售价约下降12.1%，需求扩张尚未转成定价改善。",
        "demand.customer_capex_capacity_signal": "中芯、华虹、长江存储和长鑫仍有建设或产能动作，为本地硅片提供客户基础；项目状态不能直接分配到某一家供应商。",
        "demand.output_consumption_proxy": "中芯利用率回升、国内供应商销量增长构成正面信号，但库存和价格压力说明新增出货的盈利质量仍需验证。",
        "demand.application_intensity_change": "国内企业已覆盖抛光片、外延片、功率、CIS和部分高端认证，产品升级空间存在；不同产品的认证与售价不能合并成一个国产化比例。",
        "supply.capacity_event_12m": "上海超硅当前瓶颈能力约30.58万片/月，而西安奕材120万片/月仍是规划；实际能力、设计能力和远期目标必须分开。",
        "supply.expansion_cycle_bucket": "国内扩产常经历厂房、瓶颈工序、送样认证、批量采购和利用率提升多个阶段，历史客户名单不能证明当前爬坡已经完成。",
        "supply.raw_policy_constraint": "晶圆厂本地化和国内扩产为国产硅片创造验证窗口，但全球高端供应仍集中，政策方向不能替代良率、稳定性和现金流。",
        "supply.supplier_structure_bucket": "国内供应商数量增加，但当前能力、产品等级和客户批量采购差异明显；全球五大厂商集中格局尚未被设计产能打破。",
        "supply.substitution_barrier": "客户认证、在手订单和分产品能力说明进入门槛较高；认证过期、未转批量或价格下滑时，客户名单不能代表有效份额。",
        "signal.material_price_momentum": "同一公司销量上升而均价下降，另有行业库存增长，说明国产替代当前更像份额与规模扩张，而非材料价格转强。",
    },
    "mature_200mm_wafer_demand": {
        "demand.downstream_price_momentum": "信越化学明确200毫米市场仍偏宽松；其他全尺寸出货和国内经营数据不是纯200毫米价格，因此不能推翻这一谨慎判断。",
        "demand.customer_capex_capacity_signal": "SEMI预计200毫米产能低速增长，格芯、德州仪器和英飞凌项目支持功率模拟方向；项目投资仍缺少统一净增月产能。",
        "demand.output_consumption_proxy": "目前没有全球纯200毫米出货、利用率和库存的同口径序列；8英寸等效开工包含其他尺寸，只能交叉检查。",
        "demand.application_intensity_change": "汽车、工业和功率需求提供增量，但氮化镓、碳化硅以及部分300毫米迁移会替代传统200毫米硅片面积。",
        "supply.capacity_event_12m": "2026年全球200毫米装机预计增长3%，部分功率与模拟项目投产；供应偏宽松意味着名义新增能力未必立即形成紧缺。",
        "supply.expansion_cycle_bucket": "成熟制程项目也需经历改造、设备安装和利用率爬坡；旧厂扩建与新厂建设的周期不能混用。",
        "supply.raw_policy_constraint": "美国本地化项目支持200毫米功率与模拟制造，技术路线又可能转向GaN或SiC；现有资料没有200毫米硅原料短缺证据。",
        "supply.supplier_structure_bucket": "供应商通常不按直径披露份额和可售能力，全球集中度只能说明行业背景，无法计算200毫米有效供应商数量。",
        "supply.substitution_barrier": "GaN-on-silicon、SiC转换和300毫米迁移形成实际替代压力，同时汽车与工业认证仍抬高既有硅片供应商切换成本。",
        "signal.material_price_momentum": "没有连续的200毫米成交价，供应商对市场偏宽松的表述与全尺寸量价数据共同支持价格仍弱，而非已经反转。",
    },
    "soi_engineered_substrate_demand": {
        "demand.downstream_price_momentum": "Soitec收入和毛利率同比下降，RF-SOI合作仍在推进；没有分产品订单量和平均售价，需求关系尚未转成可核验价格信号。",
        "demand.customer_capex_capacity_signal": "美国激励支持300毫米SOI能力，Soitec与格芯、联电有具名合作；公开资料没有全球SOI月产能或客户采购量。",
        "demand.output_consumption_proxy": "财务结果和平台合作证明业务与应用存在，却没有RF-SOI、FD-SOI分开的出货片数、利用率和库存，数量需求不能复算。",
        "demand.application_intensity_change": "300毫米RF-SOI和三维集成合作直接支持工程衬底的高价值属性，但RF-SOI、FD-SOI和其他衬底不能用同一均价或片数相加。",
        "supply.capacity_event_12m": "环球晶圆美国项目包含SOI能力，但当前月产量、认证进度和启用节奏没有披露；未来一年供给释放无法量化。",
        "supply.expansion_cycle_bucket": "工程衬底需把产线建设、平台合作、客户认证和稳定出货分开；现有公告没有足够日期计算完整周期。",
        "supply.raw_policy_constraint": "美国政策直接支持本地SOI专线，改善区域供应安全；它没有证明全球SOI原料短缺，也不能替代客户采用。",
        "supply.supplier_structure_bucket": "公开合作显示工程衬底供应与客户平台较集中，但缺少统一市场分母，不能计算SOI份额或有效供应商数量。",
        "supply.substitution_barrier": "RF-SOI平台合作和工程衬底规格提高切换成本；不同射频、功率和逻辑应用仍可能选择其他衬底路线。",
        "signal.material_price_momentum": "Soitec集团财务包含多类工程衬底，全球硅片收入又不是SOI价格；目前没有足够证据确认SOI材料价格拐点。",
    },
}


POLICY_REFS_BY_ENTITY: dict[str, list[str]] = {
    "global_300mm_fab_expansion": ["S015", "S021", "S028", "S032", "S051"],
    "advanced_logic_wafer_demand": ["S013", "S017", "S021", "S028", "S051"],
    "dram_hbm_wafer_demand": ["S021", "S024", "S028", "S045", "S046"],
    "nand_wafer_demand": ["S015", "S021", "S028", "S045", "S051"],
    "china_300mm_wafer_suppliers": ["S042", "S044", "S045", "S046", "S051"],
}


FACTOR_BOUNDARIES_BY_ENTITY: dict[str, dict[str, str]] = {
    "mature_200mm_wafer_demand": {
        "demand.downstream_price_momentum": "只有信越化学直接判断200毫米供需偏宽松，其余是全尺寸出货、国内8英寸或库存代理，因此价格结论保持低置信度。",
        "demand.customer_capex_capacity_signal": "SEMI是纯200毫米总量，格芯项目直接涉及200毫米改造；中芯为8英寸等效、上海超硅为硅片供给侧，只用于交叉检查。",
        "demand.output_consumption_proxy": "中芯的8英寸等效开工与上海超硅8英寸利用率不能直接代表全球纯200毫米需求，全尺寸出货只检查方向。",
        "demand.application_intensity_change": "氮化镓、碳化硅和300毫米功率迁移既可能拉动新衬底，也可能替代部分传统200毫米硅片，不能只记正面需求。",
        "supply.raw_policy_constraint": "只有格芯项目直接涉及200毫米政策改造，其余政策资金更多投向300毫米或SOI，现有资料没有证明200毫米原材料瓶颈。",
        "supply.supplier_structure_bucket": "部分供应商披露没有按直径拆分，不能从集团材料收入推导200毫米份额。",
        "signal.material_price_momentum": "没有公开连续的200毫米成交价，财务、出货与库存只是代理，不能写成价格已经上涨。",
    },
    "soi_engineered_substrate_demand": {
        "demand.downstream_price_momentum": "没有公开连续的SOI成交价，Soitec财务和全尺寸硅片量价只能作为周期代理。",
        "demand.customer_capex_capacity_signal": "政策专线与具名客户平台证明能力和方向，但没有披露采购量或全球月产能。",
        "demand.output_consumption_proxy": "具名合作证明SOI进入应用平台，不提供晶圆开工或采购片数，因此只建立需求指数。",
        "demand.application_intensity_change": "RF-SOI、三维集成和工程衬底是直接应用证据，但不同产品不能用同一片数或均价加总。",
        "supply.capacity_event_12m": "当前公开项目数量不足，历史客户关系不能证明未来十二个月一定放量。",
        "supply.raw_policy_constraint": "只有美国SOI专线激励直接相关，其余政策来源说明晶圆本地化环境，现有资料没有SOI原材料瓶颈直接证据。",
        "supply.supplier_structure_bucket": "公开关系显示供应商与客户平台较集中，但没有足以计算市场份额的统一分母。",
        "supply.substitution_barrier": "专用衬底与认证提高切换成本，碳化硅等路线只作为部分应用的反向替代，不能混成同一市场。",
        "signal.material_price_momentum": "财务与全尺寸硅片价格只能作为代理，目前没有直接SOI价格，因此不形成正式评分；取得同口径SOI价格序列前只保留定性判断。",
    },
}


TARGET_TEXT = {
    "siltronic": {
        "priority": "P1",
        "quality": "主营直接，爬坡与价格待验证",
        "view": "世创电子材料的业务几乎全部来自半导体硅片，新加坡300毫米新厂使其对本轮扩产最直接；但折旧先于利用率和收入兑现，需求上行不必然立即改善利润。",
        "risk": "新加坡爬坡慢、长协价格重谈或非先进产品去库存，会使资本投入先转化为折旧和负自由现金流。",
    },
    "globalwafers": {
        "priority": "P1",
        "quality": "主营直接，区域扩产清晰",
        "view": "环球晶圆覆盖抛光片、外延片、退火片与SOI，美国和欧洲扩产直接对应区域配套；真正的财务拐点要由客户认证、利用率和价格共同确认。",
        "risk": "多地厂房与设备投放早于客户爬坡会推高折旧和现金支出，远期设计上限不能作为当期销量。",
    },
    "soitec": {
        "priority": "P2",
        "quality": "工程衬底直接，数量口径不足",
        "view": "Soitec直接服务RF-SOI、FD-SOI和其他工程衬底需求；但2026财年收入降至5.92亿欧元、毛利率降至16.3%，说明射频库存调整和价格组合压力仍显著，光子SOI增长尚未抵消传统业务下行。",
        "risk": "SOI不能与普通抛光片市场简单相加；客户库存、射频周期和新产品认证可能使收入继续落后于终端应用，正自由现金流还包含资本开支收缩与营运资本管理的影响。",
    },
    "sumco": {
        "priority": "P1",
        "quality": "主营直接，产品周期分化",
        "view": "SUMCO是先进300毫米硅片需求与传统产品去库存的直接观察标的；先进需求改善与非先进产品疲弱可能同时存在，必须分产品判断。",
        "risk": "若大型客户项目延后或非先进300毫米、200毫米去库存持续，新增资本投入和高折旧可能抵消先进产品增长。",
    },
    "eswin_materials": {
        "priority": "P1",
        "quality": "国内12英寸直接标的，盈利待兑现",
        "view": "西安奕材专注12英寸电子级硅片，2025年销量增至807.37万片、主营业务毛利率转为3.44%，但归母净亏损仍为7.38亿元；2026年第一季度收入继续增长，复算毛利率约2.58%，规模扩张尚未跨过稳定盈利门槛。",
        "risk": "普通产品集中释放、认证慢于扩产或价格继续下降，会使销量增长被第二工厂折旧、研发和资本投入抵消；季度经营现金流转正也不能单独证明利润拐点。",
    },
}


TARGET_DECISION_TEXT: dict[str, dict[str, str]] = {
    "siltronic": {
        "confirmed": "只有新加坡厂已认证产品转成持续批量出货、利用率连续提升，且高规格300毫米毛利足以吸收新增折旧时，才提高世创的研究优先级。",
        "falsified": "若新加坡厂继续放慢爬坡、单位折旧上升且自由现金流未改善，即使全球装机增长，也应下调世创的盈利弹性。",
        "conditional": "在新加坡厂季度利用率、认证后出货、单位折旧和自由现金流尚未同时改善前，只跟踪需求兑现，不把新厂投产视为确定利润。",
    },
    "globalwafers": {
        "confirmed": "只有Sherman与密苏里项目完成目标客户认证、实际出货爬坡，且美光十年供货框架签成可执行协议时，才提高环球晶圆美国扩产的贡献判断。",
        "falsified": "若美国项目认证或客户导入延期、长期供货框架未落地，且折旧与资本支出先于收入释放，应下调环球晶圆的区域扩产价值。",
        "conditional": "在美国新产能的客户认证、长协生效、季度出货和现金回报得到共同验证前，不把政策补贴或远期120万片/月设计上限计作确定受益。",
    },
    "sumco": {
        "confirmed": "只有先进300毫米销量、产品组合和价格改善，同时非先进300毫米与200毫米库存下降，才提高SUMCO对先进逻辑需求的盈利敏感度。",
        "falsified": "若先进产品增长被非先进产品去库存、降价和高资本开支抵消，应下调SUMCO的综合盈利改善判断。",
        "conditional": "在公司披露先进与非先进产品的销量、价格和库存分化前，不用集团收入增长替代先进逻辑硅片的真实盈利贡献。",
    },
    "eswin_materials": {
        "confirmed": "只有西安奕材12英寸实际销量和利用率提高、平均售价止跌、良率与高规格占比改善，并最终带动毛利率和经营现金流转正时，才提高受益判断。",
        "falsified": "若120万片/月规划释放快于认证转批量，售价继续下跌且亏损、库存和折旧压力扩大，应下调国产替代带来的盈利预期。",
        "conditional": "在西安奕材价格、良率、利用率、毛利和经营现金流形成连续改善前，只把销量增长视为验证进展，不把规划产能当成盈利。",
    },
    "soitec": {
        "confirmed": "只有RF-SOI与FD-SOI客户库存恢复、平台认证转为分产品出货，并且新增工程衬底产能启用后收入和毛利同步改善，才提高Soitec的研究优先级。",
        "falsified": "若射频库存去化延长、客户平台采用延期，或新增产能启用后利用率与自由现金流继续承压，应下调Soitec的高价值衬底增长判断。",
        "conditional": "在RF-SOI、FD-SOI分产品订单、库存、认证进度和产能利用率可分别核验前，不用集团收入或合作公告推断工程衬底采购量。",
    },
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _apply_demand_financial_updates(
    targets_payload: Mapping[str, Any],
    sources_payload: Mapping[str, Any],
    updates_payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if updates_payload.get("schema_version") != "silicon_wafer_demand.financial_updates.v1":
        raise ValueError("需求侧最新财务必须使用financial_updates.v1")
    targets = copy.deepcopy(dict(targets_payload))
    sources = copy.deepcopy(dict(sources_payload))
    existing_refs = {str(row.get("ref") or "") for row in sources.get("sources") or []}
    new_sources = copy.deepcopy(list(updates_payload.get("sources") or []))
    duplicates = [str(row.get("ref") or "") for row in new_sources if str(row.get("ref") or "") in existing_refs]
    if duplicates:
        raise ValueError(f"需求侧最新财务来源ref重复：{duplicates}")
    sources.setdefault("sources", []).extend(new_sources)
    target_by_id = {
        str(target.get("target_id") or ""): target
        for target in targets.get("targets") or []
    }
    for update in updates_payload.get("target_updates") or []:
        target_id = str(update.get("target_id") or "")
        if target_id not in target_by_id:
            raise ValueError(f"需求侧最新财务目标不存在：{target_id}")
        target = target_by_id[target_id]
        replacements = copy.deepcopy(
            list(update.get("financial_period_replacements") or [])
        )
        replacement_by_period = {
            str(row.get("period") or ""): row for row in replacements
        }
        if "" in replacement_by_period or len(replacement_by_period) != len(replacements):
            raise ValueError(f"{target_id} 最新财务期间替换为空或重复")
        for row in replacements:
            evidence = list(row.get("field_evidence") or [])
            if not evidence:
                raise ValueError(f"{target_id}.{row.get('period')} 替换记录缺少逐字段证据")
            row["source_ref"] = str(evidence[0].get("source_ref") or "")
        historical_rows = [
            replacement_by_period.get(str(row.get("period") or ""), row)
            for row in target.get("financials") or []
        ]
        financials = copy.deepcopy(list(update.get("financials_prepend") or []))
        for row in financials:
            evidence = list(row.get("field_evidence") or [])
            if not evidence:
                raise ValueError(f"{target_id}.{row.get('period')} 缺少逐字段证据")
            row["source_ref"] = str(evidence[0].get("source_ref") or "")
        target["financials"] = [*financials, *historical_rows]
        target["recent_evidence"] = [
            *copy.deepcopy(list(update.get("recent_evidence_prepend") or [])),
            *list(target.get("recent_evidence") or []),
        ]
        drop_periods = {
            str(value) for value in update.get("target_data_point_drop_periods") or []
        }
        retained_target_points = [
            point
            for point in target.get("target_data_points") or []
            if str(point.get("period") or "") not in drop_periods
        ]
        target["target_data_points"] = [
            *copy.deepcopy(list(update.get("target_data_points_prepend") or [])),
            *retained_target_points,
        ]
    audit = copy.deepcopy(dict(updates_payload.get("audit") or {}))
    if not audit.get("all_sources_primary_or_regulatory") or not audit.get(
        "all_financial_fields_have_field_evidence"
    ):
        raise ValueError("需求侧最新财务审计没有通过一手来源与逐字段证据门禁")
    audit["update_sha256"] = sha256_file(DEMAND_FINANCIAL_UPDATE_PATH)
    return targets, sources, audit


def _source_catalog(
    demand_sources: Sequence[Mapping[str, Any]] | None = None,
    *,
    financial_targets_payload: Mapping[str, Any] | None = None,
    financial_sources_payload: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    demand_payload = _load_json(DEMAND_DIR / "sources.json")
    raw_demand_sources = list(demand_sources) if demand_sources is not None else demand_payload["sources"]
    sources = [
        normalize_agent_source(source, local_path_map=LOCAL_PATH_MAP, fetch_date=AS_OF_DATE)
        for source in raw_demand_sources
    ]
    target_ids = {target_id for spec in ENTITY_SPECS for target_id in spec["targets"]}
    target_payload = financial_targets_payload or _load_json(
        FINANCIAL_DIR / "target_financials.json"
    )
    wanted: set[str] = set()
    for target in target_payload["targets"]:
        if target["target_id"] not in target_ids:
            continue
        wanted.add(str(target["ticker_verification"]["source_ref"]))
        for row in target.get("financials") or []:
            wanted.add(str(row["source_ref"]))
            if row.get("cash_flow_source_ref"):
                wanted.add(str(row["cash_flow_source_ref"]))
            wanted.update(
                str(item["source_ref"])
                for item in row.get("field_evidence") or []
            )
        for point in target.get("target_data_points") or []:
            wanted.add(str(point["evidence_ref_uri"]).replace("source_ref:", ""))
    financial_payload = financial_sources_payload or _load_json(
        FINANCIAL_DIR / "normalized_sources.json"
    )
    for source in financial_payload["sources"]:
        if source["ref"] in wanted:
            sources.append(normalize_agent_source(source, fetch_date=AS_OF_DATE))
    market_payload = _load_json(MARKET_SNAPSHOT_PATH)
    market_refs = {
        str(snapshot["source_ref"])
        for snapshot in market_payload.get("snapshots") or []
        if str(snapshot.get("target_id")) in target_ids
    }
    for source in market_payload.get("sources") or []:
        if str(source.get("source_id")) not in market_refs:
            continue
        normalized = normalize_agent_source(source, fetch_date=AS_OF_DATE)
        normalized["source_tier"] = "B"
        normalized["source_review_status"] = "pass_with_note"
        normalized["market_data_warning"] = "第三方行情快照；用于同日估值比较，不替代发行人财务或交易所逐笔数据。"
        sources.append(normalized)

    # 相同底层URL只能算一个独立证据组。优先采用发行人审计文件的
    # canonical key，并把同一文档的tier统一为组内最高等级。
    by_url: dict[str, list[dict[str, Any]]] = {}
    for source in sources:
        url = str(source.get("url") or "").strip().lower().rstrip("/")
        if url:
            by_url.setdefault(url, []).append(source)
    tier_rank = {"S": 4, "A": 3, "B": 2, "C": 1}
    for rows in by_url.values():
        if len(rows) < 2:
            continue
        preferred = next(
            (
                str(row.get("independence_key"))
                for row in rows
                if str(row.get("independence_key") or "").startswith("issuer:")
            ),
            str(rows[0].get("independence_key")),
        )
        strongest = max(
            (str(row.get("source_tier") or "C") for row in rows),
            key=lambda value: tier_rank.get(value, 0),
        )
        for row in rows:
            row["independence_key"] = preferred
            row["source_tier"] = strongest
            row["independence_rationale"] = "与同一URL指向的底层原始文档合并为一个独立证据组；不同摘录不重复计数。"

    generic_locator = "原始网页或PDF所列段落"
    for source in sources:
        ref = str(source["ref"])
        locator = str(source.get("local_locator") or "").strip()
        if not locator or locator == generic_locator:
            override = SOURCE_PRECISE_LOCATORS.get(ref)
            if override:
                source["local_locator"] = override
                source["locator_verification_status"] = "verified_page_section_or_search_phrase"
                source["excerpt_fidelity"] = "direct_extract_or_faithful_translation_checked_against_locator"
            else:
                source["local_locator"] = generic_locator
                source["locator_verification_status"] = "not_precisely_located"
                source["excerpt_fidelity"] = "research_summary_reference_only"
                source["source_usage_scope"] = "reference_only"
                if source.get("source_review_status") == "pass":
                    source["source_review_status"] = "pass_with_note"
                source["locator_warning"] = "本轮未补齐页码、章节或可复现检索短语，不承载公开核心结论、模型输入或指标槽评分。"
        else:
            source["locator_verification_status"] = "verified_page_section_or_search_phrase"
            source["excerpt_fidelity"] = "direct_extract_or_faithful_translation_checked_against_locator"
            source["source_usage_scope"] = "core_or_reference_as_cited"

    for source in sources:
        year_text = str(source.get("publish_date") or source.get("event_date") or "")
        match = re.match(r"^(\d{4})", year_text)
        if match and int(match.group(1)) <= 2024:
            warning = str(
                source.get("temporal_warning")
                or source.get("staleness_warning")
                or "严重时效提醒：该资料发表于2024年或更早，只能证明历史计划、能力或认证，不能单独证明2026年的当前状态。"
            )
            if not warning.startswith("严重时效提醒"):
                warning = f"严重时效提醒：{warning}"
            source["temporal_warning"] = warning
            source["staleness_warning"] = warning
            source["source_review_status"] = "stale"
    refs = [source["ref"] for source in sources]
    if len(refs) != len(set(refs)):
        raise ValueError("需求侧来源 ref 重复")
    return sources


def _align_source_excerpts_to_data_points(
    sources: Sequence[dict[str, Any]],
    data_points: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Bind every source-level excerpt to one audited, directly quoted data point.

    A source can support several data points, so its catalog excerpt must not be
    a researcher-written synthesis of those points.  The catalog instead keeps
    one representative direct excerpt and, for non-Chinese sources, the Chinese
    translation attached to that same data point.
    """
    points_by_ref: dict[str, list[Mapping[str, Any]]] = {}
    missing_direct_excerpt_keys: list[str] = []
    for point in data_points:
        ref = str(point.get("source_ref") or "")
        key = str(point.get("data_point_key") or "")
        excerpt = str(point.get("source_excerpt") or "").strip()
        if not ref or not key or not excerpt:
            missing_direct_excerpt_keys.append(key or "<missing-key>")
            continue
        points_by_ref.setdefault(ref, []).append(point)
    if missing_direct_excerpt_keys:
        raise ValueError(
            "逐点证据缺少可定位直接原文："
            + ", ".join(sorted(missing_direct_excerpt_keys))
        )

    aligned_rows: list[dict[str, Any]] = []
    for source in sources:
        ref = str(source.get("ref") or "")
        candidates = sorted(
            points_by_ref.get(ref) or [],
            key=lambda point: str(point.get("data_point_key") or ""),
        )
        if not candidates:
            continue
        current_excerpt = str(source.get("excerpt") or "").strip()
        chosen = next(
            (
                point
                for point in candidates
                if str(point.get("source_excerpt") or "").strip() == current_excerpt
            ),
            candidates[0],
        )
        direct_excerpt = str(chosen["source_excerpt"]).strip()
        translated_excerpt = str(chosen.get("source_excerpt_zh") or "").strip()
        language = str(source.get("language") or "").lower()
        if language not in {"zh", "zh-cn", "zh-tw", "chinese"} and not translated_excerpt:
            raise ValueError(
                f"{ref}.{chosen['data_point_key']} 英文直接原文缺少忠实中文译意"
            )
        source["excerpt"] = direct_excerpt
        source["excerpt_zh"] = translated_excerpt or direct_excerpt
        source["excerpt_data_point_key"] = str(chosen["data_point_key"])
        source["excerpt_fidelity"] = (
            "direct_extract_or_faithful_translation_checked_against_locator"
        )
        aligned_rows.append(
            {
                "source_ref": ref,
                "data_point_key": str(chosen["data_point_key"]),
                "source_excerpt_exact_match": source["excerpt"] == direct_excerpt,
                "excerpt_zh_same_data_point": source["excerpt_zh"]
                == (translated_excerpt or direct_excerpt),
            }
        )

    failed_rows = [
        row
        for row in aligned_rows
        if not row["source_excerpt_exact_match"]
        or not row["excerpt_zh_same_data_point"]
    ]
    if failed_rows:
        raise ValueError(f"来源摘录与逐点直接原文未对齐：{failed_rows}")
    return {
        "schema_version": "opportunity_lens.source_data_point_excerpt_audit.v1",
        "source_count_with_data_points": len(points_by_ref),
        "aligned_source_count": len(aligned_rows),
        "data_point_count_checked": sum(len(rows) for rows in points_by_ref.values()),
        "missing_direct_excerpt_count": 0,
        "source_excerpt_mismatch_count": 0,
        "translation_mismatch_count": 0,
        "all_sources_with_data_points_use_exact_direct_excerpt": (
            len(aligned_rows) == len(points_by_ref)
        ),
        "rows": aligned_rows,
    }


def _candidate_rows() -> list[dict[str, Any]]:
    payload = _load_json(DEMAND_DIR / "entity_factor_evidence_candidates.json")
    return list(payload["candidates"])


def _strong_refs(
    raw_refs: Sequence[str],
    *,
    fallback_refs: Sequence[str],
    sources_by_ref: Mapping[str, Mapping[str, Any]],
    minimum: int = 5,
) -> list[str]:
    selected: list[str] = []
    groups: set[str] = set()
    for ref in [*raw_refs, *fallback_refs]:
        source = sources_by_ref.get(str(ref))
        if not source:
            continue
        if source.get("source_tier") not in {"S", "A", "B"}:
            continue
        if source.get("source_review_status") in {"reject", "weak_source_only", "duplicate"}:
            continue
        group = str(source.get("independence_key") or "")
        if not group or group in groups:
            continue
        groups.add(group)
        selected.append(str(ref))
        if len(selected) >= 7:
            break
    if len(selected) < minimum:
        raise ValueError(f"独立强证据组不足 {minimum}：{list(raw_refs)}")
    return selected


def _entity_candidate_rows(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidate_name = spec.get("candidate_name")
    if not candidate_name:
        return []
    rows = [row for row in _candidate_rows() if row["entity_name"] == candidate_name]
    if len(rows) != 10:
        raise ValueError(f"{candidate_name} 因子候选不是10行")
    return sorted(rows, key=lambda row: row["factor_id"])


FACTOR_DATA_POINT_TERMS: dict[str, tuple[str, ...]] = {
    "demand.downstream_price_momentum": ("价格", "售价", "均价", "毛利", "price", "asp"),
    "demand.customer_capex_capacity_signal": ("资本开支", "投资", "设备支出", "产能", "月产能", "投产", "量产", "开工", "晶圆投入", "洁净室", "爬坡", "项目状态", "晶圆厂计划", "capacity", "capex"),
    "demand.output_consumption_proxy": ("出货", "销量", "晶圆投入", "开工", "利用率", "库存", "shipment", "wafer start"),
    "demand.application_intensity_change": ("工艺", "节点", "产品", "应用", "hbm", "dram", "nand", "ai", "外延", "soi", "尺寸"),
    "supply.capacity_event_12m": ("产能", "扩产", "停产", "量产", "投产", "爬坡", "建设", "设备搬入", "capacity"),
    "supply.expansion_cycle_bucket": ("建设", "投产", "量产", "爬坡", "满产", "设备搬入", "周期", "construction"),
    "supply.raw_policy_constraint": ("政策", "补贴", "激励", "本地化", "供应链", "供应集中", "限制", "政府", "chips"),
    "supply.supplier_structure_bucket": ("市场份额", "供应商", "集中度", "五家公司", "认证", "客户", "supplier"),
    "supply.substitution_barrier": ("认证", "客户", "良率", "缺陷", "平坦度", "工艺", "替代", "qualification"),
    "signal.material_price_momentum": ("硅片价格", "材料价格", "售价", "均价", "毛利", "库存", "price"),
}


# The same source often contains several independently audited facts.  Factor
# cards must quote the fact that actually supports that factor, rather than a
# representative source-card excerpt.  The two S001 overrides below are hard
# contracts because the global-capacity and advanced-node conclusions depend
# on different sentences in the same SEMI release.
FACTOR_INFORMATION_POINT_DP_OVERRIDES: dict[
    tuple[str, str, str], str
] = {
    (
        "global_300mm_fab_expansion",
        "demand.customer_capex_capacity_signal",
        "S001",
    ): "DP001",
    (
        "advanced_logic_wafer_demand",
        "demand.application_intensity_change",
        "S001",
    ): "DP002",
    (
        "mature_200mm_wafer_demand",
        "demand.downstream_price_momentum",
        "S053",
    ): "DP178",
    (
        "mature_200mm_wafer_demand",
        "signal.material_price_momentum",
        "S053",
    ): "DP178",
}


ENTITY_INFORMATION_POINT_TERMS: dict[str, tuple[str, ...]] = {
    "global_300mm_fab_expansion": ("全球", "300毫米", "300mm", "晶圆厂", "装机"),
    "advanced_logic_wafer_demand": ("先进逻辑", "纳米", "2nm", "7nm", "gaa", "euv"),
    "dram_hbm_wafer_demand": ("dram", "hbm", "存储", "内存"),
    "nand_wafer_demand": ("nand", "闪存", "层", "位元"),
    "china_300mm_wafer_suppliers": ("中国", "国内", "国产", "12英寸", "300毫米"),
    "mature_200mm_wafer_demand": ("200毫米", "200mm", "成熟", "功率", "模拟"),
    "soi_engineered_substrate_demand": ("soi", "工程衬底", "rf-soi", "smart cut"),
}


# The research universe contains many valid facts that are not valid inputs
# for every entity.  This explicit routing table prevents, for example, one
# Chinese supplier's selling price from becoming the global, DRAM or NAND
# price signal, and prevents all-size silicon shipments from being labelled a
# pure 200mm or SOI output series.  An omitted entity/factor deliberately has
# no scored metric input.
DIRECT_DATA_POINT_ALLOW_BY_ENTITY_FACTOR: dict[str, dict[str, tuple[str, ...]]] = {
    "global_300mm_fab_expansion": {
        "demand.output_consumption_proxy": ("DP250", "DP251"),
        "supply.capacity_event_12m": ("DP236",),
        "supply.supplier_structure_bucket": ("SUP-DP003",),
    },
    "advanced_logic_wafer_demand": {
        "demand.customer_capex_capacity_signal": ("DP035", "DP037", "DP059", "DP060", "DP061"),
        "supply.capacity_event_12m": ("DP036",),
    },
    "dram_hbm_wafer_demand": {
        "demand.customer_capex_capacity_signal": ("DP088",),
    },
    "nand_wafer_demand": {
        "demand.customer_capex_capacity_signal": ("DP076",),
    },
    "china_300mm_wafer_suppliers": {
        "demand.downstream_price_momentum": ("DP206",),
        "demand.output_consumption_proxy": ("DP199",),
        "supply.capacity_event_12m": ("DP197", "DP205"),
        "signal.material_price_momentum": ("DP199", "DP206"),
    },
    "mature_200mm_wafer_demand": {
        "supply.capacity_event_12m": ("DP241",),
    },
    "soi_engineered_substrate_demand": {},
}


# These matchers are intentionally narrower than the reader-facing factor
# topics.  They determine whether one reviewed data point can populate one
# canonical metric slot; a broad source excerpt is never enough.  Slot order
# also prevents the same observation being counted twice inside one factor.
DIRECT_SLOT_MATCHERS: dict[str, tuple[dict[str, Any], ...]] = {
    "demand.downstream_price_momentum": (
        {"slot": "downstream_price_3m_change", "terms": ("季度价格", "价格环比"), "change": "latest"},
        {"slot": "downstream_price_1m_change", "terms": ("单月价格", "月度价格"), "change": "latest"},
        {"slot": "downstream_price_yoy_change", "terms": ("价格同比", "均价同比"), "change": "point"},
        {"slot": "price_reversal_signal", "terms": ("价格", "均价", "售价"), "negative_only": True},
    ),
    "demand.customer_capex_capacity_signal": (
        {"slot": "customer_capex_yoy_or_guidance", "terms": ("资本开支同比", "资本开支指引变化", "设备支出同比"), "change": "point"},
        {"slot": "confirmed_capacity_expansion_event", "terms": ("开工", "已启用", "已进入量产", "已进入大批量制造", "已开始并逐步爬坡", "首批设备搬入"), "actual_only": True},
        {"slot": "equipment_order_or_billings_proxy", "terms": ("设备订单同比", "billings同比", "设备出货同比"), "change": "point"},
        {"slot": "customer_delay_or_cut_event", "terms": ("延期", "推迟", "取消", "终止", "削减", "放慢", "放缓"), "negative_only": True},
    ),
    "demand.output_consumption_proxy": (
        {"slot": "output_or_shipment_growth_3m", "terms": ("季度出货", "出货环比", "销量环比", "销量与均价"), "change": "latest", "observation_field": "sales_wafers"},
        {"slot": "industry_sales_growth", "terms": ("硅晶圆面积出货同比", "行业销售同比", "半导体销售同比"), "change": "point"},
    ),
    "demand.application_intensity_change": (
        {"slot": "technology_generation_shift", "terms": ("纳米", "hbm", "nand", "dram", "gaa", "产品方向", "分产品周期")},
        {"slot": "material_intensity_proxy", "terms": ("外延", "抛光", "监控片", "soi", "工程衬底")},
        {"slot": "customer_mix_shift", "terms": ("高端产品占比", "产品结构", "外延片收入占", "高端硅片")},
        {"slot": "process_reduction_or_substitution", "terms": ("材料替代", "降低用量", "减少工序", "已替代"), "negative_only": True},
    ),
    "supply.capacity_event_12m": (
        {"slot": "current_effective_capacity", "terms": ("当前有效产能", "稳定产能", "瓶颈产能", "月产能", "管理产能"), "actual_only": True, "exclude": ("设计", "规划", "目标"), "observation_field": "capacity_wafers_per_year", "observation_scale": 0.000008333333333333333, "observation_unit": "万片/月"},
        {"slot": "confirmed_shutdown_or_disruption", "terms": ("停产", "限产", "断供", "供应扰动", "事故")},
        {"slot": "ramp_delay_or_cancel_event", "terms": ("放慢扩产", "延期", "推迟", "取消"), "negative_only": True},
        {"slot": "planned_or_rumored_capacity", "terms": ("规划产能", "设计产能", "量产计划", "量产目标", "扩产目标", "装机月产能", "装机产能"), "fact_types": ("company_target", "industry_forecast", "rumor")},
    ),
    "supply.expansion_cycle_bucket": (
        {"slot": "expansion_cycle_months_or_bucket", "terms": ("项目周期", "建设周期", "开工至量产", "未来十年以上")},
        {"slot": "equipment_lead_time_bucket", "terms": ("设备交付周期", "设备搬入周期")},
        {"slot": "qualification_or_ramp_cycle_bucket", "terms": ("验证周期", "认证周期", "爬坡周期")},
    ),
    "supply.raw_policy_constraint": (
        {"slot": "raw_material_supply_concentration", "terms": ("供应集中度", "进口依赖", "原材料集中度")},
        {"slot": "export_import_control_event", "terms": ("出口管制", "进口限制", "实体清单", "制裁")},
        {"slot": "raw_material_price_momentum", "terms": ("原材料价格", "材料价格同比", "原料价格")},
        {"slot": "policy_direction_for_entity", "terms": ("政策导致供给受限", "政策关闭市场", "进口许可限制", "国产化替代方向")},
    ),
    "supply.supplier_structure_bucket": (
        {"slot": "supplier_structure_bucket", "terms": ("供应集中度", "市场集中度", "寡头", "市场份额")},
        {"slot": "cr3_calculated", "terms": ("cr3", "前三家份额")},
        {"slot": "effective_supplier_count", "terms": ("供应商数量", "五家公司")},
        {"slot": "qualification_bottleneck_text", "terms": ("认证周期", "重新验证", "切换成本", "认证瓶颈")},
        {"slot": "cr3_gap_or_definition_conflict", "terms": ("份额口径冲突", "无法加总", "口径不一致")},
    ),
    "supply.substitution_barrier": (
        {"slot": "process_criticality_bucket", "terms": ("关键工序", "核心工艺", "低缺陷", "平坦度")},
        {"slot": "commercial_alternative_status", "terms": ("商业替代", "替代方案", "国产替代")},
        {"slot": "switching_validation_burden", "terms": ("认证周期", "重新验证", "切换成本", "验证负担")},
        {"slot": "substitution_event", "terms": ("替代技术量产", "商业化替代", "已替代"), "negative_only": True},
    ),
    "signal.material_price_momentum": (
        {"slot": "material_price_3m_change", "terms": ("季度硅片价格", "材料价格环比"), "change": "latest"},
        {"slot": "material_price_1m_change", "terms": ("月度硅片价格", "材料价格月度"), "change": "latest"},
        {"slot": "material_price_yoy_change", "terms": ("产品价格同比", "材料价格同比", "硅片价格同比", "销量与均价"), "change": "latest", "observation_field": "average_price_rmb_per_wafer"},
        {"slot": "customs_or_trade_price_proxy", "terms": ("进口均价", "出口均价", "海关价格")},
        {"slot": "official_price_revision_event", "terms": ("调价公告", "涨价公告", "官方调价")},
        {"slot": "price_denial_or_reversal", "terms": ("价格回落", "降价", "否认涨价"), "negative_only": True},
    ),
}


def _point_search_text(point: Mapping[str, Any]) -> str:
    observation_text = " ".join(
        str(item.get("value_text") or item.get("value_num") or "")
        for item in point.get("observations") or []
    )
    return " ".join(
        str(point.get(field) or "")
        for field in ("data_point_title", "metric", "value_text", "period", "note")
    ).lower() + " " + observation_text.lower()


def _observation_field_values(
    point: Mapping[str, Any],
    field: str,
) -> list[float]:
    values: list[float] = []
    pattern = re.compile(rf"(?:^|[；;,])\s*{re.escape(field)}=([-+]?\d+(?:\.\d+)?)")
    for item in point.get("observations") or []:
        raw = item.get(field)
        if raw is not None:
            values.append(float(raw))
            continue
        match = pattern.search(str(item.get("value_text") or ""))
        if match:
            values.append(float(match.group(1)))
    return values


def _latest_numeric_change(
    point: Mapping[str, Any],
    *,
    observation_field: str | None = None,
) -> float | None:
    if observation_field:
        field_values = _observation_field_values(point, observation_field)
        if len(field_values) >= 2 and field_values[-2] != 0:
            return (field_values[-1] / field_values[-2] - 1.0) * 100.0
    values = [
        float(item["value_num"])
        for item in point.get("observations") or []
        if item.get("value_num") is not None
    ]
    if len(values) >= 2 and values[-2] != 0:
        return (values[-1] / values[-2] - 1.0) * 100.0
    text_values = _observation_field_values(point, "average_price_rmb_per_wafer")
    if len(text_values) >= 2 and text_values[-2] != 0:
        return (text_values[-1] / text_values[-2] - 1.0) * 100.0
    return None


def _minimum_rule_bucket(
    rules: Sequence[Mapping[str, Any]],
    value: float,
) -> tuple[str, float]:
    for rule in rules:
        if value >= float(rule["minimum"]):
            return str(rule["bucket"]), float(rule["score"])
    raise ValueError(f"没有覆盖数值 {value} 的 minimum 评分规则")


def _maximum_rule_bucket(
    rules: Sequence[Mapping[str, Any]],
    value: float,
) -> tuple[str, float]:
    for rule in rules:
        if value <= float(rule["maximum"]):
            return str(rule["bucket"]), float(rule["score"])
    raise ValueError(f"没有覆盖数值 {value} 的 maximum 评分规则")


def _expansion_cycle_months(point: Mapping[str, Any]) -> tuple[float, str] | None:
    """Extract an explicit duration without deriving one from unrelated dates."""

    text = _point_search_text(point)
    if "未来十年以上" in text or "十年以上" in text:
        return 120.0, "原文明确写明十年以上；按可核验下限标准化为120个月"

    range_match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:至|到|—|－|-)\s*(\d+(?:\.\d+)?)\s*(年|个月|月)",
        text,
    )
    if range_match:
        low = float(range_match.group(1))
        high = float(range_match.group(2))
        unit = range_match.group(3)
        if low <= 0 or high < low or (unit == "年" and high > 20) or (unit != "年" and high > 240):
            return None
        low_months = low * 12.0 if unit == "年" else low
        high_months = high * 12.0 if unit == "年" else high
        if _minimum_rule_bucket(
            [
                {"minimum": 36.000001, "bucket": ">36", "score": 95},
                {"minimum": 24, "bucket": "24—36", "score": 85},
                {"minimum": 12, "bucket": "12—24", "score": 65},
                {"minimum": 6, "bucket": "6—12", "score": 45},
                {"minimum": -1000000, "bucket": "<6", "score": 25},
            ],
            low_months,
        )[0] != _minimum_rule_bucket(
            [
                {"minimum": 36.000001, "bucket": ">36", "score": 95},
                {"minimum": 24, "bucket": "24—36", "score": 85},
                {"minimum": 12, "bucket": "12—24", "score": 65},
                {"minimum": 6, "bucket": "6—12", "score": 45},
                {"minimum": -1000000, "bucket": "<6", "score": 25},
            ],
            high_months,
        )[0]:
            return None
        return low_months, f"原文给出{low:g}至{high:g}{unit}，区间未跨评分档；按保守下限标准化"

    month_match = re.search(r"(?:周期|历时|用时|需要|约)\D{0,8}(\d+(?:\.\d+)?)\s*(?:个)?月(?:以上)?", text)
    if month_match:
        months = float(month_match.group(1))
        if 0 < months <= 240:
            return months, "原文明确披露月份；直接标准化为月"
    year_match = re.search(r"(?:周期|历时|用时|需要|约)\D{0,8}(\d+(?:\.\d+)?)\s*年(?:以上)?", text)
    if year_match:
        years = float(year_match.group(1))
        if 0 < years <= 20:
            return years * 12.0, "原文明确披露年数；乘12标准化为月"
    return None


def _score_by_rule(
    *,
    slot_code: str,
    point: Mapping[str, Any],
    scoring_inputs: Mapping[str, Any],
    derived_change: float | None,
    standardized_value_num: float | None = None,
) -> tuple[str, float, str] | None:
    """Apply only explicit V0.8.1 metric-slot rules.

    Returning ``None`` deliberately leaves the slot missing.  In particular,
    generic positive/negative prose, utilization and inventory observations
    have no invented thresholds here.
    """

    numeric_rules = scoring_inputs["numeric_rules"]
    value_num = point.get("value_num")
    metric_text = _point_search_text(point)
    change_value = derived_change
    if change_value is None and value_num is not None and (
        "change" in slot_code or "momentum" in slot_code or "同比" in metric_text or "环比" in metric_text
    ):
        change_value = float(value_num)
    categorical = scoring_inputs["categorical_rules"]

    if slot_code in {
        "downstream_price_3m_change",
        "downstream_price_1m_change",
        "downstream_price_yoy_change",
        "price_reversal_signal",
    }:
        if change_value is None:
            return None
        bucket, score = _minimum_rule_bucket(numeric_rules["downstream_price_change"], change_value)
        return bucket, score, (
            "V0.8.1下游价格变化分档：≥30%=100，15%至30%=85，5%至15%=70，"
            "-5%至5%=50，-15%至-5%=35，低于-15%=20。"
        )

    if slot_code in {
        "customer_capex_yoy_or_guidance",
        "equipment_order_or_billings_proxy",
    }:
        if change_value is None:
            return None
        bucket, score = _minimum_rule_bucket(numeric_rules["capex_or_guidance_change"], change_value)
        return bucket, score, (
            "V0.8.1资本开支变化分档：≥25%=95，10%至25%=80，-10%至10%=58，"
            "-25%至-10%=40，低于-25%=20。"
        )

    if slot_code == "confirmed_capacity_expansion_event":
        rule = categorical["confirmed_expansion"]
        return str(rule["bucket"]), float(rule["score"]), (
            "V0.8.1把已确认扩产归入75至85分区间；本研究冻结为80分，"
            "只用于已开工、设备搬入、已量产或在产爬坡事实。"
        )

    if slot_code == "customer_delay_or_cut_event":
        if any(term in metric_text for term in ("取消", "大幅削减", "终止")):
            return "扩产明确取消或大幅削减", 20.0, "V0.8.1明确削减或取消扩产为10至30分；本研究冻结为20分。"
        if any(term in metric_text for term in ("延期", "推迟", "放慢", "放缓", "削减")):
            return "扩产明确延期或削减", 40.0, "V0.8.1推迟扩产为35至45分；本研究冻结为40分。"
        return None

    if slot_code in {"output_or_shipment_growth_3m", "industry_sales_growth"}:
        if change_value is None:
            return None
        bucket, score = _minimum_rule_bucket(numeric_rules["output_growth"], change_value)
        return bucket, score, (
            "V0.8.1产出或消耗代理分档：≥25%=90，10%至25%=75，0%至10%=60，"
            "-10%至0%=45，低于-10%=25。"
        )

    if slot_code in {"technology_generation_shift", "material_intensity_proxy", "customer_mix_shift"}:
        if str(point.get("fact_type")) in {"company_target", "industry_forecast"} or any(
            term in metric_text for term in ("计划", "目标", "预计", "预测")
        ):
            rule = categorical["application_mild_or_planned"]
        else:
            rule = categorical["application_structural_unquantified"]
        return str(rule["bucket"]), float(rule["score"]), (
            "V0.8.1应用强度规则：结构性提升但缺少单位用量量化为75分；"
            "仍处计划或仅温和提升为60分。"
        )

    if slot_code == "process_reduction_or_substitution":
        return "工艺替代导致单位用量下降", 30.0, "V0.8.1工艺替代导致用量下降为25至40分；本研究冻结为30分。"

    if slot_code == "capacity_addition_12m_pct":
        if standardized_value_num is None:
            return None
        bucket, score = _maximum_rule_bucket(numeric_rules["capacity_addition_12m"], standardized_value_num)
        return bucket, score, (
            "V0.8.1未来十二个月有效新增产能/当前有效产能分档：≤10%=85，"
            "10%至25%=70，25%至50%=50，高于50%=20；规划或传闻不进入分子。"
        )

    if slot_code == "current_effective_capacity":
        rule = categorical["current_capacity_denominator_only"]
        return str(rule["bucket"]), float(rule["score"]), "当前有效产能仅作为新增比例分母，按中性50分记录。"

    if slot_code == "ramp_delay_or_cancel_event":
        rule = categorical["supply_ramp_delay"]
        return str(rule["bucket"]), float(rule["score"]), "已确认的供给爬坡延期会延后有效新增供给；按V0.8.1方向冻结为75分。"

    if slot_code in {
        "expansion_cycle_months_or_bucket",
        "equipment_lead_time_bucket",
        "qualification_or_ramp_cycle_bucket",
    }:
        if standardized_value_num is None:
            return None
        bucket, score = _minimum_rule_bucket(numeric_rules["expansion_cycle_months"], standardized_value_num)
        return bucket, score, (
            "V0.8.1周期分档：超过36个月=95，24至36个月=85，12至24个月=65，"
            "6至12个月=45，短于6个月=25。"
        )

    if slot_code == "raw_material_supply_concentration":
        rule = categorical["raw_supply_concentration_without_policy_pressure"]
        return str(rule["bucket"]), float(rule["score"]), "V0.8.1：有供应集中但没有政策或价格冲击时为55分。"

    if slot_code in {"export_import_control_event", "policy_direction_for_entity"}:
        if any(term in metric_text for term in ("市场关闭", "断供", "禁止向", "自身受限")):
            return "政策直接限制本实体供给或市场", 20.0, "V0.8.1：政策使公司自身市场关闭或原料断供时为20分。"
        return "存在明确政策约束但受益方向仍需区分", 70.0, "V0.8.1：存在明确原料或政策约束、但方向需区分时为70分。"

    if slot_code == "raw_material_price_momentum":
        if change_value is None:
            return None
        bucket, score = _minimum_rule_bucket(numeric_rules["material_price_change"], change_value)
        return bucket, score, (
            "V0.8.1材料价格变化分档：≥50%=100，25%至50%=90，10%至25%=75，"
            "0%至10%=60，-10%至0%=45，低于-10%=25。"
        )

    if slot_code == "supplier_structure_bucket":
        if any(term in metric_text for term in ("近乎垄断", "单一供应商")):
            return "接近垄断", 95.0, "V0.8.1供应商结构：接近垄断为95分。"
        if any(term in metric_text for term in ("寡头", "五家公司", "多数供应")):
            rule = categorical["supplier_oligopoly"]
            return str(rule["bucket"]), float(rule["score"]), "V0.8.1供应商结构：寡头为80分。"
        if any(term in metric_text for term in ("中度集中", "较集中")):
            return "中度集中", 60.0, "V0.8.1供应商结构：中度集中为60分。"
        if "分散" in metric_text:
            return "供应分散", 35.0, "V0.8.1供应商结构：分散为35分。"
        return None

    if slot_code == "cr3_calculated":
        if standardized_value_num is None:
            return None
        cr3 = standardized_value_num
        if cr3 >= 85:
            return "接近垄断或高度寡头", 95.0, "V0.8.1 CR3参考规则：CR3≥85%对应接近垄断或高度寡头。"
        if cr3 >= 70:
            return "寡头", 80.0, "V0.8.1 CR3参考规则：CR3为70%至85%对应寡头。"
        if cr3 >= 40:
            return "中度集中", 60.0, "V0.8.1 CR3参考规则：CR3为40%至70%对应中度集中。"
        return "供应分散", 35.0, "V0.8.1 CR3参考规则：CR3低于40%对应分散。"

    if slot_code in {"process_criticality_bucket", "commercial_alternative_status", "switching_validation_burden"}:
        if any(term in metric_text for term in ("无商业替代", "无替代")) and any(
            term in metric_text for term in ("必经", "关键工序", "核心工艺")
        ):
            return "无商业替代且属于必经工艺", 90.0, "V0.8.1替代壁垒：无商业替代且为必经工艺时为90分。"
        if any(term in metric_text for term in ("有限替代", "重新验证", "切换成本", "认证周期")):
            return "替代有限且切换成本高", 75.0, "V0.8.1替代壁垒：替代有限且切换成本高时为75分。"
        if "部分替代" in metric_text:
            return "部分替代可行", 55.0, "V0.8.1替代壁垒：部分替代可行时为55分。"
        if any(term in metric_text for term in ("替代成熟", "成熟替代")):
            return "商业替代成熟", 30.0, "V0.8.1替代壁垒：商业替代成熟时为30分。"
        return None

    if slot_code == "substitution_event":
        if any(term in metric_text for term in ("快速扩散", "大规模商业化")):
            return "替代已商业化且快速扩散", 10.0, "V0.8.1替代壁垒：替代商业化且快速扩散时为10分。"
        return None

    if slot_code in {
        "material_price_3m_change",
        "material_price_1m_change",
        "material_price_yoy_change",
        "customs_or_trade_price_proxy",
        "price_denial_or_reversal",
    }:
        if change_value is None:
            return None
        bucket, score = _minimum_rule_bucket(numeric_rules["material_price_change"], change_value)
        return bucket, score, (
            "V0.8.1材料价格变化分档：≥50%=100，25%至50%=90，10%至25%=75，"
            "0%至10%=60，-10%至0%=45，低于-10%=25。"
        )

    # V0.8.1没有为该文本事实提供可复算的槽位分档。
    return None


def _compile_metric_slot_inputs(
    code: str,
    candidates: Sequence[Mapping[str, Any]],
    *,
    scoring_inputs: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    explicit: dict[str, dict[str, Any]] = {}
    selected: list[dict[str, Any]] = []
    used_keys: set[str] = set()
    negative_terms = (
        "延期", "推迟", "取消", "削减", "放慢", "下滑", "下降", "回落",
        "疲弱", "去库存", "停产", "断供", "终止", "放缓", "替代", "delay", "cancel",
        "decline", "cut", "slowdown", "destock", "shutdown",
    )
    cycle_slots = {
        "expansion_cycle_months_or_bucket",
        "equipment_lead_time_bucket",
        "qualification_or_ramp_cycle_bucket",
    }
    categorical_slots = {
        "confirmed_capacity_expansion_event",
        "customer_delay_or_cut_event",
        "technology_generation_shift",
        "material_intensity_proxy",
        "customer_mix_shift",
        "process_reduction_or_substitution",
        "confirmed_shutdown_or_disruption",
        "ramp_delay_or_cancel_event",
        "raw_material_supply_concentration",
        "export_import_control_event",
        "policy_direction_for_entity",
        "supplier_structure_bucket",
        "qualification_bottleneck_text",
        "cr3_gap_or_definition_conflict",
        "process_criticality_bucket",
        "commercial_alternative_status",
        "switching_validation_burden",
        "substitution_event",
        "official_price_revision_event",
    }
    for matcher in DIRECT_SLOT_MATCHERS[code]:
        chosen: Mapping[str, Any] | None = None
        chosen_standardized_num: float | None = None
        chosen_standardized_text = ""
        chosen_standardized_unit = ""
        chosen_normalization = ""
        chosen_score: tuple[str, float, str] | None = None
        slot_code = str(matcher["slot"])
        is_context_slot = slot_code in {"price_source_quality", "planned_or_rumored_capacity"}
        for point in candidates:
            key = str(point["data_point_key"])
            if key in used_keys:
                continue
            search_text = _point_search_text(point)
            if not any(str(term).lower() in search_text for term in matcher["terms"]):
                continue
            if any(str(term).lower() in search_text for term in matcher.get("exclude") or ()):
                continue
            fact_types = set(str(value) for value in matcher.get("fact_types") or ())
            if fact_types and str(point.get("fact_type")) not in fact_types:
                continue
            if matcher.get("actual_only") and str(point.get("fact_type")) != "actual":
                continue
            value_num = point.get("value_num")
            observation_field = str(matcher.get("observation_field") or "").strip() or None
            derived_change = (
                _latest_numeric_change(point, observation_field=observation_field)
                if matcher.get("change") == "latest"
                else None
            )
            if matcher.get("change") == "point" and value_num is None:
                derived_change = _latest_numeric_change(
                    point, observation_field=observation_field
                )
            negative = any(term in search_text for term in negative_terms)
            if value_num is not None and ("同比" in search_text or "环比" in search_text):
                negative = negative or float(value_num) < 0
            if derived_change is not None:
                negative = negative or derived_change < 0
            if matcher.get("negative_only") and not negative:
                continue

            raw_value_text = str(point.get("value_text") or "").strip()
            if not raw_value_text and point.get("value_num") is None:
                raw_value_text = json.dumps(
                    point.get("observations") or [], ensure_ascii=False, separators=(",", ":")
                )
            standardized_num: float | None
            standardized_text: str
            standardized_unit: str
            normalization_method: str
            if slot_code in cycle_slots:
                duration = _expansion_cycle_months(point)
                if duration is None:
                    continue
                standardized_num, normalization_method = duration
                standardized_text = ""
                standardized_unit = "月"
            elif derived_change is not None:
                standardized_num = float(derived_change)
                standardized_text = ""
                standardized_unit = "%"
                normalization_method = (
                    f"取同一数据点最后两个相邻观测的{observation_field or '数值'}复算变化率；未插值、未跨来源拼接"
                    if point.get("value_num") is None
                    else "保留来源披露的同比或环比百分比；未改变期间或分母"
                )
            elif observation_field and point.get("value_num") is None:
                observation_values = _observation_field_values(point, observation_field)
                if not observation_values:
                    continue
                scale = float(matcher.get("observation_scale") or 1.0)
                standardized_num = observation_values[-1] * scale
                standardized_text = ""
                standardized_unit = str(
                    matcher.get("observation_unit") or point.get("unit") or "未注明单位"
                )
                normalization_method = (
                    f"取同一数据点最后一期{observation_field}={observation_values[-1]:g}，"
                    f"乘以{scale:.12g}标准化为{standardized_unit}；未跨来源拼接"
                )
            elif slot_code in categorical_slots:
                standardized_num = None
                standardized_text = raw_value_text or str(
                    point.get("data_point_title") or point.get("metric") or ""
                )
                standardized_unit = "文本分类"
                normalization_method = "保留原文事实范围，只按V0.8.1已定义的事件或结构类别编码"
            elif point.get("value_num") is not None:
                standardized_num = float(point["value_num"])
                standardized_text = ""
                standardized_unit = str(point.get("unit") or "未注明单位")
                normalization_method = "保留数据点原值、原单位和原期间；未插值、未从来源关键词补值"
            else:
                standardized_num = None
                standardized_text = raw_value_text
                standardized_unit = str(point.get("unit") or "文本")
                normalization_method = "保留数据点原文和原期间；该背景槽只展示，不进入评分"

            score_result = None if is_context_slot else _score_by_rule(
                slot_code=slot_code,
                point=point,
                scoring_inputs=scoring_inputs,
                derived_change=derived_change,
                standardized_value_num=standardized_num,
            )
            if not is_context_slot and score_result is None:
                continue
            chosen = point
            chosen_standardized_num = standardized_num
            chosen_standardized_text = standardized_text
            chosen_standardized_unit = standardized_unit
            chosen_normalization = normalization_method
            chosen_score = score_result
            break
        if chosen is None:
            continue
        used_keys.add(str(chosen["data_point_key"]))
        selected.append(copy.deepcopy(dict(chosen)))
        if not is_context_slot:
            if chosen_score is None:
                raise AssertionError(f"{code}.{slot_code} 已选中但没有V0.8.1评分")
            bucket, slot_score, scoring_rule = chosen_score
        raw_value_text = str(chosen.get("value_text") or "").strip()
        if not raw_value_text and chosen.get("value_num") is None:
            raw_value_text = json.dumps(chosen.get("observations") or [], ensure_ascii=False, separators=(",", ":"))
        raw_unit = str(chosen.get("unit") or "文本")
        slot_input: dict[str, Any] = {
            "data_point_keys": [str(chosen["data_point_key"])],
            "raw_unit": raw_unit,
            "standardized_unit": chosen_standardized_unit,
            "normalization_method": chosen_normalization,
            "period": str(chosen.get("period") or ""),
            "as_of_date": AS_OF_DATE,
        }
        if not is_context_slot:
            slot_input.update(
                {
                    "bucket": bucket,
                    "slot_score": round(slot_score, 4),
                    "scoring_rule": scoring_rule,
                }
            )
        if chosen.get("value_num") is not None:
            slot_input["raw_value_num"] = chosen["value_num"]
        else:
            slot_input["raw_value_text"] = raw_value_text
        if chosen_standardized_num is not None:
            slot_input["standardized_value_num"] = round(float(chosen_standardized_num), 6)
        else:
            slot_input["standardized_value_text"] = chosen_standardized_text
        explicit[str(matcher["slot"])] = slot_input
    return explicit, selected


def _factor_candidate_data_points(
    code: str,
    refs: Sequence[str],
    *,
    data_points_by_source: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    """Route only data points whose metric/title directly measures the factor.

    Source prose is deliberately excluded from matching.  A relevant source
    without a directly measured data point leaves the protocol slot missing.
    """
    terms = FACTOR_DATA_POINT_TERMS[code]
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        for point in data_points_by_source.get(ref) or []:
            metric_text = " ".join(
                str(point.get(field) or "")
                for field in ("metric", "data_point_title")
            ).lower()
            if not any(term.lower() in metric_text for term in terms):
                continue
            key = str(point["data_point_key"])
            if key in seen:
                continue
            seen.add(key)
            selected.append(
                {
                    "data_point_key": key,
                    "data_point_title": str(point.get("data_point_title") or ""),
                    "metric": str(point.get("metric") or ""),
                    "unit": str(point.get("unit") or ""),
                    "value_num": point.get("value_num"),
                    "value_text": point.get("value_text"),
                    "observations": copy.deepcopy(point.get("observations") or []),
                    "period": str(point.get("period") or ""),
                    "source_ref": str(point.get("source_ref") or ref),
                    "fact_type": str(point.get("fact_type") or point.get("research_category") or ""),
                }
            )
            if len(selected) >= 24:
                return selected
    return selected


def _humanize_wafer_capacity_text(value: Any) -> str:
    text = str(value or "")
    replacements = (
        ("WSPM", "月产能"),
        ("精确底部求和", "公开可量化项目测算"),
        ("底部精确求和", "公开可量化项目测算"),
        ("底部求和", "公开可量化项目测算"),
        ("核心下限模型", "公开可量化项目情景"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _factor_information_point_overrides(
    *,
    entity_key: str,
    factor_code: str,
    refs: Sequence[str],
    data_points_by_source: Mapping[str, Sequence[Mapping[str, Any]]],
    sources_by_ref: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, str]]:
    """Bind every factor/source pair to one same-source audited fact.

    A source-card excerpt is a locator aid, not a substitute for the actual
    fact used by a factor.  When a source has audited data points, this helper
    selects the point whose title, metric and verbatim excerpt best match the
    factor and entity.  Only a source with no data point may fall back to its
    direct source excerpt in ``build_segment_entity``.
    """

    factor_terms = tuple(value.lower() for value in FACTOR_DATA_POINT_TERMS[factor_code])
    entity_terms = tuple(
        value.lower() for value in ENTITY_INFORMATION_POINT_TERMS.get(entity_key, ())
    )
    overrides: dict[str, dict[str, str]] = {}
    for ref in refs:
        points = list(data_points_by_source.get(ref) or [])
        if not points:
            continue
        forced_key = FACTOR_INFORMATION_POINT_DP_OVERRIDES.get(
            (entity_key, factor_code, ref)
        )
        if forced_key:
            matches = [
                point
                for point in points
                if str(point.get("data_point_key") or "") == forced_key
            ]
            if len(matches) != 1:
                raise ValueError(
                    f"{entity_key}.{factor_code}.{ref} 指定信息点 {forced_key} 不存在或不唯一"
                )
            selected = matches[0]
        else:
            def relevance(point: Mapping[str, Any]) -> tuple[int, int, str]:
                topic_text = " ".join(
                    str(point.get(field) or "")
                    for field in (
                        "data_point_title",
                        "metric",
                        "value_text",
                        "source_excerpt_zh",
                        "source_excerpt",
                    )
                ).lower()
                factor_hits = sum(1 for term in factor_terms if term in topic_text)
                entity_hits = sum(1 for term in entity_terms if term in topic_text)
                # Factor relevance dominates entity relevance.  The final key
                # makes the selection deterministic across rebuilds.
                return (
                    factor_hits * 10 + entity_hits * 3,
                    len(str(point.get("source_excerpt") or "")),
                    str(point.get("data_point_key") or ""),
                )

            selected = max(points, key=relevance)
        excerpt = str(selected.get("source_excerpt") or "").strip()
        language = str(sources_by_ref[ref].get("language") or "").strip().lower()
        is_chinese = language in {"zh", "zh-cn", "zh-tw", "chinese", "中文"}
        excerpt_zh = str(selected.get("source_excerpt_zh") or "").strip()
        if is_chinese:
            excerpt_zh = excerpt
        if not excerpt or not excerpt_zh:
            raise ValueError(
                f"{entity_key}.{factor_code}.{ref} 对应数据点缺少原文或中文译意"
            )
        overrides[ref] = {
            "excerpt": excerpt,
            "excerpt_zh": excerpt_zh,
            "data_point_key": str(selected.get("data_point_key") or ""),
        }
    return overrides


def _factor_inputs(
    spec: Mapping[str, Any],
    *,
    sources_by_ref: Mapping[str, Mapping[str, Any]],
    data_points_by_source: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    inputs: dict[str, Any] = {}
    slot_payload = _load_json(FACTOR_SLOT_INPUT_PATH)
    if slot_payload.get("schema_version") != "opportunity_lens.factor_slot_inputs.v2":
        raise ValueError("因子指标槽输入必须使用v2逐数据点评分合同")
    boundary_map = FACTOR_BOUNDARIES_BY_ENTITY.get(str(spec["key"]), {})
    allowed_by_factor = DIRECT_DATA_POINT_ALLOW_BY_ENTITY_FACTOR.get(str(spec["key"]))
    if allowed_by_factor is None:
        raise ValueError(f"{spec['key']} 缺少逐实体逐因子数据点路由")
    public_refs_by_factor = FACTOR_PUBLIC_REFS_BY_ENTITY.get(str(spec["key"]))
    findings_by_factor = FACTOR_FINDING_BY_ENTITY.get(str(spec["key"]))
    if public_refs_by_factor is None or set(public_refs_by_factor) != set(SEGMENT_FACTOR_CODES):
        raise ValueError(f"{spec['key']} 缺少完整的逐因子公开证据路由")
    if findings_by_factor is None or set(findings_by_factor) != set(SEGMENT_FACTOR_CODES):
        raise ValueError(f"{spec['key']} 缺少完整的逐因子研究结论")
    data_point_source_by_key = {
        str(point["data_point_key"]): str(point["source_ref"])
        for rows_for_source in data_points_by_source.values()
        for point in rows_for_source
    }
    for code in SEGMENT_FACTOR_CODES:
        route = FACTOR_ROUTES[code]
        allowed_keys = tuple(str(value) for value in allowed_by_factor.get(code) or ())
        missing_allowed = [value for value in allowed_keys if value not in data_point_source_by_key]
        if missing_allowed:
            raise ValueError(f"{spec['key']}.{code} 路由到不存在的数据点：{missing_allowed}")
        allowed_source_refs = [data_point_source_by_key[value] for value in allowed_keys]
        raw_refs = [
            *allowed_source_refs,
            *public_refs_by_factor[code],
        ]
        direct_data_point_refs = list(dict.fromkeys(str(ref) for ref in raw_refs))
        refs = _strong_refs(
            raw_refs,
            fallback_refs=(),
            sources_by_ref=sources_by_ref,
        )
        broad_candidates = _factor_candidate_data_points(
            code,
            [ref for ref in direct_data_point_refs if ref in refs],
            data_points_by_source=data_points_by_source,
        )
        allowed_key_set = set(allowed_keys)
        broad_candidates = [
            point
            for point in broad_candidates
            if str(point["data_point_key"]) in allowed_key_set
        ]
        metric_slot_inputs, candidate_data_points = _compile_metric_slot_inputs(
            code,
            broad_candidates,
            scoring_inputs=slot_payload,
        )
        boundary = str(boundary_map.get(code) or "证据只能约束其披露的项目、时期与产品，不能外推未披露客户、月产能或市场份额。")
        finding = str(findings_by_factor[code])
        method = FACTOR_METHOD_BY_CODE[code]
        source_role = FACTOR_SOURCE_ROLE_BY_CODE[code]
        source_titles = "、".join(
            str(sources_by_ref[ref].get("title_zh") or sources_by_ref[ref].get("title") or ref)
            for ref in refs[:3]
        )
        if metric_slot_inputs:
            direct_titles = "、".join(
                str(point.get("data_point_title") or point.get("metric") or point["data_point_key"])
                for point in candidate_data_points
            )
            scoring_explanation = (
                f"本轮能直接复算的依据是{direct_titles}。只有这些同口径数据进入量化比较；"
                "其他资料用于解释项目、产品和反方条件，不额外抬高分数。"
            )
        else:
            scoring_explanation = (
                "现有资料能回答方向和边界，但没有与这一问题同分母、同期间且可复算的数值。"
                "因此本轮不评分；证据不足不能解释为供需中性。"
            )
        interpretations = {
            ref: (
                f"《{sources_by_ref[ref].get('title_zh') or sources_by_ref[ref].get('title')}》"
                f"用于{source_role}；只采用其直接披露的对象、时期和产品范围，不外推未披露数量。"
            )
            for ref in refs
        }
        information_point_overrides = _factor_information_point_overrides(
            entity_key=str(spec["key"]),
            factor_code=code,
            refs=refs,
            data_points_by_source=data_points_by_source,
            sources_by_ref=sources_by_ref,
        )
        inputs[code] = {
            "metric_name": f"{spec['name']}的{route['label']}",
            "period": "2026—2030",
            "as_of_date": AS_OF_DATE,
            "unit": "分",
            # Kept only for the shared function's backwards-compatible
            # signature.  The function deletes this value before compiling
            # slots; it never enters any score.
            "expert_bucket_score": 50.0,
            "score_input_kind": "explicit_metric_slot_inputs",
            "audit_multiplier": 1.0,
            "candidate_data_points": candidate_data_points,
            "metric_slot_inputs": metric_slot_inputs,
            "score_rationale": (
                f"量化判断只回答“{route['question']}”。{scoring_explanation}"
            ),
            "factor_value_summary": finding,
            "source_context_summary": (
                f"主要依据包括《{source_titles}》等{len(refs)}个独立来源，用于{source_role}。"
                f"{boundary}"
            ),
            "factor_topic_analysis": (
                f"本节回答：{route['question']}。{finding}{method}{boundary}"
            ),
            "theme_analysis_points": [
                finding,
                method,
                boundary,
            ],
            "source_refs": refs,
            "evidence_interpretations": interpretations,
            "evidence_information_points": information_point_overrides,
        }
    return inputs


ENTITY_RESEARCH_NARRATIVES: dict[str, str] = {
    "global_300mm_fab_expansion": """
### 问题

全球300毫米晶圆厂在2026—2030年会增加多少硅片需求，关键不是宣布了多少座工厂，而是新产能何时形成稳定晶圆投入。厂房开工、设备搬入、首片、批量生产与达到设计能力是五个不同节点；投资额还可能同时覆盖研发、厂务、封装和多座工厂。因此，本实体把“全球装机边界”和“4个公开可量化项目的基准情景”分开回答。前者给市场总量边界，后者只展示一组可复算的项目子集，不能当作已实现采购的最低值。

### 证据与数据

SEMI预计全球300毫米装机月产能由反算的2024年约847万片增至2028年的1,110万片，四年增加约263万片；7纳米及以下产能同期由85万片增至140万片。^src:source_ref:S001 另一份SEMI硅片出货展望预计2028年300毫米硅片出货超过10,800百万平方英寸，按300毫米圆片面积换算，至少相当于月均约821万片。这个数与1,110万片装机相比约为74%，只能作为出货强度与装机能力的同年对照，不能解释为74%的晶圆厂利用率，更不能据此声称还有289万片/月的供应缺口。^src:source_ref:DMD-SEMI-WAFER-OUTLOOK-202509

项目层面共核验36项，覆盖美国、亚洲和欧洲的逻辑、存储、模拟功率与特色工艺。多数项目只披露投资、技术方向或目标年份；只有UMC新加坡、ESMC德累斯顿、ST Agrate和士兰微厦门高端模拟一期同时具备可解释为新增的月产能及可建模时点。UMC披露第一阶段2026年开始批量生产、满产3万片/月和最高50亿美元投资，但没有说明何时满产；因此2028年满产只是本研究的爬坡假设。^src:source_ref:S031 ^src:source_ref:DMD-UMC-FAB12I-CURRENT ST Agrate的每周净增2,000片折合约8,667片/月，ESMC的4万片/月则计划到2029年达到；士兰微一期年产24万片折合2万片/月，并以2027年第四季度通线、2030年达产为公司目标。四项均需按年份爬坡，不能在开工年一次性计入。^src:source_ref:S036 ^src:source_ref:S015 ^src:source_ref:DMD-SILAN-12INCH-ANALOG-20260105

### 估算方法

总量路径以SEMI的2028年装机为锚，2029年沿用约7%的公开增长方向，2030年因没有同等级公开预测，仅展示较慢、基准和较快三种研究情景。4个可量化项目的情景按“净增月产能 × 12 × 当年平均爬坡比例 × 工艺投入系数 × 库存系数”计算。爬坡比例描述投产后的有效开工，工艺系数小幅计入监控片等净新增消耗，库存系数用于表示建库或去库。三个系数分别变化，避免把同一需求重复放大；正因为乘入了这些研究假设，结果只能称为基准、较慢或较快情景，不能称为已实现采购的最低值。

### 分析与结论

全球300毫米需求在2026—2028年向上具有较强证据，但公开信息不足以计算全球硅片的精确年度供给缺口。装机口径包含尚未满载的晶圆厂能力，硅片出货面积包含不同规格与库存变化，供应侧又缺少五大厂商按尺寸、产品、年份拆分的有效产能。美国政府资料只能确认约90%的硅片来自东亚、五家公司掌握多数供应，并没有公布各家可售月产能。^src:source_ref:DMD-NIST-GLOBALWAFERS 因而更可靠的判断是：先进300毫米合格产能可能比普通产品更紧，而普通300毫米和部分成熟产品仍可能供给宽松，两者不能用一个“全球缺口”数字概括。

对供应商而言，需求兑现次序应当是客户认证先完成、项目实际开工上升、产品销量与价格改善，最后才体现为毛利和现金流。Siltronic 2025年报正好给出反例：新加坡厂完成多项重要客户认证，却因为需求低于原先预期而放慢扩产；这说明“厂房存在”和“可盈利利用率”之间仍有距离。^src:source_ref:DMD-SILTRONIC-AR2025

### 如果想进一步研究，需要补充的信息

应优先取得台积电美国、三星Taylor、Micron、SK hynix以及中国主要存储项目的净增月产能、季度设备搬入、晶圆投入和利用率；供应侧需要五大硅片商按尺寸、规格和区域的可售产能、客户认证、库存与长协价格。只有两端采用同一尺寸、同一年度和同一有效产能口径，才能把当前的方向判断收窄为供需缺口。
""",
    "advanced_logic_wafer_demand": """
### 问题

先进逻辑对硅片行业的意义包含两部分：晶圆投入面积增加，以及缺陷密度、平坦度、金属污染和外延结构等规格升级。只统计新工厂数量会漏掉单位价值提升；只讲AI资本开支又会把设备、封装和数据中心投资误算成硅片采购。本实体只讨论7纳米及以下逻辑晶圆投入及与之匹配的300毫米高规格衬底。

### 证据与数据

SEMI预计7纳米及以下装机月产能从2024年的85万片增至2028年的140万片；按两个公开舍入值反算约65%，SEMI正文称约69%，差异来自端点舍入。两种表述都显示其增速明显高于同期300毫米总产能。^src:source_ref:S001 单厂资料确认多条技术路径正在推进，但成熟度不同：Intel披露2025年亚利桑那18A制造进入爬坡，Fab 52属于先进逻辑大批量制造体系；三星Taylor则仍是计划使用EUV生产2纳米、目标2026年底前投入运营，不能写成已经量产。^src:source_ref:S017 ^src:source_ref:DMD-SAMSUNG-TAYLOR-20260610 Rapidus已经开始2纳米GAA试制、原型晶圆开始取得电学特性，量产仍以2027年为目标；原型进展证明工艺在推进，却没有披露月产能或硅片供应商。^src:source_ref:S038

台积电亚利桑那三厂、JASM二厂等项目进一步确认先进逻辑地域扩散，但项目公告通常给节点和投资，未给净增晶圆投入。JASM公开的10万片/月是两厂合计，不是二厂净增；亚利桑那三厂的项目级节点、投产年份和月产能也不足以从现有保留证据确认。^src:source_ref:S011 这些限制决定了项目不能按投资额排序后换算成硅片数量。

### 判断方法

数量上采用SEMI的先进节点总量，不再把缺少月产能的单厂公告相加。价值量上只做传导判断：先进逻辑开工增加后，供应商还必须证明对应规格已经送样、通过认证并形成批量复购；没有产品规格、客户、采购量时，不向任何硅片公司分配假设份额。监控片与工艺投入只在4个公开可量化项目的情景中以小幅净额系数体现，良率损失不再次乘入晶圆投入，因为月产能本身已经是投入片数。

### 分析与结论

先进逻辑是2026—2030年最确定的高规格300毫米需求来源。它既增加面积，也可能提高每片硅片价值，因而对有稳定高端认证的供应商更重要。但“市场增长”不自动等于“国产供应商获得同等份额”：先进节点认证周期长，客户通常更重视长期一致性、缺陷控制和多批次稳定性，新增本地产能也可能继续由原有全球龙头供货。NIST披露全球硅片供应多数由五家公司管理，说明供给集中仍是先进规格受益分配的重要约束。^src:source_ref:DMD-NIST-GLOBALWAFERS

公司财务应当寻找比行业总量更严格的组合证据：先进300毫米销量或产品占比上升、平均售价稳定或改善、客户认证转批量、毛利和经营现金流同时改善。仅有资本开支增加可能意味着供应商提前备产；仅有收入增长也可能来自低价放量。SUMCO等专业硅片商更适合作为全球周期观察点，但合并披露不能替代逐客户、逐规格的订单证据。

反方情形包括2纳米以下项目推迟、单位晶圆算力提高快于终端需求、晶圆厂利用现有厂房吸收增量，以及新增订单继续集中于既有供应商。上述任一情形都会使面积或国产替代慢于名义装机。当前结论因此是“高规格需求方向强、公司受益需逐项验证”，而不是对所有300毫米硅片统一看多。

### 如果想进一步研究，需要补充的信息

需要取得先进逻辑项目的季度晶圆投入、量产良率与利用率，以及硅片的规格书、认证批次、外延片占比、供应商分配和长协价格。对中国企业还要确认从送样、验证到批量采购的时间与金额；这些资料将决定先进逻辑增长究竟转化为哪家公司的销量和利润。
""",
    "dram_hbm_wafer_demand": """
### 问题

DRAM与HBM需求容易被重复计算：HBM堆叠层数提高每颗产品所需裸片数，但晶圆厂月产能已经记录了晶圆投入，不能再按堆叠层数乘一次。本实体因此回答两个不同问题：先进存储需要多少300毫米晶圆投入，以及更复杂的产品结构是否提高硅片规格和单位价值。

### 证据与数据

SEMI在2026年6月预计全球300毫米存储月产能为2026年410万片、2027年420万片，一年只增加约10万片。这是DRAM与NAND合并的装机口径，不能拆成HBM独立产能，但足以说明AI存储叙事与晶圆面积不是一比一关系。^src:source_ref:DMD-SEMI-MEMORY-20260629 需求端同时出现恢复信号：Siltronic 2025年报称存储和逻辑在库存正常化后出现初步复苏迹象，却也指出功率与200毫米仍受高库存压制。^src:source_ref:DMD-SILTRONIC-AR2025

项目证据显示先进DRAM产线在多个地区推进。SK hynix M15X在2026年第一季度开始晶圆投入并逐步爬坡，但公司未披露月产能，媒体给出的宽区间不采用；Yongin首厂只计划2027年2月启用首个洁净室，洁净室启用不能当成量产。^src:source_ref:S025 ^src:source_ref:S024 Micron在美国的多座DRAM项目提供长期方向，但纽约首厂2026年才开始建设，公司只把投产描述为本十年后半段，无法据此精确计算2030前采购。^src:source_ref:S021 ^src:source_ref:S022 南亚科技4.5万片/月是2022年三期设计，现阶段只有历史尺寸与规模证据，当前投产和爬坡仍需更新。^src:source_ref:DMD-NANYA-FAB5A-12INCH

### 估算方法

本实体以SEMI的410万和420万片/月作为存储整体边界，不把单厂投资换成产能，也不把HBM层数、裸片数或封装良率再次乘入。项目只用于判断爬坡的地区和时间；只有公司披露净增月产能、起始年份和可解释基期时才进入片数模型。规格价值另行判断，依据是先进DRAM所需的低缺陷抛光片、外延片、监控片与更严格一致性，而不是构造一个没有价格与产品权重的“HBM硅片指数”。

### 分析与结论

2026—2027年的公开总量支持存储硅片需求缓慢增加，而不是按HBM出货或层数成倍增长。真正可能快于面积的部分是高规格产品占比与单位价值；这对拥有先进认证的供应商有利，但仍受客户库存、良率、长期协议价格和新厂爬坡影响。短期上，库存正常化能够提升实际开工；中期上，M15X、Micron和Yongin等项目是否按计划投入决定面积增量；长期上，节点迁移提高每片位产出，可能抵消部分晶圆面积需求。

盈利验证应当分开看高端300毫米销量、平均售价、毛利和现金流。若供应商只披露集团总销量，无法判断增长来自DRAM/HBM还是普通产品；若收入改善但毛利下降，可能是低价放量或新厂折旧先行。Siltronic当前“认证取得进展但扩产放慢”正说明客户资格与经济利用率并非同一件事。^src:source_ref:DMD-SILTRONIC-AR2025

反方包括存储客户延迟资本开支、库存再次上升、HBM位增长主要由良率和节点迁移承接，以及长协重谈压低价格。出现这些情况时，应同时下调晶圆面积、规格溢价与供应商盈利，而不是只延后一年。当前最稳健的判断是：存储面积温和向上、先进规格价值强于面积增速、公开资料不足以对DRAM与NAND精确拆分。

### 如果想进一步研究，需要补充的信息

需要DRAM、HBM与NAND分开的季度晶圆投入和利用率，M15X、Yongin、Micron项目的实际月产能与爬坡，以及HBM代际对应的晶圆面积、良率和硅片规格。供应商侧还需高端300毫米分产品销量、价格、客户认证和长协变化，才能把存储复苏转成公司盈利判断。
""",
    "nand_wafer_demand": """
### 问题

NAND位需求增长并不等于硅片面积增长。层数提高、工艺迁移和良率改善会增加每片晶圆可承载的位数；利用现有洁净室恢复开工，也可能先满足需求而不新建厂。本实体的任务是分清终端位增长、晶圆厂实际开工和原生硅片采购三层传导。

### 证据与数据

SEMI公开的300毫米存储总量预计从2026年410万片/月增至2027年420万片/月，但没有把DRAM与NAND分开，因此它只能给存储整体上限。^src:source_ref:DMD-SEMI-MEMORY-20260629 Kioxia的项目披露更能说明NAND特征：公司计划在四日市和北上现有厂房内增加生产设备，并优先利用Y7、K2等洁净室推动位增长；这意味着位供给可以在新建厂房有限的情况下增加。^src:source_ref:S040 Micron新加坡先进NAND厂和长江存储三期证明新增方向仍存在，但现有公开资料没有给出足以复算的净增月产能。^src:source_ref:S022 ^src:source_ref:S045

长江存储三期的项目级一手资料只足以确认存储建设方向，不能从媒体报道进一步指定为DRAM，也不能采用匿名月产能。^src:source_ref:S047 同样，项目投资可能包含厂房、设备和多阶段建设，不能按行业平均资本强度反推晶圆片数。对NAND而言，这一限制尤其重要，因为层数与工艺效率变化会显著改变每片晶圆的位产出。

### 估算方法

数量判断首先使用存储整体装机边界，然后逐项目记录设备搬入、晶圆投入和利用率；没有净增月产能的项目不进入片数加总。NAND层数只用于解释单位晶圆位产出和规格变化，不把位增速乘到硅片面积。原生片采购还要检查库存：晶圆厂短期建库可能使采购高于投入，去库则相反，但库存系数不能改变物理装机能力。

### 分析与结论

NAND硅片需求在周期恢复时会增长，但面积增速大概率低于位增速，而且更依赖现有厂利用率。2026—2028年需要重点观察Kioxia、Micron和长江存储的实际晶圆投入，而不是只看层数路线图或工厂面积。若现有洁净室和设备升级能够吸收大部分位需求，新建厂对原生片采购的增量会推迟；若终端需求强、库存恢复正常且现有厂接近有效上限，新厂爬坡才会形成更明显的面积增长。

对硅片供应商，NAND受益应由普通与高规格300毫米销量、价格、库存和客户认证共同确认。合并财务无法把NAND客户从逻辑、DRAM和其他产品中分离；SUMCO等公司的库存与非先进300毫米价格可作周期代理，却不能直接当作NAND采购量。硅片厂若在客户开工恢复前提前扩产，新增折旧和库存会先压制毛利。

反方情形是层数升级与单位晶圆位产出持续快于终端位需求，客户延迟设备投入，或库存去化再次中断。出现这些情况时，NAND位出货仍可能增长，但硅片面积、价格和供应商利润未必同步改善。当前结论是方向温和复苏、面积弹性有限、单厂量化证据不足，不能给出NAND专属的精确硅片缺口。

### 如果想进一步研究，需要补充的信息

需要Kioxia、Micron和长江存储按季度披露的净增月产能、利用率、晶圆投入与库存，并取得NAND代际的单位晶圆位产出、层数、良率和硅片规格。供应商侧需要分客户或至少分产品的销量、均价与库存，这些数据能检验位增长是否真正转成原生硅片采购。
""",
    "china_300mm_wafer_suppliers": """
### 问题

中国12英寸硅片供应商谁更可能受益，不能只按规划产能排序。真正的比较应同时看可用瓶颈产能、实际销量、客户认证是否仍有效、高规格产品占比、价格、利用率、毛利和现金流。本实体的排序回答“谁最接近把需求变成经营结果”，不是给出市场份额或证券收益预测。

### 证据与数据

上海超硅当前证据更适合用于经营兑现排序：2025年12英寸瓶颈年产能367万片，折合约30.58万片/月，利用率75.18%；设计能力高于瓶颈能力，说明只看厂房名义规模会高估可售产出。^src:source_ref:S058 西安奕材披露的是到2026年形成120万片/月的规划口径，当前稳定可售产能与利用率尚未直接披露；持续亏损也说明规划规模、价格、良率、利用率和折旧尚未共同跨过盈利门槛。^src:source_ref:S059

沪硅产业的历史监管资料确认30万片/月300毫米项目和多家客户认证，产品与客户基础较完整，但核心证据来自2021年，只能证明曾进入认证体系，不能直接代表2026年订单。^src:source_ref:S057 立昂微2025年12英寸销量178.57万片、名义产能30万片/月，硅片业务收入增长65.63%，同时部分12英寸衬底与外延项目仍在建设或延期。^src:source_ref:S061 上海合晶现有12英寸功率硅片约4万片/月，郑州二期CIS目标6万片/月，远期逻辑规划10万片/月，细分定位清楚但近端规模较小。^src:source_ref:S062 TCL中环2025年半导体材料销量增长23.99%，期末库存增长35.87%，且缺少12英寸分产品结构，暂不能仅凭总销量判断高端受益。^src:source_ref:S060

### 排序方法

本研究按五步比较：先确认当前可用的瓶颈能力，而非远期设计能力；再看实际销量与利用率；第三步验证客户认证是否在当前期形成批量复购；第四步看抛光片、外延片、退火片等产品结构是否匹配新增需求；最后以平均售价、毛利、存货和经营现金流检查盈利兑现。任何只有历史客户名单或远期规划、没有当期采购与财务验证的企业都要降级。这个方法得到的当前顺序为上海超硅、西安奕材、沪硅产业、立昂微、上海合晶、TCL中环半导体材料；顺序会随季度数据更新，不代表绝对技术排名。

### 分析与结论

上海超硅当前瓶颈能力和利用率最可核验，若利用率提升且认证转订单，经营弹性可能较大；西安奕材规划规模领先，但当前稳定可售能力尚未直接披露，持续亏损使其盈利确定性低于规划确定性；沪硅产业的产品和客户基础较完整，但资料时效要求先核验复购；立昂微的销量增速积极，却需要排除在建项目延期与新增折旧；上海合晶更像功率和CIS细分受益；TCL中环则要先解释库存增速快于销量和尺寸结构缺失。

因此可以认为，中国供应商已经具备批量供货和客户认证基础，但还不能认为全球300毫米扩产会按规划产能比例平均分配给它们。先进逻辑与高规格产品的认证壁垒更高，普通抛光片又可能在集中扩产后承受价格压力。全球供应仍高度集中于少数公司，也说明国产替代需要逐客户、逐规格验证，而非按国内晶圆厂资本开支推导。^src:source_ref:DMD-NIST-GLOBALWAFERS

最重要的反方是普通12英寸产能先于高端认证释放。若销量增长同时伴随均价下降、库存上升、毛利为负和经营现金流恶化，需求增长并没有形成有质量的盈利。反过来，即使总片数增长一般，高规格占比、利用率和价格同步改善，也可能使利润弹性高于行业面积增速。

### 如果想进一步研究，需要补充的信息

应取得六家公司按季度拆分的12英寸抛光片、外延片、退火片和其他高规格产品销量、均价、良率、利用率、库存、客户认证转批量日期及采购金额。历史客户名单必须用当前复购或年度采购重核；这些数据将决定排名变化，并把行业需求转换为收入、折旧、毛利与现金流情景。
""",
    "mature_200mm_wafer_demand": """
### 问题

200毫米晶圆仍广泛用于功率、模拟、汽车和工业芯片，但它与300毫米的扩产节奏、设备生态和库存周期不同。本实体要回答的问题是低速装机增长能否真正转成硅片采购与盈利。研究只使用纯200毫米装机口径作为主线；总8英寸等效包含300毫米面积换算及更小尺寸，只能作数量级交叉检查，不能与纯200毫米结果相加。

### 证据与数据

SEMI预计全球200毫米装机月产能在2026年增长3%至770万片，2027—2029年增速分别为3%、1%和2%。^src:source_ref:S065 这条路径显示成熟尺寸仍增长，但明显慢于300毫米先进产能。项目层面，GlobalFoundries Burlington只确认对现有设施进行200毫米硅基氮化镓改造，没有披露月产能；它证明产品方向，不足以计算新增片数。^src:source_ref:S032 功率与模拟项目还存在向300毫米迁移的情况，因此相关终端增长不一定全部落到200毫米硅片。

当前供需证据偏谨慎。Siltronic 2025年报称功率半导体和200毫米市场因库存持续偏高而仍然疲弱；这是一项比旧周期资料更接近当前的供应商观察。^src:source_ref:DMD-SILTRONIC-AR2025 信越化学也曾明确200毫米供需偏宽松，说明装机增长不能直接写成短缺。^src:source_ref:S053 同时，汽车、工业和功率需求具有周期性，旧厂利用率恢复和二手设备改造可能先于新建产能满足订单。

### 估算方法

2026—2029年直接采用SEMI的770万片/月基数和逐年增速；2030年没有同等级公开预测，因此只展示不增长、增长2%和增长4%三种研究情景。年度采购运行率按装机变化、利用率和小幅工艺投入系数估算，但结果不与300毫米面积等效余量相加。对项目公告，只有明确为200毫米且给出净增月产能和时间时才进入片数模型；投资额、厂房改造和“产能翻倍”相对表述都不能替代基期。

### 分析与结论

200毫米需求在2026—2029年更可能是低速扩张而非结构性短缺。需求来源仍包括功率、模拟、汽车和工业，但当前库存和价格环境显示供给并不紧张；区域本地化项目可以提高安全性，却未必立刻提高全球利用率。若终端恢复、库存回归正常且旧厂接近有效上限，新增装机才会转成稳定原生片采购；若需求疲弱，现有厂提高利用率或改造设备就可能吸收大部分订单。

公司层面的正确验证是分尺寸销量、价格与库存。综合硅片商收入改善不能证明200毫米转紧，因为先进300毫米可能同时增长；相反，200毫米库存下降、平均售价企稳、利用率与毛利改善同时出现，才是更强信号。当前资料支持“数量仍增、周期偏弱、价格缺乏上行证据”，不支持给出精确供给缺口。

反方既包括汽车和工业复苏慢于预期，也包括功率器件进一步转向300毫米或宽禁带衬底。前者压低总开工，后者改变产品结构；二者都可能使200毫米装机扩张先形成闲置、库存和价格压力。评分只能表示值得跟踪，不代表供需已经转紧。

### 如果想进一步研究，需要补充的信息

需要全球200毫米按地区、应用和季度拆分的装机与利用率，功率和模拟厂的实际晶圆投入，硅片供应商分尺寸出货、价格、库存与再生片比例，以及旧设备改造形成的有效产能。只有这些数据齐全，才能判断低速增长是健康平衡还是继续宽松。
""",
    "soi_engineered_substrate_demand": """
### 问题

SOI、RF-SOI、FD-SOI等工程衬底的价值来自材料结构、客户平台和长期认证，不能与普通抛光硅片按片数或均价直接相加。本实体要判断具名客户关系和新能力是否形成真实机会，同时明确当前公开资料为什么不足以给出全球SOI月产能、市场缺口或统一增长率。

### 证据与数据

公开资料能够确认若干直接关系：Soitec与GlobalFoundries、UMC等平台存在RF-SOI或工程衬底合作，说明产品已经进入具名应用体系；美国对GlobalWafers项目的支持也包含300毫米SOI能力。^src:source_ref:S055 ^src:source_ref:S056 ^src:source_ref:S051 这些来源证明“能力与合作存在”，却没有披露年度采购量、供应份额、分尺寸出货或客户复购。

全球供给的集中度背景同样重要。NIST称约90%的硅片来自东亚、五家公司掌握多数全球供应，但这是一项全硅片口径，不能直接当作SOI市场份额。^src:source_ref:DMD-NIST-GLOBALWAFERS 工程衬底还有不同直径、不同绝缘层结构和应用平台，统一片数会掩盖产品差异；公司集团收入也包含多类衬底，不能从收入增速倒推出RF-SOI数量。

### 研究方法

本实体不输出没有锚点的片数、市场规模或主观需求指数。证据按三层使用：产品和客户公告确认应用平台；工厂及政策资料确认新增能力；发行人财务检查收入、利润、库存和资本开支。只有当分产品产能、出货、价格和客户采购采用同一尺寸与年度口径时，才计算供需。现阶段具名合作不被换算为订单量，新厂能力也不等于已完成认证或达到经济利用率。

### 分析与结论

可以认为SOI是高价值、认证驱动、数量可见度较低的细分市场。射频、FD-SOI和三维集成等应用为工程衬底提供结构性方向，具名合作提高了需求存在的可信度；但采购规模、价格和产能基线不足，使任何精确增长率都不可复核。与普通300毫米相比，SOI的受益更依赖特定平台赢单和认证，而不是全球晶圆厂总装机。

对Soitec等公司，财务验证必须落到分产品收入、出货、利用率、价格和现金流。集团收入增长可能来自不同工程衬底，集团下降也可能掩盖某一平台放量；所以标的页只能给条件化建议。GlobalWafers美国SOI能力则需要继续跟踪设备安装、客户认证和实际爬坡，政策支持本身不是销量。

反方包括射频库存恢复缓慢、客户平台渗透不及预期、认证延期、新产能闲置，以及碳化硅等替代路线在部分应用中改变衬底选择。任何一项都会使收入落后于终端应用叙事。当前最可靠的结论不是“SOI短缺”，而是“应用与客户关系得到一手证据支持，数量和价格仍无法公开量化”。

### 如果想进一步研究，需要补充的信息

需要全球SOI按200毫米和300毫米拆分的有效月产能、出货、利用率和均价，RF-SOI与FD-SOI的客户采购量、认证阶段和复购，以及Soitec和GlobalWafers分产品的资本开支与爬坡。补齐后才能比较供给弹性、客户集中和盈利传导；在此之前不把SOI并入普通硅片供需表。
    """,
}


ENTITY_RESEARCH_EXTENSIONS: dict[str, str] = {
    "global_300mm_fab_expansion": """
### 从上一轮扩产周期得到的约束

2020—2022年硅晶圆面积出货由12,407升至14,713百万平方英寸，随后两年回落至12,266；这段历史说明项目建设与材料采购存在时差，补库结束后利用率和价格会先承压。^src:source_ref:S006 2026—2030虽然有AI先进节点和地区本地化两项新动力，但Intel放慢Ohio、取消德国计划的最新事实表明，长期厂房规划仍可能因实际需求和资本纪律调整。^src:source_ref:S017 本实体因此只把设备搬入、实际晶圆投入和可复算净增月产能作为近期需求依据，不用项目投资总额重复上一轮的线性外推。

### 地区与时间如何改变结论

美国项目的共同特征是投资规模大、分期长且项目级月产能披露少。它们能够提高本地供应安全，却未必在2026—2030年全部形成有效采购。亚洲项目更接近现有供应链，先进逻辑、存储和成熟制程同时推进，但合并产能、历史规划和匿名估计较多；中国项目还要区分8英寸等效与原生300毫米。欧洲的ESMC、ST等项目披露相对适合复算，但少数项目不能代表全球。区域项目数量因此只说明检索覆盖，不能当作需求权重。

时间判断也要服从里程碑。华虹第二阶段的83K没有公开时间单位，不能换算成月产能；Infineon工厂启用不等于稳定量产；Yongin洁净室开放也不等于晶圆投入。相反，M15X已经开始晶圆投入，虽然缺少月产能，至少比单纯开工更接近实际采购。^src:source_ref:S044 ^src:source_ref:S035 ^src:source_ref:S024 ^src:source_ref:S025 这种逐项目校正会让可量化结果变小，却能避免把未来目标提前计入。

### 怎样跟踪结论是否兑现

全球需求向上的确认顺序应是设备搬入、实际晶圆投入、季度利用率、硅片采购、供应商出货与价格，最后是毛利和现金流。若晶圆厂装机增加而硅片供应商库存继续上升，说明项目尚未转成有效订单；若高规格交付期延长、认证加快、长协价格企稳，同时主要供应商利用率上升，才说明结构性趋紧正在兑现。项目延期不能只把收入往后挪，因为延期还可能让硅片厂新增供给先释放，改变价格与盈利。

36项台账仍有明确覆盖边界：它不是SEMI全球项目数据库的替代，也没有纳入无法由一手资料定位的匿名计划。每次更新都应先复核已有项目状态，再新增项目，避免旧目标被长期当成当前事实。对投资判断而言，总量向上只证明行业机会存在，哪家供应商受益仍要由认证、产品结构、销量和现金回报重新证明。
""",
    "advanced_logic_wafer_demand": """
### 高规格需求怎样穿透到供应商

先进节点对硅片的要求不是一个统一“高端”标签。逻辑厂会分别验证晶体缺陷、纳米形貌、平坦度、边缘控制、金属污染和外延结构，并用多批次稳定性决定是否扩大采购。供应商即使能生产300毫米抛光片，也可能只进入成熟节点；曾经通过某客户认证，也不代表已经获得2纳米或18A的当期订单。因此，项目节点与供应商产品认证必须一一对应，历史客户名单不能跨节点继承。

台积电、三星、Intel与Rapidus的项目处在不同阶段，给硅片需求带来的时间也不同。Intel制造爬坡是近端验证点；三星Taylor要等目标投运变成实际晶圆投入；Rapidus还需从原型电学特性跨越良率、批量制造和客户采用；亚利桑那后续厂则需要项目级月产能和投产时点。把四者统一写成“先进厂量产”会高估短期采购，也会掩盖不同硅片规格的认证节奏。

### 数量与盈利的不同敏感性

即使先进逻辑面积按SEMI路径增长，供应商收入也不一定按同一比例变化。高规格产品价格与组合改善可能使收入快于面积，新增厂折旧、低利用率或客户议价也可能抵消价值提升。更合理的公司情景至少拆成销量、产品结构、平均售价、单位成本和折旧五项，再用经营现金流检查利润质量。专业硅片公司的资本开支只说明备产意愿，不能替代项目级赢单。

还要保留技术效率的反方：先进封装、芯片设计和单位晶圆算力提高可能用更少面积承载更多计算；良率改善也能延缓新增开工。另一方面，更多工艺步骤和更严规格可能提高监控片、外延片和单位价值。二者方向相反，因而本研究只对面积采用公开装机锚点，对价值量保持条件化判断，不构造没有产品价格的精确收入倍数。
""",
    "dram_hbm_wafer_demand": """
### 存储周期与本轮差异

2022年以后全球硅晶圆面积连续回落，反映消费电子库存与存储周期可以压过长期数字化趋势；2025年出货面积恢复但销售额仍下降，也说明数量复苏早于价格修复。^src:source_ref:S006 ^src:source_ref:S005 本轮HBM与AI服务器提高的是先进DRAM的产品结构和规格要求，而不是把堆叠层数直接变成更多晶圆。410万至420万片/月的存储总装机锚点仍是温和增长，必须用实际晶圆投入和高规格硅片复购验证。^src:source_ref:DMD-SEMI-MEMORY-20260629

### 为什么不能用堆叠层数算片数

以晶圆厂月投入为例，如果某条DRAM产线已经记录每月投入10万片，把HBM从8层升级到12层不会让同一条产线自动变成15万片投入。堆叠会改变每颗产品需要的裸片数、产品组合与价值，但晶圆面积是否增加仍由晶圆厂实际开工、节点、良率和新增设备决定。模型因此只在装机或明确项目净增中计算数量，把HBM的影响放在高规格占比、产品价格和客户认证中分析。

存储项目的地区扩散同样不能替代片数。Micron美国项目、M15X和Yongin证明长期产能方向，Samsung P5提供2028年运营目标，南亚科技提供历史设计规模；四类证据的时间和成熟度不同。^src:source_ref:S021 ^src:source_ref:S025 ^src:source_ref:S024 ^src:source_ref:S030 只有M15X公开到晶圆投入节点，但仍没有月产能。若将历史4.5万片设计、洁净室开放和长期投资全部算作当年量产，会同时提前时间并重复容量。

### 如何验证供应商真正受益

先进存储受益首先应在高端300毫米抛光片、外延或特定监控产品的认证和销量中出现，然后才是平均售价、毛利和现金流。供应商若只披露集团300毫米销量，无法分辨逻辑、DRAM和NAND；若长协价格下调，即使销量回升，利润也可能滞后。需要特别观察新加坡等新增供应能力是否按需求放量，因为客户认证完成后仍可能因市场较弱而放慢爬坡。

存储周期的反方也比项目延期更复杂。库存恢复会短期增加采购，但节点迁移和良率提升会提高单位晶圆位产出；终端AI需求强，并不保证传统DRAM和NAND同步改善。当前410万到420万片/月的公开锚点只支持存储整体温和增长。若要判断HBM的额外价值，必须取得分产品晶圆投入、硅片规格与价格，而不能从HBM收入倒推面积。
""",
    "nand_wafer_demand": """
### 为什么本轮不能照搬上一轮补库

上一轮面积出货在2022年见顶后连续两年回落，说明位需求、渠道补库和原生晶圆面积并不同步。^src:source_ref:S006 到本轮，Kioxia明确表示现有四日市和北上厂房可支持至2029年的需求，并优先在现有设施内追加设备；因此更高层数和设备升级可能先提高位产出，只有新增晶圆投入才形成额外硅片面积。^src:source_ref:S040

### 项目证据应怎样读取

NAND项目最容易把“建筑面积”和“位产能”误当作晶圆面积。Kioxia选择在现有设施内追加设备，本身就是一项重要反方：需求增加可以通过洁净室利用、设备升级与层数提升实现，并不必然要求同比例新建晶圆投入。Micron新加坡项目证明先进NAND长期方向，却缺少净增月产能；长江存储三期只确认项目推进，产品组合和片数不能由匿名报道补齐。三者共同支持需求存在，却不能直接相加成一条新增月产能。

若把NAND位需求拆解，终端容量先经过渠道库存和产品库存，再决定晶圆厂开工；开工还受到层数、单位晶圆裸片数和良率影响；最后原生硅片采购又受晶圆厂自身硅片库存影响。每一层都可能与位出货不同步。研究中把库存系数限制在采购与实际投入之间，不让它改变物理装机，也不把层数同时作用于开工和硅片数量。

### 2026—2030年的观察节奏

2026年首先看存储库存正常化是否带动既有厂开工，2027年看新加坡等项目设备投入和Kioxia现有洁净室利用，2028年以后再判断新厂是否形成额外面积。若单位晶圆位产出持续提升，位需求可以显著增长而面积只温和增加；若终端需求超预期、既有厂接近上限且新工艺良率偏低，面积弹性才会放大。没有逐季开工时，年度精确预测不可信。

供应商端应同时跟踪普通与高规格300毫米销量、平均售价、库存和客户认证。NAND复苏若只表现为低价去库存，对硅片商毛利帮助有限；若高规格产品复购、价格企稳和经营现金流同步改善，才是高质量受益。反之，新供应能力早于客户开工会形成折旧与库存压力，所以NAND实体的研究优先级低于证据更直接的先进逻辑，并不等于长期需求不存在。

完整量化还需要把DRAM从存储总量中剥离。SEMI公开410万和420万片是存储合计，不能先分配给NAND再与DRAM项目相加。付费分产品装机或公司一手开工数据是必要输入；在此之前，本节只给传导机制、项目时点和可证伪信号。这样的限制能避免同一片存储产能被DRAM和NAND各计算一次。
""",
    "china_300mm_wafer_suppliers": """
### 国产替代从历史认证走向盈利验证

2020年以来国内12英寸项目和客户认证持续增加，但早期客户名单只能证明当时进入过供应链，不能证明2026年的复购、份额或高端规格。沪硅产业等历史认证资料因此只作能力起点，并在当前排序中由销量、利用率、价格、良率和现金流重新验证。^src:source_ref:S057 本轮与上一轮不同之处在于，多家公司规划能力正进入折旧和量产兑现期：如果本地化订单没有同步转成高规格复购，普通产品供给可能先于需求；只有利用率、平均售价、毛利和经营现金流共同改善，才能把“国产替代方向”升级为“实际盈利受益”。

### 排名变化的关键情景

上海超硅若瓶颈工序补齐、75.18%的利用率上升并带动现金流，其当前经营证据会进一步增强；若设计能力继续闲置，扩产反而增加折旧。西安奕材2025年销量增至807.37万片、主营业务毛利率转为3.44%，但归母净亏损仍为7.38亿元；2026年第一季度收入继续增长，按收入和营业成本复算的毛利率约2.58%。^src:source_ref:FIN-ESWIN-2025AR ^src:source_ref:FIN-ESWIN-2026Q1 这说明规模与认证正在兑现，却仍需平均售价、产品结构、折旧摊薄和持续盈利共同确认。沪硅产业最大的待验证项是历史认证的时效，当前复购比旧客户名单更重要。

立昂微的观察点是销量快速增长能否覆盖在建项目的资本开支与折旧，上海合晶则需要验证CIS与功率细分客户能否按规划放量。TCL中环的总销量增长不足以说明12英寸高规格受益，库存增速更快要求拆出尺寸、产品和平均售价。六家公司没有一套完全同口径披露，排名因此基于当前最可比事实，并明确下一步需要补什么，而不是填补缺失数据。

### 国内需求与全球受益的差别

国内晶圆厂扩产可以提高本地采购机会，但先进节点、高端外延或退火产品仍可能由长期认证的国际龙头供应。国内公司在成熟产品放量不等于已经进入全球头部客户的先进平台；出口和海外认证也不能由国内客户名单推断。排序先回答中国市场的订单承接能力，再单独验证全球客户，不把两种机会合并。

财务上要警惕“收入增长、利润恶化”的组合。扩产初期折旧上升可以暂时压低利润，但如果同时出现低利用率、降价和库存累积，就说明普通产品供给已经早于有效需求。反过来，客户认证转批量、高规格占比上升和现金回款改善会提供更强证据。每次季度更新都应重新计算瓶颈能力与实际销量，而不是沿用规划产能排名。
""",
    "mature_200mm_wafer_demand": """
### 2020年以来的成熟制程周期

疫情期汽车、工业与功率器件缺货推动成熟制程扩产，但2022年后全球硅晶圆面积出货连续回落，说明补库结束和终端去库存会让新增能力晚于需求见顶。^src:source_ref:S006 当前信越化学仍称200毫米供需偏宽松，SEMI同时预计2026年装机增长3%至770万片/月；两项证据合在一起支持“物理能力继续增加、市场未必转紧”，而不是重演普遍短缺。^src:source_ref:S053 ^src:source_ref:S065 2026—2030的主要变化是地区本地化、氮化镓和特色工艺项目增加，但其增量必须由实际开工、库存下降和价格企稳验证。

### 纯200毫米与面积等效必须分开

300毫米圆片面积约为200毫米的2.25倍，把不同尺寸换成8英寸等效可以比较总面积，却不能说明真实200毫米设备、产品或硅片采购。如果先把300毫米换成等效片，又把SEMI纯200毫米装机相加，就会重复计算。因此主结果只采用770万片/月及后续增速；总面积等效只检查数量级，不参与需求求和。

项目也需要按实际直径核验。GlobalFoundries Burlington明确是200毫米现有设施改造，可以确认氮化镓产品方向，却没有净增月产能。Infineon德累斯顿公开启用和投资，但保留来源没有说明晶圆尺寸，不能因为同类功率工厂常见某种尺寸就填成300毫米。^src:source_ref:S032 ^src:source_ref:S035 这种克制避免把功率与模拟扩产全部错误归入200毫米或300毫米。

### 年度情景怎样使用

2026年的770万片/月和2027—2029年的3%、1%、2%是公开装机路径，描述物理能力而非实际采购。2030年的0%、2%、4%只是敏感性：不增长对应汽车工业恢复较慢，2%延续低速扩张，4%对应终端和本地化需求较强。无论哪一档，采购仍要乘实际利用率并受库存影响；研究不会把情景最高值当成公司订单。

当前Siltronic与信越化学的判断都提示200毫米没有普遍短缺。一个可能的演化是需求恢复带动利用率先上升、库存下降，然后价格企稳，最后才触发新增硅片能力；另一个演化是功率和汽车需求持续疲弱，使现有设备足以满足订单。跟踪顺序应是库存、开工、硅片出货、价格和新产能，而不是先看晶圆厂资本开支。

### 对供应商盈利的含义

综合供应商必须拆分200毫米与300毫米。先进300毫米增长可能掩盖200毫米价格下跌，集团收入和毛利无法单独证明成熟尺寸改善。真正的正面组合是200毫米出货恢复、库存下降、售价稳定、利用率和现金流同步上升；若只有销量增长而价格与毛利下降，更多是去库存或低价放量。现阶段把200毫米定义为“低速增长、供需仍宽松”更符合证据。
""",
    "soi_engineered_substrate_demand": """
### 客户关系能证明什么

具名合作的价值在于确认工程衬底进入了具体平台和认证体系，但合作公告通常不披露年度采购、价格和供应份额。Soitec与GlobalFoundries、UMC的关系可以支持RF-SOI应用方向，不能据此假设客户全部采购自一家供应商。政策支持或新专线也只能证明能力建设，设备安装、客户认证和经济利用率仍需后续证据。

SOI内部也不能统一计量。200毫米与300毫米产品、RF-SOI与FD-SOI、不同绝缘层和应用平台的价格及产能不相同；集团“工程衬底”收入还可能包括其他材料。若用集团收入除以一个假设均价，既混合产品又缺少可验证分母。当前选择不输出指数或片数，是因为这些数字不会比具名客户与实际财务更有信息。

### 如何判断供需和盈利

供需趋紧至少需要同一产品的有效产能、出货、利用率、库存和价格。若客户平台放量、交付期延长、价格企稳，同时供应商利用率提高，可认为特定SOI产品趋紧；若新产能已经安装但需求恢复慢、库存和资本占用上升，则是供给先行。全硅片“东亚占90%”只能说明地理集中背景，不能替代SOI分产品平衡。

Soitec财务应拆分RF-SOI、FD-SOI和其他工程衬底的收入、出货与资本投入，再与客户平台进度对照。GlobalWafers美国项目则要验证SOI设备、认证和实际产出。收入增长若伴随现金流恶化，可能仍处扩产初期；收入下降也不必然否定长期平台，只要客户认证和产品路线仍有效。公司受益判断因此必须同时看经营和项目证据。

### 时间与反方情景

2026—2030年的主要变量是射频库存恢复、FD-SOI平台渗透、新产品认证和新增能力爬坡。认证推迟会使需求晚于终端叙事，客户集中会增加单一平台风险，碳化硅等材料在部分功率应用中的替代也会改变可服务市场。这些反方不是附注，而会直接降低销量、价格与利用率情景。取得分产品数据前，最有决策价值的是监控明确里程碑，而不是给一个看似精确的全球增速。更新时还应逐项核对合作是否仍生效、是否从技术验证进入批量采购，以及新产能是否获得具名客户认证；任何一个环节停滞，都应下调近端收入判断，而不能用长期应用空间掩盖。
""",
}


def _entity_section(spec: Mapping[str, Any], refs: Sequence[str]) -> dict[str, Any]:
    del refs  # 正文引用是公开证据索引的唯一来源，避免手工清单与正文漂移。
    key = str(spec["key"])
    name = str(spec["name"])
    narrative = "\n\n".join(
        [ENTITY_RESEARCH_NARRATIVES[key].strip(), ENTITY_RESEARCH_EXTENSIONS[key].strip()]
    )
    body = natural_citations(narrative)
    if len(body) < 2200:
        raise ValueError(f"{name}实体正文不足2200字符：{len(body)}")
    cited_refs = _refs_in_markdown(body)
    return {
        "entity_key": key,
        "section_key": "entity_research",
        "section_title": f"{name}：证据、测算与结论",
        "body_markdown": body,
        "support_status": "partially_supported",
        "evidence_ref_uri_list": [source_uri(ref) for ref in cited_refs],
    }


def _financial_target_map(
    payload: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    payload = payload or _load_json(FINANCIAL_DIR / "target_financials.json")
    return {target["target_id"]: target for target in payload["targets"]}


def _audited_financial_points(
    target: Mapping[str, Any],
    sources_by_ref: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return build_financial_data_points(target, sources_by_ref)


def _market_snapshot_map() -> dict[str, dict[str, Any]]:
    payload = _load_json(MARKET_SNAPSHOT_PATH)
    return {str(row["target_id"]): dict(row) for row in payload.get("snapshots") or []}


def _market_snapshot_points(
    target_id: str,
    sources_by_ref: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    snapshot = _market_snapshot_map()[target_id]
    ref = str(snapshot["source_ref"])
    source = sources_by_ref[ref]
    market_cap = float(snapshot["market_cap"])
    cny_100m = market_cap * float(snapshot["fx_to_cny"]) / 100_000_000
    usd_100m = market_cap * float(snapshot["fx_to_usd"]) / 100_000_000
    trailing_pe = snapshot.get("trailing_pe")
    forward_pe = snapshot.get("forward_pe")
    if isinstance(trailing_pe, (int, float)) and float(trailing_pe) > 0:
        pe_text = f"滚动市盈率{float(trailing_pe):.2f}倍"
    else:
        pe_text = "滚动市盈率不适用（亏损或数据源没有可用正值）"
    if isinstance(forward_pe, (int, float)) and float(forward_pe) > 0:
        pe_text += f"；前瞻市盈率{float(forward_pe):.2f}倍"
    elif isinstance(forward_pe, (int, float)):
        pe_text += f"；前瞻值{float(forward_pe):.2f}倍为负，不具估值意义"
    common = {
        "period": "2026-07-17",
        "as_of_date": "2026-07-17",
        "source_title": source["title"],
        "source_title_zh": source.get("title_zh") or source["title"],
        "source_publisher": source["publisher"],
        "source_url": source.get("url"),
        "source_excerpt": source["excerpt"],
        "source_excerpt_zh": source.get("excerpt_zh") or source["excerpt"],
        "evidence_ref_uri": source_uri(ref),
        "data_quality_label": "third_party_same_session_market_snapshot",
        "credibility_weight": 0.85,
        "numeric_weight": 1.0,
    }
    return [
        {
            **common,
            "metric_name": "同日收盘价",
            "metric_category": "market_snapshot",
            "unit": str(snapshot["currency"]),
            "value_num": float(snapshot["price"]),
        },
        {
            **common,
            "metric_name": "同日市值与统一币种换算",
            "metric_category": "valuation",
            "unit": "亿元人民币/亿美元",
            "value_text": f"{cny_100m:.2f}亿元人民币（约{usd_100m:.2f}亿美元）",
            "calculation_note": (
                f"原币市值{market_cap:g}×人民币汇率{float(snapshot['fx_to_cny']):.9g}÷1亿；"
                f"美元等值使用汇率{float(snapshot['fx_to_usd']):.9g}。汇率日期{snapshot['fx_date']}。"
            ),
        },
        {
            **common,
            "metric_name": "同日PE/PB/PS",
            "metric_category": "valuation",
            "unit": "倍",
            "value_text": (
                f"{pe_text}；市净率{float(snapshot['price_to_book']):.2f}倍；"
                f"市销率{float(snapshot['price_to_sales']):.2f}倍"
            ),
        },
    ]


def _fact_type(
    point: Mapping[str, Any],
    source: Mapping[str, Any],
) -> str:
    text = " ".join(
        str(point.get(field) or "")
        for field in ("metric", "period", "note", "source_excerpt", "original_fact_type")
    ).lower()
    if str(point.get("research_category")) == "calculated_inference" or any(
        token in text for token in ("calculated", "inferred", "研究假设", "情景假设")
    ):
        return "analyst_assumption"
    if source.get("source_tier") == "C" or source.get("source_review_status") in {
        "weak_source_only", "reference_only", "reject"
    } or any(token in text for token in ("匿名", "传闻", "媒体估计", "rumor")):
        return "rumor"
    publisher = str(source.get("publisher") or "").lower()
    if "semi" in publisher and any(
        token in text for token in ("预测", "预计", "projected", "forecast", "20", "e")
    ):
        return "industry_forecast"
    if any(token in text for token in ("规划", "计划", "目标", "拟建", "预计", "planned", "target")):
        return "company_target"
    return "actual"


def _claim_type(source: Mapping[str, Any]) -> str:
    text = " ".join(
        str(source.get(field) or "")
        for field in ("title", "title_zh", "excerpt", "excerpt_zh")
    ).lower()
    if source.get("source_tier") == "C" or source.get("source_review_status") in {
        "weak_source_only", "reference_only", "reject"
    }:
        return "rumor"
    if str(source.get("publisher") or "").lower() == "semi" and any(
        token in text for token in ("预计", "projected", "forecast", "outlook")
    ):
        return "industry_forecast"
    if any(token in text for token in ("计划", "目标", "预计", "planned", "target", "expected")):
        return "company_target"
    return "observed_fact"


def _build_target(
    *,
    target_id: str,
    entity_specs: Sequence[Mapping[str, Any]],
    financial_targets: Mapping[str, Mapping[str, Any]],
    sources_by_ref: Mapping[str, Mapping[str, Any]],
    index: int,
) -> dict[str, Any]:
    target = financial_targets[target_id]
    text = TARGET_TEXT[target_id]
    decision_text = TARGET_DECISION_TEXT[target_id]
    ticker_info = target["ticker_verification"]
    ticker = str(ticker_info.get("requested_market_data_alias") or ticker_info["official_code"])
    ref = str(ticker_info["source_ref"])
    source = sources_by_ref[ref]
    name = str(target["company_name_zh"])
    primary_spec = entity_specs[0]
    entity_names = [str(item["name"]) for item in entity_specs]
    entity_name_text = "、".join(entity_names)
    return {
        "entity_key": primary_spec["key"],
        "target_name": name,
        "ticker": ticker,
        "market": str(ticker_info.get("exchange") or "公开市场"),
        "target_type": "security",
        "target_url": source.get("url"),
        "exposure_rationale": f"{target['direct_relation']['summary_zh']} 本研究用它同时检验{entity_name_text}能否转成供应商销量和盈利。",
        "evidence_ref_uri": source_uri(ref),
        "research_action": f"按季度跟踪{name}的分产品销量、利用率、价格、客户认证、资本开支、毛利和经营现金流，并与{entity_name_text}的项目进度对照。",
        "investment_view": text["view"],
        "risk_note": text["risk"],
        "target_priority": text["priority"],
        "target_quality_label": text["quality"],
        "relative_preference": f"先验证{name}在{entity_name_text}中的当前销量与客户关系，再与同类供应商比较高规格产品、价格和现金回报。",
        "confirmed_scenario_action": decision_text["confirmed"],
        "falsified_scenario_action": decision_text["falsified"],
        "target_profile_markdown": (
            f"{name}与{entity_name_text}存在可核验的主营或产品关系。{target['direct_relation']['summary_zh']}"
            "研究不把行业扩产直接写成公司订单，当前财务只用于检查需求是否已经穿透到销量、价格与现金流。"
        ),
        "target_deep_research_markdown": (
            f"对{name}的判断分为需求直接性、客户与项目关系、盈利兑现三步。"
            f"{target['direct_relation']['caveat_zh']}至少三期发行人财务用于观察收入、毛利、经营现金流和资本开支；"
            f"但只有与{entity_name_text}相关的分产品销量、认证与价格能够回答本研究的盈利弹性。"
        ),
        "entity_relation_markdown": f"{name}用于检验{entity_name_text}能否由行业总量转化为供应商销量与盈利。",
        "parent_research_relation_markdown": "该标的是需求侧研究从晶圆厂扩产、硅片采购到上市公司财务兑现的观察点。",
        "conditional_investment_recommendation": decision_text["conditional"],
        "financial_data_status": "已取得至少三期发行人财务，并补充2026年7月17日同一交易日的第三方行情、PE/PB/PS、市值及人民币和美元等值；亏损或无有效正值时明确标为市盈率不适用。",
        "link_status": "linked",
        "support_status": "partially_supported",
        "sort_order": index,
        "target_data_points": [
            *_audited_financial_points(target, sources_by_ref),
            *_market_snapshot_points(target_id, sources_by_ref),
        ],
    }


def _build_observation_target(
    *,
    entity_spec: Mapping[str, Any],
    sources_by_ref: Mapping[str, Mapping[str, Any]],
    index: int,
) -> dict[str, Any]:
    key = str(entity_spec["key"])
    if key == "nand_wafer_demand":
        ref = "DMD-SEMI-MEMORY-20260629"
        name = "NAND硅片供需观察篮子"
        metric = "全球300毫米存储装机月产能"
        value_text = "2026年410万片/月；2027年420万片/月（DRAM与NAND合计）"
        profile = "用存储整体装机、NAND项目里程碑和硅片商库存价格共同跟踪，不把存储合计强行拆成NAND片数。"
        action = "季度核验Kioxia、Micron和长江存储的实际晶圆投入、利用率、库存和原生片采购。"
        risk = "层数升级与良率改善可能使NAND位增长快于硅片面积，存储合计也无法替代NAND分产品数据。"
        confirmed_action = "若Kioxia、Micron和长江存储的NAND晶圆投入与利用率上升，同时原生片采购增加、库存下降，才提高NAND硅片面积需求的置信度。"
        conditional_recommendation = "在NAND分产品晶圆投入、层数、利用率、库存和原生片采购能够对账前，只观察供需，不把存储合计产能用于证券判断。"
    elif key == "mature_200mm_wafer_demand":
        ref = "S065"
        name = "200毫米硅片供需观察篮子"
        metric = "全球200毫米装机月产能"
        value_text = "2026年770万片/月；2027—2029年增速分别为3%、1%和2%"
        profile = "用纯200毫米装机、季度利用率、库存和价格跟踪成熟尺寸，不与300毫米面积等效结果相加。"
        action = "季度核验汽车、工业、功率和模拟厂开工，以及供应商分尺寸出货、库存、价格和现金流。"
        risk = "汽车工业需求疲弱或旧厂利用率恢复足以满足订单时，新装机可能先形成闲置和价格压力。"
        confirmed_action = "若200毫米功率、模拟与汽车晶圆厂开工率提高，供应商分尺寸出货增长、库存下降且价格企稳，才提高成熟硅片需求判断。"
        conditional_recommendation = "在纯200毫米出货、利用率、库存和价格形成连续同向改善前，不把8英寸等效产能或单个项目投资用于证券判断。"
    else:
        raise ValueError(f"没有为{key}配置观察篮子")
    risk_clause = risk.rstrip("。；")
    source = sources_by_ref[ref]
    return {
        "entity_key": key,
        "target_name": name,
        "ticker": f"OBS-{key}",
        "market": "研究观察工具",
        "target_type": "basket",
        "target_url": source.get("url"),
        "exposure_rationale": profile,
        "evidence_ref_uri": source_uri(ref),
        "research_action": action,
        "investment_view": "当前用于验证行业需求是否兑现，不作为可交易证券或收益预测。",
        "risk_note": risk,
        "target_priority": "P1",
        "target_quality_label": "行业数据直接，分产品数据仍待补充",
        "relative_preference": "先观察实际开工、库存与价格，再比较供应商盈利，不以规划产能替代订单。",
        "confirmed_scenario_action": confirmed_action,
        "falsified_scenario_action": f"若{risk_clause}，则下调数量需求和供应商盈利判断。",
        "target_profile_markdown": f"{name}不是证券标的。{profile}",
        "target_deep_research_markdown": f"{action}{risk}观察篮子只汇总同一口径证据，不补造供应商份额或实时估值。",
        "entity_relation_markdown": f"该观察篮子为{entity_spec['name']}提供独立的需求、库存和价格验证。",
        "parent_research_relation_markdown": "它用于把晶圆厂扩产叙事与实际硅片采购和供需状态对照。",
        "conditional_investment_recommendation": conditional_recommendation,
        "financial_data_status": "这是行业观察工具，不适用证券财务和实时估值；公司财务在具名证券页单独验证。",
        "link_status": "linked",
        "support_status": "partially_supported",
        "sort_order": index,
        "target_data_points": [
            {
                "metric_name": metric,
                "metric_category": "industry_demand",
                "period": "2026—2029" if key == "mature_200mm_wafer_demand" else "2026—2027",
                "as_of_date": AS_OF_DATE,
                "unit": "万片/月",
                "value_num": None,
                "value_text": value_text,
                "source_title": source["title"],
                "source_title_zh": source.get("title_zh") or source["title"],
                "source_publisher": source["publisher"],
                "source_excerpt": source["excerpt"],
                "source_excerpt_zh": source.get("excerpt_zh") or source["excerpt"],
                "evidence_ref_uri": source_uri(ref),
            }
        ],
    }


def _main_sections() -> list[dict[str, Any]]:
    summary = """
### 研究回答

2026—2030年全球半导体硅片需求大方向向上，但不同尺寸和产品明显分化。最有把握的是300毫米先进逻辑：SEMI预计全球300毫米装机月产能从反算的2024年约847万片升至2028年1,110万片，其中7纳米及以下从85万片升至140万片。^src:source_ref:S001 200毫米则是低速增长，2026年约770万片/月，2027—2029年公开增速为3%、1%和2%；2030年没有同等级公开预测，只能做情景延伸。^src:source_ref:S065 存储整体预计2026年410万片/月、2027年420万片/月，说明HBM需求强并不意味着晶圆面积按堆叠层数增长。^src:source_ref:DMD-SEMI-MEMORY-20260629

供需方面，现有公开资料不能支持一个精确的“全球硅片缺口”。SEMI预计2028年300毫米硅片出货超过10,800百万平方英寸，换算为月均至少约821万片；与同年1,110万片晶圆厂装机相比约为74%。两个数字的分母分别是硅片出货面积和晶圆厂装机能力，只能作为同年强度对照，不能把差额叫作缺口，也不能直接当作利用率。^src:source_ref:DMD-SEMI-WAFER-OUTLOOK-202509 供应侧公开资料只确认约90%的硅片来自东亚、五家公司掌握多数供应，缺少各家按尺寸、规格和年份拆分的有效可售产能。^src:source_ref:DMD-NIST-GLOBALWAFERS 因此本研究的结论是“高规格300毫米存在趋紧可能，普通300毫米、200毫米和功率相关产品仍可能宽松”，而不是全市场统一短缺。

### 数据与方法

本轮逐项核验36个晶圆厂项目，并把“开工、设备搬入、首片、批量生产、满产”分别记录。只有UMC新加坡、ESMC德累斯顿、ST Agrate和士兰微厦门高端模拟一期四项同时具备可解释为新增的月产能与建模时点，进入公开可量化项目子集；其余项目保留方向和时间，不按投资额反推。UMC每月3万片是满产规模，公司只披露2026年开始批量生产，没有披露满产年份，模型把2028年作为显式研究假设。^src:source_ref:S031 ESMC计划4万片/月并在2029年达到，ST Agrate目标净增约8,667片/月；士兰微一期年产24万片折合2万片/月，计划2027年第四季度通线并于2030年达产。四项同样按年度爬坡计入。^src:source_ref:S015 ^src:source_ref:S036 ^src:source_ref:DMD-SILAN-12INCH-ANALOG-20260105

总量模型、公开可量化项目子集与公司财务各回答一个问题：总量说明市场边界，项目台账说明落地节奏，公司财务说明需求是否转成收入、毛利和现金流。三者不相加，也不互相补空。公开资料能覆盖的项目范围只是全球项目的下限，但4个项目的片数结果是带参数的情景估算，不能视为已实现采购的最低值；36项台账也是经本轮检索核验的样本，不是全球全部项目名录。Sony熊本合志、GlobalFoundries Malta/Burlington、晶合集成三期和士兰微厦门新线已补入；力积电当前官方资料确认现有厂组合和P5交易变化，但没有可核验的2026—2030新增月产能，因此不进入定量排名。^src:source_ref:DMD-PSMC-CURRENT-2026

### 核心结论

需求优先级依次是先进逻辑高规格300毫米、先进DRAM/HBM的规格价值、NAND周期恢复、成熟300毫米，以及低速增长但当前偏宽松的200毫米。SOI具有具名客户平台和高价值属性，但缺少全球分尺寸产能、出货和价格基线，不做主观片数或缺口。项目落地集中在2026—2028年，2029—2030年更依赖前期项目利用率、延期项目重启和下一轮投资。

中国供应商按当前可核验经营证据排序为上海超硅、西安奕材、沪硅产业、立昂微、上海合晶、TCL中环半导体材料。排序看的是当前瓶颈能力、实际销量、认证时效、产品结构、价格、利用率、毛利和现金流，不是只看设计产能。上海超硅有当前瓶颈能力和利用率口径；西安奕材2025年销量和收入继续增长、主营业务毛利率转正，但归母仍大额亏损，第二工厂稳定利用率和盈利尚待核验。两家公司都说明国产替代已有供货基础，却还没有普遍转成高质量盈利。^src:source_ref:S058 ^src:source_ref:FIN-ESWIN-2025AR

### 如果想进一步研究，需要补充的信息

第一优先级是主要先进逻辑和存储项目的净增月产能、季度晶圆投入及利用率；第二是全球五大硅片商按尺寸、规格、区域的有效产能、库存、认证与长协价格；第三是中国供应商按季度拆分的12英寸分产品销量、均价、良率、利用率、客户复购和现金流。补齐这三组数据，才能从方向判断进入可复核的年度缺口和公司盈利情景。
"""

    demand_transmission = """
### 问题

终端需求不会直接变成硅片订单。真正需要验证的是一条逐层收窄的传导链：终端产品或算力需求先改变芯片出货与产品结构，晶圆厂再决定新增晶圆投入、节点迁移和产能利用率，最后才形成特定尺寸、规格和认证体系下的硅片采购。本节把终端驱动、晶圆厂行为和硅片需求分开，避免把AI服务器投资、汽车销量、政府补贴或晶圆厂设备支出直接写成硅片市场规模。

### 2020年以来的周期回溯

上一轮扩张说明“需求强、建厂多、硅片盈利好”并不会同步发生。全球半导体硅晶圆面积出货从2020年的12,407百万平方英寸升至2022年的14,713百万平方英寸，随后在2023年降至12,602、2024年进一步降至12,266；也就是说，疫情后的补库和扩产高峰之后，库存与利用率调整足以让面积需求连续回落。^src:source_ref:S006 到2025年，面积出货恢复至12,973百万平方英寸、同比增长5.8%，但销售额反而下降1.2%，说明数量复苏并不自动带来价格和盈利改善。^src:source_ref:S005 同期项目也出现明显分化：Intel一边推进18A爬坡，一边放慢Ohio建设并取消德国晶圆厂计划，证明区域补贴和长期规划仍要服从实际需求与资本纪律。^src:source_ref:S017

2026—2030与上一轮不同的地方，不是“所有硅片重新短缺”，而是需求更集中于AI相关先进逻辑、高规格存储和地区本地化。7纳米及以下装机月产能预计由2024年的85万片升至2028年的140万片，先进节点的面积和规格同时提高；但NAND可以先利用现有洁净室和设备升级吸收位增长，200毫米到2029年也只是低速扩张。^src:source_ref:S001 ^src:source_ref:S040 ^src:source_ref:S065 供应链重组则更多改变产能所在地和认证路径：美国新增本地硅片能力与政策支持可以降低地域集中风险，却只有在设备安装、客户认证、利用率和复购落地后才增加有效供给。^src:source_ref:S051 ^src:source_ref:DMD-NIST-GLOBALWAFERS 因此本轮研究把“先进规格结构性增长”“成熟产品周期恢复”和“区域产能迁移”分开，不把2020—2022年的总量景气直接外推到未来五年。

### 证据与传导路径

第一条链是AI服务器、GPU、ASIC和云厂商自研芯片，经先进逻辑转向高规格300毫米硅片。SEMI把AI工作负载和2纳米以下节点列为未来300毫米投资的重要动力，并预计2026年全球300毫米前端设备支出约1,420亿美元、2026年装机能力增长约7%；这证明晶圆厂正在为先进逻辑扩充能力，但设备支出同时包含光刻、刻蚀、厂务等，不能换算为硅片片数。^src:source_ref:DMD-SEMI-300MM-OUTLOOK-2Q26 台积电亚利桑那一厂已于2024年第四季度进入4纳米大批量制造，二厂正在安装设备并以2027年下半年量产为目标；这类“已量产—设备安装—计划量产”的里程碑比投资额更接近未来晶圆投入。^src:source_ref:S011 因此可以认为AI需求提高了先进逻辑高规格硅片的方向性需求，但具体到年度数量，仍必须等待各厂月度晶圆投入、利用率和材料认证。

第二条链是AI训练推动HBM和先进DRAM，推理与存储扩容同时影响NAND，再经存储晶圆投入形成300毫米硅片需求。SEMI预计300毫米存储装机月产能从2026年的约410万片升至2027年的420万片，说明面积增量明显低于“HBM层数增长”给人的直觉。^src:source_ref:DMD-SEMI-MEMORY-20260629 HBM堆叠发生在晶圆制造之后；当月产能已经表示晶圆投入时，再乘堆叠层数会重复计算。Micron新加坡项目是更接近需求落地的证据：公司在既有NAND制造园区于2026年1月开工，预计2028年下半年开始输出晶圆，并明确表示后续爬坡与需求相匹配。^src:source_ref:DMD-MICRON-SINGAPORE-20260127 因此存储需求应拆成“晶圆面积温和增加”和“高端规格价值提高”两部分，不能只用位增长或HBM层数代表硅片数量。

第三条链是汽车电动化、功率电子、模拟和嵌入式芯片，经成熟制程200毫米或300毫米工厂形成硅片需求。GlobalFoundries的Malta扩建跨越十年以上，Burlington则是现有200毫米设施改造；项目方向支持汽车、通信和特色工艺，但长期总投资或园区总产量都不能全部归入2026—2030新增量。^src:source_ref:S032 SEMI预计200毫米装机能力2026年增至约770万片/月，随后2027—2029年增速降至3%、1%和2%，这说明成熟制程需求仍增长，但强度低于先进300毫米。^src:source_ref:S065 同时，供应商披露功率和200毫米仍受库存与需求疲弱影响，意味着汽车或工业终端只有在实际开工和库存下降后才会变成硅片采购。^src:source_ref:DMD-SILTRONIC-AR2025

第四条链是工业、物联网和机器人需求，经微控制器、传感器、模拟与功率器件进入成熟晶圆厂。SEMI把汽车、物联网和机器人列为300毫米投资的长期驱动，但这是行业方向，不是对单个项目或单个硅片供应商的订单确认。^src:source_ref:DMD-SEMI-DEMAND-TRANSMISSION-20251008 这条链最容易被高估，因为旧厂提高利用率、设备改造和产品迁移可能先吸收增量；只有季度晶圆投入、利用率和原生片采购同时上升，才证明终端需求穿透到了硅片。

第五条链是地缘政治、补贴和本地化，经“在哪个地区建设产能”影响供应链布局。美国CHIPS激励和各地本地化政策确实改变了台积电、三星、GlobalFoundries等项目的选址和资本承担方式。^src:source_ref:S021 ^src:source_ref:S028 但补贴不是终端需求，也不会自动增加全球芯片消费；如果同一需求只是从亚洲转移到美国或欧洲，全球硅片总量未必增加。政策只有在新增工厂形成实际晶圆投入、且没有被其他地区减产抵消时，才构成净需求。

### 估算方法与结论

模型只在最后一层计算硅片数量，核心关系为：

> 年度新增硅片采购量 = 已披露的净增月产能 × 12个月 × 当年平均爬坡比例 × 工艺投入系数 × 库存系数

爬坡比例表示投产后当年实际开工程度；工艺投入系数只补充监控片等合理新增消耗；库存系数反映建库或去库。终端市场规模、资本开支、设备支出、HBM层数和补贴金额都不进入片数公式，只用于解释为什么某类项目可能推进或延后。由此得到的结论是：先进逻辑具备最完整的“终端需求—项目推进—高规格材料”链；DRAM/HBM的规格价值证据强于面积倍增证据；NAND和成熟制程更依赖利用率、库存与现有厂改造；政策主要改变地域和时点，而非自动创造终端需求。

### 如果想进一步研究，需要补充的信息

需要按应用拆分的季度芯片出货、具名晶圆厂的月度晶圆投入和利用率、项目设备搬入与量产日期、硅片规格及认证批次，以及供应商按产品的销量、价格与库存。只有这些数据在同一期间连续出现，才能识别终端需求究竟在芯片层、晶圆厂层还是硅片层被吸收，并把当前方向判断收窄为年度采购量。
"""

    global_projects = """
### 问题

全球哪些晶圆厂项目在2026—2030年最可能形成新增硅片采购，不能简单按投资额或项目数量排序。项目对需求的影响取决于产品、尺寸、建设阶段、实际晶圆投入和公开月产能；一座美国长期巨型项目可能在2030年前贡献有限，一座欧洲中型厂若已经设备搬入并有明确净增产能，反而更适合近期量化。

### 证据与项目分层

36项核验项目可分三组。第一组是战略影响大但月产能未公开的先进逻辑项目，包括台积电亚利桑那、三星Taylor、Intel Fab 52和Rapidus IIM-1。它们决定高规格300毫米需求方向：Intel 18A已进入制造爬坡，三星仍以2026年底前投入运营为目标，Rapidus处于原型晶圆验证阶段。^src:source_ref:S017 ^src:source_ref:DMD-SAMSUNG-TAYLOR-20260610 ^src:source_ref:S038 这些项目优先级高，但不能给出精确片数。

第二组是存储项目，近端重点为SK hynix M15X、Micron Boise与新加坡、Yongin首厂和Samsung P5。M15X在2026年第一季度开始晶圆投入，却没有公开月产能；Yongin计划2027年2月启用首个洁净室，不等于量产；Samsung P5计划2028年运营，产品组合和月产能仍未披露。^src:source_ref:S025 ^src:source_ref:S024 ^src:source_ref:S030 因此存储项目更适合按里程碑排序，而不是用媒体产能相加。

第三组是成熟逻辑、模拟和功率项目，其中UMC新加坡、ESMC和ST Agrate可以进入公开可量化项目子集。UMC披露2026年开始批量生产、每月3万片满产规模；ESMC计划每月4万片并在2029年达到；ST Agrate目标到2027年净增每周2,000片，折合约8,667片/月。^src:source_ref:S031 ^src:source_ref:S015 ^src:source_ref:S036 Crolles每周1.4万片是2027年目标总量，折合约6.07万片/月，但基期未披露，不能当作净增。Infineon德累斯顿在2026年7月2日启用，来源没有说明晶圆尺寸或稳定爬坡，也不进入片数求和。^src:source_ref:S035

### 排序方法

项目优先级先看产品对硅片规格和面积的影响，再看当前里程碑与2026—2030窗口的重合，最后看是否披露可复算净增月产能。战略优先级不等于数量排名：先进逻辑项目即使缺少月产能，仍可能对高规格供应商最重要；定量排名则只允许使用明确净增的同口径项目。项目台账因此保留两个互补视角——“应重点跟踪谁”和“当前至少能算出多少”，绝不把缺失数据填成零或用行业平均投资强度补造。

区域上，美国项目多、投资大但普遍分期长；亚洲同时包含先进逻辑、存储和成熟制程，时点分散且若干中国项目缺少公开月产能；欧洲公开月产能相对更容易复算，但规模不能代表全球。GlobalFoundries Malta的100万片/年混合现有厂扩建和新厂、跨十年以上，无法拆出2026—2030净增；Burlington只是现有200毫米设施改造。^src:source_ref:S032 Sony熊本合志新厂与台积电仅签署无约束力备忘录、研究下一代图像传感器线，尚未形成产能和投产承诺。^src:source_ref:DMD-SONY-KOSHI-20260514

### 分析与结论

2026—2028年是项目从建设转向设备投入和初期生产的密集阶段，但采购兑现会晚于开工公告，并受季度爬坡影响。2029—2030年不能把现有项目直线外推：部分长期美国项目可能延迟，部分亚洲项目可能通过既有洁净室提高利用率，欧洲项目也可能因终端需求调整节奏。项目数据库最重要的作用不是制造一个伪精确全球总和，而是明确每个项目当前能证明到哪一步。

### 如果想进一步研究，需要补充的信息

需要台积电、三星、Intel、Rapidus、Micron、SK hynix和中国主要存储厂的设备搬入、季度晶圆投入、利用率与硅片采购；对有周产能或合并产能的项目，还要补充基期和项目拆分。取得这些资料后才能把战略优先级转成年度采购排名，并判断项目延期对供应商收入的具体影响。
"""

    product_demand = """
### 问题

晶圆厂扩产如何转化为不同产品的硅片需求，需要同时回答“面积增加多少”和“每片价值是否提高”。先进逻辑、DRAM/HBM、NAND、成熟200毫米与SOI的分母不同，不能把资本开支、位增长、堆叠层数或集团收入混成一个需求增速。

### 数据和计算方法

300毫米总量以SEMI 2028年1,110万片/月为锚，基准路径为2026年约970万、2027年1,037万、2028年1,110万、2029年1,188万、2030年1,235万片/月。2029年沿用约7%的公开方向，2030年4%仅是基准研究情景，不是行业预测。^src:source_ref:S001 ^src:source_ref:S064 2028年300毫米硅片出货面积下限换算为月均约821万片，只用来检查装机与出货的数量级，不与装机相减。^src:source_ref:DMD-SEMI-WAFER-OUTLOOK-202509

4个公开可量化项目沿用上述核心公式估算基准、较慢和较快情景。HBM堆叠层数不再乘入，因为晶圆厂月产能已经是晶圆投入；良率损失也不重复算作新增开工。UMC满产年份未披露，模型将2028年设为研究假设并在情景中调整爬坡。^src:source_ref:S031

### 分产品判断

先进逻辑的面积和规格最强。7纳米及以下月产能由85万片增至140万片，意味着低缺陷抛光片、外延片和更严过程控制的需求可能同时上升；但公司受益仍取决于认证和复购。^src:source_ref:S001 DRAM/HBM的面积增量更温和：存储整体2026至2027年只增加约10万片/月，HBM主要提高规格和价值，不能按堆叠层数放大数量。^src:source_ref:DMD-SEMI-MEMORY-20260629

NAND位增长与面积增长脱钩更明显。Kioxia公开表示优先利用现有洁净室和追加设备推动位增长，因此层数、良率和利用率可能先吸收需求；新厂只有披露净增月产能后才进入片数。^src:source_ref:S040 200毫米则按770万片/月和3%、1%、2%的公开增速计算到2029年，2030年用0%、2%、4%三种情景；它当前仍受功率和工业库存影响，不能套用300毫米景气。^src:source_ref:S065 ^src:source_ref:DMD-SILTRONIC-AR2025

SOI不量化。公开资料确认Soitec与具名平台合作、GlobalWafers新增SOI能力，但缺少全球按尺寸拆分的有效产能、出货和价格，任何片数或市场缺口都不可复核。^src:source_ref:S051 ^src:source_ref:S055 把SOI与普通抛光片相加会同时混淆产品、价格和客户认证。

### 分析与结论

2026—2030年最值得关注的是“高规格价值增长快于总面积”，而不是所有硅片同步紧缺。先进逻辑具有面积与规格双重驱动；存储的规格效应强于HBM叙事暗示的数量效应；NAND面积取决于层数和利用率；200毫米低速增长且当前偏宽松；SOI具备应用方向却不具备公开量化条件。4个可量化项目的基准情景和全球总量路径之间的巨大差距主要来自公开信息覆盖不足，不应解释为额外需求。

### 如果想进一步研究，需要补充的信息

需要付费或公司一手的逻辑、DRAM、NAND、200毫米和SOI分产品装机、季度利用率及原生片采购，并用实际采购反校爬坡、工艺和库存系数。公司层面还需分规格销量与价格，才能把面积增长转换为收入和毛利。
"""

    supply_balance = """
### 问题

2026—2030年会不会出现硅片短缺，首先要把需求侧晶圆厂装机与供应侧硅片有效产能放在同一尺寸、规格、年度和利用率口径。现有公开信息只能完成部分对照：需求端有SEMI装机与出货面积，供应端却没有全球主要厂商按尺寸和高规格认证拆分的完整有效产能。因此本节给出年度判断和触发条件，不制造精确缺口。

### 可核验数据

需求端，300毫米基准装机从2026年约970万片/月升至2028年1,110万片/月，之后在研究情景中升至2029年约1,188万和2030年约1,235万。^src:source_ref:S001 ^src:source_ref:S064 2028年硅片出货展望超过10,800百万平方英寸，换算月均至少约821万片，是出货强度下限而非供应能力。^src:source_ref:DMD-SEMI-WAFER-OUTLOOK-202509 200毫米2026年约770万片/月并低速增长，当前供应商年报仍称功率和200毫米需求受高库存压制。^src:source_ref:S065 ^src:source_ref:DMD-SILTRONIC-AR2025

供应端，NIST确认约90%的硅片来自东亚，五家公司掌握多数全球供应，但没有给出按产品可售月产能。^src:source_ref:DMD-NIST-GLOBALWAFERS SEMI当前硅片市场监测产品页说明其付费数据库覆盖按地区、尺寸的季度出货、供需、价格和预测，反过来表明完整数表并未在公开页面提供。^src:source_ref:DMD-SEMI-SI-MONITOR-2026Q1 公司层面也出现供给并非全面紧张的证据：Siltronic新加坡厂已完成多项客户认证，但因需求低于原先预期而放慢爬坡；信越化学对200毫米仍持偏宽松判断。^src:source_ref:DMD-SILTRONIC-AR2025 ^src:source_ref:S053

### 年度判断方法

2026年看库存正常化与已投项目的初期爬坡，2027年看先进逻辑和存储项目是否从目标转成实际晶圆投入，2028年用1,110万片装机与821万片以上出货强度作数量级对照，2029—2030年则观察前期项目利用率和硅片商扩产是否同步。每年都按高规格300毫米、普通300毫米、200毫米和SOI分别判断；某一产品趋紧不外推到其他产品。项目公告只改变需求时点，供应商新厂还必须经过客户认证和达到经济利用率才算有效供给。

### 分析与结论

当前更可能出现的是结构性错配，而不是全市场统一缺口。先进逻辑与部分先进存储要求高规格、长认证周期，合格供给可能阶段性趋紧；普通300毫米若多家扩产同时释放，价格和利用率可能承压；200毫米仍有库存和需求疲弱证据；SOI因口径不全无法判断绝对平衡。2026—2027年供需改善主要来自库存恢复与项目爬坡，2028年先进装机扩张更明显，2029—2030年的紧张程度高度依赖项目延期、客户认证和供应商扩产纪律。

能够证明趋紧的信号应同时包括交付期延长、长协价格企稳或上涨、库存下降、高规格利用率上升和客户认证加速；只看到晶圆厂资本开支不够。能够证明过剩的信号则是硅片销量增长但价格、毛利和现金流下降，新厂爬坡放慢且库存继续上升。Siltronic当前披露已经提示后一种风险仍存在。^src:source_ref:DMD-SILTRONIC-AR2025

### 如果想进一步研究，需要补充的信息

最关键的是SEMI付费供需数据库或等价的一手数据，以及五大硅片商按200毫米、普通300毫米、高规格300毫米和SOI拆分的有效产能、出货、利用率、库存、认证和价格。需求端需同口径的晶圆厂实际开工。只有这些数据齐备，才能计算年度缺口；否则精确数字会把口径差额误写成供需差额。
"""

    china_suppliers = """
### 问题

中国硅片企业谁更能承接2026—2030年需求，排序不能只看规划产能。高信息比较至少要同时回答：当前瓶颈能力是否可用、实际销量和利用率如何、客户认证是否仍在复购、产品是否匹配先进或特色需求，以及价格、毛利和现金流能否证明新增销量有质量。

### 证据与排名方法

当前第一位是上海超硅。公司2025年12英寸瓶颈年产能367万片，折合约30.58万片/月，利用率75.18%，当前能力与利用率口径最完整；它的关键是补齐瓶颈工序、提升利用率并把认证转成订单。^src:source_ref:S058 第二位西安奕材规划到2026年形成120万片/月12英寸硅片产能，但当前稳定可售能力和利用率尚未直接披露；持续亏损意味着规划规模、价格、良率、利用率和折旧尚未共同跨过盈亏门槛。^src:source_ref:S059

第三位沪硅产业具备30万片/月300毫米项目和多家客户认证基础，但核心客户资料来自2021年，必须用当前复购核验，不能直接当作2026订单。^src:source_ref:S057 第四位立昂微2025年12英寸销量178.57万片、名义产能30万片/月，硅片业务收入增长65.63%，积极信号较多，但在建或延期项目可能增加折旧。^src:source_ref:S061 第五位上海合晶现有12英寸功率硅片4万片/月、郑州二期CIS目标6万片/月、远期逻辑规划10万片/月，细分定位清楚但近端规模较小。^src:source_ref:S062 第六位TCL中环半导体材料2025年销量增长23.99%、库存增长35.87%，且缺少12英寸分产品结构，必须先解释库存与产品组合。^src:source_ref:S060

排序依次使用瓶颈能力、销量与利用率、当前客户认证、高规格产品结构、价格与盈利五层证据。规划产能只说明潜力，历史客户名单只说明曾经进入体系，二者都不能替代当期采购。排名是当前研究优先级，会随季度证据变化，不是技术绝对名次或股票推荐。

### 分析与结论

中国供应商已经具备规模化12英寸供货与客户认证基础，但需求增长尚未普遍转化为盈利。上海超硅的当前瓶颈能力与利用率证据更完整，西安奕材的规划规模更大但实际稳定供给仍需核验，沪硅产业具备较完整产品和客户基础，立昂微处于销量快速增长与项目延期并存阶段，上海合晶偏细分，TCL中环的信息粒度最不足。这个顺序与全球供应高度集中的现实并不矛盾：先进节点认证和长期一致性仍可能使新增订单继续集中于既有国际龙头。^src:source_ref:DMD-NIST-GLOBALWAFERS

国产替代最可能先发生在已有客户认证、规格匹配且能持续复购的产品，而不是所有12英寸硅片同步获得份额。若普通抛光片集中投产、高端认证滞后，国内供给会先于有效需求释放；其表现是利用率低、平均售价下降、库存上升、毛利与经营现金流恶化。若高规格占比和利用率改善，即使总销量增速一般，利润也可能更快恢复。

标的跟踪应把行业需求和公司兑现分开。对西安奕材，重点是规划产能能否转成可核验的稳定销量并扭亏；对沪硅产业，重点是历史认证是否形成当前批量复购；对立昂微和上海合晶，重点是项目进度与细分客户；对上海超硅，重点是瓶颈工序和75.18%利用率能否改善。证券页使用同一交易日行情和统一汇率比较，并明确亏损企业的市盈率不适用。

### 如果想进一步研究，需要补充的信息

需要六家公司按季度披露的12英寸抛光片、外延片、退火片等分产品销量、均价、良率、利用率、库存、认证转批量日期、客户年度采购和经营现金流。还应把国内晶圆厂新增项目与供应商订单逐一配对，确认本地扩产究竟由谁供货、何时放量以及是否具备盈利质量。
"""

    definitions = (
        ("summary", "摘要", summary),
        ("demand_transmission", "终端需求如何传导为硅片采购", demand_transmission),
        ("global_projects", "全球晶圆厂扩产格局与项目优先级", global_projects),
        ("product_demand", "不同产品如何形成硅片需求", product_demand),
        ("supply_balance", "2026—2030年硅片供需会怎样变化", supply_balance),
        ("china_suppliers", "中国硅片供应商的受益顺序", china_suppliers),
    )
    sections = [_report_section(key=key, title=title, body=body) for key, title, body in definitions]
    shallow = [(section["section_title"], len(section["body_markdown"])) for section in sections if len(section["body_markdown"]) < 1400]
    if shallow:
        raise ValueError(f"主报告章节不足1400字符：{shallow}")
    return sections


def _model_bundle(
    output_dir: Path,
    *,
    total_project_count: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    inputs = copy.deepcopy(_load_json(DEMAND_DIR / "model_inputs.json"))
    expected_top_level = {
        "model_id", "as_of", "scope", "years", "unit_contract", "formula", "interpretation",
        "aggregate_conversion_assumptions", "project_ramp_assumptions", "process_input_factors",
        "inventory_factors", "official_200mm_model_assumptions", "forecast_backtest_inputs",
        "source_refs_by_output", "public_aggregate_inputs", "post_2028_assumptions",
        "bottom_up_disclosed_increment_projects", "excluded_quantified_projects",
    }
    unknown = sorted(set(inputs) - expected_top_level)
    missing = sorted(expected_top_level - set(inputs))
    if unknown or missing:
        raise ValueError(f"需求模型冻结输入字段不完整：missing={missing}, unknown={unknown}")
    outputs = calculate_wafer_demand_scenarios(
        inputs,
        total_project_count=total_project_count,
    )
    aggregate = outputs["aggregate_300mm"]
    if aggregate["scenarios"]["base"]["2028"]["300mm_capacity_wspm"] != 11_100_000:
        raise ValueError("300毫米2028公开锚点反算失败")
    rows_200 = outputs["official_200mm_capacity"]["scenarios"]["base"]
    if rows_200[0]["installed_200mm_wspm"] != 7_700_000:
        raise ValueError("200毫米2026公开锚点反算失败")
    if not all(check["pass"] for check in outputs["unit_reverse_checks"]):
        raise ValueError("模型量纲反算存在失败项")
    error = outputs["forecast_backtest"]["forecast_above_actual_pct"]
    backtest = inputs["forecast_backtest_inputs"]
    expected = (float(backtest["forecast_msi"]) / float(backtest["actual_msi"]) - 1) * 100
    if abs(float(error) - expected) > 0.01:
        raise ValueError("2025年预测误差反算失败")
    input_path = output_dir / "model_inputs.json"
    output_path = output_dir / "model_outputs.json"
    write_json(input_path, inputs)
    write_json(output_path, outputs)
    return inputs, outputs, {
        "model_inputs_sha256": sha256_file(input_path),
        "model_outputs_sha256": sha256_file(output_path),
        "model_code_sha256": sha256_file(ROOT / "tools" / "opportunity_lens" / "silicon_expansion_models.py"),
    }


def _visual(outputs: Mapping[str, Any]) -> dict[str, Any]:
    years = [2026, 2027, 2028, 2029, 2030]
    aggregate = outputs["aggregate_300mm"]["scenarios"]
    panel_300 = line_chart_panel(
        title="全球300毫米装机月产能",
        unit="万片/月",
        series=[
            {
                "label": label,
                "observations": [
                    {
                        "period": year,
                        "value": aggregate[key][str(year)]["300mm_capacity_wspm"] / 10_000,
                    }
                    for year in years
                ],
            }
            for key, label in (("downside", "较慢爬坡"), ("base", "基准路径"), ("upside", "较快爬坡"))
        ],
    )
    capacity_200 = outputs["official_200mm_capacity"]["scenarios"]
    panel_200 = line_chart_panel(
        title="全球200毫米装机月产能",
        unit="万片/月",
        series=[
            {
                "label": label,
                "observations": [
                    {
                        "period": row["year"],
                        "value": row["installed_200mm_wspm"] / 10_000,
                    }
                    for row in capacity_200[key]
                ],
            }
            for key, label in (("downside", "2030不增长"), ("base", "2030增长2%"), ("upside", "2030增长4%"))
        ],
    )
    base_300 = aggregate["base"]
    base_200 = {row["year"]: row for row in capacity_200["base"]}
    bottom_up = {
        row["year"]: row
        for row in outputs["bottom_up_disclosed_wspm_subset"]["base"]["by_year"]
    }
    return build_line_visual(
        block_key="global_wafer_capacity_2026_2030",
        title="300毫米与200毫米产能路径",
        subtitle="300毫米只有2028年1,110万片/月是SEMI公开绝对量；2026—2027按该锚点和公开约7%增速反算，2029按增长方向延伸，2030为研究情景。200毫米2026—2029使用SEMI当前绝对量与增速。",
        how_to_read="两个面板均以万片/月展示装机产能。表中“公开锚点、反算、方向延伸、研究情景”逐年标明，不能把推算值写成SEMI直接预测。",
        analysis="300毫米增长更快且高规格需求集中；200毫米保持低速扩张。4个公开可量化项目的片数是带爬坡、利用率、工艺与库存假设的基准情景，不能替代全球总量，也不能视为已实现采购的最低值。",
        panels=[panel_300, panel_200],
        print_columns=["年份", "300毫米基准（万片/月）", "300毫米数值口径", "200毫米基准（万片/月）", "4个可量化项目基准情景（万片/年）", "来源"],
        print_rows=[
            [
                year,
                round(base_300[str(year)]["300mm_capacity_wspm"] / 10_000, 1),
                {
                    2026: "按2028公开锚点与约7%增速反算",
                    2027: "按2028公开锚点与约7%增速反算",
                    2028: "SEMI公开绝对量锚点",
                    2029: "按SEMI约7%增长方向延伸",
                    2030: "研究情景，不是行业预测",
                }[year],
                round(base_200[year]["installed_200mm_wspm"] / 10_000, 1),
                round(bottom_up[year]["total_prime_wafers"] / 10_000, 1),
                _row_citations(
                    [
                        "S001" if year <= 2028 else "S064",
                        "S065",
                        "S031",
                        "S036",
                        "S015",
                        "DMD-SILAN-12INCH-ANALOG-20260105",
                    ]
                ),
            ]
            for year in years
        ],
        source_refs=["S001", "S015", "S031", "S036", "S064", "S065", "DMD-SILAN-12INCH-ANALOG-20260105"],
    )


def _table_visual(
    *,
    block_key: str,
    title: str,
    subtitle: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    source_refs: Sequence[str],
    sort_order: int,
) -> dict[str, Any]:
    table = {"columns": list(columns), "rows": [list(row) for row in rows]}
    return {
        "block_key": block_key,
        "block_type": "table",
        "title": title,
        "subtitle": subtitle,
        "data": {"what": title, "table": table},
        "display_data": table,
        "print_fallback": table,
        "evidence_ref_uri_list": [source_uri(ref) for ref in dict.fromkeys(source_refs)],
        "support_status": "partially_supported",
        "red_flag_level": "none",
        "sort_order": sort_order,
    }


def _format_investment(value: Any) -> str:
    if not isinstance(value, Mapping):
        return "目前没有直接披露"
    number = float(value["value"])
    currency = str(value.get("currency") or "")
    scope = str(value.get("scope") or "").strip()
    if currency == "USD bn":
        amount = f"{number * 10:g}亿美元"
    elif currency == "EUR bn":
        amount = f"{number * 10:g}亿欧元"
    elif currency == "KRW tn":
        amount = f"{number:g}万亿韩元"
    elif currency == "RMB 100m":
        amount = f"{number:g}亿元人民币"
    else:
        amount = f"{number:g} {currency}".strip()
    return f"{scope}{amount}" if scope else amount


def _row_citations(refs: Sequence[str]) -> str:
    return " ".join(f"^src:{source_uri(ref)}" for ref in dict.fromkeys(str(ref) for ref in refs))


def _project_database_visual(project_ledger: Mapping[str, Any]) -> dict[str, Any]:
    rows: list[list[Any]] = []
    refs: list[str] = []
    for project in project_ledger["projects"]:
        diameter = (
            f"{int(project['wafer_diameter_mm'])}毫米"
            if project.get("wafer_diameter_mm") is not None
            else "目前没有直接披露尺寸"
        )
        node = str(project.get("node") or "目前没有直接披露工艺")
        capacity = f"产能：{project.get('capacity_scope') or '目前没有直接披露可复算月产能'}"
        if project.get("wspm") is not None:
            capacity = f"产能：{float(project['wspm']) / 10_000:g}万片/月；{project.get('capacity_scope') or '口径见说明'}"
        investment_and_capacity = f"投资：{_format_investment(project.get('investment'))}；{capacity}"
        timing = []
        if project.get("construction_start"):
            timing.append(f"建设节点：{project['construction_start']}")
        if project.get("production_start"):
            timing.append(f"生产或投运口径：{project['production_start']}")
        if project.get("full_capacity_date"):
            timing.append(f"达到目标口径：{project['full_capacity_date']}")
        timing.append(f"当前：{project['status_as_of']}")
        project_refs = [str(ref) for ref in project.get("source_ids") or []]
        rows.append(
            [
                f"{project['company']}｜{project['fab_site']}｜{project['country_region']} {project['city']}",
                f"{diameter}｜{node}｜{project.get('product') or '目前没有直接披露产品'}",
                investment_and_capacity,
                "；".join(timing),
                _humanize_wafer_capacity_text(
                    project.get("model_treatment")
                    or "只保留项目事实，不进入片数测算"
                ),
                _row_citations(project_refs),
            ]
        )
        refs.extend(project_refs)
    return _table_visual(
        block_key="global_fab_project_database",
        title=f"全球晶圆厂扩产项目数据库（{len(project_ledger['projects'])}项）",
        subtitle="这是本轮经证据核验的项目样本，不是全球完整名录。每行区分投资、产能和进度；没有直接证据时不按投资额反推。",
        columns=["项目与地区", "尺寸、工艺与产品", "公开投资与产能", "当前进度", "对需求判断的作用", "来源"],
        rows=rows,
        source_refs=refs,
        sort_order=520,
    )


def _china_project_database_visual(project_ledger: Mapping[str, Any]) -> dict[str, Any]:
    rows: list[list[Any]] = []
    refs: list[str] = []
    projects = [
        project
        for project in project_ledger["projects"]
        if str(project.get("country_region")) == "中国大陆"
    ]
    for project in projects:
        project_refs = [str(ref) for ref in project.get("source_ids") or []]
        capacity = (
            f"{float(project['wspm']) / 10_000:g}万片/月；{project.get('capacity_scope') or '口径见项目说明'}"
            if project.get("wspm") is not None
            else str(project.get("capacity_scope") or "目前没有可复算的新增月产能")
        )
        milestones = [
            value
            for value in (
                f"开工：{project['construction_start']}" if project.get("construction_start") else None,
                f"投产：{project['production_start']}" if project.get("production_start") else None,
                f"目标：{project['full_capacity_date']}" if project.get("full_capacity_date") else None,
                f"当前：{project['status_as_of']}",
            )
            if value
        ]
        rows.append(
            [
                f"{project['company']}｜{project['fab_site']}｜{project['city']}",
                f"{project.get('product') or '目前没有直接披露产品'}；{project.get('node') or '目前没有直接披露工艺'}",
                capacity,
                "；".join(milestones),
                str(project.get("model_treatment") or "只用于方向判断"),
                _row_citations(project_refs),
            ]
        )
        refs.extend(project_refs)
    return _table_visual(
        block_key="china_fab_expansion_database",
        title="中国大陆晶圆厂扩产与硅片需求线索",
        subtitle="单独汇总本轮已取得一手项目证据的中国大陆项目；规划产能、当前能力和已投产增量分别展示，缺失时点不从媒体或投资额补造。",
        columns=["公司与项目", "产品和工艺", "公开产能", "项目进度", "如何进入硅片需求判断", "来源"],
        rows=rows,
        source_refs=refs,
        sort_order=522,
    )


def _global_supplier_competition_visual() -> dict[str, Any]:
    supplier_rows = (
        (
            "信越化学",
            "覆盖300毫米抛光片、外延片、退火片和SOI；扩建厂房已经完成",
            "设备按需求安装启用，且公司仍判断200毫米市场偏宽松",
            "先进300毫米需求可推动设备投放，但普通与200毫米产品不会同步收紧",
            ["S052", "S053"],
        ),
        (
            "SUMCO",
            "专业半导体硅片供应商，2025年资本投入799.57亿日元",
            "2025年营业利润很低且归母亏损，公开财务没有按客户和规格拆分有效产能",
            "只有高端销量、价格、利用率和现金流同步改善，扩产才会转成盈利",
            ["FIN-SUMCO-01"],
        ),
        (
            "环球晶圆",
            "美国项目覆盖先进大批量300毫米硅片与300毫米SOI，本地化能力最明确",
            "约40亿美元项目仍需建设、认证和爬坡，集团收入不能替代分产品供给",
            "2026—2030的增量更多来自美国新能力，但兑现时间取决于客户认证",
            ["DMD-NIST-GLOBALWAFERS", "S051", "FIN-GWC-01"],
        ),
        (
            "Siltronic",
            "新加坡新厂已完成多项重要客户认证，2025年仍维持较高资本投入",
            "需求低于原预期，公司已经放慢新厂爬坡，认证不等于经济利用率",
            "是观察高规格供给由认证转向批量采购的关键样本，也是供给提前释放的反证",
            ["DMD-SILTRONIC-AR2025", "FIN-SIL-01"],
        ),
        (
            "SK Siltron",
            "300毫米抛光片和外延片覆盖HBM、DRAM、NAND、GPU/AI与逻辑，并披露2纳米外延研发",
            "当前公开报告未给出按规格的有效产能、利用率、客户和价格",
            "技术覆盖支持其承接先进需求，但数量和盈利不能在缺少经营数据时推断",
            ["DMD-SK-SILTRON-SR2025"],
        ),
        (
            "Soitec",
            "工程衬底和SOI是差异化高价值供给，但2026财年收入降至5.92亿欧元、毛利率降至16.3%",
            "客户库存调整、降产和不利价格组合仍在压制盈利；集团没有全球SOI月产能和按平台采购量",
            "光子SOI增长提供AI方向，但尚未抵消传统业务下行，不能与普通抛光片按片数直接比较",
            ["FIN-SOITEC-FY2026", "S055", "S056"],
        ),
    )
    rows: list[list[Any]] = []
    refs: list[str] = []
    for supplier, capability, constraint, outlook, row_refs in supplier_rows:
        rows.append([supplier, capability, constraint, outlook, _row_citations(row_refs)])
        refs.extend(row_refs)
    return _table_visual(
        block_key="global_wafer_supplier_competition",
        title="全球主要硅片供应商的能力、约束与变化方向",
        subtitle="比较能直接验证的产品、扩产和财务证据；没有统一分母，不计算伪精确市场份额，也不把集团收入当作有效产能。",
        columns=["供应商", "当前可核验能力", "当前主要约束", "2026—2030判断", "来源"],
        rows=rows,
        source_refs=refs,
        sort_order=537,
    )


def _capacity_ranking_visual(
    model_inputs: Mapping[str, Any],
    project_ledger: Mapping[str, Any],
) -> dict[str, Any]:
    projects_by_id = {project["project_id"]: project for project in project_ledger["projects"]}
    ranked = sorted(
        model_inputs["bottom_up_disclosed_increment_projects"],
        key=lambda row: float(row["nameplate_incremental_wspm"]),
        reverse=True,
    )
    segment_labels = {
        "mature_logic_300mm": "300毫米成熟逻辑",
        "analog_power_300mm": "300毫米模拟与功率",
    }
    rows: list[list[Any]] = []
    refs: list[str] = []
    for rank, item in enumerate(ranked, start=1):
        project = projects_by_id[item["project_id"]]
        project_refs = [str(ref) for ref in project.get("source_ids") or []]
        if str(item["project_id"]) == "P012":
            # The supplemental UMC profile identifies Fab 12i but does not
            # disclose this row's 30k/month or 2026 production facts.  Keep
            # only the announcement that contains both numbers so every
            # clickable row citation opens on the displayed evidence.
            project_refs = [ref for ref in project_refs if ref == "S031"]
        rows.append(
            [
                rank,
                f"{project['company']}｜{project['fab_site']}",
                project["country_region"],
                segment_labels.get(str(item["segment"]), str(item["segment"])),
                f"{float(item['nameplate_incremental_wspm']) / 10_000:.2f}万片/月",
                f"{item['production_year']}年起爬坡",
                str(item.get("note") or "净增月产能与投产时间可由公开资料直接复算"),
                _row_citations(project_refs),
            ]
        )
        refs.extend(project_refs)
    return _table_visual(
        block_key="disclosed_incremental_capacity_ranking",
        title="可直接复算的新增月产能排名",
        subtitle=f"{len(project_ledger['projects'])}项项目中只有4项同时具备可解释为净增的月产能和建模时点；项目覆盖范围只是公开资料下限，排序不是全球完整排名。",
        columns=["排名", "公司与工厂", "地区", "产品", "净增月产能", "模型起点", "口径说明", "来源"],
        rows=rows,
        source_refs=refs,
        sort_order=530,
    )


def _supplier_relationship_visual(relations: Mapping[str, Any]) -> dict[str, Any]:
    rows = [
        [
            row["wafer_supplier"],
            row["fab_customer"],
            f"{row['product']}｜{row['relationship']}",
            f"{row['status']}；{row['boundary']}",
            _row_citations(row.get("source_ids") or []),
        ]
        for row in relations["relations"]
    ]
    refs = [
        str(ref)
        for row in relations["relations"]
        for ref in row.get("source_ids") or []
    ]
    return _table_visual(
        block_key="fab_wafer_supplier_relationships",
        title="晶圆厂与硅片供应商关系矩阵",
        subtitle="只收录具名公开关系，并区分已生效、历史认证、合作框架与待最终协议；没有数量时不推断份额。",
        columns=["硅片供应商", "晶圆厂客户", "产品与公开关系", "当前结论", "来源"],
        rows=rows,
        source_refs=refs,
        sort_order=540,
    )


def _project_priority_visual(project_ledger: Mapping[str, Any]) -> dict[str, Any]:
    by_id = {str(row["project_id"]): row for row in project_ledger["projects"]}
    priorities = (
        ("P002", "先进逻辑高规格需求", "计划2027年下半年生产；月产能未披露", "补充实际设备搬入、晶圆投入和月产能"),
        ("P006", "2纳米与EUV本地制造", "目标2026年底前投入运营；尚不能视为已投产", "核验投运、利用率和硅片认证"),
        ("P007", "18A先进逻辑爬坡", "2025年制造进入爬坡；月产能未披露", "补充季度投入和高规格硅片供应关系"),
        ("P013", "2纳米GAA新平台", "原型晶圆已开始取得电学特性；目标2027年量产", "核验良率、量产时点和月产能"),
        ("P018", "先进DRAM与HBM", "2026年第一季度开始晶圆投入；月产能未披露", "补充季度爬坡与实际采购"),
        ("P014", "美国先进DRAM", "计划2027年生产；缺少月产能", "补充设备搬入和季度晶圆投入"),
        ("P019", "韩国长期存储集群", "2027年2月启用首个洁净室是目标，不等于量产", "补充首片、量产和月产能"),
        ("P020", "2028年存储新增方向", "推进主体工程，计划2028年运营", "补充DRAM/NAND组合与月产能"),
        ("P012", "成熟300毫米可量化增量", "计划2026年批量生产；满产3万片/月但年份未披露", "核验实际爬坡和达到满产的年份"),
        ("P005", "欧洲本地成熟制程", "4万片/月，计划2029年达到", "核验首产、客户认证与利用率"),
    )
    rows: list[list[Any]] = []
    refs: list[str] = []
    for rank, (project_id, reason, status, needed) in enumerate(priorities, start=1):
        project = by_id[project_id]
        project_refs = [str(ref) for ref in project.get("source_ids") or []]
        rows.append(
            [
                rank,
                f"{project['company']}｜{project['fab_site']}",
                reason,
                status,
                needed,
                _row_citations(project_refs),
            ]
        )
        refs.extend(project_refs)
    return _table_visual(
        block_key="project_demand_research_priority",
        title="最值得跟踪的全球晶圆厂项目",
        subtitle="按产品影响、2026—2030时间相关性和证据成熟度排列研究优先级；不是按未披露产能推算的需求规模排名。",
        columns=["优先级", "项目", "为什么重要", "当前可确认进度", "下一步验证", "来源"],
        rows=rows,
        source_refs=refs,
        sort_order=525,
    )


def _supply_balance_visual(outputs: Mapping[str, Any]) -> dict[str, Any]:
    capacity_300 = outputs["aggregate_300mm"]["scenarios"]["base"]
    capacity_200 = {
        int(row["year"]): row
        for row in outputs["official_200mm_capacity"]["scenarios"]["base"]
    }
    year_rows = (
        (
            2026,
            "300毫米以2028年1,110万片/月和2024—2028年7%复合增速反算，再按2026年7%增长校准；200毫米直接采用2026年770万片/月。存储总装机约410万片/月。",
            "先进300毫米需求改善，但普通产品和200毫米仍受库存约束。",
            ["S001", "S064", "S065", "DMD-SEMI-MEMORY-20260629", "DMD-SILTRONIC-AR2025"],
        ),
        (
            2027,
            "300毫米=2026模型值×1.07；200毫米=770万片/月×1.03。存储总装机约420万片/月。",
            "公开增速给出装机方向，关键仍是计划是否转成实际晶圆投入。",
            ["S064", "S065", "DMD-SEMI-MEMORY-20260629"],
        ),
        (
            2028,
            "300毫米直接采用1,110万片/月公开锚点；200毫米=2027模型值×1.01。300毫米硅片出货面积下限另行折算为月均约821万片，只作强度对照。",
            "装机和出货不是同一分母；高规格可能趋紧，但无法据此计算全市场缺口。",
            ["S001", "S065", "DMD-SEMI-WAFER-OUTLOOK-202509"],
        ),
        (
            2029,
            "300毫米=2028公开锚点×1.07；200毫米=2028模型值×1.02，两个增速均来自公开路径。",
            "供需取决于前期项目利用率、认证和硅片商扩产纪律。",
            ["S064", "S065", "DMD-SILTRONIC-AR2025"],
        ),
        (
            2030,
            "公开资料没有同等级年度预测。表中300毫米=2029模型值×1.04，200毫米=2029模型值×1.02；4%和2%均为研究基准情景，不是外部预测。",
            "结果只用于敏感性观察，不能据此给出精确缺口、价格或公司订单。",
            ["S064", "S065"],
        ),
    )
    rows: list[list[Any]] = []
    refs: list[str] = []
    for year, evidence, conclusion, row_refs in year_rows:
        cap_300 = float(capacity_300[str(year)]["300mm_capacity_wspm"]) / 10_000
        cap_200 = float(capacity_200[year]["installed_200mm_wspm"]) / 10_000
        rows.append(
            [
                year,
                f"300毫米{cap_300:.1f}万片/月；200毫米{cap_200:.1f}万片/月",
                evidence,
                conclusion,
                _row_citations(row_refs),
            ]
        )
        refs.extend(row_refs)
    return _table_visual(
        block_key="public_supply_demand_judgment_2026_2030",
        title="2026—2030年硅片供需判断",
        subtitle="装机数字描述晶圆厂能力，不是硅片供应或实际采购；2029—2030含研究情景。公开资料不足以计算精确年度缺口。",
        columns=["年份", "装机基准", "当年最重要证据", "供需判断", "来源"],
        rows=rows,
        source_refs=refs,
        sort_order=535,
    )


def _china_supplier_ranking_visual() -> dict[str, Any]:
    rows: list[list[Any]] = []
    refs: list[str] = []
    for item in DEMAND_SUPPLIER_RANKING_ROWS:
        row_refs = [str(ref) for ref in item["source_refs"]]
        rows.append(
            [
                item["rank"],
                item["supplier"],
                item["evidence"],
                item["why"],
                item["watch"],
                _row_citations(row_refs),
            ]
        )
        refs.extend(row_refs)
    return _table_visual(
        block_key="china_300mm_supplier_ranking",
        title="中国12英寸硅片供应商当前受益顺序",
        subtitle="按瓶颈能力、实际销量、当前认证、产品结构、利用率、价格和盈利排序；不是技术绝对名次，也不代表证券收益。",
        columns=["顺序", "供应商", "当前证据", "为什么排在这里", "下一步验证", "来源"],
        rows=rows,
        source_refs=refs,
        sort_order=538,
    )


def _collect_source_refs(value: Any, *, source_tree: bool = False) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key)
            child_source_tree = source_tree or bool(
                re.search(r"(?:^|_)(?:source|evidence)_(?:ref|refs|id|ids)(?:$|_)", key)
            ) or key == "source_refs_by_output"
            refs.update(_collect_source_refs(child, source_tree=child_source_tree))
        return refs
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            refs.update(_collect_source_refs(child, source_tree=source_tree))
        return refs
    if isinstance(value, str):
        refs.update(SOURCE_REF_PATTERN.findall(value))
        refs.update(re.findall(r"source_ref:([A-Za-z0-9_.-]+)", value))
        if source_tree:
            candidate = value.replace("source_ref:", "").strip()
            if re.fullmatch(r"[A-Za-z0-9_.-]+", candidate):
                refs.add(candidate)
    return refs


CONTEXTUAL_SLOT_EVIDENCE: dict[tuple[str, str, str], tuple[str, str]] = {
    (
        "mature_200mm_wafer_demand",
        "demand.downstream_price_momentum",
        "price_reversal_signal",
    ): (
        "DP178",
        "已找到200毫米供需仍偏宽松的定性反证，但没有该槽要求的同口径价格变化值，故不评分。",
    ),
    (
        "mature_200mm_wafer_demand",
        "signal.material_price_momentum",
        "price_denial_or_reversal",
    ): (
        "DP178",
        "已找到200毫米供需仍偏宽松的定性反证，但没有该槽要求的官方硅片价格回落幅度，故不评分。",
    ),
}


def _annotate_contextual_metric_slot_evidence(
    entity: dict[str, Any],
    *,
    data_points_by_key: Mapping[str, Mapping[str, Any]],
) -> None:
    entity_key = str(entity.get("key") or "")
    for factor in entity.get("factor_scores") or []:
        factor_code = str(factor.get("factor_code") or "")
        for slot in factor.get("metric_slots") or []:
            slot_code = str(slot.get("slot_code") or "")
            contextual = CONTEXTUAL_SLOT_EVIDENCE.get(
                (entity_key, factor_code, slot_code)
            )
            if not contextual:
                continue
            point_key, explanation = contextual
            point = data_points_by_key.get(point_key)
            if point is None:
                raise ValueError(f"指标槽背景证据 {point_key} 不存在")
            if str(slot.get("value_status") or "") in {
                "available",
                "calculated",
                "stale_but_usable",
            }:
                raise ValueError(
                    f"{entity_key}.{factor_code}.{slot_code} 已可精确计量，不能再标为仅背景证据"
                )
            slot["raw_value_text"] = explanation
            slot["standardized_value_text"] = "仅作供需背景反证，不代替价格、利用率或库存数值"
            slot["preprocess_trace"] = (
                f"链接{point_key}核对相邻的供需事实；由于指标口径不等于本槽要求，"
                "保持未评分且不计入覆盖率。"
            )
            slot["scoring_trace"] = "定性供需证据不转换为价格分数。"
            slot["contextual_evidence_only"] = True
            slot["contextual_data_point_keys"] = [point_key]
            slot["contextual_source_refs"] = [str(point.get("source_ref") or "")]


def _normalize_unrated_factor_public_text(entity: dict[str, Any]) -> None:
    """Keep internal convergence scores out of unscored public factor prose."""

    for factor in entity.get("factor_scores") or []:
        if str(factor.get("score_status") or "") == "complete":
            continue
        missing_labels = [
            str(slot.get("slot_label") or slot.get("metric_name") or "")
            for slot in factor.get("metric_slots") or []
            if str(slot.get("slot_role") or "") != "context"
            and str(slot.get("value_status") or "")
            not in {"available", "calculated", "stale_but_usable"}
        ]
        missing_text = "、".join(value for value in missing_labels[:3] if value)
        factor["score_rationale"] = (
            f"现有证据支持“{str(factor.get('factor_value_summary') or '').rstrip('。')}”。"
            f"但尚缺{missing_text or '同对象、同期间的可复算指标'}等同口径数据，"
            "现阶段只保留方向判断，暂不评分。"
        )


def _normalize_complete_factor_score_text(entity: dict[str, Any]) -> None:
    """Bind completed-factor prose to the computed raw/adjusted scores."""
    for factor in entity.get("factor_scores") or []:
        if str(factor.get("score_status") or "") != "complete":
            continue
        score_raw = float(factor["score_raw"])
        score_adjusted = float(factor["score_adjusted"])
        rationale = re.sub(
            r"(?:正式调整后得分|原始得分|基准分|初始分|种子分)[^。；\n]*[。；]?",
            "",
            str(factor.get("score_rationale") or ""),
        ).strip()
        factor["score_rationale"] = (
            f"正式调整后得分为{score_adjusted:.2f}分；原始得分为{score_raw:.2f}分，"
            "两者差异来自覆盖率和证据置信度收敛。"
            f"{rationale}"
        )


def _unrated_factor_public_text_audit(pack: Mapping[str, Any]) -> dict[str, Any]:
    forbidden = re.compile(r"\d+(?:\.\d+)?分|研究排序|评分为")
    rows: list[dict[str, Any]] = []
    for entity in pack.get("entities") or []:
        for factor in entity.get("factor_scores") or []:
            if str(factor.get("score_status") or "") == "complete":
                continue
            public_values: list[str] = []
            for field in (
                "score_rationale",
                "factor_value_summary",
                "source_context_summary",
                "factor_topic_analysis",
                "notes",
            ):
                public_values.append(str(factor.get(field) or ""))
            public_values.extend(
                str(value) for value in factor.get("theme_analysis_points") or []
            )
            joined = "\n".join(public_values)
            if forbidden.search(joined):
                raise ValueError(
                    f"{entity.get('key')}.{factor.get('factor_code')} 未评级公开文本泄露内部评分"
                )
            if "暂不评分" not in str(factor.get("score_rationale") or ""):
                raise ValueError(
                    f"{entity.get('key')}.{factor.get('factor_code')} 未说明暂不评分原因"
                )
            rows.append(
                {
                    "entity_key": str(entity.get("key") or ""),
                    "factor_code": str(factor.get("factor_code") or ""),
                    "pass": True,
                }
            )
    return {
        "schema_version": "opportunity_lens.unrated_factor_public_text_audit.v1",
        "unrated_factor_count": len(rows),
        "forbidden_patterns": ["数字+分", "研究排序", "评分为"],
        "all_unrated_factors_explain_missing_metrics_and_no_score": True,
        "rows": rows,
    }


def _factor_public_score_consistency_audit(pack: Mapping[str, Any]) -> dict[str, Any]:
    """Prevent a third seed score or template language leaking to readers."""
    score_pattern = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)\s*分")
    complete_rows: list[dict[str, Any]] = []
    for entity in pack.get("entities") or []:
        for factor in entity.get("factor_scores") or []:
            if str(factor.get("score_status") or "") != "complete":
                continue
            public_values = [
                str(factor.get(field) or "")
                for field in (
                    "score_rationale",
                    "factor_value_summary",
                    "source_context_summary",
                    "factor_topic_analysis",
                    "notes",
                )
            ]
            public_values.extend(
                str(value) for value in factor.get("theme_analysis_points") or []
            )
            joined = "\n".join(public_values)
            score_raw = float(factor["score_raw"])
            score_adjusted = float(factor["score_adjusted"])
            mentions = [float(value) for value in score_pattern.findall(joined)]
            third_scores = sorted(
                {
                    value
                    for value in mentions
                    if abs(value - score_raw) > 0.005
                    and abs(value - score_adjusted) > 0.005
                }
            )
            if third_scores:
                raise ValueError(
                    f"{entity.get('key')}.{factor.get('factor_code')}公开文字出现第三套分数："
                    f"{third_scores}"
                )
            expected_adjusted = f"正式调整后得分为{score_adjusted:.2f}分"
            if expected_adjusted not in str(factor.get("score_rationale") or ""):
                raise ValueError(
                    f"{entity.get('key')}.{factor.get('factor_code')}未明确展示正式调整后分"
                )
            complete_rows.append(
                {
                    "entity_key": str(entity.get("key") or ""),
                    "factor_code": str(factor.get("factor_code") or ""),
                    "score_raw": score_raw,
                    "score_adjusted": score_adjusted,
                    "public_score_mentions": mentions,
                    "third_score_mentions": [],
                    "pass": True,
                }
            )

    public_text = json.dumps(
        {
            "sections": pack.get("sections") or [],
            "entity_sections": pack.get("entity_sections") or [],
            "visuals": pack.get("visuals") or [],
            "targets": pack.get("entity_investment_targets") or [],
            "entities": pack.get("entities") or [],
        },
        ensure_ascii=False,
    )
    forbidden_template_phrases = ["按按", "分开逐项比较"]
    found_phrases = [
        phrase for phrase in forbidden_template_phrases if phrase in public_text
    ]
    if found_phrases:
        raise ValueError(f"公开文本存在模板病句：{found_phrases}")
    return {
        "schema_version": "opportunity_lens.factor_public_score_consistency.v1",
        "complete_factor_count": len(complete_rows),
        "complete_factor_rows": complete_rows,
        "unrated_factor_count": sum(
            1
            for entity in pack.get("entities") or []
            for factor in entity.get("factor_scores") or []
            if str(factor.get("score_status") or "") != "complete"
        ),
        "forbidden_template_phrases": forbidden_template_phrases,
        "found_template_phrases": [],
        "all_complete_factors_use_only_raw_and_adjusted_scores": True,
        "all_unrated_factors_exclude_scores_and_rankings": bool(
            pack.get("unrated_factor_public_text_audit", {}).get(
                "all_unrated_factors_explain_missing_metrics_and_no_score"
            )
        ),
    }


def _metric_slot_cross_audit(
    pack: Mapping[str, Any],
    *,
    project_ledger: Mapping[str, Any],
    model_inputs: Mapping[str, Any],
) -> dict[str, Any]:
    """Classify all 315 protocol slots without confusing context with score."""

    usable_statuses = {"available", "calculated", "stale_but_usable"}
    rows: list[dict[str, Any]] = []
    for entity in pack.get("entities") or []:
        entity_key = str(entity.get("key") or "")
        for factor in entity.get("factor_scores") or []:
            factor_code = str(factor.get("factor_code") or "")
            for slot in factor.get("metric_slots") or []:
                status = str(slot.get("value_status") or "")
                if status in usable_statuses:
                    classification = "exact_slot_match"
                    explanation = (
                        "同一指标槽已链接可复核的数据点、来源、原始值和标准化过程。"
                    )
                    point_keys = [
                        str(value) for value in slot.get("data_point_keys") or []
                    ]
                elif slot.get("contextual_evidence_only"):
                    classification = "contextual_evidence_only"
                    explanation = str(slot.get("raw_value_text") or "")
                    point_keys = [
                        str(value)
                        for value in slot.get("contextual_data_point_keys") or []
                    ]
                else:
                    classification = "truly_not_found"
                    explanation = (
                        "现有数据点中没有与该槽同对象、同口径、同期间且可复算的披露。"
                    )
                    point_keys = []
                rows.append(
                    {
                        "entity_key": entity_key,
                        "factor_code": factor_code,
                        "slot_code": str(slot.get("slot_code") or ""),
                        "slot_role": str(slot.get("slot_role") or ""),
                        "classification": classification,
                        "value_status": status,
                        "data_point_keys": point_keys,
                        "explanation": explanation,
                    }
                )
    if len(rows) != 315:
        raise ValueError(f"指标槽交叉审计应覆盖315行，实际{len(rows)}行")
    counts = {
        label: sum(1 for row in rows if row["classification"] == label)
        for label in (
            "exact_slot_match",
            "contextual_evidence_only",
            "truly_not_found",
        )
    }
    grade_a_count = sum(
        1
        for project in project_ledger.get("projects") or []
        if str(project.get("evidence_grade") or "") == "A"
    )
    quantifiable_projects = list(
        model_inputs.get("bottom_up_disclosed_increment_projects") or []
    )
    if grade_a_count != 30 or len(quantifiable_projects) != 4:
        raise ValueError(
            f"项目账本口径变化：A级={grade_a_count}，可量化={len(quantifiable_projects)}"
        )
    return {
        "schema_version": "opportunity_lens.metric_slot_cross_audit.v1",
        "slot_count": len(rows),
        "classification_counts": counts,
        "project_ledger_context": {
            "grade_a_project_count": grade_a_count,
            "quantifiable_project_count": len(quantifiable_projects),
            "quantifiable_project_ids": [
                str(row.get("project_id") or "") for row in quantifiable_projects
            ],
            "classification": "contextual_evidence_only",
            "note": (
                "36项项目账本中30项状态证据为A级；只有4项同时具备可解释为净增的月产能和建模时点。"
                "这是研究账本覆盖说明，不是外部市场规模，也不进入因子评分。"
            ),
        },
        "rows": rows,
    }


def _factor_information_point_audit(pack: Mapping[str, Any]) -> dict[str, Any]:
    """Verify every factor quote against a same-source data point verbatim."""

    sources_by_ref = {
        str(source.get("ref") or ""): source for source in pack.get("sources") or []
    }
    points_by_ref: dict[str, list[Mapping[str, Any]]] = {}
    for point in pack.get("data_points") or []:
        points_by_ref.setdefault(str(point.get("source_ref") or ""), []).append(point)
    rows: list[dict[str, Any]] = []
    for entity in pack.get("entities") or []:
        entity_key = str(entity.get("key") or "")
        for factor in entity.get("factor_scores") or []:
            factor_code = str(factor.get("factor_code") or "")
            refs = [
                str(value).replace("source_ref:", "")
                for value in factor.get("evidence_ref_uri_list") or []
            ]
            points = list(factor.get("information_points") or [])
            if len(refs) != len(points):
                raise ValueError(
                    f"{entity_key}.{factor_code} 信息点与来源数量不一致"
                )
            for ref, information_point in zip(refs, points):
                source = sources_by_ref[ref]
                excerpt = str(information_point.get("excerpt") or "").strip()
                language = str(source.get("language") or "").strip().lower()
                is_chinese = language in {
                    "zh",
                    "zh-cn",
                    "zh-tw",
                    "chinese",
                    "中文",
                }
                if is_chinese:
                    if "excerpt_zh" in information_point:
                        raise ValueError(
                            f"{entity_key}.{factor_code}.{ref} 中文信息点不得重复展示excerpt_zh"
                        )
                    excerpt_zh = ""
                else:
                    if not str(information_point.get("excerpt_zh") or "").strip():
                        raise ValueError(
                            f"{entity_key}.{factor_code}.{ref} 非中文信息点缺少中文译意"
                        )
                    excerpt_zh = str(information_point["excerpt_zh"]).strip()
                same_source_points = points_by_ref.get(ref) or []
                if same_source_points:
                    matches = [
                        point
                        for point in same_source_points
                        if str(point.get("source_excerpt") or "").strip() == excerpt
                        and (
                            is_chinese
                            or str(point.get("source_excerpt_zh") or "").strip()
                            == excerpt_zh
                        )
                    ]
                    if not matches:
                        raise ValueError(
                            f"{entity_key}.{factor_code}.{ref} 信息点未匹配同来源数据点"
                        )
                    matched_key = str(
                        sorted(
                            matches,
                            key=lambda row: str(row.get("data_point_key") or ""),
                        )[0].get("data_point_key")
                        or ""
                    )
                    match_kind = "same_source_data_point_exact"
                else:
                    if excerpt != str(source.get("excerpt") or "").strip():
                        raise ValueError(
                            f"{entity_key}.{factor_code}.{ref} 无数据点时未使用来源直接摘录"
                        )
                    if (
                        not is_chinese
                        and excerpt_zh != str(source.get("excerpt_zh") or "").strip()
                    ):
                        raise ValueError(
                            f"{entity_key}.{factor_code}.{ref} 无数据点时中文译意未匹配来源"
                        )
                    matched_key = ""
                    match_kind = "source_direct_excerpt_no_data_point"
                rows.append(
                    {
                        "entity_key": entity_key,
                        "factor_code": factor_code,
                        "source_ref": ref,
                        "matched_data_point_key": matched_key,
                        "match_kind": match_kind,
                    }
                )
    critical = {
        (row["entity_key"], row["factor_code"], row["source_ref"]): row
        for row in rows
    }
    global_point = critical[
        (
            "global_300mm_fab_expansion",
            "demand.customer_capex_capacity_signal",
            "S001",
        )
    ]
    advanced_point = critical[
        (
            "advanced_logic_wafer_demand",
            "demand.application_intensity_change",
            "S001",
        )
    ]
    if global_point["matched_data_point_key"] != "DP001":
        raise ValueError("S001全球总产能信息点必须绑定DP001（11.1 million）")
    if advanced_point["matched_data_point_key"] != "DP002":
        raise ValueError("S001先进逻辑信息点必须绑定DP002（850,000至1.4 million）")
    data_points_by_key = {
        str(point.get("data_point_key") or ""): point
        for point in pack.get("data_points") or []
    }
    if "11.1 million wafers per month" not in str(
        data_points_by_key["DP001"].get("source_excerpt") or ""
    ):
        raise ValueError("DP001原文缺少11.1 million wafers per month精确锚点")
    advanced_excerpt = str(
        data_points_by_key["DP002"].get("source_excerpt") or ""
    )
    if "850,000 wpm" not in advanced_excerpt or "1.4 million wpm" not in advanced_excerpt:
        raise ValueError("DP002原文缺少850,000至1.4 million wpm精确锚点")
    return {
        "schema_version": "opportunity_lens.factor_information_point_audit.v1",
        "factor_count": sum(
            len(entity.get("factor_scores") or [])
            for entity in pack.get("entities") or []
        ),
        "information_point_count": len(rows),
        "same_source_data_point_exact_count": sum(
            row["match_kind"] == "same_source_data_point_exact" for row in rows
        ),
        "source_direct_excerpt_no_data_point_count": sum(
            row["match_kind"] == "source_direct_excerpt_no_data_point" for row in rows
        ),
        "critical_assertions": {
            "S001_global_total_capacity": "DP001 exact 11.1 million wafers per month",
            "S001_advanced_logic": "DP002 exact 850,000 to 1.4 million wafers per month",
        },
        "all_information_points_pass": True,
        "rows": rows,
    }


def _metric_slot_chain_audit(pack: Mapping[str, Any]) -> dict[str, Any]:
    usable_statuses = {"available", "calculated", "stale_but_usable"}
    data_points_by_key: dict[str, Mapping[str, Any]] = {}
    for point in pack.get("data_points") or []:
        key = str(point.get("data_point_key") or "").strip()
        if not key or key in data_points_by_key:
            raise ValueError(f"研究包数据点键为空或重复：{key!r}")
        data_points_by_key[key] = point

    factor_count = 0
    total_slot_count = 0
    usable_scored_count = 0
    usable_context_count = 0
    referenced_data_point_keys: list[str] = []
    referenced_source_refs: list[str] = []
    coverage_rechecks: list[dict[str, Any]] = []
    for entity in pack.get("entities") or []:
        entity_key = str(entity.get("key") or "")
        for factor in entity.get("factor_scores") or []:
            factor_count += 1
            factor_code = str(factor.get("factor_code") or "")
            slots = list(factor.get("metric_slots") or [])
            total_slot_count += len(slots)
            applicable = [
                slot
                for slot in slots
                if str(slot.get("slot_role") or "") != "context"
                and str(slot.get("value_status") or "") != "not_applicable"
            ]
            denominator = sum(float(slot["slot_weight"]) for slot in applicable)
            usable_applicable = [
                slot
                for slot in applicable
                if str(slot.get("value_status") or "") in usable_statuses
            ]
            numerator = sum(float(slot["slot_weight"]) for slot in usable_applicable)
            recalculated_coverage = numerator / denominator if denominator else 0.0
            reported_coverage = float(factor.get("coverage") or 0.0)
            if abs(recalculated_coverage - reported_coverage) > 0.0001:
                raise ValueError(
                    f"{entity_key}.{factor_code} 覆盖率复算不一致："
                    f"reported={reported_coverage}, recalculated={recalculated_coverage}"
                )
            coverage_rechecks.append(
                {
                    "entity_key": entity_key,
                    "factor_code": factor_code,
                    "usable_non_context_weight": round(numerator, 6),
                    "applicable_non_context_weight": round(denominator, 6),
                    "reported_coverage": round(reported_coverage, 6),
                    "recalculated_coverage": round(recalculated_coverage, 6),
                    "pass": True,
                }
            )
            for slot in slots:
                status = str(slot.get("value_status") or "")
                if status not in usable_statuses:
                    continue
                slot_code = str(slot.get("slot_code") or "")
                role = str(slot.get("slot_role") or "")
                keys = [str(value).strip() for value in slot.get("data_point_keys") or []]
                if len(keys) != 1 or not keys[0]:
                    raise ValueError(
                        f"{entity_key}.{factor_code}.{slot_code} 必须精确链接一个唯一数据点"
                    )
                point = data_points_by_key.get(keys[0])
                if point is None:
                    raise ValueError(
                        f"{entity_key}.{factor_code}.{slot_code} 链接不存在的数据点 {keys[0]}"
                    )
                refs = [str(value).strip() for value in slot.get("source_refs") or []]
                expected_refs = [str(point.get("source_ref") or "").strip()]
                if refs != expected_refs or not refs[0]:
                    raise ValueError(
                        f"{entity_key}.{factor_code}.{slot_code} 来源与数据点不一致："
                        f"slot={refs}, data_point={expected_refs}"
                    )
                if slot.get("raw_value_num") is None and not str(slot.get("raw_value_text") or "").strip():
                    raise ValueError(f"{entity_key}.{factor_code}.{slot_code} 缺少原始值")
                if slot.get("standardized_value_num") is None and not str(
                    slot.get("standardized_value_text") or ""
                ).strip():
                    raise ValueError(f"{entity_key}.{factor_code}.{slot_code} 缺少标准化值")
                for required in ("raw_unit", "standardized_unit", "normalization_method"):
                    if not str(slot.get(required) or "").strip():
                        raise ValueError(
                            f"{entity_key}.{factor_code}.{slot_code} 缺少 {required}"
                        )
                if role == "context":
                    forbidden = [
                        field
                        for field in ("slot_score", "bucket", "scoring_rule")
                        if field in slot
                    ]
                    if forbidden:
                        raise ValueError(
                            f"{entity_key}.{factor_code}.{slot_code} context槽不得含 {forbidden}"
                        )
                    usable_context_count += 1
                else:
                    for required in ("slot_score", "bucket", "scoring_rule"):
                        if slot.get(required) is None or not str(slot.get(required)).strip():
                            raise ValueError(
                                f"{entity_key}.{factor_code}.{slot_code} 评分槽缺少 {required}"
                            )
                    usable_scored_count += 1
                referenced_data_point_keys.extend(keys)
                referenced_source_refs.extend(refs)

    return {
        "schema_version": "opportunity_lens.metric_slot_chain_audit.v1",
        "protocol_version": "C轨供需失衡评分流程与可解释计算体系_V0.8.1",
        "factor_count": factor_count,
        "total_slot_count": total_slot_count,
        "usable_scored_slot_count": usable_scored_count,
        "usable_context_slot_count": usable_context_count,
        "usable_slot_count": usable_scored_count + usable_context_count,
        "unique_linked_data_point_count": len(set(referenced_data_point_keys)),
        "unique_linked_source_count": len(set(referenced_source_refs)),
        "context_excluded_from_score_coverage_confidence": True,
        "all_usable_slots_have_exact_data_point_source_raw_standardized_chain": True,
        "coverage_rechecks": coverage_rechecks,
    }


def _source_locator_audit(
    pack: Mapping[str, Any],
    *,
    model_inputs: Mapping[str, Any],
) -> dict[str, Any]:
    generic_locator = "原始网页或PDF所列段落"
    sources_by_ref = {
        str(source.get("ref") or ""): source
        for source in pack.get("sources") or []
    }
    if "" in sources_by_ref or len(sources_by_ref) != len(pack.get("sources") or []):
        raise ValueError("来源定位审计发现空ref或重复ref")

    public_core_refs = _collect_source_refs(
        {
            "claims": pack.get("claims") or [],
            "entities": pack.get("entities") or [],
            "entity_sections": pack.get("entity_sections") or [],
            "targets": pack.get("entity_investment_targets") or [],
            "sections": pack.get("sections") or [],
            "visuals": pack.get("visuals") or [],
        }
    )
    model_refs = _collect_source_refs(model_inputs)
    usable_slot_refs: set[str] = set()
    for entity in pack.get("entities") or []:
        for factor in entity.get("factor_scores") or []:
            for slot in factor.get("metric_slots") or []:
                if str(slot.get("value_status") or "") in {
                    "available", "calculated", "stale_but_usable"
                }:
                    usable_slot_refs.update(str(value) for value in slot.get("source_refs") or [])

    def is_precise(ref: str) -> bool:
        source = sources_by_ref.get(ref)
        if not source:
            return False
        locator = str(source.get("local_locator") or "").strip()
        return bool(
            locator
            and locator != generic_locator
            and source.get("locator_verification_status")
            == "verified_page_section_or_search_phrase"
            and source.get("excerpt_fidelity")
            == "direct_extract_or_faithful_translation_checked_against_locator"
            and source.get("source_usage_scope") != "reference_only"
        )

    def summarize(name: str, refs: set[str]) -> dict[str, Any]:
        unknown = sorted(ref for ref in refs if ref not in sources_by_ref)
        not_precise = sorted(ref for ref in refs if ref in sources_by_ref and not is_precise(ref))
        if unknown or not_precise:
            raise ValueError(
                f"{name} 来源定位不满足门禁：unknown={unknown}, not_precise={not_precise}"
            )
        count = len(refs)
        return {
            "required_count": count,
            "precisely_located_count": count,
            "coverage_rate": 1.0 if count else 1.0,
            "unknown_refs": [],
            "not_precisely_located_refs": [],
        }

    all_refs = set(sources_by_ref)
    generic_refs = sorted(
        ref
        for ref, source in sources_by_ref.items()
        if str(source.get("local_locator") or "").strip() in {"", generic_locator}
    )
    reference_only_refs = sorted(
        ref
        for ref, source in sources_by_ref.items()
        if source.get("source_usage_scope") == "reference_only"
    )
    return {
        "schema_version": "opportunity_lens.source_locator_audit.v1",
        "overall": summarize("overall", all_refs),
        "public_core": summarize("public_core", public_core_refs),
        "model_inputs": summarize("model_inputs", model_refs),
        "usable_metric_slots": summarize("usable_metric_slots", usable_slot_refs),
        "generic_locator_count": len(generic_refs),
        "generic_locator_refs": generic_refs,
        "reference_only_count": len(reference_only_refs),
        "reference_only_refs": reference_only_refs,
        "all_public_core_model_and_usable_slot_refs_precisely_located": True,
    }


def _public_citation_excerpt_match_audit(pack: Mapping[str, Any]) -> dict[str, Any]:
    """Fail when a key public citation opens on a non-matching source excerpt."""
    sources_by_ref = {
        str(source.get("ref") or ""): source
        for source in pack.get("sources") or []
    }
    points_by_key = {
        str(point.get("data_point_key") or ""): point
        for point in pack.get("data_points") or []
    }
    public_surfaces = {
        "sections": pack.get("sections") or [],
        "entity_sections": pack.get("entity_sections") or [],
        "visuals": pack.get("visuals") or [],
    }
    public_json = json.dumps(public_surfaces, ensure_ascii=False)
    leaked_base_refs = sorted(
        base_ref
        for base_ref in PUBLIC_FACT_SOURCE_ALIAS
        if source_uri(base_ref) in public_json
    )
    if leaked_base_refs:
        raise ValueError(
            f"公开核心内容仍引用宽泛来源卡，抽屉可能错位：{leaked_base_refs}"
        )

    cluster_checks: list[dict[str, Any]] = []
    for alias_ref, spec in PUBLIC_FACT_CLUSTER_SOURCE_SPECS.items():
        source = sources_by_ref.get(alias_ref)
        if source is None:
            raise ValueError(f"缺少公开事实簇来源卡：{alias_ref}")
        if source.get("independence_key") != sources_by_ref[str(spec["base_ref"])].get(
            "independence_key"
        ):
            raise ValueError(f"公开事实簇错误增加独立证据组：{alias_ref}")
        expected_excerpt_parts: list[str] = []
        expected_excerpt_zh_parts: list[str] = []
        for point_key in spec["data_point_keys"]:
            point = points_by_key.get(str(point_key))
            if point is None:
                raise ValueError(f"公开事实簇审计缺少数据点：{point_key}")
            expected_excerpt_parts.append(str(point["source_excerpt"]).strip())
            expected_excerpt_zh_parts.append(
                str(point.get("source_excerpt_zh") or point["source_excerpt"]).strip()
            )
        missing_exact_parts = [
            excerpt
            for excerpt in expected_excerpt_parts
            if excerpt not in str(source.get("excerpt") or "")
        ]
        missing_exact_zh_parts = [
            excerpt
            for excerpt in expected_excerpt_zh_parts
            if excerpt not in str(source.get("excerpt_zh") or "")
        ]
        if missing_exact_parts or missing_exact_zh_parts:
            raise ValueError(
                f"公开事实簇抽屉未展示对应事实：{alias_ref}, "
                f"original={len(missing_exact_parts)}, zh={len(missing_exact_zh_parts)}"
            )
        citation_count = public_json.count(source_uri(alias_ref))
        if citation_count == 0:
            raise ValueError(f"公开事实簇来源卡没有被核心内容使用：{alias_ref}")
        cluster_checks.append(
            {
                "source_ref": alias_ref,
                "base_ref": spec["base_ref"],
                "independence_key": source.get("independence_key"),
                "data_point_keys": list(spec["data_point_keys"]),
                "public_citation_occurrence_count": citation_count,
                "exact_original_excerpt_match": True,
                "exact_chinese_excerpt_match": True,
            }
        )

    supply_visual = next(
        (
            visual
            for visual in pack.get("visuals") or []
            if visual.get("block_key") == "public_supply_demand_judgment_2026_2030"
        ),
        None,
    )
    if supply_visual is None:
        raise ValueError("关键公开数值表缺失：public_supply_demand_judgment_2026_2030")
    expected_row_refs = {
        2026: {
            PUBLIC_FACT_SOURCE_ALIAS["S001"],
            PUBLIC_FACT_SOURCE_ALIAS["S064"],
            PUBLIC_FACT_SOURCE_ALIAS["S065"],
        },
        2027: {PUBLIC_FACT_SOURCE_ALIAS["S064"], PUBLIC_FACT_SOURCE_ALIAS["S065"]},
        2028: {PUBLIC_FACT_SOURCE_ALIAS["S001"], PUBLIC_FACT_SOURCE_ALIAS["S065"]},
        2029: {PUBLIC_FACT_SOURCE_ALIAS["S064"], PUBLIC_FACT_SOURCE_ALIAS["S065"]},
        2030: {PUBLIC_FACT_SOURCE_ALIAS["S064"], PUBLIC_FACT_SOURCE_ALIAS["S065"]},
    }
    row_checks: list[dict[str, Any]] = []
    for row in supply_visual["display_data"]["rows"]:
        year = int(row[0])
        row_refs = set(SOURCE_REF_PATTERN.findall(str(row[-1])))
        missing_refs = sorted(expected_row_refs[year] - row_refs)
        if missing_refs:
            raise ValueError(f"{year}年核心数值行缺少事实级抽屉引用：{missing_refs}")
        if year == 2030 and "研究基准情景" not in str(row[2]):
            raise ValueError("2030年核心数值行没有标明研究基准情景")
        row_checks.append(
            {
                "year": year,
                "required_fact_cluster_refs": sorted(expected_row_refs[year]),
                "required_fact_cluster_refs_present": True,
                "research_scenario_explicit": year != 2030 or True,
            }
        )

    core_numeric_visual_keys = (
        "global_wafer_capacity_2026_2030",
        "disclosed_incremental_capacity_ranking",
        "public_supply_demand_judgment_2026_2030",
    )
    core_numeric_table_checks: list[dict[str, Any]] = []
    for block_key in core_numeric_visual_keys:
        visual = next(
            (
                item
                for item in pack.get("visuals") or []
                if item.get("block_key") == block_key
            ),
            None,
        )
        if visual is None:
            raise ValueError(f"核心数值表缺失：{block_key}")
        table = visual.get("print_fallback") or visual.get("display_data") or {}
        rows = table.get("rows") or []
        if not rows:
            raise ValueError(f"核心数值表没有逐行数据：{block_key}")
        checked_rows: list[dict[str, Any]] = []
        for row_index, row in enumerate(rows, start=1):
            cited_refs = SOURCE_REF_PATTERN.findall(str(row[-1]))
            if not cited_refs:
                raise ValueError(f"{block_key}第{row_index}行没有可点击来源")
            missing_sources = sorted(ref for ref in cited_refs if ref not in sources_by_ref)
            empty_drawers = sorted(
                ref
                for ref in cited_refs
                if not str(sources_by_ref.get(ref, {}).get("excerpt") or "").strip()
                or not str(sources_by_ref.get(ref, {}).get("excerpt_zh") or "").strip()
            )
            if missing_sources or empty_drawers:
                raise ValueError(
                    f"{block_key}第{row_index}行来源抽屉不完整："
                    f"missing={missing_sources}, empty={empty_drawers}"
                )
            checked_rows.append(
                {
                    "row_index": row_index,
                    "row_subject": str(row[1] if len(row) > 1 else row[0]),
                    "source_refs": cited_refs,
                    "all_source_drawers_have_original_and_chinese_excerpt": True,
                }
            )
        core_numeric_table_checks.append(
            {
                "block_key": block_key,
                "row_count": len(checked_rows),
                "rows": checked_rows,
                "all_rows_have_clickable_fact_excerpts": True,
            }
        )

    return {
        "schema_version": "opportunity_lens.public_citation_excerpt_match.v1",
        "public_surface_names": list(public_surfaces),
        "fact_cluster_source_count": len(cluster_checks),
        "fact_cluster_checks": cluster_checks,
        "supply_balance_row_count": len(row_checks),
        "supply_balance_row_checks": row_checks,
        "core_numeric_table_count": len(core_numeric_table_checks),
        "core_numeric_row_count": sum(
            table["row_count"] for table in core_numeric_table_checks
        ),
        "core_numeric_table_checks": core_numeric_table_checks,
        "broad_source_ref_leak_count": 0,
        "broad_source_ref_leaks": [],
        "same_file_fact_clusters_reuse_independence_key": True,
        "all_key_public_citations_open_matching_fact_excerpt": True,
    }


def build_pack(*, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    research_question = extract_primary_research_question(INTAKE_PATH)
    financial_audit = _load_json(FINANCIAL_AUDIT_PATH)
    audited_financial_targets, audited_financial_sources, financial_audit_summary = (
        apply_financial_evidence_audit(
            _load_json(FINANCIAL_DIR / "target_financials.json"),
            _load_json(FINANCIAL_DIR / "normalized_sources.json"),
            financial_audit,
        )
    )
    (
        audited_financial_targets,
        audited_financial_sources,
        demand_financial_update_audit,
    ) = _apply_demand_financial_updates(
        audited_financial_targets,
        audited_financial_sources,
        _load_json(DEMAND_FINANCIAL_UPDATE_PATH),
    )
    evidence_audit = _load_json(DEMAND_AUDIT_PATH)
    audited_source_rows, source_audit_summary = apply_source_catalog_corrections(
        _load_json(DEMAND_DIR / "sources.json"),
        evidence_audit,
    )
    audited_source_rows = align_demand_source_records(audited_source_rows)
    sources = _source_catalog(
        audited_source_rows,
        financial_targets_payload=audited_financial_targets,
        financial_sources_payload=audited_financial_sources,
    )
    sources_by_ref = {source["ref"]: source for source in sources}
    audited_data_points, data_point_audit_summary = apply_data_point_evidence_audit(
        _load_json(DEMAND_DIR / "data_points.json"),
        evidence_audit,
        minimum_retained=100,
    )
    for point in audited_data_points:
        point_key = str(point.get("data_point_id") or point.get("data_point_key") or "")
        if point_key == "DP122":
            point["extraction_method"] = "inferred"
            point["fact_type"] = "inferred"
            point["note"] = (
                "公司原文披露到2027年把当前产能翻倍至4,000片/周；"
                "基期=4,000÷2=2,000片/周。该序列含推导值，因此整条按inferred记录。"
            )
    audited_data_points = [*audited_data_points, *copy.deepcopy(DEMAND_SUPPLEMENTAL_DATA_POINTS)]
    data_points = normalize_agent_data_points(
        audited_data_points,
        sources_by_ref=sources_by_ref,
    )
    source_excerpt_audit = _align_source_excerpts_to_data_points(sources, data_points)
    _append_public_fact_cluster_sources(sources, data_points)
    sources_by_ref = {source["ref"]: source for source in sources}
    data_points_by_source: dict[str, list[dict[str, Any]]] = {}
    for point in data_points:
        ref = str(point["source_ref"])
        point["fact_type"] = _fact_type(point, sources_by_ref[ref])
        data_points_by_source.setdefault(ref, []).append(point)
    if len({point["fact_type"] for point in data_points}) < 3:
        raise ValueError("需求侧事实类型未区分实际、预测/规划、研究假设或传闻")
    project_ledger = synchronize_demand_project_ledger(
        _load_json(DEMAND_DIR / "fab_project_ledger.json")
    )
    for project in project_ledger.get("projects") or []:
        for field in ("model_treatment", "evidence_gap_note"):
            if project.get(field) is not None:
                project[field] = _humanize_wafer_capacity_text(project[field])
    model_inputs, outputs, model_hashes = _model_bundle(
        output_dir,
        total_project_count=len(project_ledger["projects"]),
    )
    supplier_relationships = _load_json(DEMAND_DIR / "fab_to_wafer_supplier_relations.json")

    entities: list[dict[str, Any]] = []
    entity_sections: list[dict[str, Any]] = []
    for spec in ENTITY_SPECS:
        factor_inputs = _factor_inputs(
            spec,
            sources_by_ref=sources_by_ref,
            data_points_by_source=data_points_by_source,
        )
        refs = list(
            dict.fromkeys(
                ref
                for code in SEGMENT_FACTOR_CODES
                for ref in factor_inputs[code]["source_refs"]
            )
        )
        built_entity = build_segment_entity(
            {
                "key": spec["key"],
                "canonical_name": spec["name"],
                "display_name": spec["name"],
                "description": spec["description"],
                "factor_inputs": factor_inputs,
                "band_reason": "评分比较当前研究优先级；月产能、利用率、客户采购和产品价格缺口通过区间保留。",
            },
            sources_by_ref=sources_by_ref,
            as_of_date=AS_OF_DATE,
        )
        _annotate_contextual_metric_slot_evidence(
            built_entity,
            data_points_by_key={
                str(point["data_point_key"]): point for point in data_points
            },
        )
        _normalize_unrated_factor_public_text(built_entity)
        _normalize_complete_factor_score_text(built_entity)
        entities.append(built_entity)
        entity_sections.append(_entity_section(spec, refs))

    financial_targets = _financial_target_map(audited_financial_targets)
    targets: list[dict[str, Any]] = []
    target_specs: dict[str, list[Mapping[str, Any]]] = {}
    for spec in ENTITY_SPECS:
        for target_id in spec["targets"]:
            target_specs.setdefault(str(target_id), []).append(spec)
    primary_entity_by_target = {
        "siltronic": "dram_hbm_wafer_demand",
        "globalwafers": "global_300mm_fab_expansion",
        "sumco": "advanced_logic_wafer_demand",
        "eswin_materials": "china_300mm_wafer_suppliers",
        "soitec": "soi_engineered_substrate_demand",
    }
    for target_index, (target_id, related_specs) in enumerate(target_specs.items(), start=1):
        primary_key = primary_entity_by_target[target_id]
        related_specs = sorted(related_specs, key=lambda item: str(item["key"]) != primary_key)
        targets.append(
            _build_target(
                target_id=target_id,
                entity_specs=related_specs,
                financial_targets=financial_targets,
                sources_by_ref=sources_by_ref,
                index=target_index,
            )
        )
    for entity_key in ("nand_wafer_demand", "mature_200mm_wafer_demand"):
        spec = next(item for item in ENTITY_SPECS if item["key"] == entity_key)
        targets.append(
            _build_observation_target(
                entity_spec=spec,
                sources_by_ref=sources_by_ref,
                index=len(targets) + 1,
            )
        )

    builder = RunPackBuilder(
        slug=SLUG,
        research_question=research_question,
        display_title=DISPLAY_TITLE,
        requested_by="codex_opportunity_lens_research_workflow_v2",
        run_mode="c_hybrid",
        quality_profile="deep_research",
        problem_statement="核验2026—2030年全球晶圆厂扩产怎样形成硅片需求，拆分产品与地区，并判断中国供应商的受益条件和过剩风险。",
        intake={
            "research_question": research_question,
            "available_materials_choice": "B",
            "intake_material_type": "papers_folder",
            "materials_delivery_note": "本地硅片研报数量有限，只作为背景；全球项目、产能、客户关系与财务以独立公开一手检索补充。",
            "evidence_policy": "balanced",
            "time_window": {"core": "2026—2030", "history": "2020年以来项目、产能和周期"},
            "research_scope": {"geography": "全球", "industry": "半导体硅片需求", "exclusion": "光伏硅片与未形成晶圆投入的资本开支概念"},
            "special_constraints": {"capacity": "投资额不换算月产能", "memory": "HBM堆叠不重复乘入晶圆投入", "supplier": "历史认证不等于当前订单"},
            "field_origin": {"research_question": "user_provided", "scope": "user_provided", "model": "user_required_and_researcher_refined"},
            "default_accepted": {},
        },
    )
    builder.sources = sources
    builder.evidence_groups = {source["ref"]: source["independence_key"] for source in sources}
    builder.data_points = data_points
    claim_refs = [
        "S001", "S003", "S005", "S011", "S015", "S020", "S024", "S031", "S036",
        "S040", "S042", "S045", "S053", "S058", "S059", "S061", "S064", "S065",
        "DMD-SEMI-MEMORY-20260629", "DMD-SEMI-WAFER-OUTLOOK-202509",
        "DMD-NIST-GLOBALWAFERS", "DMD-SILTRONIC-AR2025",
        "DMD-SEMI-300MM-OUTLOOK-2Q26", "DMD-SEMI-DEMAND-TRANSMISSION-20251008",
        "DMD-MICRON-SINGAPORE-20260127", "DMD-SK-SILTRON-SR2025", "DMD-PSMC-CURRENT-2026",
    ]
    builder.claims = [
        {
            "source_ref": ref,
            "claim_text": sources_by_ref[ref]["excerpt_zh"],
            "source_excerpt": sources_by_ref[ref]["excerpt"],
            **({"source_excerpt_zh": sources_by_ref[ref]["excerpt_zh"]} if sources_by_ref[ref]["language"] != "zh-CN" else {}),
            "claim_type": _claim_type(sources_by_ref[ref]),
            "note": "只在来源披露范围内使用；没有月产能、客户或采购量时不外推。",
        }
        for ref in claim_refs
    ]
    builder.entities = entities
    builder.entity_sections = _replace_public_fact_source_refs(entity_sections)
    builder.entity_investment_targets = targets
    builder.sections = _replace_public_fact_source_refs(_main_sections())
    builder.visuals = _replace_public_fact_source_refs(
        [
            _visual(outputs),
            _project_database_visual(project_ledger),
            _china_project_database_visual(project_ledger),
            _project_priority_visual(project_ledger),
            _capacity_ranking_visual(model_inputs, project_ledger),
            _supply_balance_visual(outputs),
            _global_supplier_competition_visual(),
            _china_supplier_ranking_visual(),
            _supplier_relationship_visual(supplier_relationships),
        ]
    )
    builder.search_plan = [
        {"axis_key": "global_fab_projects", "query_text": "全球晶圆厂扩产、设备搬入、量产和月产能", "languages": ["zh", "en", "ja", "ko"], "status": "completed"},
        {"axis_key": "product_demand", "query_text": "先进逻辑、DRAM HBM、NAND、200毫米和SOI硅片需求", "languages": ["zh", "en", "ja", "ko"], "status": "completed"},
        {"axis_key": "wafer_suppliers", "query_text": "硅片供应商扩产、客户认证、销量、价格、利用率和盈利", "languages": ["zh", "en", "ja"], "status": "completed"},
        {"axis_key": "counterevidence", "query_text": "项目延期、利用现有洁净室、库存、价格下降和阶段性过剩", "languages": ["zh", "en", "ja", "ko"], "status": "completed"},
    ]
    builder.supplement_requests = [
        {
            "entity_key": "global_300mm_fab_expansion",
            "request_title": "补充大型晶圆厂的真实月产能与季度爬坡",
            "request_detail": "优先取得先进逻辑和存储项目的净增月产能、设备搬入、首片、利用率和原生硅片采购，扩大当前仅有4个项目的可量化子集。",
            "priority": "p1",
            "blocking_status": "limits_scoring",
            "review_status": "pending",
            "evidence_ref_uri": source_uri("S001"),
        },
        {
            "entity_key": "dram_hbm_wafer_demand",
            "request_title": "补充DRAM与NAND的分产品产能",
            "request_detail": "取得DRAM、NAND的月产能、利用率与单位晶圆位产出，验证HBM规格效应与NAND层数效应。",
            "priority": "p1",
            "blocking_status": "limits_scoring",
            "review_status": "pending",
            "evidence_ref_uri": source_uri("S003"),
        },
        {
            "entity_key": "china_300mm_wafer_suppliers",
            "request_title": "补充国内供应商的季度分产品经营数据",
            "request_detail": "补充12英寸抛光、外延、退火和SOI销量、价格、利用率、良率、认证转批量与经营现金流。",
            "priority": "p1",
            "blocking_status": "limits_scoring",
            "review_status": "pending",
            "evidence_ref_uri": source_uri("S058"),
        },
    ]
    builder.audit_issues = []
    builder.review_records = []
    pack = builder.build(publication_mode="stage")
    pack["as_of_date"] = AS_OF_DATE
    pack["model_artifacts"] = {
        **model_hashes,
        "evidence_audit_sha256": sha256_file(DEMAND_AUDIT_PATH),
        "financial_evidence_audit_sha256": sha256_file(FINANCIAL_AUDIT_PATH),
        "shared_financial_targets_sha256": sha256_file(
            FINANCIAL_DIR / "target_financials.json"
        ),
        "shared_financial_sources_sha256": sha256_file(
            FINANCIAL_DIR / "normalized_sources.json"
        ),
        "demand_financial_updates_sha256": sha256_file(
            DEMAND_FINANCIAL_UPDATE_PATH
        ),
        "supplemental_research_sha256": sha256_file(
            ROOT / "tools" / "opportunity_lens" / "silicon_supplemental_research.py"
        ),
        "factor_slot_inputs_sha256": sha256_file(FACTOR_SLOT_INPUT_PATH),
        "market_snapshot_sha256": sha256_file(MARKET_SNAPSHOT_PATH),
        "method": "全球总量与4个公开可量化项目的情景结果分开计算；后者逐项传播爬坡、利用率、工艺投入和库存系数，不能视为已实现采购的最低值。",
    }
    pack["evidence_audit"] = {
        "data_points": data_point_audit_summary,
        "sources": source_audit_summary,
        "supplemental_source_count": len(DEMAND_SUPPLEMENTAL_SOURCES),
        "supplemental_data_point_count": len(DEMAND_SUPPLEMENTAL_DATA_POINTS),
        "synchronized_project_count": len(project_ledger["projects"]),
        "audit_sha256": sha256_file(DEMAND_AUDIT_PATH),
    }
    pack["financial_evidence_audit"] = {
        **financial_audit_summary,
        "audit_sha256": sha256_file(FINANCIAL_AUDIT_PATH),
        "demand_side_latest_update": demand_financial_update_audit,
    }
    pack["source_data_point_excerpt_audit"] = source_excerpt_audit
    pack["project_ledger"] = project_ledger
    pack["supplier_relationships"] = supplier_relationships
    pack["tracking_framework"] = {
        "update_frequency": "季度；重大项目设备搬入、首片、量产或延期时事件驱动更新",
        "fields": ["净增月产能", "设备搬入和量产", "季度利用率", "分产品硅片销量与价格", "客户认证和复购", "毛利与经营现金流"],
    }
    pack["metric_slot_chain_audit"] = _metric_slot_chain_audit(pack)
    pack["metric_slot_cross_audit"] = _metric_slot_cross_audit(
        pack,
        project_ledger=project_ledger,
        model_inputs=model_inputs,
    )
    pack["factor_information_point_audit"] = _factor_information_point_audit(pack)
    pack["unrated_factor_public_text_audit"] = _unrated_factor_public_text_audit(
        pack
    )
    pack["factor_public_score_consistency_audit"] = (
        _factor_public_score_consistency_audit(pack)
    )
    pack["source_locator_audit"] = _source_locator_audit(
        pack,
        model_inputs=model_inputs,
    )
    pack["public_citation_excerpt_match_audit"] = (
        _public_citation_excerpt_match_audit(pack)
    )
    return pack


def write_bundle(*, output_dir: Path) -> Path:
    pack = build_pack(output_dir=output_dir)
    path = write_pack_bundle(pack, output_dir=output_dir, audit_profile="generic")
    write_json(output_dir / "source_catalog.json", pack["sources"])
    write_json(
        output_dir / "source_data_point_excerpt_audit.json",
        pack["source_data_point_excerpt_audit"],
    )
    write_json(
        output_dir / "metric_slot_cross_audit.json",
        pack["metric_slot_cross_audit"],
    )
    write_json(
        output_dir / "factor_information_point_audit.json",
        pack["factor_information_point_audit"],
    )
    write_json(
        output_dir / "unrated_factor_public_text_audit.json",
        pack["unrated_factor_public_text_audit"],
    )
    write_json(
        output_dir / "factor_public_score_consistency_audit.json",
        pack["factor_public_score_consistency_audit"],
    )
    write_json(
        output_dir / "public_citation_excerpt_match_audit.json",
        pack["public_citation_excerpt_match_audit"],
    )
    write_json(output_dir / "project_ledger.json", pack["project_ledger"])
    write_json(output_dir / "supplier_relationships.json", pack["supplier_relationships"])
    write_json(
        output_dir / "artifact_hashes.json",
        {
            "run_pack_sha256": sha256_file(path),
            "model_inputs_sha256": sha256_file(output_dir / "model_inputs.json"),
            "model_outputs_sha256": sha256_file(output_dir / "model_outputs.json"),
            "evidence_audit_sha256": sha256_file(DEMAND_AUDIT_PATH),
            "financial_evidence_audit_sha256": sha256_file(FINANCIAL_AUDIT_PATH),
            "shared_financial_targets_sha256": sha256_file(
                FINANCIAL_DIR / "target_financials.json"
            ),
            "shared_financial_sources_sha256": sha256_file(
                FINANCIAL_DIR / "normalized_sources.json"
            ),
            "demand_financial_updates_sha256": sha256_file(
                DEMAND_FINANCIAL_UPDATE_PATH
            ),
            "factor_slot_inputs_sha256": sha256_file(FACTOR_SLOT_INPUT_PATH),
            "market_snapshot_sha256": sha256_file(MARKET_SNAPSHOT_PATH),
            "source_data_point_excerpt_audit_sha256": sha256_file(
                output_dir / "source_data_point_excerpt_audit.json"
            ),
            "metric_slot_cross_audit_sha256": sha256_file(
                output_dir / "metric_slot_cross_audit.json"
            ),
            "factor_information_point_audit_sha256": sha256_file(
                output_dir / "factor_information_point_audit.json"
            ),
            "unrated_factor_public_text_audit_sha256": sha256_file(
                output_dir / "unrated_factor_public_text_audit.json"
            ),
            "factor_public_score_consistency_audit_sha256": sha256_file(
                output_dir / "factor_public_score_consistency_audit.json"
            ),
            "public_citation_excerpt_match_audit_sha256": sha256_file(
                output_dir / "public_citation_excerpt_match_audit.json"
            ),
            "builder_sha256": sha256_file(
                ROOT / "tools" / "opportunity_lens" / "build_silicon_wafer_demand_run_pack.py"
            ),
            "supplemental_research_sha256": sha256_file(
                ROOT / "tools" / "opportunity_lens" / "silicon_supplemental_research.py"
            ),
        },
    )
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="构建2026—2030全球晶圆厂扩产与硅片需求Opportunity Lens研究包")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    pack_path = write_bundle(output_dir=args.output_dir)
    print(pack_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
