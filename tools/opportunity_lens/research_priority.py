from __future__ import annotations


def clamp_score(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def priority_label(score: float | None, verification_debt_count: int = 0) -> str:
    if score is None:
        return "research_only_insufficient_data"
    if verification_debt_count >= 3:
        return "medium_priority_for_followup"
    if score >= 75:
        return "high_priority_for_scoring"
    if score >= 55:
        return "medium_priority_for_followup"
    if score >= 35:
        return "low_priority_watch"
    return "research_only_insufficient_data"


def compute_research_priority_score(
    *,
    core_score: float | None,
    early_signal_score: float | None,
    verification_debt_count: int,
) -> float | None:
    if core_score is None and early_signal_score is None:
        return None
    core_component = 0.0 if core_score is None else float(core_score) * 0.55
    signal_component = 0.0 if early_signal_score is None else float(early_signal_score) * 0.35
    evidence_bonus = 10.0 if core_score is not None else 0.0
    debt_penalty = min(25.0, verification_debt_count * 5.0)
    return round(clamp_score(core_component + signal_component + evidence_bonus - debt_penalty), 4)
