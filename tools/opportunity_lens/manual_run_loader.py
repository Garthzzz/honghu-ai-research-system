from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from tools.research_core.config import resolve_track_config
from tools.research_core.content_cache import ContentAddressedCache
from tools.data_platform.shared_identity import connect_shared_identity_database

from .constants import (
    EARLY_SIGNAL_RULE_VERSION,
    EVIDENCE_POLICY_VERSION,
    INTAKE_CONTRACT_VERSION,
    RESEARCH_WORKFLOW_CONTRACT_VERSION,
    ROOT,
    RESEARCH_DB_PATH,
    RUN_PACK_SCHEMA_VERSION,
    SCORE_RULE_VERSION,
    SOURCE_LADDER_VERSION,
    VERSION_BUNDLE,
)
from .db import connect, object_uri
from .factor_dictionary import FACTOR_BY_CODE, factors_for_entity_type
from .metric_slot_gaps import summarize_missing_metric_slots
from .migrate import init_db
from .publication import publish_run
from .public_content_quality_audit import (
    PUBLIC_AUDIT_FIELD,
    PUBLIC_AUDIT_MANIFEST_TYPE,
    validate_pack_audit_attestation,
)
from .review_workflow import record_agent_review, record_quality_gate
from .run_pack_contract import LEGACY_PACK_SCHEMA, gate_for_issue_code, validate_run_pack
from .workflow_bridge import build_pack_workflow_state, compile_pack_brief
from .workflow import advance_run, create_run, mark_reviewable


def _j(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


MIN_FACTOR_EVIDENCE_REFS = 3
MIN_IMPORTANT_FACTOR_EVIDENCE_REFS = 5
IMPORTANT_FACTOR_SCORE_THRESHOLD = 70.0
MIN_RESEARCH_DATA_POINTS = 100
MIN_THEORY_RESEARCH_DATA_POINTS = 8
SOURCE_REF_TOKEN_RE = re.compile(r"source_ref:([A-Za-z0-9_.-]+)")
PUBLIC_URL_RE = re.compile(r"https?://")
PUBLIC_SOURCE_URI_RE = re.compile(r"opp://source/\d+")
PUBLIC_SOURCE_REF_RE = re.compile(r"source_ref:[A-Za-z0-9_.-]+")
CHAINED_EVIDENCE_TOKEN_RE = re.compile(r"\^(?:src|evidence):[^\s\]\)<>，。；、,;^]+\^(?:src|evidence):")


def _source_uri_is_inside_citation(body: str, start: int) -> bool:
    prefix = body[max(0, start - 12):start]
    return prefix.endswith("^src:") or prefix.endswith("^evidence:")


def _source_ref_is_inside_citation(body: str, start: int) -> bool:
    prefix = body[max(0, start - 12):start]
    return prefix.endswith("^src:") or prefix.endswith("^evidence:")


def _has_visible_source_uri(body: str) -> bool:
    for match in PUBLIC_SOURCE_URI_RE.finditer(body):
        if not _source_uri_is_inside_citation(body, match.start()):
            return True
    return False


def _has_visible_source_ref(body: str) -> bool:
    for match in PUBLIC_SOURCE_REF_RE.finditer(body):
        if not _source_ref_is_inside_citation(body, match.start()):
            return True
    return False


def _evidence_chain_segment(body: str) -> str:
    marker = "### 证据链与数据基础"
    if marker not in body:
        return ""
    segment = body.split(marker, 1)[1]
    next_heading = re.search(r"\n###\s+", segment)
    return segment[:next_heading.start()] if next_heading else segment


def _validate_public_section_body(body: str, label: str) -> None:
    if not body:
        return
    errors: list[str] = []
    if "原文地址:" in body or "原文地址：" in body:
        errors.append("正文暴露原文地址")
    if "本地底稿:" in body or "本地底稿：" in body:
        errors.append("正文暴露本地底稿路径")
    if "原始 JSON" in body or "raw JSON" in body.lower():
        errors.append("正文或用户抽屉文案暴露原始 JSON")
    if PUBLIC_URL_RE.search(body):
        errors.append("正文含裸 URL；原文链接必须进入 ^src 证据抽屉")
    if _has_visible_source_ref(body):
        errors.append("正文含 source_ref 机器占位符")
    if _has_visible_source_uri(body):
        errors.append("正文含裸 opp://source 机器 URI")
    if CHAINED_EVIDENCE_TOKEN_RE.search(body):
        errors.append("连续 ^src/^evidence 引用之间缺少空格")
    evidence_segment = _evidence_chain_segment(body)
    if evidence_segment and evidence_segment.count("\n- **") >= 3:
        errors.append("证据链与数据基础退化为来源清单，必须改写为证据关系和推理")
    if errors:
        raise ValueError(f"{label} 公共正文展示不合格: " + "；".join(errors))


def _validate_public_section_bodies(pack: dict, context: str) -> None:
    for section in pack.get("sections", []):
        _validate_public_section_body(
            str(section.get("body_markdown") or ""),
            f"{context} section[{section.get('section_key') or section.get('section_title')}]",
        )
    for section in pack.get("entity_sections", []):
        _validate_public_section_body(
            str(section.get("body_markdown") or ""),
            f"{context} entity_section[{section.get('entity_key')}]",
        )


def _entity_research_mode(entity: dict) -> str:
    raw = (
        entity.get("entity_research_mode")
        or entity.get("research_entity_type")
        or entity.get("entity_mode")
        or entity.get("mode")
        or "market_linked"
    )
    value = str(raw).strip().lower()
    if value in {"theory", "research", "research_only", "theoretical", "lit_review", "literature_review"}:
        return "theory_research"
    return "theory_research" if value == "theory_research" else "market_linked"


def _is_theory_entity(entity: dict) -> bool:
    return _entity_research_mode(entity) == "theory_research"


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _unique_refs(values: list[Any]) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        if isinstance(value, dict):
            value = value.get("evidence_ref") or value.get("evidence_ref_uri") or value.get("ref")
        if not value:
            continue
        ref = str(value).strip()
        if ref and ref not in seen:
            seen.add(ref)
            refs.append(ref)
    return refs


def _factor_score_value(factor: dict) -> float:
    try:
        return float(factor.get("score_adjusted", factor.get("score_raw", 0)) or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_important_factor(factor: dict, rank: int) -> bool:
    flag = str(factor.get("factor_importance") or "").strip().lower()
    if flag in {"important", "key", "核心", "关键"} or factor.get("is_important") is True:
        return True
    return rank <= 3 or _factor_score_value(factor) >= IMPORTANT_FACTOR_SCORE_THRESHOLD


def _collect_factor_evidence_refs(
    entity: dict,
    factor: dict,
    *,
    include_entity_refs: bool = False,
) -> list[str]:
    refs: list[Any] = []
    refs.extend(_as_list(factor.get("evidence_ref_uri_list")))
    refs.extend(_as_list(factor.get("source_context_refs")))
    refs.extend(_as_list(factor.get("evidence_ref_uri")))
    for item in _as_list(factor.get("information_points")):
        if isinstance(item, dict):
            refs.append(item.get("evidence_ref") or item.get("evidence_ref_uri"))
    for item in _as_list(factor.get("evidence_items")):
        if isinstance(item, dict):
            refs.append(item.get("evidence_ref") or item.get("evidence_ref_uri"))
    # V2 因子门禁只能计算该因子明确绑定的证据。实体级来源是页面背景，
    # 不能自动灌入每个因子并抬高覆盖数量。旧包可显式打开兼容开关。
    if include_entity_refs:
        refs.extend(_as_list(entity.get("evidence_ref_uri_list")))
    return _unique_refs(refs)


def _dedupe_evidence_refs_by_group(
    evidence_refs: list[str],
    evidence_group_by_ref: dict[str, str] | None = None,
) -> list[str]:
    evidence_group_by_ref = evidence_group_by_ref or {}
    selected: list[str] = []
    seen_groups: set[str] = set()
    for ref in evidence_refs:
        group = str(evidence_group_by_ref.get(ref) or ref)
        if group in seen_groups:
            continue
        seen_groups.add(group)
        selected.append(ref)
    return selected


def _factor_observation_units(factor: dict) -> int:
    value = factor.get("series_observation_count")
    if value is not None:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            pass
    count = 0
    for item in _as_list(factor.get("information_points")) + _as_list(factor.get("evidence_items")):
        if not isinstance(item, dict):
            continue
        obs_count = item.get("observation_count")
        if obs_count is not None:
            try:
                count += max(1, int(obs_count))
                continue
            except (TypeError, ValueError):
                pass
        count += 1
    return count


def _evidence_item_lookup(factor: dict) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for item in _as_list(factor.get("evidence_items")) + _as_list(factor.get("information_points")):
        if not isinstance(item, dict):
            continue
        ref = item.get("evidence_ref") or item.get("evidence_ref_uri")
        if ref:
            lookup[str(ref)] = item
    return lookup


def _credibility_weight(ref: str, item: dict) -> float:
    explicit = item.get("credibility_weight")
    if explicit is not None:
        try:
            return max(0.0, min(float(explicit), 1.0))
        except (TypeError, ValueError):
            pass
    tier = str(item.get("source_tier") or item.get("credibility_tier") or "").upper()
    if tier == "S":
        return 1.0
    if tier == "A":
        return 0.9
    if tier == "B":
        return 0.75
    if ref.startswith("ab://research.data_point/"):
        return 0.9
    if ref.startswith("opp://source/"):
        return 0.85
    if ref.startswith("ab://research.source/"):
        return 0.75
    if ref.startswith("http://") or ref.startswith("https://"):
        return 0.65
    return 0.6


def _numeric_weight(ref: str, item: dict) -> float:
    explicit = item.get("numeric_weight")
    if explicit is not None:
        try:
            return max(0.0, min(float(explicit), 1.0))
        except (TypeError, ValueError):
            pass
    if item.get("value_num") is not None or ref.startswith("ab://research.data_point/"):
        return 1.0
    text = " ".join(str(item.get(key) or "") for key in ("metric_line", "excerpt", "value_text", "source_excerpt"))
    return 0.9 if re.search(r"\d", text) else 0.7


def _direction_score(direction: str | None, fallback_score: float) -> tuple[str, float]:
    value = str(direction or "").strip().lower()
    if value in {"positive", "bullish", "利多", "正向"}:
        return "positive", 1.0
    if value in {"negative", "bearish", "利空", "负向"}:
        return "negative", -1.0
    if value in {"mixed", "多空混合", "conflict"}:
        return "mixed", 0.0
    if value in {"neutral", "中性"}:
        return "neutral", 0.0
    if fallback_score >= 60:
        return "positive", 1.0
    if fallback_score <= 40:
        return "negative", -1.0
    return "mixed", 0.0


def _build_evidence_weighting(
    factor: dict,
    evidence_refs: list[str],
    required_refs: int,
    observation_units: int = 0,
    evidence_group_by_ref: dict[str, str] | None = None,
) -> dict:
    score = _factor_score_value(factor)
    lookup = _evidence_item_lookup(factor)
    items = []
    total_weight = 0.0
    total_contribution = 0.0
    for index, ref in enumerate(evidence_refs, start=1):
        item = lookup.get(ref, {})
        credibility = _credibility_weight(ref, item)
        numeric = _numeric_weight(ref, item)
        direction, direction_value = _direction_score(item.get("direction") or factor.get("direction"), score)
        magnitude = item.get("magnitude_weight", 1.0)
        try:
            magnitude = max(0.0, min(float(magnitude), 1.5))
        except (TypeError, ValueError):
            magnitude = 1.0
        weight = round(credibility * numeric * magnitude, 4)
        contribution = round(weight * direction_value, 4)
        total_weight += weight
        total_contribution += contribution
        items.append({
            "index": index,
            "evidence_ref": ref,
            "independence_key": (evidence_group_by_ref or {}).get(ref, ref),
            "credibility_weight": round(credibility, 3),
            "numeric_weight": round(numeric, 3),
            "direction": direction,
            "direction_score": direction_value,
            "magnitude_weight": round(magnitude, 3),
            "weight": weight,
            "weighted_contribution": contribution,
            "reason": item.get("weight_reason") or "按来源可信度、是否包含数值口径和利多利空方向加权。",
        })
    net = total_contribution / total_weight if total_weight else 0.0
    return {
        "minimum_required_groups": required_refs,
        "available_group_count": len(evidence_refs),
        "minimum_required_refs": required_refs,
        "available_ref_count": len(evidence_refs),
        "series_observation_count": observation_units,
        "gate_verdict": "pass" if len(evidence_refs) >= required_refs else "blocked",
        "weighted_direction_score": round(net, 4),
        "weighted_evidence_score": round((net + 1.0) * 50.0, 2),
        "score_usage": "manual_score_with_weighted_evidence_audit",
        "items": items,
    }


def _source_ref_replacer(source_ids: dict[str, int]):
    def repl(match: re.Match) -> str:
        source_ref = match.group(1)
        source_id = source_ids.get(source_ref)
        if source_id is None:
            raise ValueError(f"研究包引用了未知 source_ref: {source_ref}")
        prefix = match.string[max(0, match.start() - 12):match.start()]
        if prefix.endswith("^src:") or prefix.endswith("^evidence:"):
            return str(source_id)
        return object_uri("source", source_id)

    return repl


def _normalize_pack_source_refs(value: Any, source_ids: dict[str, int]) -> Any:
    """把 source_ref:<ref> 证据占位符归一成可解析来源引用。

    研究包生成阶段还不知道 opportunity_source.id；允许在证据字段、报告正文
    和因子追踪文本中使用稳定的 source ref。正文 `^src:` / `^evidence:`
    上标归一成短数字 id，其他结构化证据字段归一成 `opp://source/<id>`。
    """
    if isinstance(value, dict):
        return {key: _normalize_pack_source_refs(item, source_ids) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_pack_source_refs(item, source_ids) for item in value]
    if isinstance(value, str) and "source_ref:" in value:
        return SOURCE_REF_TOKEN_RE.sub(_source_ref_replacer(source_ids), value)
    return value


def _read_pack(
    path: str | Path,
    *,
    publication_mode: str = "stage",
    raw_text: str | None = None,
) -> dict:
    pack_path = Path(path)
    pack = json.loads(raw_text if raw_text is not None else pack_path.read_text(encoding="utf-8"))
    pack["_pack_path"] = str(pack_path)
    _validate_pack(pack, publication_mode=publication_mode)
    return pack


def _legacy_validate_pack(pack: dict) -> None:
    required = ["slug", "research_question", "intake", "sources", "entities", "sections"]
    missing = [key for key in required if not pack.get(key)]
    if missing:
        raise ValueError("manual run pack 缺少字段: " + ", ".join(missing))
    _validate_public_section_bodies(pack, "raw")
    slugs = [source.get("ref") for source in pack.get("sources", [])]
    if len(slugs) != len(set(slugs)):
        raise ValueError("source ref 不能重复")
    entity_keys = [entity.get("key") for entity in pack.get("entities", [])]
    if len(entity_keys) != len(set(entity_keys)):
        raise ValueError("entity key 不能重复")
    entity_key_set = set(entity_keys)
    entity_by_key = {entity.get("key"): entity for entity in pack.get("entities", [])}
    data_point_count = len(pack.get("data_points", []))
    if data_point_count < MIN_RESEARCH_DATA_POINTS:
        raise ValueError(
            f"manual run pack 数据点不足：需要至少 {MIN_RESEARCH_DATA_POINTS} 个平行数据点，当前 {data_point_count} 个。"
            "同一来源同一对象同一口径的序列观测只算一个数据点；研报一句话、一组数字、分析数据和序列数据点在数据点层级平行。"
        )
    for entity in pack.get("entities", []):
        if _is_theory_entity(entity):
            profile = entity.get("research_profile") or entity.get("lit_review_profile") or {}
            required_profile_fields = (
                "research_question",
                "literature_review_markdown",
                "analysis_markdown",
                "answer_markdown",
                "conclusion_markdown",
            )
            missing_profile_fields = [
                field for field in required_profile_fields
                if not str(profile.get(field) or "").strip()
            ]
            if missing_profile_fields:
                raise ValueError(
                    f"entity[{entity.get('key')}] 是 theory_research，但 research_profile 缺少字段: "
                    + ", ".join(missing_profile_fields)
                )
            research_points = entity.get("research_data_points") or []
            if len(research_points) < MIN_THEORY_RESEARCH_DATA_POINTS:
                raise ValueError(
                    f"entity[{entity.get('key')}] 是 theory_research，需要至少 "
                    f"{MIN_THEORY_RESEARCH_DATA_POINTS} 条研究型数据点，当前 {len(research_points)} 条。"
                )
            for point in research_points:
                for field in ("source_ref", "data_point_title", "metric", "source_excerpt", "interpretation", "research_use"):
                    if not str(point.get(field) or "").strip():
                        raise ValueError(f"entity[{entity.get('key')}] research_data_points 缺少 {field}")
            continue
        factors = sorted(entity.get("factor_scores", []), key=_factor_score_value, reverse=True)
        for rank, factor in enumerate(factors, start=1):
            code = factor.get("factor_code")
            if code not in FACTOR_BY_CODE:
                raise ValueError(f"未知 factor_code: {code}")
            evidence_refs = _collect_factor_evidence_refs(entity, factor)
            required_refs = MIN_IMPORTANT_FACTOR_EVIDENCE_REFS if _is_important_factor(factor, rank) else MIN_FACTOR_EVIDENCE_REFS
            observation_units = _factor_observation_units(factor)
            if len(evidence_refs) < required_refs:
                raise ValueError(
                    f"entity[{entity.get('key')}] factor[{code}] 证据组不足："
                    f"需要至少 {required_refs} 个唯一证据组，当前 {len(evidence_refs)} 个。"
                    f"序列型数据的多个观测只能算同一个证据组，当前序列观测 {observation_units} 个。"
                    "必须回到检索、原文复核和入库循环补足证据，禁止进入下一 section 或发布。"
                )
    for section in pack.get("entity_sections", []):
        if section.get("entity_key") not in entity_key_set:
            raise ValueError(f"entity_sections 引用了未知 entity_key: {section.get('entity_key')}")
    for target in pack.get("entity_investment_targets", []):
        if target.get("entity_key") not in entity_key_set:
            raise ValueError(f"entity_investment_targets 引用了未知 entity_key: {target.get('entity_key')}")
        if _is_theory_entity(entity_by_key[target.get("entity_key")]):
            raise ValueError(
                f"entity_investment_targets[{target.get('target_name') or target.get('entity_key')}] "
                "指向 theory_research 实体。研究型实体不绑定标的、不写投资建议。"
            )
        required_target_fields = (
            "target_name",
            "exposure_rationale",
            "research_action",
            "investment_view",
            "risk_note",
            "target_priority",
            "target_quality_label",
            "relative_preference",
            "confirmed_scenario_action",
            "falsified_scenario_action",
            "target_profile_markdown",
            "target_deep_research_markdown",
            "entity_relation_markdown",
            "parent_research_relation_markdown",
            "conditional_investment_recommendation",
            "financial_data_status",
        )
        missing_target_fields = [
            field for field in required_target_fields
            if not str(target.get(field) or "").strip()
        ]
        if missing_target_fields:
            raise ValueError(
                f"entity_investment_targets[{target.get('target_name') or target.get('entity_key')}] "
                f"缺少发布必填字段: {', '.join(missing_target_fields)}"
            )
        if not target.get("target_data_points"):
            raise ValueError(
                f"entity_investment_targets[{target.get('target_name') or target.get('entity_key')}] "
                "缺少 target_data_points，标的研究必须有结构化入库数据。必须回到数据补录和复核循环，禁止进入下一 section 或发布。"
            )


def _validate_pack(pack: dict, *, publication_mode: str = "stage") -> dict:
    """Run the versioned contract; legacy packs retain the old compatibility checks."""
    report = validate_run_pack(pack, publication_mode=publication_mode)
    report.raise_for_errors()
    if report.pack_schema_version == LEGACY_PACK_SCHEMA:
        _legacy_validate_pack(pack)
    else:
        public_audit, public_errors = validate_pack_audit_attestation(pack, profile="auto")
        pack[PUBLIC_AUDIT_FIELD] = public_audit
        if public_errors:
            raise ValueError("V2 run pack 公开内容门禁失败: " + "；".join(public_errors))
    pack["_contract_validation_report"] = report.as_dict()
    return report.as_dict()


def validate_pack_file(
    path: str | Path,
    *,
    publication_mode: str = "validate",
    require_skill_files: bool = True,
) -> dict:
    pack_path = Path(path)
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    report = validate_run_pack(pack, publication_mode=publication_mode)
    rendered = report.as_dict()
    if report.pack_schema_version != LEGACY_PACK_SCHEMA:
        try:
            public_audit, public_errors = validate_pack_audit_attestation(pack, profile="auto")
            rendered["public_content_quality_audit"] = public_audit
            rendered.setdefault("metrics", {}).update({
                "public_content_audit_status": public_audit["status"],
                "public_content_audit_rules_sha256": public_audit["rules_sha256"],
                "public_content_audit_pack_sha256": public_audit["pack_sha256"],
                "public_content_audit_result_sha256": public_audit["result_sha256"],
            })
            for message in public_errors:
                rendered["valid"] = False
                rendered.setdefault("issues", []).append({
                    "code": (
                        "public_content_audit_stale"
                        if "失效" in message or "缺少字段" in message or "不是对象" in message
                        else "public_content_quality_audit"
                    ),
                    "severity": "error",
                    "path": PUBLIC_AUDIT_FIELD,
                    "message": message,
                })
        except (TypeError, ValueError) as exc:
            rendered["valid"] = False
            rendered.setdefault("issues", []).append({
                "code": "public_content_quality_audit",
                "severity": "error",
                "path": PUBLIC_AUDIT_FIELD,
                "message": str(exc),
            })
    if report.valid and report.pack_schema_version != LEGACY_PACK_SCHEMA:
        try:
            brief = compile_pack_brief(
                pack,
                require_skill_files=require_skill_files,
            )
            rendered["metrics"]["workflow_brief_requirement_count"] = len(brief.requirements)
            rendered["metrics"]["workflow_brief_hash"] = brief.as_dict()["brief_hash"]
        except (TypeError, ValueError) as exc:
            rendered["valid"] = False
            rendered["issues"].append({
                "code": "workflow_brief_contract",
                "severity": "error",
                "path": "intake",
                "message": str(exc),
            })
    return rendered


def _existing_slug_run_ids(conn, slug: str) -> list[int]:
    rows = conn.execute(
        """
        SELECT run_id FROM opportunity_run_manifest
        WHERE manifest_type='manual_research_pack' AND manifest_hash=?
        """,
        (f"manual_pack_slug:{slug}",),
    ).fetchall()
    return [int(row["run_id"]) for row in rows]


def _delete_existing_slug(conn, slug: str) -> list[int]:
    run_ids = _existing_slug_run_ids(conn, slug)
    for run_id in run_ids:
        conn.execute("DELETE FROM opportunity_run WHERE id=?", (run_id,))
    return run_ids


def _rewind_run_sequence_after_tail_delete(conn, deleted_run_ids: list[int]) -> None:
    if not deleted_run_ids:
        return
    remaining_max = conn.execute("SELECT COALESCE(MAX(id), 0) FROM opportunity_run").fetchone()[0]
    if max(deleted_run_ids) <= int(remaining_max or 0):
        return
    conn.execute(
        "UPDATE sqlite_sequence SET seq=? WHERE name='opportunity_run'",
        (int(remaining_max or 0),),
    )


def _tables_with_run_id(conn) -> list[str]:
    rows = conn.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type='table' AND name LIKE 'opportunity_%'
        ORDER BY name
        """
    ).fetchall()
    tables: list[str] = []
    for row in rows:
        table_name = row["name"]
        columns = [column["name"] for column in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]
        if "run_id" in columns:
            tables.append(table_name)
    return tables


def _restore_replaced_run_id(conn, inserted_run_id: int, deleted_run_ids: list[int]) -> int:
    if not deleted_run_ids:
        return inserted_run_id
    target_run_id = min(deleted_run_ids)
    if inserted_run_id == target_run_id:
        return inserted_run_id
    existing = conn.execute("SELECT 1 FROM opportunity_run WHERE id=?", (target_run_id,)).fetchone()
    if existing is not None:
        raise RuntimeError(f"目标 run_id={target_run_id} 已存在，不能恢复替换 run 的原编号")
    conn.execute("PRAGMA defer_foreign_keys=ON")
    for table_name in _tables_with_run_id(conn):
        conn.execute(f"UPDATE {table_name} SET run_id=? WHERE run_id=?", (target_run_id, inserted_run_id))
    conn.execute("UPDATE opportunity_run SET id=? WHERE id=?", (target_run_id, inserted_run_id))
    max_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM opportunity_run").fetchone()[0]
    conn.execute(
        "UPDATE sqlite_sequence SET seq=? WHERE name='opportunity_run'",
        (int(max_id or 0),),
    )
    return target_run_id


def _source_role(source: dict) -> tuple[str, str, str]:
    review_status = source.get("source_review_status")
    # A weak or unresolved source may remain visible as context, but it must
    # never inherit the loader's core-evidence default merely because the pack
    # omitted an explicit policy role.
    if review_status == "weak_source_only":
        if source.get("policy_evidence_role") == "early_signal_candidate":
            return "early_signal_candidate", "pass_early_signal", "early_signal_only"
        return "reference_only", "pass_reference", "reference_only"
    if review_status == "conflict":
        return "needs_review", "blocked", "blocked_by_conflict"
    if review_status == "reject":
        return "rejected", "rejected", "rejected"
    if review_status in {"pending", "duplicate"}:
        return "needs_review", "needs_review", "reference_only"
    role = source.get("policy_evidence_role", "core_evidence")
    if role == "core_evidence":
        return role, "pass_core", "core_eligible"
    if role == "early_signal_candidate":
        return role, "pass_early_signal", "early_signal_only"
    if role == "reference_only":
        return role, "pass_reference", "reference_only"
    return "needs_review", "needs_review", "reference_only"


def _source_channel(source: dict) -> str:
    value = str(source.get("source_channel") or "").strip().lower()
    if not value:
        value = "report" if source.get("local_path") else "web" if source.get("url") else "legacy_unspecified"
    if value not in {"report", "web", "legacy_unspecified"}:
        raise ValueError(f"非法 source_channel: {value}")
    return value


def _resolve_company_identity(target: dict[str, Any]) -> dict[str, Any]:
    """Resolve listed-company targets at the loader boundary without inventing identities."""
    resolved = dict(target)
    if str(resolved.get("target_type") or "company") not in {"company", "security"}:
        return resolved
    if not Path(RESEARCH_DB_PATH).is_file():
        return resolved
    conn = connect_shared_identity_database(RESEARCH_DB_PATH)
    try:
        rows: list[sqlite3.Row] = []
        if resolved.get("company_id") is not None:
            row = conn.execute("SELECT id,name,ticker FROM company WHERE id=?", (int(resolved["company_id"]),)).fetchone()
            if row is None:
                raise ValueError(f"Opportunity Lens target company_id 不存在：{resolved['company_id']}")
            rows = [row]
        elif str(resolved.get("ticker") or "").strip():
            rows = conn.execute(
                "SELECT id,name,ticker FROM company WHERE upper(ticker)=upper(?)",
                (str(resolved["ticker"]).strip(),),
            ).fetchall()
        else:
            name = str(resolved.get("target_name") or "").strip()
            rows = conn.execute("SELECT id,name,ticker FROM company WHERE name=?", (name,)).fetchall()
            alias_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='company_identity_alias'"
            ).fetchone()
            if not rows and alias_exists:
                rows = conn.execute(
                    """SELECT c.id,c.name,c.ticker FROM company_identity_alias a
                       JOIN company c ON c.id=a.canonical_company_id WHERE a.alias=?""",
                    (name,),
                ).fetchall()
        unique = {int(row["id"]): row for row in rows}
        if len(unique) > 1:
            raise ValueError(f"上市公司身份不唯一，必须补证券代码：{resolved.get('target_name')}")
        if len(unique) == 1:
            row = next(iter(unique.values()))
            resolved["company_id"] = int(row["id"])
            resolved["ticker"] = resolved.get("ticker") or row["ticker"]
            resolved["target_url"] = f"/company/{int(row['id'])}"
            resolved["link_status"] = "linked"
        elif resolved.get("ticker"):
            resolved["link_status"] = "needs_company_profile"
            resolved["financial_data_status"] = resolved.get("financial_data_status") or "证券代码尚未映射到公司主数据"
        return resolved
    finally:
        conn.close()


def _insert_source_clusters(conn, run_id: int, pack: dict) -> dict[str, int]:
    cluster_ids: dict[str, int] = {}
    for source in pack.get("sources", []):
        cluster_key = (
            source.get("independence_key")
            or source.get("cluster")
            or source.get("publisher")
            or source["ref"]
        )
        if cluster_key in cluster_ids:
            continue
        cur = conn.execute(
            """
            INSERT INTO opportunity_source_cluster(
              run_id, cluster_key, cluster_label, independence_rationale, confidence
            ) VALUES(?,?,?,?,?)
            """,
            (
                run_id,
                cluster_key,
                source.get("cluster_label") or cluster_key,
                source.get("independence_rationale")
                or ("legacy pack 按发布机构保守聚类；V2 pack 必须显式提供 independence_key。"),
                float(source.get("cluster_confidence", 0.75)),
            ),
        )
        cluster_ids[cluster_key] = int(cur.lastrowid)
    return cluster_ids


def _insert_sources(
    conn,
    run_id: int,
    pack: dict,
    cluster_ids: dict[str, int],
    search_task_by_source_ref: dict[str, int] | None = None,
) -> dict[str, int]:
    source_ids: dict[str, int] = {}
    search_task_by_source_ref = search_task_by_source_ref or {}
    for source in pack.get("sources", []):
        role, gate, eligibility = _source_role(source)
        cluster_key = (
            source.get("independence_key")
            or source.get("cluster")
            or source.get("publisher")
            or source["ref"]
        )
        cur = conn.execute(
            """
            INSERT INTO opportunity_source(
              run_id, source_cluster_id, source_channel, title, source_tier, source_review_status,
              title_zh, publisher, author, publish_date, event_date, fetch_date,
              url, local_path, local_locator, content_hash, excerpt,
              excerpt_zh, language, evidence_ref_uri, policy_evidence_role, policy_gate_verdict,
              scoring_eligibility
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                cluster_ids.get(cluster_key),
                _source_channel(source),
                source["title"],
                source.get("source_tier", "unknown"),
                source.get("source_review_status", "pass_with_note"),
                source.get("title_zh"),
                source.get("publisher"),
                source.get("author"),
                source.get("publish_date"),
                source.get("event_date"),
                source.get("fetch_date"),
                source.get("url"),
                source.get("local_path"),
                source.get("local_locator"),
                source.get("content_hash") or _hash_text(source.get("excerpt", "") + source["title"]),
                source.get("excerpt"),
                source.get("excerpt_zh"),
                source.get("language", "zh-CN"),
                "",
                role,
                gate,
                eligibility,
            ),
        )
        source_id = int(cur.lastrowid)
        ref_uri = object_uri("source", source_id)
        conn.execute("UPDATE opportunity_source SET evidence_ref_uri=? WHERE id=?", (ref_uri, source_id))
        source_ids[source["ref"]] = source_id
        search_task_id = search_task_by_source_ref.get(str(source["ref"]))
        conn.execute(
            """
            INSERT INTO opportunity_search_log(
              run_id, search_task_id, source_channel, search_log_decision, title, url, publisher, reason, evidence_ref_uri
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                search_task_id,
                _source_channel(source),
                source.get("search_log_decision", "included"),
                source["title"],
                source.get("url"),
                source.get("publisher"),
                source.get("screen_reason") or "纳入人工核验证据包。",
                ref_uri,
            ),
        )
        conn.execute(
            """
            INSERT INTO opportunity_source_discovery(
              run_id, search_task_id, source_cluster_id, title, url, publisher,
              screen_decision, screen_reason, policy_evidence_role,
              policy_gate_verdict, scoring_eligibility, source_channel
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                search_task_id,
                cluster_ids.get(cluster_key),
                source["title"],
                source.get("url"),
                source.get("publisher"),
                source.get("search_log_decision", "included"),
                source.get("screen_reason") or "纳入人工核验证据包。",
                role,
                gate,
                eligibility,
                _source_channel(source),
            ),
        )
    return source_ids


def _insert_search_plan(conn, run_id: int, pack: dict) -> dict[str, int]:
    searches = pack.get("search_plan", [])
    if not searches:
        return {}
    cur = conn.execute(
        """
        INSERT INTO opportunity_search_plan(
          run_id, plan_name, search_axes_json, source_groups_json, search_protocol_version
        ) VALUES(?,?,?,?,?)
        """,
        (
            run_id,
            pack.get("search_plan_name", "人工核验证据搜索计划"),
            _j([item.get("axis_key") for item in searches]),
            _j(sorted({item.get("source_group", "manual") for item in searches})),
            "C_SEARCH_PROTOCOL_V1_MANUAL_VERIFIED",
        ),
    )
    plan_id = int(cur.lastrowid)
    task_by_source_ref: dict[str, int] = {}
    for item in searches:
        source_refs = [str(ref) for ref in item.get("source_refs", []) if str(ref)]
        cur = conn.execute(
            """
            INSERT INTO opportunity_search_task(
              run_id, search_plan_id, axis_key, source_group, source_channel, query_text,
              search_task_status, completed_at, result_count, included_count, rejection_reason
            ) VALUES(?,?,?,?,?,?,'completed',datetime('now'),?,?,?)
            """,
            (
                run_id,
                plan_id,
                item.get("axis_key", "manual"),
                item.get("source_group", "manual"),
                item.get("source_channel", "legacy_unspecified"),
                item.get("query_text") or item.get("query"),
                int(item.get("result_count", len(source_refs))),
                int(item.get("included_count", len(source_refs))),
                item.get("rejection_reason"),
            ),
        )
        task_id = int(cur.lastrowid)
        for ref in source_refs:
            task_by_source_ref.setdefault(ref, task_id)
    return task_by_source_ref


def _upsert_entity(conn, entity: dict) -> int:
    row = conn.execute(
        "SELECT id FROM opportunity_entity WHERE entity_type=? AND canonical_name=?",
        (entity.get("entity_type", "product_material"), entity["canonical_name"]),
    ).fetchone()
    if row:
        entity_id = int(row["id"])
        conn.execute(
            """
            UPDATE opportunity_entity
            SET display_name=?, description=?, updated_at=datetime('now')
            WHERE id=?
            """,
            (entity.get("display_name"), entity.get("description"), entity_id),
        )
        return entity_id
    cur = conn.execute(
        """
        INSERT INTO opportunity_entity(
          entity_type, taxonomy_level, canonical_name, display_name, description, external_ref_type
        ) VALUES(?,?,?,?,?,?)
        """,
        (
            entity.get("entity_type", "product_material"),
            entity.get("taxonomy_level") or entity.get("entity_type", "product_material"),
            entity["canonical_name"],
            entity.get("display_name") or entity["canonical_name"],
            entity.get("description"),
            entity.get("external_ref_type"),
        ),
    )
    return int(cur.lastrowid)


def _insert_entities(conn, run_id: int, pack: dict) -> dict[str, int]:
    entity_ids: dict[str, int] = {}
    for entity in pack.get("entities", []):
        entity_id = _upsert_entity(conn, entity)
        entity_ids[entity["key"]] = entity_id
        research_mode = _entity_research_mode(entity)
        readiness_score = entity.get("readiness_score")
        if readiness_score is None:
            readiness_score = 1.0 if research_mode == "theory_research" else 0.6
        conn.execute(
            """
            INSERT INTO opportunity_entity_maturation(
              run_id, entity_id, maturation_status, readiness_score, readiness_reason, evidence_ref_uri
            ) VALUES(?,?,?,?,?,?)
            """,
            (
                run_id,
                entity_id,
                entity.get("maturation_status", "research_only" if research_mode == "theory_research" else "scoring_limited"),
                float(readiness_score),
                entity.get("readiness_reason"),
                entity.get("evidence_ref_uri"),
            ),
        )
        conn.execute(
            """
            INSERT INTO opportunity_candidate_entity(
              run_id, candidate_stage, name, entity_type_hint, entity_id,
              preliminary_research_priority_label, source_count, independent_source_count,
              reason, evidence_ref_uri
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                entity.get("candidate_stage", "research_only" if research_mode == "theory_research" else "merged_to_entity"),
                entity.get("display_name") or entity["canonical_name"],
                entity.get("entity_type", "product_material"),
                entity_id,
                entity.get("research_priority_label", "research_only_insufficient_data" if research_mode == "theory_research" else "medium_priority_for_followup"),
                int(entity.get("source_count", 0)),
                int(entity.get("independent_source_count", 0)),
                entity.get("candidate_reason"),
                entity.get("evidence_ref_uri"),
            ),
        )
    return entity_ids


def _insert_claims_and_data_points(
    conn,
    run_id: int,
    pack: dict,
    source_ids: dict[str, int],
    entity_ids: dict[str, int],
) -> dict[str, Any]:
    """Insert claim/data-point evidence and return stable lookup indexes.

    Run-pack factor slots are assembled before database ids exist.  The lookup
    indexes let the score loader bind each explicit metric slot back to the
    exact data points (or, when a source only produced a textual claim, the
    exact claims) that were inserted in this transaction.  Existing packs do
    not need to provide slot metadata and continue to use the legacy path.
    """

    evidence_objects: dict[str, Any] = {
        "data_points_by_key": {},
        "data_points_by_title": {},
        "data_points_by_source_ref": {},
        "claims_by_source_ref": {},
        "source_uri_by_ref": {
            ref: object_uri("source", source_id)
            for ref, source_id in source_ids.items()
        },
    }

    def append_index(index_name: str, key: Any, row_id: int) -> None:
        normalized = str(key or "").strip()
        if not normalized:
            return
        evidence_objects[index_name].setdefault(normalized, []).append(int(row_id))

    for claim in pack.get("claims", []):
        source_id = source_ids[claim["source_ref"]]
        entity_id = entity_ids.get(claim.get("entity_key"))
        role, gate, eligibility = _source_role(claim)
        cur = conn.execute(
            """
            INSERT INTO opportunity_claim_evidence(
              run_id, entity_id, source_id, claim_type, claim_text, source_excerpt, source_excerpt_zh,
              claim_evidence_status, claim_next_action, support_status, evidence_ref_uri,
              policy_evidence_role, policy_gate_verdict, scoring_eligibility
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                entity_id,
                source_id,
                claim.get("claim_type", "manual_claim"),
                claim["claim_text"],
                claim.get("source_excerpt"),
                claim.get("source_excerpt_zh"),
                claim.get("claim_evidence_status", "verified"),
                claim.get("claim_next_action", "use_as_background"),
                claim.get("support_status", "supported"),
                object_uri("source", source_id),
                role,
                gate,
                eligibility,
            ),
        )
        append_index("claims_by_source_ref", claim["source_ref"], int(cur.lastrowid))
    for point in pack.get("data_points", []):
        source_id = source_ids[point["source_ref"]]
        entity_id = entity_ids.get(point.get("entity_key"))
        role, gate, eligibility = _source_role(point)
        observations = point.get("observations") if isinstance(point.get("observations"), list) else []
        period = point.get("period")
        as_of_date = point.get("as_of_date")
        value_num = point.get("value_num")
        value_text = point.get("value_text")
        if observations:
            first_period = observations[0].get("period") or observations[0].get("as_of_date")
            last_period = observations[-1].get("period") or observations[-1].get("as_of_date")
            latest = observations[-1]
            value_num = None
            value_text = _j({
                "kind": "time_series_data_point",
                "metric": point["metric"],
                "unit": point.get("unit", "无"),
                "period_start": first_period,
                "period_end": last_period,
                "observation_count": len(observations),
                "latest": {
                    "period": last_period,
                    "value": latest.get("value_num", latest.get("value_text")),
                },
                "observations": observations,
            })
            period = period or f"{first_period}~{last_period}"
            as_of_date = as_of_date or last_period
        cur = conn.execute(
            """
            INSERT INTO opportunity_data_point(
              run_id, entity_id, source_id, metric, period, as_of_date,
              value_num, value_text, unit, source_excerpt, source_excerpt_zh, value_status,
              calculation_review_status, extraction_method, evidence_ref_uri,
              policy_evidence_role, policy_gate_verdict, scoring_eligibility
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                entity_id,
                source_id,
                point["metric"],
                period,
                as_of_date,
                value_num,
                value_text,
                point.get("unit", "无"),
                point["source_excerpt"],
                point.get("source_excerpt_zh"),
                point.get("value_status", "available"),
                point.get("calculation_review_status", "pass"),
                point.get("extraction_method", "structured_extraction"),
                object_uri("source", source_id),
                role,
                gate,
                eligibility,
            ),
        )
        data_point_id = int(cur.lastrowid)
        append_index("data_points_by_source_ref", point["source_ref"], data_point_id)
        append_index("data_points_by_key", point.get("data_point_key"), data_point_id)
        append_index("data_points_by_title", point.get("data_point_title"), data_point_id)
    return evidence_objects


def _insert_research_profiles(
    conn,
    run_id: int,
    pack: dict,
    source_ids: dict[str, int],
    entity_ids: dict[str, int],
) -> None:
    for entity in pack.get("entities", []):
        entity_id = entity_ids[entity["key"]]
        research_mode = _entity_research_mode(entity)
        profile = entity.get("research_profile") or entity.get("lit_review_profile")
        if profile:
            refs = profile.get("evidence_ref_uri_list") or entity.get("evidence_ref_uri_list", [])
            conn.execute(
                """
                INSERT INTO opportunity_entity_research_profile(
                  run_id, entity_id, entity_research_mode, research_depth_status,
                  research_question, research_scope, methodology_note,
                  literature_review_markdown, data_collection_markdown,
                  analysis_markdown, answer_markdown, conclusion_markdown,
                  limitations_markdown, evidence_ref_uri_list_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    entity_id,
                    research_mode,
                    profile.get("research_depth_status", "complete"),
                    profile.get("research_question") or entity.get("display_name") or entity["canonical_name"],
                    profile.get("research_scope"),
                    profile.get("methodology_note"),
                    profile["literature_review_markdown"],
                    profile.get("data_collection_markdown"),
                    profile["analysis_markdown"],
                    profile["answer_markdown"],
                    profile["conclusion_markdown"],
                    profile.get("limitations_markdown"),
                    _j(refs),
                ),
            )
        elif research_mode == "market_linked" and pack.get("pack_schema_version", LEGACY_PACK_SCHEMA) == LEGACY_PACK_SCHEMA:
            conn.execute(
                """
                INSERT INTO opportunity_entity_research_profile(
                  run_id, entity_id, entity_research_mode, research_depth_status,
                  research_question, research_scope, methodology_note,
                  literature_review_markdown, data_collection_markdown,
                  analysis_markdown, answer_markdown, conclusion_markdown,
                  limitations_markdown, evidence_ref_uri_list_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    entity_id,
                    research_mode,
                    "complete",
                    entity.get("display_name") or entity["canonical_name"],
                    "市场相关实体，按 Opportunity Lens 市场型路径处理。",
                    "本 profile 用于标记实体类型；正式分析仍以评分、证据链和标的页为准。",
                    "该实体为市场型实体，不走独立理论文献综述分支。",
                    None,
                    "该实体继续使用核心因子评分、证据组、早期信号和标的投资研究建议。",
                    "按市场型实体模式回答：是否存在可交易或可跟踪的供需失衡机会。",
                    "市场型实体需要绑定标的、评分和条件化投资建议。",
                    None,
                    _j(entity.get("evidence_ref_uri_list", [])),
                ),
            )
        for index, point in enumerate(entity.get("research_data_points") or [], start=1):
            source_ref = point["source_ref"]
            source_id = source_ids.get(source_ref)
            evidence_ref_uri = point.get("evidence_ref_uri") or (object_uri("source", source_id) if source_id else source_ref)
            conn.execute(
                """
                INSERT INTO opportunity_research_data_point(
                  run_id, entity_id, source_id, data_point_title, research_category,
                  metric, period, as_of_date, value_num, value_text, unit,
                  source_excerpt, source_excerpt_zh, source_context, interpretation, research_use,
                  limitations, evidence_ref_uri, sort_order
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    entity_id,
                    source_id,
                    point["data_point_title"],
                    point.get("research_category", "literature_evidence"),
                    point["metric"],
                    point.get("period"),
                    point.get("as_of_date") or pack.get("as_of_date"),
                    point.get("value_num"),
                    point.get("value_text"),
                    point.get("unit", "文本"),
                    point["source_excerpt"],
                    point.get("source_excerpt_zh"),
                    point.get("source_context"),
                    point["interpretation"],
                    point["research_use"],
                    point.get("limitations"),
                    evidence_ref_uri,
                    int(point.get("sort_order", index)),
                ),
            )


def _score_grade(score: float | None) -> str:
    if score is None:
        return "unrated"
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    return "D"


_SLOT_VALUE_STATUS_ALIASES = {
    "not_found": "not_found_after_search",
    "not_disclosed": "not_disclosed_with_source",
    "missing": "not_found_after_search",
}
_SLOT_USABLE_VALUE_STATUSES = {"available", "calculated", "stale_but_usable"}


def _slot_source_refs(slot: dict) -> list[str]:
    refs: list[str] = []
    for value in _as_list(slot.get("source_refs")) + _as_list(slot.get("evidence_ref_uri_list")):
        text = str(value or "").strip()
        if text and text not in refs:
            refs.append(text)
    return refs


def _slot_evidence_ids(slot: dict, evidence_objects: dict[str, Any]) -> tuple[list[int], list[int]]:
    """Resolve an explicit slot to transaction-local data point / claim ids."""

    data_point_ids: list[int] = []
    claim_ids: list[int] = []

    def extend_unique(target: list[int], values: list[int] | None) -> None:
        for value in values or []:
            if int(value) not in target:
                target.append(int(value))

    key_selectors = _as_list(slot.get("data_point_keys")) + _as_list(slot.get("data_point_key"))
    title_selectors = (
        []
        if key_selectors
        else _as_list(slot.get("data_point_titles")) + _as_list(slot.get("data_point_title"))
    )
    for key in key_selectors:
        resolved = evidence_objects["data_points_by_key"].get(str(key))
        if not resolved:
            raise ValueError(f"指标槽显式数据点键无法解析：{key}")
        extend_unique(data_point_ids, resolved)
    for title in title_selectors:
        resolved = evidence_objects["data_points_by_title"].get(str(title))
        if not resolved:
            raise ValueError(f"指标槽显式数据点标题无法解析：{title}")
        extend_unique(data_point_ids, resolved)

    has_explicit_data_point_selector = bool(key_selectors or title_selectors)
    source_uri_by_ref = evidence_objects.get("source_uri_by_ref", {})
    ref_by_source_uri = {uri: ref for ref, uri in source_uri_by_ref.items()}
    for value in _slot_source_refs(slot):
        source_ref = value
        if source_ref.startswith("source_ref:"):
            source_ref = source_ref.split(":", 1)[1]
        elif source_ref.startswith("opp://source/"):
            source_ref = ref_by_source_uri.get(source_ref, "")
        if not source_ref:
            continue
        if not has_explicit_data_point_selector:
            extend_unique(data_point_ids, evidence_objects["data_points_by_source_ref"].get(source_ref))
        extend_unique(claim_ids, evidence_objects["claims_by_source_ref"].get(source_ref))
    # A slot page should show the exact evidence set, not hundreds of unrelated
    # observations from a broad annual report.  Explicit selectors are never
    # truncated; source-ref fallback is capped and remains auditable via the
    # slot's source URI.
    if not has_explicit_data_point_selector:
        data_point_ids = data_point_ids[:12]
        claim_ids = claim_ids[:12]
    return data_point_ids, claim_ids


def _slot_source_uri(slot: dict, evidence_objects: dict[str, Any]) -> str | None:
    source_uri_by_ref = evidence_objects.get("source_uri_by_ref", {})
    for value in _slot_source_refs(slot):
        if value.startswith("opp://source/"):
            return value
        source_ref = value.split(":", 1)[1] if value.startswith("source_ref:") else value
        if source_ref in source_uri_by_ref:
            return source_uri_by_ref[source_ref]
    return None


def _slot_notes(slot: dict, fallback: str | None = None) -> str | None:
    parts: list[str] = []
    raw_value = slot.get("raw_value_num")
    if raw_value is None:
        raw_value = slot.get("raw_value_text")
    if raw_value not in (None, ""):
        parts.append(f"原始输入：{raw_value}{slot.get('raw_unit') or ''}")
    standardized_value = slot.get("standardized_value_num")
    if standardized_value is None:
        standardized_value = slot.get("standardized_value_text")
    if standardized_value not in (None, ""):
        parts.append(f"标准化结果：{standardized_value}{slot.get('standardized_unit') or ''}")
    for label, key in (
        ("标准化方法", "normalization_method"),
        ("分档", "bucket"),
        ("分档规则", "scoring_rule"),
        ("预处理", "preprocess_trace"),
        ("评分说明", "scoring_trace"),
    ):
        value = slot.get(key)
        if value not in (None, ""):
            parts.append(f"{label}：{value}")
    if parts:
        return "；".join(parts)
    return str(slot.get("notes") or fallback or "").strip() or None


def _insert_explicit_metric_slots(
    conn,
    *,
    run_id: int,
    entity_id: int,
    factor: dict,
    factor_code: str,
    pack: dict,
    evidence_objects: dict[str, Any],
) -> None:
    slots = factor.get("metric_slots") or []
    for index, raw_slot in enumerate(slots, start=1):
        slot = dict(raw_slot)
        value_status = _SLOT_VALUE_STATUS_ALIASES.get(
            str(slot.get("value_status") or "not_found_after_search"),
            str(slot.get("value_status") or "not_found_after_search"),
        )
        usable = value_status in _SLOT_USABLE_VALUE_STATUSES
        if value_status == "not_applicable":
            metric_slot_status = "not_applicable"
        elif usable:
            metric_slot_status = "accepted" if slot.get("slot_role") == "context" else "used_in_factor"
        elif value_status == "stale_only":
            metric_slot_status = "stale_only"
        elif value_status == "weak_source_only":
            metric_slot_status = "weak_source_only"
        elif value_status == "conflict_unresolved":
            metric_slot_status = "conflict_unresolved"
        else:
            metric_slot_status = "candidate"

        data_point_ids, claim_ids = _slot_evidence_ids(slot, evidence_objects)
        if usable and not data_point_ids:
            raise ValueError(
                f"可用指标槽 {factor_code}.{slot.get('slot_code') or slot.get('slot_key')} "
                "没有解析到明确数据点"
            )
        selected_data_point_id = data_point_ids[0] if data_point_ids else None
        source_uri = _slot_source_uri(slot, evidence_objects)
        slot_score = slot.get("slot_score") if usable else None
        cur = conn.execute(
            """
            INSERT INTO opportunity_metric_slot(
              run_id, entity_id, factor_code, slot_key, slot_label, metric_name,
              metric_slot_status, value_status, slot_weight, slot_score, slot_confidence,
              unit, period, as_of_date, selected_data_point_id, evidence_ref_uri, notes,
              policy_evidence_role, policy_gate_verdict, scoring_eligibility
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                entity_id,
                factor_code,
                str(slot.get("slot_code") or slot.get("slot_key") or f"slot_{index}"),
                slot.get("slot_label") or slot.get("metric_name") or FACTOR_BY_CODE[factor_code].label,
                slot.get("metric_name") or slot.get("slot_label") or FACTOR_BY_CODE[factor_code].label,
                slot.get("metric_slot_status") or metric_slot_status,
                value_status,
                float(slot.get("slot_weight", 1.0)),
                None if slot_score is None else float(slot_score),
                float(slot.get("slot_confidence", 0.0)),
                slot.get("standardized_unit") or slot.get("unit") or factor.get("unit", "分"),
                slot.get("period") or factor.get("period") or pack.get("as_of_date", "2026-07-03"),
                slot.get("as_of_date") or factor.get("as_of_date") or pack.get("as_of_date", "2026-07-03"),
                selected_data_point_id,
                source_uri,
                _slot_notes(slot, factor.get("notes")),
                slot.get("policy_evidence_role", "core_evidence"),
                slot.get("policy_gate_verdict", "pass_core"),
                slot.get("scoring_eligibility", "core_eligible"),
            ),
        )
        slot_id = int(cur.lastrowid)
        link_role = "contradiction" if slot.get("slot_role") == "contradiction" else "selected"
        for position, data_point_id in enumerate(data_point_ids):
            conn.execute(
                """
                INSERT INTO opportunity_slot_data_point_link(
                  slot_id, data_point_id, claim_id, link_role, evidence_ref_uri
                ) VALUES(?,?,?,?,?)
                """,
                (
                    slot_id,
                    data_point_id,
                    None,
                    link_role if position == 0 else "supporting",
                    object_uri("data_point", data_point_id),
                ),
            )
        if not data_point_ids:
            for position, claim_id in enumerate(claim_ids):
                conn.execute(
                    """
                    INSERT INTO opportunity_slot_data_point_link(
                      slot_id, data_point_id, claim_id, link_role, evidence_ref_uri
                    ) VALUES(?,?,?,?,?)
                    """,
                    (
                        slot_id,
                        None,
                        claim_id,
                        link_role if position == 0 else "supporting",
                        object_uri("claim", claim_id),
                    ),
                )


def _insert_scores(
    conn,
    run_id: int,
    pack: dict,
    entity_ids: dict[str, int],
    evidence_objects: dict[str, Any] | None = None,
    evidence_group_by_ref: dict[str, str] | None = None,
) -> dict[str, list[dict]]:
    evidence_objects = evidence_objects or {
        "data_points_by_key": {},
        "data_points_by_title": {},
        "data_points_by_source_ref": {},
        "claims_by_source_ref": {},
        "source_uri_by_ref": {},
    }
    cur = conn.execute(
        """
        INSERT INTO opportunity_score_batch(
          run_id, score_rule_version, score_batch_status, is_current,
          input_manifest_json, input_manifest_hash, rule_manifest_hash, completed_at
        ) VALUES(?,?,?,?,?,?,?,datetime('now'))
        """,
        (
            run_id,
            SCORE_RULE_VERSION,
            "completed",
            1,
            _j({"pack_slug": pack["slug"], "mode": "manual_verified"}),
            _hash_text(pack["slug"]),
            _hash_text(SCORE_RULE_VERSION),
        ),
    )
    batch_id = int(cur.lastrowid)
    inserted: dict[str, list[dict]] = {}
    for entity in pack.get("entities", []):
        if _is_theory_entity(entity):
            inserted[entity["key"]] = []
            continue
        entity_id = entity_ids[entity["key"]]
        entity_type = entity.get("entity_type", "product_material")
        factors = entity.get("factor_scores", [])
        factor_rank = {
            id(factor): rank
            for rank, factor in enumerate(sorted(factors, key=_factor_score_value, reverse=True), start=1)
        }
        factor_rows: list[dict] = []
        for factor in factors:
            code = factor["factor_code"]
            score = float(factor.get("score_adjusted", factor.get("score_raw", 0)))
            rank = factor_rank.get(id(factor), 999)
            is_v2_pack = pack.get("pack_schema_version") != LEGACY_PACK_SCHEMA
            evidence_refs = _collect_factor_evidence_refs(
                entity,
                factor,
                include_entity_refs=not is_v2_pack,
            )
            counted_evidence_refs = (
                _dedupe_evidence_refs_by_group(evidence_refs, evidence_group_by_ref)
                if is_v2_pack
                else evidence_refs
            )
            required_refs = MIN_IMPORTANT_FACTOR_EVIDENCE_REFS if _is_important_factor(factor, rank) else MIN_FACTOR_EVIDENCE_REFS
            observation_units = _factor_observation_units(factor)
            evidence_weighting = _build_evidence_weighting(
                factor,
                counted_evidence_refs,
                required_refs,
                observation_units,
                evidence_group_by_ref,
            )
            adjustment_trace = factor.get("adjustment_trace") or {}
            aggregation_trace = factor.get("aggregation_trace") or {}
            coverage_multiplier = float(
                factor.get("coverage_multiplier", adjustment_trace.get("coverage_multiplier", 1.0))
            )
            confidence_multiplier = float(
                factor.get("confidence_multiplier", adjustment_trace.get("confidence_multiplier", 1.0))
            )
            audit_multiplier = float(
                factor.get("audit_multiplier", adjustment_trace.get("audit_multiplier", 1.0))
            )
            reliability_multiplier = float(
                factor.get(
                    "reliability_multiplier",
                    adjustment_trace.get("factor_reliability_multiplier", 1.0),
                )
            )
            missing_reason = factor.get("missing_reason") or summarize_missing_metric_slots(
                factor.get("metric_slots") or []
            )
            trace = {
                "factor_code": code,
                "factor_label": FACTOR_BY_CODE[code].label,
                "trace": factor.get("trace"),
                "manual_assessment": factor.get("trace"),
                "human_question": FACTOR_BY_CODE[code].human_question,
                "evidence_refs": evidence_refs,
                "evidence_weighting": evidence_weighting,
                "core_score_note": factor.get("core_score_note", "仅使用核心合格证据或明确标注的有限证据。"),
                "missing_reason": missing_reason,
            }
            if factor.get("metric_slots"):
                trace["metric_slot_count"] = len(factor["metric_slots"])
                trace["aggregation_trace"] = aggregation_trace
                trace["adjustment_trace"] = adjustment_trace
            for field in (
                "contextual_human_question",
                "contextual_factor_description",
                "source_context_summary",
                "factor_value_summary",
                "factor_topic_analysis",
                "score_rationale",
                "theme_analysis_points",
                "information_points",
                "adjacent_factor_links",
                "target_implications",
                "source_context_refs",
                "score_input_kind",
            ):
                if factor.get(field):
                    trace[field] = factor[field]
            cur = conn.execute(
                """
                INSERT INTO opportunity_factor_score(
                  run_id, score_batch_id, entity_id, factor_code, score_status,
                  score_raw, score_adjusted, coverage, confidence, coverage_multiplier,
                  confidence_multiplier, audit_multiplier, reliability_multiplier,
                  factor_trace_json, evidence_ref_uri_list_json, is_current
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
                """,
                (
                    run_id,
                    batch_id,
                    entity_id,
                    code,
                    factor.get("score_status", "complete"),
                    float(factor.get("score_raw", score)),
                    score,
                    float(factor.get("coverage", entity.get("coverage", 0.65))),
                    float(factor.get("confidence", entity.get("confidence", 0.65))),
                    coverage_multiplier,
                    confidence_multiplier,
                    audit_multiplier,
                    reliability_multiplier,
                    _j(trace),
                    _j(evidence_refs),
                ),
            )
            factor_score_id = int(cur.lastrowid)
            factor_rows.append(
                {
                    "id": factor_score_id,
                    "factor_code": code,
                    "score_adjusted": score,
                    "score_status": factor.get("score_status", "complete"),
                    "factor_readiness_status": factor.get(
                        "factor_readiness_status", "limited"
                    ),
                    "missing_reason": missing_reason,
                }
            )
            conn.execute(
                """
                INSERT INTO opportunity_factor_readiness(
                  run_id, entity_id, factor_code, factor_readiness_status,
                  coverage, confidence, missing_reason, evidence_ref_uri_list_json
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    entity_id,
                    code,
                    factor.get("factor_readiness_status", "limited"),
                    float(factor.get("coverage", entity.get("coverage", 0.65))),
                    float(factor.get("confidence", entity.get("confidence", 0.65))),
                    missing_reason,
                    _j(evidence_refs),
                ),
            )
            if factor.get("metric_slots"):
                _insert_explicit_metric_slots(
                    conn,
                    run_id=run_id,
                    entity_id=entity_id,
                    factor=factor,
                    factor_code=code,
                    pack=pack,
                    evidence_objects=evidence_objects,
                )
            else:
                # Backward-compatible fallback for historical packs.  New V2
                # packs should provide explicit replayable metric_slots.
                conn.execute(
                    """
                    INSERT INTO opportunity_metric_slot(
                      run_id, entity_id, factor_code, slot_key, slot_label, metric_name,
                      metric_slot_status, value_status, slot_weight, slot_score, slot_confidence,
                      unit, period, as_of_date, evidence_ref_uri, notes,
                      policy_evidence_role, policy_gate_verdict, scoring_eligibility
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        run_id,
                        entity_id,
                        code,
                        factor.get("slot_key", code.replace(".", "_")),
                        FACTOR_BY_CODE[code].label,
                        factor.get("metric_name", FACTOR_BY_CODE[code].label),
                        factor.get("metric_slot_status", "used_in_factor"),
                        factor.get("value_status", "available_text_only"),
                        float(factor.get("slot_weight", 1.0)),
                        score,
                        float(factor.get("confidence", entity.get("confidence", 0.65))),
                        factor.get("unit", "分"),
                        factor.get("period", pack.get("as_of_date", "2026-07-03")),
                        factor.get("as_of_date", pack.get("as_of_date", "2026-07-03")),
                        evidence_refs[0] if evidence_refs else None,
                        factor.get("notes"),
                        "core_evidence",
                        "pass_core",
                        "core_eligible",
                    ),
                )
        inserted[entity["key"]] = factor_rows
        score_point = float(entity.get("score_point", 0))
        conn.execute(
            """
            INSERT INTO opportunity_composite_score(
              run_id, score_batch_id, entity_id, score_status, score_grade,
              rating_status, score_quality_label, score_point, score_band_low,
              score_band_high, band_method, band_reason, coverage, confidence,
              audit_multiplier, composite_trace_json, evidence_ref_uri_list_json,
              research_bias_label, is_current
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
            """,
            (
                run_id,
                batch_id,
                entity_id,
                entity.get("score_status", "complete"),
                entity.get("score_grade", _score_grade(score_point)),
                entity.get("rating_status", "valid"),
                entity.get("score_quality_label", "medium_confidence"),
                score_point,
                float(entity.get("score_band_low", max(0, score_point - 6))),
                float(entity.get("score_band_high", min(100, score_point + 6))),
                entity.get("band_method", "manual_verified_opportunity_lens"),
                entity.get(
                    "band_reason",
                    (
                        "人工核验证据包按适用于该研究对象的"
                        f" {len(factor_rows)} 项因子形成综合判断。"
                        if pack.get("pack_schema_version") != LEGACY_PACK_SCHEMA
                        else "人工核验证据包按 14 因子框架评分。"
                    ),
                ),
                float(entity.get("coverage", 0.65)),
                float(entity.get("confidence", 0.65)),
                float(entity.get("audit_multiplier", 1.0)),
                _j(entity.get("composite_trace", {})),
                _j(entity.get("evidence_ref_uri_list", [])),
                entity.get("research_bias_label", "positive_research"),
            ),
        )
        applicability = entity.get("factor_applicability") or {}
        not_applicable = applicability.get("not_applicable") or {}
        if not isinstance(not_applicable, dict):
            not_applicable = {}
        for factor in factors_for_entity_type(entity_type):
            if factor.code in {row["factor_code"] for row in factor_rows}:
                continue
            excluded_reason = str(not_applicable.get(factor.code) or "").strip()
            readiness_status = "not_applicable" if excluded_reason else "missing"
            missing_reason = excluded_reason or "本轮人工证据包未覆盖该因子。"
            conn.execute(
                """
                INSERT INTO opportunity_factor_readiness(
                  run_id, entity_id, factor_code, factor_readiness_status,
                  coverage, confidence, missing_reason, evidence_ref_uri_list_json
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    entity_id,
                    factor.code,
                    readiness_status,
                    0,
                    0,
                    missing_reason,
                    "[]",
                ),
            )
    return inserted


def _insert_sections_visuals_and_followups(
    conn,
    run_id: int,
    pack: dict,
    entity_ids: dict[str, int],
    factor_rows: dict[str, list[dict]],
) -> None:
    section_ids: dict[str, int] = {}
    for index, section in enumerate(pack.get("sections", []), start=1):
        refs = section.get("evidence_ref_uri_list", [])
        cur = conn.execute(
            """
            INSERT INTO opportunity_report_section(
              run_id, section_key, section_title, body_markdown, support_status,
              red_flag_level, flag_reason_json, review_status, evidence_ref_uri_list_json,
              sort_order
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                section.get("section_key", f"section_{index}"),
                section["section_title"],
                section["body_markdown"],
                section.get("support_status", "supported"),
                section.get("red_flag_level", "none"),
                _j(section.get("flag_reason", [])),
                section.get("review_status", "approved"),
                _j(refs),
                int(section.get("sort_order", index * 10)),
            ),
        )
        section_id = int(cur.lastrowid)
        section_ids[section.get("section_key", f"section_{index}")] = section_id
        for ref in refs:
            conn.execute(
                """
                INSERT OR IGNORE INTO opportunity_section_evidence_link(section_id, evidence_ref_uri, link_role)
                VALUES(?,?,?)
                """,
                (section_id, ref, "supports"),
            )
    for index, section in enumerate(pack.get("entity_sections", []), start=1):
        refs = section.get("evidence_ref_uri_list", [])
        cur = conn.execute(
            """
            INSERT INTO opportunity_report_section(
              run_id, entity_id, section_key, section_title, body_markdown,
              support_status, red_flag_level, flag_reason_json, review_status,
              evidence_ref_uri_list_json, sort_order
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                entity_ids[section["entity_key"]],
                section.get("section_key", "entity_research_profile"),
                section.get("section_title", "研究实体介绍与投资标的"),
                section["body_markdown"],
                section.get("support_status", "supported"),
                section.get("red_flag_level", "none"),
                _j(section.get("flag_reason", [])),
                section.get("review_status", "approved"),
                _j(refs),
                int(section.get("sort_order", 1000 + index * 10)),
            ),
        )
        section_id = int(cur.lastrowid)
        section_ids[f"entity:{section['entity_key']}:{section.get('section_key', 'entity_research_profile')}"] = section_id
        for ref in refs:
            conn.execute(
                """
                INSERT OR IGNORE INTO opportunity_section_evidence_link(section_id, evidence_ref_uri, link_role)
                VALUES(?,?,?)
                """,
                (section_id, ref, "supports"),
            )
    for index, raw_target in enumerate(pack.get("entity_investment_targets", []), start=1):
        target = _resolve_company_identity(raw_target)
        cur = conn.execute(
            """
            INSERT INTO opportunity_entity_investment_target(
              run_id, entity_id, target_name, ticker, market, target_type,
              company_id, target_url, exposure_rationale, evidence_ref_uri,
              research_action, investment_view, risk_note, target_priority,
              target_quality_label, relative_preference, confirmed_scenario_action,
              falsified_scenario_action, target_profile_markdown,
              target_deep_research_markdown, entity_relation_markdown,
              parent_research_relation_markdown, conditional_investment_recommendation,
              financial_data_status, link_status, support_status, sort_order
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                entity_ids[target["entity_key"]],
                target["target_name"],
                target.get("ticker"),
                target.get("market"),
                target.get("target_type", "company"),
                target.get("company_id"),
                target.get("target_url"),
                target["exposure_rationale"],
                target.get("evidence_ref_uri"),
                target["research_action"],
                target["investment_view"],
                target["risk_note"],
                target.get("target_priority"),
                target.get("target_quality_label"),
                target.get("relative_preference"),
                target.get("confirmed_scenario_action"),
                target.get("falsified_scenario_action"),
                target.get("target_profile_markdown"),
                target.get("target_deep_research_markdown"),
                target.get("entity_relation_markdown"),
                target.get("parent_research_relation_markdown"),
                target.get("conditional_investment_recommendation"),
                target.get("financial_data_status"),
                target.get("link_status", "linked"),
                target.get("support_status", "partially_supported"),
                int(target.get("sort_order", index)),
            ),
        )
        target_id = int(cur.lastrowid)
        for dp_index, point in enumerate(target.get("target_data_points", []), start=1):
            direction = point.get("direction", "neutral")
            try:
                direction_score = float(point.get("direction_score", {"positive": 1, "negative": -1, "mixed": 0, "neutral": 0}.get(direction, 0)))
            except (TypeError, ValueError):
                direction_score = 0.0
            try:
                credibility_weight = float(point.get("credibility_weight", 0.7))
            except (TypeError, ValueError):
                credibility_weight = 0.7
            try:
                numeric_weight = float(point.get("numeric_weight", 0.7))
            except (TypeError, ValueError):
                numeric_weight = 0.7
            weighted_contribution = point.get("weighted_contribution")
            if weighted_contribution is None:
                weighted_contribution = credibility_weight * numeric_weight * direction_score
            conn.execute(
                """
                INSERT INTO opportunity_target_data_point(
                  run_id, entity_id, target_id, metric_name, metric_category,
                  period, as_of_date, value_num, value_text, unit,
                  source_title, source_title_zh, source_publisher, source_url, source_excerpt,
                  source_excerpt_zh, source_language,
                  evidence_ref_uri, data_quality_label, direction, credibility_weight,
                  numeric_weight, direction_score, weighted_contribution, sort_order
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    run_id,
                    entity_ids[target["entity_key"]],
                    target_id,
                    point["metric_name"],
                    point.get("metric_category", "target_research"),
                    point.get("period"),
                    point.get("as_of_date"),
                    point.get("value_num"),
                    point.get("value_text"),
                    point.get("unit"),
                    point.get("source_title"),
                    point.get("source_title_zh"),
                    point.get("source_publisher"),
                    point.get("source_url"),
                    point.get("source_excerpt"),
                    point.get("source_excerpt_zh"),
                    point.get("source_language"),
                    point.get("evidence_ref_uri") or target.get("evidence_ref_uri"),
                    point.get("data_quality_label", "人工核验"),
                    direction,
                    credibility_weight,
                    numeric_weight,
                    direction_score,
                    float(weighted_contribution),
                    int(point.get("sort_order", dp_index)),
                ),
            )
    for entity in pack.get("entities", []):
        rows = factor_rows.get(entity["key"], [])
        if not rows:
            continue
        data = {
            "entity_key": entity["key"],
            "entity_name": entity.get("display_name") or entity["canonical_name"],
            "factors": sorted(rows, key=lambda row: row["score_adjusted"], reverse=True),
        }
        cur = conn.execute(
            """
            INSERT INTO opportunity_visual_block(
              run_id, entity_id, block_key, block_type, title, subtitle,
              data_json, print_fallback_json, evidence_ref_uri_list_json,
              support_status, red_flag_level, sort_order
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                entity_ids[entity["key"]],
                f"heatmap_{entity['key']}",
                "heatmap",
                f"{entity.get('display_name') or entity['canonical_name']} 因子评分热力图",
                (
                    f"按适用于该研究对象的 {len(rows)} 项因子、计算方法和证据追踪展示，"
                    "只有证据充分的因子才显示分数。"
                ),
                _j(data),
                _j(data),
                _j(entity.get("evidence_ref_uri_list", [])),
                "supported",
                "none",
                int(entity.get("visual_sort_order", 100)),
            ),
        )
        visual_id = int(cur.lastrowid)
        for row in rows:
            conn.execute(
                """
                INSERT OR IGNORE INTO opportunity_visual_evidence_link(
                  visual_block_id, evidence_ref_uri, factor_score_id
                ) VALUES(?,?,?)
                """,
                (visual_id, entity.get("evidence_ref_uri_list", [None])[0], row["id"]),
            )
    for index, visual in enumerate(pack.get("visuals", []), start=1):
        refs = visual.get("evidence_ref_uri_list", [])
        data = visual.get("data") or {}
        fallback = visual.get("print_fallback") or visual.get("display_data") or data
        cur = conn.execute(
            """
            INSERT INTO opportunity_visual_block(
              run_id, entity_id, block_key, block_type, title, subtitle,
              data_json, print_fallback_json, evidence_ref_uri_list_json,
              support_status, red_flag_level, empty_state_reason, sort_order
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                entity_ids.get(visual.get("entity_key")),
                visual.get("block_key", f"pack_visual_{index}"),
                visual.get("block_type", "table"),
                visual.get("title", f"可视化模块 {index}"),
                visual.get("subtitle"),
                _j(data),
                _j(fallback),
                _j(refs),
                visual.get("support_status", "supported"),
                visual.get("red_flag_level", "none"),
                visual.get("empty_state_reason"),
                int(visual.get("sort_order", 500 + index * 10)),
            ),
        )
        visual_id = int(cur.lastrowid)
        for ref in refs:
            conn.execute(
                """
                INSERT OR IGNORE INTO opportunity_visual_evidence_link(
                  visual_block_id, evidence_ref_uri
                ) VALUES(?,?)
                """,
                (visual_id, ref),
            )
    for index, item in enumerate(pack.get("nav", []), start=1):
        conn.execute(
            """
            INSERT INTO opportunity_navigation_index(run_id, nav_key, label, href, sort_order)
            VALUES(?,?,?,?,?)
            """,
            (
                run_id,
                item.get("nav_key", f"nav_{index}"),
                item.get("label", f"段落 {index}"),
                item.get("href", f"#section-{index}"),
                int(item.get("sort_order", index * 10)),
            ),
        )
    for item in pack.get("supplement_requests", []):
        conn.execute(
            """
            INSERT INTO opportunity_supplement_request(
              run_id, entity_id, request_title, request_detail, priority,
              blocking_status, review_status, evidence_ref_uri
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                entity_ids.get(item.get("entity_key")),
                item["request_title"],
                item.get("request_detail"),
                item.get("priority", "p2"),
                item.get("blocking_status", "limits_scoring"),
                item.get("review_status", "pending"),
                item.get("evidence_ref_uri"),
            ),
        )
    for item in pack.get("audit_issues", []):
        conn.execute(
            """
            INSERT INTO opportunity_audit_issue(
              run_id, entity_id, affected_uri, audit_issue_type, audit_severity,
              audit_issue_status, issue_title, issue_detail, evidence_ref_uri,
              evidence_ref_uri_list_json, reviewer
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                entity_ids.get(item.get("entity_key")),
                item.get("affected_uri", f"opp://run/{run_id}"),
                item.get("audit_issue_type", "low_coverage"),
                item.get("audit_severity", "p2"),
                item.get("audit_issue_status", "open"),
                item["issue_title"],
                item.get("issue_detail"),
                item.get("evidence_ref_uri"),
                _j(item.get("evidence_ref_uri_list", [])),
                item.get("reviewer", "manual_run_loader"),
            ),
        )


def _insert_early_signals(conn, run_id: int, pack: dict, entity_ids: dict[str, int]) -> None:
    entity_by_key = {entity.get("key"): entity for entity in pack.get("entities", [])}
    for signal in pack.get("early_signals", []):
        if _is_theory_entity(entity_by_key.get(signal.get("entity_key"), {})):
            continue
        entity_id = entity_ids[signal["entity_key"]]
        conn.execute(
            """
            INSERT INTO opportunity_early_signal_aggregate(
              run_id, entity_id, early_signal_rule_version, evidence_policy,
              early_signal_score, early_signal_strength_label, research_priority_score,
              research_priority_label, source_count, independent_source_count,
              verification_debt_count, core_score_snapshot, core_score_changed_by_overlay,
              evidence_ref_uri_list_json, excluded_from_core_reason, aggregate_trace_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                entity_id,
                EARLY_SIGNAL_RULE_VERSION,
                pack["intake"].get("evidence_policy", "freshness_first"),
                float(signal.get("early_signal_score", 0)),
                signal.get("early_signal_strength_label", "weak"),
                float(signal.get("research_priority_score", 0)),
                signal.get("research_priority_label", "medium_priority_for_followup"),
                int(signal.get("source_count", 0)),
                int(signal.get("independent_source_count", 0)),
                int(signal.get("verification_debt_count", 0)),
                signal.get("core_score_snapshot"),
                0,
                _j(signal.get("evidence_ref_uri_list", [])),
                signal.get("excluded_from_core_reason", "早期信号不进入核心 14 因子 raw score。"),
                _j(signal.get("aggregate_trace", {})),
            ),
        )


def _insert_quality_and_review_records(conn, run_id: int, pack: dict, pack_hash: str) -> None:
    validation = pack.get("_contract_validation_report") or {}
    warnings = [issue for issue in validation.get("issues", []) if issue.get("severity") == "warning"]
    findings_by_gate: dict[str, list[dict]] = {}
    for issue in warnings:
        findings_by_gate.setdefault(gate_for_issue_code(str(issue.get("code") or "")), []).append(issue)
    gate_names = resolve_track_config("c").get("review", {}).get("deterministic_gates", [])
    artifact_refs = [pack.get("_pack_path") or "run_pack", f"sha256:{pack_hash}"]
    for gate_name in gate_names:
        findings = findings_by_gate.get(gate_name, [])
        record_quality_gate(
            conn,
            run_id,
            gate_name,
            "YELLOW" if findings else "GREEN",
            findings=findings,
            artifact_refs=artifact_refs,
            gate_version=RESEARCH_WORKFLOW_CONTRACT_VERSION,
        )
    for index, item in enumerate(pack.get("review_records", []), start=1):
        findings = item.get("findings") or []
        default_review_kind = "legacy" if pack.get("pack_schema_version", LEGACY_PACK_SCHEMA) == LEGACY_PACK_SCHEMA else "independent"
        record_agent_review(
            conn,
            run_id,
            int(item.get("review_round", index)),
            item.get("reviewer_role") or item.get("stage") or "reviewer",
            str(item.get("verdict", "RED")).upper(),
            item.get("reconciliation_status", "pending"),
            json.dumps(findings, ensure_ascii=False, sort_keys=True),
            review_stage=item.get("stage", "unspecified"),
            reviewer_id=item.get("reviewer_id"),
            review_kind=item.get("review_kind", default_review_kind),
            input_artifact_hash=item.get("input_artifact_hash"),
            output_artifact_hash=item.get("output_artifact_hash"),
        )


def _update_stats_and_manifest(
    conn,
    run_id: int,
    pack: dict,
    pack_hash: str,
    *,
    workflow_brief: dict[str, Any] | None,
    workflow_manifest: dict[str, Any] | None,
    content_cache_record: dict[str, Any],
) -> None:
    stats = conn.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM opportunity_source WHERE run_id=?) AS source_count,
          (SELECT COUNT(DISTINCT source_cluster_id) FROM opportunity_source WHERE run_id=?) AS independent_source_count,
          (SELECT COUNT(*) FROM opportunity_candidate_entity WHERE run_id=?) AS candidate_count,
          (SELECT COUNT(*) FROM opportunity_entity_maturation WHERE run_id=?) AS canonical_entity_count,
          (SELECT COUNT(*) FROM opportunity_composite_score WHERE run_id=? AND is_current=1) AS scored_entity_count,
          (SELECT COUNT(*) FROM opportunity_audit_issue WHERE run_id=? AND audit_severity='p0' AND audit_issue_status='open') AS open_p0_count,
          (SELECT COUNT(*) FROM opportunity_audit_issue WHERE run_id=? AND audit_severity='p1' AND audit_issue_status='open') AS open_p1_count,
          (SELECT COUNT(*) FROM opportunity_supplement_request WHERE run_id=? AND review_status IN ('pending','in_review')) AS supplement_open_count
        """,
        (run_id, run_id, run_id, run_id, run_id, run_id, run_id, run_id),
    ).fetchone()
    conn.execute(
        """
        UPDATE opportunity_run_stats
        SET source_count=?, independent_source_count=?, candidate_count=?,
            canonical_entity_count=?, scored_entity_count=?, open_p0_count=?,
            open_p1_count=?, supplement_open_count=?, updated_at=datetime('now')
        WHERE run_id=?
        """,
        (
            stats["source_count"],
            stats["independent_source_count"],
            stats["candidate_count"],
            stats["canonical_entity_count"],
            stats["scored_entity_count"],
            stats["open_p0_count"],
            stats["open_p1_count"],
            stats["supplement_open_count"],
            run_id,
        ),
    )
    manifest = {
        "pack_slug": pack["slug"],
        "display_title": pack.get("display_title"),
        "pack_hash": pack_hash,
        "pack_path": pack.get("_pack_path"),
        "mode": "versioned_research_pack",
        "pack_schema_version": pack.get("pack_schema_version") or LEGACY_PACK_SCHEMA,
        "workflow_contract_version": pack.get("workflow_contract_version") or RESEARCH_WORKFLOW_CONTRACT_VERSION,
        "contract_validation": pack.get("_contract_validation_report", {}),
        "public_content_quality_audit": pack.get(PUBLIC_AUDIT_FIELD),
        "content_cache": content_cache_record,
        "versions": VERSION_BUNDLE,
        "deferred_capabilities": [
            "真实 crawler",
            "自动多语种搜索调度",
            "真实 PDF renderer",
        ],
    }
    conn.execute(
        """
        INSERT INTO opportunity_run_manifest(
          run_id, manifest_type, manifest_json, manifest_hash,
          intake_contract_version, evidence_policy_version, early_signal_rule_version,
          workflow_contract_version, pack_schema_version
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            run_id,
            "manual_research_pack",
            _j(manifest),
            f"manual_pack_slug:{pack['slug']}",
            INTAKE_CONTRACT_VERSION,
            EVIDENCE_POLICY_VERSION,
            EARLY_SIGNAL_RULE_VERSION,
            pack.get("workflow_contract_version") or RESEARCH_WORKFLOW_CONTRACT_VERSION,
            pack.get("pack_schema_version") or LEGACY_PACK_SCHEMA,
        ),
    )
    workflow_records = []
    if workflow_brief is not None and workflow_manifest is not None:
        workflow_records = [
            ("research_brief", workflow_brief, workflow_brief["brief_hash"]),
            ("research_execution_manifest", workflow_manifest, workflow_manifest["manifest_hash"]),
        ]
        public_audit = pack.get(PUBLIC_AUDIT_FIELD)
        if isinstance(public_audit, dict):
            workflow_records.append(
                (
                    PUBLIC_AUDIT_MANIFEST_TYPE,
                    public_audit,
                    str(public_audit.get("result_sha256") or ""),
                )
            )
    for manifest_type, payload, digest in workflow_records:
        conn.execute(
            """
            INSERT INTO opportunity_run_manifest(
              run_id, manifest_type, manifest_json, manifest_hash,
              intake_contract_version, evidence_policy_version, early_signal_rule_version,
              workflow_contract_version, pack_schema_version
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                manifest_type,
                _j(payload),
                digest,
                INTAKE_CONTRACT_VERSION,
                EVIDENCE_POLICY_VERSION,
                EARLY_SIGNAL_RULE_VERSION,
                pack.get("workflow_contract_version") or RESEARCH_WORKFLOW_CONTRACT_VERSION,
                pack.get("pack_schema_version") or LEGACY_PACK_SCHEMA,
            ),
        )
    conn.execute(
        """
        INSERT INTO opportunity_handoff_package(
          run_id, handoff_status, package_json, gap_summary
        ) VALUES(?,?,?,?)
        """,
        (
            run_id,
            pack.get("handoff_status", "research_pack_ready"),
            _j(manifest),
            pack.get("gap_summary"),
        ),
    )


def load_pack(
    path: str | Path,
    *,
    db_path: str | Path | None = None,
    replace: bool = False,
    publication_mode: str = "stage",
    require_skill_files: bool = True,
) -> int:
    if publication_mode not in {"stage", "publish"}:
        raise ValueError("publication_mode 只能是 stage 或 publish")
    pack_path = Path(path)
    pack_text = pack_path.read_text(encoding="utf-8")
    pack = _read_pack(pack_path, publication_mode=publication_mode, raw_text=pack_text)
    pack_hash = _hash_text(pack_text)
    target_db = Path(db_path) if db_path is not None else Path("data/opportunity_lens.db")
    try:
        target_db.resolve().relative_to(ROOT.resolve())
        cache_root = ROOT / "cache" / "research_content"
    except ValueError:
        cache_root = target_db.parent / ".research_content"
    content_cache_record = ContentAddressedCache(cache_root).put_text(
        pack_text,
        suffix=".json",
        metadata={
            "artifact_kind": "opportunity_lens_run_pack",
            "source_path": str(pack_path.resolve()),
            "slug": str(pack.get("slug") or ""),
            "workflow_contract_version": pack.get("workflow_contract_version") or RESEARCH_WORKFLOW_CONTRACT_VERSION,
        },
    )
    if content_cache_record["hash"] != f"sha256:{pack_hash}":
        raise IOError("run pack cache hash 与 loader pack hash 不一致")
    workflow_brief = None
    workflow_manifest = None
    if pack.get("pack_schema_version") != LEGACY_PACK_SCHEMA:
        brief, execution_manifest = build_pack_workflow_state(
            pack,
            pack_hash=content_cache_record["hash"],
            publication_mode=publication_mode,
            require_skill_files=require_skill_files,
        )
        workflow_brief = brief.as_dict()
        workflow_manifest = execution_manifest.as_dict()
    init_db(target_db, reset=False)
    conn = connect(target_db)
    try:
        existing_run_ids = _existing_slug_run_ids(conn, pack["slug"])
        if existing_run_ids and not replace:
            raise ValueError(
                f"slug={pack['slug']!r} 已存在 run_id={existing_run_ids}；"
                "默认不覆盖，确认替换时显式传 replace=True 或 CLI --replace"
            )
        if replace:
            deleted_run_ids = _delete_existing_slug(conn, pack["slug"])
            _rewind_run_sequence_after_tail_delete(conn, deleted_run_ids)
        intake = pack["intake"]
        run_id = create_run(
            conn,
            research_question=pack["research_question"],
            run_mode=pack.get("run_mode", "c_hybrid"),
            requested_by=pack.get("requested_by", "manual_verified_agent_flow"),
            problem_statement=pack.get("problem_statement"),
            display_title=pack.get("display_title"),
            available_materials_choice=intake.get("available_materials_choice", "A"),
            evidence_policy=intake.get("evidence_policy", "freshness_first"),
            intake_contract_payload=intake,
        )
        advance_run(conn, run_id, "intake_validated", "manual run pack intake 已校验")
        search_task_by_source_ref = _insert_search_plan(conn, run_id, pack)
        advance_run(conn, run_id, "searching", "研究包检索计划已登记")
        advance_run(conn, run_id, "screening", "研究包来源筛选记录已准备")
        clusters = _insert_source_clusters(conn, run_id, pack)
        sources = _insert_sources(
            conn,
            run_id,
            pack,
            clusters,
            search_task_by_source_ref=search_task_by_source_ref,
        )
        evidence_group_by_ref = {
            object_uri("source", sources[source["ref"]]): str(
                source.get("independence_key")
                or source.get("cluster")
                or source.get("publisher")
                or source["ref"]
            )
            for source in pack.get("sources", [])
            if source.get("ref") in sources
        }
        advance_run(conn, run_id, "extracting", "研究包来源与独立证据组已入库")
        pack = _normalize_pack_source_refs(pack, sources)
        _validate_public_section_bodies(pack, "normalized")
        entities = _insert_entities(conn, run_id, pack)
        evidence_objects = _insert_claims_and_data_points(conn, run_id, pack, sources, entities)
        _insert_research_profiles(conn, run_id, pack, sources, entities)
        advance_run(conn, run_id, "mapping_entities", "claim、数据点和实体映射已入库")
        has_market_entities = any(not _is_theory_entity(entity) for entity in pack.get("entities", []))
        if has_market_entities:
            advance_run(conn, run_id, "scoring", "market-linked 实体进入评分装载")
            factor_rows = _insert_scores(
                conn,
                run_id,
                pack,
                entities,
                evidence_objects,
                evidence_group_by_ref,
            )
        else:
            factor_rows = {entity["key"]: [] for entity in pack.get("entities", [])}
        _insert_early_signals(conn, run_id, pack, entities)
        advance_run(conn, run_id, "report_drafting", "评分或理论研究底稿已完成，进入报告装载")
        _insert_sections_visuals_and_followups(conn, run_id, pack, entities, factor_rows)
        advance_run(conn, run_id, "under_review", "报告、可视化和补证项已装载，等待发布审查")
        _insert_quality_and_review_records(conn, run_id, pack, pack_hash)
        _update_stats_and_manifest(
            conn,
            run_id,
            pack,
            pack_hash,
            workflow_brief=workflow_brief,
            workflow_manifest=workflow_manifest,
            content_cache_record=content_cache_record,
        )
        if replace:
            run_id = _restore_replaced_run_id(conn, run_id, deleted_run_ids)
        mark_reviewable(conn, run_id)
        if publication_mode == "publish":
            publish_run(conn, run_id, reason="V2 run pack 已通过可审计发布门禁")
        conn.commit()
        return run_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="校验、暂存或发布 Opportunity Lens 研究包。")
    parser.add_argument("pack", help="run pack JSON 路径")
    parser.add_argument("--db", default=str(Path("data/opportunity_lens.db")), help="Opportunity Lens DB 路径")
    parser.add_argument("--replace", action="store_true", help="显式替换相同 slug 的旧 run，并尽量复用原 run_id")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true", help="只校验 pack 是否可暂存，不打开或写入数据库")
    mode.add_argument("--validate-for-publish", action="store_true", help="只读执行完整发布前 pack 校验，不打开或写入数据库")
    mode.add_argument("--publish", action="store_true", help="通过发布门禁后标记 published；默认只暂存为 reviewable")
    parser.add_argument(
        "--frozen-broadcast-install",
        action="store_true",
        help=(
            "仅用于安装已经冻结并通过合同校验的广播包；仍校验 Skill 注册、"
            "建模记录和产物哈希，但不要求前端部署机保留 Skill 正文文件"
        ),
    )
    args = parser.parse_args()
    if args.frozen_broadcast_install and args.publish:
        parser.error("--frozen-broadcast-install 不得与 --publish 同时使用")
    if args.validate_only or args.validate_for_publish:
        validation_mode = "publish" if args.validate_for_publish else "validate"
        report = validate_pack_file(
            args.pack,
            publication_mode=validation_mode,
            require_skill_files=not args.frozen_broadcast_install,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not report["valid"]:
            raise SystemExit(1)
        return
    publication_mode = "publish" if args.publish else "stage"
    run_id = load_pack(
        args.pack,
        db_path=args.db,
        replace=args.replace,
        publication_mode=publication_mode,
        require_skill_files=not args.frozen_broadcast_install,
    )
    print(f"Opportunity Lens run pack 已{('发布' if args.publish else '暂存')} run_id={run_id}")


if __name__ == "__main__":
    main()
