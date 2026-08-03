from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from tools.financial.constants import MODEL_SKILLS
from tools.research_core.config import contract_version, publish_review_stages, resolve_track_config

from .factor_dictionary import FACTOR_BY_CODE
from .intake_parser import parse_intake_payload


PACK_SCHEMA_V2 = str(resolve_track_config("c")["pack_schema_version"])
LEGACY_PACK_SCHEMA = "opportunity_lens.run_pack.legacy"
SOURCE_REF_RE = re.compile(r"^source_ref:([A-Za-z0-9_.-]+)$")
PUBLIC_URL_RE = re.compile(r"https?://")
PUBLIC_MACHINE_MARKERS = ("opp://source/", "source_ref:", "原文地址：", "原文地址:", "本地底稿：", "本地底稿:", "原始 JSON")
PUBLIC_SECTION_STRUCTURE_CONTRACT = (
    "public.problem_method_data_analysis_summary.v1"
)
PUBLIC_SECTION_HEADINGS = (
    "问题",
    "研究方法与数据",
    "研究与分析",
    "总结",
)
SUPPLEMENT_PRIORITY_VALUES = frozenset({"p0", "p1", "p2", "p3"})
SUPPLEMENT_BLOCKING_STATUS_VALUES = frozenset(
    {
        "blocks_scoring",
        "limits_scoring",
        "blocks_publication",
        "non_blocking",
        "unknown_pending_review",
    }
)
SUPPLEMENT_REVIEW_STATUS_VALUES = frozenset(
    {
        "pending",
        "in_review",
        "approved",
        "rejected",
        "resolved",
        "waived",
        "reopened",
        "not_required",
    }
)
ENTITY_TYPE_VALUES = frozenset(
    {
        "theme",
        "industry",
        "segment",
        "product_material",
        "process_step",
        "application",
        "customer",
        "company",
        "security",
        "geography",
    }
)
ENTITY_MATURATION_STATUS_VALUES = frozenset(
    {
        "seed", "evidence_supported", "scoring_ready", "scoring_limited",
        "research_only", "scored", "review_ready", "published", "blocked",
        "superseded", "rejected", "archived",
    }
)
RESEARCH_PRIORITY_LABEL_VALUES = frozenset(
    {
        "high_priority_for_scoring", "medium_priority_for_followup",
        "low_priority_watch", "research_only_insufficient_data",
        "research_only_literature_review_complete", "reject_or_out_of_scope",
    }
)
SCORE_GRADE_VALUES = frozenset({"S", "A", "B", "C", "D", "F", "unrated"})
SCORE_QUALITY_LABEL_VALUES = frozenset(
    {
        "high_confidence", "medium_confidence", "provisional",
        "unrated_insufficient_evidence", "review_required",
    }
)
TEMPLATE_PHRASES = (
    "它不是孤立数字",
    "在这个问题下，该指标说明",
    "该证据必须结合原始链接全文",
    "manual_verified_fact",
    "行业事实原文证据",
    "如果想进一步研究，需要补充的信息",
)
MACHINE_LABEL_PATTERNS = (
    re.compile(r"manual_verified_fact", re.IGNORECASE),
    re.compile(r"time_series_data_point", re.IGNORECASE),
    re.compile(r"(?:行业事实|客户验证和供货进展|材料和工艺瓶颈)原文证据"),
    re.compile(r"原文证据\s*\d+"),
    re.compile(r"这是\s*Opportunity Lens\s*来源记录", re.IGNORECASE),
    re.compile(r"^\s*[\[{].*\"kind\"\s*:", re.DOTALL),
)

DUPLICATION_ISSUE_CODES = {
    "source_ref_duplicate", "entity_key_duplicate", "data_identity_duplicate",
    "theory_interpretation_duplicate", "theory_use_duplicate",
    "target_field_duplicate", "template_phrase", "machine_label",
    "factor_rationale_duplicate",
}
PROVENANCE_ISSUE_CODES = {
    "source_ref_empty", "source_locator_missing", "independence_key_missing",
    "independence_rationale_missing", "data_source_unknown",
    "factor_independence_unresolved", "target_evidence_unknown", "review_artifact_hash",
    "evidence_ref_format", "evidence_ref_unknown", "source_channel_missing", "search_channel_isolation",
}
EVIDENCE_ISSUE_CODES = {
    "source_field_empty", "source_translation_missing", "data_field_empty",
    "data_time_empty", "data_value_empty", "data_value_non_finite",
    "parallel_data_points", "factor_evidence_groups", "theory_profile_field",
    "theory_ledger_count", "theory_ledger_field", "target_data_points",
    "target_data_point_field", "target_data_point_value", "factor_field_empty",
    "factor_score_range", "factor_information_point", "claim_field_empty",
    "composite_score_range", "metric_slot_chain", "metric_slot_coverage",
}
SCOPE_ISSUE_CODES = {
    "entity_mode", "theory_has_scores", "theory_has_target",
    "market_scores_missing", "market_target_missing", "target_entity_unknown",
    "entity_section_unknown", "entity_section_missing", "data_scope_missing",
    "entity_field_empty", "entity_type_enum", "entity_state_enum",
    "data_entity_unknown", "claim_entity_unknown",
}


def gate_for_issue_code(code: str) -> str:
    if code in DUPLICATION_ISSUE_CODES:
        return "duplication"
    if code in PROVENANCE_ISSUE_CODES:
        return "provenance"
    if code in EVIDENCE_ISSUE_CODES:
        return "evidence_integrity"
    if code in SCOPE_ISSUE_CODES:
        return "scope_and_units"
    return "contract"


@dataclass(frozen=True)
class ContractIssue:
    code: str
    severity: str
    path: str
    message: str


@dataclass
class PackValidationReport:
    pack_schema_version: str
    workflow_contract_version: str | None
    publication_mode: str
    issues: list[ContractIssue] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def blockers(self) -> list[ContractIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[ContractIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def valid(self) -> bool:
        return not self.blockers

    def as_dict(self) -> dict[str, Any]:
        return {
            "pack_schema_version": self.pack_schema_version,
            "workflow_contract_version": self.workflow_contract_version,
            "publication_mode": self.publication_mode,
            "valid": self.valid,
            "issues": [asdict(issue) for issue in self.issues],
            "metrics": self.metrics,
        }

    def raise_for_errors(self) -> None:
        if self.blockers:
            detail = "\n".join(f"[{x.code}] {x.path}: {x.message}" for x in self.blockers[:80])
            raise ValueError(f"Opportunity Lens run pack 契约校验失败，共 {len(self.blockers)} 项:\n{detail}")


def _text(value: Any) -> str:
    return str(value or "").strip()


def public_markdown_character_count(value: Any) -> int:
    """Count reader-visible characters, excluding Markdown transport syntax.

    Homepage length limits describe the amount a researcher reads.  Internal
    route targets, evidence tokens and Markdown table/heading markers must not
    consume that budget, otherwise adding a correct company link can make an
    unchanged sentence fail the gate.
    """

    plain = _text(value)
    plain = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", plain)
    plain = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", plain)
    plain = re.sub(r"\^src:source_ref:[A-Za-z0-9_.-]+", "", plain)
    plain = re.sub(r"<[^>]+>", "", plain)
    return sum(
        len(token)
        for token in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", plain)
    )


def _normal(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", _text(value).lower())


def _list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _validate_source_ref_uris(
    report: PackValidationReport,
    refs: Any,
    *,
    path: str,
    source_groups: dict[str, str | None],
    required: bool = False,
) -> None:
    values = [_text(value) for value in _list(refs) if _text(value)]
    if required and not values:
        report.issues.append(ContractIssue("evidence_ref_format", "error", path, "证据索引不能为空"))
        return
    for index, ref in enumerate(values):
        match = SOURCE_REF_RE.fullmatch(ref)
        if not match:
            report.issues.append(ContractIssue(
                "evidence_ref_format",
                "error",
                f"{path}[{index}]",
                "V2 run pack 内部证据必须使用 source_ref:<ref>，不得写裸 URL、opp:// 或任意字符串",
            ))
        elif match.group(1) not in source_groups:
            report.issues.append(ContractIssue(
                "evidence_ref_unknown",
                "error",
                f"{path}[{index}]",
                f"未知 source_ref: {match.group(1)}",
            ))


def _validate_human_field(report: PackValidationReport, value: Any, *, path: str) -> None:
    text = _text(value)
    if not text:
        return
    for pattern in MACHINE_LABEL_PATTERNS:
        if pattern.search(text):
            report.issues.append(ContractIssue(
                "machine_label",
                "error",
                path,
                "人读字段包含机器标签、过程标签或原始结构，必须改写为具体业务含义",
            ))
            return


def entity_research_mode(entity: dict[str, Any], *, legacy: bool = False) -> str:
    canonical = _text(entity.get("entity_research_mode"))
    if canonical in {"market_linked", "theory_research"}:
        return canonical
    if legacy:
        raw = _text(
            entity.get("research_entity_type")
            or entity.get("entity_mode")
            or entity.get("mode")
            or canonical
            or "market_linked"
        ).lower()
        if raw in {"theory", "research", "research_only", "theoretical", "lit_review", "literature_review"}:
            return "theory_research"
        return "market_linked"
    raise ValueError("entity_research_mode 必须显式为 market_linked 或 theory_research")


def _factor_score(factor: dict[str, Any]) -> float:
    try:
        return float(factor.get("score_adjusted", factor.get("score_raw", 0)) or 0)
    except (TypeError, ValueError):
        return 0.0


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


_USABLE_METRIC_SLOT_STATUSES = {"available", "calculated", "stale_but_usable"}


def _validate_metric_slot_chain(
    report: PackValidationReport,
    factor: dict[str, Any],
    *,
    path: str,
    data_point_keys: set[str],
    source_groups: dict[str, str | None],
) -> None:
    """Require a replayable data-point -> normalization -> bucket -> score chain."""

    slots = factor.get("metric_slots")
    if slots is None:
        return
    if not isinstance(slots, list) or not slots:
        report.issues.append(
            ContractIssue("metric_slot_chain", "error", f"{path}.metric_slots", "指标槽必须是非空数组")
        )
        return
    seen_codes: set[str] = set()
    applicable_weight = 0.0
    usable_weight = 0.0
    for index, slot in enumerate(slots):
        slot_path = f"{path}.metric_slots[{index}]"
        if not isinstance(slot, dict):
            report.issues.append(ContractIssue("metric_slot_chain", "error", slot_path, "指标槽必须是对象"))
            continue
        code = _text(slot.get("slot_code") or slot.get("slot_key"))
        if not code or code in seen_codes:
            report.issues.append(
                ContractIssue("metric_slot_chain", "error", f"{slot_path}.slot_code", "指标槽代码不能为空或重复")
            )
        seen_codes.add(code)
        weight = _finite_number(slot.get("slot_weight"))
        if weight is None or weight <= 0:
            report.issues.append(
                ContractIssue("metric_slot_chain", "error", f"{slot_path}.slot_weight", "指标槽权重必须是正有限数")
            )
            continue
        value_status = _text(slot.get("value_status") or "not_found_after_search")
        role = _text(slot.get("slot_role") or "primary")
        if role not in {"primary", "supporting", "contradiction", "context"}:
            report.issues.append(
                ContractIssue("metric_slot_chain", "error", f"{slot_path}.slot_role", "指标槽角色无效")
            )
        if role == "context":
            for field_name in ("slot_score", "bucket", "scoring_rule"):
                if field_name in slot:
                    report.issues.append(
                        ContractIssue(
                            "metric_slot_chain",
                            "error",
                            f"{slot_path}.{field_name}",
                            "背景指标槽只展示事实，不得包含任何评分字段",
                        )
                    )
            if not _text(slot.get("scoring_trace")):
                report.issues.append(
                    ContractIssue(
                        "metric_slot_chain",
                        "error",
                        f"{slot_path}.scoring_trace",
                        "背景指标槽必须明确说明不进入评分、覆盖率或置信度",
                    )
                )
        if value_status != "not_applicable" and role != "context":
            applicable_weight += weight
        usable = value_status in _USABLE_METRIC_SLOT_STATUSES
        if usable:
            if role != "context":
                usable_weight += weight
            keys = [_text(value) for value in _list(slot.get("data_point_keys")) if _text(value)]
            if not keys:
                report.issues.append(
                    ContractIssue("metric_slot_chain", "error", f"{slot_path}.data_point_keys", "可用指标槽必须明确链接数据点键")
                )
            unknown_keys = [key for key in keys if key not in data_point_keys]
            if unknown_keys:
                report.issues.append(
                    ContractIssue("metric_slot_chain", "error", f"{slot_path}.data_point_keys", f"指标槽引用未知数据点键：{unknown_keys}")
                )
            refs = [_text(value).removeprefix("source_ref:") for value in _list(slot.get("source_refs")) if _text(value)]
            if not refs or any(ref not in source_groups for ref in refs):
                report.issues.append(
                    ContractIssue("metric_slot_chain", "error", f"{slot_path}.source_refs", "可用指标槽必须绑定已登记来源")
                )
            raw_present = _finite_number(slot.get("raw_value_num")) is not None or bool(_text(slot.get("raw_value_text")))
            standardized_present = _finite_number(slot.get("standardized_value_num")) is not None or bool(
                _text(slot.get("standardized_value_text"))
            )
            if not raw_present:
                report.issues.append(ContractIssue("metric_slot_chain", "error", slot_path, "可用指标槽缺少原始值"))
            if not standardized_present:
                report.issues.append(ContractIssue("metric_slot_chain", "error", slot_path, "可用指标槽缺少标准化值"))
            for field_name in ("raw_unit", "standardized_unit", "normalization_method", "preprocess_trace"):
                if not _text(slot.get(field_name)):
                    report.issues.append(
                        ContractIssue("metric_slot_chain", "error", f"{slot_path}.{field_name}", "可用指标槽的复算链字段不能为空")
                    )
            if role != "context":
                for field_name in ("bucket", "scoring_rule", "scoring_trace"):
                    if not _text(slot.get(field_name)):
                        report.issues.append(
                            ContractIssue("metric_slot_chain", "error", f"{slot_path}.{field_name}", "评分指标槽的复算链字段不能为空")
                        )
                score = _finite_number(slot.get("slot_score"))
                if score is None or not 0 <= score <= 100:
                    report.issues.append(
                        ContractIssue("metric_slot_chain", "error", f"{slot_path}.slot_score", "可用指标槽分数必须是0~100的有限数")
                    )
        elif slot.get("slot_score") is not None:
            report.issues.append(
                ContractIssue("metric_slot_chain", "error", f"{slot_path}.slot_score", "缺失或不可用指标槽不得保留分数")
            )
    calculated_coverage = usable_weight / applicable_weight if applicable_weight else 0.0
    declared_coverage = _finite_number(factor.get("coverage"))
    if declared_coverage is None or abs(calculated_coverage - declared_coverage) > 0.00011:
        report.issues.append(
            ContractIssue(
                "metric_slot_coverage",
                "error",
                f"{path}.coverage",
                f"因子覆盖率必须由可用槽权重/适用槽权重复算；应为{calculated_coverage:.4f}，当前为{factor.get('coverage')!r}",
            )
        )
    if calculated_coverage < 0.50 and _text(factor.get("score_status")) == "complete":
        report.issues.append(
            ContractIssue("metric_slot_coverage", "error", f"{path}.score_status", "覆盖率低于50%时不得标为完整评分")
        )


def _factor_refs(factor: dict[str, Any], *, entity: dict[str, Any], legacy: bool) -> list[str]:
    values: list[Any] = []
    for key in ("evidence_ref_uri_list", "source_context_refs", "evidence_ref_uri"):
        values.extend(_list(factor.get(key)))
    for key in ("information_points", "evidence_items"):
        for item in _list(factor.get(key)):
            if isinstance(item, dict):
                values.append(item.get("evidence_ref") or item.get("evidence_ref_uri"))
    if legacy:
        values.extend(_list(entity.get("evidence_ref_uri_list")))
    return list(dict.fromkeys(_text(value) for value in values if _text(value)))


def _evidence_item_groups(factor: dict[str, Any]) -> dict[str, str]:
    groups: dict[str, str] = {}
    for key in ("information_points", "evidence_items"):
        for item in _list(factor.get(key)):
            if not isinstance(item, dict):
                continue
            ref = _text(item.get("evidence_ref") or item.get("evidence_ref_uri"))
            group = _text(item.get("independence_key") or item.get("evidence_group"))
            if ref and group:
                groups[ref] = group
    return groups


def _evidence_groups(
    refs: list[str],
    factor: dict[str, Any],
    source_groups: dict[str, str | None],
    explicit_groups: dict[str, str],
    *,
    legacy: bool,
) -> tuple[set[str], list[str]]:
    item_groups = _evidence_item_groups(factor)
    groups: set[str] = set()
    unresolved: list[str] = []
    for ref in refs:
        group = item_groups.get(ref) or explicit_groups.get(ref)
        match = SOURCE_REF_RE.fullmatch(ref)
        if not group and match:
            group = source_groups.get(match.group(1))
        if group:
            groups.add(group)
        elif legacy:
            groups.add(f"legacy:{ref}")
        else:
            unresolved.append(ref)
    return groups, unresolved


def _public_body_issues(body: str, path: str) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    if not body:
        return issues
    visible = re.sub(
        r"\^(?:src|evidence):(?:source_ref:[A-Za-z0-9_.-]+|opp://source/\d+)",
        "^evidence:CITATION",
        body,
    )
    if PUBLIC_URL_RE.search(visible):
        issues.append(ContractIssue("public_naked_url", "error", path, "正文含裸 URL；链接必须进入证据对象"))
    for marker in PUBLIC_MACHINE_MARKERS:
        if marker in visible:
            issues.append(ContractIssue("public_machine_marker", "error", path, f"正文暴露机器标记: {marker}"))
    for phrase in TEMPLATE_PHRASES:
        if phrase in body:
            issues.append(ContractIssue("template_phrase", "error", path, f"正文包含禁用模板/机器短语: {phrase}"))
    return issues


def _structured_public_body_issues(
    body: str,
    path: str,
) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    matches: list[tuple[str, re.Match[str]]] = []
    for heading in PUBLIC_SECTION_HEADINGS:
        found = list(
            re.finditer(
                rf"(?m)^#{{2,4}}\s*{re.escape(heading)}\s*$",
                body,
            )
        )
        if len(found) != 1:
            issues.append(
                ContractIssue(
                    "public_section_structure",
                    "error",
                    path,
                    f"公开章节必须且只能出现一个“{heading}”小标题",
                )
            )
            continue
        matches.append((heading, found[0]))
    if len(matches) != len(PUBLIC_SECTION_HEADINGS):
        return issues
    if [heading for heading, _ in sorted(matches, key=lambda row: row[1].start())] != list(
        PUBLIC_SECTION_HEADINGS
    ):
        issues.append(
            ContractIssue(
                "public_section_structure",
                "error",
                path,
                "公开章节小标题顺序必须为“问题—研究方法与数据—研究与分析—总结”",
            )
        )
        return issues
    ordered = [match for _, match in matches]
    for index, (heading, match) in enumerate(matches):
        end = ordered[index + 1].start() if index + 1 < len(ordered) else len(body)
        visible = re.sub(r"\s+", "", body[match.end():end])
        if len(visible) < 20:
            issues.append(
                ContractIssue(
                    "public_section_structure",
                    "error",
                    path,
                    f"“{heading}”部分为空或过短，不能只放标题",
                )
            )
    return issues


def _review_records(pack: dict[str, Any]) -> list[dict[str, Any]]:
    records = pack.get("review_records") or []
    return [record for record in records if isinstance(record, dict)]


def validate_run_pack(pack: dict[str, Any], *, publication_mode: str = "stage") -> PackValidationReport:
    if publication_mode not in {"validate", "stage", "publish"}:
        raise ValueError(f"未知 publication_mode: {publication_mode}")
    profile = resolve_track_config("c")
    schema = _text(pack.get("pack_schema_version")) or LEGACY_PACK_SCHEMA
    legacy = schema == LEGACY_PACK_SCHEMA
    report = PackValidationReport(
        pack_schema_version=schema,
        workflow_contract_version=_text(pack.get("workflow_contract_version")) or None,
        publication_mode=publication_mode,
    )

    if not legacy and schema != profile["pack_schema_version"]:
        report.issues.append(ContractIssue("pack_schema", "error", "pack_schema_version", f"不支持的版本 {schema!r}"))
    if legacy:
        report.issues.append(ContractIssue(
            "legacy_pack",
            "warning",
            "pack_schema_version",
            "旧研究包可识别并审计，但能否重新装载仍取决于 legacy 校验；既有 DB 页面继续可读。缺少 V2 独立证据组和 reviewer 记录时不得自动发布。",
        ))
    elif report.workflow_contract_version != contract_version():
        report.issues.append(ContractIssue(
            "workflow_version",
            "error",
            "workflow_contract_version",
            f"V2 pack 必须显式声明 {contract_version()}",
        ))

    required = ("slug", "research_question", "intake", "sources", "entities", "sections")
    if not legacy:
        required = ("display_title",) + required
    for key in required:
        if not pack.get(key):
            report.issues.append(ContractIssue("missing_field", "error", key, "必填字段为空"))

    # Loader 会把 supplement_requests 直接写入带 CHECK 约束的表；契约校验必须
    # 在任何 DB 写入前覆盖同一枚举，避免 validate-only 通过而 stage 才失败。
    for index, item in enumerate(pack.get("supplement_requests") or []):
        path = f"supplement_requests[{index}]"
        if not isinstance(item, dict):
            report.issues.append(
                ContractIssue(
                    "supplement_field",
                    "error",
                    path,
                    "补证请求必须是对象",
                )
            )
            continue
        if not _text(item.get("request_title")):
            report.issues.append(
                ContractIssue(
                    "supplement_field",
                    "error",
                    f"{path}.request_title",
                    "补证请求标题不能为空",
                )
            )
        enum_fields = (
            ("priority", SUPPLEMENT_PRIORITY_VALUES),
            ("blocking_status", SUPPLEMENT_BLOCKING_STATUS_VALUES),
            ("review_status", SUPPLEMENT_REVIEW_STATUS_VALUES),
        )
        for field_name, allowed_values in enum_fields:
            value = _text(item.get(field_name))
            if value not in allowed_values:
                report.issues.append(
                    ContractIssue(
                        "enum_value",
                        "error",
                        f"{path}.{field_name}",
                        f"非法 {field_name}: {value!r}",
                    )
                )
    if not legacy:
        try:
            canonical_intake = parse_intake_payload(pack.get("intake") or {}, allow_legacy_alias=False)
        except Exception as exc:
            report.issues.append(ContractIssue("intake_contract", "error", "intake", str(exc)))
        else:
            if canonical_intake["research_question"] != _text(pack.get("research_question")):
                report.issues.append(ContractIssue("intake_contract", "error", "intake.research_question", "必须与 pack.research_question 完全一致"))
            for issue in canonical_intake.get("validation_issues", []):
                report.issues.append(ContractIssue("intake_contract", "error", "intake", str(issue)))
        valid_run_modes = {"c_open", "c_open_with_seed", "c_paper", "c_hybrid", "c_paper_scoring_ready", "needs_problem_rewrite"}
        if _text(pack.get("run_mode") or "c_hybrid") not in valid_run_modes:
            report.issues.append(ContractIssue("enum_value", "error", "run_mode", f"非法 run_mode: {pack.get('run_mode')!r}"))

    channel_contract = _text(pack.get("search_channel_contract_version"))
    enforce_channel_contract = channel_contract == "research.search_channels.v1"
    if channel_contract and not enforce_channel_contract:
        report.issues.append(ContractIssue(
            "search_channel_isolation", "error", "search_channel_contract_version",
            f"不支持的搜索渠道合同：{channel_contract}",
        ))
    searches = [item for item in pack.get("search_plan", []) if isinstance(item, dict)]
    if enforce_channel_contract:
        if not searches:
            report.issues.append(ContractIssue(
                "search_channel_isolation", "error", "search_plan",
                "新研究必须分别执行研报与网络检索，search_plan 不能为空",
            ))
        channels_by_axis: dict[str, set[str]] = {}
        for index, item in enumerate(searches):
            channel = _text(item.get("source_channel"))
            axis = _text(item.get("axis_key"))
            if channel not in {"report", "web"}:
                report.issues.append(ContractIssue(
                    "source_channel_missing", "error", f"search_plan[{index}].source_channel",
                    "搜索任务必须标记 report 或 web",
                ))
            if axis and channel in {"report", "web"}:
                channels_by_axis.setdefault(axis, set()).add(channel)
            if int(item.get("round", 1) or 1) >= 2 and not _text(item.get("gap_trigger")):
                report.issues.append(ContractIssue(
                    "search_channel_isolation", "error", f"search_plan[{index}].gap_trigger",
                    "第二轮搜索必须说明由哪个第一轮分析 gap 触发",
                ))
        for axis, channels in channels_by_axis.items():
            if channels != {"report", "web"}:
                report.issues.append(ContractIssue(
                    "search_channel_isolation", "error", "search_plan",
                    f"问题轴 {axis!r} 必须分别执行 report 与 web 检索，当前为 {sorted(channels)}",
                ))

    modeling_contract = _text(pack.get("modeling_contract_version"))
    enforce_modeling_contract = modeling_contract == "research.modeling_skills.v1"
    if modeling_contract and not enforce_modeling_contract:
        report.issues.append(ContractIssue(
            "modeling_contract", "error", "modeling_contract_version",
            f"不支持的建模合同：{modeling_contract}",
        ))
    if enforce_modeling_contract:
        for index, item in enumerate(pack.get("modeling_records") or []):
            path = f"modeling_records[{index}]"
            if not isinstance(item, dict):
                report.issues.append(ContractIssue("modeling_contract", "error", path, "Skill 执行记录必须是对象"))
                continue
            if _text(item.get("skill_name")) not in MODEL_SKILLS:
                report.issues.append(ContractIssue("modeling_contract", "error", f"{path}.skill_name", "只能登记四类活动建模 Skill"))
            if _text(item.get("status")) not in {"loaded", "completed", "blocked", "not_applicable"}:
                report.issues.append(ContractIssue("modeling_contract", "error", f"{path}.status", "Skill 执行状态无效"))
            if _text(item.get("status")) == "completed":
                for field_name in ("input_artifact_hash", "output_artifact_hash"):
                    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", _text(item.get(field_name))):
                        report.issues.append(ContractIssue("modeling_contract", "error", f"{path}.{field_name}", "完成记录必须绑定有效 SHA256"))
        for index, item in enumerate(pack.get("independent_model_freezes") or []):
            path = f"independent_model_freezes[{index}]"
            if not isinstance(item, dict):
                report.issues.append(ContractIssue("modeling_contract", "error", path, "独立预测冻结记录必须是对象"))
                continue
            if not _text(item.get("model_ref")):
                report.issues.append(ContractIssue("modeling_contract", "error", f"{path}.model_ref", "独立预测冻结必须标明模型"))
            for field_name in ("input_hash", "output_hash"):
                if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", _text(item.get(field_name))):
                    report.issues.append(ContractIssue("modeling_contract", "error", f"{path}.{field_name}", "独立预测冻结必须绑定有效 SHA256"))
            if item.get("frozen_before_consensus") is not True:
                report.issues.append(ContractIssue("modeling_contract", "error", f"{path}.frozen_before_consensus", "独立预测必须在读取一致预期前冻结"))
        for index, item in enumerate(pack.get("external_reconciliations") or []):
            path = f"external_reconciliations[{index}]"
            if not isinstance(item, dict):
                report.issues.append(ContractIssue("modeling_contract", "error", path, "外部对账记录必须是对象"))
                continue
            for field_name in ("model_ref", "benchmark_ref"):
                if not _text(item.get(field_name)):
                    report.issues.append(ContractIssue("modeling_contract", "error", f"{path}.{field_name}", "外部对账字段不能为空"))
            if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", _text(item.get("artifact_hash"))):
                report.issues.append(ContractIssue("modeling_contract", "error", f"{path}.artifact_hash", "外部对账必须绑定有效 SHA256"))
            if _text(item.get("status")) not in {"completed", "completed_with_gap", "blocked"}:
                report.issues.append(ContractIssue("modeling_contract", "error", f"{path}.status", "外部对账状态无效"))

    sources = [source for source in pack.get("sources", []) if isinstance(source, dict)]
    source_refs = [_text(source.get("ref")) for source in sources]
    if any(not ref for ref in source_refs):
        report.issues.append(ContractIssue("source_ref_empty", "error", "sources", "source.ref 不能为空"))
    if len(source_refs) != len(set(source_refs)):
        report.issues.append(ContractIssue("source_ref_duplicate", "error", "sources", "source.ref 不能重复"))
    source_groups: dict[str, str | None] = {}
    source_languages: dict[str, str] = {}
    for index, source in enumerate(sources):
        source_path = f"sources[{index}]"
        if not legacy:
            for field_name in ("title", "publisher", "source_tier", "source_review_status", "excerpt", "language"):
                if not _text(source.get(field_name)):
                    report.issues.append(ContractIssue("source_field_empty", "error", f"{source_path}.{field_name}", "字段不能为空"))
            _validate_human_field(report, source.get("title"), path=f"{source_path}.title")
            _validate_human_field(report, source.get("excerpt"), path=f"{source_path}.excerpt")
            if not (_text(source.get("url")) or _text(source.get("local_path"))):
                report.issues.append(ContractIssue(
                    "source_locator_missing",
                    "error",
                    source_path,
                    "V2 source 必须有原始 URL 或本地原文路径，标题不能替代来源定位",
                ))
            language = _text(source.get("language")).lower()
            if language.startswith("en"):
                if not _text(source.get("title_zh")) or not _text(source.get("excerpt_zh")):
                    report.issues.append(ContractIssue(
                        "source_translation_missing",
                        "error",
                        source_path,
                        "英文来源必须保留英文 title/excerpt，并显式提供 title_zh 和 excerpt_zh",
                    ))
            if _text(source.get("source_tier")) not in {"S", "A", "B", "C", "D", "unknown"}:
                report.issues.append(ContractIssue("enum_value", "error", f"{source_path}.source_tier", "非法来源层级"))
            if _text(source.get("source_review_status")) not in {"pending", "pass", "pass_with_note", "weak_source_only", "duplicate", "paywalled", "stale", "conflict", "reject"}:
                report.issues.append(ContractIssue("enum_value", "error", f"{source_path}.source_review_status", "非法来源审查状态"))
            if enforce_channel_contract and _text(source.get("source_channel")) not in {"report", "web"}:
                report.issues.append(ContractIssue(
                    "source_channel_missing", "error", f"{source_path}.source_channel",
                    "新来源必须在入库前标记为 report 或 web",
                ))
        key = _text(source.get("independence_key") or source.get("cluster"))
        if not key and legacy:
            key = _text(source.get("publisher") or source.get("ref"))
        if not key and not legacy:
            report.issues.append(ContractIssue(
                "independence_key_missing",
                "error",
                f"sources[{index}]",
                "V2 source 必须说明 independence_key，不能把 URI 数量当独立来源数",
            ))
        if not legacy and not _text(source.get("independence_rationale")):
            report.issues.append(ContractIssue(
                "independence_rationale_missing",
                "error",
                source_path,
                "V2 source 必须说明为何与其他来源独立或为何属于同一证据组",
            ))
        source_groups[_text(source.get("ref"))] = key or None
        source_languages[_text(source.get("ref"))] = _text(source.get("language")).lower()
    explicit_groups = {
        _text(key): _text(value)
        for key, value in (pack.get("evidence_groups") or {}).items()
        if _text(key) and _text(value)
    }

    entities = [entity for entity in pack.get("entities", []) if isinstance(entity, dict)]
    entity_keys = [_text(entity.get("key")) for entity in entities]
    if any(not key for key in entity_keys):
        report.issues.append(ContractIssue("entity_key_empty", "error", "entities", "entity.key 不能为空"))
    if len(entity_keys) != len(set(entity_keys)):
        report.issues.append(ContractIssue("entity_key_duplicate", "error", "entities", "entity.key 不能重复"))
    entity_by_key = {entity.get("key"): entity for entity in entities}

    for index, claim in enumerate(pack.get("claims", [])):
        if not isinstance(claim, dict):
            report.issues.append(ContractIssue("claim_field_empty", "error", f"claims[{index}]", "claim 必须是对象"))
            continue
        claim_path = f"claims[{index}]"
        ref = _text(claim.get("source_ref"))
        if ref not in source_groups:
            report.issues.append(ContractIssue("data_source_unknown", "error", claim_path, f"未知 source_ref: {ref!r}"))
        claim_entity_key = _text(claim.get("entity_key"))
        if claim_entity_key and claim_entity_key not in entity_by_key:
            report.issues.append(ContractIssue("claim_entity_unknown", "error", claim_path, f"未知 entity_key: {claim_entity_key}"))
        for field_name in ("claim_text", "source_excerpt"):
            if not _text(claim.get(field_name)):
                report.issues.append(ContractIssue("claim_field_empty", "error", f"{claim_path}.{field_name}", "字段不能为空"))
        if not legacy:
            _validate_human_field(report, claim.get("claim_type"), path=f"{claim_path}.claim_type")
            _validate_human_field(report, claim.get("claim_text"), path=f"{claim_path}.claim_text")
        if not legacy and source_languages.get(ref, "").startswith("en") and not _text(claim.get("source_excerpt_zh")):
            report.issues.append(ContractIssue("source_translation_missing", "error", claim_path, "英文 claim 摘录必须提供 source_excerpt_zh"))

    data_points = [item for item in pack.get("data_points", []) if isinstance(item, dict)]
    minimum = int(profile["min_parallel_data_points"])
    data_identities: set[tuple[str, ...]] = set()
    data_point_keys: set[str] = set()
    for index, point in enumerate(data_points):
        path = f"data_points[{index}]"
        point_key = _text(point.get("data_point_key"))
        if point_key:
            if point_key in data_point_keys:
                report.issues.append(
                    ContractIssue("data_identity_duplicate", "error", f"{path}.data_point_key", "data_point_key 必须唯一")
                )
            data_point_keys.add(point_key)
        source_ref = _text(point.get("source_ref"))
        if source_ref not in source_groups:
            report.issues.append(ContractIssue("data_source_unknown", "error", path, f"未知 source_ref: {source_ref!r}"))
        data_entity_key = _text(point.get("entity_key"))
        if data_entity_key and data_entity_key not in entity_by_key:
            report.issues.append(ContractIssue("data_entity_unknown", "error", path, f"未知 entity_key: {data_entity_key}"))
        for key in ("metric", "unit", "source_excerpt"):
            if not _text(point.get(key)):
                report.issues.append(ContractIssue("data_field_empty", "error", f"{path}.{key}", "字段不能为空"))
        if not legacy:
            _validate_human_field(report, point.get("metric"), path=f"{path}.metric")
            _validate_human_field(report, point.get("value_text"), path=f"{path}.value_text")
        if not legacy and source_languages.get(source_ref, "").startswith("en") and not _text(point.get("source_excerpt_zh")):
            report.issues.append(ContractIssue("source_translation_missing", "error", path, "英文数据点摘录必须提供 source_excerpt_zh"))
        observations = point.get("observations")
        if observations is not None and not isinstance(observations, list):
            report.issues.append(ContractIssue("data_value_empty", "error", f"{path}.observations", "observations 必须是数组"))
            observations = []
        if observations:
            for obs_index, observation in enumerate(observations):
                obs_path = f"{path}.observations[{obs_index}]"
                if not isinstance(observation, dict):
                    report.issues.append(ContractIssue("data_value_empty", "error", obs_path, "序列观测必须是对象"))
                    continue
                if not _text(observation.get("period") or observation.get("as_of_date")):
                    report.issues.append(ContractIssue("data_time_empty", "error", obs_path, "每个序列观测必须有 period/as_of_date"))
                obs_number = _finite_number(observation.get("value_num"))
                if observation.get("value_num") is not None and obs_number is None:
                    report.issues.append(ContractIssue("data_value_non_finite", "error", obs_path, "value_num 必须是有限数值"))
                if obs_number is None and not _text(observation.get("value_text")):
                    report.issues.append(ContractIssue("data_value_empty", "error", obs_path, "每个序列观测必须有 value_num/value_text"))
        else:
            if not _text(point.get("period")) and not _text(point.get("as_of_date")):
                report.issues.append(ContractIssue("data_time_empty", "error", path, "period/as_of_date 至少一个必填"))
            number = _finite_number(point.get("value_num"))
            if point.get("value_num") is not None and number is None:
                report.issues.append(ContractIssue("data_value_non_finite", "error", path, "value_num 必须是有限数值"))
            if number is None and not _text(point.get("value_text")):
                report.issues.append(ContractIssue("data_value_empty", "error", path, "value_num/value_text 至少一个必填"))
        identity_parts = [
            source_ref,
            _text(point.get("entity_key")),
            _normal(point.get("metric")),
            _normal(point.get("unit")),
        ]
        if legacy:
            identity_parts.append(_text(point.get("period") or point.get("as_of_date")))
        else:
            identity_parts.append(_normal(point.get("scope_key") or point.get("series_key")))
        identity = tuple(identity_parts)
        if identity in data_identities:
            report.issues.append(ContractIssue(
                "data_identity_duplicate",
                "error" if not legacy else "warning",
                path,
                "同源、同对象、同指标、同口径的多期观测必须合并为一个 observations 序列；不同范围请显式填写 scope_key",
            ))
        data_identities.add(identity)
    if len(data_identities) < minimum:
        report.issues.append(ContractIssue(
            "parallel_data_points",
            "error",
            "data_points",
            f"真实研究至少需要 {minimum} 个平行数据点，当前只有 {len(data_identities)} 个唯一研究事实；同一序列观测不能拆开计数。",
        ))

    factor_count = 0
    theory_count = 0
    market_count = 0
    market_entity_keys: set[str] = set()
    for entity_index, entity in enumerate(entities):
        path = f"entities[{entity_index}]"
        if not legacy:
            for field_name in ("canonical_name", "display_name", "entity_type", "taxonomy_level", "description"):
                if not _text(entity.get(field_name)):
                    report.issues.append(ContractIssue("entity_field_empty", "error", f"{path}.{field_name}", "字段不能为空"))
            if _text(entity.get("entity_type")) not in ENTITY_TYPE_VALUES:
                report.issues.append(
                    ContractIssue(
                        "entity_type_enum",
                        "error",
                        f"{path}.entity_type",
                        "实体类型与 live DB 枚举不兼容",
                    )
                )
            if _text(entity.get("taxonomy_level")) not in ENTITY_TYPE_VALUES:
                report.issues.append(
                    ContractIssue(
                        "entity_type_enum",
                        "error",
                        f"{path}.taxonomy_level",
                        "实体层级与 live DB 枚举不兼容",
                    )
                )
            enum_checks = (
                ("maturation_status", ENTITY_MATURATION_STATUS_VALUES),
                ("research_priority_label", RESEARCH_PRIORITY_LABEL_VALUES),
                ("score_grade", SCORE_GRADE_VALUES),
                ("score_quality_label", SCORE_QUALITY_LABEL_VALUES),
            )
            for field_name, allowed_values in enum_checks:
                value = _text(entity.get(field_name))
                if value and value not in allowed_values:
                    report.issues.append(
                        ContractIssue(
                            "entity_state_enum",
                            "error",
                            f"{path}.{field_name}",
                            "实体状态与 live DB 枚举不兼容",
                        )
                    )
            if not entity.get("evidence_ref_uri_list"):
                report.issues.append(ContractIssue("entity_field_empty", "error", f"{path}.evidence_ref_uri_list", "实体必须绑定证据索引"))
            _validate_source_ref_uris(
                report,
                entity.get("evidence_ref_uri_list"),
                path=f"{path}.evidence_ref_uri_list",
                source_groups=source_groups,
                required=False,
            )
        try:
            mode = entity_research_mode(entity, legacy=legacy)
        except ValueError as exc:
            report.issues.append(ContractIssue("entity_mode", "error", path, str(exc)))
            mode = "market_linked"
        if mode == "theory_research":
            theory_count += 1
            profile_data = entity.get("research_profile") or (entity.get("lit_review_profile") if legacy else None) or {}
            for field_name in ("research_question", "literature_review_markdown", "analysis_markdown", "answer_markdown", "conclusion_markdown"):
                if not _text(profile_data.get(field_name)):
                    report.issues.append(ContractIssue("theory_profile_field", "error", f"{path}.research_profile.{field_name}", "字段不能为空"))
            if not legacy:
                _validate_source_ref_uris(
                    report,
                    profile_data.get("evidence_ref_uri_list"),
                    path=f"{path}.research_profile.evidence_ref_uri_list",
                    source_groups=source_groups,
                    required=True,
                )
            points = [point for point in entity.get("research_data_points", []) if isinstance(point, dict)]
            min_rows = int(profile["theory_research"]["min_research_ledger_rows"])
            if len(points) < min_rows:
                report.issues.append(ContractIssue("theory_ledger_count", "error", f"{path}.research_data_points", f"至少需要 {min_rows} 条底稿，当前 {len(points)} 条"))
            interpretations: set[str] = set()
            uses: set[str] = set()
            for point_index, point in enumerate(points):
                point_path = f"{path}.research_data_points[{point_index}]"
                for field_name in ("source_ref", "data_point_title", "metric", "source_excerpt", "interpretation", "research_use"):
                    if not _text(point.get(field_name)):
                        report.issues.append(ContractIssue("theory_ledger_field", "error", f"{point_path}.{field_name}", "字段不能为空"))
                if not legacy:
                    _validate_human_field(report, point.get("data_point_title"), path=f"{point_path}.data_point_title")
                    _validate_human_field(report, point.get("metric"), path=f"{point_path}.metric")
                research_source_ref = _text(point.get("source_ref"))
                if research_source_ref not in source_groups:
                    report.issues.append(ContractIssue("data_source_unknown", "error", point_path, f"未知 source_ref: {research_source_ref!r}"))
                if not legacy and source_languages.get(research_source_ref, "").startswith("en") and not _text(point.get("source_excerpt_zh")):
                    report.issues.append(ContractIssue("source_translation_missing", "error", point_path, "英文研究底稿摘录必须提供 source_excerpt_zh"))
                interpretation = _normal(point.get("interpretation"))
                use = _normal(point.get("research_use"))
                if interpretation and interpretation == use:
                    report.issues.append(ContractIssue("theory_interpretation_equals_use", "error", point_path, "解读和用途必须回答不同问题"))
                if interpretation in interpretations and interpretation:
                    report.issues.append(ContractIssue("theory_interpretation_duplicate", "error" if not legacy else "warning", point_path, "解读在同实体内重复"))
                if use in uses and use:
                    report.issues.append(ContractIssue("theory_use_duplicate", "error" if not legacy else "warning", point_path, "用途在同实体内重复"))
                interpretations.add(interpretation)
                uses.add(use)
            if entity.get("factor_scores"):
                report.issues.append(ContractIssue("theory_has_scores", "error", path, "theory_research 不得包含 factor_scores"))
        else:
            market_count += 1
            market_entity_keys.add(_text(entity.get("key")))
            if not legacy:
                score_point = _finite_number(entity.get("score_point"))
                if score_point is None or not 0 <= score_point <= 100:
                    report.issues.append(ContractIssue("composite_score_range", "error", f"{path}.score_point", "综合分必须是 0~100 的有限数值"))
                for field_name in ("coverage", "confidence"):
                    ratio = _finite_number(entity.get(field_name))
                    if ratio is None or not 0 <= ratio <= 1:
                        report.issues.append(ContractIssue("composite_score_range", "error", f"{path}.{field_name}", "覆盖率/置信度必须是 0~1 的有限数值"))
                low = _finite_number(entity.get("score_band_low"))
                high = _finite_number(entity.get("score_band_high"))
                if low is None or high is None or score_point is None or not 0 <= low <= score_point <= high <= 100:
                    report.issues.append(ContractIssue("composite_score_range", "error", path, "score band 必须满足 0 <= low <= score <= high <= 100"))
            factors = sorted(entity.get("factor_scores", []), key=_factor_score, reverse=True)
            if not factors and not legacy:
                report.issues.append(ContractIssue(
                    "market_scores_missing",
                    "error",
                    f"{path}.factor_scores",
                    "market_linked 实体必须有经过证据门槛的因子评分；证据不足时不得作为已发布市场实体",
                ))
            factor_rationales: set[str] = set()
            for rank, factor in enumerate(factors, start=1):
                factor_count += 1
                code = _text(factor.get("factor_code"))
                factor_path = f"{path}.factor_scores[{rank - 1}]"
                if code not in FACTOR_BY_CODE:
                    report.issues.append(ContractIssue("factor_code", "error", factor_path, f"未知 factor_code: {code}"))
                    continue
                if not legacy:
                    for field_name in (
                        "metric_name", "unit", "score_rationale", "factor_value_summary",
                        "source_context_summary", "factor_topic_analysis",
                    ):
                        if not _text(factor.get(field_name)):
                            report.issues.append(ContractIssue("factor_field_empty", "error", f"{factor_path}.{field_name}", "字段不能为空"))
                    _validate_human_field(report, factor.get("metric_name"), path=f"{factor_path}.metric_name")
                    _validate_human_field(report, factor.get("factor_value_summary"), path=f"{factor_path}.factor_value_summary")
                    analysis_points = [
                        _text(item)
                        for item in _list(factor.get("theme_analysis_points"))
                        if _text(item)
                    ]
                    if len(analysis_points) < 2 or len({_normal(item) for item in analysis_points}) != len(analysis_points):
                        report.issues.append(ContractIssue(
                            "factor_field_empty",
                            "error",
                            f"{factor_path}.theme_analysis_points",
                            "至少需要 2 条互不重复的主题分析要点，不能由页面 fallback 生成通用分析",
                        ))
                    if not _text(factor.get("period")) and not _text(factor.get("as_of_date")):
                        report.issues.append(ContractIssue("factor_field_empty", "error", factor_path, "period/as_of_date 至少一个必填"))
                    for field_name in ("score_raw", "score_adjusted"):
                        score = _finite_number(factor.get(field_name))
                        if score is None or not 0 <= score <= 100:
                            report.issues.append(ContractIssue("factor_score_range", "error", f"{factor_path}.{field_name}", "分数必须是 0~100 的有限数值"))
                    for field_name in ("coverage", "confidence"):
                        ratio = _finite_number(factor.get(field_name))
                        if ratio is None or not 0 <= ratio <= 1:
                            report.issues.append(ContractIssue("factor_score_range", "error", f"{factor_path}.{field_name}", "覆盖率/置信度必须是 0~1 的有限数值"))
                    rationale = _normal(factor.get("score_rationale"))
                    if rationale and rationale in factor_rationales:
                        report.issues.append(ContractIssue(
                            "factor_rationale_duplicate",
                            "error",
                            f"{factor_path}.score_rationale",
                            "同实体因子评分理由重复；必须解释该因子的独有事实、逻辑和分数边界",
                        ))
                    factor_rationales.add(rationale)
                    _validate_metric_slot_chain(
                        report,
                        factor,
                        path=factor_path,
                        data_point_keys=data_point_keys,
                        source_groups=source_groups,
                    )
                refs = _factor_refs(factor, entity=entity, legacy=legacy)
                groups, unresolved = _evidence_groups(refs, factor, source_groups, explicit_groups, legacy=legacy)
                important = rank <= 3 or _factor_score(factor) >= 70 or bool(factor.get("is_important"))
                required_groups = int(profile["factor_evidence_groups"]["important" if important else "normal"])
                information_points = [item for item in factor.get("information_points", []) if isinstance(item, dict)]
                if not legacy and len(information_points) < required_groups:
                    report.issues.append(ContractIssue(
                        "factor_information_point",
                        "error",
                        f"{factor_path}.information_points",
                        f"因子至少需要 {required_groups} 条人读证据说明，当前 {len(information_points)} 条",
                    ))
                for item_index, item in enumerate(information_points if not legacy else []):
                    item_path = f"{factor_path}.information_points[{item_index}]"
                    for field_name in ("evidence_ref", "excerpt", "interpretation"):
                        if not _text(item.get(field_name)):
                            report.issues.append(ContractIssue("factor_information_point", "error", f"{item_path}.{field_name}", "字段不能为空"))
                if unresolved:
                    report.issues.append(ContractIssue(
                        "factor_independence_unresolved",
                        "error",
                        factor_path,
                        f"以下证据没有 independence_key/evidence_group: {unresolved}",
                    ))
                if len(groups) < required_groups:
                    report.issues.append(ContractIssue(
                        "factor_evidence_groups",
                        "error",
                        factor_path,
                        f"需要至少 {required_groups} 个独立证据组，当前 {len(groups)} 个；引用数 {len(refs)} 不能替代独立性。",
                    ))

    targets = [target for target in pack.get("entity_investment_targets", []) if isinstance(target, dict)]
    allowed_target_types = {
        "company", "security", "etf", "futures_contract", "spread", "basket", "external_watch",
    }
    targets_by_entity: dict[str, list[dict[str, Any]]] = {}
    required_target_fields = (
        "target_name", "exposure_rationale", "research_action", "investment_view", "risk_note",
        "target_priority", "target_quality_label", "relative_preference", "confirmed_scenario_action",
        "falsified_scenario_action", "target_profile_markdown", "target_deep_research_markdown",
        "entity_relation_markdown", "parent_research_relation_markdown",
        "conditional_investment_recommendation", "financial_data_status",
    )
    for index, target in enumerate(targets):
        path = f"entity_investment_targets[{index}]"
        entity_key = target.get("entity_key")
        if entity_key not in entity_by_key:
            report.issues.append(ContractIssue("target_entity_unknown", "error", path, f"未知 entity_key: {entity_key}"))
            continue
        target_type = _text(target.get("target_type") or "security")
        if target_type not in allowed_target_types:
            report.issues.append(ContractIssue(
                "target_type_invalid",
                "error",
                f"{path}.target_type",
                f"target_type={target_type!r} 不在数据库允许集合 {sorted(allowed_target_types)} 中",
            ))
        if entity_research_mode(entity_by_key[entity_key], legacy=legacy) == "theory_research":
            report.issues.append(ContractIssue("theory_has_target", "error", path, "theory_research 不得绑定标的"))
        for field_name in required_target_fields:
            if not _text(target.get(field_name)):
                report.issues.append(ContractIssue("target_field_empty", "error", f"{path}.{field_name}", "字段不能为空"))
        if not target.get("target_data_points"):
            report.issues.append(ContractIssue("target_data_points", "error", path, "每个标的必须有结构化 target_data_points"))
        for point_index, point in enumerate(target.get("target_data_points", []) if not legacy else []):
            point_path = f"{path}.target_data_points[{point_index}]"
            if not isinstance(point, dict):
                report.issues.append(ContractIssue("target_data_point_field", "error", point_path, "标的数据点必须是对象"))
                continue
            for field_name in (
                "metric_name", "metric_category", "unit", "source_title",
                "source_publisher", "source_excerpt", "evidence_ref_uri",
            ):
                if not _text(point.get(field_name)):
                    report.issues.append(ContractIssue("target_data_point_field", "error", f"{point_path}.{field_name}", "字段不能为空"))
            _validate_human_field(report, point.get("metric_name"), path=f"{point_path}.metric_name")
            if not _text(point.get("period")) and not _text(point.get("as_of_date")):
                report.issues.append(ContractIssue("target_data_point_field", "error", point_path, "period/as_of_date 至少一个必填"))
            point_number = _finite_number(point.get("value_num"))
            if point.get("value_num") is not None and point_number is None:
                report.issues.append(ContractIssue("target_data_point_value", "error", point_path, "value_num 必须是有限数值"))
            if point_number is None and not _text(point.get("value_text")):
                report.issues.append(ContractIssue("target_data_point_value", "error", point_path, "value_num/value_text 至少一个必填"))
            evidence_ref = _text(point.get("evidence_ref_uri"))
            match = SOURCE_REF_RE.fullmatch(evidence_ref)
            if not match:
                report.issues.append(ContractIssue(
                    "target_evidence_unknown",
                    "error",
                    f"{point_path}.evidence_ref_uri",
                    "V2 标的数据点证据必须使用 source_ref:<ref>",
                ))
            elif match.group(1) not in source_groups:
                report.issues.append(ContractIssue("target_evidence_unknown", "error", f"{point_path}.evidence_ref_uri", f"未知 source_ref: {match.group(1)}"))
            if match and source_languages.get(match.group(1), "").startswith("en"):
                if not _text(point.get("source_title_zh")) or not _text(point.get("source_excerpt_zh")):
                    report.issues.append(ContractIssue("source_translation_missing", "error", point_path, "英文标的数据点必须提供 source_title_zh 和 source_excerpt_zh"))
        targets_by_entity.setdefault(str(entity_key), []).append(target)
    for entity_key in sorted(market_entity_keys):
        if not legacy and not targets_by_entity.get(entity_key):
            report.issues.append(ContractIssue(
                "market_target_missing",
                "error",
                f"entity[{entity_key}]",
                "market_linked 实体必须至少绑定一个可追溯标的、交易工具或观察篮子",
            ))
    for entity_key, rows in targets_by_entity.items():
        for field_name in ("investment_view", "risk_note", "relative_preference", "confirmed_scenario_action", "falsified_scenario_action", "research_action"):
            values: dict[str, int] = {}
            for row in rows:
                value = _normal(row.get(field_name))
                if value:
                    values[value] = values.get(value, 0) + 1
            duplicates = sum(count - 1 for count in values.values() if count > 1)
            if duplicates:
                report.issues.append(ContractIssue(
                    "target_field_duplicate",
                    "error" if not legacy else "warning",
                    f"entity[{entity_key}].targets.{field_name}",
                    f"发现 {duplicates} 条重复内容；标的字段必须逐标的差异化",
                ))

    main_min = int(profile["fallback_minimum_characters"]["report_section"])
    entity_min = int(profile["fallback_minimum_characters"]["entity_section"])
    if _text(pack.get("quality_profile")) == "deep_research":
        main_min = int(profile["deep_research_minimum_characters"]["report_section"])
        entity_min = int(profile["deep_research_minimum_characters"]["entity_section"])
    homepage_min = pack.get("homepage_section_min_characters")
    homepage_max = pack.get("homepage_section_max_characters")
    try:
        homepage_min = main_min if homepage_min is None else int(homepage_min)
    except (TypeError, ValueError):
        homepage_min = main_min
        report.issues.append(ContractIssue(
            "homepage_section_length",
            "error",
            "homepage_section_min_characters",
            "首页摘要 section 下限必须是正整数",
        ))
    try:
        homepage_max = None if homepage_max is None else int(homepage_max)
    except (TypeError, ValueError):
        homepage_max = None
        report.issues.append(ContractIssue(
            "homepage_section_length",
            "error",
            "homepage_section_max_characters",
            "首页摘要 section 上限必须是正整数",
        ))
    if homepage_min <= 0:
        report.issues.append(ContractIssue(
            "homepage_section_length",
            "error",
            "homepage_section_min_characters",
            "首页摘要 section 下限必须是正整数",
        ))
        homepage_min = main_min
    if homepage_max is not None and homepage_max <= 0:
        report.issues.append(ContractIssue(
            "homepage_section_length",
            "error",
            "homepage_section_max_characters",
            "首页摘要 section 上限必须是正整数",
        ))
        homepage_max = None
    if homepage_max is not None and homepage_min > homepage_max:
        report.issues.append(ContractIssue(
            "homepage_section_length",
            "error",
            "homepage_section_min_characters",
            "首页摘要 section 下限不能高于上限",
        ))
    structure_contract = _text(pack.get("public_section_structure_contract"))
    if structure_contract and structure_contract != PUBLIC_SECTION_STRUCTURE_CONTRACT:
        report.issues.append(
            ContractIssue(
                "public_section_structure_contract",
                "error",
                "public_section_structure_contract",
                f"不支持的公开章节结构合同 {structure_contract!r}",
            )
        )
    require_structured_sections = (
        structure_contract == PUBLIC_SECTION_STRUCTURE_CONTRACT
    )
    for index, section in enumerate(pack.get("sections", [])):
        body = _text(section.get("body_markdown"))
        visible_character_count = public_markdown_character_count(body)
        review_status = _text(section.get("review_status"))
        if review_status and review_status not in SUPPLEMENT_REVIEW_STATUS_VALUES:
            report.issues.append(
                ContractIssue(
                    "entity_state_enum",
                    "error",
                    f"sections[{index}].review_status",
                    "章节审查状态与 live DB 枚举不兼容",
                )
            )
        report.issues.extend(_public_body_issues(body, f"sections[{index}].body_markdown"))
        if require_structured_sections:
            report.issues.extend(
                _structured_public_body_issues(
                    body,
                    f"sections[{index}].body_markdown",
                )
            )
        if not legacy and not section.get("evidence_ref_uri_list"):
            report.issues.append(ContractIssue("section_evidence_missing", "error", f"sections[{index}]", "公开正文 section 必须绑定证据索引"))
        if not legacy:
            _validate_source_ref_uris(
                report,
                section.get("evidence_ref_uri_list"),
                path=f"sections[{index}].evidence_ref_uri_list",
                source_groups=source_groups,
                required=False,
            )
        if not legacy and visible_character_count < homepage_min:
            report.issues.append(ContractIssue("section_depth", "error", f"sections[{index}]", f"首页摘要 section 少于下限 {homepage_min} 字符"))
        if not legacy and homepage_max is not None and visible_character_count > homepage_max:
            report.issues.append(ContractIssue("section_length", "error", f"sections[{index}]", f"首页摘要 section 超过上限 {homepage_max} 字符"))
    entity_section_keys: set[str] = set()
    for index, section in enumerate(pack.get("entity_sections", [])):
        body = _text(section.get("body_markdown"))
        review_status = _text(section.get("review_status"))
        if review_status and review_status not in SUPPLEMENT_REVIEW_STATUS_VALUES:
            report.issues.append(
                ContractIssue(
                    "entity_state_enum",
                    "error",
                    f"entity_sections[{index}].review_status",
                    "章节审查状态与 live DB 枚举不兼容",
                )
            )
        report.issues.extend(_public_body_issues(body, f"entity_sections[{index}].body_markdown"))
        if require_structured_sections:
            report.issues.extend(
                _structured_public_body_issues(
                    body,
                    f"entity_sections[{index}].body_markdown",
                )
            )
        if section.get("entity_key") not in entity_by_key:
            report.issues.append(ContractIssue("entity_section_unknown", "error", f"entity_sections[{index}]", "引用未知 entity_key"))
        else:
            entity_section_keys.add(_text(section.get("entity_key")))
        if not legacy and not section.get("evidence_ref_uri_list"):
            report.issues.append(ContractIssue("section_evidence_missing", "error", f"entity_sections[{index}]", "实体正文必须绑定证据索引"))
        if not legacy:
            _validate_source_ref_uris(
                report,
                section.get("evidence_ref_uri_list"),
                path=f"entity_sections[{index}].evidence_ref_uri_list",
                source_groups=source_groups,
                required=False,
            )
        if not legacy and len(body) < entity_min:
            report.issues.append(ContractIssue("entity_section_depth", "error", f"entity_sections[{index}]", f"正文少于兜底下限 {entity_min} 字符"))
    if not legacy:
        for entity_key in sorted(set(entity_keys) - entity_section_keys):
            report.issues.append(ContractIssue("entity_section_missing", "error", f"entity[{entity_key}]", "每个研究实体必须有独立回答问题的正文 section"))

        for index, visual in enumerate(pack.get("visuals", [])):
            if not isinstance(visual, dict):
                report.issues.append(ContractIssue("evidence_ref_format", "error", f"visuals[{index}]", "visual 必须是对象"))
                continue
            _validate_source_ref_uris(
                report,
                visual.get("evidence_ref_uri_list"),
                path=f"visuals[{index}].evidence_ref_uri_list",
                source_groups=source_groups,
                required=True,
            )
        for index, signal in enumerate(pack.get("early_signals", [])):
            if not isinstance(signal, dict):
                report.issues.append(ContractIssue("evidence_ref_format", "error", f"early_signals[{index}]", "early signal 必须是对象"))
                continue
            _validate_source_ref_uris(
                report,
                signal.get("evidence_ref_uri_list"),
                path=f"early_signals[{index}].evidence_ref_uri_list",
                source_groups=source_groups,
                required=True,
            )

    records = _review_records(pack)
    canonical_review_stages = set(profile.get("review", {}).get("canonical_review_stages", []))
    for index, record in enumerate(records if not legacy else []):
        record_path = f"review_records[{index}]"
        for field_name in (
            "stage", "reviewer_role", "reviewer_id", "review_kind", "verdict",
            "reconciliation_status", "input_artifact_hash", "output_artifact_hash",
        ):
            if not _text(record.get(field_name)):
                report.issues.append(ContractIssue("review_record_field", "error", f"{record_path}.{field_name}", "字段不能为空"))
        for field_name in ("input_artifact_hash", "output_artifact_hash"):
            if _text(record.get(field_name)) and not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", _text(record.get(field_name))):
                report.issues.append(ContractIssue(
                    "review_artifact_hash",
                    "error",
                    f"{record_path}.{field_name}",
                    "artifact hash 必须是 sha256:<64位十六进制>",
                ))
        if _text(record.get("stage")) not in canonical_review_stages:
            report.issues.append(ContractIssue("review_stage", "error", record_path, f"未知 review stage: {record.get('stage')!r}"))
        if _text(record.get("review_kind")) not in {"independent", "human", "deterministic"}:
            report.issues.append(ContractIssue("review_kind", "error", record_path, "review_kind 必须是 independent、human 或 deterministic"))
        if _text(record.get("verdict")).upper() not in {"GREEN", "YELLOW", "RED"}:
            report.issues.append(ContractIssue("review_verdict", "error", record_path, "verdict 非法"))
        if _text(record.get("reconciliation_status")) not in {"pending", "resolved", "deferred_to_user", "blocked", "not_applicable"}:
            report.issues.append(ContractIssue("review_reconciliation", "error", record_path, "reconciliation_status 非法"))
        if not isinstance(record.get("findings"), list):
            report.issues.append(ContractIssue("review_findings", "error", record_path, "findings 必须是数组"))
    if publication_mode == "publish":
        review_signals = ["public_ui"]
        if market_count:
            review_signals.append("market_linked")
        if any(_text(target.get("target_type")) == "security" for target in targets):
            review_signals.append("security_target")
        required_stages = set(publish_review_stages("c", review_signals))
        latest: dict[str, dict[str, Any]] = {}
        for record in records:
            stage = _text(record.get("stage"))
            if stage:
                latest[stage] = record
        missing = sorted(required_stages - set(latest))
        if missing:
            report.issues.append(ContractIssue(
                "review_records_missing",
                "error",
                "review_records",
                f"发布缺少 reviewer stage: {missing}；静态 workflow_review_contract 不能替代执行记录。",
            ))
        for stage in sorted(required_stages & set(latest)):
            record = latest[stage]
            if _text(record.get("verdict")).upper() != "GREEN":
                report.issues.append(ContractIssue("review_not_green", "error", f"review_records.{stage}", "最新 verdict 不是 GREEN"))
            if _text(record.get("reconciliation_status")) not in {"resolved", "not_applicable"}:
                report.issues.append(ContractIssue("review_unresolved", "error", f"review_records.{stage}", "review findings 未完成 reconciliation"))
            if not _text(record.get("input_artifact_hash")):
                report.issues.append(ContractIssue("review_input_hash", "error", f"review_records.{stage}", "缺少 reviewer 输入 artifact hash"))
            allowed_kinds = {"deterministic", "independent", "human"} if stage == "browser" else {"independent", "human"}
            if _text(record.get("review_kind")) not in allowed_kinds:
                report.issues.append(ContractIssue(
                    "review_kind",
                    "error",
                    f"review_records.{stage}",
                    f"{stage} reviewer 类型必须是 {sorted(allowed_kinds)}",
                ))
        final_record = latest.get("final")
        if final_record and _text(final_record.get("review_kind")) not in {"independent", "human"}:
            report.issues.append(ContractIssue("final_review_kind", "error", "review_records.final", "final reviewer 必须是 independent 或 human"))
        if legacy:
            report.issues.append(ContractIssue("legacy_publish", "error", "pack_schema_version", "legacy pack 必须先升级为 V2 才能重新发布"))

    sources_with_explicit_roles = [
        source for source in sources if _text(source.get("policy_evidence_role"))
    ]
    core_sources = (
        [
            source
            for source in sources
            if _text(source.get("policy_evidence_role")) == "core_evidence"
        ]
        if sources_with_explicit_roles
        else sources
    )
    report.metrics = {
        "source_count": len(sources),
        "independent_source_group_count": len({group for group in source_groups.values() if group}),
        "core_independent_source_group_count": len(
            {
                source_groups.get(_text(source.get("ref")))
                for source in core_sources
                if source_groups.get(_text(source.get("ref")))
            }
        ),
        "parallel_data_point_count": len(data_points),
        "entity_count": len(entities),
        "market_linked_entity_count": market_count,
        "theory_research_entity_count": theory_count,
        "factor_count": factor_count,
        "target_count": len(targets),
        "review_record_count": len(records),
        "legacy": legacy,
    }
    return report
