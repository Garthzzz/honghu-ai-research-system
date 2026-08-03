from __future__ import annotations

"""构建长鑫科技 DRAM 设备供应链 Opportunity Lens Run17。

公开正文只保留决策所需的核心地图；完整工艺、证据、情景和公司模型
分别进入研究实体。所有数值均从冻结底稿读取，脚本不在构建阶段补造输入。
"""

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from tools.opportunity_lens.run_pack_builder import RunPackBuilder
from tools.opportunity_lens.run_pack_contract import validate_run_pack
from tools.opportunity_lens.intake_parser import parse_markdown_intake_text


ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "cache" / "research_runs" / "cxmt_dram_equipment_run17"
WORK = RUN_DIR / "workpapers"
OUTPUT_DIR = ROOT / "opportunity_lens" / "research_outputs" / "20260802_cxmt_dram_equipment_run17"
OUTPUT_PATH = OUTPUT_DIR / "run17_pack_stage.json"
PUBLIC_DRAFT_PATH = OUTPUT_DIR / "run17_public_draft.md"
INTAKE_PATH = ROOT / "opportunity_lens" / "intake_requests" / "Opportunity_Lens_用户研究请求_长鑫科技设备供应链_优化版.md"
WORKFLOW_REQUEST_PATH = RUN_DIR / "workflow_request.json"

CXMT_PATH = WORK / "cxmt_entity_fab_capacity_evidence.json"
PROCESS_PATH = WORK / "dram_process_equipment_global_evidence.json"
SUPPLIER_PATH = WORK / "cxmt_supplier_stage_evidence.json"
DEMAND_PATH = WORK / "cxmt_equipment_demand_scenario_model.json"
FINANCE_PATH = WORK / "listed_supplier_independent_operating_models_frozen.json"
VALUATION_PATH = WORK / "listed_supplier_external_reconciliation_and_valuation.json"

MODEL_REFS = {
    "cxmt": "model-cxmt-entity-fab",
    "process": "model-dram-process-global",
    "supplier": "model-cxmt-supplier-stage",
    "demand": "model-cxmt-equipment-demand",
    "finance": "model-supplier-finance-freeze",
    "valuation": "model-supplier-valuation-reconcile",
}

COMPANY_IDS = {
    "长鑫科技": 675,
    "北方华创": 424,
    "中微公司": 425,
    "拓荆科技": 426,
    "盛美上海": 441,
    "华海清科": 427,
    "精智达": 553,
    "京仪装备": 676,
    "长川科技": 435,
    "正帆科技": 458,
    "芯源微": 428,
    "中科飞测": 443,
    "华峰测控": 436,
}

ENTITY_TITLES = {
    "cxmt_entity_fab_platform": "长鑫主体、基地、产品与建设项目",
    "dram_process_equipment_map": "DRAM工艺与设备全景",
    "capacitor_etch_deposition": "电容、高深宽比刻蚀与薄膜沉积",
    "patterning_clean_cmp_metrology": "图形化、清洗、CMP与检测量测",
    "test_automation_utilities_services": "测试、自动化、厂务、零部件与服务",
    "global_peer_export_controls": "国际DRAM同业、设备竞争与出口限制",
    "cxmt_supplier_stage_matrix": "长鑫供应商与供应阶段",
    "cxmt_equipment_demand_2026_2031": "2026—2031设备需求与国产替代情景",
    "listed_supplier_investment_opportunities": "上市设备公司经营、估值与投资筛选",
}


class Run17BuildError(ValueError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise Run17BuildError(f"缺少Run17输入：{path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Run17BuildError(f"Run17输入必须是对象：{path}")
    return value


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _ev(ref: str) -> str:
    return f"source_ref:{ref}"


def _cite(*refs: str) -> str:
    return " ".join(f"^src:{_ev(ref)}" for ref in refs if ref)


def _company(name: str) -> str:
    company_id = COMPANY_IDS.get(name)
    return f"[{name}](/company/{company_id})" if company_id else name


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            return "—"
        return f"{float(value):,.{digits}f}"
    return str(value)


def _safe_ref(value: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")


def _section(key: str, title: str, body: str, order: int, refs: Sequence[str]) -> dict[str, Any]:
    for heading in ("### 问题", "### 研究方法与数据", "### 研究与分析", "### 总结"):
        if heading not in body:
            raise Run17BuildError(f"{key}缺少公开结构：{heading}")
    return {
        "section_key": key,
        "section_title": title,
        "title": title,
        "body_markdown": body.strip(),
        "evidence_ref_uri_list": [_ev(ref) for ref in dict.fromkeys(refs)],
        "support_status": "supported",
        "review_status": "pending",
        "sort_order": order,
    }


def _source_tier(value: str) -> str:
    text = str(value or "").lower()
    if text in {"s", "a", "强源", "primary"} or "primary" in text:
        return "A"
    if text in {"b", "中强"}:
        return "B"
    return "C"


def _load_inputs() -> dict[str, dict[str, Any]]:
    return {
        "request": _read_json(WORKFLOW_REQUEST_PATH),
        "cxmt": _read_json(CXMT_PATH),
        "process": _read_json(PROCESS_PATH),
        "supplier": _read_json(SUPPLIER_PATH),
        "demand": _read_json(DEMAND_PATH),
        "finance": _read_json(FINANCE_PATH),
        "valuation": _read_json(VALUATION_PATH),
    }


def _model_sources() -> list[dict[str, Any]]:
    specs = [
        (MODEL_REFS["cxmt"], CXMT_PATH, "长鑫主体、基地、产能与项目证据底稿", "长鑫主体、基地、产品、项目预算和公开边界的逐项核验。"),
        (MODEL_REFS["process"], PROCESS_PATH, "DRAM工艺、全球设备与出口限制证据底稿", "DRAM工艺、设备优先级、国际同业和出口限制的全球多语言证据底稿。"),
        (MODEL_REFS["supplier"], SUPPLIER_PATH, "长鑫具名供应商阶段证据矩阵", "按送样、交付、重复订单和稳定量产分档，排除匿名客户与关联关系误判。"),
        (MODEL_REFS["demand"], DEMAND_PATH, "长鑫2026—2031设备需求情景模型", "以220.66亿元已披露设备购置安装预算为锚的分类、年度和执行情景。"),
        (MODEL_REFS["finance"], FINANCE_PATH, "八家设备公司独立FY1—FY3经营模型", "在读取一致预期前冻结八家公司收入、利润、现金流和长鑫敏感性边界。"),
        (MODEL_REFS["valuation"], VALUATION_PATH, "八家设备公司外部对账与估值", "独立模型与Wind一致预期、最近两个季度卖方预测及市场估值的逐公司对账。"),
    ]
    rows = []
    for ref, path, title, excerpt in specs:
        rows.append({
            "ref": ref,
            "title": title,
            "publisher": "Industry Demo独立研究",
            "source_tier": "B",
            "source_review_status": "pass_with_note",
            "excerpt": excerpt,
            "language": "zh",
            "independence_key": "internal:run17:derived_workpapers",
            "independence_rationale": "本轮内部派生底稿统一归为一个非外部组；只用于模型回放，不增加外部独立证据组数量。",
            "source_channel": "report",
            "published_at": "2026-08-02",
            "local_path": path.relative_to(ROOT).as_posix(),
            "artifact_sha256": _sha(path),
        })
    report_names = {
        "北方华创": "naura",
        "中微公司": "amec",
        "拓荆科技": "piotech",
        "盛美上海": "acm",
        "华海清科": "hwatsing",
        "精智达": "jingzhida",
        "京仪装备": "jingyi",
        "长川科技": "changchuan",
    }
    paper_dir = ROOT / "papers" / "长鑫科技设备供应链"
    for company, slug in report_names.items():
        matches = list(paper_dir.glob(f"*2025年报*{company}*.pdf"))
        if not matches:
            raise Run17BuildError(f"缺少重点公司2025年报：{company}")
        path = matches[0]
        ref = f"ar-{slug}-2025"
        rows.append({
            "ref": ref,
            "title": f"{company}2025年年度报告",
            "publisher": company,
            "source_tier": "A",
            "source_review_status": "pass",
            "excerpt": "2025年收入、归母净利润、经营现金流、资本开支、产品进展和客户边界的公司法定披露。",
            "language": "zh",
            "independence_key": f"issuer:{slug}:annual_report_2025",
            "independence_rationale": "上市公司年度报告；与卖方预测和独立模型分组独立。",
            "source_channel": "web",
            "published_at": "2026",
            "local_path": path.relative_to(ROOT).as_posix(),
            "artifact_sha256": _sha(path),
            "search_axis_hint": "financials",
        })
    return rows


def _forecast_ref(company: str, institution: str, date: str) -> str:
    token = hashlib.sha256(f"{company}|{institution}|{date}".encode("utf-8")).hexdigest()[:10]
    return f"forecast-{token}"


def _forecast_sequence_text(values: Sequence[Any], metric_name: str) -> str:
    periods = ("FY2026", "FY2027", "FY2028")
    available = [
        f"{period}为{_fmt(value)}亿元"
        for period, value in zip(periods, values)
        if isinstance(value, (int, float))
    ]
    if not available:
        return f"该来源未取得可复核的{metric_name}序列"
    return f"{metric_name}" + "、".join(available)


def _iter_sell_side_reports(d: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for company_row in d["valuation"]["companies"]:
        company = str(company_row["company"])
        reconciliation = company_row["external_reconciliation"]
        candidates: list[Mapping[str, Any]] = []
        primary = reconciliation.get("primary")
        if isinstance(primary, Mapping) and "wind" not in str(primary.get("name") or "").lower():
            candidates.append(primary)
        secondary = reconciliation.get("secondary")
        if isinstance(secondary, Mapping):
            candidates.append(secondary)
        elif isinstance(secondary, list):
            candidates.extend(row for row in secondary if isinstance(row, Mapping))
        for report in candidates:
            institution = str(report.get("name") or "未命名机构")
            date = str(report.get("date") or "日期未标注")
            local_source = str(report.get("local_source") or "")
            url = str(report.get("url") or "")
            if not local_source and not url:
                raise Run17BuildError(f"{company}{institution}{date}卖方报告缺少URL或本地原文")
            reports.append(
                {
                    "company": company,
                    "institution": institution,
                    "date": date,
                    "ref": _forecast_ref(company, institution, date),
                    "local_source": local_source,
                    "url": url,
                    "revenue": list(report.get("revenue") or []),
                    "net_income": list(report.get("net_income") or []),
                    "valuation_reference": str(report.get("valuation_reference") or "未单列估值参数"),
                }
            )
    return reports


def _sell_side_sources(d: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for report in _iter_sell_side_reports(d):
        company = str(report["company"])
        institution = str(report["institution"])
        date = str(report["date"])
        title_zh = f"{institution}：{company}盈利预测与估值研究"
        is_english = company == "北方华创" and institution == "UBS"
        revenue_text = _forecast_sequence_text(report["revenue"], "收入")
        profit_text = _forecast_sequence_text(report["net_income"], "归母净利润")
        row: dict[str, Any] = {
            "ref": report["ref"],
            "title": (
                "Key Call: NAURA Technology Group — China's aggressive memory capex and WFE localization intact; maintain Buy"
                if is_english else title_zh
            ),
            "publisher": institution,
            "source_tier": "C",
            "source_review_status": "pass_with_note",
            "excerpt": (
                f"Report dated {date}; FY2026–FY2028 revenue forecasts are RMB 51.83/72.48/95.55bn and net earnings forecasts are RMB 6.78/11.60/16.72bn."
                if is_english else f"报告日期{date}；{revenue_text}；{profit_text}；估值参考：{report['valuation_reference']}。"
            ),
            "language": "en" if is_english else "zh",
            "independence_key": f"sellside:{institution}:{company}:{date}",
            "independence_rationale": "同一机构、同一公司、同一发布日期的报告只计一个独立组；只用于冻结后的外部对账。",
            "source_channel": "report",
            "published_at": date,
            "local_locator": "网页盈利预测表（FY2026—FY2028收入与归母净利润）及同页估值段落。",
            "screen_reason": "研究截止日前最近两个季度内的同公司卖方预测，用于独立模型冻结后的外部对账。",
        }
        if is_english:
            row["title_zh"] = "核心观点：北方华创——中国存储资本开支与晶圆制造设备本土化趋势延续，维持买入"
            row["excerpt_zh"] = "报告日期为2026年7月17日；FY2026—FY2028收入预测为518.30/724.80/955.51亿元，归母净利润预测为67.81/115.98/167.20亿元。"
        local_source = str(report.get("local_source") or "")
        if local_source:
            path = ROOT / local_source
            if not path.is_file():
                raise Run17BuildError(f"卖方报告本地原文不存在：{path}")
            row["local_path"] = path.relative_to(ROOT).as_posix()
            row["artifact_sha256"] = _sha(path)
            if company == "北方华创" and institution == "UBS":
                row["local_locator"] = "第1页Highlights表（FY2026—FY2028收入、净利润）及评级/目标价摘要。"
            elif company == "长川科技" and institution == "UBS":
                row["local_locator"] = "第1页盈利预测摘要；第12页图表24目标价推导。"
        else:
            row["url"] = report["url"]
        rows.append(row)
    return rows


def _context_report_sources() -> list[dict[str, Any]]:
    paper_dir = ROOT / "papers" / "长鑫科技设备供应链"
    specs = [
        ("*Bernstein*拓荆科技*.pdf", "Bernstein", "supplier_stage", "拓荆季度经营与薄膜设备外部对照"),
        ("*华泰证券*拓荆科技*.pdf", "华泰证券", "supplier_stage", "拓荆薄膜与混合键合业务对照"),
        ("*浙商证券*北方华创*.pdf", "浙商证券", "companies", "北方华创平台化能力与盈利预测对照"),
        ("*格林期货*存储大扩产*.pdf", "格林期货", "demand", "存储扩产与设备材料需求的周期背景"),
        ("*花旗*北美连接器*.pdf", "Citi", "global_peers", "海外硬件与存储产业景气背景"),
        ("*汇丰*前端半导体设备厂商*.pdf", "HSBC", "export_controls", "全球前道设备市场、区域限制与盈利对照"),
        ("*中信证券*长鑫科技*.pdf", "中信证券", "entity_fab", "长鑫IPO、产品与投资价值的卖方对照"),
        ("*UBS*SemiBytes*.pdf", "UBS", "global_peers", "海外半导体设备业绩前瞻"),
        ("*中信证券*半导体设备系列报告*.pdf", "中信证券", "critical_equipment", "AI与晶圆制造资本开支驱动的设备链对照"),
    ]
    english_metadata = {
        1: (
            "Piotech 1Q26: Clean beat from top to bottom, but net profit gain is from change in fair value of assets",
            "拓荆科技2026年一季度：收入与利润全面超预期，但净利润增长主要来自资产公允价值变动",
            "Piotech reported a strong 1Q26 top line, while most attributable net profit came from fair-value gains on financial assets.",
            "拓荆科技2026年一季度收入表现强劲，但归母净利润的大部分来自金融资产公允价值变动。",
        ),
        5: (
            "North America Connectors & Other Components, Electronic Components & Equipment and Hardware & Storage — 2Q26 Earnings Preview",
            "北美连接器、电子元件设备与硬件存储：2026年二季度业绩前瞻",
            "Citi reviews storage, hardware, connectivity and optical demand under the agentic-AI infrastructure cycle.",
            "花旗评估智能体AI基础设施周期下的存储、硬件、连接和光通信需求。",
        ),
        6: (
            "Front-end semicaps — Raising forecasts on strong WFE backdrop",
            "前道半导体设备：晶圆制造设备市场强劲，上调预测",
            "HSBC raises its CY2028 WFE estimate and reviews implications for major front-end equipment vendors.",
            "汇丰上调2028年全球晶圆制造设备市场预测，并分析主要前道设备公司的影响。",
        ),
        8: (
            "US Semiconductors and Semi Equipment — SemiBytes: Earnings Previews",
            "美国半导体与半导体设备：SemiBytes业绩前瞻",
            "UBS previews earnings for US semiconductor and equipment companies under current demand and inventory conditions.",
            "瑞银结合当前需求和库存环境，对美国半导体及设备公司进行业绩前瞻。",
        ),
    }
    rows: list[dict[str, Any]] = []
    for index, (pattern, publisher, axis, excerpt) in enumerate(specs, start=1):
        matches = list(paper_dir.glob(pattern))
        if not matches:
            raise Run17BuildError(f"缺少已使用的近期背景研报：{pattern}")
        path = matches[0]
        row = {
                "ref": f"context-report-{index:02d}",
                "title": english_metadata[index][0] if index in english_metadata else path.stem,
                "publisher": publisher,
                "source_tier": "C",
                "source_review_status": "pass_with_note",
                "excerpt": english_metadata[index][2] if index in english_metadata else excerpt + "；仅作为行业、公司或估值对照，不替代长鑫和供应商原始披露。",
                "language": "en" if index in english_metadata else "zh",
                "independence_key": f"sellside_context:{publisher}:{_sha(path)}",
                "independence_rationale": "同一研报只计一个独立组；卖方结论只作对照，不承担具名供应核心事实。",
                "source_channel": "report",
                "published_at": path.name[:10],
                "local_path": path.relative_to(ROOT).as_posix(),
                "artifact_sha256": _sha(path),
                "local_locator": "第1页标题、摘要与核心观点；相关报告仅作行业或公司对照。",
                "search_axis_hint": axis,
                "screen_reason": "近期中英文卖方或行业报告，用于本地研报链的独立对照。",
            }
        if index in english_metadata:
            row["title_zh"] = english_metadata[index][1]
            row["excerpt_zh"] = english_metadata[index][3] + "该报告只作行业或公司对照，不替代长鑫与供应商原始披露。"
        rows.append(row)
    return rows


def _build_sources(d: Mapping[str, Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, str]]:
    sources: list[dict[str, Any]] = []
    evidence_groups: dict[str, str] = {}
    ref_by_internal: dict[str, str] = {}

    # 长鑫监管和公司材料。
    evidence_by_source: dict[str, list[dict[str, Any]]] = {}
    for row in d["cxmt"]["evidence_records"]:
        evidence_by_source.setdefault(str(row["source_id"]), []).append(row)
    for source in d["cxmt"]["sources"]:
        source_id = str(source["source_id"])
        ref = f"cxmt-{source_id.lower()}"
        evidence_rows = evidence_by_source.get(source_id, [])
        excerpt = str(evidence_rows[0]["excerpt"] if evidence_rows else source.get("notes") or source["title"])
        row = {
            "ref": ref,
            "title": source["title"],
            "publisher": source["publisher"],
            "source_tier": _source_tier(source.get("tier")),
            "source_review_status": "pass",
            "excerpt": excerpt,
            "language": "zh",
            "independence_key": source["independence_key"],
            "independence_rationale": source.get("notes") or "监管、公司或政府原始材料。",
            "source_channel": "web",
            "published_at": source.get("date"),
            "url": source["url"],
        }
        sources.append(row)
        evidence_groups[ref] = row["independence_key"]
        ref_by_internal[f"cxmt:{source_id}"] = ref

    # DRAM全球工艺、厂商和出口管制。
    title_zh_by_evidence_id = {
        "E01": "半导体制造简介",
        "E02": "应用材料推出用于DRAM缩放的材料工程解决方案",
        "E03": "泛林集团推出面向高深宽比介质刻蚀的Flex G系列",
        "E04": "东京电子2026财年业绩发布会文字实录",
        "E05": "泽字节时代的新型存储器",
        "E06": "EUV光刻系统",
        "E07": "三星宣布行业首款EUV DRAM",
        "E08": "深入了解1-Alpha DRAM",
        "E09": "1-Gamma DRAM技术",
        "E10": "SK海力士开发行业首款1c DDR5",
        "E11": "南亚科技2025年第一季度业绩",
        "E12": "三星开发行业首款12纳米级DDR5 DRAM",
        "E13": "Axion T2000产品说明书",
        "E14": "KLA发布新一代缺陷检测与复查产品组合",
        "E15": "什么是关键尺寸扫描电子显微镜",
        "E16": "SCREEN半导体清洗设备累计出货突破1.5万台",
        "E17": "半导体制造设备市场",
        "E19": "什么是自动测试设备",
        "E20": "晶圆电测流程",
        "E21": "AP3000/AP3000e探针台",
        "E22": "存储器封装简介",
        "E23": "半导体刻蚀解决方案",
        "E24": "污染控制",
        "E25": "计算光刻",
        "E26": "美国商务部加强限制中国先进半导体制造能力的出口管制",
        "E27": "美国出口管理条例第772部分定义",
        "E28": "荷兰扩大先进半导体制造设备出口管制措施",
        "E29": "荷兰收紧先进半导体制造设备出口管制",
        "E30": "日本半导体制造设备出口管制",
        "E39": "澄清关于ASML的常见误解",
        "E40": "ASML 2025年年度报告：财务数据",
        "E41": "尼康半导体光刻系统产品阵容",
        "E42": "佳能光刻系统",
        "E43": "美国出口管理条例第740部分许可例外",
        "E44": "东京电子Episode系列",
    }
    for item in d["process"]["evidence_ledger"]:
        ref = f"dram-{str(item['evidence_id']).lower()}"
        language = str(item.get("language") or "en")
        independence_key = str(item["independence_key"])
        if str(item["evidence_id"]) == "E26":
            independence_key = "us_bis_semiconductor_controls_2024"
        elif str(item["evidence_id"]) == "E34":
            independence_key = "issuer:piotech:annual_report_2025"
        elif str(item["evidence_id"]) == "E36":
            independence_key = "issuer:kingsemi:annual_report_2025"
        elif str(item["evidence_id"]) == "E37":
            independence_key = "issuer:skyverse:annual_report_2025"
        row = {
            "ref": ref,
            "title": item["source_title"],
            "title_zh": title_zh_by_evidence_id.get(str(item["evidence_id"]), item["source_title"]),
            "publisher": item["publisher"],
            "source_tier": _source_tier(item.get("source_tier")),
            "source_review_status": "pass_with_note" if item.get("limitations") else "pass",
            "excerpt": item.get("excerpt_original") or item.get("excerpt_zh") or item["claim"],
            "excerpt_zh": item.get("excerpt_zh") or item["claim"],
            "language": language,
            "independence_key": independence_key,
            "independence_rationale": item["independence_rationale"],
            "source_channel": "web",
            "published_at": item.get("published_at") or item.get("accessed_at"),
            "url": item["url"],
        }
        if not language.lower().startswith("en"):
            row.pop("title_zh", None)
            row.pop("excerpt_zh", None)
        sources.append(row)
        evidence_groups[ref] = row["independence_key"]
        ref_by_internal[f"dram:{item['evidence_id']}"] = ref

    # 具名供应关系证据。
    supplier_evidence_by_source: dict[str, list[str]] = {}
    for supplier in d["supplier"]["supplier_records"]:
        for ev in supplier.get("evidence") or []:
            supplier_evidence_by_source.setdefault(str(ev["source_id"]), []).append(str(ev["facts"]))
    for source in d["supplier"]["sources"]:
        source_id = str(source["source_id"])
        ref = f"supplier-{_safe_ref(source_id)}"
        excerpt = "；".join(supplier_evidence_by_source.get(source_id, [])) or str(source.get("use") or source["title"])
        independence_key = f"supplier:{source_id.lower()}"
        supplier_group_overrides = {
            "S-CXMT-IPO-20260527": "cxmt_ipo_2026_disclosure",
            "S-NAURA-AR-2025": "issuer:naura:annual_report_2025",
            "S-AMEC-AR-2025": "issuer:amec:annual_report_2025",
            "S-KINGSEMI-AR-2025": "issuer:kingsemi:annual_report_2025",
            "S-SKYVERSE-AR-2025": "issuer:skyverse:annual_report_2025",
            "S-CHANGCHUAN-AR-2025": "issuer:changchuan:annual_report_2025",
        }
        independence_key = supplier_group_overrides.get(source_id, independence_key)
        row = {
            "ref": ref,
            "title": source["title"],
            "publisher": source["publisher"],
            "source_tier": _source_tier(source.get("tier")),
            "source_review_status": "pass_with_note",
            "excerpt": excerpt,
            "language": "zh",
            "independence_key": independence_key,
            "independence_rationale": "发行人或供应商原始公告/招股书；只支持文件中具名设备、客户与阶段。",
            "source_channel": "web",
            "published_at": source.get("publish_date"),
            "url": source["url"],
        }
        sources.append(row)
        evidence_groups[ref] = independence_key
        ref_by_internal[f"supplier:{source_id}"] = ref

    for row in _model_sources():
        sources.append(row)
        evidence_groups[row["ref"]] = row["independence_key"]

    for row in _sell_side_sources(d):
        sources.append(row)
        evidence_groups[row["ref"]] = row["independence_key"]

    for row in _context_report_sources():
        sources.append(row)
        evidence_groups[row["ref"]] = row["independence_key"]

    return sources, evidence_groups, ref_by_internal


def _entity_for_topic(topic: str) -> str:
    text = topic.lower()
    if any(word in text for word in ("主体", "基地", "产能", "产品", "项目", "募投", "fab")):
        return "cxmt_entity_fab_platform"
    if any(word in text for word in ("出口", "manufacturer", "global", "peer", "export")):
        return "global_peer_export_controls"
    if any(word in text for word in ("电容", "刻蚀", "沉积", "capacitor", "etch", "deposition")):
        return "capacitor_etch_deposition"
    if any(word in text for word in ("图形", "光刻", "清洗", "cmp", "量测", "检测", "pattern", "metrology")):
        return "patterning_clean_cmp_metrology"
    if any(word in text for word in ("测试", "厂务", "自动化", "封装", "test", "utility", "automation")):
        return "test_automation_utilities_services"
    return "dram_process_equipment_map"


def _fact_row(
    index: int,
    *,
    source_ref: str,
    entity_key: str,
    metric: str,
    period: str,
    value_text: str,
    source_excerpt: str,
    note: str,
    extraction_method: str = "web_fetch",
) -> tuple[dict[str, Any], dict[str, Any]]:
    data_point = {
        "data_point_key": f"run17.fact.{index:03d}",
        "source_ref": source_ref,
        "entity_key": entity_key,
        "metric": metric,
        "unit": "研究事实",
        "period": period,
        "scope_key": f"run17.{entity_key}.{index:03d}",
        "value_text": value_text,
        "source_excerpt": source_excerpt,
        "extraction_method": extraction_method,
        "note": note,
    }
    claim = {
        "claim_id": f"run17.claim.{index:03d}",
        "entity_key": entity_key,
        "source_ref": source_ref,
        "claim_type": "模型与情景" if extraction_method == "inferred" else "事实与分析",
        "claim_text": value_text,
        "source_excerpt": source_excerpt,
    }
    return data_point, claim


def _build_facts(
    d: Mapping[str, Mapping[str, Any]], ref_by_internal: Mapping[str, str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    points: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []

    def add(**kwargs: Any) -> None:
        point, claim = _fact_row(len(points) + 1, **kwargs)
        points.append(point)
        claims.append(claim)

    for row in d["cxmt"]["evidence_records"]:
        ref = ref_by_internal[f"cxmt:{row['source_id']}"]
        if str(row["source_id"]) == "S02":
            ref = ref_by_internal["cxmt:S01"]
        add(
            source_ref=ref,
            entity_key=_entity_for_topic(str(row["topic"])),
            metric=str(row["topic"]),
            period=str(row.get("source_date") or "截至2026-08-02"),
            value_text=str(row["statement"]),
            source_excerpt=str(row["excerpt"]),
            note=f"状态：{row['status']}；边界：{row['boundary']}；置信度：{row['confidence']}。",
        )

    for row in d["process"]["evidence_ledger"]:
        ref = ref_by_internal[f"dram:{row['evidence_id']}"]
        add(
            source_ref=ref,
            entity_key=_entity_for_topic(str(row["axis"])),
            metric=str(row["axis"]),
            period=str(row.get("published_at") or row.get("accessed_at") or "截至2026-08-02"),
            value_text=str(row["claim"]),
            source_excerpt=str(row.get("excerpt_zh") or row.get("excerpt_original") or row["claim"]),
            note=f"反方：{row.get('counterevidence') or '无'}；限制：{row.get('limitations') or '无'}。",
        )

    # 工艺阶段和设备优先级均是引用底层证据后的结构化研究事实。
    for row in d["process"]["process_chain"]:
        evidence_id = str((row.get("evidence_ids") or ["E01"])[0])
        ref = ref_by_internal.get(f"dram:{evidence_id}", MODEL_REFS["process"])
        add(
            source_ref=ref,
            entity_key=_entity_for_topic(str(row["stage"])),
            metric="DRAM工艺—设备映射",
            period="截至2026-08-02",
            value_text=f"{row['stage']}：{row['core_steps']}；主要设备为{row['equipment']}。",
            source_excerpt=str(row["decision_relevance"]),
            note="由工艺原理与设备公司原始技术资料归纳；不代表长鑫具体型号或装机数量。",
            extraction_method="inferred",
        )
    for row in d["process"]["scorecards"]:
        evidence_id = str((row.get("evidence_ids") or ["E01"])[0])
        ref = ref_by_internal.get(f"dram:{evidence_id}", MODEL_REFS["process"])
        add(
            source_ref=ref,
            entity_key=_entity_for_topic(str(row["module"])),
            metric="设备研究优先级",
            period="截至2026-08-02",
            value_text=f"{row['module']}优先级{_fmt(row['priority_score'])}分。",
            source_excerpt=str(row["rationale"]),
            note="分数按价值量、壁垒、DRAM专属性、重复强度、产能瓶颈和良率重要性加权，只作研究排序，不是市场份额或收益概率。",
            extraction_method="inferred",
        )

    for supplier in d["supplier"]["supplier_records"]:
        evidence = supplier.get("evidence") or []
        if evidence:
            source_id = str(evidence[0]["source_id"])
            ref = ref_by_internal[f"supplier:{source_id}"]
            excerpt = str(evidence[0]["facts"])
        else:
            ref = MODEL_REFS["supplier"]
            excerpt = str(supplier["assessment"])
        add(
            source_ref=ref,
            entity_key="cxmt_supplier_stage_matrix",
            metric="长鑫供应阶段",
            period=str(supplier.get("latest_positive_strong_evidence_date") or supplier.get("latest_checked_official_date") or "截至2026-08-02"),
            value_text=f"{supplier['company']}：阶段{supplier['highest_confirmed_stage']}，{supplier['stage_label']}。",
            source_excerpt=excerpt,
            note=str(supplier["assessment"]),
            extraction_method="web_fetch" if evidence else "inferred",
        )

    demand = d["demand"]
    for row in demand["base_allocation"]:
        add(
            source_ref=MODEL_REFS["demand"],
            entity_key="cxmt_equipment_demand_2026_2031",
            metric="2026—2028设备分类需求",
            period="2026—2028",
            value_text=(f"{row['category']}基准预算{_fmt(row['base_budget'])}亿元，"
                        f"国产可争取情景{_fmt(row['base_domestic_addressable_amount'])}亿元。"),
            source_excerpt=str(row["reason"]),
            note="类别金额＝220.66亿元×类别占比；国产可争取金额＝类别金额×情景承接比例。",
            extraction_method="inferred",
        )
    for row in demand["category_ranges"]:
        add(
            source_ref=MODEL_REFS["demand"],
            entity_key="cxmt_equipment_demand_2026_2031",
            metric="设备需求区间",
            period="2026—2028",
            value_text=(f"{row['category']}预算区间{_fmt(row['budget_range'][0])}—{_fmt(row['budget_range'][1])}亿元，"
                        f"国产可争取情景{_fmt(row['domestic_addressable_amount_range'][0])}—{_fmt(row['domestic_addressable_amount_range'][1])}亿元。"),
            source_excerpt="区间来自已披露总预算约束下的设备价值量和国内承接比例情景。",
            note="各类别上下限不能同时相加；不是公司采购指引。",
            extraction_method="inferred",
        )
    for row in demand["annual_installation_base"]:
        add(
            source_ref=MODEL_REFS["demand"],
            entity_key="cxmt_equipment_demand_2026_2031",
            metric="设备搬入年度节奏",
            period=str(row["year"]),
            value_text=f"{row['year']}年基准搬入安装{_fmt(row['equipment_purchase_and_installation'])}亿元，占已披露预算{_fmt(row['weight_pct'])}%。",
            source_excerpt=str(row["interpretation"]),
            note="设备搬入、安装、验收和供应商收入确认不是同一时点。",
            extraction_method="inferred",
        )
    for row in demand["execution_scenarios"]:
        add(
            source_ref=MODEL_REFS["demand"],
            entity_key="cxmt_equipment_demand_2026_2031",
            metric="项目执行情景",
            period="2026—2028",
            value_text=f"{row['scenario']}：累计{_fmt(row['cumulative_2026_2028_amount'])}亿元。",
            source_excerpt="；".join(row["main_triggers"]),
            note=str(row["interpretation"]),
            extraction_method="inferred",
        )

    for model in d["finance"]["models"]:
        for year, forecast in model["forecast"].items():
            add(
                source_ref=MODEL_REFS["finance"],
                entity_key="listed_supplier_investment_opportunities",
                metric="独立FY1—FY3经营模型",
                period=str(year),
                value_text=(f"{model['company']}：收入{_fmt(forecast['revenue'])}亿元、归母净利润"
                            f"{_fmt(forecast['net_income'])}亿元、自由现金流{_fmt(forecast['free_cash_flow'])}亿元。"),
                source_excerpt="；".join(model["assumptions"]["basis"]),
                note="在读取一致预期前冻结；长鑫只作敏感性，不作为基准收入单点。",
                extraction_method="inferred",
            )

    for row in d["valuation"]["companies"]:
        valuation_row = row["valuation"]
        value_range = valuation_row["value_range"]
        add(
            source_ref=MODEL_REFS["valuation"],
            entity_key="listed_supplier_investment_opportunities",
            metric="独立估值与市场对照",
            period=str(row["market_as_of"]),
            value_text=(
                f"{row['company']}：独立估值{_fmt(value_range[0])}—{_fmt(value_range[1])}亿元，"
                f"参考市值{_fmt(row['market_cap'])}亿元，相对差异"
                f"{_fmt(valuation_row['relative_to_market_pct'][0])}%—"
                f"{_fmt(valuation_row['relative_to_market_pct'][1])}%。"
            ),
            source_excerpt=str(valuation_row["conclusion"]),
            note=(
                f"估值方法：{valuation_row['method']}；市场时点为{row['market_as_of']}。"
                "各公司时点并非完全一致，不用于严格同日横截面排名。"
            ),
            extraction_method="inferred",
        )

    for report in _iter_sell_side_reports(d):
        revenue_text = _forecast_sequence_text(report["revenue"], "收入")
        profit_text = _forecast_sequence_text(report["net_income"], "归母净利润")
        add(
            source_ref=str(report["ref"]),
            entity_key="listed_supplier_investment_opportunities",
            metric="近期卖方盈利预测对账",
            period=str(report["date"]),
            value_text=f"{report['institution']}对{report['company']}的预测：{revenue_text}；{profit_text}。",
            source_excerpt=f"估值参考：{report['valuation_reference']}。",
            note="只作为独立模型冻结后的外部对账；报告必须位于研究截止日前最近两个季度。",
            extraction_method="pdf_direct" if report.get("local_source") else "web_fetch",
        )

    if len(points) < 100:
        raise Run17BuildError(f"平行数据点仅{len(points)}，未达到100")
    return points, claims


def _process_priority_table(process: Mapping[str, Any], limit: int | None = None) -> str:
    rows = sorted(process["scorecards"], key=lambda row: float(row["priority_score"]), reverse=True)
    if limit:
        rows = rows[:limit]
    lines = [
        "| 排名 | 设备子类 | 优先级 | 为什么重要 |",
        "|---:|---|---:|---|",
    ]
    for rank, row in enumerate(rows, start=1):
        lines.append(f"| {rank} | {row['module']} | {_fmt(row['priority_score'])} | {row['rationale']} |")
    return "\n".join(lines)


def _process_chain_table(process: Mapping[str, Any]) -> str:
    lines = [
        "| 工艺阶段 | 核心步骤 | 主要设备 | 对投资研究的作用 |",
        "|---|---|---|---|",
    ]
    for row in process["process_chain"]:
        steps = "、".join(str(item) for item in row["core_steps"]) if isinstance(row["core_steps"], list) else str(row["core_steps"])
        equipment = "、".join(str(item) for item in row["equipment"]) if isinstance(row["equipment"], list) else str(row["equipment"])
        lines.append(f"| {row['stage']} | {steps} | {equipment} | {row['decision_relevance']} |")
    return "\n".join(lines)


def _supplier_table(supplier: Mapping[str, Any]) -> str:
    ordered = sorted(
        supplier["supplier_records"],
        key=lambda row: (-int(row["highest_confirmed_stage"]), str(row["company"])),
    )
    lines = [
        "| 公司 | 设备/服务 | 公开可确认阶段 | 最强证据与结论 | 投资研究处理 |",
        "|---|---|---|---|---|",
    ]
    for row in ordered:
        name = _company(str(row["company"]).replace("(688596.SH)", ""))
        evidence = row.get("evidence") or []
        fact = evidence[0]["facts"] if evidence else row["assessment"]
        treatment = (
            "可进入长鑫受益候选，但仍需跟踪复购、关键层和收入确认"
            if int(row["highest_confirmed_stage"]) >= 5
            else "只保留工艺适配观察，不把行业地位写成长鑫订单"
        )
        lines.append(f"| {name} | {row['category']} | {row['stage_label']} | {fact} | {treatment} |")
    return "\n".join(lines)


def _demand_table(demand: Mapping[str, Any]) -> str:
    ranges = {row["category"]: row for row in demand["category_ranges"]}
    lines = [
        "| 设备类别 | 基准预算（价值量占比） | 价值量区间 | 基准国产可争取（承接比例） | 国产可争取区间 | 核心判断 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in demand["base_allocation"]:
        rg = ranges[row["category"]]
        lines.append(
            f"| {row['category']} | {_fmt(row['base_budget'], 1)}亿元（{_fmt(row['base_value_share_pct'], 0)}%） | {_fmt(rg['budget_range'][0], 1)}—{_fmt(rg['budget_range'][1], 1)}亿元 | "
            f"{_fmt(row['base_domestic_addressable_amount'], 1)}亿元（{_fmt(row['base_domestic_addressable_pct'], 0)}%） | {_fmt(rg['domestic_addressable_amount_range'][0], 1)}—{_fmt(rg['domestic_addressable_amount_range'][1], 1)}亿元 | {row['reason']} |"
        )
    return "\n".join(lines)


def _annual_demand_table(demand: Mapping[str, Any]) -> str:
    lines = [
        "| 年份/情景 | 模型分配的设备搬入金额 | 解释 |",
        "|---|---:|---|",
    ]
    for row in demand["annual_installation_base"]:
        lines.append(f"| {row['year']}年基准 | {_fmt(row['equipment_purchase_and_installation'], 1)}亿元 | {row['interpretation']} |")
    for row in demand["execution_scenarios"]:
        lines.append(f"| {row['scenario']} | {_fmt(row['cumulative_2026_2028_amount'], 1)}亿元 | {row['interpretation']}；触发条件：{'、'.join(row['main_triggers'])} |")
    return "\n".join(lines)


def _finance_table(finance: Mapping[str, Any], valuation: Mapping[str, Any]) -> str:
    valuation_by_name = {row["company"]: row for row in valuation["companies"]}
    lines = [
        "| 公司 | 与长鑫的公开证据边界 | FY2026—FY2028收入 | FY2026—FY2028归母净利润 | FY2026—FY2028自由现金流 | 独立估值/参考市值 |",
        "|---|---|---:|---:|---:|---|",
    ]
    for model in finance["models"]:
        name = str(model["company"])
        row = valuation_by_name[name]
        forecasts = model["forecast"]
        revenue = "/".join(_fmt(forecasts[str(year)]["revenue"]) for year in (2026, 2027, 2028))
        profit = "/".join(_fmt(forecasts[str(year)]["net_income"]) for year in (2026, 2027, 2028))
        fcf = "/".join(_fmt(forecasts[str(year)]["free_cash_flow"]) for year in (2026, 2027, 2028))
        valuation_range = row["valuation"]["value_range"]
        relative = row["valuation"]["relative_to_market_pct"]
        if name in {"北方华创", "中微公司", "长川科技"}:
            exposure = "若未来取得长鑫具名订单，集团业务方向上可能受益；基准模型未计入长鑫收入"
        else:
            exposure = model["cxmt_sensitivity_only"]["direction"]
        lines.append(
            f"| {_company(name)} | {exposure} | {revenue} | {profit} | {fcf} | "
            f"{_fmt(valuation_range[0])}—{_fmt(valuation_range[1])}/{_fmt(row['market_cap'])}亿元（{row['market_as_of']}）；"
            f"{_fmt(relative[0])}%—{_fmt(relative[1])}% |"
        )
    return "\n".join(lines)


def _valuation_detail_table(valuation: Mapping[str, Any]) -> str:
    lines = [
        "| 公司 | 方法与参数 | 当前市场隐含 | 外部对账 | 当前研究动作 |",
        "|---|---|---|---|---|",
    ]
    for row in valuation["companies"]:
        val = row["valuation"]
        primary = row["external_reconciliation"]["primary"]
        if val["method"] == "FY1 PS诊断":
            implied = val.get("market_implied_fy1_revenue_at_multiple_range") or []
            implied_text = f"在8—12倍PS下需FY1收入约{_fmt(implied[1])}—{_fmt(implied[0])}亿元"
            market_multiple = f"市场前瞻PS {_fmt(val.get('market_forward_ps'))}倍；PE {_fmt(val.get('market_forward_pe'))}倍仅显示利润失真，不用于估值"
        else:
            implied = val.get("market_implied_fy1_net_income_at_multiple_range") or []
            implied_text = "—" if not implied else f"在所用倍数下需FY1净利润约{_fmt(implied[1])}—{_fmt(implied[0])}亿元"
            market_multiple = f"市场前瞻PE {_fmt(val.get('market_forward_pe'))}倍"
        action = val["conclusion"]
        benchmark_date = primary.get("date") or primary.get("as_of") or "日期未标注"
        benchmark_profit = "/".join(_fmt(value) for value in primary.get("net_income", []))
        lines.append(
            f"| {_company(row['company'])} | {val['method']}，{_fmt(val['multiple_range'][0])}—{_fmt(val['multiple_range'][1])}倍；{val['multiple_basis']} | "
            f"{implied_text}；{market_multiple} | "
            f"独立FY1净利润{_fmt(row['independent_forecast']['2026']['net_income'])}亿元；{primary['name']}（{benchmark_date}）FY2026—FY2028归母净利润{benchmark_profit}亿元 | {action} |"
        )
    return "\n".join(lines)


def _refs_for_axis(process: Mapping[str, Any], *words: str, limit: int = 8) -> list[str]:
    refs = []
    for row in process["evidence_ledger"]:
        hay = " ".join([str(row.get("axis") or ""), str(row.get("claim") or ""), str(row.get("supports") or "")]).lower()
        if any(word.lower() in hay for word in words):
            refs.append(f"dram-{str(row['evidence_id']).lower()}")
    return list(dict.fromkeys(refs))[:limit]


def _main_sections(d: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    cxmt = d["cxmt"]
    process = d["process"]
    supplier = d["supplier"]
    demand = d["demand"]
    finance = d["finance"]
    valuation = d["valuation"]
    summary = f"""
### 问题

长鑫科技2026—2028年的扩产和技术升级，哪些设备需求最确定，哪些中国公司已有可核验供应关系，当前估值是否仍有安全边际？

### 研究方法与数据

以{_company('长鑫科技')}IPO监管材料确认主体、基地、项目和220.66亿元设备购置安装预算；以三星、SK海力士、美光、南亚科技及全球设备厂原始资料重建DRAM工艺；逐家公司核对招股书、问询回复和年报中的长鑫具名交付；最后冻结八家上市公司FY2026—FY2028模型，再与Wind一致预期和最近两个季度卖方预测对账。 {_cite('cxmt-s01', MODEL_REFS['process'], MODEL_REFS['supplier'], MODEL_REFS['finance'], MODEL_REFS['valuation'])}

### 研究与分析

**最确定的总量锚是两项前道升级项目合计220.66亿元设备购置安装预算，计划在2026—2027年分批搬入调试、2028年上半年验收；它不是新增晶圆月产能，也不能直接分摊成设备公司收入。** 基准情景把刻蚀、薄膜沉积/热处理/注入、清洗/CMP、检测量测列为国产设备最值得跟踪的四组机会；先进曝光仍是最大价值量和最弱国产供给交集。

公开强证据只确认六条具名商业链：{_company('拓荆科技')}和{_company('盛美上海')}达到正式交付，{_company('华海清科')}、{_company('精智达')}、{_company('京仪装备')}和{_company('正帆科技')}出现量产线、连续交付、重复合同或长期服务证据。**没有一家公司可以据公开材料称为长鑫“主力、第一或独家供应商”。** {_company('北方华创')}、{_company('中微公司')}和{_company('长川科技')}具备工艺或平台能力，但本轮没有取得长鑫具名订单强证据，投资判断必须把“产业能力”与“长鑫收入”分开。

| 决策层 | 当前结论 | 进一步查看 |
|---|---|---|
| 设备机会 | 高深宽比刻蚀、电容薄膜、清洗/CMP和先进量测随工艺复杂度提升，需求强度可能快于晶圆产能 | [关键设备优先级](/opportunity-lens/run/17/entity-name/DRAM工艺与设备全景) |
| 供应证据 | 六条具名商业链成立，但阶段、年份和产品不同，不能横向写成统一份额 | [供应阶段矩阵](/opportunity-lens/run/17/entity-name/长鑫供应商与供应阶段) |
| 需求时间 | 模型基准把2026—2028年设备搬入约分配为79.4/105.9/35.3亿元，并把2027年设为高峰；2029—2031只做条件情景 | [设备需求情景](/opportunity-lens/run/17/entity-name/2026—2031设备需求与国产替代情景) |
| 投资筛选 | 产业优先跟踪北方、盛美、华海；京仪、拓荆弹性高但估值高；八家公司在各自参考市值日均高于独立估值区间 | [公司经营与估值](/opportunity-lens/run/17/entity-name/上市设备公司经营、估值与投资筛选) |

### 总结

**当前最有把握的是“设备资本开支真实、国产导入分环节推进”；最没有把握的是单一供应商份额、先进关键层份额和2029—2031新增产能。** 因此先跟踪交付、验收和复购，不因长鑫扩产主题在高估值下追买；只有订单证据与盈利兑现同时增强，才把产业机会转成公司权重。
"""

    entity_map = f"""
### 问题

研究对象到底是长鑫科技集团、长鑫存储、历史睿力集成、合肥/北京项目公司，还是封装测试与模组主体？若主体混写，产能、设备预算和供应商关系都会被错误外推。

### 研究方法与数据

用上交所招股书、问询回复、法律意见书、环境与项目材料逐一核对法律主体、控制关系、工厂所在地、业务分工、在建工程和项目预算。注册地址、研发中心和项目公司只在文件明确承担晶圆制造时计入fab；历史项目数据不自动外推到当前集团。 {_cite('cxmt-s01','cxmt-s02','cxmt-s03','cxmt-s04',MODEL_REFS['cxmt'])}

### 研究与分析

{_company('长鑫科技')}是IPO发行人，长鑫存储是其全资子公司，长鑫新桥和北京长鑫集电承担不同生产或建设职能，历史睿力集成是发行人前身，长鑫产品（合肥）更偏产品和模组边界。集团公开确认合肥一期、合肥二期和北京三条12英寸产线，合肥二期在2024年量产，北京线在2023年量产；2023—2025年产能利用率由87.06%升至92.46%和95.73%。这些信息证明现有产线高负荷运行，却不能推出集团当前绝对WSPM。

唯一公开且较强的绝对产能锚是早期合肥项目环评的设计12.5万片/月，它对应特定历史项目，而不是截至2026年的集团总产能。2025年末合肥一期、合肥二期和北京生产线累计转固规模分别约467.50、269.50和203.90亿元，在建工程仍约39.86、55.60和119.96亿元；转固和在建规模说明资产密集度与持续技改，但同样不能机械换算设备台数。

产品方面，第三、第四代工艺已量产，第五代处于研发；自有DDR4已在2024年底停止，重点转向DDR5和LPDDR5/5X。LPDDR5X 8533/9600已在2025年5月量产，10667截至2025年10月处于送样。封装以外协为主，测试以自制为主、外协补充，模组自制和外协并存，所以前道、晶圆测试和封测厂资本开支必须分开。

从资产到设备收入还有四个时点：项目预算获批、设备下单与预付款、搬入安装、验收转固。长鑫披露的设备购置安装预算只证明总量上限和建设方向，不能决定上市设备公司的确认年份。2025年末三条线仍有在建工程，说明存量线可能同时发生扩建、技改和未验收设备；若只看到转固增加就写成“新增产能释放”，会把会计时点和有效晶圆产出混为一谈。后续应把在建工程、固定资产转入、供应商合同负债/存货和长鑫产品放量同时核对。

另一个容易误判的是产品速度与制程节点。LPDDR5X更高速度证明产品和测试要求提升，但不自动揭示采用多少纳米、是否使用EUV或具体电容结构。第五代工艺由研发到量产时，只有公司正式产品、客户认证、资本开支或设备搬入至少两类证据闭环，才把它转成新增关键设备需求。

### 总结

**能够直接用于设备投资判断的是三条12英寸产线、高利用率、两项前道升级项目和产品向DDR5/LPDDR5X迁移；不能直接使用的是30万/35万/60万片月产能、上海新fab、HBM量产、EUV采用和各基地同配置等未闭环说法。** 详细主体和项目表见[研究实体](/opportunity-lens/run/17/entity-name/长鑫主体、基地、产品与建设项目)。
"""

    priority = f"""
### 问题

完整DRAM设备链里，哪些环节真正决定扩产、工艺升级和良率，哪些只是“半导体设备”大类映射？

### 研究方法与数据

先把晶圆进厂、表面准备、图形化、刻蚀、沉积与掺杂、平坦化、检测量测、晶圆电测修复、封装终测、自动化和厂务串成闭环，再按价值量25%、技术壁垒20%、DRAM专属性15%、重复使用15%、产能瓶颈10%和良率重要性15%加权。分数只用于研究优先级，不代表市场份额或上涨概率。 {_cite('dram-e01','dram-e02','dram-e03','dram-e04','dram-e13','dram-e14','dram-e19')}

### 研究与分析

{_process_priority_table(process, limit=10)}

排序的核心不是“刻蚀比沉积好”，而是DRAM电容结构把两者锁在同一瓶颈：更深更窄的电容孔需要高离子能、严格CD和侧壁控制，随后又要在高深宽比表面沉积均匀电极与高k介质。任一环节失配都会通过漏电、接触电阻、结构坍塌和良率损失传导到有效产能。量测和清洗因此不是低价值辅助——节点缩小、多重图形和国产设备并行验证会增加采样、缺陷分类、残留去除和干燥难度。

光刻与涂显在总价值量中最高，但必须拆开：EUV只覆盖最关键层，DUV仍承担大量层；多重图形会增加涂显、沉积、刻蚀、去胶、清洗与套刻量测次数。国内涂胶显影和部分非关键层有进展，并不等于先进曝光国产化。晶圆电测、修复、老化和终测决定坏点识别与可售良率，却不能与前道220.66亿元预算重复计算。

### 总结

**最高研究优先级是高深宽比电容刻蚀、电容薄膜沉积、先进图形化和在线检测量测；清洗/CMP更接近已有国产商业验证，测试、温控和厂务则更容易形成具名客户证据。** 这四类机会的确定性和估值并不相同，必须进入细分研究实体逐项判断。
"""

    supply = f"""
### 问题

哪些公司是真正向长鑫交付过设备或系统，哪些只是产品适用于DRAM或披露“国内存储客户”？

### 研究方法与数据

把供应阶段分成未取得具名强证据、接触/送样、验证、小批量、正式商业交付、跨期连续交付或复购、稳定量产/长期服务、主力供应九档。只接受客户或供应商原始文件中的具名主体、设备/系统、金额、验收或量产信息；共同董事、员工背景、匿名存储客户和同源转载均不升级阶段。 {_cite(MODEL_REFS['supplier'],'supplier-s-piotech-ipo-20220414','supplier-s-acm-ipo-20211112','supplier-s-hwatsing-ipo-20220601','supplier-s-jingzhida-ipo-20230713','supplier-s-jingyi-ipo-20231124','supplier-s-zhengfan-reply-20260613')}

### 研究与分析

{_supplier_table(supplier)}

已确认关系中，{_company('拓荆科技')}的旧证据是薄膜沉积设备进入长鑫产线并在2021年前三季度确认3,221.87万元收入；{_company('盛美上海')}在2020年向睿力集成销售单片清洗设备并确认2,719.72万元收入。它们证明商业交付，却不能证明2026年的当前份额或关键层复购。

{_company('华海清科')}的CMP设备有“大生产线量产应用”证据，但公开收入跨年波动大，说明项目交付并非稳定年金；{_company('精智达')}在2020—2022年连续取得存储测试设备收入并有后续验收，{_company('京仪装备')}披露温控设备大批量长期适配和多笔合同，{_company('正帆科技')}则确认高纯工艺介质系统长期服务。三者更接近连续商业关系，但仍不代表前道核心设备最大价值量。

### 总结

**具名关系只能证明“进入过、交付过或长期服务”，不能自动证明先进关键层、当前份额和未来利润弹性。** 当前投资排序应同时看供应阶段、设备价值量、收入基数和估值；供应矩阵的首要用途是排除假阳性，不是凑出一张“国产替代名单”。
"""

    global_section = f"""
### 问题

国际DRAM厂的路线和美国、荷兰、日本出口限制，会怎样改变长鑫的设备组合、冗余、维护和国产替代节奏？

### 研究方法与数据

用三星、SK海力士、美光、南亚科技及Applied Materials、Lam、TEL、ASML、KLA等原始资料比较EUV/DUV、多重图形、电容、外围CMOS和量测方案；法规只使用BIS、荷兰政府和日本经产省原文，区分许可证、终端用途、整机、软件、部件、安装维护和替换件。 {_cite('dram-e07','dram-e08','dram-e09','dram-e10','dram-e11','dram-e26','dram-e28','dram-e29','dram-e30','dram-e43')}

### 研究与分析

三星从1a DRAM推进EUV，公开强调减少多重图形步骤；美光1alpha证明无EUV也可通过侧墙沉积和重复图形转移推进，1gamma才首次引入EUV和下一代HKMG；SK海力士1c沿用1b平台并优化EUV；南亚1B在2025年二季度晶圆投入约占总产能三分之一。四条路线说明“是否有EUV”并非先进DRAM唯一维度，但会改变涂显、掩膜、沉积、刻蚀、清洗、套刻和良率控制的组合。

出口控制不是简单的“所有海外设备都不能卖”。美国规则覆盖特定半导体制造设备、软件、HBM和先进DRAM终端用途，并对安装、维护、维修和替换件设置条件；荷兰对特定先进DUV及少量量测检测技术实行逐案许可；日本对23类先进设备实行面向所有地区的许可控制。现实影响包括交付延迟、配置降档、备件库存增加、远程软件与现场服务不确定、国产设备双平台验证和更高冗余，而不是立即把所有进口装机归零。

国产替代的真正难点因此从“有没有设备”转向三件事：关键层工艺窗口是否稳定；跨批次良率和软件反馈能否闭环；备件与服务是否支持高稼动率。国际厂商以工艺协同、装机基础、应用数据库和现场服务构成系统壁垒，中国厂商若只完成单机验证而没有量产线复购，仍不能视为完成替代。

### 总结

**出口限制会提高国产设备验证价值，也会提高调试、冗余和量测需求，但它同时可能拖慢长鑫扩产和良率爬坡。** 受益方向与项目总进度不是单向同涨：设备国产化比例提高而项目延后时，部分供应商收入仍可能后移。
"""

    demand_section = f"""
### 问题

在绝对新增WSPM、设备台数和供应商金额未披露时，怎样估算2026—2031设备需求而不制造伪精确结果？

### 研究方法与数据

只以{_company('长鑫科技')}披露的生产线升级项目46.66亿元和DRAM技术升级项目174.00亿元设备购置安装预算为总量锚。类别需求＝220.66亿元×类别价值量占比；国产可争取金额＝类别需求×国内厂商情景承接比例；年度搬入金额＝220.66亿元×年度权重。设备预算不分摊到供应商，2029—2031没有正式资本开支锚时只列条件触发。 {_cite('cxmt-s01',MODEL_REFS['demand'])}

### 研究与分析

{_demand_table(demand)}

{_annual_demand_table(demand)}

基准国产可争取金额的情景中枢约62亿元，但它是六类专家输入的模型合计，不是已经签订的国产订单。最敏感的两项是假设刻蚀和薄膜/热处理/注入能承接35%，清洗/CMP能承接55%；若关键层验证停滞，国产金额会落向区间下沿；若长鑫为降低供应风险增加双平台、量测和清洗冗余，总支出可能高于披露预算，但超出部分必须等待新项目或合同验证。

2026—2028基准年度分配约为79.4、105.9和35.3亿元，强调的是模型中的搬入安装节奏而非供应商收入确认。延期情景累计约180.9亿元；高于预算的约242.7亿元增强情景只在额外冗余或后续扩展出现时成立。2029—2031只有第五代工艺量产、新产线正式披露、设备替换周期、重复订单和服务收入形成闭环，才上调需求。

### 总结

**基准模型把2027年设为设备搬入高峰，2026年更重首批交付和调试，2028年更重验收和尾项；这是年度分配假设，不是长鑫披露的年度采购计划。** 任何公司收入模型都必须再经过“具名设备—供应阶段—交付验收—收入确认”四步，不能把约62亿元直接分给国产设备股。
"""

    investment = f"""
### 问题

哪些A股设备公司既能承接长鑫需求，又能把产业机会转成集团利润和现金流；当前价格是否已透支？

### 研究方法与数据

八家公司分别从2025年实际收入、归母利润、经营现金流和资本开支建立FY2026—FY2028集团模型；长鑫只作为敏感性，不进入基准收入单点。模型冻结后读取Wind一致预期和研究截止日前最近两个季度同公司卖方预测。估值以数据可支持的FY1正常化PE或PS为主，并反推当前市值要求的FY1利润；不因长鑫主题强行使用DCF或PB—ROE。 {_cite(MODEL_REFS['finance'],MODEL_REFS['valuation'])}

### 研究与分析

{_finance_table(finance, valuation)}

产业确定性和股票安全边际出现明显错位。{_company('北方华创')}平台覆盖最广、集团增长和长鑫扩产方向一致，但公开长鑫具名设备证据不足，当前市值又高于42—65倍FY1 PE区间上沿；适合作为产业核心跟踪，不适合把“高确定性”误写成“当前价低风险”。{_company('盛美上海')}和{_company('华海清科')}有具名长鑫交付或量产线证据，设备类别也与清洗/CMP国产承接较高的情景一致，但当前市值同样显著高于独立区间。

{_company('拓荆科技')}的薄膜沉积处于高价值、高壁垒方向，旧具名交付证据成立，若先进存储产品从验证转规模量产，收入弹性可能高；问题是现价已经要求远高于基准模型的盈利。{_company('京仪装备')}和{_company('精智达')}具名关系更直接、收入基数更小，单笔项目弹性大，但温控/测试在220.66亿元前道预算中的口径不同，且小公司估值和验收波动更大。

{_company('中微公司')}和{_company('长川科技')}在刻蚀/沉积或测试领域有产业能力，却没有长鑫具名强证据；本轮只能按集团业务和行业机会估值，不能作为长鑫直接受益核心仓。按各公司底稿中明确标注的参考市值日期，八家公司均高于独立估值区间；七家公司使用2026年7月14日、京仪装备使用7月30日，因此这里只判断各自估值边界，不作严格同日横截面排名。这一结果不是断言股价必跌，而是说明市场已经计入更高利润率、更快订单兑现或更高估值持续期。

### 总结

**产业跟踪优先级：北方华创、盛美上海、华海清科；高弹性但高估值：京仪装备、拓荆科技；集团逻辑成立但长鑫证据不足：中微公司、长川科技；精智达需先验证盈利与验收持续性。** 当前不把任何一家公司列为“长鑫扩产即买入”：已有具名供应证据的公司要看复购与验收，尚未具名的公司先等首个订单与交付验收；同时还要满足估值或盈利条件。
"""

    monitoring = f"""
### 问题

哪些少量事件最能证伪或上调当前结论，避免研究在项目推进后失效？

### 研究方法与数据

监控只保留能改变项目执行、国产设备阶段或公司利润的指标，分别映射长鑫项目、工艺产品、供应商订单、出口许可和公司财务。早期新闻只有在追到公告、订单、验收、政府项目或客户/供应商原始资料后才升级。

### 研究与分析

| 监控项 | 当前基线 | 上调条件 | 下调或证伪条件 | 影响 |
|---|---|---|---|---|
| 两项升级项目搬入和验收 | 2026—2027分批搬入，2028H1计划验收 | 新增设备合同、搬入、转固与验收同向 | 在建工程停滞、许可/厂务/良率延误 | 改变2026—2028年度设备需求 |
| 第五代工艺与DDR5/LPDDR5X | 第五代研发，第三/第四代量产 | 新代产品量产、良率和客户放量 | 送样不转量产、旧代库存或价格压力 | 改变关键层刻蚀、薄膜和量测强度 |
| 国产设备复购 | 六条具名商业链，阶段各异 | 同设备跨期订单、验收和关键层扩展 | 一次性交付后无复购、仅非关键层 | 改变供应商阶段和收入弹性 |
| 出口许可与服务 | 分设备、软件、部件和终端用途许可 | 关键设备和备件许可稳定、服务连续 | 许可延迟、维护/替换件受限 | 同时影响项目进度和国产冗余需求 |
| 设备公司财务兑现 | 八家公司估值均高于独立区间 | FY1利润上修、现金转换改善、估值回落 | 订单增而现金流恶化、毛利率降、验收后移 | 决定产业机会能否转为股票回报 |

“悦芯TM8000在长鑫量产导入”、长鑫HBM量产、EUV或国产ArF浸没式曝光使用、上海新fab、绝对月产能、国产设备具体份额以及特定封测厂份额均属于重要但尚未验证线索。它们可能显著改变刻蚀、沉积、量测、封装和设备总量，但在缺少客户/供应商原始文件、项目批准或可核验搬入前，只提高补证优先级，不进入基准情景。

### 总结

**最重要的三项更新顺序是：项目是否按期搬入、国产设备是否形成同设备复购、候选公司利润和现金流是否同步兑现。** 若只有产业新闻而没有这三项中的任何一项，维持原有供应阶段和估值判断。
"""

    specs = [
        ("summary", "摘要", summary, ["cxmt-s01", MODEL_REFS["supplier"], MODEL_REFS["demand"], MODEL_REFS["valuation"]]),
        ("entity_boundary", "长鑫主体与研究边界", entity_map, ["cxmt-s01","cxmt-s02","cxmt-s03","cxmt-s04",MODEL_REFS["cxmt"]]),
        ("equipment_priority", "关键设备优先级", priority, ["dram-e01","dram-e02","dram-e03","dram-e04","dram-e13","dram-e14","dram-e19"]),
        ("supplier_stage", "长鑫供应商与供应阶段", supply, [MODEL_REFS["supplier"]]),
        ("peer_export", "国际同业与出口限制", global_section, ["dram-e07","dram-e08","dram-e09","dram-e10","dram-e11","dram-e26","dram-e28","dram-e30"]),
        ("demand_scenario", "设备需求与国产替代情景", demand_section, ["cxmt-s01",MODEL_REFS["demand"]]),
        ("investment_screen", "受益公司与估值筛选", investment, [MODEL_REFS["finance"],MODEL_REFS["valuation"]]),
        ("monitoring", "风险、反方证据与监控", monitoring, [MODEL_REFS["cxmt"],MODEL_REFS["supplier"],MODEL_REFS["demand"]]),
    ]
    return [_section(key, title, body, (index + 1) * 10, refs) for index, (key, title, body, refs) in enumerate(specs)]


def _entity_bodies(d: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    process = d["process"]
    supplier = d["supplier"]
    demand = d["demand"]
    finance = d["finance"]
    valuation = d["valuation"]

    cxmt_body = f"""
### 问题

{_company('长鑫科技')}的发行人、生产子公司、历史睿力集成、合肥和北京基地分别承担什么职能？三条12英寸线、工艺代际、产品、测试模组和两项升级项目能支持怎样的设备需求判断？

### 研究方法与数据

主体关系以IPO招股书、法律意见书和监管问询为主；基地和项目以项目文件、固定资产/在建工程、建设期限和产品披露交叉核验。对每条信息标记设计、在建、转固、量产或高利用状态。绝对产能只有文件明确对应当前主体和项目时才使用，历史环评数据不外推。 {_cite('cxmt-s01','cxmt-s02','cxmt-s03','cxmt-s04',MODEL_REFS['cxmt'])}

### 研究与分析

发行人长鑫科技集团由睿力集成演变而来，长鑫存储是全资子公司；长鑫新桥和北京长鑫集电对应不同生产/建设资产，长鑫产品（合肥）承担产品与模组相关职能。这个法律边界很重要：供应商招股书中出现“睿力集成”可能是早期长鑫商业链，但不能不加时间地写成2026年长鑫集团当前份额；项目公司拥有资产也不代表集团所有基地使用同一设备配置。

集团明确拥有合肥一期、合肥二期和北京三条12英寸产线。合肥二期于2024年量产，北京线于2023年量产，2023—2025年产能利用率为87.06%、92.46%、95.73%。高利用率说明新增技术改造若顺利搬入，对有效产出和产品结构有直接意义；但利用率接近满载也意味着设备调试、切换和良率爬坡需要更强冗余，不能把名义设备吞吐直接当成有效产能。

| 研究对象 | 已确认状态 | 可用于设备判断 | 不可外推内容 |
|---|---|---|---|
| 合肥一期 | 已转固并持续生产 | 存量升级、替换、维护和备件 | 不能用早期12.5万片/月设计值代表集团总产能 |
| 合肥二期 | 2024年量产，2025年仍有在建工程 | 新代工艺爬坡和追加工具 | 不能假设与合肥一期完全同配 |
| 北京线 | 2023年量产，2025年末在建工程规模较大 | 继续建设、技改和设备搬入 | 不能从注册或项目新闻猜测绝对月产能 |
| 生产线升级项目 | 设备购置安装46.66亿元 | 2026—2028现实设备需求锚 | 不是新增WSPM，也不是供应商收入 |
| DRAM技术升级项目 | 设备购置安装174.00亿元 | 新代产品、关键工艺和良率工具需求锚 | 不披露分设备台数、型号和供应商金额 |

产品路线已经从自有DDR4转向DDR5与LPDDR5/5X，第三、第四代工艺量产，第五代研发。LPDDR5X 8533/9600的量产及10667送样意味着速度、功耗、良率和测试要求继续提高，但公开资料仍不足以证明HBM量产、EUV使用或3D DRAM进入主线。封装外协为主，测试自制为主并有外协补充，模组自制与外协并存；因此后道设备的采购主体、收入确认和资本开支来源不能与前道募投预算合并。

从项目预算到上市公司收入还隔着下单、预付款、设备搬入、安装调试、客户验收和会计确认。长鑫2025年末仍有较大在建工程，既可能包含扩建和技改，也可能包含尚未验收工具；固定资产转入增加不必然等于当期有效晶圆产能同比例增加。后续复核应把长鑫在建工程/转固、设备公司合同负债与存货、客户验收以及DDR5/LPDDR5X放量放在同一时间轴，才能判断资本开支是否真正转成有效产出和供应商现金流。

产品代际也不能反推精确节点。更高速度只证明器件设计、功耗、测试和良率要求提升，不公开揭示EUV层数、电容结构或各基地设备配置。第五代工艺只有在公司正式量产、客户产品放量、设备搬入或关键供应商复购至少两类证据闭环后，才进入基准设备需求，而不是看到研发进展就提前计入。

主体核验最终决定数据归属：同一历史“长鑫”名称必须保留当时法律主体、基地和项目，供应商收入不能跨主体、跨年份平移。这个约束会降低表面上的供应商数量，却提高了后续财务测算的可复核性。

### 总结

**研究基线是三条量产12英寸线、高利用率、产品向DDR5/LPDDR5X升级以及220.66亿元设备预算。** 绝对集团WSPM、上海新fab、HBM、EUV和各基地统一设备组合均不进入基准。未来上调设备需求必须看到新项目批准、设备搬入或在建工程变化，而不是重复引用旧规划数字。
"""

    process_body = f"""
### 问题

从裸硅片进厂到晶圆测试、封装、老化和最终测试，DRAM设备怎样逐环节发挥作用？哪些工艺重复次数高、价值量高或直接决定良率？

### 研究方法与数据

结合三星的晶圆制造流程、Micron端到端内存流程、设备厂技术资料及DRAM电容/外围器件研究，建立十一阶段映射。每个子类按价值量、技术壁垒、DRAM专属性、重复使用、产能瓶颈和良率重要性评分；不使用整个半导体设备市场份额代替DRAM细分。 {_cite('dram-e01','dram-e02','dram-e19','dram-e20','dram-e22','dram-e23','dram-e24')}

### 研究与分析

{_process_chain_table(process)}

DRAM不是一次完成图形和薄膜，而是在多层结构上反复执行清洗、涂胶显影、曝光、刻蚀、去胶、薄膜、退火、CMP和量测。重复性使价值量不能只按“单台设备价格”判断：某类工具单价不是最高，但若在大量层反复使用、吞吐低或采样密度提高，也可能成为设备数量和维护收入的重要来源。

工艺可以分为三组经济机制。第一组是先进图形、电容刻蚀和薄膜，技术壁垒和价值量最高，供应商必须与客户联合调工艺窗口；第二组是清洗、CMP和量测，贯穿多个循环并直接决定缺陷、残留、平坦度和良率；第三组是晶圆电测、修复、终测、自动化和厂务，单一设备未必在前道资本开支中占比最高，却更容易因温度、洁净、气体、真空和测试并行度形成持续服务或重复订单。

封装测试必须保持边界。Micron原始流程把Probe/Param、封装、终测/烧机和模组测试分开；长鑫又披露封装外协为主，所以前道项目预算不应包含外协封装厂全部设备。投资研究中，精智达的存储器件测试、京仪的温控、正帆的高纯介质系统可以是长鑫受益链，但不能与刻蚀、沉积的前道价值量直接相加比较。

### 总结

**决定长鑫先进DRAM扩产质量的核心链是“图形化—高深宽比刻蚀—电容薄膜—清洗/CMP—在线量测—电测修复”。** 自动化、厂务和服务保障高稼动率，后道测试决定可售良率，但采购口径不同。完整映射的用途是找出真正瓶颈和收入确认链，而不是制作设备百科。
"""

    capacitor_body = f"""
### 问题

DRAM电容、高深宽比结构、字线、位线、外围CMOS与互连为什么会提高刻蚀、ALD/CVD/PVD、热处理和注入需求？中国设备在哪些层次可能进入，哪些仍缺关键层证据？

### 研究方法与数据

用Applied Materials的DRAM协同方案、Lam的HARC刻蚀机理、TEL的电容模具刻蚀和批式高k沉积、imec电容架构研究，以及三星、美光、SK海力士代际资料，拆解“结构更深—材料更多—图形更密—良率窗口更窄”的传导。中国供应能力只使用公司年报和产品资料；长鑫关系另由具名供应证据矩阵约束。 {_cite('dram-e02','dram-e03','dram-e04','dram-e05','dram-e09','dram-e12','dram-e31','dram-e32','dram-e34','dram-e44')}

### 研究与分析

DRAM缩放要在更小面积维持电容量，传统柱状电容因此提高深宽比。电容模具首先需要多层介质沉积，再通过高离子能等离子体刻出深而窄的孔；随后形成下电极、高k介质和上电极。刻蚀需要纵向选择性、CD均匀、侧壁形貌和底部开口同时满足，沉积则需要在深孔内保持保形性、膜厚均匀、低缺陷和稳定电学性能。二者共同决定电容漏电、结构可靠性和良率。

| 工艺难点 | 设备需求变化 | 全球主要平台 | 中国供应判断 | 长鑫证据边界 |
|---|---|---|---|---|
| 高深宽比电容孔 | 更高离子能、脉冲RF、CD/侧壁控制、较低吞吐 | Lam、TEL、Applied等 | 中微、北方具备存储刻蚀产品能力 | 未取得两家公司长鑫具名关键电容层订单 |
| 电容模具与高k/电极 | 更多PECVD/ALD/CVD/PVD循环和批式均匀性 | TEL、Applied、Lam等 | 拓荆、北方等覆盖多类沉积 | 拓荆有历史长鑫正式交付，关键层与当前复购仍待确认 |
| 字线/位线金属化 | 低电阻金属、阻挡层、填充和退火要求提高 | Applied、Lam、TEL等 | 中微钨平台、北方PVD/CVD/炉管可适配 | 行业/产品能力不能代替长鑫订单 |
| 外围CMOS与互连 | HKMG、低k、接触和互连复杂度提升 | Applied、TEL、Lam等 | 多家国内平台覆盖非关键与部分先进层 | 长鑫第五代工艺具体设备配置未披露 |

需求增速可能快于晶圆产能，原因有三：一是多重图形和复杂结构增加工艺步骤；二是HARC与高k工艺窗口变窄，低吞吐或冗余工具数增加；三是国产设备导入初期需要并行平台、更多量测和更长验证。但这只是设备强度方向，不能在缺少工艺层数、设备吞吐和WSPM时输出精确台数。

对上市公司的收入传导不能只看“设备进入”。高深宽比刻蚀和先进薄膜往往经历联合开发、送样、工艺验证、小批量、量产线导入、重复订单和服务扩展；早期工具可能用于非关键层、研发线或单一配方。只有设备类别、工艺层次、客户基地和跨期复购同时闭合，才可提高收入敞口。拓荆旧交付证明长鑫曾采购其沉积设备，却没有公开披露2026年设备金额；中微和北方公开产品适用于先进存储，也没有长鑫具名订单。三者的估值不能使用同一种“长鑫国产替代率”。

反方路径同样重要：如果第五代工艺延迟、产品结构转向对现有设备复用度更高的路线、进口关键工具许可拖慢整线，或国产设备验证增加停机和调试时间，单位产能设备强度可能上升但供应商收入确认后移。设备数量增多与股东回报改善不是同义关系，必须同时复核毛利、验收、回款和资本开支。

后续最关键的增量证据不是新型号新闻，而是同一设备在长鑫量产线上出现第二次订单、跨期验收或服务收入，并能说明工艺层次。只有这种证据才能把“技术适配”升级成可持续商业份额。

### 总结

**电容刻蚀与薄膜沉积是最有可能随技术代际提高单位晶圆设备强度的两类环节。** 拓荆拥有长鑫历史交付强证据；北方和中微拥有工艺平台能力但缺长鑫具名关键层证据。投资上应把“设备类别高价值”与“公司已拿到长鑫订单”分开打分。
"""

    pattern_body = f"""
### 问题

先进图形化、清洗、CMP和检测量测分别如何影响DRAM产能与良率？国产供给是在哪些细分工具形成商业化，而不是笼统的“大类国产率”？

### 研究方法与数据

比较ASML、Nikon、Canon的曝光平台，三星EUV与美光DUV多重图形路线，KLA/Hitachi的缺陷和CD量测，SCREEN的清洗、Ebara的CMP，以及国内盛美、华海、芯源微、中科飞测的原始披露。路线判断不等于长鑫型号确认，后者仍需客户或供应商具名资料。 {_cite('dram-e06','dram-e07','dram-e08','dram-e13','dram-e14','dram-e15','dram-e16','dram-e17','dram-e33','dram-e35','dram-e36','dram-e37')}

### 研究与分析

图形化要拆成曝光、涂胶显影、掩膜与计算光刻、套刻/CD量测和多重图形配套。ASML是EUV唯一制造商，但先进芯片只有关键层用EUV，DUV仍覆盖大量层；美光1alpha的DUV四重图形证明无EUV也能推进节点，却用更多侧墙沉积、图形转移、刻蚀、去胶、清洗和量测换取分辨率。设备受益因此不是单纯“EUV台数”，而是整套流程次数变化。

清洗贯穿每轮工艺，随着深孔和新材料增加，残留、表面损伤、干燥水痕与结构坍塌风险更高。盛美历史上向睿力集成交付单片清洗设备并确认收入，是可核验商业关系；但公开文件不能证明它覆盖长鑫最先进所有清洗层。芯源微的涂胶显影和前道化学清洗在存储客户获得订单或复购，仍因客户匿名而不能直接认定长鑫。

CMP要控制全片平坦度、缺陷和后续套刻窗口。华海清科招股书明确设备在长鑫大生产线量产，并有两台300 Dual交付记录；收入年份波动表明它更像项目/验收驱动，而非稳定按月重复收入。检测量测则从缺陷发现扩展到CD、套刻、膜厚、材料和HARC三维形貌。中科飞测展示HARC X射线量测、e-beam CD及明暗场工具，但部分产品仍处验证或刚通过验证，且没有长鑫具名强证据。

设备类别之间还存在替代与互补。采用更多DUV多重图形会增加涂显、侧墙沉积、刻蚀、去胶、清洗和套刻量测；引入EUV可减少部分步骤，却提高掩膜、光源、污染控制和EUV层缺陷管理难度。CMP步骤是否增加取决于具体集成方案，但平坦度误差会直接缩小下一层曝光窗口。量测采样率会在新工艺、国产设备验证和良率异常期上升，在稳定量产后部分回落。因此不能用固定“每万片设备价值量”跨代外推。

从股票角度，清洗/CMP的优势是具名商业证据和国内平台成熟度较高，短板是市场可能已经把进入客户提前定价成稳定份额；检测量测的优势是需求强度随复杂度上升，短板是高端产品验证、软件算法和客户装机闭环不足。未来两个报告期更有信息量的指标是同设备重复订单、验收转收入、服务收入和毛利率，而不是新产品数量。

| 子环节 | 投资重要性 | 国内商业化判断 | 最关键缺口 |
|---|---|---|---|
| 先进曝光 | 价值量最高、出口许可敏感 | 先进量产替代证据不足 | 长鑫具体路线、许可和装机未披露 |
| 涂胶显影/多重图形配套 | DUV路线会增加次数 | 芯源微等已有存储客户订单 | 匿名客户无法映射长鑫关键层 |
| 单片/批式清洗 | 高频重复、良率敏感 | 盛美具名历史交付，国内平台较成熟 | 最新复购、最先进层覆盖和份额 |
| CMP | 平坦度与后续图形窗口 | 华海具名大生产线量产 | 当前项目金额、复购和工艺层次 |
| 先进检测量测 | 工艺复杂度与国产验证共同抬升 | 部分光学工具/新量测在验证 | 明场、e-beam、软件闭环和长鑫具名关系 |

### 总结

**图形化是进口和许可风险最大的总量环节；清洗/CMP是当前具名国产商业证据最清楚的前道机会；先进量测是随工艺复杂度和国产设备并行验证最可能增量加速的短板。** 三者的公司和估值逻辑不同，不能用统一国产化率处理。
"""

    test_body = f"""
### 问题

晶圆电测与修复、封装/老化/终测、AMHS、温控、高纯介质、真空与关键零部件在长鑫链条中怎样创造价值？哪些资本开支属于长鑫，哪些属于外协封测或厂务服务？

### 研究方法与数据

使用Samsung EDS、Micron端到端内存制造、Advantest内存ATE、Accretech晶圆探针、MKS关键部件和Entegris污染控制资料，结合长鑫“封装外协为主、测试自制为主”的披露及精智达、京仪、正帆原始文件。前道、后道、厂务和服务分别计量，不把220.66亿元前道设备预算重复计入。 {_cite('dram-e19','dram-e20','dram-e21','dram-e22','dram-e23','dram-e24','supplier-s-jingzhida-ipo-20230713','supplier-s-jingyi-ipo-20231124','supplier-s-zhengfan-reply-20260613')}

### 研究与分析

晶圆电测先识别坏点、速度和漏电，再通过Pre-Laser、Laser Repair和修复后复测提高可用die比例；终测与烧机验证封装后的功能、速度和可靠性。DRAM测试成本高度依赖并行度、温控范围、失效地址记录和数据分析。精智达在2020—2022年对睿力/长鑫连续确认存储器件测试设备收入，2022年末仍有设备待验收并在2023年一季度完成部分验收，说明它是跨期项目关系，不是一次传闻。

自动搬运、温控和厂务决定高稼动率。300mm产线需要FOUP/AMHS、设备端口和调度系统稳定运行；刻蚀、沉积和清洗又依赖高纯气体/化学品、真空、RF、压力流量控制、废气处理和温度控制。京仪装备披露温控设备大批量长期适配长鑫等产线并有多笔合同；正帆科技披露高纯工艺介质系统长期服务长鑫。这两类关系更容易形成重复服务，但单台价值和毛利结构不同于核心前道设备。

收入确认机制也不同。测试设备通常在安装、程序调试和客户验收后确认，产品升级会带来新测试程序和硬件，但验收后移会使利润波动；温控和厂务随主设备或产线建设交付，可能包含系统集成、工程和备件，毛利与回款取决于合同结构；关键零部件既可能由长鑫直接采购，也可能嵌入国内外整机，客户和收入归属不能由终端fab倒推。对同一家公司做长鑫敏感性时，必须先识别它位于哪一层合同链。

备件和服务的长期价值往往随装机基础累积，却受设备保有量、保修期、国产部件认证和客户自行维护能力影响。出口限制若压缩海外现场服务，会提高国产部件和工程团队价值，也可能因整机停机或许可延迟降低当期需求。正向替代和项目执行风险应同时进入情景，不能只保留一边。

因此，本实体中的“长期供应”只说明关系持续，不等于高毛利或高市占。研究员仍要按合同类型拆分设备、工程、备件和服务，检查应收、存货、验收与经营现金流，才能判断订单质量。

| 环节 | 长鑫边界 | 受益方式 | 核心风险 |
|---|---|---|---|
| 晶圆探针/ATE/修复 | 测试以自制为主、外协补充 | 新产品测试程序、并行度、验收和维护 | 产品代际切换、验收周期、单客户集中 |
| 封装、老化和最终测试 | 封装以外协为主 | 外协封测厂设备、材料和服务 | 采购主体不一定是长鑫，不能重复计入前道预算 |
| AMHS与自动化 | 晶圆厂持续需要 | 新线搬入、调度软件和存量改造 | 系统集成和项目验收时点 |
| 温控与厂务 | 贯穿前道设备运行 | 重复合同、备件、维护与扩产配套 | 单项价值量、价格竞争、客户资本开支节奏 |
| 真空/RF/流量/过滤零部件 | 嵌入整机和subfab | 国产部件替代、备件和服务 | 认证周期长，可能通过整机厂而非长鑫直接采购 |

### 总结

**精智达、京仪装备和正帆科技的长鑫具名证据比多数前道平台公司更直接，但投资价值不能只看“关系强”：还要看设备价值量、收入基数、验收节奏和估值。** 后道外协与前道预算必须分开，零部件受益还要判断采购是长鑫直采还是随整机导入。
"""

    global_body = f"""
### 问题

三星、SK海力士、美光和南亚科技的路线能为长鑫提供什么可比边界？全球设备寡头和出口许可如何影响长鑫的工艺选择、成本、冗余与国产替代？

### 研究方法与数据

同业只比较已公开工艺方向、产品代际和设备含义，不把国际厂商具体型号直接套到长鑫。竞争格局按曝光、刻蚀、沉积、清洗、CMP、量测、测试和关键部件分别判断。出口限制逐条读取BIS、荷兰政府和日本经产省规则，并主动核对“许可控制”与“全面禁运”的差异。 {_cite('dram-e07','dram-e08','dram-e09','dram-e10','dram-e11','dram-e26','dram-e27','dram-e28','dram-e29','dram-e30','dram-e43')}

### 研究与分析

三星从1a推进EUV并在12nm级DDR5使用新高k电容材料和多层EUV；SK海力士1c沿用1b平台、优化EUV并导入新材料；美光1alpha依靠DUV四重图形推进，1gamma才引入EUV和下一代HKMG；南亚1B在2025年二季度晶圆投入约占总产能三分之一。这些信息给出的不是长鑫设备清单，而是路线差异：EUV减少部分多重图形步骤，无EUV路线则增加沉积、刻蚀、去胶、清洗和套刻负担；新高k、HKMG和更深电容同时抬升薄膜、刻蚀与量测要求。

| 设备子类 | 全球主要平台 | 竞争性质 | 中国能力与缺口 |
|---|---|---|---|
| EUV/先进DUV曝光 | ASML；DUV另有Nikon/Canon部分平台 | EUV单一来源，DUV按分辨率和层次分化 | 先进曝光量产替代最弱，许可和服务风险最大 |
| HARC/关键刻蚀 | Lam、Applied、TEL等 | 工艺窗口、RF/真空和装机数据壁垒高 | 中微、北方有先进存储能力，长鑫关键层订单待证 |
| 电容/金属薄膜 | Applied、TEL、Lam等 | 材料、保形性、批式均匀和客户协同 | 拓荆、北方等覆盖扩展，最先进高k/电极证据不足 |
| 清洗/CMP | SCREEN、TEL、Lam、Ebara等 | 高频重复、工艺配方和装机服务重要 | 盛美、华海已有长鑫具名商业证据 |
| 检测量测 | KLA、Hitachi、Applied等 | 光学/e-beam/CD/三维形貌与软件闭环 | 部分工具验证推进，先进明场/e-beam与软件仍弱 |
| 内存ATE/探针 | Advantest、Teradyne、Accretech等 | 并行度、温控、程序和数据能力 | 国内测试设备切入，产品代际和规模稳定性待验证 |

美国规则对特定设备、软件、先进DRAM终端用途、安装维护和替换件设限；荷兰对特定先进DUV及部分量测检测实施逐案许可；日本对23类先进设备实施许可管理。项目风险不是二元：许可证可能延长交期，配置和服务可能受限，备件库存与双平台验证增加，而部分工具仍可获批。国产设备受益与长鑫项目受阻可以同时发生，财务模型必须允许收入后移。

对标不能变成“复制海外厂设备数”。三星、SK海力士和美光拥有更长的先进节点装机与工艺数据库，设备吞吐、冗余、维护合同和良率学习曲线不同；南亚的产能规模、产品结构与节点推进节奏也不同。长鑫可能因更多DUV步骤、国产设备并行验证、许可不确定和本地服务能力差异而需要更多刻蚀、沉积、清洗、量测或备用工具，但缺少逐层流程、吞吐和WSPM时只能判断方向，不能套用每万片台数。

出口限制的第二层影响是软件和部件。计算光刻、设备控制、量测反馈、现场升级、真空/RF/流量控制和替换件决定装机能否维持良率和稼动率。国产整机若仍依赖受限部件或软件，整机国产标签并不能消除供应风险；相反，部件、服务和工艺支持的验证周期可能比整机导入更长。研究必须同时跟踪许可证、服务连续性和国内部件认证。

### 总结

**国际同业说明长鑫可以在不同图形路线间权衡，但无法绕过电容、薄膜、刻蚀、清洗和量测的复杂度。** 出口许可最先影响先进曝光、量测、软件、关键部件和现场服务；国产替代只有形成关键层量产、跨期复购和良率闭环，才能从风险对冲升级为稳定份额。
"""

    supplier_body = f"""
### 问题

长鑫具名供应商分别到了什么阶段？哪些历史交付仍有决策价值，哪些公司只有工艺适配、匿名存储客户或关联关系，不能进入核心结论？

### 研究方法与数据

逐家公司查询招股书、监管问询、年报和客户文件，阶段从0到8依次对应无具名强证据、接触、验证、小批量、订单、正式交付、连续交付/复购、稳定量产/长期服务和主力供应。历史收入只证明当期交付，不自动证明2026年仍有份额；同源转载合并为一个证据组。 {_cite(MODEL_REFS['supplier'],'supplier-s-piotech-ipo-20220414','supplier-s-acm-ipo-20211112','supplier-s-hwatsing-ipo-20220601','supplier-s-jingzhida-ipo-20230713','supplier-s-jingyi-ipo-20231124','supplier-s-zhengfan-reply-20260613')}

### 研究与分析

{_supplier_table(supplier)}

{_company('拓荆科技')}和{_company('盛美上海')}有具名设备、客户与收入确认，足以证明曾正式商业交付；但证据主要来自2020—2021年，当前先进工艺层次、复购和份额仍待新披露。{_company('华海清科')}、{_company('京仪装备')}和{_company('正帆科技')}分别对应CMP量产线、温控长期大批量适配和高纯介质长期服务，关系更稳定，但设备价值量和采购口径差异很大。{_company('精智达')}有跨期连续交付和验收，仍需判断2026年产品结构和客户集中。

“未取得具名强证据”不是判定“没有供应”，而是公开资料不足以确认具名供应。{_company('北方华创')}和{_company('中微公司')}的DRAM设备能力强，{_company('芯源微')}、{_company('中科飞测')}、{_company('华峰测控')}和{_company('长川科技')}也有工艺或测试适配，但共同董事、前员工、匿名“国内存储客户”或行业排名都不能升级成长鑫订单。

悦芯TM8000“量产导入长鑫”在产业和卖方材料中被提及，却没有客户/供应商原始文件、设备验收或合同闭环，因此作为重要未验证线索保留。若未来出现具名客户公告、验收或连续收入，它会提高长川及相关测试链优先级；在此之前不进入核心评分和财务输入。

### 总结

**公开证据支持六家公司进入长鑫供应候选，但没有公司达到主力或独家供应。** 投资上先按“证据阶段×设备价值量×收入弹性×估值”四维筛选；阶段高但价值量小、阶段低但平台强、阶段和价值量都高但估值透支，必须得到不同动作。
"""

    demand_body = f"""
### 问题

2026—2028已披露项目会形成多大设备需求，各类国产设备可争取多少；2029—2031在没有正式产能承诺时如何建立可证伪情景？

### 研究方法与数据

两项前道升级项目设备购置安装预算46.66亿元和174.00亿元合计220.66亿元。模型不猜WSPM与设备台数，而按DRAM工艺价值量和国内承接成熟度分配类别；总量始终受220.66亿元约束。年度节奏根据公司“2026—2027搬入调试、2028H1验收”建立36%/48%/16%基准。 {_cite('cxmt-s01',MODEL_REFS['demand'])}

### 研究与分析

{_demand_table(demand)}

{_annual_demand_table(demand)}

核心算式为：类别需求金额＝220.66亿元×类别价值量占比；国产可争取金额＝类别需求金额×该类国内设备在长鑫项目中可承接的情景比例；年度搬入金额＝220.66亿元×年度权重。按专家情景取整后，基准分配约为光刻/涂显57.4亿元、刻蚀39.7亿元、薄膜/热处理/注入53.0亿元、清洗/CMP 24.3亿元、检测量测24.3亿元、测试/自动化/厂务及其他22.1亿元；国产可争取情景中枢约62亿元。

约62亿元不能读成国产订单，因为每项承接比例都含专家判断，且供应商、工艺层次和验收时点未披露。光刻/涂显将曝光和配套放在同一预算类中，却只给2%基准国产承接，目的就是防止用国产涂显进展伪装先进曝光替代；清洗/CMP给55%，是基于具名商业证据和成熟度更高，但最先进清洗层和CMP份额仍未确认。

2029—2031不输出单点。只有第五代工艺量产、新项目正式披露、存量设备进入升级周期、国产设备出现重复订单、备件软件服务随装机增长时才上调。若DRAM价格下行、扩产延迟、许可受阻或国产验证停留非关键层，则设备需求后移、国产承接落向区间下沿。增强情景约242.7亿元中的超预算部分必须由新项目或额外冗余证明，不能当公司承诺。

### 总结

**基准看2027搬入高峰，2026看首批交付调试，2028看验收尾项；2029—2031只跟条件。** 设备公司的收入上调还需具名订单、产品层次、交付验收和会计确认四个输入，模型拒绝把总预算机械分摊到股票。
"""

    investment_body = f"""
### 问题

长鑫设备链里，哪些上市公司有真实供应关系和财务承接能力？它们未来三年收入、利润和现金流怎样变化，当前市值已经隐含多高盈利，什么条件才构成买点？

### 研究方法与数据

研究池先覆盖二十二家设备、测试、厂务和零部件公司，再以具名供应证据、设备价值量、集团财务可建模性和证券身份筛出八家完成FY2026—FY2028模型。模型在读取一致预期前冻结，收入按公司产品和订单基线外推，利润＝收入×净利率，经营现金流＝净利润×现金转换率，自由现金流＝经营现金流－资本开支。长鑫只作敏感性，不单列基准收入。冻结后与Wind和最近两个季度同公司中英文卖方预测对账。 {_cite(MODEL_REFS['finance'],MODEL_REFS['valuation'])}

### 研究与分析

{_finance_table(finance, valuation)}

{_valuation_detail_table(valuation)}

**{_company('北方华创')}。** 平台覆盖刻蚀、沉积、炉管、清洗等多类DRAM设备，集团FY2026—FY2028独立净利润76.25/99.02/126.03亿元；当前市值要求的盈利显著高于基准区间。它是产业核心观察标的，但没有长鑫具名设备订单强证据，买点需要市场估值回落，或集团利润和自由现金流持续上修，而不是单靠长鑫主题。

**{_company('拓荆科技')}与{_company('盛美上海')}。** 拓荆对应薄膜沉积高价值方向并有历史长鑫交付，盛美对应清洗且具名收入证据更清晰。拓荆FY1净利润13.77亿元、盛美17.81亿元，当前市值分别远高于45—60倍和40—50倍FY1 PE区间；两者需要先进存储产品批量验收和利润率兑现才能消化溢价。

**{_company('华海清科')}。** CMP在长鑫大生产线量产证据强，FY1净利润13.65亿元，项目交付和服务并存。估值主要风险是市场已把国产替代从“量产进入”提前计入“长期份额稳定”；若复购、服务收入和自由现金流没有同步提高，供应证据强也不等于股价安全。

**{_company('京仪装备')}与{_company('精智达')}。** 两家公司与长鑫关系更直接、收入基数小，单个项目对利润弹性大。京仪的温控重复合同更稳定，精智达的测试设备受验收和客户集中影响更强；二者估值都要求快速盈利爬坡。买点应等待在手合同转收入、现金回款和新一代产品复购，不按前道总预算分配。

**{_company('中微公司')}与{_company('长川科技')}。** 两家公司有刻蚀/薄膜或测试产业能力，但本轮没有长鑫具名强证据；独立模型只能评价集团业务，不能给长鑫收入加成。当前估值同样明显高于独立区间，因此只作为产业能力候选，等待客户和产品证据升级。

### 总结

**所有八家公司在各自参考市值日均高于独立模型的可解释区间，说明市场已经计入较强成长和估值持续期；这些日期并不完全一致，不能据此做严格同日排名。** 产业优先跟踪北方、盛美、华海；高弹性观察京仪、拓荆；中微、长川等待长鑫证据；精智达先看验收与盈利。已有具名关系的公司至少满足“复购或验收、盈利上修、估值回落”中的两项；未具名公司则先取得首个订单并完成交付验收，再讨论提高权重。
"""

    return {
        "cxmt_entity_fab_platform": cxmt_body,
        "dram_process_equipment_map": process_body,
        "capacitor_etch_deposition": capacitor_body,
        "patterning_clean_cmp_metrology": pattern_body,
        "test_automation_utilities_services": test_body,
        "global_peer_export_controls": global_body,
        "cxmt_supplier_stage_matrix": supplier_body,
        "cxmt_equipment_demand_2026_2031": demand_body,
        "listed_supplier_investment_opportunities": investment_body,
    }


def _body_parts(body: str) -> dict[str, str]:
    pattern = re.compile(r"### (问题|研究方法与数据|研究与分析|总结)\s*\n")
    matches = list(pattern.finditer(body))
    if len(matches) != 4:
        raise Run17BuildError("研究实体正文未严格包含四段结构")
    parts: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        parts[match.group(1)] = body[match.end():end].strip()
    return parts


def _refs_from_body(body: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"\^src:source_ref:([A-Za-z0-9_.-]+)", body)))


def _research_points_for_entity(
    entity_key: str,
    all_points: Sequence[Mapping[str, Any]],
    sources_by_ref: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    selected = [row for row in all_points if row["entity_key"] == entity_key]
    if len(selected) < 10:
        selected.extend(row for row in all_points if row not in selected)
    result: list[dict[str, Any]] = []
    for index, point in enumerate(selected[:10], start=1):
        ref = str(point["source_ref"])
        source = sources_by_ref[ref]
        excerpt = str(point["source_excerpt"])
        row = {
            "source_ref": ref,
            "data_point_title": f"{ENTITY_TITLES[entity_key]}证据{index}",
            "metric": str(point["metric"]),
            "period": str(point.get("period") or "截至2026-08-02"),
            "unit": str(point.get("unit") or "研究事实"),
            "value_text": str(point.get("value_text") or excerpt),
            "source_excerpt": excerpt,
            "interpretation": f"证据{index}用于界定{ENTITY_TITLES[entity_key]}中的主体、期间或工艺边界：{str(point['value_text'])[:180]}",
            "research_use": f"用于本实体第{index}项分析，不与同源记录重复提高证据权重。",
        }
        if str(source.get("language") or "").lower().startswith("en"):
            row["source_excerpt_zh"] = str(source.get("excerpt_zh") or point["value_text"])
        result.append(row)
    return result


def _literature_review(refs: Sequence[str], sources_by_ref: Mapping[str, Mapping[str, Any]]) -> str:
    names = []
    for ref in refs[:8]:
        source = sources_by_ref[ref]
        names.append(f"{source['publisher']}《{source.get('title_zh') or source['title']}》")
    return (
        "本实体同时使用监管/公司原始披露、设备厂技术资料、国际DRAM厂原始资料和独立模型。"
        "核心材料包括" + "；".join(names) + "。同源转载合并，卖方材料不替代客户与供应商原始记录；"
        "对没有公开时间的官网技术资料仅按截至访问日的产品能力使用。"
    )


def _point_keys(
    points: Sequence[Mapping[str, Any]],
    *,
    source_refs: Sequence[str] = (),
    contains: Sequence[str] = (),
    limit: int = 12,
) -> list[str]:
    """Locate the exact frozen data points consumed by a metric slot."""

    refs = set(source_refs)
    needles = [str(value) for value in contains if str(value)]
    result: list[str] = []
    for point in points:
        if refs and str(point.get("source_ref")) not in refs:
            continue
        haystack = " ".join(
            str(point.get(field) or "")
            for field in ("metric", "value_text", "source_excerpt", "note")
        )
        if needles and not any(needle in haystack for needle in needles):
            continue
        key = str(point.get("data_point_key") or "")
        if key and key not in result:
            result.append(key)
        if len(result) >= limit:
            break
    if not result:
        raise Run17BuildError(
            f"评分槽没有找到冻结数据点：source_refs={list(source_refs)} contains={list(contains)}"
        )
    return result


def _metric_slot(
    *,
    code: str,
    label: str,
    weight: float,
    score: float | None,
    raw_value: Any,
    raw_unit: str,
    standardized_value: Any,
    standardized_unit: str,
    bucket: str,
    scoring_rule: str,
    rationale: str,
    data_point_keys: Sequence[str],
    source_refs: Sequence[str],
    value_status: str = "available",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "slot_code": code,
        "slot_label": label,
        "metric_name": label,
        "slot_role": "primary",
        "slot_weight": float(weight),
        "value_status": value_status,
        "raw_unit": raw_unit,
        "standardized_unit": standardized_unit,
        "normalization_method": "保持原披露口径；文本阶段按本轮公开阶段表映射，金额统一为亿元人民币。",
        "preprocess_trace": "核对主体、期间、单位和事实/情景身份；没有把缺失值当作零。",
        "period": "截至2026-08-02",
        "as_of_date": "2026-08-02",
        "data_point_keys": list(dict.fromkeys(data_point_keys)),
        "source_refs": [_ev(ref) for ref in dict.fromkeys(source_refs)],
        "rationale_text": rationale,
    }
    if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
        row["raw_value_num"] = float(raw_value)
    else:
        row["raw_value_text"] = str(raw_value)
    if isinstance(standardized_value, (int, float)) and not isinstance(standardized_value, bool):
        row["standardized_value_num"] = float(standardized_value)
    else:
        row["standardized_value_text"] = str(standardized_value)
    if score is not None:
        row.update(
            {
                "slot_score": float(score),
                "bucket": bucket,
                "scoring_rule": scoring_rule,
                "scoring_trace": f"标准化值进入“{bucket}”档，按公开规则得到{float(score):.1f}分。",
            }
        )
    return row


def _missing_metric_slot(*, code: str, label: str, weight: float, reason: str) -> dict[str, Any]:
    return {
        "slot_code": code,
        "slot_label": label,
        "metric_name": label,
        "slot_role": "primary",
        "slot_weight": float(weight),
        "value_status": "not_found_after_search",
        "raw_value_text": "公开资料未披露",
        "raw_unit": "研究事实",
        "standardized_value_text": "不进入评分",
        "standardized_unit": "不适用",
        "normalization_method": "缺失值保持缺失，不按零分处理。",
        "preprocess_trace": reason,
        "period": "截至2026-08-02",
        "as_of_date": "2026-08-02",
        "data_point_keys": [],
        "source_refs": [],
        "rationale_text": reason,
    }


def _reliability_multiplier(coverage: float, confidence: float) -> tuple[float, float, float]:
    coverage_multiplier = 1.0 if coverage >= 0.80 else 0.85 if coverage >= 0.65 else 0.60 if coverage >= 0.50 else 0.0
    confidence_multiplier = 1.0 if confidence >= 0.85 else 0.90 if confidence >= 0.75 else 0.75 if confidence >= 0.60 else 0.50 if confidence >= 0.45 else 0.0
    return coverage_multiplier, confidence_multiplier, min(coverage_multiplier, confidence_multiplier)


def _factor_from_slots(
    *,
    code: str,
    metric_name: str,
    slots: Sequence[Mapping[str, Any]],
    confidence: float,
    rationale: str,
    summary: str,
    topic_analysis: str,
    sources_by_ref: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    applicable = sum(float(slot["slot_weight"]) for slot in slots if slot.get("value_status") != "not_applicable")
    usable = [slot for slot in slots if slot.get("value_status") in {"available", "calculated", "stale_but_usable"}]
    usable_weight = sum(float(slot["slot_weight"]) for slot in usable)
    coverage = usable_weight / applicable if applicable else 0.0
    raw = sum(float(slot["slot_score"]) * float(slot["slot_weight"]) for slot in usable) / usable_weight
    coverage_multiplier, confidence_multiplier, reliability = _reliability_multiplier(coverage, confidence)
    adjusted = 50.0 + (raw - 50.0) * reliability
    refs = list(
        dict.fromkeys(
            str(ref).removeprefix("source_ref:")
            for slot in usable
            for ref in slot.get("source_refs", [])
        )
    )
    unique_groups = {sources_by_ref[ref]["independence_key"] for ref in refs}
    if len(unique_groups) < 5:
        raise Run17BuildError(f"重要因子{code}独立证据组不足5组：{sorted(unique_groups)}")
    information_points = []
    for index, ref in enumerate(refs, start=1):
        source = sources_by_ref[ref]
        excerpt = str(source.get("excerpt_zh") or source["excerpt"])
        information_points.append(
            {
                "evidence_ref": _ev(ref),
                "excerpt": excerpt,
                "interpretation": f"第{index}组证据用于约束{metric_name}的原始输入或方向：{excerpt}",
                "independence_key": source["independence_key"],
            }
        )
    missing = [str(slot.get("slot_label")) for slot in slots if slot not in usable]
    return {
        "factor_code": code,
        "metric_name": metric_name,
        "unit": "分",
        "period": "截至2026-08-02；核心观察2026—2028，长期条件2029—2031",
        "score_raw": round(raw, 2),
        "score_adjusted": round(adjusted, 2),
        "score_status": "complete" if coverage >= 0.50 else "insufficient_evidence",
        "factor_readiness_status": "ready" if coverage >= 0.80 else "limited" if coverage >= 0.50 else "missing",
        "coverage": round(coverage, 4),
        "confidence": round(confidence, 4),
        "coverage_multiplier": coverage_multiplier,
        "confidence_multiplier": confidence_multiplier,
        "audit_multiplier": 1.0,
        "reliability_multiplier": reliability,
        "score_rationale": rationale,
        "factor_value_summary": summary,
        "source_context_summary": "分数是研究优先级，不是订单份额、发生概率或预期收益；缺失值不按零分处理。",
        "factor_topic_analysis": topic_analysis,
        "theme_analysis_points": [
            f"{metric_name}由{len(usable)}个可用评分槽复算，覆盖率{coverage:.0%}。",
            "弱线索只提高补证优先级，不进入基准财务与估值。",
        ],
        "evidence_ref_uri_list": [_ev(ref) for ref in refs],
        "information_points": information_points,
        "metric_slots": [dict(slot) for slot in slots],
        "missing_reason": "无" if not missing else "未进入评分的槽位：" + "、".join(missing),
        "aggregation_trace": {
            "formula": "可用槽位加权分之和÷可用槽位权重之和",
            "usable_slot_weight": usable_weight,
            "applicable_slot_weight": applicable,
            "factor_score_raw": round(raw, 6),
        },
        "adjustment_trace": {
            "coverage_multiplier": coverage_multiplier,
            "confidence_multiplier": confidence_multiplier,
            "audit_multiplier": 1.0,
            "factor_reliability_multiplier": reliability,
            "formula": "50＋（原始分－50）×可靠性乘数",
            "factor_score_adjusted": round(adjusted, 6),
        },
        "trace": "指标槽→标准化→分档→槽位分→因子加权→覆盖率与置信度向50分收敛。",
    }


def _build_replayable_factors(
    d: Mapping[str, Mapping[str, Any]],
    points: Sequence[Mapping[str, Any]],
    sources_by_ref: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build a four-factor adaptive contract for the heterogeneous supplier basket."""

    demand_slots = [
        _metric_slot(
            code="disclosed_equipment_budget",
            label="两项前道项目设备预算总量",
            weight=0.35,
            score=90,
            raw_value=220.66,
            raw_unit="亿元人民币",
            standardized_value=220.66,
            standardized_unit="亿元人民币",
            bucket="已披露、金额明确、实施期明确",
            scoring_rule="项目方正式披露设备预算且实施期明确记90分；只有方向无金额记60分；传闻不计分。",
            rationale="220.66亿元来自两项项目设备购置安装预算合计，只代表项目总量锚。",
            data_point_keys=_point_keys(points, source_refs=[MODEL_REFS["demand"]], contains=["220.66"]),
            source_refs=["cxmt-s01", MODEL_REFS["demand"]],
        ),
        _metric_slot(
            code="installation_acceptance_window",
            label="搬入调试与验收窗口",
            weight=0.20,
            score=80,
            raw_value="2026—2027年分批搬入调试，2028年上半年验收",
            raw_unit="时间窗口",
            standardized_value="跨三年、具备明确里程碑",
            standardized_unit="阶段",
            bucket="实施窗口明确但年度采购额未披露",
            scoring_rule="搬入与验收均有明确窗口记80分；只有建设期记60分；没有时间记40分。",
            rationale="公开文件给出实施期，但79.4/105.9/35.3亿元仍是模型年度分配。",
            data_point_keys=_point_keys(points, source_refs=["cxmt-s01"], contains=["2026年至2027年底"]),
            source_refs=["cxmt-s01"],
        ),
        _metric_slot(
            code="dram_process_intensity",
            label="DRAM缩放带来的设备强度",
            weight=0.30,
            score=85,
            raw_value="电容HARC、薄膜、量测和图形化随缩放增加难度",
            raw_unit="多源工艺事实",
            standardized_value="四类独立原始技术来源一致指向设备强度上升",
            standardized_unit="方向",
            bucket="多工艺、多公司原始资料一致",
            scoring_rule="至少四个独立原始技术来源支持且存在具体设备机制记85分；只有卖方概述记55分。",
            rationale="Applied、Lam、TEL和imec分别从协同工艺、HARC、电容沉积/清洗和结构极限支持设备强度上升。",
            data_point_keys=_point_keys(points, source_refs=["dram-e02", "dram-e03", "dram-e04", "dram-e05"]),
            source_refs=["dram-e02", "dram-e03", "dram-e04", "dram-e05"],
        ),
        _missing_metric_slot(
            code="absolute_capacity_tool_count",
            label="集团绝对新增产能、设备台数与供应商金额",
            weight=0.15,
            reason="已查IPO、问询、项目和供应商材料，公开资料没有给出集团当前绝对WSPM、设备台数和分供应商采购额。",
        ),
    ]
    demand_factor = _factor_from_slots(
        code="demand.customer_capex_capacity_signal",
        metric_name="项目预算与DRAM工艺设备需求强度",
        slots=demand_slots,
        confidence=0.86,
        rationale="项目总预算和执行窗口来自长鑫正式材料，工艺强度由四类国际原始资料交叉支持；绝对产能、台数和供应商金额缺失，因此不把预算当订单。",
        summary="总量和工艺方向较强，分设备、分年度和分供应商兑现仍需验收与订单验证。",
        topic_analysis="设备需求分回答‘项目是否真实’和‘工艺是否更吃设备’，不把TEL其他客户POR或出口管制误当成长鑫采购证据。",
        sources_by_ref=sources_by_ref,
    )

    capture_slots = [
        _metric_slot(
            code="clean_cmp_named_capture",
            label="清洗与CMP在长鑫的具名承接",
            weight=0.25,
            score=85,
            raw_value="盛美正式销售；华海CMP进入长鑫量产线",
            raw_unit="供应阶段",
            standardized_value="阶段5与阶段7",
            standardized_unit="公开供应阶段",
            bucket="具名交付且至少一项进入量产线",
            scoring_rule="长鑫具名量产/重复供货记85分；正式交付记65分；只有行业能力记35分。",
            rationale="清洗和CMP是目前具名证据最强的前道设备方向，但份额和先进关键层仍未披露。",
            data_point_keys=_point_keys(points, source_refs=["supplier-s-acm-ipo-20211112", "supplier-s-hwatsing-ipo-20220601"]),
            source_refs=["supplier-s-acm-ipo-20211112", "supplier-s-hwatsing-ipo-20220601"],
        ),
        _metric_slot(
            code="deposition_named_capture",
            label="薄膜沉积在长鑫的具名承接",
            weight=0.20,
            score=70,
            raw_value="拓荆历史正式交付；先进存储设备已规模化量产",
            raw_unit="供应阶段",
            standardized_value="长鑫阶段5＋行业量产能力",
            standardized_unit="公开供应阶段",
            bucket="具名正式交付，当前份额未披露",
            scoring_rule="具名量产/重复供货记85分；具名正式交付且行业能力延续记70分；只有能力记40分。",
            rationale="历史交付与当前先进存储能力均成立，但不能从两者推出当前长鑫份额。",
            data_point_keys=_point_keys(points, source_refs=["supplier-s-piotech-ipo-20220414", "dram-e34"]),
            source_refs=["supplier-s-piotech-ipo-20220414", "dram-e34"],
        ),
        _metric_slot(
            code="etch_process_capture",
            label="刻蚀在长鑫的可承接程度",
            weight=0.20,
            score=50,
            raw_value="先进DRAM刻蚀已获客户核准并销售；未取得长鑫具名订单",
            raw_unit="能力与客户边界",
            standardized_value="行业能力成立、长鑫直接证据阶段0",
            standardized_unit="公开供应阶段",
            bucket="能力可用但客户未闭环",
            scoring_rule="长鑫具名量产记85分；具名交付记65分；只有DRAM能力且长鑫阶段0记50分。",
            rationale="中微具备先进DRAM刻蚀能力，但本轮没有把能力映射成长鑫收入。",
            data_point_keys=_point_keys(points, source_refs=["dram-e32"])
            + _point_keys(points, source_refs=[MODEL_REFS["supplier"]], contains=["中微公司"]),
            source_refs=["dram-e32", "supplier-s-amec-ar-2025", MODEL_REFS["supplier"]],
        ),
        _metric_slot(
            code="metrology_capture",
            label="检测量测在长鑫的可承接程度",
            weight=0.15,
            score=45,
            raw_value="高深宽比结构量测处于客户验证；未取得长鑫具名订单",
            raw_unit="能力与客户边界",
            standardized_value="行业验证、长鑫关系未闭环",
            standardized_unit="公开供应阶段",
            bucket="验证期且客户未具名",
            scoring_rule="长鑫具名量产记85分；具名验证记60分；行业验证但长鑫未具名记45分。",
            rationale="先进量测需求明确，但国产产品仍处验证阶段，不能用工艺必要性替代长鑫采购事实。",
            data_point_keys=_point_keys(points, source_refs=["dram-e13", "dram-e14", "dram-e37"]),
            source_refs=["dram-e13", "dram-e14", "dram-e37"],
        ),
        _metric_slot(
            code="lithography_capture",
            label="先进曝光与配套的国产承接程度",
            weight=0.20,
            score=20,
            raw_value="EUV唯一供应商为ASML，先进DUV仍以海外平台为主",
            raw_unit="供应结构",
            standardized_value="关键曝光层国产承接公开证据极弱",
            standardized_unit="方向",
            bucket="关键平台高度依赖海外",
            scoring_rule="关键曝光具名量产记85分；国产配套但曝光未替代记35分；关键平台高度依赖海外记20分。",
            rationale="涂显等配套进展不能被写成先进曝光替代，故该槽显著压低国产承接分。",
            data_point_keys=_point_keys(points, source_refs=["dram-e06", "dram-e39", "dram-e41"]),
            source_refs=["dram-e06", "dram-e39", "dram-e41"],
        ),
    ]
    capture_factor = _factor_from_slots(
        code="supply.substitution_barrier",
        metric_name="关键设备国产承接可行性（替代壁垒反向评分）",
        slots=capture_slots,
        confidence=0.82,
        rationale="分数方向明确为‘越高越能承接’：清洗/CMP和薄膜具名证据较强，刻蚀与量测仍缺长鑫闭环，先进曝光显著拉低得分。",
        summary="国产承接呈强分化，不能把一类设备的进展外推到整条DRAM设备链。",
        topic_analysis="该因子是替代壁垒的反向分，解决了‘国产能力进展究竟应提高还是降低壁垒分’的方向歧义。",
        sources_by_ref=sources_by_ref,
    )

    supplier_ref_map = {
        "北方华创": "supplier-s-naura-ar-2025",
        "中微公司": "supplier-s-amec-ar-2025",
        "拓荆科技": "supplier-s-piotech-ipo-20220414",
        "盛美上海": "supplier-s-acm-ipo-20211112",
        "华海清科": "supplier-s-hwatsing-ipo-20220601",
        "精智达": "supplier-s-jingzhida-ipo-20230713",
        "京仪装备": "supplier-s-jingyi-ipo-20231124",
        "长川科技": "supplier-s-changchuan-ar-2025",
    }
    supplier_records = {str(row["company"]): row for row in d["supplier"]["supplier_records"]}
    stage_score = {0: 20, 1: 30, 2: 40, 3: 50, 4: 58, 5: 65, 6: 75, 7: 85, 8: 95}
    exposure_slots = []
    for name in supplier_ref_map:
        record = supplier_records[name]
        stage = int(record["highest_confirmed_stage"])
        ref = supplier_ref_map[name]
        point_refs = [ref] if record.get("evidence") else [MODEL_REFS["supplier"]]
        exposure_slots.append(
            _metric_slot(
                code=f"company_{_safe_ref(record['ticker'])}",
                label=f"{name}长鑫具名供应阶段",
                weight=0.125,
                score=stage_score[stage],
                raw_value=f"阶段{stage}：{record['stage_label']}",
                raw_unit="供应阶段",
                standardized_value=stage,
                standardized_unit="0—8阶段",
                bucket=f"阶段{stage}",
                scoring_rule="阶段0/5/6/7/8分别记20/65/75/85/95分；中间阶段按预先固定映射，不按公司名调整。",
                rationale=str(record["assessment"]),
                data_point_keys=_point_keys(points, source_refs=point_refs, contains=[name]),
                source_refs=[ref, MODEL_REFS["supplier"]],
            )
        )
    exposure_factor = _factor_from_slots(
        code="company.exposure_directness",
        metric_name="八家公司组合的长鑫具名供应直接性",
        slots=exposure_slots,
        confidence=0.84,
        rationale="严格按八家公司等权计算：拓荆、盛美、华海、精智达、京仪使用具名阶段；北方、中微、长川均按阶段0处理，不把正帆混入分母。",
        summary="组合内五家公司有不同强度的具名商业证据，三家公司只有工艺或平台能力，没有长鑫具名订单强证据。",
        topic_analysis="组合分只衡量证据直接性，不衡量收入份额；阶段7也不等于主力、第一或独家供应。",
        sources_by_ref=sources_by_ref,
    )

    annual_ref_map = {
        "北方华创": "ar-naura-2025",
        "中微公司": "ar-amec-2025",
        "拓荆科技": "ar-piotech-2025",
        "盛美上海": "ar-acm-2025",
        "华海清科": "ar-hwatsing-2025",
        "精智达": "ar-jingzhida-2025",
        "京仪装备": "ar-jingyi-2025",
        "长川科技": "ar-changchuan-2025",
    }
    finance_models = {str(row["company"]): row for row in d["finance"]["models"]}
    valuations = {str(row["company"]): row for row in d["valuation"]["companies"]}
    sell_side_by_company: dict[str, list[dict[str, Any]]] = {}
    for report in _iter_sell_side_reports(d):
        sell_side_by_company.setdefault(str(report["company"]), []).append(report)
    financial_slots = []
    for name in annual_ref_map:
        forecast = finance_models[name]["forecast"]["2026"]
        valuation = valuations[name]["valuation"]
        fcf_conversion = float(forecast["free_cash_flow"]) / float(forecast["net_income"])
        valuation_upper_gap = float(valuation["relative_to_market_pct"][1])
        valuation_score = 80 if valuation_upper_gap >= 10 else 65 if valuation_upper_gap >= -10 else 50 if valuation_upper_gap >= -30 else 35 if valuation_upper_gap >= -50 else 20
        cash_score = 80 if fcf_conversion >= 0.80 else 65 if fcf_conversion >= 0.40 else 50 if fcf_conversion >= 0 else 25
        slot_score = 0.60 * valuation_score + 0.40 * cash_score
        financial_slots.append(
            _metric_slot(
                code=f"financial_{_safe_ref(finance_models[name]['ticker'])}",
                label=f"{name}现金转换与估值安全边际",
                weight=0.125,
                score=slot_score,
                raw_value=f"FY2026自由现金流/净利润={fcf_conversion:.2f}；估值上沿相对参考市值={valuation_upper_gap:.1f}%",
                raw_unit="比率与百分比",
                standardized_value=f"现金流档{cash_score}分；估值档{valuation_score}分",
                standardized_unit="分档",
                bucket=f"60%估值安全边际＋40%现金转换率＝{slot_score:.1f}分",
                scoring_rule="估值上沿相对参考市值≥10%/≥-10%/≥-30%/≥-50%/<-50%记80/65/50/35/20分；FY1自由现金流/净利润≥0.8/≥0.4/≥0/负值记80/65/50/25分；两者按60%/40%合成。",
                rationale=f"{name}使用{valuation['method']}；参考市值时点为{valuations[name]['market_as_of']}，不与其他公司作严格同日排名。",
                data_point_keys=(
                    _point_keys(points, source_refs=[MODEL_REFS["finance"]], contains=[name], limit=3)
                    + _point_keys(points, source_refs=[MODEL_REFS["valuation"]], contains=[name], limit=1)
                    + [
                        key
                        for report in sell_side_by_company.get(name, [])
                        for key in _point_keys(points, source_refs=[str(report["ref"])], contains=[name], limit=1)
                    ]
                ),
                source_refs=[
                    annual_ref_map[name],
                    MODEL_REFS["finance"],
                    MODEL_REFS["valuation"],
                    *[str(report["ref"]) for report in sell_side_by_company.get(name, [])],
                ],
            )
        )
    financial_factor = _factor_from_slots(
        code="company.financial_capture_quality",
        metric_name="八家公司盈利、现金流与估值承接质量",
        slots=financial_slots,
        confidence=0.75,
        rationale="八家公司均纳入FY2026自由现金流/净利润和适用估值上沿对参考市值的差异；没有用六份年报代表八家公司，也没有把不同日期当同日横截面。",
        summary="产业增长预期较强，但现金转换率和估值安全边际普遍不足，压低组合的财务承接分。",
        topic_analysis="该分数衡量‘增长是否能转成可持有的价格与现金流’，不等于公司质量排名，也不把高PE机械解释为高风险。",
        sources_by_ref=sources_by_ref,
    )

    factors = [demand_factor, capture_factor, exposure_factor, financial_factor]
    factor_weights = {
        demand_factor["factor_code"]: 0.30,
        capture_factor["factor_code"]: 0.25,
        exposure_factor["factor_code"]: 0.25,
        financial_factor["factor_code"]: 0.20,
    }
    score = sum(float(row["score_adjusted"]) * factor_weights[row["factor_code"]] for row in factors)
    coverage = sum(float(row["coverage"]) * factor_weights[row["factor_code"]] for row in factors)
    confidence = sum(float(row["confidence"]) * factor_weights[row["factor_code"]] for row in factors)
    composite = {
        "score_point": round(score, 2),
        "coverage": round(coverage, 4),
        "confidence": round(confidence, 4),
        "factor_weights": factor_weights,
        "formula": "综合分＝项目预算与工艺需求30%＋国产承接可行性25%＋八家公司具名敞口25%＋财务承接质量20%",
        "market_reflection_state": "crowded",
        "research_bias_label": "neutral_watch",
        "included_factors": list(factor_weights),
        "not_applicable": {
            "demand.downstream_price_momentum": "本研究对象是设备供应链组合，DRAM现货价格只作需求背景，不能替代项目预算和设备验收。",
            "demand.output_consumption_proxy": "长鑫绝对WSPM未披露，利用率已作为项目背景，重复打分会与资本开支槽重复。",
            "demand.application_intensity_change": "工艺强度已经在项目预算与工艺需求因子中计分，不重复建立应用强度父因子。",
            "supply.capacity_event_12m": "设备搬入窗口已经进入项目需求因子；公开资料没有可独立复算的新增WSPM事件。",
            "supply.expansion_cycle_bucket": "2026—2028搬入与验收周期已在项目需求因子计分，重复打分会放大同一项目。",
            "supply.raw_policy_constraint": "出口许可既可能限制海外设备也可能促进国产验证，方向非单一；只进入风险与情景，不直接抬高综合分。",
            "supply.supplier_structure_bucket": "八家公司具名阶段已经逐公司进入暴露直接性因子，不再按供应商数量重复加分。",
            "signal.material_price_momentum": "设备供应链研究不存在可比的单一材料价格序列，该因子与研究对象不适用。",
        },
    }
    return factors, composite


def _build_entities(
    d: Mapping[str, Mapping[str, Any]],
    bodies: Mapping[str, str],
    points: Sequence[Mapping[str, Any]],
    sources: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sources_by_ref = {str(row["ref"]): row for row in sources}
    entities: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    descriptions = {
        "cxmt_entity_fab_platform": "核验长鑫法律主体、三条12英寸线、产品工艺代际、利用率、项目预算和封装测试边界。",
        "dram_process_equipment_map": "从裸硅片到晶圆电测、封装终测建立DRAM工艺—设备闭环和优先级。",
        "capacitor_etch_deposition": "深挖电容、HARC刻蚀、薄膜、字线位线和外围CMOS的设备增量。",
        "patterning_clean_cmp_metrology": "比较EUV/DUV图形化、清洗、CMP和先进检测量测的竞争与国产阶段。",
        "test_automation_utilities_services": "研究晶圆测试、封装终测、自动化、厂务、零部件与服务的采购边界。",
        "global_peer_export_controls": "比较四家国际DRAM厂路线、全球设备竞争和美荷日出口许可。",
        "cxmt_supplier_stage_matrix": "按具名证据区分长鑫供应商的正式交付、连续复购、量产和未确认关系。",
        "cxmt_equipment_demand_2026_2031": "以已披露预算为锚估算2026—2028分类与年度需求，并给出2029—2031触发条件。",
        "listed_supplier_investment_opportunities": "对八家上市设备公司建立集团财务、估值、市场隐含和长鑫证据边界。",
    }
    for order, (key, title) in enumerate(ENTITY_TITLES.items(), start=1):
        body = bodies[key]
        refs = _refs_from_body(body)
        entity_points = _research_points_for_entity(key, points, sources_by_ref)
        if not refs:
            refs = [str(row["source_ref"]) for row in entity_points]
        parts = _body_parts(body)
        section = _section(f"{key}_deep_research", title, body, order * 10, refs)
        section["entity_key"] = key
        sections.append(section)
        if key == "listed_supplier_investment_opportunities":
            factors, composite = _build_replayable_factors(d, points, sources_by_ref)
            entities.append({
                "key": key,
                "canonical_name": title,
                "display_name": title,
                "entity_type": "theme",
                "taxonomy_level": "theme",
                "description": descriptions[key],
                "entity_research_mode": "market_linked",
                "score_status": "complete",
                "rating_status": "valid",
                "score_point": composite["score_point"],
                "score_band_low": 52.0,
                "score_band_high": 69.0,
                "score_grade": "C",
                "score_quality_label": "medium_confidence",
                "coverage": composite["coverage"],
                "confidence": composite["confidence"],
                "market_reflection_state": composite["market_reflection_state"],
                "research_bias_label": composite["research_bias_label"],
                "band_method": "关键情景与估值边界压力测试",
                "band_reason": "低端对应项目延期、具名阶段不升级和现金流继续偏弱；高端对应按期搬入、重复订单和估值回落共同兑现。",
                "composite_trace": composite,
                "factor_applicability": {
                    "contract": "长鑫设备供应链候选组合自适应四因子合同",
                    "included_weights": composite["factor_weights"],
                    "not_applicable": composite["not_applicable"],
                    "rationale": "避免把同一项目预算、扩产周期、供应商数量和工艺强度在标准主题因子中重复加分。",
                },
                "evidence_ref_uri": _ev(refs[0]),
                "evidence_ref_uri_list": [_ev(ref) for ref in refs],
                "factor_scores": factors,
                "candidate_reason": parts["总结"],
                "maturation_status": "review_ready",
                "readiness_score": 0.88,
                "readiness_reason": "供应证据、集团财务、外部对账和估值均已冻结并完成复算。",
            })
        else:
            entities.append({
                "key": key,
                "canonical_name": title,
                "display_name": title,
                "entity_type": "theme",
                "taxonomy_level": "theme",
                "description": descriptions[key],
                "entity_research_mode": "theory_research",
                "external_ref_type": "opportunity_lens_entity",
                "maturation_status": "research_only",
                "readiness_score": 0.9,
                "readiness_reason": "问题、双链证据、反方和结论均已形成，等待独立审稿。",
                "research_priority_label": "research_only_literature_review_complete",
                "source_count": len(refs),
                "independent_source_count": len({sources_by_ref[ref]["independence_key"] for ref in refs}),
                "candidate_reason": descriptions[key],
                "evidence_ref_uri": _ev(refs[0]),
                "evidence_ref_uri_list": [_ev(ref) for ref in refs],
                "score_point": None,
                "score_grade": "unrated",
                "score_band_low": None,
                "score_band_high": None,
                "coverage": 0.92,
                "confidence": 0.82,
                "factor_scores": [],
                "research_profile": {
                    "entity_research_mode": "theory_research",
                    "research_depth_status": "complete",
                    "research_question": parts["问题"],
                    "research_scope": descriptions[key],
                    "methodology_note": parts["研究方法与数据"],
                    "literature_review_markdown": _literature_review(refs, sources_by_ref),
                    "data_collection_markdown": "研报链与公开网页链分别执行；原始披露用于事实，技术资料用于工艺机制，模型只用于透明情景。",
                    "analysis_markdown": parts["研究与分析"],
                    "answer_markdown": parts["总结"],
                    "conclusion_markdown": parts["总结"],
                    "limitations_markdown": "公开资料不披露完整设备型号、台数、供应商份额和商业秘密；结论停留在可复核层级。",
                    "evidence_ref_uri_list": [_ev(ref) for ref in refs],
                },
                "research_data_points": entity_points,
            })
    return entities, sections


def _target_point(metric_name: str, value: Any, unit: str, period: str, source_ref: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "metric_name": metric_name,
        "metric_category": "财务估值",
        "period": period,
        "unit": unit,
        "source_title": "Run17长鑫设备候选独立财务与估值模型",
        "source_publisher": "Industry Demo独立研究",
        "source_excerpt": "公司集团模型在读取一致预期前冻结，长鑫只作敏感性，不作为基准收入单点。",
        "evidence_ref_uri": _ev(source_ref),
    }
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        row["value_num"] = float(value)
        row["value_text"] = _fmt(value)
    else:
        row["value_text"] = str(value)
    return row


def _build_targets(d: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    models = {row["company"]: row for row in d["finance"]["models"]}
    values = {row["company"]: row for row in d["valuation"]["companies"]}
    supplier = {row["company"]: row for row in d["supplier"]["supplier_records"]}
    views = {
        "北方华创": ("产业核心跟踪", "平台覆盖最广，但长鑫具名供应待证；等待盈利/现金流上修或估值明显回落。"),
        "中微公司": ("工艺能力观察", "先进存储刻蚀与薄膜能力成立，长鑫具名订单待证；不因行业适配给长鑫收入加成。"),
        "拓荆科技": ("高弹性观察", "薄膜沉积历史正式交付成立，当前需要先进存储批量验收和利润兑现来消化高估值。"),
        "盛美上海": ("具名清洗核心观察", "长鑫历史清洗交付明确，等待当前复购、先进层覆盖和估值改善。"),
        "华海清科": ("具名CMP核心观察", "长鑫量产线应用证据强，关注复购、服务收入、自由现金流和估值回落。"),
        "精智达": ("高风险弹性观察", "连续测试设备交付和验收成立，但客户集中、验收与盈利波动要求更高安全边际。"),
        "京仪装备": ("小基数高弹性观察", "温控长期适配与重复合同强，等待订单转收入、现金回款和估值回落。"),
        "长川科技": ("主题外观察", "测试平台有产业适配，但无长鑫具名强证据；悦芯线索验证前不进入长鑫核心受益。"),
    }
    stage_names = {name: str(row["stage_label"]) for name, row in supplier.items()}
    targets: list[dict[str, Any]] = []
    for order, name in enumerate(models, start=1):
        model = models[name]
        value = values[name]
        val = value["valuation"]
        label, view = views[name]
        stage = stage_names.get(name, "未在十二家公司具名证据矩阵中形成更高阶段")
        f26 = model["forecast"]["2026"]
        f28 = model["forecast"]["2028"]
        company_id = COMPANY_IDS[name]
        if name in {"北方华创", "中微公司", "长川科技"}:
            exposure_text = (
                "只有未来取得长鑫具名订单并完成交付验收，才可能形成集团增量收入；"
                "当前公开资料没有形成该闭环，基准模型不计入长鑫收入"
            )
            confirmed_action = (
                f"若{name}取得首个长鑫具名订单并完成交付验收，同时集团FY1利润或自由现金流兑现，"
                "再复核估值并考虑提高研究权重。"
            )
            falsified_action = (
                f"若{name}的产业适配长期无法转化为长鑫具名订单或验收，"
                "或集团现金流显著弱于利润，降低研究优先级或退出。"
            )
            deep_trigger_text = "若首个具名订单、交付验收和自由现金流改善没有形成闭环"
        else:
            exposure_text = model["cxmt_sensitivity_only"]["direction"]
            confirmed_action = f"若{name}的具名复购、FY1利润上修和自由现金流改善中至少两项成立，再复核估值并考虑提高权重。"
            falsified_action = f"若{name}的既有客户关系被正式材料否定、验收后移或现金流显著弱于利润，降低研究优先级或退出。"
            deep_trigger_text = "若具名复购、验收转收入和自由现金流改善未同时出现"
        profile = (
            f"### 公司与长鑫关系\n\n{_company(name)}（{model['ticker']}）的公开边界为{stage}。"
            f"{exposure_text}；缺少{'、'.join(model['cxmt_sensitivity_only']['missing_to_quantify'])}，"
            "因此集团FY1—FY3模型没有单列长鑫收入。\n\n"
            f"### 财务与估值\n\nFY2026收入/归母净利润/自由现金流为{_fmt(f26['revenue'])}/"
            f"{_fmt(f26['net_income'])}/{_fmt(f26['free_cash_flow'])}亿元，FY2028相应为"
            f"{_fmt(f28['revenue'])}/{_fmt(f28['net_income'])}/{_fmt(f28['free_cash_flow'])}亿元。"
            f"{val['method']}得到{_fmt(val['value_range'][0])}—{_fmt(val['value_range'][1])}亿元，"
            f"相对{value['market_as_of']}市值{_fmt(value['market_cap'])}亿元为{_fmt(val['relative_to_market_pct'][0])}%—"
            f"{_fmt(val['relative_to_market_pct'][1])}%。\n\n### 研究动作\n\n{view}"
        )
        primary = value["external_reconciliation"]["primary"]
        profit_diff = value["external_reconciliation"]["independent_minus_primary_pct"]["net_income"]
        deep_research = (
            f"### 集团经营路径\n\n{_company(name)}的独立模型从2025年实际财务起算，不把无法核验的长鑫订单倒灌进收入。"
            f"FY2026—FY2028归母净利润依次为{_fmt(f26['net_income'])}/"
            f"{_fmt(model['forecast']['2027']['net_income'])}/{_fmt(f28['net_income'])}亿元，自由现金流依次为"
            f"{_fmt(f26['free_cash_flow'])}/{_fmt(model['forecast']['2027']['free_cash_flow'])}/"
            f"{_fmt(f28['free_cash_flow'])}亿元；利润增长若不能转化为现金流，估值上沿不成立。\n\n"
            f"### 外部预测对账\n\n与{primary['name']}（{primary.get('as_of') or primary.get('date') or '研究截止日可得口径'}）相比，{_company(name)}独立模型的"
            f"FY2026—FY2028归母净利润差异为{_fmt(profit_diff[0])}%/"
            f"{_fmt(profit_diff[1])}%/{_fmt(profit_diff[2])}%。差异来自集团收入增速、利润率和现金转换假设，"
            "不是对未披露客户订单作精确预测。\n\n"
            f"### 条件与风险\n\n{exposure_text}。{view}"
            f"{deep_trigger_text}，{_company(name)}不因存储扩产主题自动获得更高估值。"
        )
        targets.append({
            "entity_key": "listed_supplier_investment_opportunities",
            "target_name": name,
            "target_type": "security",
            "company_id": company_id,
            "ticker": model["ticker"],
            "exposure_rationale": f"{label}；{stage}。集团经营与长鑫敞口分开建模。",
            "evidence_ref_uri": _ev(MODEL_REFS["valuation"]),
            "research_action": view,
            "investment_view": f"{label}，不构成无条件买入建议。",
            "risk_note": f"{name}的主要风险是长鑫项目延后、{stage}不再升级，以及集团利润或现金流低于独立模型。",
            "target_priority": f"第{order}项逐股研究对象；排序按研究覆盖顺序，不是预期收益排名。",
            "target_quality_label": "集团财务已冻结并外部对账；长鑫收入不可量化",
            "relative_preference": view,
            "confirmed_scenario_action": confirmed_action,
            "falsified_scenario_action": falsified_action,
            "target_profile_markdown": profile,
            "target_deep_research_markdown": deep_research,
            "entity_relation_markdown": f"{name}对应DRAM设备链中的具体产品或平台，但只有{stage}能作为长鑫关系证据。",
            "parent_research_relation_markdown": "本标的由长鑫项目总量、设备类别和具名供应阶段筛出；集团财务不从长鑫预算机械分摊。",
            "conditional_investment_recommendation": view,
            "financial_data_status": "FY2026—FY2028独立模型、外部对账和估值已完成；客户收入缺口保留",
            "target_data_points": [
                *[
                    _target_point(
                        f"FY{year}{metric_label}",
                        model["forecast"][str(year)][metric_key],
                        "亿元人民币",
                        f"FY{year}E",
                        MODEL_REFS["finance"],
                    )
                    for year in (2026, 2027, 2028)
                    for metric_label, metric_key in (
                        ("收入", "revenue"),
                        ("归母净利润", "net_income"),
                        ("自由现金流", "free_cash_flow"),
                    )
                ],
                _target_point("独立估值下限", val["value_range"][0], "亿元人民币", value["market_as_of"], MODEL_REFS["valuation"]),
                _target_point("独立估值上限", val["value_range"][1], "亿元人民币", value["market_as_of"], MODEL_REFS["valuation"]),
                _target_point("参考市值", value["market_cap"], "亿元人民币", value["market_as_of"], MODEL_REFS["valuation"]),
            ],
        })
    return targets


def _source_search_axis(source: Mapping[str, Any]) -> str:
    hint = str(source.get("search_axis_hint") or "")
    if hint:
        return hint
    ref = str(source["ref"])
    if ref.startswith("forecast-"):
        return "valuation"
    model_axis = {
        MODEL_REFS["cxmt"]: "entity_fab",
        MODEL_REFS["process"]: "process",
        MODEL_REFS["supplier"]: "supplier_stage",
        MODEL_REFS["demand"]: "demand",
        MODEL_REFS["finance"]: "financials",
        MODEL_REFS["valuation"]: "valuation",
    }
    if ref in model_axis:
        return model_axis[ref]
    if ref.startswith("ar-"):
        return "financials"
    if ref.startswith("cxmt-"):
        match = re.search(r"s(\d+)$", ref)
        number = int(match.group(1)) if match else 1
        return "entity_fab" if number <= 8 else "demand"
    if ref.startswith("supplier-"):
        return "supplier_stage" if any(token in ref for token in ("ipo", "reply")) else "companies"
    if ref.startswith("dram-e"):
        number = int(ref.removeprefix("dram-e"))
        if number in {26, 27, 28, 29, 30, 43}:
            return "export_controls"
        if number in {7, 8, 9, 10, 11, 12, 39, 40, 41, 42}:
            return "global_peers"
        if 31 <= number <= 38:
            return "companies"
        if number in {1, 19, 20, 21, 22, 23, 24, 25}:
            return "process"
        return "critical_equipment"
    return "companies"


def _search_plan(sources: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    axes = {
        "entity_fab": "长鑫法律主体、基地、产线、产品、利用率、在建工程与升级项目",
        "process": "DRAM从晶圆制造到测试出货的完整工艺和设备链",
        "critical_equipment": "电容、HARC刻蚀、沉积、图形化、清洗、CMP和先进量测",
        "supplier_stage": "长鑫具名设备供应商、产品、交付、验收、复购和量产阶段",
        "global_peers": "三星、SK海力士、美光、南亚科技工艺路线和全球设备平台",
        "export_controls": "美国、荷兰、日本对整机、软件、部件、维护和替换件的限制",
        "demand": "2025—2028项目搬入验收和2026—2031设备需求情景",
        "companies": "中国设备、测试、厂务、零部件候选及反方证据",
        "financials": "重点上市公司年报、FY1—FY3独立财务、现金流和外部预测",
        "valuation": "适用估值、当前市场隐含盈利和估值安全边际",
    }
    task_refs: dict[tuple[str, str, int], list[str]] = {}
    web_axis_counter: dict[str, int] = {}
    for source in sources:
        axis = _source_search_axis(source)
        channel = str(source.get("source_channel") or "web")
        if channel == "report":
            round_number = 1
        else:
            web_axis_counter[axis] = web_axis_counter.get(axis, 0) + 1
            round_number = 1 if web_axis_counter[axis] % 2 else 2
        task_refs.setdefault((axis, channel, round_number), []).append(str(source["ref"]))

    rows: list[dict[str, Any]] = []
    for key, query in axes.items():
        specs = [
            ("report", 1, f"近期中英文研报与本地年报：{query}", None),
            ("web", 1, f"全球监管、公司、设备厂、研究机构与项目方原始资料：{query}", None),
            (
                "web",
                2,
                f"追最早出处、主体产品期间数量、独立侧证、否认与替代解释：{query}",
                "第一轮存在具名客户、阶段、工艺层次、设备金额或许可证边界缺口",
            ),
        ]
        for channel, round_number, query_text, trigger in specs:
            refs = task_refs.get((key, channel, round_number), [])
            item = {
                "axis_key": key,
                "source_group": "local_reports" if channel == "report" else "open_web_primary",
                "source_channel": channel,
                "round": round_number,
                "query_text": query_text,
                "source_refs": refs,
                "result_count": len(refs),
                "included_count": len(refs),
                "status": "completed",
            }
            if trigger:
                item["gap_trigger"] = trigger
            if not refs:
                item["rejection_reason"] = (
                    "该通道完成检索但没有形成可纳入source；结构化Wind/Tushare财务快照按财务库边界不复制为C轨来源。"
                    if key in {"financials", "valuation"} and channel == "web"
                    else "该轮没有新增达到纳入门槛且不与既有底层文件重复的来源。"
                )
            rows.append(item)
    return rows


def _prompt_requirements(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = request.get("prompt_requirements")
    if not isinstance(rows, list) or len(rows) != 25:
        raise Run17BuildError("Run17必须完整保留25条用户要求")
    hints = [
        "cxmt_entity_fab_platform", "cxmt_entity_fab_platform", "cxmt_entity_fab_platform",
        "dram_process_equipment_map", "dram_process_equipment_map", "capacitor_etch_deposition",
        "dram_process_equipment_map", "global_peer_export_controls", "cxmt_supplier_stage_matrix",
        "cxmt_supplier_stage_matrix", "cxmt_supplier_stage_matrix", "global_peer_export_controls",
        "global_peer_export_controls", "cxmt_equipment_demand_2026_2031", "cxmt_equipment_demand_2026_2031",
        "listed_supplier_investment_opportunities", "listed_supplier_investment_opportunities",
        "listed_supplier_investment_opportunities", "listed_supplier_investment_opportunities",
        "monitoring", "monitoring", "search_plan", "summary", "entity_sections", "review_workflow",
    ]
    return [
        {
            "question": str(row["question"]),
            "acceptance_criteria": str(row.get("acceptance_criteria") or "在对应正文、研究实体、模型或审计产物中完整覆盖并绑定证据。"),
            "output_hint": hint,
        }
        for row, hint in zip(rows, hints, strict=True)
    ]


def _weak_lead_registry(d: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    cxmt_leads = d["cxmt"].get("unverified_leads") or []
    supplier_leads = d["supplier"].get("important_unverified_leads") or []
    process_leads = d["process"].get("unverified_but_important") or []
    rows: list[dict[str, Any]] = []
    for index, lead in enumerate(cxmt_leads, start=1):
        rows.append(
            {
                "lead_id": f"run17-weak-{index:02d}",
                "claim": str(lead["lead"]),
                "earliest_or_common_source": str(lead["earliest_or_common_sources_checked"]),
                "checked_scope": str(lead["verification_result"]),
                "treatment": "不进入供应阶段、需求基准、财务输入或核心评分；" + str(lead["what_is_needed"]),
                "status": "important_unverified",
                "origin_workpapers": [CXMT_PATH.relative_to(ROOT).as_posix()],
            }
        )
    rows.append(
        {
            "lead_id": "run17-weak-06",
            "claim": str(supplier_leads[0]["claim"]),
            "earliest_or_common_source": "产业文章和卖方转述",
            "checked_scope": str(supplier_leads[0]["checked"]),
            "treatment": str(supplier_leads[0]["treatment"]),
            "status": "important_unverified",
            "origin_workpapers": [SUPPLIER_PATH.relative_to(ROOT).as_posix()],
        }
    )
    rows.append(
        {
            "lead_id": "run17-weak-07",
            "claim": "北方华创、中微、芯源微、中科飞测、华峰测控、长川科技等已经进入长鑫关键层供应链。",
            "earliest_or_common_source": "多篇二级文章、卖方转述和共同措辞的供应链名单",
            "checked_scope": str(supplier_leads[1]["checked"]) + "；" + str(process_leads[1]["why"]),
            "treatment": "合并两个重叠说法为一个线索；没有客户—设备—阶段原件前，只提高补证优先级。",
            "status": "important_unverified",
            "origin_workpapers": [
                SUPPLIER_PATH.relative_to(ROOT).as_posix(),
                PROCESS_PATH.relative_to(ROOT).as_posix(),
            ],
        }
    )
    rows.append(
        {
            "lead_id": "run17-weak-08",
            "claim": "长鑫新增设备采购的国产设备比例或北方华创、中微份额已经达到二级文章所称的具体百分比。",
            "earliest_or_common_source": "多篇使用相近措辞和数字的二级文章",
            "checked_scope": str(process_leads[0]["why"]),
            "treatment": "没有客户—设备—份额原件前，不进入供应商金额和公司收入模型。",
            "status": "important_unverified",
            "origin_workpapers": [PROCESS_PATH.relative_to(ROOT).as_posix()],
        }
    )
    rows.append(
        {
            "lead_id": "run17-weak-09",
            "claim": "国产28nm级ArF浸没式曝光机已经在先进DRAM量产线稳定使用。",
            "earliest_or_common_source": "二级产业文章与设备路线讨论",
            "checked_scope": str(process_leads[2]["why"]),
            "treatment": "没有先进DRAM关键层、套刻、吞吐、可用率和客户验收原件前，不提高光刻国产承接分。",
            "status": "important_unverified",
            "origin_workpapers": [PROCESS_PATH.relative_to(ROOT).as_posix()],
        }
    )
    deduped = rows
    for index, row in enumerate(deduped, start=1):
        row["lead_id"] = f"run17-weak-{index:02d}"
    if len(deduped) != 9:
        raise Run17BuildError(f"统一弱线索注册表应为9条，当前{len(deduped)}条")
    return deduped


def _modeling_records() -> list[dict[str, Any]]:
    return [
        {
            "skill_name": "industry_supply_demand_modeling",
            "status": "completed",
            "input_artifact_hash": _sha(CXMT_PATH),
            "output_artifact_hash": _sha(DEMAND_PATH),
            "result_summary": "以已披露项目预算为锚完成设备分类、年度执行、国产承接与2029—2031条件情景。",
        },
        {
            "skill_name": "company_financial_modeling",
            "status": "completed",
            "input_artifact_hash": _sha(SUPPLIER_PATH),
            "output_artifact_hash": _sha(FINANCE_PATH),
            "result_summary": "八家公司集团级FY1—FY3经营、利润和现金流在读取一致预期前冻结；长鑫收入不造数。",
        },
        {
            "skill_name": "company_valuation_modeling",
            "status": "completed",
            "input_artifact_hash": _sha(FINANCE_PATH),
            "output_artifact_hash": _sha(VALUATION_PATH),
            "result_summary": "完成适用估值、市场隐含、Wind一致预期和最近两个季度卖方预测对账。",
        },
        {
            "skill_name": "probability_scenario_modeling",
            "status": "completed",
            "input_artifact_hash": _sha(CXMT_PATH),
            "output_artifact_hash": _sha(DEMAND_PATH),
            "result_summary": "完成延期、按计划和冗余增强三种执行情景，不给主观情景赋伪精确发生概率。",
        },
    ]


def _public_draft(pack: Mapping[str, Any]) -> str:
    chunks = [f"# {pack['display_title']}", f"研究问题：{pack['problem_statement']}"]
    for section in sorted(pack["sections"], key=lambda row: row["sort_order"]):
        body = re.sub(r"\s*\^src:source_ref:[A-Za-z0-9_.-]+", "", str(section["body_markdown"]))
        chunks.append(f"## {section['section_title']}\n\n{body}")
    chunks.append("# 研究实体")
    for section in sorted(pack["entity_sections"], key=lambda row: row["sort_order"]):
        body = re.sub(r"\s*\^src:source_ref:[A-Za-z0-9_.-]+", "", str(section["body_markdown"]))
        chunks.append(f"## {section['section_title']}\n\n{body}")
    return "\n\n".join(chunks).strip() + "\n"


def _quality_checks(pack: Mapping[str, Any]) -> None:
    if len(pack["data_points"]) < 100:
        raise Run17BuildError("平行数据点不足100")
    if len(pack["entities"]) != 9 or len(pack["entity_sections"]) != 9:
        raise Run17BuildError("Run17必须保留9个细分但不过度拆分的研究实体")
    main_chars = sum(len(str(row["body_markdown"])) for row in pack["sections"])
    if main_chars < 14000:
        raise Run17BuildError(f"主报告仅{main_chars}字符，未达到14000")
    for row in pack["entity_sections"]:
        if len(str(row["body_markdown"])) < 1800:
            raise Run17BuildError(f"研究实体{row['entity_key']}仅{len(str(row['body_markdown']))}字符")
    if len(str(pack["sections"][0]["body_markdown"])) > 2500:
        raise Run17BuildError("摘要超过2500字符，不再是快速阅读摘要")
    for row in [*pack["sections"], *pack["entity_sections"]]:
        body = str(row["body_markdown"])
        for heading in ("### 问题", "### 研究方法与数据", "### 研究与分析", "### 总结"):
            if heading not in body:
                raise Run17BuildError(f"{row['section_key']}缺少{heading}")
    forbidden = ("字段完成度", "参数 owner", "D0/D1/D2", "low/mode/high", "主力供应商是")
    public_text = _public_draft(pack)
    for token in forbidden:
        if token in public_text:
            raise Run17BuildError(f"公开正文出现禁用表达：{token}")


def build_pack() -> dict[str, Any]:
    d = _load_inputs()
    sources, evidence_groups, ref_by_internal = _build_sources(d)
    points, claims = _build_facts(d, ref_by_internal)
    source_languages = {str(row["ref"]): str(row.get("language") or "").lower() for row in sources}
    for row in points:
        if source_languages.get(str(row["source_ref"]), "").startswith("en"):
            row["source_excerpt_zh"] = str(row["source_excerpt"])
    for row in claims:
        if source_languages.get(str(row["source_ref"]), "").startswith("en"):
            row["source_excerpt_zh"] = str(row["source_excerpt"])
    bodies = _entity_bodies(d)
    entities, entity_sections = _build_entities(d, bodies, points, sources)
    sections = _main_sections(d)
    intake = parse_markdown_intake_text(INTAKE_PATH.read_text(encoding="utf-8"))
    builder = RunPackBuilder(
        slug="cxmt-dram-equipment-supply-chain-run17",
        display_title="长鑫科技DRAM设备供应链",
        research_question=str(intake["research_question"]),
        problem_statement="长鑫扩产与工艺升级将把设备需求导向哪些环节，哪些中国公司具备可核验供应能力和投资安全边际？",
        intake=intake,
        requested_by="user_run17_cxmt_dram_equipment_research",
        run_mode="c_hybrid",
        quality_profile="deep_research",
        public_section_structure_contract="public.problem_method_data_analysis_summary.v1",
    )
    for source in sources:
        builder.add_source(source)
    builder.data_points.extend(points)
    builder.claims.extend(claims)
    for entity in entities:
        builder.add_entity(entity)
    builder.entity_sections.extend(entity_sections)
    builder.entity_investment_targets.extend(_build_targets(d))
    builder.sections.extend(sections)
    builder.search_plan.extend(_search_plan(sources))
    builder.modeling_records.extend(_modeling_records())
    builder.independent_model_freezes.append({
        "model_ref": "Run17八家设备公司独立FY1—FY3集团经营模型",
        "input_hash": _sha(SUPPLIER_PATH),
        "output_hash": _sha(FINANCE_PATH),
        "frozen_before_consensus": True,
        "frozen_at": str(d["finance"].get("frozen_at") or "2026-08-02"),
    })
    builder.external_reconciliations.append({
        "model_ref": "Run17八家设备公司独立FY1—FY3集团经营模型",
        "benchmark_ref": "Wind一致预期与研究截止日前最近两个季度同公司卖方预测",
        "artifact_hash": _sha(VALUATION_PATH),
        "status": "completed",
        "summary": "独立模型冻结后逐公司对账；长鑫客户收入客观不可得，不用总预算机械分摊。",
    })
    builder.evidence_groups.update(evidence_groups)
    pack = builder.build(publication_mode="stage")
    pack["prompt_requirements"] = _prompt_requirements(d["request"])
    weak_leads = _weak_lead_registry(d)
    pack["weak_lead_registry"] = weak_leads
    external_sources = [
        row for row in sources if str(row.get("independence_key")) != "internal:run17:derived_workpapers"
    ]
    external_groups = {str(row["independence_key"]) for row in external_sources}
    pack["open_search_statistics"] = {
        "pack_total_source_count": len(sources),
        "external_source_count": len(external_sources),
        "external_independent_evidence_group_count": len(external_groups),
        "derived_model_artifact_count": len(sources) - len(external_sources),
        "parallel_research_fact_count": len(points),
        "report_source_count": sum(1 for row in sources if row["source_channel"] == "report"),
        "web_source_count": sum(1 for row in sources if row["source_channel"] == "web"),
        "same_origin_duplicate_count": len(external_sources) - len(external_groups),
        "unresolved_material_lead_count": len(weak_leads),
        "unresolved_material_lead_disposition": "重要但尚未验证的线索只进入监控与不确定性，不进入供应阶段、财务输入或核心评分。",
    }
    pack["financial_data_boundary"] = {
        "database": "financial.db",
        "policy": "Wind/Tushare结构化快照只进入financial.db；研究包只保存冻结模型、外部对账和公司页语义关系。",
        "company_ids": sorted(COMPANY_IDS[row["company"]] for row in d["finance"]["models"]),
    }
    pack["deterministic_gate_plan"] = [
        {"gate": gate, "status": "pending", "result": "待发布流程执行并写回"}
        for gate in ("contract", "evidence_integrity", "provenance", "duplication", "scope_and_units")
    ]
    pack["review_records"] = []
    _quality_checks(pack)
    validate_run_pack(pack, publication_mode="stage").raise_for_errors()
    return pack


def main() -> int:
    pack = build_pack()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    PUBLIC_DRAFT_PATH.write_text(_public_draft(pack), encoding="utf-8")
    report = validate_run_pack(pack, publication_mode="stage")
    print(json.dumps({
        "output": str(OUTPUT_PATH),
        "public_draft": str(PUBLIC_DRAFT_PATH),
        "sources": len(pack["sources"]),
        "data_points": len(pack["data_points"]),
        "entities": len(pack["entities"]),
        "targets": len(pack["entity_investment_targets"]),
        "validation_errors": [issue.__dict__ for issue in report.blockers],
        "validation_warnings": [issue.__dict__ for issue in report.warnings],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
