from __future__ import annotations

import sqlite3
from typing import Any
from urllib.parse import urlparse

from .ab_readonly import resolve_ab_uri
from .db import connect, dict_row
from .display_annotations import chinese_translation, freshness_warning, source_original_text
from .display_labels import display_label
from .state_registry import URI_TABLES
from .validators import ValidationError, validate_uri

INTERNAL_SAFE_COLUMNS = {
    "intake_contract": [
        "id", "run_id", "research_question", "available_materials_choice",
        "intake_material_type", "evidence_policy", "intake_contract_version",
        "evidence_policy_version", "early_signal_rule_version", "intake_contract_hash",
    ],
    "source": [
        "id", "run_id", "title", "source_tier", "source_review_status", "publisher",
        "publish_date", "event_date", "fetch_date", "url", "local_path", "excerpt",
        "local_locator", "language", "evidence_ref_uri",
        "title_zh", "excerpt_zh",
        "policy_evidence_role", "policy_gate_verdict", "scoring_eligibility",
    ],
    "data_point": [
        "id", "run_id", "entity_id", "source_id", "metric", "period", "as_of_date",
        "value_num", "value_text", "unit", "source_excerpt", "value_status",
        "source_excerpt_zh", "calculation_review_status", "evidence_ref_uri",
        "policy_evidence_role", "policy_gate_verdict", "scoring_eligibility",
    ],
    "entity": [
        "id", "entity_type", "taxonomy_level", "canonical_name", "display_name",
        "description", "parent_entity_id", "external_ref_type", "external_ref_id",
    ],
    "metric_slot": [
        "id", "run_id", "entity_id", "factor_code", "slot_key", "slot_label",
        "metric_name", "metric_slot_status", "value_status", "slot_weight",
        "slot_score", "slot_confidence", "unit", "period", "as_of_date",
        "selected_data_point_id", "evidence_ref_uri",
        "policy_evidence_role", "policy_gate_verdict", "scoring_eligibility", "notes",
    ],
    "score_batch": [
        "id", "run_id", "score_rule_version", "score_batch_status", "is_current",
        "input_manifest_hash", "source_manifest_hash", "factor_manifest_hash",
        "rule_manifest_hash", "created_at", "completed_at", "failure_reason",
    ],
    "factor_score": [
        "id", "run_id", "score_batch_id", "entity_id", "factor_code", "score_status",
        "score_raw", "score_adjusted", "coverage", "confidence",
        "coverage_multiplier", "confidence_multiplier", "audit_multiplier",
        "reliability_multiplier", "evidence_ref_uri_list_json", "is_current",
    ],
    "composite_score": [
        "id", "run_id", "score_batch_id", "entity_id", "score_status", "score_grade",
        "rating_status", "score_quality_label", "score_point", "score_band_low",
        "score_band_high", "band_method", "band_reason", "coverage", "confidence",
        "audit_multiplier", "evidence_ref_uri_list_json", "research_bias_label",
        "is_current",
    ],
    "source_cluster": [
        "id", "run_id", "cluster_key", "cluster_label", "independence_rationale",
        "confidence",
    ],
    "event": [
        "id", "run_id", "entity_id", "event_scope", "event_type", "system_event_type",
        "event_category", "event_direction", "event_title", "event_summary",
        "event_date", "dedupe_key", "confidence", "score_effect",
        "official_confirmation_status", "evidence_ref_uri", "evidence_ref_uri_list_json",
        "policy_evidence_role", "policy_gate_verdict", "scoring_eligibility",
    ],
    "audit_issue": [
        "id", "run_id", "entity_id", "affected_uri", "audit_issue_type",
        "audit_severity", "audit_issue_status", "issue_title", "issue_detail",
        "evidence_ref_uri", "evidence_ref_uri_list_json", "reviewer", "waiver_reason",
    ],
    "supplement_request": [
        "id", "run_id", "entity_id", "request_title", "request_detail", "priority",
        "blocking_status", "review_status", "evidence_ref_uri",
    ],
    "visual_block": [
        "id", "run_id", "entity_id", "section_id", "block_key", "block_type",
        "title", "subtitle", "data_json", "print_fallback_json",
        "evidence_ref_uri_list_json", "support_status", "red_flag_level",
        "empty_state_reason",
    ],
    "early_signal": [
        "id", "run_id", "entity_id", "early_signal_rule_version", "evidence_policy",
        "early_signal_score", "early_signal_strength_label", "research_priority_score",
        "research_priority_label", "source_count", "independent_source_count",
        "verification_debt_count", "core_score_snapshot", "core_score_changed_by_overlay",
        "evidence_ref_uri_list_json", "excluded_from_core_reason",
    ],
    "investment_target": [
        "id", "run_id", "entity_id", "target_name", "ticker", "market",
        "target_type", "company_id", "target_url", "exposure_rationale",
        "evidence_ref_uri", "research_action", "investment_view", "risk_note",
        "target_priority", "target_quality_label", "relative_preference",
        "confirmed_scenario_action", "falsified_scenario_action",
        "conditional_investment_recommendation", "financial_data_status",
        "link_status", "support_status", "sort_order",
    ],
    "target_data_point": [
        "id", "run_id", "entity_id", "target_id", "metric_name", "metric_category",
        "period", "as_of_date", "value_num", "value_text", "unit",
        "source_title", "source_title_zh", "source_publisher", "source_url", "source_excerpt",
        "source_excerpt_zh", "source_language",
        "evidence_ref_uri", "data_quality_label", "direction",
        "credibility_weight", "numeric_weight", "direction_score",
        "weighted_contribution", "sort_order",
    ],
}


def _deep_link(object_type: str, row: dict[str, Any]) -> str | None:
    if object_type == "intake_contract":
        return f"/opportunity-lens/run/{row['run_id']}"
    if object_type == "entity":
        return f"/opportunity-lens/entity/{row['id']}"
    if object_type == "factor_score":
        return f"/opportunity-lens/factor/{row['id']}"
    if object_type == "metric_slot":
        return f"/opportunity-lens/metric-slot/{row['id']}"
    if object_type == "investment_target":
        return f"/opportunity-lens/target/{row['id']}"
    if object_type == "target_data_point":
        return f"/opportunity-lens/target/{row['target_id']}?evidence_ref=opp://target_data_point/{row['id']}"
    run_id = row.get("run_id")
    if run_id:
        return f"/opportunity-lens/run/{run_id}?evidence_ref=opp://{object_type}/{row['id']}"
    return None


def _format_value(row: dict[str, Any]) -> str:
    if row.get("value_num") is not None:
        return f"{row.get('value_num')} {row.get('unit') or ''}".strip()
    return f"{row.get('value_text') or ''} {row.get('unit') or ''}".strip()


def _annotate_record_for_display(object_type: str, row: dict[str, Any] | None) -> None:
    if not row:
        return
    for field_name in (
        "source_review_status", "policy_evidence_role", "policy_gate_verdict",
        "scoring_eligibility", "extraction_method", "calculation_review_status",
        "direction", "intake_material_type", "evidence_policy",
    ):
        if row.get(field_name) is not None:
            row[f"{field_name}_display"] = display_label(row[field_name])
    if object_type == "source":
        language = row.get("language")
        row["freshness_warning"] = freshness_warning(row.get("publish_date"))
        row["title_zh"] = row.get("title_zh") or chinese_translation(row.get("title"), language)
        row["excerpt_zh"] = row.get("excerpt_zh") or chinese_translation(row.get("excerpt"), language)
        row["excerpt_display"] = source_original_text(row.get("excerpt"))
        return
    if object_type == "data_point":
        row["freshness_warning"] = freshness_warning(row.get("period"), row.get("as_of_date"), row.get("source_excerpt"))
        row["source_excerpt_zh"] = row.get("source_excerpt_zh") or chinese_translation(row.get("source_excerpt"))
        row["source_excerpt_display"] = source_original_text(row.get("source_excerpt"))
        return
    if object_type == "target_data_point":
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


def _human_explanation(object_type: str, row: dict[str, Any]) -> dict[str, Any]:
    if object_type == "intake_contract":
        return {
            "headline": "这是本次扫描的入口合同。",
            "plain_steps": [
                f"研究问题：{row.get('research_question')}",
                f"资料选择：{row.get('available_materials_choice')}，业务类型为 {display_label(row.get('intake_material_type'))}",
                f"证据策略：{display_label(row.get('evidence_policy'))}",
            ],
            "json_guide": ["版本信息用于复现入口规则；校验摘要用于确认合同是否被改动。"],
        }
    if object_type == "early_signal":
        return {
            "headline": "这是早期信号 overlay，不是核心评分。",
            "plain_steps": [
                f"早期信号分：{row.get('early_signal_score')}",
                f"研究优先级：{row.get('research_priority_score')}，标签为 {row.get('research_priority_label')}",
                f"核心 14 因子评分是否被机会线索改写：{'否' if row.get('core_score_changed_by_overlay') == 0 else '是'}。",
            ],
            "json_guide": ["证据索引列出支撑该机会线索的全部可追溯来源。"],
        }
    if object_type == "source":
        language = row.get("language")
        plain_steps = [
            f"标题：{row.get('title')}",
            f"发布方：{row.get('publisher') or '未标明'}",
            f"发布时间：{row.get('publish_date') or '未标明'}",
            f"来源等级：{row.get('source_tier')}",
            f"复核状态：{display_label(row.get('source_review_status'))}",
            f"原文摘录：{row.get('excerpt_display') or row.get('excerpt') or '未录入'}",
        ]
        optional_dates = (
            ("事件/版本日期", row.get("event_date")),
            ("抓取日期", row.get("fetch_date")),
            ("原文定位", row.get("local_locator")),
        )
        plain_steps[3:3] = [f"{label}：{value}" for label, value in optional_dates if value]
        title_zh = row.get("title_zh") or chinese_translation(row.get("title"), language)
        excerpt_zh = row.get("excerpt_zh") or chinese_translation(row.get("excerpt"), language)
        stale = freshness_warning(row.get("publish_date"))
        if title_zh:
            plain_steps.append(f"中文标题：{title_zh}")
        if excerpt_zh:
            plain_steps.append(f"原文摘录中文译意：{excerpt_zh}")
        if stale:
            plain_steps.append(stale)
        return {
            "headline": row.get("title") or f"来源 {row.get('id')}",
            "plain_steps": plain_steps,
            "json_guide": [
                "这里展示的是来源记录的只读快照。",
                "原文摘录是本次研究实际使用的关键事实，不等于整篇材料摘要。",
                "证据角色、门槛结论和评分资格共同决定该来源能否进入核心评分。",
            ],
        }
    if object_type == "data_point":
        plain_steps = [
            f"指标：{row.get('metric')}",
            f"期间：{row.get('period') or row.get('as_of_date') or '未标明'}",
            f"数值：{_format_value(row)}",
            f"来源关联：{'已关联' if row.get('source_id') else '未关联'}",
            f"原文摘录：{row.get('source_excerpt_display') or row.get('source_excerpt') or '未录入'}",
        ]
        excerpt_zh = row.get("source_excerpt_zh") or chinese_translation(row.get("source_excerpt"))
        stale = freshness_warning(row.get("period"), row.get("as_of_date"), row.get("source_excerpt"))
        if excerpt_zh:
            plain_steps.append(f"原文摘录中文译意：{excerpt_zh}")
        if stale:
            plain_steps.append(stale)
        return {
            "headline": f"数据点：{row.get('metric')}" if row.get("metric") else f"数据点 {row.get('id')}",
            "plain_steps": plain_steps,
            "json_guide": [
                "这里展示的是数据点记录的只读快照。",
                "引用原文是判断该数据点能否追溯到来源的第一层依据。",
                "计算复核状态说明摘录或计算是否完成检查。",
            ],
        }
    if object_type == "investment_target":
        return {
            "headline": row.get("target_name") or f"投资标的 {row.get('id')}",
            "plain_steps": [
                f"标的：{row.get('target_name')}",
                f"类型：{display_label(row.get('target_type'))}",
                f"标的质量：{row.get('target_quality_label') or '未标明'}",
                f"证实后动作：{row.get('confirmed_scenario_action') or '未录入'}",
                f"证伪后动作：{row.get('falsified_scenario_action') or '未录入'}",
            ],
            "json_guide": [
                "投资观点和条件化建议共同说明何种条件下值得跟踪或调整判断。",
                "已关联行研公司时可进入公司页；外部观察项则打开对应研究入口。",
            ],
        }
    if object_type == "target_data_point":
        plain_steps = [
            f"指标：{row.get('metric_name')}",
            f"期间：{row.get('period') or row.get('as_of_date') or '未标明'}",
            f"数值：{_format_value({'value_num': row.get('value_num'), 'value_text': row.get('value_text'), 'unit': row.get('unit')})}",
            f"方向：{display_label(row.get('direction'))}",
            f"原文摘录：{row.get('source_excerpt_display') or row.get('source_excerpt') or '未录入'}",
        ]
        language = row.get("source_language")
        title_zh = row.get("source_title_zh") or chinese_translation(row.get("source_title"), language)
        excerpt_zh = row.get("source_excerpt_zh") or chinese_translation(row.get("source_excerpt"), language)
        stale = freshness_warning(row.get("period"), row.get("as_of_date"), row.get("source_title"), row.get("source_excerpt"))
        if title_zh:
            plain_steps.append(f"中文标题：{title_zh}")
        if excerpt_zh:
            plain_steps.append(f"原文摘录中文译意：{excerpt_zh}")
        if stale:
            plain_steps.append(stale)
        return {
            "headline": row.get("metric_name") or f"标的数据点 {row.get('id')}",
            "plain_steps": plain_steps,
            "json_guide": [
                "可信度、数值支撑和方向共同解释该数据点在标的研究中的证据权重。",
                "证据按钮指向原始来源或 A/B 行研库对象。",
            ],
        }
    if object_type in {"metric_slot", "event"}:
        return {
            "headline": row.get("slot_label") or row.get("event_title") or f"证据对象 {row.get('id')}",
            "plain_steps": [
                f"证据角色：{display_label(row.get('policy_evidence_role'))}",
                f"证据门槛结论：{display_label(row.get('policy_gate_verdict'))}",
                f"评分资格：{display_label(row.get('scoring_eligibility'))}",
            ],
            "json_guide": ["只有通过核心门槛的证据才能进入核心 14 因子；只用于机会线索的证据不能抬高核心分。"],
        }
    return {
        "headline": f"证据对象 {row.get('id')}",
        "plain_steps": ["这里展示对象的只读快照；页面入口可返回对应研究对象。"],
        "json_guide": ["内部定位信息保留在 API，不在用户页面直接展示。"],
    }


def _resolve_external_url(ref: str, conn: sqlite3.Connection | None = None) -> dict:
    owns_conn = conn is None
    if owns_conn:
        conn = connect(readonly=True)
    cols = INTERNAL_SAFE_COLUMNS["source"]
    col_sql = ", ".join(cols)
    try:
        row = conn.execute(
            f"SELECT {col_sql} FROM opportunity_source WHERE url=? OR evidence_ref_uri=? ORDER BY id LIMIT 1",
            (ref, ref),
        ).fetchone()
    finally:
        if owns_conn:
            conn.close()
    record = dict_row(row)
    if record:
        _annotate_record_for_display("source", record)
        return {
            "uri": ref,
            "scheme": "url",
            "object_type": "source",
            "table": "opportunity_source",
            "id": record["id"],
            "found": True,
            "record": record,
            "deep_link": _deep_link("source", record),
            "human_explanation": _human_explanation("source", record),
        }
    return {
        "uri": ref,
        "scheme": "url",
        "object_type": "external_url",
        "table": None,
        "id": None,
        "found": False,
        "record": {"url": ref},
        "deep_link": ref,
        "human_explanation": {
            "headline": "这是外部 URL 证据，但当前 C 轨 DB 未找到对应来源记录。",
            "plain_steps": [
                f"URL：{ref}",
                "需要把该 URL 入库为 opportunity_source 后，才能展示标题、发布时间和原文摘录。",
            ],
            "json_guide": ["当前只找到外部链接，尚未形成包含标题、日期和原文摘录的完整证据记录。"],
        },
    }


def resolve_opp_uri(ref: str, conn: sqlite3.Connection | None = None) -> dict:
    scheme, object_type, ident = validate_uri(ref)
    if scheme != "opp":
        raise ValidationError(f"not an opp URI: {ref}")
    table = URI_TABLES[object_type]
    cols = INTERNAL_SAFE_COLUMNS[object_type]
    col_sql = ", ".join(cols)
    owns_conn = conn is None
    if owns_conn:
        conn = connect(readonly=True)
    try:
        row = conn.execute(f"SELECT {col_sql} FROM {table} WHERE id=?", (ident,)).fetchone()
    finally:
        if owns_conn:
            conn.close()
    record = dict_row(row)
    _annotate_record_for_display(object_type, record)
    return {
        "uri": ref,
        "scheme": "opp",
        "object_type": object_type,
        "table": table,
        "id": ident,
        "found": bool(record),
        "record": record,
        "deep_link": _deep_link(object_type, record) if record else None,
        "human_explanation": _human_explanation(object_type, record) if record else None,
    }


def resolve(ref: str, conn: sqlite3.Connection | None = None) -> dict:
    parsed = urlparse(ref or "")
    if parsed.scheme in {"http", "https"}:
        return _resolve_external_url(ref, conn=conn)
    scheme, _object_type, _ident = validate_uri(ref)
    if scheme == "ab":
        return resolve_ab_uri(ref)
    return resolve_opp_uri(ref, conn=conn)


def resolve_many(refs: list[str], conn: sqlite3.Connection | None = None) -> list[dict]:
    return [resolve(ref, conn=conn) for ref in refs]
