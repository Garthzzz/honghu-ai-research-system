from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from tools.opportunity_lens.constants import (
    RESEARCH_WORKFLOW_CONTRACT_VERSION,
    RUN_PACK_SCHEMA_VERSION,
)
from tools.opportunity_lens.factor_dictionary import SEGMENT_FACTORS, factor_weight
from tools.opportunity_lens.metric_slot_gaps import summarize_missing_metric_slots
from tools.opportunity_lens.public_content_quality_audit import (
    PUBLIC_AUDIT_FIELD,
    build_pack_audit_attestation,
    render_markdown as render_public_content_audit_markdown,
    run_audit as run_public_content_audit,
)
from tools.opportunity_lens.run_pack_contract import validate_run_pack


SEGMENT_FACTOR_CODES = tuple(factor.code for factor in SEGMENT_FACTORS)


def extract_primary_research_question(intake_path: Path) -> str:
    """Return the first fenced block under the required research-question heading."""
    text = intake_path.read_text(encoding="utf-8", errors="strict")
    heading = re.search(r"(?m)^##\s*必填\s*1[^\n]*\n", text)
    if not heading:
        raise ValueError(f"研究请求缺少‘必填 1’标题：{intake_path}")
    match = re.search(r"```(?:text)?\s*\n(?P<body>.*?)\n```", text[heading.end() :], re.DOTALL)
    if not match or not match.group("body").strip():
        raise ValueError(f"研究请求缺少研究问题正文：{intake_path}")
    return match.group("body").strip()


def natural_citations(text: str, *, prefix: str = "") -> str:
    """Translate compact workpaper citations such as ``[S001]`` to viewer citations."""
    pattern = re.compile(r"\[(S\d{3}|FIN-[A-Z]+-\d{2})\]")
    translated = pattern.sub(lambda match: f"^src:source_ref:{prefix}{match.group(1)}", text)
    return re.sub(
        r"(\^src:source_ref:(?:[A-Za-z0-9_-]+-)?(?:S\d{3}|FIN-[A-Z]+-\d{2}))(?=\^src:source_ref:)",
        r"\1 ",
        translated,
    )


def normalize_agent_source(
    source: Mapping[str, Any],
    *,
    ref_prefix: str = "",
    local_path_map: Mapping[str, str] | None = None,
    fetch_date: str = "2026-07-19",
) -> dict[str, Any]:
    """Normalize a research-agent source row to the public V2 source contract."""
    raw_ref = str(source.get("source_id") or source.get("ref") or "").strip()
    if not raw_ref:
        raise ValueError("来源缺少 source_id/ref")
    locator = str(
        source.get("original_url_or_locator")
        or source.get("url")
        or source.get("local_path")
        or source.get("local_locator")
        or ""
    ).strip()
    if not locator:
        raise ValueError(f"来源 {raw_ref} 缺少原始定位")
    language_raw = str(source.get("language") or "zh-CN").strip().lower()
    if language_raw in {"zh", "zh-cn", "chinese"}:
        language = "zh-CN"
    elif language_raw.startswith("ja"):
        language = "ja"
    elif "ko" in language_raw and "en" not in language_raw:
        language = "ko"
    else:
        language = "en"

    tier_raw = str(source.get("tier") or source.get("source_tier") or "").lower()
    publisher = str(source.get("publisher") or "").lower()
    regulatory_markers = ("监管", "交易所", "政府", "commerce", "meti", "economic development board", "semi")
    if tier_raw == "t3":
        tier = "C"
    elif any(marker in tier_raw or marker in publisher for marker in regulatory_markers):
        tier = "S"
    elif any(marker in tier_raw for marker in ("定期报告", "年报", "regulatory", "first_party")):
        tier = "S"
    elif "官网" in tier_raw or "公司" in tier_raw or locator.startswith("http"):
        tier = "A"
    else:
        tier = "B"

    publish_date = str(
        source.get("publish_date")
        or source.get("published_date")
        or source.get("date")
        or ""
    ).strip()
    historical = bool(re.match(r"^(?:20(?:0\d|1\d|2[0-4]))(?:-|$)", publish_date))
    status_raw = str(source.get("source_review_status") or "").lower()
    if tier_raw == "t3":
        status = "weak_source_only"
    elif "reject" in status_raw:
        status = "reject"
    elif "stale" in status_raw or historical:
        status = "stale"
    elif "note" in status_raw or "无公开发布日期" in publish_date:
        status = "pass_with_note"
    else:
        status = "pass"

    title = str(source.get("title") or source.get("title_zh") or "").strip()
    title_zh = str(source.get("title_zh") or title).strip()
    excerpt = str(source.get("excerpt") or source.get("excerpt_zh") or "").strip()
    excerpt_zh = str(source.get("excerpt_zh") or excerpt).strip()
    result: dict[str, Any] = {
        "ref": f"{ref_prefix}{raw_ref}",
        "title": title,
        "title_zh": title_zh,
        "publisher": str(source.get("publisher") or "").strip(),
        "publish_date": publish_date if re.match(r"^\d{4}(?:-\d{2}(?:-\d{2})?)?$", publish_date) else None,
        "event_date": publish_date if re.match(r"^\d{4}(?:-\d{2}(?:-\d{2})?)?$", publish_date) else None,
        "fetch_date": fetch_date,
        "source_tier": tier,
        "source_review_status": status,
        "excerpt": excerpt,
        "excerpt_zh": excerpt_zh,
        "language": language,
        "independence_key": str(source.get("independence_key") or f"source:{raw_ref}"),
        "independence_rationale": str(
            source.get("independence_rationale")
            or "按原始发布主体、底层文件与披露事项归并；转载和同一底稿不重复计数。"
        ),
    }
    if locator.startswith(("http://", "https://")):
        result["url"] = locator
        result["local_locator"] = str(
            source.get("local_location_detail")
            or source.get("local_locator_detail")
            or source.get("local_locator")
            or "原始网页或PDF所列段落"
        )
    else:
        mapped = (local_path_map or {}).get(locator, locator)
        result["local_path"] = mapped.replace("\\", "/")
        result["local_locator"] = str(
            source.get("local_location_detail")
            or source.get("local_locator_detail")
            or source.get("local_locator")
            or locator
        )
    if historical:
        result["staleness_warning"] = str(
            source.get("staleness_warning")
            or "该资料用于历史项目、产品能力或校准，不能单独证明2026—2030年的新增订单。"
        )
    if source.get("date_note"):
        result["date_note"] = str(source["date_note"])
    return result


def normalize_agent_data_points(
    payload: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    sources_by_ref: Mapping[str, Mapping[str, Any]],
    ref_prefix: str = "",
) -> list[dict[str, Any]]:
    """Normalize parallel facts without splitting observations into artificial rows."""
    raw_points = payload.get("data_points", []) if isinstance(payload, Mapping) else payload
    points: list[dict[str, Any]] = []
    for raw in raw_points:
        source_ids = [str(value) for value in raw.get("source_ids") or []]
        if not source_ids and raw.get("source_id"):
            source_ids = [str(raw["source_id"])]
        if not source_ids and raw.get("source_ref"):
            source_ids = [str(raw["source_ref"])]
        if not source_ids:
            raise ValueError(f"数据点 {raw.get('id') or raw.get('data_point_id')} 缺少来源")
        ref = f"{ref_prefix}{source_ids[0]}"
        if ref not in sources_by_ref:
            raise ValueError(f"数据点 {raw.get('id') or raw.get('data_point_id')} 引用未知来源 {ref}")
        source = sources_by_ref[ref]
        period = str(raw.get("period") or raw.get("as_of_date") or raw.get("as_of") or "").strip()
        entity = str(raw.get("entity") or raw.get("entity_key") or raw.get("subject") or "研究对象").strip()
        metric = str(raw.get("metric") or "").strip()
        unit = str(raw.get("unit") or "文本").strip()
        raw_value = raw.get("value")
        if raw.get("observations"):
            observations_raw = list(raw.get("observations") or [])
            value_summary = f"{len(observations_raw)}期同口径序列"
        elif isinstance(raw_value, Mapping):
            value_summary = "；".join(f"{key}={value}" for key, value in raw_value.items())
        elif isinstance(raw_value, (list, tuple)):
            value_summary = "、".join(str(value) for value in raw_value)
        elif raw_value is None:
            value_summary = "原文所述状态"
        else:
            value_summary = f"{raw_value}{unit if unit not in {'文本', '状态', 'qualitative'} else ''}"
        if len(value_summary) > 180:
            value_summary = value_summary[:177] + "…"
        limitation = str(raw.get("note") or raw.get("evidence_level") or "").strip()
        interpretation = (
            f"{entity}在{period or '截至研究日'}的“{metric}”按{value_summary}记录；{limitation}"
            if limitation
            else f"这条原始披露确认{entity}在{period or '截至研究日'}的“{metric}”为{value_summary}；结论只覆盖原披露主体、期间和口径。"
        )
        route_text = f"{entity}{metric}".lower()
        if any(token in route_text for token in ("产能", "wspm", "wafer", "月产", "投产", "量产", "开工", "爬坡", "建设")):
            research_use = f"用于判断{entity}是否、何时进入扩产与硅片需求模型；未披露的月产能或爬坡进度不由投资额补推。"
        elif any(token in route_text for token in ("设备", "投资", "资本开支", "capex", "预算", "金额")):
            research_use = f"用于约束{entity}的项目或设备投入边界，并区分总投资、设备支出、已投入金额与尚未发生的采购。"
        elif any(token in route_text for token in ("订单", "合同", "客户", "供应", "交付", "验收", "认证")):
            research_use = f"用于判断{entity}的供应关系处于产品匹配、合同、交付还是验收阶段；不据此外推未披露客户或份额。"
        elif any(token in route_text for token in ("收入", "利润", "毛利", "现金流", "售价", "销量", "出货", "利用率", "库存")):
            research_use = f"用于检验{entity}的行业需求是否已经穿透到销量、价格、利用率、盈利或现金流，而不是只停留在设计产能。"
        elif any(token in route_text for token in ("工艺", "节点", "产品", "应用", "尺寸", "直径", "外延", "soi", "dram", "nand", "hbm")):
            research_use = f"用于界定{entity}对应的尺寸、产品或工艺需求，防止把不同硅片类型和设备边界合并计算。"
        else:
            research_use = f"作为{entity}“{metric}”的可追溯事实，限定项目筛选、情景判断或反方检验；不用于补造原文未披露的数量。"
        fact_type = str(raw.get("fact_type") or "").strip().lower()
        classification_text = " ".join(
            (
                fact_type,
                period,
                metric,
                str(raw.get("note") or ""),
                str(raw.get("evidence_level") or raw.get("evidence_tier") or ""),
                str(raw.get("source_excerpt") or ""),
            )
        ).lower()
        if any(token in fact_type for token in ("calculated", "inferred")):
            research_category = "calculated_inference"
        elif (
            re.search(r"(?:^|[^a-z])\d{4}e(?:[^a-z]|$)", period.lower())
            or any(token in classification_text for token in ("预测", "预计", "forecast", "projection"))
        ):
            research_category = "industry_or_company_forecast"
        elif any(token in classification_text for token in ("规划", "计划", "目标", "拟建", "意向", "planned", "target")):
            research_category = "company_plan_or_target"
        elif source.get("source_tier") == "C" or any(
            token in classification_text for token in ("媒体估计", "媒体报道", "传闻", "rumor")
        ):
            research_category = "media_estimate_reference"
        elif "series" in fact_type:
            research_category = "observed_time_series"
        else:
            research_category = "observed_fact"

        point: dict[str, Any] = {
            "source_ref": ref,
            "data_point_key": str(
                raw.get("data_point_key")
                or raw.get("data_point_id")
                or raw.get("id")
                or f"{ref}|{entity}|{metric}|{period}"
            ),
            "data_point_title": f"{entity}：{raw.get('metric')}",
            "research_category": research_category,
            "original_fact_type": fact_type or "not_labeled",
            "metric": metric,
            "period": period or "截至研究日",
            "unit": unit,
            "scope_key": f"{entity}|{period or 'as_of'}",
            "source_excerpt": str(
                raw.get("source_excerpt")
                or source.get("excerpt")
                or source.get("excerpt_zh")
                or ""
            ).strip(),
            "interpretation": interpretation,
            "research_use": research_use,
            "extraction_method": str(
                raw.get("extraction_method")
                or (
                    "inferred"
                    if "calculated" in str(raw.get("fact_type"))
                    else ("web_fetch" if source.get("url") else "pdf_direct")
                )
            ),
            "note": str(raw.get("note") or ""),
        }
        if source.get("source_tier") == "C" or source.get("source_review_status") in {
            "weak_source_only", "reference_only", "reject",
        }:
            point["policy_evidence_role"] = "reference_only"
        if str(source.get("language") or "").lower().startswith(("en", "ja", "ko")):
            point["source_excerpt_zh"] = str(
                raw.get("source_excerpt_zh") or source.get("excerpt_zh") or ""
            )
        value = raw.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            point["value_num"] = float(value)
        elif value is not None:
            if isinstance(value, (list, tuple)):
                point["value_text"] = "、".join(str(item) for item in value)
            elif isinstance(value, Mapping):
                point["value_text"] = "；".join(f"{key}={item}" for key, item in value.items())
            else:
                point["value_text"] = str(value)
        observations = []
        for observation in raw.get("observations") or []:
            row: dict[str, Any] = {"period": str(observation.get("period") or observation.get("as_of_date") or "")}
            observation_value = observation.get("value", observation.get("value_num"))
            if isinstance(observation_value, (int, float)) and not isinstance(observation_value, bool):
                row["value_num"] = float(observation_value)
            elif observation.get("value_text") is not None:
                row["value_text"] = str(observation.get("value_text") or "")
            elif observation_value is None:
                composite_values = [
                    f"{key}={value}"
                    for key, value in observation.items()
                    if key not in {"period", "as_of_date", "value", "value_num", "value_text"}
                    and value is not None
                ]
                row["value_text"] = "；".join(composite_values)
            else:
                row["value_text"] = str(observation.get("value_text") or observation_value or "")
            observations.append(row)
        if observations:
            point["observations"] = observations
        if "value_num" not in point and "value_text" not in point and not observations:
            raise ValueError(f"数据点 {raw.get('id') or raw.get('data_point_id')} 缺少值")
        points.append(point)
    return points


def apply_source_catalog_corrections(
    payload: Any,
    audit_payload: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply reviewer-approved source updates and additions deterministically."""
    raw_sources = payload.get("sources", []) if isinstance(payload, Mapping) else payload
    if not isinstance(raw_sources, list):
        raise ValueError("source catalog 顶层必须是数组或包含 sources 数组")
    corrections = (
        list(audit_payload.get("source_corrections") or [])
        if isinstance(audit_payload, Mapping)
        else []
    )
    sources = [dict(source) for source in raw_sources]
    by_id = {
        str(source.get("source_id") or source.get("ref") or "").strip(): source
        for source in sources
    }
    if "" in by_id or len(by_id) != len(sources):
        raise ValueError("source catalog 存在空或重复 source_id/ref")
    counts = {"updated": 0, "created": 0}
    applied_ids: list[str] = []
    for index, correction in enumerate(corrections):
        if not isinstance(correction, Mapping):
            raise ValueError(f"source_corrections[{index}] 必须是对象")
        action = str(correction.get("action") or "").strip()
        if not action and correction.get("source_id") and correction.get("corrected_fields"):
            action = "update_existing_source"
            correction = {
                **dict(correction),
                "match": {"source_id": str(correction["source_id"])},
                "set": dict(correction["corrected_fields"]),
            }
        correction_id = str(correction.get("correction_id") or f"source-correction-{index}")
        if action == "update_existing_source":
            match = correction.get("match") or {}
            if not isinstance(match, Mapping):
                raise ValueError(f"{correction_id}.match 必须是对象")
            source_id = str(match.get("source_id") or "").strip()
            if source_id not in by_id:
                raise ValueError(f"{correction_id} 找不到待更新来源 {source_id}")
            source = by_id[source_id]
            for key, expected in match.items():
                if key == "source_id":
                    continue
                if expected is not None and source.get(key) != expected:
                    raise ValueError(
                        f"{correction_id} 来源前置条件不一致: {key}={source.get(key)!r}, expected={expected!r}"
                    )
            updates = correction.get("set") or {}
            if not isinstance(updates, Mapping) or not updates:
                raise ValueError(f"{correction_id}.set 必须是非空对象")
            source.update(dict(updates))
            source["source_id"] = source_id
            counts["updated"] += 1
        elif action == "create_source_and_rebind":
            new_source = correction.get("new_source") or {}
            if not isinstance(new_source, Mapping):
                raise ValueError(f"{correction_id}.new_source 必须是对象")
            source = dict(new_source)
            source_id = str(source.get("source_id") or source.get("ref") or "").strip()
            if not source_id or source_id in by_id:
                raise ValueError(f"{correction_id} 新来源 ID 为空或重复: {source_id}")
            source["source_id"] = source_id
            sources.append(source)
            by_id[source_id] = source
            counts["created"] += 1
        else:
            raise ValueError(f"{correction_id} 的 source correction action 非法: {action!r}")
        applied_ids.append(correction_id)
    return sources, {
        "raw_count": len(raw_sources),
        "final_count": len(sources),
        "updated_count": counts["updated"],
        "created_count": counts["created"],
        "applied_correction_ids": applied_ids,
    }


def apply_financial_evidence_audit(
    target_payload: Any,
    source_payload: Any,
    audit_payload: Any,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Apply the independent financial audit without mutating its raw inputs.

    Besides value and ticker corrections, every financial period receives the
    audit's field-level evidence slices.  Consumers can therefore split a row
    when its income-statement and cash-flow fields come from different filings
    instead of presenting a composite row as if one excerpt supported it all.
    """
    if not isinstance(target_payload, Mapping) or not isinstance(
        target_payload.get("targets"), list
    ):
        raise ValueError("financial target payload must contain a targets array")
    if not isinstance(source_payload, Mapping) or not isinstance(
        source_payload.get("sources"), list
    ):
        raise ValueError("financial source payload must contain a sources array")
    if not isinstance(audit_payload, Mapping):
        raise ValueError("financial audit payload must be an object")

    targets_payload = copy.deepcopy(dict(target_payload))
    sources_payload = copy.deepcopy(dict(source_payload))
    targets = targets_payload["targets"]
    sources = sources_payload["sources"]
    targets_by_id = {
        str(target.get("target_id") or "").strip(): target for target in targets
    }
    sources_by_ref = {
        str(source.get("ref") or "").strip(): source for source in sources
    }
    if "" in targets_by_id or len(targets_by_id) != len(targets):
        raise ValueError("financial targets contain an empty or duplicate target_id")
    if "" in sources_by_ref or len(sources_by_ref) != len(sources):
        raise ValueError("financial sources contain an empty or duplicate ref")

    new_source_refs: list[str] = []
    for index, raw_source in enumerate(audit_payload.get("new_sources") or []):
        if not isinstance(raw_source, Mapping):
            raise ValueError(f"new_sources[{index}] must be an object")
        source = copy.deepcopy(dict(raw_source))
        ref = str(source.get("ref") or "").strip()
        if not ref or ref in sources_by_ref:
            raise ValueError(f"new financial source is empty or duplicate: {ref!r}")
        sources.append(source)
        sources_by_ref[ref] = source
        new_source_refs.append(ref)

    excerpt_replacements: list[str] = []
    superseded_refs: dict[str, str] = {}
    for index, correction in enumerate(audit_payload.get("source_corrections") or []):
        if not isinstance(correction, Mapping):
            raise ValueError(f"source_corrections[{index}] must be an object")
        ref = str(correction.get("ref") or "").strip()
        if ref not in sources_by_ref:
            raise ValueError(f"financial source correction references missing {ref!r}")
        action = str(correction.get("action") or "").strip()
        if action == "replace_excerpt":
            excerpt = str(correction.get("excerpt") or "").strip()
            excerpt_zh = str(correction.get("excerpt_zh") or "").strip()
            if not excerpt or not excerpt_zh:
                raise ValueError(f"{ref} excerpt correction is incomplete")
            sources_by_ref[ref]["excerpt"] = excerpt
            sources_by_ref[ref]["excerpt_zh"] = excerpt_zh
            excerpt_replacements.append(ref)
        elif action == "supersede":
            replacement_ref = str(correction.get("replacement_ref") or "").strip()
            if replacement_ref not in sources_by_ref:
                raise ValueError(
                    f"{ref} supersession references missing {replacement_ref!r}"
                )
            superseded_refs[ref] = replacement_ref
        else:
            raise ValueError(f"unsupported financial source correction action: {action!r}")

    target_correction_keys: set[tuple[str, str]] = set()
    for index, correction in enumerate(audit_payload.get("target_corrections") or []):
        if not isinstance(correction, Mapping):
            raise ValueError(f"target_corrections[{index}] must be an object")
        target_id = str(correction.get("target_id") or "").strip()
        period = str(correction.get("period") or "").strip()
        key = (target_id, period)
        if key in target_correction_keys:
            raise ValueError(f"duplicate financial target correction: {key}")
        target_correction_keys.add(key)
        if target_id not in targets_by_id:
            raise ValueError(f"financial correction references missing target {target_id!r}")
        corrected_fields = correction.get("corrected_fields") or {}
        if not isinstance(corrected_fields, Mapping) or not corrected_fields:
            raise ValueError(f"financial correction {key} has no corrected_fields")
        target = targets_by_id[target_id]
        if period == "ticker":
            destination = target.get("ticker_verification")
            if not isinstance(destination, dict):
                raise ValueError(f"target {target_id} has no ticker_verification object")
        else:
            matches = [
                row
                for row in target.get("financials") or []
                if str(row.get("period") or "") == period
            ]
            if len(matches) != 1:
                raise ValueError(f"financial correction period does not resolve once: {key}")
            destination = matches[0]
        destination.update(copy.deepcopy(dict(corrected_fields)))
        explicit_ref = str(correction.get("source_ref") or "").strip()
        if explicit_ref:
            destination["source_ref"] = explicit_ref
        destination["audit_source_excerpt"] = str(
            correction.get("source_excerpt") or ""
        ).strip()
        destination["audit_source_excerpt_zh"] = str(
            correction.get("source_excerpt_zh") or ""
        ).strip()

    raw_period_audits = audit_payload.get("period_audits") or []
    period_audits: dict[tuple[str, str], Mapping[str, Any]] = {}
    for index, row in enumerate(raw_period_audits):
        if not isinstance(row, Mapping):
            raise ValueError(f"period_audits[{index}] must be an object")
        key = (str(row.get("target_id") or ""), str(row.get("period") or ""))
        if key in period_audits:
            raise ValueError(f"duplicate financial period audit: {key}")
        period_audits[key] = row
    expected_period_keys = {
        (str(target["target_id"]), str(row["period"]))
        for target in targets
        for row in target.get("financials") or []
    }
    if set(period_audits) != expected_period_keys:
        missing = sorted(expected_period_keys - set(period_audits))
        unexpected = sorted(set(period_audits) - expected_period_keys)
        raise ValueError(
            "financial period audit coverage is incomplete: "
            f"missing={missing}, unexpected={unexpected}"
        )

    evidence_slice_count = 0
    for target in targets:
        target_id = str(target["target_id"])
        ticker_info = target.get("ticker_verification") or {}
        ticker_ref = str(ticker_info.get("source_ref") or "")
        ticker_info["source_ref"] = superseded_refs.get(ticker_ref, ticker_ref)
        if ticker_info["source_ref"] not in sources_by_ref:
            raise ValueError(f"{target_id} ticker references missing source")
        for row in target.get("financials") or []:
            period = str(row["period"])
            audit = period_audits[(target_id, period)]
            status = str(audit.get("status") or "").strip().lower()
            if status not in {"pass", "correct"}:
                raise ValueError(f"{target_id} {period} has non-passing audit status {status!r}")
            audit_fields = audit.get("corrected_fields") or {}
            if not isinstance(audit_fields, Mapping):
                raise ValueError(f"{target_id} {period} corrected_fields must be an object")
            row.update(copy.deepcopy(dict(audit_fields)))
            raw_evidence = audit.get("field_evidence") or []
            if not isinstance(raw_evidence, list) or not raw_evidence:
                raise ValueError(f"{target_id} {period} has no field_evidence")
            evidence_slices: list[dict[str, Any]] = []
            supported_fields: set[str] = set()
            for evidence_index, evidence in enumerate(raw_evidence):
                if not isinstance(evidence, Mapping):
                    raise ValueError(
                        f"{target_id} {period} field_evidence[{evidence_index}] must be an object"
                    )
                ref = superseded_refs.get(
                    str(evidence.get("source_ref") or "").strip(),
                    str(evidence.get("source_ref") or "").strip(),
                )
                if ref not in sources_by_ref:
                    raise ValueError(f"{target_id} {period} references missing source {ref!r}")
                supports = [
                    str(field).strip()
                    for field in (evidence.get("supports") or [])
                    if str(field).strip()
                ]
                if not supports:
                    raise ValueError(f"{target_id} {period} evidence {ref} supports no fields")
                missing_values = [field for field in supports if row.get(field) is None]
                if missing_values:
                    raise ValueError(
                        f"{target_id} {period} evidence {ref} points to empty fields {missing_values}"
                    )
                excerpt = str(evidence.get("source_excerpt") or "").strip()
                excerpt_zh = str(evidence.get("source_excerpt_zh") or "").strip()
                if not excerpt or not excerpt_zh:
                    raise ValueError(
                        f"{target_id} {period} evidence {ref} has no exact bilingual excerpt"
                    )
                evidence_slices.append(
                    {
                        "source_ref": ref,
                        "supports": supports,
                        "source_excerpt": excerpt,
                        "source_excerpt_zh": excerpt_zh,
                    }
                )
                supported_fields.update(supports)
            row["field_evidence"] = evidence_slices
            evidence_slice_count += len(evidence_slices)
            current_ref = superseded_refs.get(
                str(row.get("source_ref") or ""), str(row.get("source_ref") or "")
            )
            evidence_refs = {item["source_ref"] for item in evidence_slices}
            row["source_ref"] = current_ref if current_ref in evidence_refs else evidence_slices[0]["source_ref"]

    raw_point_audits = audit_payload.get("target_data_point_audits") or []
    point_audits: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(raw_point_audits):
        if not isinstance(row, Mapping):
            raise ValueError(f"target_data_point_audits[{index}] must be an object")
        target_id = str(row.get("target_id") or "").strip()
        if not target_id or target_id in point_audits:
            raise ValueError(f"duplicate or empty target data-point audit: {target_id!r}")
        point_audits[target_id] = row
    if set(point_audits) != set(targets_by_id):
        raise ValueError("target data-point audit coverage does not match financial targets")

    final_target_point_count = 0
    for target_id, target in targets_by_id.items():
        audit = point_audits[target_id]
        replacements = audit.get("replacement_records") or []
        originals = [copy.deepcopy(dict(point)) for point in target.get("target_data_points") or []]
        if replacements:
            if not isinstance(replacements, list):
                raise ValueError(f"{target_id} replacement_records must be an array")
            defaults = originals[0] if originals else {}
            normalized_points: list[dict[str, Any]] = []
            for replacement in replacements:
                if not isinstance(replacement, Mapping):
                    raise ValueError(f"{target_id} replacement record must be an object")
                point = copy.deepcopy(defaults)
                point.update(copy.deepcopy(dict(replacement)))
                ref = superseded_refs.get(
                    str(point.pop("source_ref", "") or "").strip(),
                    str(point.get("evidence_ref_uri") or "").replace("source_ref:", "").strip(),
                )
                if not ref:
                    ref = str(point.get("evidence_ref_uri") or "").replace("source_ref:", "").strip()
                    ref = superseded_refs.get(ref, ref)
                if ref not in sources_by_ref:
                    raise ValueError(f"{target_id} target data point references missing {ref!r}")
                source = sources_by_ref[ref]
                point["evidence_ref_uri"] = f"source_ref:{ref}"
                point.setdefault("metric_category", "financial_trend")
                point["source_title"] = source.get("title") or source.get("title_zh")
                point["source_title_zh"] = source.get("title_zh") or source.get("title")
                point["source_publisher"] = source.get("publisher")
                point["source_url"] = source.get("url")
                point["source_language"] = source.get("language")
                if not str(point.get("source_excerpt") or "").strip():
                    raise ValueError(f"{target_id} replacement data point has no exact excerpt")
                if str(source.get("language") or "").lower() not in {"zh", "zh-cn"} and not str(
                    point.get("source_excerpt_zh") or ""
                ).strip():
                    raise ValueError(f"{target_id} replacement data point has no Chinese excerpt")
                normalized_points.append(point)
            target["target_data_points"] = normalized_points
        else:
            action = str(audit.get("action") or "").strip()
            if action != "retain":
                raise ValueError(f"{target_id} audit action {action!r} requires replacements")
            for point in originals:
                ref = str(point.get("evidence_ref_uri") or "").replace("source_ref:", "")
                ref = superseded_refs.get(ref, ref)
                if ref not in sources_by_ref:
                    raise ValueError(f"{target_id} retained point references missing {ref!r}")
                point["evidence_ref_uri"] = f"source_ref:{ref}"
            target["target_data_points"] = originals
        final_target_point_count += len(target["target_data_points"])

    sources_payload["sources"] = sources
    targets_payload["targets"] = targets
    summary = {
        "schema_version": str(audit_payload.get("schema_version") or ""),
        "publication_decision_before_application": str(
            (audit_payload.get("summary") or {}).get("publication_decision") or ""
        ),
        "source_excerpt_replacement_count": len(excerpt_replacements),
        "source_excerpt_replacement_refs": excerpt_replacements,
        "new_source_count": len(new_source_refs),
        "new_source_refs": new_source_refs,
        "superseded_sources": superseded_refs,
        "target_correction_count": len(target_correction_keys),
        "financial_period_count": len(expected_period_keys),
        "field_evidence_slice_count": evidence_slice_count,
        "target_data_point_count": final_target_point_count,
    }
    return targets_payload, sources_payload, summary


_FINANCIAL_FIELD_LABELS: dict[str, str] = {
    "revenue": "收入",
    "cost_of_revenue": "营业成本",
    "gross_profit": "毛利润",
    "gross_margin_pct": "毛利率",
    "adjusted_main_business_gross_margin_pct": "调整后主营毛利率",
    "operating_profit": "营业利润",
    "operating_margin_pct": "营业利润率",
    "net_profit": "净利润",
    "net_profit_attributable_to_parent": "归母净利润",
    "operating_cash_flow": "经营现金流",
    "capex": "资本开支",
    "capex_cash_outflow_net_of_grants": "扣除补助后的资本开支现金净额",
    "capex_cash_paid_for_long_term_assets": "购建长期资产现金支出",
    "capex_cash_paid_intangibles_and_ppe": "无形资产及固定资产现金支出",
    "capital_investment_executed": "资本投入执行额",
    "free_cash_flow": "自由现金流",
    "issuer_defined_net_cash_flow": "公司定义净现金流",
}


def build_financial_data_points(
    target: Mapping[str, Any],
    sources_by_ref: Mapping[str, Mapping[str, Any]],
    *,
    normalize_order_intake_wording: bool = False,
) -> list[dict[str, Any]]:
    """Build target data points with exact, field-scoped financial evidence."""

    def clean_excerpt(value: Any) -> str:
        text = str(value or "")
        if normalize_order_intake_wording:
            return text.replace("order intake", "new orders").replace(
                "Order intake", "New orders"
            )
        return text

    points: list[dict[str, Any]] = []
    for raw_point in target.get("target_data_points") or []:
        point = copy.deepcopy(dict(raw_point))
        ref = str(point.get("evidence_ref_uri") or "").replace("source_ref:", "")
        if ref not in sources_by_ref:
            raise ValueError(f"target data point references missing source {ref!r}")
        source = sources_by_ref[ref]
        point["source_title"] = source.get("title") or source.get("title_zh")
        point["source_title_zh"] = source.get("title_zh") or source.get("title")
        point["source_publisher"] = source.get("publisher")
        point["source_url"] = source.get("url")
        point["source_language"] = source.get("language")
        point["source_excerpt"] = clean_excerpt(
            point.get("source_excerpt") or source.get("excerpt")
        )
        if str(source.get("language") or "").lower() != "zh-cn":
            point["source_excerpt_zh"] = str(
                point.get("source_excerpt_zh") or source.get("excerpt_zh") or ""
            )
        points.append(point)

    for row in target.get("financials") or []:
        raw_slices = row.get("field_evidence") or [
            {
                "source_ref": row.get("source_ref"),
                "supports": [
                    field
                    for field in _FINANCIAL_FIELD_LABELS
                    if row.get(field) is not None
                ],
                "source_excerpt": row.get("source_excerpt"),
                "source_excerpt_zh": row.get("source_excerpt_zh"),
            }
        ]
        for slice_index, evidence in enumerate(raw_slices, start=1):
            ref = str(evidence.get("source_ref") or "")
            if ref not in sources_by_ref:
                raise ValueError(f"financial row references missing source {ref!r}")
            source = sources_by_ref[ref]
            supports = [str(field) for field in evidence.get("supports") or []]
            values: list[str] = []
            for field in supports:
                value = row.get(field)
                if value is None:
                    continue
                label = _FINANCIAL_FIELD_LABELS.get(field, field)
                suffix = "%" if field.endswith("_pct") else ""
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    values.append(f"{label}{float(value):,.2f}{suffix}")
                else:
                    values.append(f"{label}{value}{suffix}")
            if not values:
                raise ValueError(
                    f"{target.get('target_id')} {row.get('period')} evidence {ref} has no values"
                )
            source_count_suffix = (
                f"（来源{slice_index}/{len(raw_slices)}）" if len(raw_slices) > 1 else ""
            )
            points.append(
                {
                    "metric_name": (
                        f"{target['company_name_zh']}{row['period']}核心财务{source_count_suffix}"
                    ),
                    "metric_category": "financial_history",
                    "period": str(row["period"]),
                    "as_of_date": str(row.get("period_end") or ""),
                    "value_text": "；".join(values),
                    "unit": f"{row['currency']} 百万，比例除外",
                    "source_title": source["title"],
                    "source_title_zh": source.get("title_zh") or source["title"],
                    "source_publisher": source["publisher"],
                    "source_url": source.get("url"),
                    "source_excerpt": clean_excerpt(
                        evidence.get("source_excerpt") or source.get("excerpt")
                    ),
                    "source_excerpt_zh": str(
                        evidence.get("source_excerpt_zh")
                        or source.get("excerpt_zh")
                        or source.get("excerpt")
                        or ""
                    ),
                    "source_language": source["language"],
                    "evidence_ref_uri": source_uri(ref),
                    "data_quality_label": "发行人或交易所财务",
                    "direction": "mixed",
                    "credibility_weight": 1.0,
                    "numeric_weight": 1.0,
                }
            )
    return points


def apply_data_point_evidence_audit(
    payload: Any,
    audit_payload: Any,
    *,
    minimum_retained: int = 100,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply a complete pass/correct/drop audit before pack normalization.

    A V2 data point has one primary ``source_ref``.  If an audit says that a
    claim needs an additional source to become true, the composite claim is
    removed instead of silently attaching evidence the schema cannot preserve.
    """
    raw_points = payload.get("data_points", []) if isinstance(payload, Mapping) else payload
    if not isinstance(raw_points, list):
        raise ValueError("data_points 顶层必须是数组或包含 data_points 数组")
    if isinstance(audit_payload, Mapping):
        audit_rows = None
        for key in ("audits", "records", "results", "data_points"):
            if key in audit_payload:
                audit_rows = audit_payload[key]
                break
    else:
        audit_rows = audit_payload
    if not isinstance(audit_rows, list):
        raise ValueError("evidence audit 必须是数组或包含 audits/records/results 数组")
    excerpt_catalog = (
        dict(audit_payload.get("excerpt_catalog") or {})
        if isinstance(audit_payload, Mapping)
        else {}
    )

    def point_id(row: Mapping[str, Any]) -> str:
        return str(row.get("data_point_id") or row.get("id") or "").strip()

    raw_by_id: dict[str, dict[str, Any]] = {}
    raw_order: list[str] = []
    for index, raw in enumerate(raw_points):
        if not isinstance(raw, Mapping):
            raise ValueError(f"data_points[{index}] 必须是对象")
        identifier = point_id(raw)
        if not identifier:
            raise ValueError(f"data_points[{index}] 缺少 id/data_point_id")
        if identifier in raw_by_id:
            raise ValueError(f"data point ID 重复: {identifier}")
        raw_by_id[identifier] = dict(raw)
        raw_order.append(identifier)

    audit_by_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(audit_rows):
        if not isinstance(row, Mapping):
            raise ValueError(f"evidence audit[{index}] 必须是对象")
        identifier = point_id(row)
        if not identifier:
            raise ValueError(f"evidence audit[{index}] 缺少 data_point_id")
        if identifier in audit_by_id:
            raise ValueError(f"evidence audit ID 重复: {identifier}")
        audit_by_id[identifier] = dict(row)

    missing = [identifier for identifier in raw_order if identifier not in audit_by_id]
    unexpected = [identifier for identifier in audit_by_id if identifier not in raw_by_id]
    if missing or unexpected:
        raise ValueError(
            "evidence audit 覆盖不完整: "
            f"missing={missing[:10]}, unexpected={unexpected[:10]}"
        )

    retained: list[dict[str, Any]] = []
    counts = {"pass": 0, "correct": 0, "drop": 0, "multi_source_drop": 0}
    dropped_ids: list[str] = []
    for identifier in raw_order:
        raw = dict(raw_by_id[identifier])
        audit = audit_by_id[identifier]
        catalog_excerpt = excerpt_catalog.get(str(audit.get("evidence_excerpt_key") or ""), {})
        if catalog_excerpt and not isinstance(catalog_excerpt, Mapping):
            raise ValueError(f"{identifier} 的 evidence excerpt catalog 记录必须是对象")
        verdict = str(audit.get("verdict") or "").strip().lower()
        if verdict not in {"pass", "correct", "drop"}:
            raise ValueError(f"{identifier} 的 evidence audit verdict 非法: {verdict!r}")
        audited_source_ids = [
            str(value).strip()
            for value in (audit.get("source_ids") or [])
            if str(value).strip()
        ]
        if audited_source_ids:
            raw["source_id"] = audited_source_ids[0]
            raw.pop("source_ids", None)
        additional_sources = [
            str(value).strip()
            for value in (audit.get("additional_source_ids") or [])
            if str(value).strip()
        ]
        if not additional_sources and len(audited_source_ids) > 1:
            additional_sources = audited_source_ids[1:]
        if verdict == "drop" or additional_sources:
            counts["drop"] += 1
            if additional_sources:
                counts["multi_source_drop"] += 1
            dropped_ids.append(identifier)
            continue

        if verdict == "correct":
            corrected_fields = audit.get("corrected_fields") or {}
            if not isinstance(corrected_fields, Mapping):
                raise ValueError(f"{identifier}.corrected_fields 必须是对象")
            raw.update(dict(corrected_fields))
            corrected_excerpt = (
                audit.get("corrected_source_excerpt")
                or audit.get("corrected_excerpt")
                or audit.get("source_excerpt")
                or catalog_excerpt.get("source_excerpt")
            )
            corrected_excerpt_zh = (
                audit.get("corrected_source_excerpt_zh")
                or audit.get("corrected_excerpt_zh")
                or audit.get("source_excerpt_zh")
                or catalog_excerpt.get("source_excerpt_zh")
            )
            if not str(corrected_excerpt or "").strip():
                raise ValueError(f"{identifier} 标为 correct 但缺少精确 corrected_excerpt")
            raw["source_excerpt"] = str(corrected_excerpt).strip()
            if str(corrected_excerpt_zh or "").strip():
                raw["source_excerpt_zh"] = str(corrected_excerpt_zh).strip()
            counts["correct"] += 1
        else:
            corrected_excerpt = (
                audit.get("corrected_source_excerpt")
                or audit.get("corrected_excerpt")
                or audit.get("source_excerpt")
                or catalog_excerpt.get("source_excerpt")
            )
            corrected_excerpt_zh = (
                audit.get("corrected_source_excerpt_zh")
                or audit.get("corrected_excerpt_zh")
                or audit.get("source_excerpt_zh")
                or catalog_excerpt.get("source_excerpt_zh")
            )
            if str(corrected_excerpt or "").strip():
                raw["source_excerpt"] = str(corrected_excerpt).strip()
            if str(corrected_excerpt_zh or "").strip():
                raw["source_excerpt_zh"] = str(corrected_excerpt_zh).strip()
            if not str(raw.get("source_excerpt") or "").strip():
                raise ValueError(f"{identifier} 标为 pass 但原 source_excerpt 为空")
            counts["pass"] += 1
        retained.append(raw)

    retained_before_series_merge = len(retained)
    merge_groups = (
        list(audit_payload.get("required_series_merges") or [])
        if isinstance(audit_payload, Mapping)
        else []
    )
    if merge_groups:
        retained_by_id = {point_id(row): row for row in retained}
        group_by_member: dict[str, list[str]] = {}
        for index, group in enumerate(merge_groups):
            if not isinstance(group, Mapping):
                raise ValueError(f"required_series_merges[{index}] 必须是对象")
            identifiers = [
                str(value).strip()
                for value in (group.get("data_point_ids") or [])
                if str(value).strip() in retained_by_id
            ]
            if len(identifiers) < 2:
                continue
            if any(identifier in group_by_member for identifier in identifiers):
                raise ValueError(f"序列合并组存在重叠: {identifiers}")
            for identifier in identifiers:
                group_by_member[identifier] = identifiers

        merged: list[dict[str, Any]] = []
        consumed: set[str] = set()
        for identifier in raw_order:
            if identifier not in retained_by_id or identifier in consumed:
                continue
            identifiers = group_by_member.get(identifier)
            if not identifiers:
                merged.append(retained_by_id[identifier])
                continue
            rows = [retained_by_id[value] for value in identifiers]
            source_ids = {
                str(row.get("source_id") or (row.get("source_ids") or [""])[0])
                for row in rows
            }
            if len(source_ids) != 1:
                raise ValueError(f"序列合并组必须来自同一主来源: {identifiers}")
            base = dict(rows[0])
            observations: list[dict[str, Any]] = []
            excerpts: list[str] = []
            excerpts_zh: list[str] = []
            notes: list[str] = []
            periods: list[str] = []
            for row in rows:
                period = str(row.get("period") or row.get("as_of") or "截至研究日")
                periods.append(period)
                if row.get("observations"):
                    observations.extend(dict(value) for value in row["observations"])
                elif isinstance(row.get("value"), (int, float)) and not isinstance(row.get("value"), bool):
                    observations.append({"period": period, "value": row["value"]})
                else:
                    observations.append({"period": period, "value_text": str(row.get("value") or "")})
                excerpt = str(row.get("source_excerpt") or "").strip()
                excerpt_zh = str(row.get("source_excerpt_zh") or "").strip()
                note = str(row.get("note") or "").strip()
                if excerpt and excerpt not in excerpts:
                    excerpts.append(excerpt)
                if excerpt_zh and excerpt_zh not in excerpts_zh:
                    excerpts_zh.append(excerpt_zh)
                if note and note not in notes:
                    notes.append(note)
            base.pop("value", None)
            base["observations"] = observations
            base["period"] = periods[0] if len(set(periods)) == 1 else f"{periods[0]}—{periods[-1]}"
            base["source_excerpt"] = "\n".join(excerpts)
            if excerpts_zh:
                base["source_excerpt_zh"] = "\n".join(excerpts_zh)
            merge_note = "同一来源、同一对象和同一指标的多期观测已合并为一条平行数据点。"
            base["note"] = "；".join([*notes, merge_note])
            merged.append(base)
            consumed.update(identifiers)
        retained = merged

    if len(retained) < int(minimum_retained):
        raise ValueError(
            f"证据审计后只保留 {len(retained)} 个平行数据点，低于门槛 {minimum_retained}"
        )
    summary = {
        "raw_count": len(raw_points),
        "retained_count": len(retained),
        "retained_before_series_merge": retained_before_series_merge,
        "series_merge_group_count": len({tuple(value) for value in group_by_member.values()}) if merge_groups else 0,
        "series_merge_deduction": retained_before_series_merge - len(retained),
        "pass_count": counts["pass"],
        "correct_count": counts["correct"],
        "drop_count": counts["drop"],
        "multi_source_drop_count": counts["multi_source_drop"],
        "dropped_ids": dropped_ids,
        "coverage_complete": True,
    }
    return retained, summary


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )


def source_uri(ref: str) -> str:
    return f"source_ref:{ref}"


def _finite(value: Any, *, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是有限数值") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} 必须是有限数值")
    return number


_USABLE_SLOT_STATUSES = {"available", "calculated", "stale_but_usable"}


# V0.8.1 segment-factor slot contract.  The builders route already-reviewed
# source excerpts into these slots; a slot remains missing when no routed
# source contains the information required by that slot.  This deliberately
# avoids treating a factor-level source list as if every source answered every
# metric question.
_SEGMENT_SLOT_PROTOCOL: dict[str, tuple[dict[str, Any], ...]] = {
    "demand.downstream_price_momentum": (
        {"code": "downstream_price_3m_change", "label": "下游产品三个月价格变化", "role": "primary", "weight": 0.45, "keywords": ("价格", "售价", "均价", "asp", "price")},
        {"code": "downstream_price_1m_change", "label": "下游产品一个月价格变化", "role": "supporting", "weight": 0.20, "keywords": ("月度", "环比", "单月", "1m", "month-on-month")},
        {"code": "downstream_price_yoy_change", "label": "下游产品价格同比变化", "role": "supporting", "weight": 0.20, "keywords": ("同比", "yoy", "year-on-year")},
        {"code": "price_source_quality", "label": "价格来源质量", "role": "context", "weight": 0.05, "keywords": ("合同价", "现货", "指数", "报价", "contract price", "spot price")},
        {"code": "price_reversal_signal", "label": "价格回落或砍价反证", "role": "contradiction", "weight": 0.10, "keywords": ("降价", "价格回落", "砍价", "price decline", "price cut")},
    ),
    "demand.customer_capex_capacity_signal": (
        {"code": "customer_capex_yoy_or_guidance", "label": "客户资本开支变化或指引", "role": "primary", "weight": 0.35, "keywords": ("资本开支", "capex", "投资预算", "投资计划")},
        {"code": "confirmed_capacity_expansion_event", "label": "已确认扩产事件", "role": "primary", "weight": 0.30, "keywords": ("扩产", "新建", "开工", "投产", "量产", "产能", "fab", "capacity")},
        {"code": "equipment_order_or_billings_proxy", "label": "设备订单或出货代理", "role": "supporting", "weight": 0.20, "keywords": ("设备订单", "设备采购", "billings", "equipment order", "交付设备")},
        {"code": "customer_delay_or_cut_event", "label": "客户延期或削减计划反证", "role": "contradiction", "weight": 0.15, "keywords": ("延期", "推迟", "削减", "取消", "delay", "postpone", "cut capex", "cancel")},
    ),
    "demand.output_consumption_proxy": (
        {"code": "output_or_shipment_growth_3m", "label": "产出或出货变化", "role": "primary", "weight": 0.40, "keywords": ("出货", "销量", "产量", "晶圆投入", "wafer input", "shipment", "output")},
        {"code": "industry_sales_growth", "label": "行业销售变化", "role": "supporting", "weight": 0.25, "keywords": ("行业销售", "销售额", "wsts", "sia", "industry sales")},
        {"code": "utilization_rate_signal", "label": "产能利用率或开工率", "role": "supporting", "weight": 0.20, "keywords": ("利用率", "开工率", "稼动率", "utilization")},
        {"code": "inventory_destocking_signal", "label": "库存与去库存反证", "role": "contradiction", "weight": 0.15, "keywords": ("库存", "去库存", "存货", "inventory", "destock")},
    ),
    "demand.application_intensity_change": (
        {"code": "technology_generation_shift", "label": "技术代际变化", "role": "primary", "weight": 0.40, "keywords": ("先进制程", "工艺节点", "纳米", "hbm", "nand", "层", "gaa", "euv", "advanced node")},
        {"code": "material_intensity_proxy", "label": "单位材料或工序强度", "role": "primary", "weight": 0.30, "keywords": ("单位用量", "工序", "外延", "抛光", "清洗", "监控片", "材料强度", "process step", "epitax")},
        {"code": "customer_mix_shift", "label": "高端产品结构变化", "role": "supporting", "weight": 0.20, "keywords": ("高端", "产品结构", "产品组合", "占比", "mix", "premium")},
        {"code": "process_reduction_or_substitution", "label": "工艺减少或替代反证", "role": "contradiction", "weight": 0.10, "keywords": ("减少工序", "材料替代", "降低用量", "substitution", "fewer process")},
    ),
    "supply.capacity_event_12m": (
        {"code": "capacity_addition_12m_pct", "label": "未来十二个月有效新增产能", "role": "primary", "weight": 0.35, "keywords": ("十二个月", "12个月", "12m", "明年", "2026", "2027", "新增产能", "扩产")},
        {"code": "current_effective_capacity", "label": "当前有效产能", "role": "supporting", "weight": 0.15, "keywords": ("现有产能", "稳定产能", "有效产能", "月产", "当前产能", "wspm")},
        {"code": "confirmed_shutdown_or_disruption", "label": "已确认停产或供应扰动", "role": "primary", "weight": 0.25, "keywords": ("停产", "限产", "断供", "事故", "复产", "shutdown", "disruption")},
        {"code": "ramp_delay_or_cancel_event", "label": "爬坡延期或取消", "role": "supporting", "weight": 0.15, "keywords": ("爬坡", "延期", "推迟", "取消", "ramp", "delay")},
        {"code": "planned_or_rumored_capacity", "label": "仅规划或传闻产能", "role": "context", "weight": 0.10, "keywords": ("规划", "拟建", "计划", "意向", "planned", "rumor")},
    ),
    "supply.expansion_cycle_bucket": (
        {"code": "expansion_cycle_months_or_bucket", "label": "从立项到可用产能的周期", "role": "primary", "weight": 0.50, "keywords": ("建设周期", "扩产周期", "开工", "投产", "量产", "达产", "construction", "mass production")},
        {"code": "equipment_lead_time_bucket", "label": "关键设备交付周期", "role": "supporting", "weight": 0.20, "keywords": ("交付周期", "设备交付", "lead time", "设备搬入")},
        {"code": "qualification_or_ramp_cycle_bucket", "label": "客户验证或爬坡周期", "role": "supporting", "weight": 0.20, "keywords": ("验证周期", "客户认证", "验收", "爬坡", "qualification", "ramp")},
        {"code": "fast_modular_expansion_signal", "label": "可快速复制扩产反证", "role": "contradiction", "weight": 0.10, "keywords": ("快速扩产", "模块化", "短周期", "rapid expansion", "modular")},
    ),
    "supply.raw_policy_constraint": (
        {"code": "raw_material_supply_concentration", "label": "原料或供应地集中度", "role": "primary", "weight": 0.30, "keywords": ("原材料", "供应集中", "进口依赖", "集中度", "raw material", "concentration")},
        {"code": "export_import_control_event", "label": "进出口管制事件", "role": "primary", "weight": 0.30, "keywords": ("出口管制", "进口限制", "许可", "制裁", "实体清单", "export control", "sanction")},
        {"code": "raw_material_price_momentum", "label": "原材料价格变化", "role": "supporting", "weight": 0.20, "keywords": ("原料价格", "材料价格", "成本上涨", "raw material price")},
        {"code": "policy_direction_for_entity", "label": "政策对研究对象的方向", "role": "supporting", "weight": 0.20, "keywords": ("补贴", "政策支持", "国产化", "本土化", "限制", "subsidy", "localization")},
    ),
    "supply.supplier_structure_bucket": (
        {"code": "supplier_structure_bucket", "label": "供应商竞争结构", "role": "primary", "weight": 0.40, "keywords": ("市场份额", "竞争格局", "寡头", "垄断", "集中度", "market share", "oligopoly")},
        {"code": "cr3_calculated", "label": "前三家份额复算", "role": "supporting", "weight": 0.20, "keywords": ("cr3", "前三", "top 3", "top3")},
        {"code": "effective_supplier_count", "label": "有效供应商数量", "role": "supporting", "weight": 0.20, "keywords": ("供应商数量", "五家公司", "厂商数量", "supplier count", "five companies")},
        {"code": "qualification_bottleneck_text", "label": "认证与切换瓶颈", "role": "supporting", "weight": 0.10, "keywords": ("认证", "合格供应商", "切换成本", "qualification", "qualified supplier")},
        {"code": "cr3_gap_or_definition_conflict", "label": "份额口径冲突", "role": "contradiction", "weight": 0.10, "keywords": ("口径不一致", "份额冲突", "无法加总", "definition conflict")},
    ),
    "supply.substitution_barrier": (
        {"code": "process_criticality_bucket", "label": "工序关键程度", "role": "primary", "weight": 0.35, "keywords": ("关键工序", "核心工艺", "必经", "关键设备", "critical process")},
        {"code": "commercial_alternative_status", "label": "商业替代方案成熟度", "role": "primary", "weight": 0.35, "keywords": ("替代", "国产设备", "商业化", "alternative", "substitute")},
        {"code": "switching_validation_burden", "label": "切换与重新验证负担", "role": "supporting", "weight": 0.20, "keywords": ("重新验证", "客户验证", "认证", "流片", "switching", "qualification")},
        {"code": "substitution_event", "label": "替代技术商业化反证", "role": "contradiction", "weight": 0.10, "keywords": ("替代技术量产", "商业化替代", "已替代", "commercial substitution")},
    ),
    "signal.material_price_momentum": (
        {"code": "material_price_3m_change", "label": "材料三个月价格变化", "role": "primary", "weight": 0.40, "keywords": ("硅片价格", "材料价格", "售价", "均价", "asp", "price")},
        {"code": "material_price_1m_change", "label": "材料一个月价格变化", "role": "supporting", "weight": 0.15, "keywords": ("月度", "环比", "1m", "month-on-month")},
        {"code": "material_price_yoy_change", "label": "材料价格同比变化", "role": "supporting", "weight": 0.15, "keywords": ("同比", "yoy", "year-on-year")},
        {"code": "customs_or_trade_price_proxy", "label": "贸易价格代理", "role": "supporting", "weight": 0.15, "keywords": ("海关", "进口均价", "出口均价", "trade price", "customs")},
        {"code": "official_price_revision_event", "label": "官方调价事件", "role": "supporting", "weight": 0.10, "keywords": ("调价", "涨价公告", "价格调整", "price revision")},
        {"code": "price_denial_or_reversal", "label": "否认涨价或价格回落反证", "role": "contradiction", "weight": 0.05, "keywords": ("否认涨价", "价格回落", "降价", "price reversal", "price decline")},
    ),
}


def _coverage_multiplier(value: float) -> float:
    value = round(float(value), 12)
    if value >= 0.80:
        return 1.0
    if value >= 0.65:
        return 0.85
    if value >= 0.50:
        return 0.60
    return 0.0


def _confidence_multiplier(value: float) -> float:
    if value >= 0.85:
        return 1.0
    if value >= 0.75:
        return 0.90
    if value >= 0.60:
        return 0.75
    if value >= 0.45:
        return 0.50
    return 0.0


def _source_weight(source: Mapping[str, Any]) -> float:
    return {"S": 1.0, "A": 0.97, "B": 0.93, "C": 0.86}.get(
        str(source.get("source_tier") or "").upper(),
        0.0,
    )


def _score_bucket(score: float) -> str:
    if score >= 80:
        return "强正向"
    if score >= 65:
        return "正向"
    if score >= 55:
        return "温和正向"
    if score >= 45:
        return "中性"
    if score >= 30:
        return "负向"
    return "强负向"


def _protocol_metric_slots(
    *,
    key: str,
    code: str,
    expert_bucket_score: float,
    source_refs: Sequence[str],
    sources_by_ref: Mapping[str, Mapping[str, Any]],
    item: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Compile explicit, replayable inputs into the canonical V0.8.1 slots.

    Factor-level sources and an expert factor score are *not* metric inputs.
    A slot becomes usable only when the builder supplies ``metric_slot_inputs``
    with concrete data-point keys and a standardized value.  Score-bearing
    slots additionally require a bucket and frozen value-to-score rule;
    context slots deliberately serialize none of those scoring fields.  This prevents a broad
    source excerpt (for example one mentioning both capacity and equipment)
    from being linked to an unrelated slot and prevents every slot from merely
    inheriting the same factor-level judgement.
    """

    protocol = _SEGMENT_SLOT_PROTOCOL.get(code)
    if not protocol:
        raise ValueError(f"{key}.{code} 缺少V0.8.1指标槽协议")
    del expert_bucket_score  # Factor-level judgement must never fill a slot.
    explicit_inputs = item.get("metric_slot_inputs") or {}
    if not isinstance(explicit_inputs, Mapping):
        raise ValueError(f"{key}.{code}.metric_slot_inputs 必须是对象")
    candidates = item.get("candidate_data_points") or []
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        raise ValueError(f"{key}.{code}.candidate_data_points 必须是数组")
    candidates_by_key: dict[str, Mapping[str, Any]] = {}
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            raise ValueError(f"{key}.{code}.candidate_data_points[{index}] 必须是对象")
        candidate_key = str(candidate.get("data_point_key") or "").strip()
        if not candidate_key:
            raise ValueError(f"{key}.{code}.candidate_data_points[{index}] 缺少 data_point_key")
        if candidate_key in candidates_by_key:
            raise ValueError(f"{key}.{code} 候选数据点键重复：{candidate_key}")
        candidates_by_key[candidate_key] = candidate

    canonical_codes = {str(definition["code"]) for definition in protocol}
    extra_inputs = sorted(set(str(value) for value in explicit_inputs) - canonical_codes)
    if extra_inputs:
        raise ValueError(f"{key}.{code} 使用了非协议指标槽：{extra_inputs}")
    slots: list[dict[str, Any]] = []
    for definition in protocol:
        slot_code = str(definition["code"])
        role = str(definition["role"])
        explicit = explicit_inputs.get(slot_code)
        slot: dict[str, Any] = {
            "slot_code": slot_code,
            "slot_label": str(definition["label"]),
            "metric_name": str(definition["label"]),
            "slot_role": role,
            "slot_weight": float(definition["weight"]),
            "source_refs": [],
            "period": str(item.get("period") or "2026—2030"),
            "as_of_date": str(item.get("as_of_date") or "2026-07-19"),
        }
        if explicit is None:
            slot.update(
                {
                    "value_status": "not_found_after_search",
                    "raw_value_text": "本轮纳入的数据点中没有可直接回答并复算该指标槽的披露。",
                    "standardized_value_text": "不填值，不按零分处理",
                    "preprocess_trace": "缺失保持缺失，并计入覆盖率分母；没有从来源关键词或同因子其他槽继承。",
                    "scoring_trace": (
                        "该槽是背景信息，只展示事实与口径，不进入因子分数、覆盖率或置信度。"
                        if role == "context"
                        else "该槽不参与原始得分，只使因子覆盖率下降并向中性50分收敛。"
                    ),
                }
            )
            if role != "context":
                slot["bucket"] = "证据不足"
        else:
            if not isinstance(explicit, Mapping):
                raise ValueError(f"{key}.{code}.{slot_code} 指标槽输入必须是对象")
            data_point_keys = list(
                dict.fromkeys(str(value).strip() for value in explicit.get("data_point_keys") or [])
            )
            if not data_point_keys or "" in data_point_keys:
                raise ValueError(f"{key}.{code}.{slot_code} 可用槽缺少 data_point_keys")
            missing_keys = [value for value in data_point_keys if value not in candidates_by_key]
            if missing_keys:
                raise ValueError(
                    f"{key}.{code}.{slot_code} 引用了未提供的候选数据点：{missing_keys}"
                )
            selected = [candidates_by_key[value] for value in data_point_keys]
            matched_refs = list(
                dict.fromkeys(str(value.get("source_ref") or "").strip() for value in selected)
            )
            if "" in matched_refs or not matched_refs:
                raise ValueError(f"{key}.{code}.{slot_code} 数据点缺少 source_ref")
            outside_factor = [value for value in matched_refs if value not in source_refs]
            if outside_factor:
                raise ValueError(
                    f"{key}.{code}.{slot_code} 数据点来源不在因子证据中：{outside_factor}"
                )
            unknown_refs = [value for value in matched_refs if value not in sources_by_ref]
            if unknown_refs:
                raise ValueError(f"{key}.{code}.{slot_code} 引用了未知来源：{unknown_refs}")

            raw_num = explicit.get("raw_value_num")
            raw_text = str(explicit.get("raw_value_text") or "").strip()
            if raw_num is None and not raw_text and len(selected) == 1:
                raw_num = selected[0].get("value_num")
                raw_text = str(selected[0].get("value_text") or "").strip()
            if raw_num is None and not raw_text:
                raw_text = "；".join(
                    f"{value.get('data_point_title') or value.get('metric') or value.get('data_point_key')}="
                    f"{value.get('value_text') if value.get('value_text') is not None else value.get('value_num')}"
                    for value in selected
                )
            if raw_num is None and not raw_text:
                raise ValueError(f"{key}.{code}.{slot_code} 缺少原始值")

            raw_units = {
                str(value.get("unit") or "").strip() for value in selected if str(value.get("unit") or "").strip()
            }
            raw_unit = str(explicit.get("raw_unit") or "").strip()
            if not raw_unit and len(raw_units) == 1:
                raw_unit = next(iter(raw_units))
            if not raw_unit:
                raise ValueError(f"{key}.{code}.{slot_code} 缺少明确原始单位")
            standardized_num = explicit.get("standardized_value_num")
            standardized_text = str(explicit.get("standardized_value_text") or "").strip()
            if standardized_num is None and not standardized_text:
                raise ValueError(f"{key}.{code}.{slot_code} 缺少标准化值")
            standardized_unit = str(explicit.get("standardized_unit") or "").strip()
            normalization_method = str(explicit.get("normalization_method") or "").strip()
            bucket = str(explicit.get("bucket") or "").strip()
            scoring_rule = str(explicit.get("scoring_rule") or "").strip()
            if not all((standardized_unit, normalization_method)):
                raise ValueError(
                    f"{key}.{code}.{slot_code} 必须填写 standardized_unit、normalization_method"
                )
            if role == "context":
                if explicit.get("slot_score") is not None:
                    raise ValueError(f"{key}.{code}.{slot_code} context槽不得设置slot_score")
                if bucket or scoring_rule:
                    raise ValueError(
                        f"{key}.{code}.{slot_code} context槽不得设置bucket或scoring_rule"
                    )
                slot_score = None
            else:
                if not all((bucket, scoring_rule)):
                    raise ValueError(
                        f"{key}.{code}.{slot_code} 必须填写 bucket、scoring_rule"
                    )
                slot_score = _finite(
                    explicit.get("slot_score"),
                    name=f"{key}.{code}.{slot_code}.slot_score",
                )
                if not 0 <= slot_score <= 100:
                    raise ValueError(f"{key}.{code}.{slot_code} slot_score 必须位于0到100")
            slot_update = {
                "value_status": str(explicit.get("value_status") or "available"),
                "source_refs": matched_refs,
                "data_point_keys": data_point_keys,
                "data_point_titles": [
                    str(value.get("data_point_title") or value.get("metric") or value.get("data_point_key"))
                    for value in selected
                ],
                "raw_unit": raw_unit,
                "standardized_unit": standardized_unit,
                "unit": standardized_unit,
                "normalization_method": normalization_method,
                "preprocess_trace": str(
                    explicit.get("preprocess_trace")
                    or f"按“{normalization_method}”将原始值标准化为{standardized_text or standardized_num}{standardized_unit}。"
                ),
                "scoring_trace": str(
                    explicit.get("scoring_trace")
                    or (
                        "该槽是背景信息，只展示事实与口径，不进入因子分数、覆盖率或置信度。"
                        if role == "context"
                        else f"标准化值按冻结规则“{scoring_rule}”落入“{bucket}”档，对应{round(slot_score, 2)}分。"
                    )
                ),
            }
            if role != "context":
                slot_update.update(
                    {
                        "slot_score": round(slot_score, 4),
                        "bucket": bucket,
                        "scoring_rule": scoring_rule,
                    }
                )
            slot.update(slot_update)
            if raw_num is not None:
                slot["raw_value_num"] = _finite(
                    raw_num, name=f"{key}.{code}.{slot_code}.raw_value_num"
                )
            else:
                slot["raw_value_text"] = raw_text
            if standardized_num is not None:
                slot["standardized_value_num"] = _finite(
                    standardized_num,
                    name=f"{key}.{code}.{slot_code}.standardized_value_num",
                )
            else:
                slot["standardized_value_text"] = standardized_text
            for field in (
                "extraction_quality_weight",
                "preprocessing_quality_weight",
                "period",
                "as_of_date",
            ):
                if explicit.get(field) is not None:
                    slot[field] = explicit[field]
        slots.append(slot)
    return slots


def _slot_factor_calculation(
    *,
    key: str,
    code: str,
    raw_slots: Sequence[Mapping[str, Any]],
    sources_by_ref: Mapping[str, Mapping[str, Any]],
    audit_multiplier: float,
) -> dict[str, Any]:
    """Build a replayable metric-slot -> factor trace for one factor.

    Text buckets remain researcher classifications rather than external facts,
    but every classification is frozen with the raw evidence, rule and source.
    Missing slots stay missing and reduce coverage; they are never scored zero.
    """

    slots: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_slots):
        slot = copy.deepcopy(dict(raw))
        slot_code = str(slot.get("slot_code") or f"slot_{index + 1}")
        role = str(slot.get("slot_role") or "primary")
        if role not in {"primary", "supporting", "contradiction", "context"}:
            raise ValueError(f"{key}.{code}.{slot_code} slot_role 无效")
        weight = _finite(slot.get("slot_weight", 1.0), name=f"{key}.{code}.{slot_code}.slot_weight")
        if weight <= 0:
            raise ValueError(f"{key}.{code}.{slot_code} slot_weight 必须为正")
        status = str(slot.get("value_status") or "not_found")
        refs = list(dict.fromkeys(str(ref) for ref in slot.get("source_refs") or []))
        unknown = [ref for ref in refs if ref not in sources_by_ref]
        if unknown:
            raise ValueError(f"{key}.{code}.{slot_code} 引用了未知来源：{unknown}")
        usable = status in _USABLE_SLOT_STATUSES
        score_bearing = usable and role != "context"
        score = None
        if role == "context":
            if slot.get("slot_score") is not None:
                raise ValueError(f"{key}.{code}.{slot_code} context槽不得设置slot_score")
            if str(slot.get("bucket") or "").strip() or str(
                slot.get("scoring_rule") or ""
            ).strip():
                raise ValueError(
                    f"{key}.{code}.{slot_code} context槽不得设置bucket或scoring_rule"
                )
            # A context slot is evidence-only.  Do not serialize empty scoring
            # fields: their mere presence made downstream audits and readers
            # treat the slot as if it participated in a score.
            slot.pop("slot_score", None)
            slot.pop("bucket", None)
            slot.pop("scoring_rule", None)
        if usable:
            if not refs:
                raise ValueError(f"{key}.{code}.{slot_code} 可用slot缺少来源")
            data_point_keys = [
                str(value).strip() for value in slot.get("data_point_keys") or []
            ]
            if not data_point_keys or "" in data_point_keys:
                raise ValueError(f"{key}.{code}.{slot_code} 可用slot缺少数据点链接")
            if slot.get("raw_value_num") is None and not str(slot.get("raw_value_text") or "").strip():
                raise ValueError(f"{key}.{code}.{slot_code} 可用slot缺少原始值")
            if slot.get("standardized_value_num") is None and not str(
                slot.get("standardized_value_text") or ""
            ).strip():
                raise ValueError(f"{key}.{code}.{slot_code} 可用slot缺少标准化值")
            for required_field in ("raw_unit", "standardized_unit", "normalization_method"):
                if not str(slot.get(required_field) or "").strip():
                    raise ValueError(
                        f"{key}.{code}.{slot_code} 可用slot缺少 {required_field}"
                    )
            if not str(slot.get("preprocess_trace") or "").strip():
                raise ValueError(f"{key}.{code}.{slot_code} 可用slot缺少完整计算说明")
            if score_bearing:
                score = _finite(slot.get("slot_score"), name=f"{key}.{code}.{slot_code}.slot_score")
                if not 0 <= score <= 100:
                    raise ValueError(f"{key}.{code}.{slot_code} slot_score 必须位于0到100")
                for required_field in ("bucket", "scoring_rule", "scoring_trace"):
                    if not str(slot.get(required_field) or "").strip():
                        raise ValueError(
                            f"{key}.{code}.{slot_code} 可用slot缺少 {required_field}"
                        )

        groups = {
            str(sources_by_ref[ref].get("independence_key") or ref)
            for ref in refs
        }
        source_weight = max((_source_weight(sources_by_ref[ref]) for ref in refs), default=0.0)
        statuses = {
            str(sources_by_ref[ref].get("source_review_status") or "")
            for ref in refs
        }
        freshness_weight = (
            0.50 if "stale" in statuses else 0.75 if "pass_with_note" in statuses else 1.0
        ) if refs else 0.0
        consistency_weight = min(1.0, 0.75 + 0.10 * max(0, len(groups) - 1)) if refs else 0.0
        extraction_quality_weight = _finite(
            slot.get("extraction_quality_weight", 0.90 if slot.get("raw_value_num") is not None else 0.82),
            name=f"{key}.{code}.{slot_code}.extraction_quality_weight",
        )
        preprocessing_quality_weight = _finite(
            slot.get("preprocessing_quality_weight", 0.95 if slot.get("standardized_value_num") is not None else 0.85),
            name=f"{key}.{code}.{slot_code}.preprocessing_quality_weight",
        )
        confidence = (
            source_weight
            * freshness_weight
            * consistency_weight
            * extraction_quality_weight
            * preprocessing_quality_weight
            if usable
            else 0.0
        )
        slot_update = {
            "slot_code": slot_code,
            "slot_role": role,
            "slot_weight": weight,
            "source_refs": refs,
            "evidence_ref_uri_list": [source_uri(ref) for ref in refs],
            "source_count": len(refs),
            "independent_source_count": len(groups),
            "source_weight": round(source_weight, 4),
            "freshness_weight": round(freshness_weight, 4),
            "consistency_weight": round(consistency_weight, 4),
            "extraction_quality_weight": round(extraction_quality_weight, 4),
            "preprocessing_quality_weight": round(preprocessing_quality_weight, 4),
            "slot_confidence": round(confidence, 4),
            "preprocess_trace": str(
                slot.get("preprocess_trace")
                or "保留原始值；按冻结的单位、期间和分类规则标准化；未对缺失值填0。"
            ),
            "scoring_trace": str(
                slot.get("scoring_trace")
                or (
                    "该槽只展示背景事实，不进入因子分数、覆盖率或置信度。"
                    if role == "context"
                    else "按本slot冻结的bucket与规则生成slot_score；该bucket是研究者编码，不是外部事实。"
                )
            ),
        }
        if role != "context":
            slot_update["slot_score"] = score
        slot.update(slot_update)
        slots.append(slot)

    applicable = [
        slot
        for slot in slots
        if slot["value_status"] != "not_applicable" and slot["slot_role"] != "context"
    ]
    applicable_weight = sum(float(slot["slot_weight"]) for slot in applicable)
    usable_slots = [slot for slot in applicable if slot["value_status"] in _USABLE_SLOT_STATUSES]
    usable_weight = sum(float(slot["slot_weight"]) for slot in usable_slots)
    coverage = usable_weight / applicable_weight if applicable_weight else 0.0
    confidence = (
        sum(float(slot["slot_confidence"]) * float(slot["slot_weight"]) for slot in usable_slots)
        / usable_weight
        if usable_weight
        else 0.0
    )

    primary = [slot for slot in usable_slots if slot["slot_role"] == "primary"]
    supporting = [slot for slot in usable_slots if slot["slot_role"] == "supporting"]
    contradictions = [slot for slot in usable_slots if slot["slot_role"] == "contradiction"]

    def weighted_score(rows: Sequence[Mapping[str, Any]]) -> float | None:
        total = sum(float(row["slot_weight"]) for row in rows)
        if not total:
            return None
        return sum(float(row["slot_score"]) * float(row["slot_weight"]) for row in rows) / total

    primary_score = weighted_score(primary)
    support_score = weighted_score(supporting)
    contradiction_score = weighted_score(contradictions)
    if primary_score is None:
        if len(supporting) >= 2 and support_score is not None:
            primary_component = min(support_score, 65.0)
        else:
            primary_component = 50.0
    else:
        primary_component = primary_score
    support_adjustment = (
        max(-8.0, min(8.0, (support_score - 50.0) * 0.16))
        if support_score is not None
        else 0.0
    )
    contradiction_penalty = (
        max(0.0, min(20.0, (50.0 - contradiction_score) * 0.20))
        if contradiction_score is not None
        else 0.0
    )
    score_raw = max(0.0, min(100.0, primary_component + support_adjustment - contradiction_penalty))
    coverage_mult = _coverage_multiplier(coverage)
    confidence_mult = _confidence_multiplier(confidence)
    reliability = min(coverage_mult, confidence_mult, audit_multiplier)
    score_adjusted = 50.0 + (score_raw - 50.0) * reliability

    if coverage < 0.50:
        readiness = "missing"
        score_status = "insufficient_evidence"
    elif coverage < 0.65 or confidence < 0.60:
        readiness = "limited"
        score_status = "complete"
    else:
        readiness = "ready"
        score_status = "complete"
    return {
        "metric_slots": slots,
        "score_raw": round(score_raw, 4),
        "score_adjusted": round(score_adjusted, 4),
        "coverage": round(coverage, 4),
        "confidence": round(confidence, 4),
        "factor_readiness_status": readiness,
        "score_status": score_status,
        "missing_reason": summarize_missing_metric_slots(slots),
        "aggregation_trace": {
            "primary_score": None if primary_score is None else round(primary_score, 4),
            "support_adjustment": round(support_adjustment, 4),
            "event_adjustment": 0.0,
            "contradiction_penalty": round(contradiction_penalty, 4),
            "formula": "raw=primary_component+support_adjustment-contradiction_penalty",
        },
        "adjustment_trace": {
            "coverage_multiplier": coverage_mult,
            "confidence_multiplier": confidence_mult,
            "audit_multiplier": audit_multiplier,
            "factor_reliability_multiplier": reliability,
            "formula": "adjusted=50+(raw-50)×min(coverage_multiplier,confidence_multiplier,audit_multiplier)",
        },
    }


def build_segment_entity(
    specification: Mapping[str, Any],
    *,
    sources_by_ref: Mapping[str, Mapping[str, Any]],
    as_of_date: str,
) -> dict[str, Any]:
    """Build one complete ten-factor segment entity from human-written inputs."""
    key = str(specification["key"])
    factor_inputs = specification.get("factor_inputs") or {}
    missing = sorted(set(SEGMENT_FACTOR_CODES) - set(factor_inputs))
    extra = sorted(set(factor_inputs) - set(SEGMENT_FACTOR_CODES))
    if missing or extra:
        raise ValueError(f"{key} 因子集合不完整：missing={missing}, extra={extra}")

    factors: list[dict[str, Any]] = []
    entity_refs: list[str] = []
    for code in SEGMENT_FACTOR_CODES:
        item = dict(factor_inputs[code])
        refs = list(dict.fromkeys(str(ref) for ref in item.get("source_refs") or []))
        if len(refs) < 5:
            raise ValueError(f"{key}.{code} 至少需要 5 个来源引用")
        groups = {
            str(sources_by_ref[ref].get("independence_key") or "")
            for ref in refs
            if ref in sources_by_ref
        }
        if len(groups - {""}) < 5:
            raise ValueError(f"{key}.{code} 至少需要 5 个独立证据组")
        unknown = [ref for ref in refs if ref not in sources_by_ref]
        if unknown:
            raise ValueError(f"{key}.{code} 引用了未知来源：{unknown}")

        if not item.get("metric_slots"):
            expert_bucket_score = _finite(
                item.get("expert_bucket_score", item.get("score_raw")),
                name=f"{key}.{code}.expert_bucket_score",
            )
            item["metric_slots"] = _protocol_metric_slots(
                key=key,
                code=code,
                expert_bucket_score=expert_bucket_score,
                source_refs=refs,
                sources_by_ref=sources_by_ref,
                item=item,
            )
            item["score_input_kind"] = "researcher_bucket_classification_not_external_fact"
        slot_calculation = _slot_factor_calculation(
            key=key,
            code=code,
            raw_slots=list(item["metric_slots"]),
            sources_by_ref=sources_by_ref,
            audit_multiplier=_finite(
                item.get("audit_multiplier", 1.0),
                name=f"{key}.{code}.audit_multiplier",
            ),
        )
        item.update(slot_calculation)

        score_raw = _finite(item["score_raw"], name=f"{key}.{code}.score_raw")
        score_adjusted = _finite(
            item.get("score_adjusted", score_raw),
            name=f"{key}.{code}.score_adjusted",
        )
        coverage = _finite(item.get("coverage", 0.80), name=f"{key}.{code}.coverage")
        confidence = _finite(item.get("confidence", 0.76), name=f"{key}.{code}.confidence")
        if not 0 <= score_raw <= 100 or not 0 <= score_adjusted <= 100:
            raise ValueError(f"{key}.{code} 分数必须位于 0 到 100")
        if not 0 <= coverage <= 1 or not 0 <= confidence <= 1:
            raise ValueError(f"{key}.{code} 覆盖率和置信度必须位于 0 到 1")

        label = next(factor.label for factor in SEGMENT_FACTORS if factor.code == code)
        summary = str(item["factor_value_summary"]).strip()
        source_context = str(item["source_context_summary"]).strip()
        topic_analysis = str(item["factor_topic_analysis"]).strip()
        rationale = str(item["score_rationale"]).strip()
        themes = [str(value).strip() for value in item.get("theme_analysis_points") or [] if str(value).strip()]
        if min(map(len, (summary, source_context, topic_analysis, rationale)), default=0) < 20:
            raise ValueError(f"{key}.{code} 的人读分析过短")
        if len(themes) < 2 or len(set(themes)) != len(themes):
            raise ValueError(f"{key}.{code} 至少需要两条不重复分析要点")

        interpretations = item.get("evidence_interpretations") or {}
        information_point_overrides = item.get("evidence_information_points") or {}
        unknown_override_refs = set(information_point_overrides) - set(refs)
        if unknown_override_refs:
            raise ValueError(
                f"{key}.{code} 的证据摘录覆盖引用了未绑定来源："
                f"{sorted(unknown_override_refs)}"
            )
        information_points: list[dict[str, Any]] = []
        for ref in refs:
            source = sources_by_ref[ref]
            point_override = information_point_overrides.get(ref) or {}
            excerpt = str(
                point_override.get("excerpt")
                or source.get("excerpt")
                or source.get("excerpt_zh")
                or ""
            ).strip()
            excerpt_zh = str(
                point_override.get("excerpt_zh")
                or source.get("excerpt_zh")
                or ""
            ).strip()
            if not excerpt:
                raise ValueError(f"{key}.{code}.{ref} 缺少可展示的来源原文")
            language = str(source.get("language") or "").strip().lower()
            show_translation = (
                bool(excerpt_zh)
                and excerpt_zh != excerpt
                and language not in {"zh", "zh-cn", "zh-tw", "chinese", "中文"}
            )
            interpretation = str(interpretations.get(ref) or "").strip()
            if not interpretation:
                interpretation = (
                    f"这份资料在“{label}”判断中用于核对{summary.rstrip('。')}；"
                    f"它只约束{source.get('title_zh') or source.get('title')}所覆盖的事实，"
                    "不能单独替代其他客户、地区或时期的证据。"
                )
            information_point = {
                "evidence_ref": source_uri(ref),
                "excerpt": excerpt,
                "interpretation": interpretation,
            }
            if show_translation:
                information_point["excerpt_zh"] = excerpt_zh
            information_points.append(information_point)
        factor = {
            "factor_code": code,
            "metric_name": str(item.get("metric_name") or label),
            "period": str(item.get("period") or as_of_date),
            "as_of_date": str(item.get("as_of_date") or as_of_date),
            "unit": str(item.get("unit") or "分"),
            "score_raw": score_raw,
            "score_adjusted": score_adjusted,
            "coverage": coverage,
            "confidence": confidence,
            "score_rationale": rationale,
            "factor_value_summary": summary,
            "source_context_summary": source_context,
            "factor_topic_analysis": topic_analysis,
            "theme_analysis_points": themes,
            "evidence_ref_uri_list": [source_uri(ref) for ref in refs],
            "information_points": information_points,
            "factor_readiness_status": str(item.get("factor_readiness_status") or "ready"),
            "score_status": str(item.get("score_status") or "complete"),
            "missing_reason": str(
                item.get("missing_reason")
                or slot_calculation.get("missing_reason")
                or ""
            ),
            "notes": str(item.get("notes") or topic_analysis),
            "score_input_kind": str(
                item.get("score_input_kind")
                or "explicit_metric_slot_inputs"
            ),
        }
        factor["metric_slots"] = slot_calculation["metric_slots"]
        factor["aggregation_trace"] = slot_calculation["aggregation_trace"]
        factor["adjustment_trace"] = slot_calculation["adjustment_trace"]
        factors.append(factor)
        entity_refs.extend(refs)

    total_weight = sum(factor_weight(item["factor_code"]) for item in factors)
    score_point = sum(
        item["score_adjusted"] * factor_weight(item["factor_code"])
        for item in factors
    ) / total_weight
    coverage = sum(
        item["coverage"] * factor_weight(item["factor_code"])
        for item in factors
    ) / total_weight
    confidence = sum(
        item["confidence"] * factor_weight(item["factor_code"])
        for item in factors
    ) / total_weight
    band_half_width = max(5.0, 18.0 * (1.0 - confidence))
    score_point = round(score_point, 2)
    limited_count = sum(
        1 for factor in factors if factor["factor_readiness_status"] != "ready"
    )
    insufficient_entity = coverage < 0.50
    rating_status = (
        "unrated_insufficient_evidence"
        if insufficient_entity
        else ("review_required" if limited_count else "valid")
    )
    return {
        "key": key,
        "canonical_name": str(specification["canonical_name"]),
        "display_name": str(specification.get("display_name") or specification["canonical_name"]),
        "entity_type": "segment",
        "taxonomy_level": "segment",
        "description": str(specification["description"]),
        "entity_research_mode": "market_linked",
        "score_point": score_point,
        "score_band_low": round(max(0.0, score_point - band_half_width), 2),
        "score_band_high": round(min(100.0, score_point + band_half_width), 2),
        "coverage": round(coverage, 4),
        "confidence": round(confidence, 4),
        "score_status": "insufficient_evidence" if insufficient_entity else "complete",
        **({"score_grade": "unrated"} if insufficient_entity else {}),
        "score_quality_label": str(
            specification.get("score_quality_label")
            or (
                "unrated_insufficient_evidence"
                if insufficient_entity
                else ("provisional" if limited_count else "medium_confidence")
            )
        ),
        "band_method": "按因子证据覆盖度与置信度设置对称认知区间",
        "band_reason": str(
            specification.get("band_reason")
            or "分数比较当前研究优先级，不代表收益率预测；公开资料缺口通过区间而不是补造数字处理。"
        ),
        "research_bias_label": str(
            specification.get("research_bias_label")
            or (
                "unrated_insufficient_evidence"
                if insufficient_entity
                else ("neutral_watch" if limited_count else "positive_research")
            )
        ),
        "rating_status": rating_status,
        "missing_factor_count": sum(
            1 for factor in factors if factor["factor_readiness_status"] == "missing"
        ),
        "weak_source_factor_count": sum(
            1 for factor in factors if factor["confidence"] < 0.60
        ),
        "conflict_factor_count": 0,
        "why_not_full_score": (
            "部分因子缺少可用指标槽或置信度不足，已按协议向中性50收敛。"
            if limited_count
            else "所有因子均达到当前评分覆盖与置信门槛。"
        ),
        "evidence_ref_uri_list": [source_uri(ref) for ref in dict.fromkeys(entity_refs)],
        "source_count": len(set(entity_refs)),
        "independent_source_count": len(
            {
                sources_by_ref[ref]["independence_key"]
                for ref in set(entity_refs)
            }
        ),
        "factor_scores": factors,
        "composite_trace": {
            "calculation": "综合分=十个适用因子按活动因子字典权重加权平均。",
            "use": "只用于比较研究优先级；不替代需求量、订单额、盈利或估值测算。",
            "factor_components": [
                {
                    "factor_code": item["factor_code"],
                    "weight": factor_weight(item["factor_code"]),
                    "score_adjusted": item["score_adjusted"],
                    "weighted_contribution": round(
                        item["score_adjusted"]
                        * factor_weight(item["factor_code"])
                        / total_weight,
                        6,
                    ),
                }
                for item in factors
            ],
        },
    }


def render_report(pack: Mapping[str, Any]) -> str:
    lines = [f"# {pack['display_title']}", ""]
    problem = str(pack.get("problem_statement") or "").strip()
    if problem:
        lines.extend([problem, ""])
    for section in pack.get("sections") or []:
        lines.extend([f"## {section['section_title']}", "", str(section["body_markdown"]).strip(), ""])
    return "\n".join(lines).rstrip() + "\n"


def line_chart_panel(
    *,
    title: str,
    unit: str,
    series: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    periods = [str(row["period"]) for item in series for row in item["observations"]]
    ordered_periods = list(dict.fromkeys(periods))
    values = [float(row["value"]) for item in series for row in item["observations"]]
    if len(ordered_periods) < 2 or not values:
        raise ValueError("折线图至少需要两个时期和一组数值")
    low = min(values)
    high = max(values)
    margin = max((high - low) * 0.08, abs(high) * 0.02, 1e-6)
    y_min = low - margin
    y_max = high + margin
    span = y_max - y_min
    colors = ("#2563eb", "#dc2626", "#0f766e", "#7c3aed", "#d97706")
    chart_series: list[dict[str, Any]] = []
    period_index = {period: index for index, period in enumerate(ordered_periods)}
    for index, item in enumerate(series):
        points: list[str] = []
        observations = list(item["observations"])
        for row in observations:
            x_index = period_index[str(row["period"])]
            x = x_index / (len(ordered_periods) - 1) * 100
            y = (y_max - float(row["value"])) / span * 100
            points.append(f"{x:.2f},{y:.2f}")
        latest = observations[-1]
        chart_series.append(
            {
                "label": str(item["label"]),
                "color": str(item.get("color") or colors[index % len(colors)]),
                "svg_points": " ".join(points),
                "observation_count": len(observations),
                "latest_period": str(latest["period"]),
                "latest_value": f"{float(latest['value']):,.2f}{unit}",
            }
        )
    midpoint = (y_min + y_max) / 2
    return {
        "title": title,
        "unit": unit,
        "axis_mode": "sequence",
        "x_axis_label": "横轴：年份",
        "y_axis_label": f"纵轴：{unit}",
        "x_ticks": [
            {"position": 0, "label": ordered_periods[0]},
            {"position": 50, "label": ordered_periods[len(ordered_periods) // 2]},
            {"position": 100, "label": ordered_periods[-1]},
        ],
        "y_ticks": [
            {"position": 0, "label": f"{y_max:,.1f}"},
            {"position": 50, "label": f"{midpoint:,.1f}"},
            {"position": 100, "label": f"{y_min:,.1f}"},
        ],
        "x_start": ordered_periods[0],
        "x_end": ordered_periods[-1],
        "y_min": f"{y_min:.4f}",
        "y_max": f"{y_max:.4f}",
        "series": chart_series,
    }


def build_line_visual(
    *,
    block_key: str,
    title: str,
    subtitle: str,
    how_to_read: str,
    analysis: str,
    panels: Sequence[Mapping[str, Any]],
    print_columns: Sequence[str],
    print_rows: Sequence[Sequence[Any]],
    source_refs: Iterable[str],
    sort_order: int = 500,
) -> dict[str, Any]:
    return {
        "block_key": block_key,
        "block_type": "line_chart",
        "title": title,
        "subtitle": subtitle,
        "data": {
            "what": title,
            "how_to_read": how_to_read,
            "analysis": analysis,
            "chart": {"panels": list(panels)},
        },
        "print_fallback": {"columns": list(print_columns), "rows": [list(row) for row in print_rows]},
        "evidence_ref_uri_list": [source_uri(ref) for ref in source_refs],
        "support_status": "partially_supported",
        "red_flag_level": "none",
        "sort_order": sort_order,
    }


def validate_research_pack_inputs(pack: Mapping[str, Any]) -> dict[str, Any]:
    identities: set[tuple[str, str, str, str, str]] = set()
    duplicates: list[tuple[str, str, str, str, str]] = []
    for point in pack.get("data_points") or []:
        identity = (
            str(point.get("source_ref") or ""),
            str(point.get("entity_key") or ""),
            "".join(str(point.get("metric") or "").lower().split()),
            "".join(str(point.get("unit") or "").lower().split()),
            "".join(str(point.get("scope_key") or point.get("series_key") or "").lower().split()),
        )
        if identity in identities:
            duplicates.append(identity)
        identities.add(identity)
    if len(identities) < 100:
        raise ValueError(f"平行数据点不足 100：{len(identities)}")
    if duplicates:
        raise ValueError(f"数据点身份重复：{duplicates[:5]}")
    section_lengths = {
        str(section.get("section_key")): len(str(section.get("body_markdown") or ""))
        for section in pack.get("sections") or []
    }
    entity_lengths = {
        str(section.get("entity_key")): len(str(section.get("body_markdown") or ""))
        for section in pack.get("entity_sections") or []
    }
    if not section_lengths or min(section_lengths.values()) < 1400:
        raise ValueError("深度研究主章节必须逐节不少于 1400 字符")
    if len(entity_lengths) != len(pack.get("entities") or []) or min(entity_lengths.values()) < 2200:
        raise ValueError("每个研究实体必须有不少于 2200 字符的独立正文")
    return {
        "unique_parallel_data_points": len(identities),
        "section_lengths": section_lengths,
        "entity_section_lengths": entity_lengths,
        "source_count": len(pack.get("sources") or []),
        "entity_count": len(pack.get("entities") or []),
        "factor_count": sum(len(entity.get("factor_scores") or []) for entity in pack.get("entities") or []),
        "target_count": len(pack.get("entity_investment_targets") or []),
    }


def write_pack_bundle(
    pack: dict[str, Any],
    *,
    output_dir: Path,
    audit_profile: str = "auto",
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    pack_path = output_dir / "run_pack.json"
    report_path = output_dir / "final_report.md"
    validation_path = output_dir / "validation_stage.json"
    audit_json_path = output_dir / "public_content_quality_audit.json"
    audit_markdown_path = output_dir / "public_content_quality_audit.md"
    summary_path = output_dir / "build_summary.json"

    metrics = validate_research_pack_inputs(pack)
    report = validate_run_pack(pack, publication_mode="stage")
    report.raise_for_errors()
    report_text = render_report(pack)
    pack[PUBLIC_AUDIT_FIELD] = build_pack_audit_attestation(pack, profile=audit_profile)
    write_json(pack_path, pack)
    write_json(validation_path, report.as_dict())
    report_path.write_text(report_text, encoding="utf-8")
    public_audit = run_public_content_audit(
        run_pack_path=pack_path,
        report_path=report_path,
        profile=audit_profile,
    )
    write_json(audit_json_path, public_audit)
    audit_markdown_path.write_text(
        render_public_content_audit_markdown(public_audit),
        encoding="utf-8",
    )
    if public_audit["status"] != "PASS":
        raise ValueError(
            "公开内容质量审计失败："
            f"errors={public_audit['summary']['errors']}，详见 {audit_json_path}"
        )
    write_json(
        summary_path,
        {
            **metrics,
            "pack_schema_version": RUN_PACK_SCHEMA_VERSION,
            "workflow_contract_version": RESEARCH_WORKFLOW_CONTRACT_VERSION,
            "stage_validation_valid": report.valid,
            "stage_validation_warnings": len(report.warnings),
            "pack_path": str(pack_path),
            "report_path": str(report_path),
            "pack_sha256": sha256_file(pack_path),
            "report_sha256": sha256_file(report_path),
            "public_content_audit_status": public_audit["status"],
            "public_content_audit_result_sha256": pack[PUBLIC_AUDIT_FIELD]["result_sha256"],
        },
    )
    return pack_path
