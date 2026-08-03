from __future__ import annotations

import sqlite3

from .verification_gate import evaluate_policy_gate

SOURCE_TIER_WEIGHT = {
    "S": 1.0,
    "A": 0.9,
    "B": 0.75,
    "C": 0.55,
    "D": 0.25,
    "unknown": 0.1,
}


def tier_weight(source_tier: str) -> float:
    return SOURCE_TIER_WEIGHT.get(source_tier, 0.1)


def update_source_review(
    conn: sqlite3.Connection,
    source_id: int,
    source_tier: str,
    source_review_status: str,
    note: str | None = None,
    evidence_policy: str | None = None,
    independent_source_count: int = 1,
) -> None:
    row = conn.execute(
        """
        SELECT s.run_id, r.evidence_policy
        FROM opportunity_source s
        JOIN opportunity_run r ON r.id=s.run_id
        WHERE s.id=?
        """,
        (source_id,),
    ).fetchone()
    if not row:
        raise KeyError(source_id)
    gate = evaluate_policy_gate(
        evidence_policy=evidence_policy or row["evidence_policy"] or "balanced",
        source_tier=source_tier,
        source_review_status=source_review_status,
        independent_source_count=independent_source_count,
    )
    conn.execute(
        """
        UPDATE opportunity_source
        SET source_tier=?, source_review_status=?, updated_at=datetime('now'),
            excerpt=COALESCE(?, excerpt),
            policy_evidence_role=?, policy_gate_verdict=?, scoring_eligibility=?
        WHERE id=?
        """,
        (
            source_tier,
            source_review_status,
            note,
            gate.policy_evidence_role,
            gate.policy_gate_verdict,
            gate.scoring_eligibility,
            source_id,
        ),
    )
