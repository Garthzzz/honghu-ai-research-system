from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .config import resolve_track_config


@dataclass(frozen=True)
class ReviewTask:
    stage: str
    reason: str
    required: bool = True


def build_review_plan(
    *,
    track: str,
    artifacts: Iterable[str],
    risks: Iterable[str] = (),
) -> list[ReviewTask]:
    """Select reviewers by artifact and risk instead of running every persona every time."""
    profile = resolve_track_config(track)
    present = set(artifacts)
    risk_set = set(risks)
    tasks = [
        ReviewTask("evidence", "来源、原文、单位、时期和独立证据组必须可追溯"),
    ]
    triggers = profile.get("review", {}).get("artifact_triggers", {})
    for artifact, stage in triggers.items():
        if artifact in present:
            tasks.append(ReviewTask(stage, f"产物包含 {artifact}"))
    if risk_set & {"conflicting_sources", "new_methodology", "derived_metric", "scoring_model"}:
        tasks.append(ReviewTask("science", "存在冲突来源、新方法、派生指标或评分模型"))
    if risk_set & {"weak_source_core_claim", "single_cluster_core_claim", "stale_current_claim"}:
        tasks.append(ReviewTask("evidence_escalation", "核心结论存在证据等级、独立性或时效风险"))
    tasks.append(ReviewTask("final", "综合检查科学严谨性、投资决策效用和展示可读性"))

    deduped: list[ReviewTask] = []
    seen: set[str] = set()
    for task in tasks:
        if task.stage not in seen:
            seen.add(task.stage)
            deduped.append(task)
    return deduped
