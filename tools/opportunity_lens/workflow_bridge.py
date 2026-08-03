from __future__ import annotations

import re
from typing import Any

from tools.research_core.brief import ResearchBrief, compile_research_brief
from tools.research_core.config import publish_review_stages, resolve_track_config
from tools.research_core.manifest import (
    ExecutionManifest,
    GateResult,
    RequirementCoverage,
    ReviewRecord,
)

from .intake_parser import parse_intake_payload
from .run_pack_contract import gate_for_issue_code


def _text_values(value: Any) -> list[str]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, dict):
        result: list[str] = []
        for item in value.values():
            result.extend(_text_values(item))
        return result
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_text_values(item))
        return result
    return [item.strip() for item in re.split(r"[\r\n；;]+", str(value)) if item.strip()]


def _entity_requirement(entity: dict[str, Any]) -> dict[str, Any]:
    name = str(entity.get("display_name") or entity.get("canonical_name") or entity.get("key") or "未命名实体").strip()
    mode = str(entity.get("entity_research_mode") or "market_linked")
    if mode == "theory_research":
        acceptance = "独立回答研究问题，包含文献综述、计算或证据底稿、反方约束、结论边界和补证顺序"
    else:
        acceptance = "独立回答实体问题，完成证据、评分、标的映射、条件化建议以及证实和证伪动作"
    return {
        "question": f"完成研究实体回答：{name}",
        "output_hint": str(entity.get("key") or name),
        "acceptance_criteria": acceptance,
    }


def compile_pack_brief(
    pack: dict[str, Any],
    *,
    require_skill_files: bool = True,
) -> ResearchBrief:
    """Map an already versioned C pack into the shared ResearchBrief contract."""
    intake = parse_intake_payload(pack.get("intake") or {}, allow_legacy_alias=False)
    scope = dict(intake.get("research_scope") or {})
    special = dict(intake.get("special_constraints") or {})
    special_values = _text_values(
        special.get("text")
        if special.get("text") not in (None, "")
        else {key: value for key, value in special.items() if key != "use_default"}
    )
    requirements = [{
        "question": f"完成主研究问题：{pack['research_question']}",
        "output_hint": "run_overview",
        "acceptance_criteria": "正文直接回答主问题，给出证据关系、计算逻辑、反方约束、结论边界和后续验证动作",
    }]
    # A long-form intake may carry a manually compiled requirement matrix.  Keep
    # every item in the shared brief so publication coverage is checked against
    # the full user request, not merely the overview and entity list.  Older
    # packs do not have this optional field and retain their existing behavior.
    for item in pack.get("prompt_requirements") or []:
        if isinstance(item, dict):
            requirement = dict(item)
            requirement.setdefault("output_hint", "run_overview")
            requirements.append(requirement)
        elif str(item or "").strip():
            requirements.append(
                {
                    "question": str(item).strip(),
                    "output_hint": "run_overview",
                    "acceptance_criteria": "在公开正文中以证据、方法、分析和明确结论完整回答",
                }
            )
    requirements.extend(_entity_requirement(entity) for entity in pack.get("entities", []))

    profile = resolve_track_config("c")
    quality_profile = str(pack.get("quality_profile") or "standard").lower()
    quality_floor = (
        profile.get("deep_research_minimum_characters", {})
        if any(token in quality_profile for token in ("deep", "highest", "maximum"))
        else profile.get("fallback_minimum_characters", {})
    )
    required_artifacts = ["run_pack", "public_markdown", "public_ui"]
    if any(entity.get("entity_research_mode") == "market_linked" for entity in pack.get("entities", [])):
        required_artifacts.extend(("calculations", "scoring"))
    if any(target.get("target_type") == "security" for target in pack.get("entity_investment_targets", [])):
        required_artifacts.append("company_financials")

    return compile_research_brief(
        track="c",
        title=str(pack.get("title") or pack.get("research_question") or pack.get("slug")).strip(),
        research_question=str(pack["research_question"]).strip(),
        prompt_requirements=requirements,
        decision_use=str(pack.get("problem_statement") or "").strip() or None,
        must_include=_text_values(scope.get("must_include")),
        exclusions=_text_values(scope.get("must_exclude")),
        special_constraints=special_values,
        scope=scope,
        time_window=dict(intake.get("time_window") or {}),
        required_artifacts=required_artifacts,
        quality_floor=quality_floor,
        require_skill_files=require_skill_files,
    )


def _requirement_evidence(pack: dict[str, Any], output_hint: str | None) -> list[str]:
    if output_hint == "run_overview":
        sections = pack.get("sections", [])
    else:
        sections = [
            section for section in pack.get("entity_sections", [])
            if str(section.get("entity_key") or "") == str(output_hint or "")
        ]
    refs: list[str] = []
    for section in sections:
        for ref in section.get("evidence_ref_uri_list", []) or []:
            text = str(ref).strip()
            if text and text not in refs:
                refs.append(text)
    return refs


def build_pack_workflow_state(
    pack: dict[str, Any],
    *,
    pack_hash: str,
    publication_mode: str,
    require_skill_files: bool = True,
) -> tuple[ResearchBrief, ExecutionManifest]:
    """Build the shared state from the same validated facts used by the C database."""
    brief = compile_pack_brief(pack, require_skill_files=require_skill_files)
    normalized_hash = pack_hash if pack_hash.startswith("sha256:") else f"sha256:{pack_hash}"
    manifest = ExecutionManifest(
        run_key=str(pack["slug"]),
        track="c",
        request_ref=str(pack.get("_pack_path") or "run_pack"),
        enforce_modeling_contract=pack.get("modeling_contract_version") == "research.modeling_skills.v1",
        requirement_coverage={
            requirement.requirement_id: RequirementCoverage(requirement.requirement_id)
            for requirement in brief.requirements
        },
    )
    manifest.register_modeling_requirements(brief.modeling_routes)
    if manifest.enforce_modeling_contract:
        for item in pack.get("modeling_records", []):
            manifest.record_skill_invocation(
                skill_name=str(item.get("skill_name") or ""),
                status=str(item.get("status") or "blocked"),
                input_artifact_hash=item.get("input_artifact_hash"),
                output_artifact_hash=item.get("output_artifact_hash"),
                note=item.get("note"),
            )
        for item in pack.get("independent_model_freezes", []):
            manifest.record_independent_freeze(
                model_ref=str(item.get("model_ref") or ""),
                input_hash=str(item.get("input_hash") or ""),
                output_hash=str(item.get("output_hash") or ""),
                frozen_before_consensus=bool(item.get("frozen_before_consensus")),
            )
        for item in pack.get("external_reconciliations", []):
            manifest.record_external_reconciliation(
                model_ref=str(item.get("model_ref") or ""),
                benchmark_ref=str(item.get("benchmark_ref") or ""),
                artifact_hash=str(item.get("artifact_hash") or ""),
                status=str(item.get("status") or "blocked"),
            )
    for task in brief.search_plan.get("tasks", []):
        manifest.record_search_channel(
            task_id=str(task["task_id"]), source_channel=str(task["source_channel"]),
            status="planned", result_count=0, gap_trigger=task.get("gap_trigger"),
        )
    manifest.input_hashes[str(pack.get("_pack_path") or "run_pack")] = normalized_hash
    manifest.record_stage("intake", "completed", brief_hash=brief.as_dict()["brief_hash"])
    manifest.record_stage("contract_validation", "completed", publication_mode=publication_mode)

    validation = pack.get("_contract_validation_report") or {}
    warnings = [issue for issue in validation.get("issues", []) if issue.get("severity") == "warning"]
    findings_by_gate: dict[str, list[dict[str, Any]]] = {}
    for issue in warnings:
        findings_by_gate.setdefault(gate_for_issue_code(str(issue.get("code") or "")), []).append(issue)
    for gate in resolve_track_config("c").get("review", {}).get("deterministic_gates", []):
        findings = findings_by_gate.get(gate, [])
        manifest.record_gate(GateResult(gate, "YELLOW" if findings else "GREEN", findings, [normalized_hash]))

    review_signals = ["public_ui"]
    if any(entity.get("entity_research_mode") == "market_linked" for entity in pack.get("entities", [])):
        review_signals.append("market_linked")
    if any(target.get("target_type") == "security" for target in pack.get("entity_investment_targets", [])):
        review_signals.append("security_target")
    manifest.set_review_plan(publish_review_stages("c", review_signals))
    for item in pack.get("review_records", []):
        manifest.record_review(ReviewRecord(
            stage=str(item.get("stage") or ""),
            reviewer_role=str(item.get("reviewer_role") or item.get("stage") or "reviewer"),
            reviewer_id=item.get("reviewer_id"),
            review_kind=str(item.get("review_kind") or "independent"),
            verdict=str(item.get("verdict") or "RED").upper(),
            reconciliation_status=str(item.get("reconciliation_status") or "pending"),
            findings=list(item.get("findings") or []),
            input_artifact_hash=item.get("input_artifact_hash"),
            output_artifact_hash=item.get("output_artifact_hash"),
            input_artifact_ref=item.get("input_artifact_ref") or str(pack.get("_pack_path") or "run_pack"),
            output_artifact_ref=item.get("output_artifact_ref") or str(pack.get("_pack_path") or "run_pack"),
        ))

    artifact_ref = str(pack.get("_pack_path") or "run_pack")
    for requirement in brief.requirements:
        manifest.record_requirement_coverage(
            requirement.requirement_id,
            "completed",
            artifact_refs=[artifact_ref],
            evidence_refs=_requirement_evidence(pack, requirement.output_hint),
        )
    manifest.record_stage("pack_ready", "completed", pack_hash=normalized_hash)
    if publication_mode == "publish":
        open_p0 = sum(
            1 for issue in pack.get("audit_issues", [])
            if str(issue.get("severity") or issue.get("audit_severity") or "").lower() == "p0"
            and str(issue.get("status") or issue.get("audit_issue_status") or "open").lower() in {"open", "in_review", "reopened"}
        )
        if not manifest.evaluate_publication(open_p0=open_p0):
            raise ValueError("共享 execution manifest 发布门禁未通过: " + "；".join(manifest.publication["blockers"]))
    return brief, manifest
