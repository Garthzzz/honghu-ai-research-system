from __future__ import annotations

"""Build independent report-library and public-web search plans."""

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .config import resolve_track_config


@dataclass(frozen=True)
class SearchTask:
    task_id: str
    source_channel: str
    axis_key: str
    query_text: str
    round: int = 1
    gap_trigger: str | None = None
    budget: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_search_plan(
    *,
    track: str,
    research_question: str,
    requirement_questions: Iterable[str],
) -> dict[str, Any]:
    profile = resolve_track_config(track)
    contract = profile.get("search_channels", {})
    channels = ["report", "web"]
    axes = [research_question, *requirement_questions]
    unique_axes = list(dict.fromkeys(str(item).strip() for item in axes if str(item).strip()))
    tasks: list[SearchTask] = []
    budgets = contract.get("default_budget_per_axis", {"report": 4, "web": 6})
    for channel in channels:
        for index, axis in enumerate(unique_axes, start=1):
            tasks.append(SearchTask(
                task_id=f"search.r1.{channel}.{index:03d}",
                source_channel=channel,
                axis_key=f"question_axis_{index:03d}",
                query_text=axis,
                budget=int(budgets.get(channel, 0)),
            ))
    return {
        "channels": channels,
        "merge_stage": "analysis_only",
        "report_hit_may_suppress_web": False,
        "report_provider_contract": list(contract.get("report_providers") or []),
        "tasks": [task.as_dict() for task in tasks],
        "second_round_contract": {
            "trigger": "first_round_analysis_gap",
            "preserve_source_channel": True,
            "require_gap_trigger": True,
        },
    }


def build_gap_search_tasks(
    *,
    gaps: Iterable[dict[str, Any]],
    start_index: int = 1,
    budget_by_channel: dict[str, int] | None = None,
) -> list[SearchTask]:
    budgets = budget_by_channel or {"report": 2, "web": 4}
    tasks: list[SearchTask] = []
    index = start_index
    for gap in gaps:
        gap_id = str(gap.get("gap_id") or "").strip()
        query = str(gap.get("query") or gap.get("question") or "").strip()
        channels = list(gap.get("channels") or ("report", "web"))
        if not gap_id or not query:
            raise ValueError("二次搜索 gap 必须有 gap_id 和 query")
        for channel in channels:
            if channel not in {"report", "web"}:
                raise ValueError(f"非法搜索渠道：{channel}")
            tasks.append(SearchTask(
                task_id=f"search.r2.{channel}.{index:03d}",
                source_channel=channel,
                axis_key=str(gap.get("axis_key") or gap_id),
                query_text=query,
                round=2,
                gap_trigger=gap_id,
                budget=int(budgets.get(channel, 0)),
            ))
            index += 1
    return tasks
