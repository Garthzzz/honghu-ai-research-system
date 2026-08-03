from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

ENUMS: dict[str, tuple[str, ...]] = {
    "entity_type": (
        "theme", "industry", "segment", "product_material", "process_step",
        "application", "customer", "company", "security", "geography",
    ),
    "taxonomy_level": (
        "theme", "industry", "segment", "product_material", "process_step",
        "application", "customer", "company", "security", "geography",
    ),
    "mapping_type": (
        "direct_mass_supply", "direct_small_batch", "qualified_testing",
        "indirect_supply", "upstream_raw_material", "downstream_customer_link",
        "global_peer", "theme_mapping_only", "unverified", "not_applicable",
    ),
    "run_mode": (
        "c_open", "c_open_with_seed", "c_paper", "c_hybrid",
        "c_paper_scoring_ready", "needs_problem_rewrite",
    ),
    "run_status": (
        "created", "intake_validated", "searching", "screening", "extracting",
        "mapping_entities", "scoring", "report_drafting", "under_review",
        "completed", "blocked", "failed", "cancelled", "archived",
    ),
    "run_readiness_status": ("draft", "reviewable", "published", "blocked", "archived"),
    "intake_material_type": ("none", "papers_folder", "research_db_reference"),
    "evidence_policy": ("freshness_first", "balanced", "accuracy_first"),
    "intake_field_origin": (
        "user_provided", "default_accepted", "user_override", "system_resolved",
        "raw_alias_normalized", "legacy_migrated",
    ),
    "policy_evidence_role": (
        "core_evidence", "early_signal_candidate", "reference_only",
        "needs_review", "rejected",
    ),
    "policy_gate_verdict": (
        "pass_core", "pass_early_signal", "pass_reference",
        "needs_review", "blocked", "rejected",
    ),
    "scoring_eligibility": (
        "core_eligible", "early_signal_only", "reference_only",
        "blocked_by_conflict", "rejected",
    ),
    "early_signal_strength_label": ("strong", "medium", "weak", "noise", "not_applicable"),
    "candidate_stage": (
        "discovered", "long_list", "candidate", "shortlist", "scoring_ready",
        "research_only", "rejected", "duplicate", "out_of_scope", "merged_to_entity",
    ),
    "factor_readiness_status": (
        "ready", "limited", "reference_only", "missing", "conflict_blocked",
        "not_applicable",
    ),
    "metric_slot_status": (
        "not_started", "candidate", "accepted", "weak_source_only", "stale_only",
        "conflict_unresolved", "not_applicable", "rejected", "used_in_factor",
    ),
    "source_tier": ("S", "A", "B", "C", "D", "unknown"),
    "source_review_status": (
        "pending", "pass", "pass_with_note", "weak_source_only", "duplicate",
        "paywalled", "stale", "conflict", "reject",
    ),
    "calculation_review_status": ("pending", "pass", "warning", "fail", "not_applicable"),
    "human_review_status": (
        "not_required", "pending", "approved", "rejected", "revised", "waived",
    ),
    "audit_issue_type": (
        "source_missing", "source_rejected", "source_conflict",
        "official_vs_media_conflict", "calculation_error", "unit_conversion_error",
        "period_conflict", "geo_scope_conflict", "capacity_definition_conflict",
        "supplier_count_definition_conflict", "duplicate_event_score", "stale_data",
        "low_coverage", "low_confidence", "ai_inference_only", "unsupported_claim",
        "theme_mapping_only", "forecast_as_fact", "cross_db_reference_stale",
        "replay_not_reproducible", "policy_gate_violation",
        "weak_signal_core_leak", "insufficient_independent_confirmation",
    ),
    "audit_severity": ("p0", "p1", "p2", "p3"),
    "event_type": (
        "price_revision", "capacity_change", "supply_disruption", "policy_control",
        "customer_validation", "long_term_contract", "customer_substitution_or_cut",
        "guidance_or_analyst_revision", "accounting_impairment",
        "clarification_denial", "market_reaction", "customs_trade_signal", "other",
    ),
    "event_category": (
        "fundamental", "market", "risk", "forecast_overlay", "reference_only",
        "veto_candidate",
    ),
    "event_direction": ("positive", "negative", "neutral", "mixed", "unknown", "not_applicable"),
    "veto_status": ("safe", "unknown", "warning", "triggered", "not_applicable"),
    "market_reflection_state": (
        "unnoticed", "early_reaction", "recognized", "crowded", "overheated",
        "post_hype_reset", "market_data_missing", "not_applicable",
    ),
    "research_bias_label": (
        "strong_positive_research", "positive_research", "neutral_watch",
        "negative_watch", "avoid_or_reject", "unrated_insufficient_evidence",
    ),
    "export_status": (
        "queued", "rendering_html", "rendering_assets", "rendering_pdf",
        "completed", "failed", "cancelled", "expired",
    ),
    "maturation_status": (
        "seed", "evidence_supported", "scoring_ready", "scoring_limited",
        "research_only", "scored", "review_ready", "published", "blocked",
        "superseded", "rejected", "archived",
    ),
    "ab_reference_usage": (
        "seed", "supporting", "stale_reference", "market_reference",
        "sentiment_reference", "rejected",
    ),
    "support_status": (
        "supported", "partially_supported", "derived", "forecast", "weak",
        "unsupported", "conflict", "not_applicable",
    ),
    "veto_code": (
        "veto.tech_substitution", "veto.capacity_flood", "veto.imbalance_too_short",
        "veto.customer_backup_selfdev", "veto.policy_market_shutdown",
    ),
    "score_batch_status": ("draft", "completed", "failed", "superseded", "replayed"),
    "score_status": (
        "complete", "insufficient_evidence", "blocked", "not_applicable",
        "superseded", "failed",
    ),
    "score_grade": ("S", "A", "B", "C", "D", "F", "unrated"),
    "rating_status": (
        "valid", "review_required", "blocked", "superseded", "not_applicable",
        "unrated_insufficient_evidence",
    ),
    "score_quality_label": (
        "high_confidence", "medium_confidence", "provisional",
        "unrated_insufficient_evidence", "review_required",
    ),
    "score_effect": (
        "none", "mapped_only", "factor_delta_small", "factor_delta_medium",
        "factor_delta_large", "veto_candidate", "forecast_overlay", "market_only",
        "reference_only",
    ),
    "official_confirmation_status": (
        "official_confirmed", "official_denied", "media_reported",
        "multi_source_reported", "single_source_reported", "rumor_unconfirmed",
        "not_applicable", "unknown",
    ),
    "search_task_status": (
        "planned", "running", "completed", "skipped_not_applicable", "failed",
        "cancelled", "blocked",
    ),
    "search_log_decision": (
        "identified", "screened", "included", "excluded", "duplicate", "paywalled",
        "unreachable", "not_applicable",
    ),
    "claim_evidence_status": (
        "extracted", "verified", "needs_review", "weak_source_only", "conflict",
        "rejected", "superseded", "not_applicable",
    ),
    "value_status": (
        "available", "available_with_grade_unknown", "available_text_only",
        "calculated", "stale_but_usable", "not_disclosed_with_source",
        "not_found_after_search", "weak_source_only", "stale_only",
        "conflict_unresolved", "unsupported", "rejected", "not_applicable",
    ),
    "relationship_status": ("verified", "probable", "weak", "rejected", "not_applicable", "unknown_pending_review"),
    "review_status": (
        "pending", "in_review", "approved", "rejected", "resolved", "waived",
        "reopened", "not_required",
    ),
    "audit_issue_status": ("open", "in_review", "resolved", "waived", "reopened"),
    "claim_next_action": (
        "route_to_data_point", "route_to_event", "route_to_forecast_overlay",
        "route_to_supplement_request", "use_as_background", "reject", "no_action",
    ),
    "priority": ("p0", "p1", "p2", "p3"),
    "blocking_status": (
        "blocks_scoring", "limits_scoring", "blocks_publication", "non_blocking",
        "unknown_pending_review",
    ),
    "handoff_status": (
        "draft", "research_pack_ready", "scoring_ready", "scoring_limited",
        "research_only", "blocked", "superseded",
    ),
    "review_decision": ("approve", "reject", "request_revision", "waive", "resolve", "reopen", "no_decision"),
    "review_verdict": ("GREEN", "YELLOW", "RED"),
    "reconciliation_status": ("pending", "resolved", "deferred_to_user", "blocked", "not_applicable"),
    "replay_status": ("pending", "passed", "failed", "not_applicable"),
    "preliminary_research_priority_label": (
        "high_priority_for_scoring", "medium_priority_for_followup",
        "low_priority_watch", "research_only_insufficient_data",
        "research_only_literature_review_complete", "reject_or_out_of_scope",
    ),
    "export_type": ("pdf", "html_snapshot", "artifact_manifest"),
    "export_scope": ("run_report", "entity_lens", "audit_appendix", "full_package"),
    "red_flag_level": ("none", "yellow", "red"),
    "flag_derivation_source": ("system", "human_override", "system_with_human_override"),
    "event_scope": ("business", "system_provenance"),
    "system_event_type": (
        "run_state_transition", "search_task_status", "source_screening_decision",
        "entity_promotion", "score_batch_completed", "audit_issue_status_change",
        "supplement_request_status_change", "export_status_change", "replay_result",
        "human_review_decision", "other_system",
    ),
    "benchmark_region": ("CN_A", "HK", "US", "JP", "KR", "proxy", "not_applicable", "unknown"),
    "proxy_mapping_status": (
        "not_required", "evidence_supported", "insufficient_evidence",
        "not_applicable", "rejected",
    ),
}

STATUS_FIELD_TO_ENUM = {
    "run_status": "run_status",
    "run_readiness_status": "run_readiness_status",
    "intake_material_type": "intake_material_type",
    "evidence_policy": "evidence_policy",
    "policy_evidence_role": "policy_evidence_role",
    "policy_gate_verdict": "policy_gate_verdict",
    "scoring_eligibility": "scoring_eligibility",
    "early_signal_strength_label": "early_signal_strength_label",
    "candidate_stage": "candidate_stage",
    "factor_readiness_status": "factor_readiness_status",
    "metric_slot_status": "metric_slot_status",
    "source_review_status": "source_review_status",
    "calculation_review_status": "calculation_review_status",
    "human_review_status": "human_review_status",
    "audit_severity": "audit_severity",
    "event_direction": "event_direction",
    "veto_status": "veto_status",
    "market_reflection_state": "market_reflection_state",
    "research_bias_label": "research_bias_label",
    "export_status": "export_status",
    "maturation_status": "maturation_status",
    "ab_reference_usage": "ab_reference_usage",
    "support_status": "support_status",
    "score_batch_status": "score_batch_status",
    "score_status": "score_status",
    "score_grade": "score_grade",
    "rating_status": "rating_status",
    "score_quality_label": "score_quality_label",
    "score_effect": "score_effect",
    "official_confirmation_status": "official_confirmation_status",
    "search_task_status": "search_task_status",
    "search_log_decision": "search_log_decision",
    "claim_evidence_status": "claim_evidence_status",
    "value_status": "value_status",
    "relationship_status": "relationship_status",
    "review_status": "review_status",
    "audit_issue_status": "audit_issue_status",
    "priority": "priority",
    "blocking_status": "blocking_status",
    "handoff_status": "handoff_status",
    "review_decision": "review_decision",
    "review_verdict": "review_verdict",
    "reconciliation_status": "reconciliation_status",
    "replay_status": "replay_status",
    "export_type": "export_type",
    "export_scope": "export_scope",
    "red_flag_level": "red_flag_level",
    "flag_derivation_source": "flag_derivation_source",
    "event_scope": "event_scope",
    "system_event_type": "system_event_type",
    "benchmark_region": "benchmark_region",
    "proxy_mapping_status": "proxy_mapping_status",
}

TRANSITION_ENUM_BY_OBJECT_TYPE = {
    "run": "run_status",
    "audit_issue": "audit_issue_status",
    "supplement_request": "review_status",
    "score_batch": "score_batch_status",
    "export_job": "export_status",
    "replay_record": "replay_status",
    "entity_maturation": "maturation_status",
    "search_task": "search_task_status",
    "review_queue": "review_status",
    "handoff_package": "handoff_status",
}

RUN_TRANSITIONS = {
    "created": {"intake_validated", "blocked", "failed", "cancelled"},
    "intake_validated": {"searching", "blocked", "failed", "cancelled"},
    "searching": {"screening", "blocked", "failed", "cancelled"},
    "screening": {"extracting", "blocked", "failed", "cancelled"},
    "extracting": {"mapping_entities", "blocked", "failed", "cancelled"},
    "mapping_entities": {"scoring", "report_drafting", "blocked", "failed", "cancelled"},
    "scoring": {"report_drafting", "blocked", "failed", "cancelled"},
    "report_drafting": {"under_review", "blocked", "failed", "cancelled"},
    "under_review": {"completed", "blocked", "failed", "cancelled"},
    "completed": {"archived"},
    "blocked": {"archived"},
    "failed": {"archived"},
    "cancelled": {"archived"},
    "archived": set(),
}

GENERIC_REVIEW_TRANSITIONS = {
    "pending": {"in_review", "resolved", "waived", "rejected", "approved"},
    "in_review": {"approved", "rejected", "resolved", "waived"},
    "approved": {"reopened"},
    "rejected": {"reopened"},
    "resolved": {"reopened"},
    "waived": {"reopened"},
    "reopened": {"in_review", "resolved", "waived"},
    "not_required": set(),
}

AUDIT_TRANSITIONS = {
    "open": {"in_review", "resolved", "waived"},
    "in_review": {"resolved", "waived", "open"},
    "resolved": {"reopened"},
    "waived": {"reopened"},
    "reopened": {"in_review", "resolved", "waived"},
}

URI_TABLES = {
    "intake_contract": "opportunity_intake_contract",
    "source": "opportunity_source",
    "data_point": "opportunity_data_point",
    "entity": "opportunity_entity",
    "metric_slot": "opportunity_metric_slot",
    "score_batch": "opportunity_score_batch",
    "factor_score": "opportunity_factor_score",
    "composite_score": "opportunity_composite_score",
    "source_cluster": "opportunity_source_cluster",
    "event": "opportunity_event_ledger",
    "audit_issue": "opportunity_audit_issue",
    "supplement_request": "opportunity_supplement_request",
    "visual_block": "opportunity_visual_block",
    "early_signal": "opportunity_early_signal_aggregate",
    "investment_target": "opportunity_entity_investment_target",
    "target_data_point": "opportunity_target_data_point",
}

AB_URI_TABLES = {
    "research.source": ("research", "source"),
    "research.data_point": ("research", "industry_data_point"),
    "research.industry_data_point": ("research", "industry_data_point"),
    "research.company": ("research", "company"),
    "sentiment.stock_kline": ("sentiment", "stock_kline"),
    "sentiment.senti_post": ("sentiment", "senti_post"),
}

HISTORICAL_ALIASES = {
    "score_ready": "scoring_ready",
    "reviewed": "review_ready_or_published",
    "promoted_to_entity": "merged_to_entity",
    "rating": "score_grade",
    "reviewer_status": "review_status",
    "event_review_status": "review_status",
}


@dataclass(frozen=True)
class EnumCheck:
    enum_name: str
    value: str

    @property
    def valid(self) -> bool:
        return self.value in ENUMS[self.enum_name]


def values(enum_name: str) -> tuple[str, ...]:
    return ENUMS[enum_name]


def has_enum(enum_name: str) -> bool:
    return enum_name in ENUMS


def assert_known_enum(enum_name: str) -> None:
    if enum_name not in ENUMS:
        raise KeyError(f"未知枚举：{enum_name}")


def is_valid(enum_name: str, value: str | None) -> bool:
    return value is not None and enum_name in ENUMS and str(value) in ENUMS[enum_name]


def require_enum(enum_name: str, value: str) -> str:
    assert_known_enum(enum_name)
    if value not in ENUMS[enum_name]:
        raise ValueError(f"{value!r} 不是 {enum_name} 的合法取值")
    return value


def enum_sql_check(column: str, enum_name: str) -> str:
    vals = ", ".join("'" + v.replace("'", "''") + "'" for v in ENUMS[enum_name])
    return f"CHECK ({column} IN ({vals}))"


def all_status_fields() -> set[str]:
    return set(STATUS_FIELD_TO_ENUM)


def registry_snapshot() -> dict[str, list[str]]:
    return {k: list(v) for k, v in sorted(ENUMS.items())}


def ensure_no_unregistered_status_fields(fields: Iterable[str]) -> None:
    missing = [f for f in fields if f.endswith("_status") and f not in STATUS_FIELD_TO_ENUM]
    if missing:
        raise ValueError(f"未注册的状态字段：{', '.join(sorted(missing))}")
