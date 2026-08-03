from __future__ import annotations

import json
import sqlite3
from statistics import fmean

from .constants import EARLY_SIGNAL_RULE_VERSION
from .research_priority import compute_research_priority_score, priority_label
from .validators import validate_enum


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def _strength_label(score: float | None) -> str:
    if score is None:
        return "not_applicable"
    if score >= 75:
        return "strong"
    if score >= 50:
        return "medium"
    if score >= 25:
        return "weak"
    return "noise"


def _early_score(slot_count: int, source_count: int, independent_source_count: int, confidence: float, debt: int) -> float | None:
    if slot_count <= 0:
        return None
    base = min(45.0, slot_count * 14.0) + min(20.0, source_count * 8.0) + min(20.0, independent_source_count * 12.0)
    confidence_part = max(0.0, min(1.0, confidence)) * 20.0
    debt_penalty = min(30.0, debt * 6.0)
    return round(max(0.0, min(100.0, base + confidence_part - debt_penalty)), 4)


def aggregate_run_early_signals(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    early_signal_rule_version: str = EARLY_SIGNAL_RULE_VERSION,
) -> list[int]:
    """聚合 early_signal_only 证据，不修改核心评分表。"""
    run = conn.execute("SELECT evidence_policy FROM opportunity_run WHERE id=?", (run_id,)).fetchone()
    if not run:
        raise KeyError(run_id)
    evidence_policy = validate_enum("evidence_policy", run["evidence_policy"] or "balanced")
    rows = conn.execute(
        """
        SELECT
          ms.entity_id,
          ms.id AS slot_id,
          ms.slot_confidence,
          ms.evidence_ref_uri,
          ms.policy_gate_verdict,
          ms.policy_evidence_role,
          dp.source_id,
          s.source_cluster_id
        FROM opportunity_metric_slot ms
        LEFT JOIN opportunity_data_point dp ON dp.id=ms.selected_data_point_id
        LEFT JOIN opportunity_source s ON s.id=dp.source_id
        WHERE ms.run_id=? AND ms.scoring_eligibility='early_signal_only'
        ORDER BY ms.entity_id, ms.id
        """,
        (run_id,),
    ).fetchall()
    by_entity: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        by_entity.setdefault(int(row["entity_id"]), []).append(row)

    output_ids: list[int] = []
    for entity_id, entity_rows in by_entity.items():
        source_ids = {row["source_id"] for row in entity_rows if row["source_id"] is not None}
        cluster_ids = {row["source_cluster_id"] for row in entity_rows if row["source_cluster_id"] is not None}
        evidence_refs = [row["evidence_ref_uri"] for row in entity_rows if row["evidence_ref_uri"]]
        debt = sum(1 for row in entity_rows if row["policy_gate_verdict"] != "pass_core")
        confidence = fmean(float(row["slot_confidence"] or 0) for row in entity_rows)
        early_score = _early_score(len(entity_rows), len(source_ids), len(cluster_ids), confidence, debt)
        core = conn.execute(
            """
            SELECT score_point FROM opportunity_composite_score
            WHERE run_id=? AND entity_id=? AND is_current=1
            ORDER BY id DESC LIMIT 1
            """,
            (run_id, entity_id),
        ).fetchone()
        core_score = core["score_point"] if core else None
        priority_score = compute_research_priority_score(
            core_score=core_score,
            early_signal_score=early_score,
            verification_debt_count=debt,
        )
        trace = {
            "run_id": run_id,
            "entity_id": entity_id,
            "slot_count": len(entity_rows),
            "source_count": len(source_ids),
            "independent_source_count": len(cluster_ids),
            "average_confidence": confidence,
            "verification_debt_count": debt,
            "core_score_snapshot": core_score,
            "core_score_changed_by_overlay": False,
            "formula": "min(100, slot_count*14 + source_count*8 + independent_source_count*12 + confidence*20 - verification_debt*6)",
        }
        row_id = int(
            conn.execute(
                """
                INSERT INTO opportunity_early_signal_aggregate(
                  run_id, entity_id, early_signal_rule_version, evidence_policy,
                  early_signal_score, early_signal_strength_label,
                  research_priority_score, research_priority_label, source_count,
                  independent_source_count, verification_debt_count,
                  core_score_snapshot, core_score_changed_by_overlay,
                  evidence_ref_uri_list_json, excluded_from_core_reason, aggregate_trace_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(run_id, entity_id, early_signal_rule_version) DO UPDATE SET
                  evidence_policy=excluded.evidence_policy,
                  early_signal_score=excluded.early_signal_score,
                  early_signal_strength_label=excluded.early_signal_strength_label,
                  research_priority_score=excluded.research_priority_score,
                  research_priority_label=excluded.research_priority_label,
                  source_count=excluded.source_count,
                  independent_source_count=excluded.independent_source_count,
                  verification_debt_count=excluded.verification_debt_count,
                  core_score_snapshot=excluded.core_score_snapshot,
                  core_score_changed_by_overlay=0,
                  evidence_ref_uri_list_json=excluded.evidence_ref_uri_list_json,
                  excluded_from_core_reason=excluded.excluded_from_core_reason,
                  aggregate_trace_json=excluded.aggregate_trace_json,
                  updated_at=datetime('now')
                """,
                (
                    run_id,
                    entity_id,
                    early_signal_rule_version,
                    evidence_policy,
                    early_score,
                    _strength_label(early_score),
                    priority_score,
                    priority_label(priority_score, debt),
                    len(source_ids),
                    len(cluster_ids),
                    debt,
                    core_score,
                    0,
                    _json(evidence_refs),
                    "policy gate 标记为 early_signal_only，不能进入核心 14 因子评分。",
                    _json(trace),
                ),
            ).lastrowid
        )
        current = conn.execute(
            """
            SELECT id FROM opportunity_early_signal_aggregate
            WHERE run_id=? AND entity_id=? AND early_signal_rule_version=?
            """,
            (run_id, entity_id, early_signal_rule_version),
        ).fetchone()
        output_ids.append(int(current["id"] if current else row_id))
    return output_ids
