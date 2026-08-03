from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from .config import brief_contract_version, contract_version, resolve_track_config
from .model_routing import route_modeling_skills, routing_obligations
from .search_channels import build_search_plan


def _normal_key(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").lower())


@dataclass(frozen=True)
class Requirement:
    requirement_id: str
    question: str
    origin: str
    priority: str = "required"
    output_hint: str | None = None
    acceptance_criteria: str | None = None


@dataclass
class ResearchBrief:
    track: str
    title: str
    research_question: str
    requirements: list[Requirement]
    decision_use: str | None = None
    must_include: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    special_constraints: list[str] = field(default_factory=list)
    scope: dict[str, Any] = field(default_factory=dict)
    time_window: dict[str, Any] = field(default_factory=dict)
    required_artifacts: list[str] = field(default_factory=list)
    quality_floor: dict[str, Any] = field(default_factory=dict)
    modeling_routes: list[dict[str, Any]] = field(default_factory=list)
    modeling_obligations: list[str] = field(default_factory=list)
    search_plan: dict[str, Any] = field(default_factory=dict)
    brief_version: str = field(default_factory=brief_contract_version)
    workflow_contract_version: str = field(default_factory=contract_version)

    def as_dict(self) -> dict:
        payload = asdict(self)
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload["brief_hash"] = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return payload


def _requirement_id(question: str) -> str:
    digest = hashlib.sha1(_normal_key(question).encode("utf-8")).hexdigest()[:12]
    return f"req.{digest}"


def _unique_text(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        normalized = _normal_key(text)
        if text and normalized not in seen:
            seen.add(normalized)
            result.append(text)
    return result


def compile_research_brief(
    *,
    track: str,
    title: str,
    research_question: str,
    prompt_requirements: Iterable[str | dict[str, Any]] = (),
    decision_use: str | None = None,
    must_include: Iterable[str] = (),
    exclusions: Iterable[str] = (),
    special_constraints: Iterable[str] = (),
    scope: dict[str, Any] | None = None,
    time_window: dict[str, Any] | None = None,
    required_artifacts: Iterable[str] | None = None,
    quality_floor: dict[str, Any] | None = None,
    require_skill_files: bool = True,
) -> ResearchBrief:
    """Compile once; only exact-normalized duplicates are merged automatically."""
    key = str(track or "").strip().lower()
    profile = resolve_track_config(key)
    candidates: list[tuple[str, str, str | None, str | None]] = []
    if key in {"a", "b"}:
        candidates.extend(("default", item, None, None) for item in profile.get("default_coverage", []))
    for item in prompt_requirements:
        if isinstance(item, dict):
            question = str(item.get("question") or item.get("requirement") or "").strip()
            output_hint = str(item.get("output_hint") or "").strip() or None
            acceptance = str(item.get("acceptance_criteria") or "").strip() or None
        else:
            question = str(item).strip()
            output_hint = None
            acceptance = None
        if question:
            candidates.append(("prompt", question, output_hint, acceptance))

    requirements: list[Requirement] = []
    seen: dict[str, int] = {}
    for origin, question, output_hint, acceptance in candidates:
        normalized = _normal_key(question)
        if not normalized:
            continue
        if normalized in seen:
            existing = requirements[seen[normalized]]
            merged_origin = "default+prompt" if {existing.origin, origin} & {"default", "default+prompt"} and origin == "prompt" else existing.origin
            requirements[seen[normalized]] = Requirement(
                existing.requirement_id,
                existing.question,
                merged_origin,
                existing.priority,
                output_hint or existing.output_hint,
                acceptance or existing.acceptance_criteria,
            )
            continue
        seen[normalized] = len(requirements)
        requirements.append(Requirement(_requirement_id(question), question, origin, "required", output_hint, acceptance))

    if key == "b" and not any(item.origin in {"prompt", "default+prompt"} for item in requirements):
        raise ValueError("B 轨必须包含非空 prompt requirements")
    if not str(research_question or "").strip():
        raise ValueError("research_question 不能为空")
    resolved_quality_floor = dict(profile.get("fallback_minimum_characters", {}))
    for floor_key, floor_value in (quality_floor or {}).items():
        existing = resolved_quality_floor.get(floor_key)
        if isinstance(existing, (int, float)) and isinstance(floor_value, (int, float)):
            resolved_quality_floor[floor_key] = max(existing, floor_value)
        else:
            resolved_quality_floor[floor_key] = floor_value
    resolved_artifacts = _unique_text(required_artifacts or profile.get("public_artifacts", []))
    routes = route_modeling_skills(
        track=key,
        title=str(title or research_question).strip(),
        research_question=str(research_question).strip(),
        requirements=[item.question for item in requirements],
        required_artifacts=resolved_artifacts,
        require_skill_files=require_skill_files,
    )
    search_plan = build_search_plan(
        track=key,
        research_question=str(research_question).strip(),
        requirement_questions=[item.question for item in requirements],
    )
    return ResearchBrief(
        track=key,
        title=str(title or research_question).strip(),
        research_question=str(research_question).strip(),
        requirements=requirements,
        decision_use=str(decision_use or "").strip() or None,
        must_include=_unique_text(must_include),
        exclusions=_unique_text(exclusions),
        special_constraints=_unique_text(special_constraints),
        scope=dict(scope or {}),
        time_window=dict(time_window or {}),
        required_artifacts=resolved_artifacts,
        quality_floor=resolved_quality_floor,
        modeling_routes=[item.as_dict() for item in routes],
        modeling_obligations=routing_obligations(routes),
        search_plan=search_plan,
    )
