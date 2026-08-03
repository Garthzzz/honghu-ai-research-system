from __future__ import annotations

from dataclasses import dataclass

from .validators import validate_enum


@dataclass(frozen=True)
class PolicyGateResult:
    policy_evidence_role: str
    policy_gate_verdict: str
    scoring_eligibility: str
    reason: str


def evaluate_policy_gate(
    *,
    evidence_policy: str,
    source_tier: str = "unknown",
    source_review_status: str = "pending",
    support_status: str = "supported",
    official_confirmation_status: str = "unknown",
    independent_source_count: int = 1,
) -> PolicyGateResult:
    """按当前证据策略契约决定证据角色。

    该 gate 只决定证据能否进入核心评分或早期信号，不直接修改任何分数。
    """
    policy = validate_enum("evidence_policy", evidence_policy)
    tier = validate_enum("source_tier", source_tier)
    review = validate_enum("source_review_status", source_review_status)
    support = validate_enum("support_status", support_status)
    confirmation = validate_enum("official_confirmation_status", official_confirmation_status)

    if review in {"reject", "duplicate", "conflict"} or support in {"unsupported", "conflict"}:
        return PolicyGateResult("rejected", "rejected", "rejected", "来源被拒绝、重复或冲突，不能进入核心分或早期信号。")
    if review in {"paywalled", "stale"}:
        return PolicyGateResult("reference_only", "pass_reference", "reference_only", "来源只适合作为背景参考。")
    if tier in {"S", "A"} and review in {"pass", "pass_with_note"}:
        return PolicyGateResult("core_evidence", "pass_core", "core_eligible", "S/A 级来源通过复核，可进入核心评分。")
    if tier == "B" and review in {"pass", "pass_with_note"} and independent_source_count >= 2:
        return PolicyGateResult("core_evidence", "pass_core", "core_eligible", "B 级来源已有独立确认，可进入核心评分。")
    if policy == "accuracy_first":
        return PolicyGateResult("needs_review", "needs_review", "reference_only", "accuracy_first 下证据不足，需补独立确认。")
    if policy in {"freshness_first", "balanced"} and tier in {"B", "C", "D", "unknown"}:
        if confirmation in {"media_reported", "single_source_reported", "rumor_unconfirmed", "unknown"}:
            return PolicyGateResult(
                "early_signal_candidate",
                "pass_early_signal",
                "early_signal_only",
                "新鲜但确认不足，只能进入早期信号，不得抬高核心因子分。",
            )
    return PolicyGateResult("reference_only", "pass_reference", "reference_only", "证据未达到核心评分门槛，仅作为参考。")


def gate_result_dict(result: PolicyGateResult) -> dict:
    return {
        "policy_evidence_role": result.policy_evidence_role,
        "policy_gate_verdict": result.policy_gate_verdict,
        "scoring_eligibility": result.scoring_eligibility,
        "reason": result.reason,
    }
