from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from .constants import (
    API_CONTRACT_VERSION,
    DB_PATH,
    EARLY_SIGNAL_RULE_VERSION,
    MODULE_NAME,
    RESEARCH_DB_PATH, FINANCIAL_DB_PATH,
    RESEARCH_WORKFLOW_CONTRACT_VERSION,
    RUN_PACK_SCHEMA_VERSION,
    SCHEMA_VERSION,
)
from tools.financial.read_models import company_bundle as financial_company_bundle
from .db import connect, dict_row, dict_rows
from .display_annotations import chinese_translation, freshness_warning, source_original_text
from .evidence_resolver import resolve
from .factor_dictionary import factor_metadata
from .metric_slot_gaps import is_missing_scoring_slot
from .flags import run_flag_summary
from .score_trace import get_entity_score_trace, get_factor_trace, get_metric_slot_trace, loads_json
from .value_display import format_data_point_value


def _connect_read(db_path: str | Path = DB_PATH) -> sqlite3.Connection | None:
    path = Path(db_path)
    if not path.exists():
        return None
    return connect(path, readonly=True)


def health(db_path: str | Path = DB_PATH) -> dict:
    path = Path(db_path)
    if not path.exists():
        return {
            "module": MODULE_NAME,
            "db_exists": False,
            "db_path": str(path),
            "schema_version": SCHEMA_VERSION,
            "api_contract_version": API_CONTRACT_VERSION,
            "workflow_contract_version": RESEARCH_WORKFLOW_CONTRACT_VERSION,
            "run_pack_schema_version": RUN_PACK_SCHEMA_VERSION,
        }
    conn = connect(path, readonly=True)
    try:
        tables = int(conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'opportunity_%'").fetchone()[0])
        runs = int(conn.execute("SELECT COUNT(*) FROM opportunity_run").fetchone()[0])
    finally:
        conn.close()
    return {
        "module": MODULE_NAME,
        "db_exists": True,
        "db_path": str(path),
        "schema_version": SCHEMA_VERSION,
        "api_contract_version": API_CONTRACT_VERSION,
        "workflow_contract_version": RESEARCH_WORKFLOW_CONTRACT_VERSION,
        "run_pack_schema_version": RUN_PACK_SCHEMA_VERSION,
        "table_count": tables,
        "run_count": runs,
    }


def _sanitize_run_row(row: dict) -> dict:
    if not row:
        return row
    row["research_question"] = row.get("research_question") or row.get("question")
    row.pop("question", None)
    return row


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


_DUAL_CURRENCY_PAIR_RE = re.compile(
    r"([+-]?[\d,]+(?:\.\d+)?)亿元人民币（约([+-]?[\d,]+(?:\.\d+)?)亿美元）"
)
_USD_CNY_RATE_RE = re.compile(r"1美元\s*=\s*([\d,]+(?:\.\d+)?)元人民币")


def _source_usd_to_cny(row: dict) -> float | None:
    """从同一来源已披露的双币种金额推导本轮展示汇率。"""

    for field in ("source_excerpt_zh", "source_excerpt", "excerpt_zh", "excerpt"):
        text = str(row.get(field) or "")
        rate_match = _USD_CNY_RATE_RE.search(text)
        if rate_match:
            rate = float(rate_match.group(1).replace(",", ""))
            if rate > 0:
                return rate
        for cny_text, usd_text in _DUAL_CURRENCY_PAIR_RE.findall(text):
            cny = float(cny_text.replace(",", ""))
            usd = float(usd_text.replace(",", ""))
            if cny and usd and cny * usd > 0:
                return abs(cny / usd)
    return None


def _value_display(row: dict) -> str:
    unit = row.get("unit") or ""
    if row.get("value_num") is not None:
        value = row["value_num"]
        if unit == "亿元人民币":
            usd_to_cny = _source_usd_to_cny(row)
            if usd_to_cny:
                if float(value).is_integer():
                    value_text = str(int(value))
                else:
                    value_text = f"{float(value):.2f}".rstrip("0").rstrip(".")
                usd_text = f"{float(value) / usd_to_cny:,.2f}"
                return f"{value_text}亿元人民币（约{usd_text}亿美元）"
    return format_data_point_value(row)


def _annotate_source_display(row: dict) -> dict:
    language = row.get("language") or row.get("source_language")
    row["freshness_warning"] = freshness_warning(row.get("publish_date") or row.get("source_publish_date"))
    row["title_zh"] = row.get("title_zh") or chinese_translation(row.get("title") or row.get("source_title"), language)
    row["excerpt_zh"] = row.get("excerpt_zh") or chinese_translation(row.get("excerpt") or row.get("source_excerpt"), language)
    row["excerpt_display"] = source_original_text(row.get("excerpt") or row.get("source_excerpt"))
    return row


def _annotate_data_point_display(row: dict) -> dict:
    language = row.get("source_language")
    row["freshness_warning"] = freshness_warning(
        row.get("period"),
        row.get("as_of_date"),
        row.get("source_publish_date"),
    )
    row["source_title_zh"] = row.get("source_title_zh") or chinese_translation(row.get("source_title"), language)
    row["source_excerpt_zh"] = row.get("source_excerpt_zh") or chinese_translation(row.get("source_excerpt"), language)
    row["source_excerpt_display"] = source_original_text(row.get("source_excerpt"))
    return row


def _annotate_target_data_point_display(row: dict) -> dict:
    row["freshness_warning"] = freshness_warning(
        row.get("period"),
        row.get("as_of_date"),
        row.get("source_title"),
        row.get("source_excerpt"),
    )
    language = row.get("source_language")
    row["source_title_zh"] = row.get("source_title_zh") or chinese_translation(row.get("source_title"), language)
    row["source_excerpt_zh"] = row.get("source_excerpt_zh") or chinese_translation(row.get("source_excerpt"), language)
    row["source_excerpt_display"] = source_original_text(row.get("source_excerpt"))
    return row


def _annotate_research_data_point_display(row: dict) -> dict:
    row["value_display"] = _value_display(row)
    row["freshness_warning"] = freshness_warning(
        row.get("period"),
        row.get("as_of_date"),
        row.get("source_publish_date"),
    )
    row["source_title_zh"] = row.get("source_title_zh") or chinese_translation(row.get("source_title"), row.get("source_language"))
    row["source_excerpt_zh"] = row.get("source_excerpt_zh") or chinese_translation(row.get("source_excerpt"), row.get("source_language"))
    row["source_excerpt_display"] = source_original_text(row.get("source_excerpt"))
    return row


def _target_link(row: dict) -> str | None:
    if row.get("company_id"):
        return f"/company/{row['company_id']}"
    return row.get("target_url")


def _target_detail_link(row: dict) -> str:
    return f"/opportunity-lens/target/{row['id']}"


def _connect_research_read() -> sqlite3.Connection | None:
    path = Path(RESEARCH_DB_PATH)
    if not path.exists():
        return None
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _ab_company_financials(company_id) -> dict | None:
    if not company_id:
        return None
    conn = _connect_research_read()
    if conn is None:
        return None
    try:
        company = dict_row(
            conn.execute(
                """
                SELECT id, name, ticker, market, listing_status, pe_ttm, pe_forward,
                       pb, ps_ttm, market_cap_value, market_cap_unit, market_cap_cny,
                       market_cap_usd, market_cap_cny_as_of, valuation_as_of, roe,
                       roa, ev_ebitda, dividend_yield, peg, valuation_source_id,
                       forecast_as_of_date, forecast_source_id, brief_intro
                FROM company
                WHERE id=?
                """,
                (company_id,),
            ).fetchone()
        )
        if not company:
            return None
        financial = financial_company_bundle(int(company_id), db_path=FINANCIAL_DB_PATH)
        if financial:
            latest_map = {
                "pe_ttm": ("pe_ttm",), "pe_forward": ("pe_forward",), "pb": ("pb",),
                "ps_ttm": ("ps_ttm",), "ev_ebitda": ("ev_ebitda",),
                "roe": ("roe",), "roa": ("roa",),
                "market_cap_cny": ("market_cap",), "market_cap_usd": ("market_cap_usd",),
            }
            latest_dates: list[str] = []
            for target_field, metric_names in latest_map.items():
                rows = [
                    row for metric in metric_names for row in financial.get("metrics", {}).get(metric, [])
                    if row.get("value_num") is not None
                ]
                if rows:
                    latest = max(rows, key=lambda row: (str(row.get("as_of_date") or ""), int(row.get("id") or 0)))
                    company[target_field] = latest["value_num"]
                    latest_dates.append(str(latest.get("as_of_date") or ""))
            company["market_cap_value"] = company.get("market_cap_cny")
            company["market_cap_unit"] = "亿元人民币" if company.get("market_cap_cny") is not None else company.get("market_cap_unit")
            if latest_dates:
                company["valuation_as_of"] = max(latest_dates)
        profile = dict_row(
            conn.execute(
                """
                SELECT company_id, industry_id, period, revenue_series, net_income_series,
                       gross_margin, net_margin, operating_cash_flow, ocf_unit,
                       financials_as_of, global_share, global_rank, china_share,
                       china_rank, revenue_share_in_industry, main_products,
                       main_customers, customer_concentration, rd_expense_ratio,
                       capex_value, capex_unit, tech_node, recent_events, risks,
                       source_ids, summary, display_note, last_verified_at
                FROM company_profile
                WHERE company_id=?
                ORDER BY COALESCE(financials_as_of, period, last_verified_at, '') DESC
                LIMIT 1
                """,
                (company_id,),
            ).fetchone()
        )
        # Historical target.html reads net_margin from the company mapping even
        # though the value is stored in company_profile. Preserve the restored
        # legacy template byte-for-byte and provide the expected read-only key.
        company["net_margin"] = profile.get("net_margin") if profile else None
        return {
            "company": company,
            "profile": profile,
            "financial": financial,
            "source_note": (
                "结构化财务与估值来自独立 financial.db；公司身份和行业画像来自 research.db。"
                if financial else "独立 financial.db 尚无该公司记录；只展示 research.db 的历史兼容聚合。"
            ),
        }
    finally:
        conn.close()


def _entity_research_brief(entity: dict, data_points: list[dict], claims: list[dict], targets: list[dict]) -> dict:
    entity_name = entity.get("display_name") or entity.get("canonical_name") or "该研究实体"
    if entity.get("entity_research_mode") == "theory_research":
        profile = entity.get("research_profile") or {}
        return {
            "research_object": profile.get("research_question") or entity.get("description") or f"本页研究对象是 {entity_name} 的理论、口径和资料综述问题。",
            "evidence_summary": (
                f"已沉淀 {len(entity.get('research_data_points') or [])} 条研究指标、计算底稿与证据索引；"
                f"普通证据库另有 {len(data_points)} 条实体数据点和 {len(claims)} 条 claim。"
            ),
            "analysis_summary": profile.get("analysis_markdown") or "理论型实体不进入核心评分，重点是资料收集、文献综述、概念边界和问题回答。",
            "conclusion": profile.get("conclusion_markdown") or "该实体不要求绑定标的或投资建议，结论以研究回答和限制条件为准。",
        }
    evidence_items = []
    for row in data_points[:3]:
        period = row.get("period") or row.get("as_of_date") or "未标明期间"
        evidence_items.append(f"{row.get('metric')}：{_value_display(row)}，期间 {period}")
    if not evidence_items:
        for row in claims[:3]:
            evidence_items.append(row.get("claim_text") or "")
    target_names = "、".join(row.get("target_name", "") for row in targets[:4] if row.get("target_name"))
    return {
        "research_object": entity.get("description") or f"本页研究对象是 {entity_name} 在当前 Opportunity Lens 扫描中的供需失衡、评分状态和证据质量。",
        "evidence_summary": "；".join(evidence_items) if evidence_items else "当前实体尚未沉淀可展示的数据点或 claim，需要补充原文证据后再进入实质研究。",
        "analysis_summary": (
            f"{entity_name} 的分析应先看证据是否能同时支持需求强度、供应约束、价格或交期信号，"
            "再判断现有资料是否足以形成可复核的因子评分。"
        ),
        "conclusion": (
            f"相关标的优先从 {target_names} 继续研究。"
            if target_names
            else "当前没有结构化标的链接，必须补标的暴露逻辑、证据和风险后才算完成实体研究。"
        ),
    }


def _series_observation_count(row: dict) -> int:
    if row.get("observation_count"):
        try:
            return int(row.get("observation_count") or 0)
        except (TypeError, ValueError):
            return 0
    payload = loads_json(row.get("value_text"), {})
    if isinstance(payload, dict) and ("observation_count" in payload or "observations" in payload):
        try:
            return int(payload.get("observation_count") or len(payload.get("observations") or []))
        except (TypeError, ValueError):
            return 0
    for text in (row.get("source_excerpt"), row.get("value_text")):
        text = str(text or "")
        marker = "共 "
        suffix = " 个观测"
        if marker in text and suffix in text:
            middle = text.split(marker, 1)[1].split(suffix, 1)[0].strip()
            if middle.isdigit():
                return int(middle)
    return 0


AI_INDUCTOR_ENTITY_TERMS = (
    "电感",
    "tlvr",
    "vrm",
    "gpu",
    "asic",
    "英伟达",
    "google",
    "华为",
    "磁粉",
    "软磁",
)

AI_INDUCTOR_NOISE_TERMS = (
    "原文证据",
    "行业事实",
    "manual_verified_fact",
    "Unnamed:",
    "股票投资评级",
    "投资评级",
    "目标价格",
    "总股本",
    "流通股本",
    "执业证书",
    "SAC",
    "@",
    "分析师：",
    "燃气轮机",
    "输电层面",
    "主网电力设备",
    "配网设备",
    "CCL",
    "HVLP",
    "氧化铜粉",
    "纳米硅粉",
    "固态电池",
    "液冷",
    "PCB上游",
)


def _is_ai_inductor_entity(entity_name: str, rows: list[dict]) -> bool:
    sample = entity_name + " " + " ".join(str(row.get("metric") or "") for row in rows[:30])
    sample = sample.lower()
    return any(term in sample for term in AI_INDUCTOR_ENTITY_TERMS)


def _curate_ai_inductor_data_points(entity_name: str, rows: list[dict], limit: int) -> list[dict]:
    limit = min(limit, 12)
    is_customer = any(term in entity_name for term in ("客户", "英伟达", "google", "华为"))
    is_material = any(term in entity_name for term in ("磁粉", "材料", "产能瓶颈"))
    is_company = "公司承接" in entity_name or "上市公司" in entity_name
    is_price = "价格" in entity_name or "tam" in entity_name

    def score(row: dict) -> tuple[int, int, int]:
        metric = str(row.get("metric") or "")
        excerpt = str(row.get("source_excerpt") or "")
        method = str(row.get("extraction_method") or "")
        source_title = str(row.get("source_title") or "")
        text = f"{metric} {excerpt} {source_title}"
        obs = _series_observation_count(row)
        value = 0
        if method == "xlsx_direct":
            value += 90
        elif method == "web_fetch":
            value += 85
        elif method == "ab_readonly_snapshot":
            value += 55
        elif method in {"pdf_direct", "docx_direct"}:
            value += 20
        if row.get("value_num") is not None:
            value += 15
        if obs >= 6:
            value += 40
        elif obs <= 1:
            value -= 8
        if any(term in text for term in AI_INDUCTOR_NOISE_TERMS):
            value -= 220
        if is_customer and any(term in text for term in ("顺络", "铂科", "龙磁", "英伟达", "Google", "谷歌", "华为", "TDK", "Murata", "中标", "小批量", "批量")):
            value += 90
        if is_material and any(term in text for term in ("羰基铁粉", "铁镍", "金属软磁", "软磁粉芯", "热压", "材料", "产能")):
            value += 80
        if is_company and any(term in text for term in ("顺络", "铂科", "龙磁", "悦安", "收入", "中标", "批量", "客户验证")):
            value += 80
        if is_price and any(term in text for term in ("需求量", "TAM", "价格", "涨价", "ASP", "毛利率", "型号")):
            value += 80
        if any(term in metric for term in ("GPU出货量", "ASIC 芯片", "平均单片用电感数", "芯片电感需求量", "GB300")):
            value += 70
        return (value, obs, -int(row.get("id") or 0))

    selected: list[dict] = []
    seen: set[str] = set()
    for row in sorted(rows, key=score, reverse=True):
        metric = str(row.get("metric") or "")
        excerpt = str(row.get("source_excerpt") or "")
        if any(term in f"{metric} {excerpt}" for term in AI_INDUCTOR_NOISE_TERMS):
            continue
        key = f"{metric}|{excerpt[:80]}"
        if key in seen:
            continue
        selected.append(row)
        seen.add(key)
        if len(selected) >= limit:
            break
    if not selected:
        selected = sorted(rows, key=score, reverse=True)[:limit]
    return sorted(selected, key=lambda row: int(row.get("id") or 0))


def _curate_entity_data_points(entity: dict, rows: list[dict], limit: int = 24) -> list[dict]:
    entity_name = str(entity.get("display_name") or entity.get("canonical_name") or "").lower()
    if _is_ai_inductor_entity(entity_name, rows):
        return _curate_ai_inductor_data_points(entity_name, rows, limit)
    is_shale_entity = "页岩" in entity_name or "钻机" in entity_name
    if is_shale_entity:
        limit = min(limit, 12)
    core_terms = (
        "wti",
        "brent",
        "brent-wti",
        "cushing",
        "commercial",
        "total stocks",
        "excluding spr",
        "crude oil",
        "refinery",
        "product supplied",
        "field production",
        "imports",
        "exports",
        "steo",
        "cftc",
        "hormuz",
        "opec",
        "rig",
        "spr",
    )
    shale_core_terms = (
        "页岩",
        "钻机",
        "rig",
        "drilling",
        "domestic production",
        "field production",
        "crude oil production",
        "lower 48",
        "alaska",
        "wti",
        "steo",
    )
    shale_noise_terms = (
        "products imports",
        "products exports",
        "total products",
        "refiner and blender",
        "gasoline",
        "distillate",
        "jet fuel",
        "residual fuel",
        "padd 1",
        "padd 2",
        "padd 3",
        "padd 4",
        "padd 5",
        "east coast",
        "midwest",
        "gulf coast",
        "rocky mountain",
        "west coast",
    )
    granular_terms = (
        "new england",
        "central atlantic",
        "lower atlantic",
        "padd 1a",
        "padd 1b",
        "padd 1c",
        "california",
        "gtab",
        "cbob",
        "rbob",
        "ed55",
        "15 ppm",
        "500 ppm",
        "kerosene",
        "propane",
        "asphalt",
        "other oils",
        "unfinished oils",
        "口径组",
    )

    def score(row: dict) -> tuple[int, int, int]:
        metric = str(row.get("metric") or "").lower()
        obs = _series_observation_count(row)
        value = 0
        if any(term in metric for term in core_terms):
            value += 80
        if is_shale_entity:
            if any(term in metric for term in shale_core_terms):
                value += 140
            if any(term in metric for term in shale_noise_terms):
                value -= 180
        if obs >= 24:
            value += 30
        elif obs >= 6:
            value += 15
        elif obs <= 2:
            value -= 15
        if any(term in metric for term in granular_terms):
            value -= 70
        if str(row.get("source_title") or "").lower().startswith("eia wpsr table"):
            value -= 5
        return (value, obs, -int(row.get("id") or 0))

    selected: list[dict] = []
    seen_metrics: set[str] = set()
    for row in sorted(rows, key=score, reverse=True):
        metric = str(row.get("metric") or "")
        if metric in seen_metrics:
            continue
        selected.append(row)
        seen_metrics.add(metric)
        if len(selected) >= limit:
            break
    return sorted(selected, key=lambda row: int(row.get("id") or 0))


def list_runs(
    limit: int = 50,
    status: str | None = None,
    readiness_status: str | None = None,
    db_path: str | Path = DB_PATH,
) -> list[dict]:
    conn = _connect_read(db_path)
    if conn is None:
        return []
    try:
        limit = max(1, min(int(limit), 200))
        params: list[Any] = []
        clauses: list[str] = []
        if status:
            clauses.append("r.run_status=?")
            params.append(status)
        if readiness_status:
            clauses.append("r.run_readiness_status=?")
            params.append(readiness_status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = dict_rows(
            conn.execute(
                f"""
                SELECT r.*, s.source_count, s.independent_source_count, s.candidate_count,
                       s.canonical_entity_count, s.scored_entity_count, s.open_p0_count,
                       s.open_p1_count, s.supplement_open_count,
                       c.intake_material_type, c.available_materials_choice
                FROM opportunity_run r
                LEFT JOIN opportunity_run_stats s ON s.run_id=r.id
                LEFT JOIN opportunity_intake_contract c ON c.run_id=r.id
                {where}
                ORDER BY r.id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        )
        return [_sanitize_run_row(row) for row in rows]
    finally:
        conn.close()


def get_intake_contract(run_id: int, db_path: str | Path = DB_PATH) -> dict | None:
    conn = _connect_read(db_path)
    if conn is None:
        return None
    try:
        row = dict_row(
            conn.execute(
                "SELECT * FROM opportunity_intake_contract WHERE run_id=?",
                (run_id,),
            ).fetchone()
        )
        if not row:
            return None
        for key, public_key, default in [
            ("time_window_json", "time_window", {}),
            ("research_scope_json", "research_scope", {}),
            ("special_constraints_json", "special_constraints", {}),
            ("field_origin_json", "field_origin", {}),
            ("default_accepted_json", "default_accepted", {}),
            ("parsed_intake_json", "parsed_intake", {}),
            ("validation_issue_json", "validation_issues", []),
        ]:
            row[public_key] = loads_json(row.pop(key, None), default)
        row.pop("raw_payload_json", None)
        row.pop("raw_intake_text", None)
        return row
    finally:
        conn.close()


def get_early_signals(run_id: int, db_path: str | Path = DB_PATH) -> list[dict]:
    conn = _connect_read(db_path)
    if conn is None:
        return []
    try:
        rows = dict_rows(
            conn.execute(
                """
                SELECT es.*, e.display_name, e.canonical_name, e.entity_type
                FROM opportunity_early_signal_aggregate es
                JOIN opportunity_entity e ON e.id=es.entity_id
                WHERE es.run_id=? AND es.early_signal_rule_version=?
                ORDER BY es.research_priority_score DESC NULLS LAST, es.early_signal_score DESC NULLS LAST, es.id
                """,
                (run_id, EARLY_SIGNAL_RULE_VERSION),
            ).fetchall()
        )
        for row in rows:
            row["evidence_ref_uri_list"] = loads_json(row.pop("evidence_ref_uri_list_json", None), [])
            row["aggregate_trace"] = loads_json(row.pop("aggregate_trace_json", None), {})
        return rows
    finally:
        conn.close()


def get_run(run_id: int, db_path: str | Path = DB_PATH) -> dict | None:
    conn = _connect_read(db_path)
    if conn is None:
        return None
    try:
        row = dict_row(
            conn.execute(
                """
                SELECT r.*, s.source_count, s.independent_source_count, s.candidate_count,
                       s.canonical_entity_count, s.scored_entity_count, s.open_p0_count,
                       s.open_p1_count, s.supplement_open_count
                FROM opportunity_run r
                LEFT JOIN opportunity_run_stats s ON s.run_id=r.id
                WHERE r.id=?
                """,
                (run_id,),
            ).fetchone()
        )
        if not row:
            return None
        row = _sanitize_run_row(row)
        row["flag_summary"] = run_flag_summary(conn, run_id)
        row["intake_contract"] = get_intake_contract(run_id, db_path=db_path)
        row["early_signals"] = get_early_signals(run_id, db_path=db_path)
        row["sections"] = get_sections(run_id, db_path=db_path)
        row["nav"] = dict_rows(
            conn.execute(
                "SELECT nav_key, label, href, sort_order FROM opportunity_navigation_index WHERE run_id=? ORDER BY sort_order",
                (run_id,),
            ).fetchall()
        )
        return row
    finally:
        conn.close()


def get_sections(run_id: int, db_path: str | Path = DB_PATH) -> list[dict]:
    conn = _connect_read(db_path)
    if conn is None:
        return []
    try:
        rows = dict_rows(
            conn.execute(
                """
                SELECT rs.*, e.display_name AS entity_display_name,
                       e.canonical_name AS entity_canonical_name,
                       cs.score_point AS entity_score_point,
                       COALESCE(rp.entity_research_mode, 'market_linked') AS entity_research_mode
                FROM opportunity_report_section rs
                LEFT JOIN opportunity_entity e ON e.id=rs.entity_id
                LEFT JOIN opportunity_composite_score cs
                  ON cs.run_id=rs.run_id AND cs.entity_id=rs.entity_id AND cs.is_current=1
                LEFT JOIN opportunity_entity_research_profile rp
                  ON rp.run_id=rs.run_id AND rp.entity_id=rs.entity_id
                WHERE rs.run_id=?
                ORDER BY rs.sort_order, cs.score_point DESC NULLS LAST, rs.id
                """,
                (run_id,),
            ).fetchall()
        )
        top_sections: list[dict] = []
        entity_sections: list[dict] = []
        for row in rows:
            row["evidence_ref_uri_list"] = loads_json(row.pop("evidence_ref_uri_list_json", None), [])
            row["flag_reason"] = loads_json(row.pop("flag_reason_json", None), [])
            if row.get("entity_id"):
                entity_title = row.get("entity_display_name") or row.get("entity_canonical_name") or "未命名研究实体"
                row["original_section_title"] = row.get("section_title")
                row["section_title"] = entity_title
                row["entity_link"] = f"/opportunity-lens/entity/{row['entity_id']}"
                entity_sections.append(row)
            else:
                top_sections.append(row)
        if entity_sections:
            entity_sections.sort(
                key=lambda row: (
                    -float(row.get("entity_score_point") or -1),
                    int(row.get("id") or 0),
                )
            )
            evidence_refs: list[str] = []
            seen_refs: set[str] = set()
            for section in entity_sections:
                for ref in section.get("evidence_ref_uri_list") or []:
                    if ref and ref not in seen_refs:
                        seen_refs.add(ref)
                        evidence_refs.append(ref)
            has_theory_entity = any(
                section.get("entity_research_mode") == "theory_research"
                for section in entity_sections
            )
            top_sections.append(
                {
                    "id": None,
                    "run_id": run_id,
                    "entity_id": None,
                    "section_key": "entity_research_profiles",
                    "section_title": "研究实体介绍、证据链与研究结论" if has_theory_entity else "研究实体介绍、证据链与投资结论",
                    "body_markdown": "",
                    "support_status": "supported",
                    "red_flag_level": "none",
                    "flag_derivation_source": "system",
                    "flag_reason": [],
                    "review_status": "accepted",
                    "evidence_ref_uri_list": evidence_refs[:20],
                    "sort_order": min(int(row.get("sort_order") or 100) for row in entity_sections),
                    "child_sections": entity_sections,
                }
            )
        return sorted(top_sections, key=lambda row: (int(row.get("sort_order") or 0), int(row.get("id") or 10**9)))
    finally:
        conn.close()


def get_run_entities(run_id: int, limit: int = 100, db_path: str | Path = DB_PATH) -> list[dict]:
    conn = _connect_read(db_path)
    if conn is None:
        return []
    try:
        limit = max(1, min(int(limit), 300))
        rows = dict_rows(
            conn.execute(
                """
	                SELECT e.id AS entity_id, e.entity_type, e.canonical_name, e.display_name,
	                       em.maturation_status, em.readiness_score,
	                       COALESCE(rp.entity_research_mode, 'market_linked') AS entity_research_mode,
	                       rp.research_depth_status,
	                       cs.id AS composite_score_id, cs.score_batch_id, cs.score_point,
                       cs.score_band_low, cs.score_band_high, cs.score_grade,
                       cs.score_status, cs.rating_status, cs.score_quality_label,
                       cs.coverage, cs.confidence, cs.evidence_ref_uri_list_json,
                       es.early_signal_score, es.early_signal_strength_label,
                       es.research_priority_score, es.research_priority_label,
                       es.core_score_changed_by_overlay
                FROM opportunity_entity_maturation em
                JOIN opportunity_entity e ON e.id=em.entity_id
	                LEFT JOIN opportunity_composite_score cs
	                  ON cs.run_id=em.run_id AND cs.entity_id=em.entity_id AND cs.is_current=1
	                LEFT JOIN opportunity_entity_research_profile rp
	                  ON rp.run_id=em.run_id AND rp.entity_id=em.entity_id
	                LEFT JOIN opportunity_early_signal_aggregate es
                  ON es.run_id=em.run_id AND es.entity_id=em.entity_id
                 AND es.early_signal_rule_version=?
                WHERE em.run_id=?
	                ORDER BY CASE COALESCE(rp.entity_research_mode, 'market_linked') WHEN 'market_linked' THEN 0 ELSE 1 END,
	                         cs.score_point DESC NULLS LAST, e.id
                LIMIT ?
                """,
                (EARLY_SIGNAL_RULE_VERSION, run_id, limit),
            ).fetchall()
        )
        for row in rows:
            row["evidence_ref_uri_list"] = loads_json(row.pop("evidence_ref_uri_list_json", None), [])
        return rows
    finally:
        conn.close()


def get_run_entity_by_name(
    run_id: int,
    entity_name: str,
    db_path: str | Path = DB_PATH,
) -> dict | None:
    """Resolve a stable run-scoped entity link without exposing a database id.

    Opportunity Lens pack builders know the entity's canonical/display name before
    the loader assigns its numeric id.  This read-only lookup lets report Markdown
    link straight to that entity while preserving the existing numeric detail route.
    """

    name = str(entity_name or "").strip()
    if not name:
        return None
    conn = _connect_read(db_path)
    if conn is None:
        return None
    try:
        return dict_row(
            conn.execute(
                """
                SELECT e.id AS entity_id, e.canonical_name, e.display_name
                FROM opportunity_entity_maturation em
                JOIN opportunity_entity e ON e.id=em.entity_id
                WHERE em.run_id=?
                  AND (e.canonical_name=? OR e.display_name=?)
                ORDER BY CASE WHEN e.display_name=? THEN 0 ELSE 1 END, e.id
                LIMIT 1
                """,
                (run_id, name, name, name),
            ).fetchone()
        )
    finally:
        conn.close()


def get_run_rating_gap_summary(
    run_id: int,
    *,
    max_labels: int = 5,
    db_path: str | Path = DB_PATH,
) -> dict:
    """Summarize score-blocking metric gaps without changing stored scores."""

    conn = _connect_read(db_path)
    if conn is None:
        return {"missing_slot_count": 0, "missing_metric_count": 0, "labels": [], "summary": ""}
    try:
        slots = dict_rows(
            conn.execute(
                """
                SELECT ms.slot_key, ms.slot_label, ms.metric_name, ms.value_status,
                       ms.slot_score, ms.scoring_eligibility
                FROM opportunity_metric_slot ms
                WHERE ms.run_id=?
                ORDER BY ms.entity_id, ms.factor_code, ms.slot_key
                """,
                (run_id,),
            ).fetchall()
        )
        counts = Counter(
            str(slot.get("slot_label") or slot.get("metric_name") or slot.get("slot_key") or "").strip()
            for slot in slots
            if is_missing_scoring_slot(slot)
        )
        counts.pop("", None)
        ordered = sorted(counts, key=lambda label: (-counts[label], label))
        limit = max(1, int(max_labels))
        shown = ordered[:limit]
        if not shown:
            summary = ""
        else:
            summary = "、".join(shown)
            if len(ordered) > limit:
                summary += f"等{len(ordered)}类指标"
        return {
            "missing_slot_count": sum(counts.values()),
            "missing_metric_count": len(ordered),
            "labels": shown,
            "summary": summary,
        }
    finally:
        conn.close()


def get_entity(entity_id: int, run_id: int | None = None, db_path: str | Path = DB_PATH) -> dict | None:
    conn = _connect_read(db_path)
    if conn is None:
        return None
    try:
        entity = dict_row(conn.execute("SELECT * FROM opportunity_entity WHERE id=?", (entity_id,)).fetchone())
        if not entity:
            return None
        maturation_params: list[Any] = [entity_id]
        maturation_run_clause = ""
        if run_id is not None:
            maturation_run_clause = " AND em.run_id=?"
            maturation_params.append(run_id)
        entity["maturation"] = dict_rows(
            conn.execute(
                f"""
                SELECT em.*, r.research_question
                FROM opportunity_entity_maturation em
                JOIN opportunity_run r ON r.id=em.run_id
                WHERE em.entity_id=? {maturation_run_clause}
                ORDER BY em.run_id DESC
                """,
                maturation_params,
            ).fetchall()
        )
        profile_params: list[Any] = [entity_id]
        profile_run_clause = ""
        if run_id is not None:
            profile_run_clause = " AND rp.run_id=?"
            profile_params.append(run_id)
        profile = dict_row(
            conn.execute(
                f"""
                SELECT rp.*, r.research_question AS run_research_question
                FROM opportunity_entity_research_profile rp
                JOIN opportunity_run r ON r.id=rp.run_id
                WHERE rp.entity_id=? {profile_run_clause}
                ORDER BY rp.run_id DESC, rp.id DESC
                LIMIT 1
                """,
                profile_params,
            ).fetchone()
        ) if _table_exists(conn, "opportunity_entity_research_profile") else None
        if profile:
            profile["evidence_ref_uri_list"] = loads_json(profile.pop("evidence_ref_uri_list_json", None), [])
        entity["research_profile"] = profile
        entity["entity_research_mode"] = (profile or {}).get("entity_research_mode") or "market_linked"
        source_params: list[Any] = [entity_id]
        source_run_clause = ""
        if run_id is not None:
            source_run_clause = " AND ce.run_id=?"
            source_params.append(run_id)
        entity["sources"] = dict_rows(
            conn.execute(
                f"""
                SELECT DISTINCT s.id, s.title, s.title_zh, s.source_tier, s.source_review_status,
                       s.publisher, s.publish_date, s.url, s.excerpt, s.excerpt_zh, s.language,
                       s.evidence_ref_uri
                FROM opportunity_claim_evidence ce
                JOIN opportunity_source s ON s.id=ce.source_id
                WHERE ce.entity_id=? {source_run_clause}
                ORDER BY s.source_tier, s.id
                """,
                source_params,
            ).fetchall()
        )
        for row in entity["sources"]:
            _annotate_source_display(row)
        section_params: list[Any] = [entity_id]
        section_run_clause = ""
        if run_id is not None:
            section_run_clause = " AND rs.run_id=?"
            section_params.append(run_id)
        entity["sections"] = dict_rows(
            conn.execute(
                f"""
                SELECT rs.*, r.research_question
                FROM opportunity_report_section rs
                JOIN opportunity_run r ON r.id=rs.run_id
                WHERE rs.entity_id=? {section_run_clause}
                ORDER BY rs.run_id DESC, rs.sort_order, rs.id
                """,
                section_params,
            ).fetchall()
        )
        for row in entity["sections"]:
            row["evidence_ref_uri_list"] = loads_json(row.pop("evidence_ref_uri_list_json", None), [])
            row["flag_reason"] = loads_json(row.pop("flag_reason_json", None), [])
        data_point_params: list[Any] = [entity_id]
        data_point_run_clause = ""
        if run_id is not None:
            data_point_run_clause = " AND dp.run_id=?"
            data_point_params.append(run_id)
        entity["data_points"] = dict_rows(
            conn.execute(
                f"""
                SELECT dp.*, s.title AS source_title, s.title_zh AS source_title_zh,
                       s.publisher AS source_publisher,
                       s.publish_date AS source_publish_date, s.source_tier,
                       s.source_review_status, s.url AS source_url,
                       s.language AS source_language
                FROM opportunity_data_point dp
                LEFT JOIN opportunity_source s ON s.id=dp.source_id
                WHERE dp.entity_id=? {data_point_run_clause}
                ORDER BY dp.run_id DESC, dp.id
                """,
                data_point_params,
            ).fetchall()
        )
        for row in entity["data_points"]:
            row["value_display"] = _value_display(row)
            row["observation_count"] = _series_observation_count(row)
            _annotate_data_point_display(row)
        entity["data_point_total_count"] = len(entity["data_points"])
        entity["display_data_points"] = _curate_entity_data_points(entity, entity["data_points"])
        research_dp_params: list[Any] = [entity_id]
        research_dp_run_clause = ""
        if run_id is not None:
            research_dp_run_clause = " AND rdp.run_id=?"
            research_dp_params.append(run_id)
        if _table_exists(conn, "opportunity_research_data_point"):
            entity["research_data_points"] = dict_rows(
                conn.execute(
                    f"""
                    SELECT rdp.*, s.title AS source_title, s.title_zh AS source_title_zh,
                           s.publisher AS source_publisher,
                           s.publish_date AS source_publish_date, s.url AS source_url,
                           s.source_tier, s.source_review_status, s.language AS source_language
                    FROM opportunity_research_data_point rdp
                    LEFT JOIN opportunity_source s ON s.id=rdp.source_id
                    WHERE rdp.entity_id=? {research_dp_run_clause}
                    ORDER BY rdp.run_id DESC, rdp.sort_order, rdp.id
                    """,
                    research_dp_params,
                ).fetchall()
            )
            for row in entity["research_data_points"]:
                _annotate_research_data_point_display(row)
        else:
            entity["research_data_points"] = []
        visual_params: list[Any] = [entity_id]
        visual_run_clause = ""
        if run_id is not None:
            visual_run_clause = " AND run_id=?"
            visual_params.append(run_id)
        entity["visuals"] = [
            _hydrate_visual_row(row, db_path)
            for row in dict_rows(
                conn.execute(
                    f"""
                    SELECT *
                    FROM opportunity_visual_block
                    WHERE entity_id=? {visual_run_clause}
                      AND block_type IN ('line_chart', 'time_series')
                    ORDER BY run_id DESC, sort_order, id
                    """,
                    visual_params,
                ).fetchall()
            )
        ]
        claim_params: list[Any] = [entity_id]
        claim_run_clause = ""
        if run_id is not None:
            claim_run_clause = " AND ce.run_id=?"
            claim_params.append(run_id)
        entity["claims"] = dict_rows(
            conn.execute(
                f"""
                SELECT ce.*, s.title AS source_title, s.title_zh AS source_title_zh,
                       s.publisher AS source_publisher,
                       s.publish_date AS source_publish_date, s.source_tier,
                       s.source_review_status, s.url AS source_url,
                       s.language AS source_language
                FROM opportunity_claim_evidence ce
                LEFT JOIN opportunity_source s ON s.id=ce.source_id
                WHERE ce.entity_id=? {claim_run_clause}
                ORDER BY ce.run_id DESC, ce.id
                """,
                claim_params,
            ).fetchall()
        )
        for row in entity["claims"]:
            _annotate_data_point_display(row)
        if _table_exists(conn, "opportunity_entity_investment_target"):
            target_params: list[Any] = [entity_id]
            target_run_clause = ""
            if run_id is not None:
                target_run_clause = " AND run_id=?"
                target_params.append(run_id)
            entity["investment_targets"] = dict_rows(
                conn.execute(
                    f"""
                    SELECT *
                    FROM opportunity_entity_investment_target
                    WHERE entity_id=? {target_run_clause}
                    ORDER BY run_id DESC, sort_order, id
                    """,
                    target_params,
                ).fetchall()
            )
            for row in entity["investment_targets"]:
                row["target_link"] = _target_link(row)
                row["target_detail_link"] = _target_detail_link(row)
        else:
            entity["investment_targets"] = []
        entity["score"] = get_entity_score_trace(conn, entity_id)
        entity["audit_issues"] = dict_rows(
            conn.execute(
                "SELECT * FROM opportunity_audit_issue WHERE entity_id=? ORDER BY id",
                (entity_id,),
            ).fetchall()
        )
        entity["entity_research_brief"] = _entity_research_brief(
            entity,
            entity["data_points"],
            entity["claims"],
            entity["investment_targets"],
        )
        return entity
    finally:
        conn.close()


def get_target(target_id: int, db_path: str | Path = DB_PATH) -> dict | None:
    conn = _connect_read(db_path)
    if conn is None:
        return None
    try:
        target = dict_row(
            conn.execute(
                """
                SELECT t.*, e.display_name AS entity_display_name,
                       e.canonical_name AS entity_canonical_name,
                       e.entity_type, r.research_question
                FROM opportunity_entity_investment_target t
                JOIN opportunity_entity e ON e.id=t.entity_id
                JOIN opportunity_run r ON r.id=t.run_id
                WHERE t.id=?
                """,
                (target_id,),
            ).fetchone()
        )
        if not target:
            return None
        target["target_link"] = _target_link(target)
        target["target_detail_link"] = _target_detail_link(target)
        if _table_exists(conn, "opportunity_target_data_point"):
            data_points = dict_rows(
                conn.execute(
                    """
                    SELECT *
                    FROM opportunity_target_data_point
                    WHERE target_id=?
                    ORDER BY sort_order, id
                    """,
                    (target_id,),
                ).fetchall()
            )
            for row in data_points:
                row["value_display"] = _value_display(row)
                _annotate_target_data_point_display(row)
            target["target_data_points"] = data_points
        else:
            target["target_data_points"] = []
        target["ab_company_financials"] = _ab_company_financials(target.get("company_id"))
        target["entity_link"] = f"/opportunity-lens/entity/{target['entity_id']}"
        target["run_link"] = f"/opportunity-lens/run/{target['run_id']}"
        return target
    finally:
        conn.close()


def get_score(entity_id: int, score_batch_id: int | None = None, db_path: str | Path = DB_PATH) -> dict | None:
    conn = _connect_read(db_path)
    if conn is None:
        return None
    try:
        return get_entity_score_trace(conn, entity_id, score_batch_id=score_batch_id)
    finally:
        conn.close()


def get_factor(factor_score_id: int, db_path: str | Path = DB_PATH) -> dict | None:
    conn = _connect_read(db_path)
    if conn is None:
        return None
    try:
        return get_factor_trace(conn, factor_score_id)
    finally:
        conn.close()


def get_metric_slot(slot_id: int, db_path: str | Path = DB_PATH) -> dict | None:
    conn = _connect_read(db_path)
    if conn is None:
        return None
    try:
        return get_metric_slot_trace(conn, slot_id)
    finally:
        conn.close()


def get_audit_board(run_id: int, db_path: str | Path = DB_PATH) -> dict:
    conn = _connect_read(db_path)
    if conn is None:
        return {"issues": [], "summary": {"red": 0, "yellow": 0, "level": "none", "top_reason": None}}
    try:
        issues = dict_rows(
            conn.execute(
                "SELECT * FROM opportunity_audit_issue WHERE run_id=? ORDER BY audit_severity, id",
                (run_id,),
            ).fetchall()
        )
        for issue in issues:
            affected = str(issue.get("affected_uri") or "").strip()
            issue["affected_display"] = "当前研究运行"
            if affected:
                run_match = re.fullmatch(r"opp://run/(\d+)", affected)
                if run_match:
                    run_row = conn.execute(
                        "SELECT research_question FROM opportunity_run WHERE id=?",
                        (int(run_match.group(1)),),
                    ).fetchone()
                    issue["affected_display"] = (
                        f"扫描 {run_match.group(1)}：{run_row['research_question']}"
                        if run_row else f"扫描 {run_match.group(1)}"
                    )
                    continue
                try:
                    resolved = resolve(affected, conn=conn)
                    explanation = (resolved or {}).get("human_explanation") or {}
                    issue["affected_display"] = explanation.get("headline") or "已关联研究对象"
                except Exception:
                    issue["affected_display"] = "已登记的内部研究对象"
        return {"issues": issues, "summary": run_flag_summary(conn, run_id)}
    finally:
        conn.close()


def get_supplement_requests(run_id: int, db_path: str | Path = DB_PATH) -> list[dict]:
    conn = _connect_read(db_path)
    if conn is None:
        return []
    try:
        return dict_rows(
            conn.execute(
                "SELECT * FROM opportunity_supplement_request WHERE run_id=? ORDER BY priority, id",
                (run_id,),
            ).fetchall()
        )
    finally:
        conn.close()


def _score_value(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("-inf")


SOURCE_URI_RE = re.compile(r"opp://source/(\d+)")


@lru_cache(maxsize=4096)
def _source_readable_label(source_id: int, db_path: str) -> str:
    conn = _connect_read(db_path)
    if conn is None:
        return f"来源 {source_id}"
    try:
        row = conn.execute(
            """
            SELECT title, publisher, publish_date
            FROM opportunity_source
            WHERE id=?
            """,
            (int(source_id),),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return f"来源 {source_id}"
    title = str(row["title"] or f"来源 {source_id}").strip()
    publisher = str(row["publisher"] or "").strip()
    publish_date = str(row["publish_date"] or "").strip()
    suffix = "，".join(part for part in (publisher, publish_date) if part)
    return f"{title}（{suffix}）" if suffix else title


def _replace_source_uri_with_label(value: str, db_path: str | Path = DB_PATH) -> str:
    resolved_db_path = str(Path(db_path).resolve())
    return SOURCE_URI_RE.sub(
        lambda match: _source_readable_label(int(match.group(1)), resolved_db_path),
        value,
    )


def _visual_cell_text(value, db_path: str | Path = DB_PATH):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return _replace_source_uri_with_label(value, db_path)
    if isinstance(value, list):
        return "；".join(str(_visual_cell_text(item, db_path)) for item in value)
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            parts.append(f"{key}: {_visual_cell_text(item, db_path)}")
        return "；".join(parts)
    return str(value)


def _columns_from_dict_rows(rows: list) -> list[str]:
    columns: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in row.keys():
            if key not in columns:
                columns.append(key)
    return columns


def _table_from_columns_rows(columns, rows, db_path: str | Path = DB_PATH) -> dict:
    if not isinstance(columns, list) or not columns or not isinstance(rows, list):
        return {}
    normalized_rows = []
    for row in rows:
        if isinstance(row, dict):
            normalized_rows.append([_visual_cell_text(row.get(col, ""), db_path) for col in columns])
        elif isinstance(row, list):
            normalized_rows.append([_visual_cell_text(cell, db_path) for cell in row])
        else:
            normalized_rows.append([_visual_cell_text(row, db_path)])
    return {"columns": [str(col) for col in columns], "rows": normalized_rows}


def _coerce_visual_display_data(payload, db_path: str | Path = DB_PATH) -> dict:
    if not isinstance(payload, dict):
        return {}
    columns = payload.get("columns")
    rows = payload.get("rows")
    if isinstance(rows, list):
        if not isinstance(columns, list) or not columns:
            columns = _columns_from_dict_rows(rows)
        table = _table_from_columns_rows(columns, rows, db_path)
        if table:
            return table
    items = payload.get("items")
    if isinstance(items, list):
        columns = payload.get("columns")
        if not isinstance(columns, list) or not columns:
            columns = _columns_from_dict_rows(items)
        table = _table_from_columns_rows(columns, items, db_path)
        if table:
            return table
    factors = payload.get("factors")
    if isinstance(factors, list):
        return _factor_display_data_from_factors(factors, db_path)
    matrix = payload.get("matrix")
    if isinstance(matrix, list):
        columns = payload.get("columns")
        if not isinstance(columns, list) or not columns:
            columns = _columns_from_dict_rows(matrix)
        table = _table_from_columns_rows(columns, matrix, db_path)
        if table:
            return table
    return {}


def _factor_display_data_from_factors(factors: list, db_path: str | Path = DB_PATH) -> dict:
    factor_rows = []
    for factor in factors:
        if not isinstance(factor, dict):
            continue
        label = factor.get("factor_label") or factor.get("factor_code") or ""
        score_status = str(factor.get("score_status") or "complete")
        readiness = str(factor.get("factor_readiness_status") or "limited")
        score_displayable = score_status == "complete" and readiness in {"ready", "limited"}
        factor_rows.append(
            {
                "因子中文名": label,
                "调整后分数": factor.get("score_adjusted", "") if score_displayable else "证据不足",
                "计算公式": factor.get("factor_formula", ""),
                "因子代码": factor.get("factor_code", ""),
            }
        )
    return _table_from_columns_rows(["因子中文名", "调整后分数", "计算公式", "因子代码"], factor_rows, db_path)


def _sort_heatmap_display_data(display_data: dict) -> dict:
    if not isinstance(display_data, dict):
        return display_data
    columns = display_data.get("columns")
    rows = display_data.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list):
        return display_data
    score_index = None
    for name in ("调整后分数", "score_adjusted"):
        if name in columns:
            score_index = columns.index(name)
            break
    if score_index is None:
        return display_data
    def sort_value(row):
        if not isinstance(row, list) or len(row) <= score_index:
            return float("-inf")
        return _score_value(row[score_index]) if isinstance(row[score_index], (int, float)) else float("-inf")
    display_data["rows"] = sorted(
        rows,
        key=sort_value,
        reverse=True,
    )
    return display_data


def _hydrate_visual_row(row: dict, db_path: str | Path = DB_PATH) -> dict:
    row["data"] = loads_json(row.pop("data_json", None), {})
    row["display_data"] = loads_json(row.pop("display_data_json", None), {})
    row["print_fallback"] = loads_json(row.pop("print_fallback_json", None), {})
    display_data = (
        _coerce_visual_display_data(row["display_data"], db_path)
        or _coerce_visual_display_data(row["data"], db_path)
        or _coerce_visual_display_data(row["print_fallback"], db_path)
    )
    print_fallback = (
        _coerce_visual_display_data(row["print_fallback"], db_path)
        or display_data
        or _coerce_visual_display_data(row["data"], db_path)
    )
    row["display_data"] = display_data
    row["print_fallback"] = print_fallback
    row["evidence_ref_uri_list"] = loads_json(row.pop("evidence_ref_uri_list_json", None), [])
    if row.get("block_type") == "heatmap" and isinstance(row["data"].get("factors"), list):
        readiness_by_code: dict[str, dict] = {}
        if row.get("run_id") and row.get("entity_id"):
            conn = _connect_read(db_path)
            if conn is not None:
                try:
                    readiness_rows = dict_rows(
                        conn.execute(
                            """
                            SELECT r.factor_code, r.factor_readiness_status, r.missing_reason
                            FROM opportunity_factor_readiness r
                            WHERE r.run_id=? AND r.entity_id=?
                              AND r.id=(
                                SELECT MAX(r2.id) FROM opportunity_factor_readiness r2
                                WHERE r2.run_id=r.run_id AND r2.entity_id=r.entity_id
                                  AND r2.factor_code=r.factor_code
                              )
                            """,
                            (row["run_id"], row["entity_id"]),
                        ).fetchall()
                    )
                    readiness_by_code = {
                        item["factor_code"]: item for item in readiness_rows
                    }
                finally:
                    conn.close()
        for factor in row["data"]["factors"]:
            if factor.get("factor_code"):
                factor.update(factor_metadata(factor["factor_code"]))
                readiness = readiness_by_code.get(factor["factor_code"], {})
                factor["factor_readiness_status"] = readiness.get(
                    "factor_readiness_status", factor.get("factor_readiness_status")
                )
                factor["missing_reason"] = readiness.get("missing_reason") or factor.get(
                    "missing_reason"
                )
        row["data"]["factors"] = sorted(
            row["data"]["factors"],
            key=lambda factor: _score_value(factor.get("score_adjusted")),
            reverse=True,
        )
        row["display_data"] = _factor_display_data_from_factors(row["data"]["factors"], db_path)
        row["print_fallback"] = row["display_data"]
        row["display_data"] = _sort_heatmap_display_data(row["display_data"])
        row["print_fallback"] = _sort_heatmap_display_data(row["print_fallback"])
    return row


def get_visuals(run_id: int, db_path: str | Path = DB_PATH) -> list[dict]:
    conn = _connect_read(db_path)
    if conn is None:
        return []
    try:
        rows = dict_rows(
            conn.execute(
                "SELECT * FROM opportunity_visual_block WHERE run_id=? ORDER BY sort_order, id",
                (run_id,),
            ).fetchall()
        )
        return [_hydrate_visual_row(row, db_path) for row in rows]
    finally:
        conn.close()


def get_export_status(run_id: int, job_id: int | str | None = "latest", db_path: str | Path = DB_PATH) -> dict:
    conn = _connect_read(db_path)
    if conn is None:
        return {"run_id": run_id, "job": None, "empty_state": "db_not_initialized"}
    try:
        if job_id in (None, "", "latest"):
            row = conn.execute(
                "SELECT * FROM opportunity_export_job WHERE run_id=? ORDER BY id DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM opportunity_export_job WHERE run_id=? AND id=?",
                (run_id, int(job_id)),
            ).fetchone()
        job = dict_row(row)
        if job and job.get("export_manifest_json"):
            job["manifest"] = loads_json(job.pop("export_manifest_json"), {})
        return {"run_id": run_id, "job": job, "empty_state": None if job else "export_not_requested"}
    finally:
        conn.close()


def resolve_evidence(ref: str, db_path: str | Path = DB_PATH) -> dict:
    conn = _connect_read(db_path)
    try:
        return resolve(ref, conn=conn)
    finally:
        if conn is not None:
            conn.close()
