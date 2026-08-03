from __future__ import annotations

import hashlib
import json
import sqlite3
from decimal import Decimal
from typing import Any

from .db import dict_row, dict_rows
from .display_annotations import chinese_translation, is_english_text, source_original_text
from .evidence_resolver import resolve as resolve_evidence
from .display_labels import display_label
from .factor_dictionary import factor_metadata
from .metric_slot_gaps import summarize_missing_metric_slots
from .constants import EARLY_SIGNAL_RULE_VERSION
from .value_display import format_data_point_value


def _normalize(obj: Any) -> Any:
    if isinstance(obj, float):
        return float(Decimal(str(obj)).quantize(Decimal("0.000001")))
    if isinstance(obj, dict):
        return {k: _normalize(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        return [_normalize(v) for v in obj]
    return obj


def canonical_json(obj: Any) -> str:
    return json.dumps(_normalize(obj), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def hash_json(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def loads_json(value: str | None, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _fmt(value, digits: int = 1, empty: str = "无") -> str:
    if value is None:
        return empty
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_pct(value, digits: int = 0) -> str:
    return f"{_fmt((value or 0) * 100, digits)}%"


def _display_label(value: str | None) -> str:
    return str(display_label(value or "unknown"))


def _format_record_value(record: dict | None) -> str:
    return format_data_point_value(record)


def _lookup_opp_source(conn: sqlite3.Connection, source_id) -> dict | None:
    if not source_id:
        return None
    row = conn.execute(
        """
        SELECT id, title, title_zh, publisher, publish_date, url, excerpt, excerpt_zh,
               language, source_tier, source_review_status
        FROM opportunity_source
        WHERE id=?
        """,
        (source_id,),
    ).fetchone()
    return dict_row(row)


def _resolve_intro_evidence(conn: sqlite3.Connection, ref: str | None) -> dict | None:
    if not ref:
        return None
    try:
        return resolve_evidence(ref, conn=conn)
    except Exception:
        return None


def _evidence_info_from_resolved(conn: sqlite3.Connection, resolved: dict | None) -> dict:
    record = (resolved or {}).get("record") or {}
    linked_source = (resolved or {}).get("linked_source") or {}
    object_type = (resolved or {}).get("canonical_object_type") or (resolved or {}).get("object_type")
    source = linked_source
    excerpt = ""
    excerpt_zh = ""
    metric = ""
    period = ""
    value = ""

    if object_type == "research.industry_data_point":
        excerpt = record.get("source_excerpt_display") or source_original_text(record.get("source_excerpt"))
        excerpt_zh = record.get("source_excerpt_zh") or chinese_translation(record.get("source_excerpt")) or ""
        metric = record.get("metric") or ""
        period = record.get("period") or record.get("as_of_date") or ""
        value = _format_record_value(record)
    elif object_type == "data_point":
        source = _lookup_opp_source(conn, record.get("source_id")) or {}
        excerpt = (
            record.get("source_excerpt_display")
            or source_original_text(record.get("source_excerpt") or source.get("excerpt"))
        )
        # 数据点译意必须和这一条数据点的原文绑定。来源对象可能承载多个事实，
        # 不能用来源级 excerpt_zh 回填，否则会把另一页、另一数值显示成当前译文。
        excerpt_zh = record.get("source_excerpt_zh") or ""
        metric = record.get("metric") or ""
        period = record.get("period") or record.get("as_of_date") or ""
        value = _format_record_value(record)
    elif object_type in {"research.source", "source"} or (resolved or {}).get("scheme") == "url":
        source = record
        excerpt = record.get("excerpt_display") or source_original_text(record.get("excerpt"))
        excerpt_zh = record.get("excerpt_zh") or chinese_translation(record.get("excerpt"), record.get("language")) or ""
    else:
        excerpt = ""

    metric_line = "；".join(bit for bit in [
        f"指标：{metric}" if metric else "",
        f"期间：{period}" if period else "",
        f"数值：{value}" if value else "",
    ] if bit)
    return {
        "excerpt": excerpt or "当前证据对象没有录入可直接展示的原文摘录，需要补充来源摘录后再提高可读性等级。",
        "excerpt_zh": excerpt_zh,
        "source_title": source.get("title") or record.get("title") or "未标明来源标题",
        "publisher": source.get("publisher") or record.get("publisher") or "未标明发布方",
        "publish_date": source.get("publish_date") or record.get("publish_date") or "未标明时间",
        "metric": metric,
        "period": period,
        "value": value,
        "metric_line": metric_line,
    }


def _build_information_point(conn: sqlite3.Connection, row: dict, slot: dict) -> tuple[dict, str | None]:
    meta = factor_metadata(row["factor_code"])
    ref = slot.get("evidence_ref_uri")
    resolved = _resolve_intro_evidence(conn, ref)
    evidence_info = _evidence_info_from_resolved(conn, resolved)
    slot_name = slot.get("slot_label") or slot.get("metric_name") or slot.get("slot_key") or meta["factor_label"]
    metric_bits = []
    if evidence_info.get("metric"):
        metric_bits.append(f"指标：{evidence_info['metric']}")
    if evidence_info.get("period"):
        metric_bits.append(f"期间：{evidence_info['period']}")
    if evidence_info.get("value"):
        metric_bits.append(f"数值：{evidence_info['value']}")
    metric_line = "；".join(metric_bits)
    interpretation = (
        f"研究包尚未为“{slot_name}”写入独立证据解读；本页只展示来源、原文和指标映射，"
        "不以自动生成的通用话术替代研究分析。正式发布前必须补写该事实如何改变本因子、相邻因子和标的判断。"
    )
    return {
        "slot_name": slot_name,
        "excerpt": evidence_info["excerpt"],
        "excerpt_zh": evidence_info.get("excerpt_zh"),
        "source_title": evidence_info["source_title"],
        "publisher": evidence_info["publisher"],
        "publish_date": evidence_info["publish_date"],
        "metric_line": metric_line or "该证据主要提供文本判断，未形成单一数值口径。",
        "interpretation": interpretation,
        "evidence_ref": ref,
    }, ref


def _is_placeholder_text(value: str | None) -> bool:
    text = str(value or "")
    placeholders = (
        "来自外部对象",
        "A/B 行研库或外部对象",
        "详情以证据抽屉",
        "未匹配来源",
        "尚未匹配到可展示",
        "没有录入可直接展示",
    )
    return any(marker in text for marker in placeholders)


def _prefer_resolved(item_value: str | None, resolved_value: str | None) -> str:
    if resolved_value and (_is_placeholder_text(item_value) or not item_value):
        return resolved_value
    return item_value or resolved_value or ""


def _translation_for_exact_excerpt(
    original: str | None,
    translation: str | None,
    resolved_original: str | None,
) -> str:
    """Only return a translation proven to describe the displayed excerpt."""

    displayed = " ".join(str(original or "").split())
    translated = " ".join(str(translation or "").split())
    resolved = " ".join(str(resolved_original or "").split())
    if not displayed or not translated or displayed == translated:
        return ""
    if not is_english_text(displayed):
        return ""
    if resolved and displayed != resolved:
        return ""
    return str(translation or "").strip()


def _manual_information_points(conn: sqlite3.Connection, trace: dict) -> list[dict]:
    points = []
    seen_refs = set()
    seen_info = set()
    for item in trace.get("information_points") or []:
        ref = item.get("evidence_ref") or item.get("evidence_ref_uri")
        if ref and ref in seen_refs:
            continue
        if ref:
            seen_refs.add(ref)
        resolved = _resolve_intro_evidence(conn, ref)
        evidence_info = _evidence_info_from_resolved(conn, resolved)
        display_excerpt = _prefer_resolved(item.get("excerpt"), evidence_info["excerpt"])
        display_excerpt_zh = _translation_for_exact_excerpt(
            display_excerpt,
            item.get("excerpt_zh") or evidence_info.get("excerpt_zh"),
            display_excerpt if item.get("excerpt_zh") else evidence_info.get("excerpt"),
        )
        display_title = _prefer_resolved(item.get("source_title"), evidence_info["source_title"])
        info_key = (display_title, evidence_info["publisher"], evidence_info["publish_date"], display_excerpt)
        if info_key in seen_info:
            continue
        seen_info.add(info_key)
        points.append({
            "slot_name": item.get("slot_name") or item.get("title") or "上下文证据",
            "excerpt": display_excerpt,
            "excerpt_zh": display_excerpt_zh,
            "source_title": display_title,
            "publisher": _prefer_resolved(item.get("publisher"), evidence_info["publisher"]),
            "publish_date": _prefer_resolved(item.get("publish_date"), evidence_info["publish_date"]),
            "metric_line": item.get("metric_line") or evidence_info.get("metric_line") or "该证据用于解释因子与研究主题的上下文关系。",
            "interpretation": item.get("interpretation") or "该信息卡缺少独立上下文解读，不能作为完整因子证据使用；应回到研究包补写原文背景、同实体相邻因子关系和标的影响后再发布。",
            "evidence_ref": ref,
        })
    return points


def _factor_human_explanation(row: dict, slots: list[dict]) -> dict:
    meta = factor_metadata(row["factor_code"])
    trace = row.get("factor_trace") or {}
    slot_count = len(slots)
    scoreable_value_statuses = {
        "available",
        "available_with_grade_unknown",
        "available_text_only",
        "calculated",
        "stale_but_usable",
    }
    usable_slots = [
        s for s in slots
        if s.get("metric_slot_status") in {"accepted", "used_in_factor"}
        and s.get("value_status") in scoreable_value_statuses
        and s.get("slot_score") is not None
        and s.get("scoring_eligibility", "core_eligible") == "core_eligible"
    ]
    excluded_slots = [s for s in slots if s.get("scoring_eligibility") == "early_signal_only"]
    readiness_status = row.get("factor_readiness_status")
    score_displayable = (
        row.get("score_status") == "complete"
        and readiness_status in {None, "ready", "limited"}
    )
    if score_displayable:
        headline = (
            f"{meta['factor_label']}当前调整后分数为 {_fmt(row.get('score_adjusted'))} 分，"
            f"原始分为 {_fmt(row.get('score_raw'))} 分。"
        )
        plain_steps = [
            f"先收集该因子的 {slot_count} 个指标槽，其中 {len(usable_slots)} 个核心合格槽进入计算。",
            f"对可用指标槽做加权平均，得到原始分 {_fmt(row.get('score_raw'))}。",
            f"覆盖度为 {_fmt_pct(row.get('coverage'))}，置信度为 {_fmt_pct(row.get('confidence'))}。",
            f"可靠性调整系数为 {_fmt_pct(row.get('reliability_multiplier'))}，得到调整后分数 {_fmt(row.get('score_adjusted'))}。",
        ]
    else:
        headline = f"{meta['factor_label']}目前证据覆盖不足，暂不形成正式评分。"
        plain_steps = [
            f"本因子共检查 {slot_count} 个指标槽，只有 {len(usable_slots)} 个核心合格槽具备可复算输入。",
            f"当前覆盖度为 {_fmt_pct(row.get('coverage'))}，置信度为 {_fmt_pct(row.get('confidence'))}，不足以支持方向性评级。",
            "证据不足时不展示分数，也不能把缺失数据解释为供需中性或投资判断。",
        ]
    if excluded_slots:
        plain_steps.append(f"有 {len(excluded_slots)} 个指标槽被标记为早期信号，只用于研究优先级，不进入核心分。")
    if row.get("missing_reason"):
        plain_steps.append(f"如果想提高本因子的证据覆盖，需要补充：{row['missing_reason']}")
    weighting = trace.get("evidence_weighting") or {}
    if weighting:
        required_groups = weighting.get("minimum_required_groups", weighting.get("minimum_required_refs"))
        available_groups = weighting.get("available_group_count", weighting.get("available_ref_count"))
        gate_verdict = weighting.get("gate_verdict")
        requirement_result = (
            "已满足该数量要求"
            if gate_verdict in {"pass", "pass_core", "pass_reference", "pass_early_signal"}
            else "尚未满足该数量要求"
        )
        plain_steps.append(
            f"正式判断至少需要 {required_groups} 个独立证据组，"
            f"当前可用 {available_groups} 个，{requirement_result}。"
        )
    json_guide = [
        "指标槽记录本因子使用的细分指标、分数和关联证据。",
        "覆盖度是可用指标权重占全部指标权重的比例。",
        "置信度是进入计算的指标槽平均置信水平。",
        "调整系数反映覆盖度、置信度和审计问题对分数的折减。",
        "证据索引可打开对应来源、原文和复核状态。",
        "证据加权综合来源可信度、数值支撑和利多利空方向。",
        "非核心输入被证据门禁排除，不参与核心评分。",
    ]
    return {
        "headline": headline,
        "formula": meta["factor_formula"],
        "description": trace.get("contextual_factor_description") or meta["factor_description"],
        "human_question": trace.get("contextual_human_question") or meta["factor_human_question"],
        "plain_steps": plain_steps,
        "json_guide": json_guide,
        "score_displayable": score_displayable,
    }


def _factor_intro_analysis(conn: sqlite3.Connection, row: dict, slots: list[dict]) -> dict:
    meta = factor_metadata(row["factor_code"])
    trace = row.get("factor_trace") or {}
    entity_name = row.get("display_name") or row.get("canonical_name") or f"实体 {row.get('entity_id')}"
    available = [s for s in slots if s.get("metric_slot_status") in {"accepted", "used_in_factor"}]
    core_eligible = [s for s in available if s.get("scoring_eligibility", "core_eligible") == "core_eligible"]
    evidence_refs = []
    manual_points = _manual_information_points(conn, trace)
    information_points = list(manual_points)
    for slot in slots:
        point, ref = _build_information_point(conn, row, slot)
        if ref:
            evidence_refs.append(ref)
        if not manual_points:
            information_points.append(point)
    for point in information_points:
        if point.get("evidence_ref"):
            evidence_refs.append(point["evidence_ref"])
    evidence_refs.extend(row.get("evidence_ref_uri_list") or [])
    evidence_refs.extend(trace.get("source_context_refs") or [])
    seen = set()
    evidence_refs = [ref for ref in evidence_refs if not (ref in seen or seen.add(ref))]
    score_rationale = trace.get("score_rationale") or (
        "研究包没有写入该因子的独立打分理由。现有数值仅保留用于历史复算，不应由页面自动补成投资结论；"
        "必须回到生产阶段说明具体证据、分数边界、反方和调整原因。"
    )
    related_theme_analysis = trace.get("factor_topic_analysis") or (
        "研究包没有写入该因子的独立主题分析。页面不会根据因子类别自动生成套话；"
        "该项应在生产阶段结合原文上下文、相邻因子、反方证据和标的影响后重写。"
    )
    theme_analysis_points = trace.get("theme_analysis_points") or [
        "缺少独立主题分析要点；当前因子只能作为历史复算记录，不能作为已完成研究结论。"
    ]
    return {
        "headline": f"{entity_name}的“{meta['factor_label']}”因子介绍与分析。",
        "factor_value_summary": trace.get("factor_value_summary"),
        "source_context_summary": trace.get("source_context_summary"),
        "information_points": information_points or [{
            "slot_name": meta["factor_label"],
            "excerpt": "当前没有可展示的原文摘录。",
            "excerpt_zh": None,
            "source_title": "未绑定来源",
            "publisher": "未标明发布方",
            "publish_date": "未标明时间",
            "metric_line": "无",
            "interpretation": "缺少原文时，不应把该因子当作高置信度结论。",
            "evidence_ref": None,
        }],
        "score_rationale": score_rationale,
        "related_theme_analysis": related_theme_analysis,
        "theme_analysis_points": theme_analysis_points,
        "evidence_refs": evidence_refs,
        "evidence_weighting": trace.get("evidence_weighting"),
    }


def _slot_human_explanation(slot: dict) -> dict:
    meta = factor_metadata(slot["factor_code"])
    score = _fmt(slot.get("slot_score"))
    confidence = _fmt((slot.get("slot_confidence") or 0) * 100, 0)
    score_displayable = (
        slot.get("metric_slot_status") in {"accepted", "used_in_factor"}
        and slot.get("value_status")
        in {
            "available",
            "available_with_grade_unknown",
            "available_text_only",
            "calculated",
            "stale_but_usable",
        }
        and slot.get("slot_score") is not None
    )
    headline = (
        f"该指标槽用于支撑“{meta['factor_label']}”，当前槽分为 {score} 分，置信度 {confidence}%。"
        if score_displayable
        else f"该指标槽用于支撑“{meta['factor_label']}”，目前没有足够证据形成槽分。"
    )
    return {
        "headline": headline,
        "formula": "指标槽分数来自已选择的数据点，并按研究包冻结的标准化与分档规则计算；因子层再按权重汇总可用槽分。",
        "plain_steps": [
            f"指标槽名称：{slot.get('slot_label') or slot.get('slot_key')}。",
            f"指标含义：{meta['factor_description']}",
            f"当前状态：{_display_label(slot.get('metric_slot_status'))}；取值状态：{_display_label(slot.get('value_status'))}。",
            f"证据资格：{_display_label(slot.get('scoring_eligibility', 'core_eligible'))}；门槛结论：{_display_label(slot.get('policy_gate_verdict', 'pass_core'))}。",
            f"关联证据：{'已绑定，可通过下方证据按钮查看' if slot.get('evidence_ref_uri') else '未绑定'}。",
        ],
        "json_guide": [
            "关联证据表说明该指标槽连接到哪些数据点或事实主张。",
            "取值列展示证据中的数值或文本结果。",
            "摘录列展示直接支撑该指标的原文。",
            "证据按钮用于打开完整来源和复核信息。",
        ],
        "score_displayable": score_displayable,
    }


def get_factor_trace(conn: sqlite3.Connection, factor_score_id: int) -> dict | None:
    row = conn.execute(
        """
        SELECT fs.*, e.display_name, e.canonical_name, e.entity_type
        FROM opportunity_factor_score fs
        LEFT JOIN opportunity_entity e ON e.id=fs.entity_id
        WHERE fs.id=?
        """,
        (factor_score_id,),
    ).fetchone()
    if not row:
        return None
    out = dict_row(row)
    out.update(factor_metadata(out["factor_code"]))
    out["factor_trace"] = loads_json(out.pop("factor_trace_json", None), {})
    if out["factor_trace"].get("contextual_human_question"):
        out["factor_human_question"] = out["factor_trace"]["contextual_human_question"]
    if out["factor_trace"].get("contextual_factor_description"):
        out["factor_description"] = out["factor_trace"]["contextual_factor_description"]
    out["evidence_ref_uri_list"] = loads_json(out.pop("evidence_ref_uri_list_json", None), [])
    out["slots"] = dict_rows(
        conn.execute(
            """
            SELECT ms.*
            FROM opportunity_metric_slot ms
            WHERE ms.run_id=? AND ms.entity_id=? AND ms.factor_code=?
            ORDER BY ms.slot_key
            """,
            (out["run_id"], out["entity_id"], out["factor_code"]),
        ).fetchall()
    )
    readiness = dict_row(
        conn.execute(
            """
            SELECT factor_readiness_status, missing_reason
            FROM opportunity_factor_readiness
            WHERE run_id=? AND entity_id=? AND factor_code=?
            ORDER BY id DESC LIMIT 1
            """,
            (out["run_id"], out["entity_id"], out["factor_code"]),
        ).fetchone()
    )
    if readiness:
        out["factor_readiness_status"] = readiness.get("factor_readiness_status")
        out["missing_reason"] = readiness.get("missing_reason")
    out["missing_reason"] = out.get("missing_reason") or summarize_missing_metric_slots(out["slots"])
    for slot in out["slots"]:
        slot.update(factor_metadata(slot["factor_code"]))
        slot["human_explanation"] = _slot_human_explanation(slot)
    out["human_explanation"] = _factor_human_explanation(out, out["slots"])
    out["is_score_displayable"] = bool(out["human_explanation"].get("score_displayable"))
    out["intro_analysis"] = _factor_intro_analysis(conn, out, out["slots"])
    return out


def get_metric_slot_trace(conn: sqlite3.Connection, slot_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM opportunity_metric_slot WHERE id=?", (slot_id,)).fetchone()
    if not row:
        return None
    out = dict_row(row)
    out.update(factor_metadata(out["factor_code"]))
    out["links"] = dict_rows(
        conn.execute(
            """
            SELECT l.*, dp.metric, dp.period, dp.as_of_date, dp.value_num, dp.value_text,
                   dp.unit, dp.source_excerpt, dp.source_excerpt_zh, dp.value_status
            FROM opportunity_slot_data_point_link l
            LEFT JOIN opportunity_data_point dp ON dp.id=l.data_point_id
            WHERE l.slot_id=?
            ORDER BY l.id
            """,
            (slot_id,),
        ).fetchall()
    )
    for link in out["links"]:
        link["value_display"] = format_data_point_value(link)
        link["source_excerpt_display"] = source_original_text(link.get("source_excerpt"))
        link["source_excerpt_zh"] = link.get("source_excerpt_zh") or chinese_translation(link.get("source_excerpt"))
    out["human_explanation"] = _slot_human_explanation(out)
    return out


def get_entity_score_trace(conn: sqlite3.Connection, entity_id: int, score_batch_id: int | None = None) -> dict | None:
    params: list[Any] = [entity_id]
    batch_clause = ""
    if score_batch_id is not None:
        batch_clause = " AND cs.score_batch_id=?"
        params.append(score_batch_id)
    row = conn.execute(
        f"""
        SELECT cs.*, e.entity_type, e.canonical_name, e.display_name
        FROM opportunity_composite_score cs
        JOIN opportunity_entity e ON e.id=cs.entity_id
        WHERE cs.entity_id=? {batch_clause}
        ORDER BY cs.is_current DESC, cs.id DESC
        LIMIT 1
        """,
        params,
    ).fetchone()
    if not row:
        return None
    out = dict_row(row)
    out["composite_trace"] = loads_json(out.pop("composite_trace_json", None), {})
    out["evidence_ref_uri_list"] = loads_json(out.pop("evidence_ref_uri_list_json", None), [])
    out["factor_scores"] = dict_rows(
        conn.execute(
            """
            SELECT fs.id, fs.factor_code, fs.score_status, fs.score_raw, fs.score_adjusted,
                   fs.coverage, fs.confidence, fs.reliability_multiplier,
                   fs.evidence_ref_uri_list_json,
                   fr.factor_readiness_status, fr.missing_reason
            FROM opportunity_factor_score fs
            LEFT JOIN opportunity_factor_readiness fr
              ON fr.id=(
                SELECT fr2.id FROM opportunity_factor_readiness fr2
                WHERE fr2.run_id=fs.run_id AND fr2.entity_id=fs.entity_id
                  AND fr2.factor_code=fs.factor_code
                ORDER BY fr2.id DESC LIMIT 1
              )
            WHERE fs.score_batch_id=? AND fs.entity_id=?
            ORDER BY fs.factor_code
            """,
            (out["score_batch_id"], entity_id),
        ).fetchall()
    )
    for factor in out["factor_scores"]:
        factor.update(factor_metadata(factor["factor_code"]))
        factor["evidence_ref_uri_list"] = loads_json(factor.pop("evidence_ref_uri_list_json", None), [])
    out["vetoes"] = dict_rows(
        conn.execute(
            """
            SELECT veto_code, veto_status, veto_reason, evidence_ref_uri
            FROM opportunity_veto_status
            WHERE score_batch_id=? AND entity_id=?
            ORDER BY veto_code
            """,
            (out["score_batch_id"], entity_id),
        ).fetchall()
    )
    early = dict_row(
        conn.execute(
            """
            SELECT *
            FROM opportunity_early_signal_aggregate
            WHERE run_id=? AND entity_id=? AND early_signal_rule_version=?
            ORDER BY id DESC LIMIT 1
            """,
            (out["run_id"], entity_id, EARLY_SIGNAL_RULE_VERSION),
        ).fetchone()
    )
    if early:
        early["evidence_ref_uri_list"] = loads_json(early.pop("evidence_ref_uri_list_json", None), [])
        early["aggregate_trace"] = loads_json(early.pop("aggregate_trace_json", None), {})
    out["early_signal"] = early
    return out
