from __future__ import annotations

import json
import sqlite3
from statistics import fmean
from typing import Any

from .constants import (
    EARLY_SIGNAL_RULE_VERSION,
    EVIDENCE_POLICY_VERSION,
    INTAKE_CONTRACT_VERSION,
    SCORE_RULE_VERSION,
)
from .factor_dictionary import COMPANY_FACTORS, FACTOR_BY_CODE, SEGMENT_FACTORS, factors_for_entity_type
from .market_reaction import upsert_market_reaction
from .preprocessing import (
    adjusted_score,
    audit_multiplier,
    confidence_multiplier,
    coverage_multiplier,
    score_band_width,
    score_grade,
    score_quality_label,
)
from .score_trace import hash_json
from .state_registry import ENUMS


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def _open_issue_counts(conn: sqlite3.Connection, run_id: int, entity_id: int) -> tuple[int, int]:
    row = conn.execute(
        """
        SELECT
          SUM(CASE WHEN audit_severity='p0' THEN 1 ELSE 0 END) AS p0,
          SUM(CASE WHEN audit_severity='p1' THEN 1 ELSE 0 END) AS p1
        FROM opportunity_audit_issue
        WHERE run_id=? AND (entity_id=? OR entity_id IS NULL)
          AND audit_issue_status IN ('open','in_review','reopened')
        """,
        (run_id, entity_id),
    ).fetchone()
    return (int(row["p0"] or 0), int(row["p1"] or 0))


def _slot_rows(conn: sqlite3.Connection, run_id: int, entity_id: int, factor_code: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT *
            FROM opportunity_metric_slot
            WHERE run_id=? AND entity_id=? AND factor_code=?
            ORDER BY slot_key
            """,
            (run_id, entity_id, factor_code),
        )
    )


def _row_value(row: sqlite3.Row, key: str, default=None):
    return row[key] if key in row.keys() else default


def _is_core_eligible_slot(row: sqlite3.Row) -> bool:
    return (_row_value(row, "scoring_eligibility", "core_eligible") == "core_eligible")


def _run_policy_snapshot(conn: sqlite3.Connection, run_id: int) -> dict:
    intake = conn.execute(
        """
        SELECT intake_contract_hash, intake_contract_version, evidence_policy_version,
               early_signal_rule_version, evidence_policy
        FROM opportunity_intake_contract
        WHERE run_id=?
        """,
        (run_id,),
    ).fetchone()
    policy_rows = conn.execute(
        """
        SELECT scoring_eligibility, COUNT(*) AS n
        FROM opportunity_metric_slot
        WHERE run_id=?
        GROUP BY scoring_eligibility
        """,
        (run_id,),
    ).fetchall()
    early_rows = conn.execute(
        """
        SELECT COUNT(*) AS n, MAX(early_signal_score) AS max_score
        FROM opportunity_early_signal_aggregate
        WHERE run_id=?
        """,
        (run_id,),
    ).fetchone()
    return {
        "intake_contract_hash": intake["intake_contract_hash"] if intake else None,
        "intake_contract_version": intake["intake_contract_version"] if intake else INTAKE_CONTRACT_VERSION,
        "evidence_policy_version": intake["evidence_policy_version"] if intake else EVIDENCE_POLICY_VERSION,
        "early_signal_rule_version": intake["early_signal_rule_version"] if intake else EARLY_SIGNAL_RULE_VERSION,
        "evidence_policy": intake["evidence_policy"] if intake else "balanced",
        "metric_slot_scoring_eligibility_counts": {row["scoring_eligibility"]: row["n"] for row in policy_rows},
        "early_signal_snapshot": {
            "aggregate_count": int(early_rows["n"] or 0),
            "max_early_signal_score": early_rows["max_score"],
        },
    }


def _evaluate_factor(
    conn: sqlite3.Connection,
    run_id: int,
    score_batch_id: int,
    entity_id: int,
    factor_code: str,
    open_p0: int,
    open_p1: int,
) -> int:
    slots = _slot_rows(conn, run_id, entity_id, factor_code)
    factor = FACTOR_BY_CODE[factor_code]
    if not slots:
        trace = {
            "run_id": run_id,
            "entity_id": entity_id,
            "score_batch_id": score_batch_id,
            "factor_code": factor_code,
            "reason": "no metric slots",
        }
        return int(
            conn.execute(
                """
                INSERT INTO opportunity_factor_score(
                  run_id, score_batch_id, entity_id, factor_code, score_status,
                  score_raw, score_adjusted, coverage, confidence, coverage_multiplier,
                  confidence_multiplier, audit_multiplier, reliability_multiplier,
                  factor_trace_json, evidence_ref_uri_list_json, is_current
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
                """,
                (
                    run_id,
                    score_batch_id,
                    entity_id,
                    factor_code,
                    "insufficient_evidence",
                    None,
                    None,
                    0,
                    0,
                    0,
                    0,
                    0 if open_p0 else (0.85 if open_p1 else 1),
                    0,
                    _json(trace),
                    _json([]),
                ),
            ).lastrowid
        )

    applicable = [s for s in slots if s["metric_slot_status"] != "not_applicable"]
    if not applicable:
        status = "not_applicable"
        cov = conf = cm = fm = am = rel = 0.0
        raw = adj = None
        used = []
    else:
        core_applicable = [s for s in applicable if _is_core_eligible_slot(s)]
        total_weight = sum(float(s["slot_weight"] or 0) for s in core_applicable) or float(factor.weight)
        usable = [
            s for s in applicable
            if s["metric_slot_status"] in {"accepted", "used_in_factor"}
            and s["value_status"] not in {"unsupported", "rejected", "conflict_unresolved"}
            and s["slot_score"] is not None
            and _is_core_eligible_slot(s)
        ]
        usable_weight = sum(float(s["slot_weight"] or 0) for s in usable)
        cov = min(1.0, usable_weight / total_weight) if total_weight else 0.0
        if usable:
            raw = sum(float(s["slot_score"]) * float(s["slot_weight"] or 0) for s in usable) / (usable_weight or 1)
            conf = sum(float(s["slot_confidence"] or 0) * float(s["slot_weight"] or 0) for s in usable) / (usable_weight or 1)
        else:
            raw = None
            conf = 0.0
        cm = coverage_multiplier(cov)
        fm = confidence_multiplier(conf)
        am = audit_multiplier(open_p0, open_p1)
        rel = min(cm, fm, am)
        adj = adjusted_score(raw, rel) if raw is not None else None
        status = "blocked" if open_p0 else ("complete" if cov >= 0.5 and raw is not None else "insufficient_evidence")
        used = [f"opp://metric_slot/{s['id']}" for s in usable]
    excluded_non_core = [
        f"opp://metric_slot/{s['id']}"
        for s in applicable
        if not _is_core_eligible_slot(s)
    ]
    trace = {
        "run_id": run_id,
        "entity_id": entity_id,
        "score_batch_id": score_batch_id,
        "factor_code": factor_code,
        "slots": [
            {
                "slot_id": s["id"],
                "slot_key": s["slot_key"],
                "status": s["metric_slot_status"],
                "value_status": s["value_status"],
                "slot_weight": s["slot_weight"],
                "slot_score": s["slot_score"],
                "slot_confidence": s["slot_confidence"],
                "evidence_ref_uri": s["evidence_ref_uri"],
                "policy_evidence_role": _row_value(s, "policy_evidence_role"),
                "policy_gate_verdict": _row_value(s, "policy_gate_verdict"),
                "scoring_eligibility": _row_value(s, "scoring_eligibility", "core_eligible"),
            }
            for s in slots
        ],
        "included_core_inputs": used,
        "excluded_non_core_inputs": excluded_non_core,
        "coverage": cov,
        "confidence": conf,
        "coverage_multiplier": cm,
        "confidence_multiplier": fm,
        "audit_multiplier": am,
        "reliability_multiplier": rel,
    }
    return int(
        conn.execute(
            """
            INSERT INTO opportunity_factor_score(
              run_id, score_batch_id, entity_id, factor_code, score_status,
              score_raw, score_adjusted, coverage, confidence, coverage_multiplier,
              confidence_multiplier, audit_multiplier, reliability_multiplier,
              factor_trace_json, evidence_ref_uri_list_json, is_current
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
            """,
            (
                run_id,
                score_batch_id,
                entity_id,
                factor_code,
                status,
                round(raw, 4) if raw is not None else None,
                round(adj, 4) if adj is not None else None,
                round(cov, 4),
                round(conf, 4),
                round(cm, 4),
                round(fm, 4),
                round(am, 4),
                round(rel, 4),
                _json(trace),
                _json(used),
            ),
        ).lastrowid
    )


def _weighted_factor_score(rows: list[sqlite3.Row], factor_codes: tuple[str, ...]) -> float | None:
    selected = [r for r in rows if r["factor_code"] in factor_codes and r["score_adjusted"] is not None]
    if not selected:
        return None
    total = sum(FACTOR_BY_CODE[r["factor_code"]].weight for r in selected)
    return sum(float(r["score_adjusted"]) * FACTOR_BY_CODE[r["factor_code"]].weight for r in selected) / total


def _build_composite(
    conn: sqlite3.Connection,
    run_id: int,
    score_batch_id: int,
    entity: sqlite3.Row,
    open_p0: int,
    open_p1: int,
) -> int:
    rows = list(
        conn.execute(
            "SELECT * FROM opportunity_factor_score WHERE score_batch_id=? AND entity_id=?",
            (score_batch_id, entity["id"]),
        )
    )
    non_na = [r for r in rows if r["score_status"] != "not_applicable"]
    if not non_na:
        point = None
        coverage = confidence = 0.0
        status = "insufficient_evidence"
    else:
        coverage = fmean(float(r["coverage"] or 0) for r in non_na)
        confidence = fmean(float(r["confidence"] or 0) for r in non_na)
        segment_score = _weighted_factor_score(rows, tuple(f.code for f in SEGMENT_FACTORS))
        if entity["entity_type"] == "company":
            company_score = _weighted_factor_score(rows, tuple(f.code for f in COMPANY_FACTORS))
            if segment_score is not None and company_score is not None:
                point = 0.65 * segment_score + 0.35 * company_score
            else:
                point = segment_score or company_score
        else:
            point = segment_score
        status = "blocked" if open_p0 else ("complete" if point is not None and coverage >= 0.5 else "insufficient_evidence")
    am = audit_multiplier(open_p0, open_p1)
    if point is not None:
        point = adjusted_score(point, am)
    width = score_band_width(coverage, confidence, open_p1)
    grade = score_grade(point, blocked=(status == "blocked"))
    rating_status = (
        "blocked" if status == "blocked"
        else "review_required" if open_p1
        else "valid" if status == "complete"
        else "unrated_insufficient_evidence"
    )
    quality = score_quality_label(coverage, confidence, review_required=bool(open_p1))
    evidence = [f"opp://factor_score/{r['id']}" for r in rows if r["score_status"] != "not_applicable"]
    trace = {
        "run_id": run_id,
        "entity_id": entity["id"],
        "score_batch_id": score_batch_id,
        "factor_scores": evidence,
        "coverage": coverage,
        "confidence": confidence,
        "audit_multiplier": am,
        "open_p0": open_p0,
        "open_p1": open_p1,
        "score_rule_version": SCORE_RULE_VERSION,
        "policy_overlay": {
            "core_score_changed_by_overlay": False,
            "overlay_rule": "early_signal_only 不参与核心 14 因子评分，只用于研究优先级。",
        },
    }
    row = conn.execute(
        """
        INSERT INTO opportunity_composite_score(
          run_id, score_batch_id, entity_id, score_status, score_grade, rating_status,
          score_quality_label, score_point, score_band_low, score_band_high,
          band_method, band_reason, coverage, confidence, audit_multiplier,
          composite_trace_json, evidence_ref_uri_list_json, research_bias_label, is_current
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
        """,
        (
            run_id,
            score_batch_id,
            entity["id"],
            status,
            grade,
            rating_status,
            quality,
            round(point, 4) if point is not None else None,
            round(max(0, point - width), 4) if point is not None else None,
            round(min(100, point + width), 4) if point is not None else None,
            "coverage_confidence_sensitivity_v1",
            "覆盖度或置信度较弱、或存在未关闭 P1 问题时，区间会扩大。",
            round(coverage, 4),
            round(confidence, 4),
            round(am, 4),
            _json(trace),
            _json(evidence),
            "unrated_insufficient_evidence" if grade == "unrated" else ("neutral_watch" if open_p1 else "positive_research"),
        ),
    )
    composite_id = int(row.lastrowid)
    for veto_code in ENUMS["veto_code"]:
        vstatus = "not_applicable" if entity["entity_type"] not in {"company", "product_material", "segment"} else "safe"
        if open_p0 and veto_code == "veto.policy_market_shutdown":
            vstatus = "triggered"
        elif open_p1 and veto_code == "veto.capacity_flood":
            vstatus = "warning"
        conn.execute(
            """
            INSERT INTO opportunity_veto_status(
              run_id, entity_id, score_batch_id, composite_score_id, veto_code,
              veto_status, veto_reason, evidence_ref_uri
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                entity["id"],
                score_batch_id,
                composite_id,
                veto_code,
                vstatus,
                "由未关闭审计状态和 fixture 证据推导。",
                f"opp://composite_score/{composite_id}",
            ),
        )
    upsert_market_reaction(
        conn,
        run_id,
        entity["id"],
        composite_id,
        entity["entity_type"],
        entity["external_ref_type"],
    )
    replay_payload = {
        "run_id": run_id,
        "entity_id": entity["id"],
        "score_batch_id": score_batch_id,
        "composite_score_id": composite_id,
        "factor_score_ids": [r["id"] for r in rows],
        "score_point": point,
        "score_grade": grade,
    }
    conn.execute(
        """
        INSERT INTO opportunity_score_replay_record(
          run_id, entity_id, score_batch_id, composite_score_id, replay_level,
          replay_status, input_manifest_hash, factor_manifest_hash,
          source_manifest_hash, rule_manifest_hash, result_hash, replay_detail_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            run_id,
            entity["id"],
            score_batch_id,
            composite_id,
            "L2",
            "passed" if status in {"complete", "blocked"} else "not_applicable",
            hash_json(trace),
            hash_json([r["factor_code"] for r in rows]),
            hash_json(evidence),
            hash_json({"score_rule_version": SCORE_RULE_VERSION}),
            hash_json(replay_payload),
            _json(replay_payload),
        ),
    )
    return composite_id


def create_score_batch(
    conn: sqlite3.Connection,
    run_id: int,
    entity_ids: list[int] | None = None,
    score_rule_version: str = SCORE_RULE_VERSION,
) -> int:
    current = list(
        conn.execute(
            "SELECT id FROM opportunity_score_batch WHERE run_id=? AND is_current=1",
            (run_id,),
        )
    )
    policy_snapshot = _run_policy_snapshot(conn, run_id)
    input_manifest = {
        "run_id": run_id,
        "entity_ids": entity_ids,
        "score_rule_version": score_rule_version,
        "intake_contract_version": policy_snapshot["intake_contract_version"],
        "evidence_policy_version": policy_snapshot["evidence_policy_version"],
        "early_signal_rule_version": policy_snapshot["early_signal_rule_version"],
        "intake_contract_hash": policy_snapshot["intake_contract_hash"],
        "policy_gate_snapshot": policy_snapshot["metric_slot_scoring_eligibility_counts"],
        "early_signal_snapshot": policy_snapshot["early_signal_snapshot"],
    }
    batch_id = int(
        conn.execute(
            """
            INSERT INTO opportunity_score_batch(
              run_id, score_rule_version, score_batch_status, is_current,
              input_manifest_json, input_manifest_hash, rule_manifest_hash
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                run_id,
                score_rule_version,
                "draft",
                0,
                _json(input_manifest),
                hash_json(input_manifest),
                hash_json({"score_rule_version": score_rule_version}),
            ),
        ).lastrowid
    )
    try:
        params: list[Any] = [run_id]
        entity_clause = ""
        if entity_ids:
            placeholders = ",".join("?" for _ in entity_ids)
            entity_clause = f" AND e.id IN ({placeholders})"
            params.extend(entity_ids)
        entities = list(
            conn.execute(
                f"""
                SELECT e.*
                FROM opportunity_entity e
                JOIN opportunity_entity_maturation em ON em.entity_id=e.id
                LEFT JOIN opportunity_entity_research_profile erp
                  ON erp.run_id=em.run_id AND erp.entity_id=e.id
                WHERE em.run_id=?
                  AND COALESCE(erp.entity_research_mode, 'market_linked')='market_linked'
                  {entity_clause}
                ORDER BY e.id
                """,
                params,
            )
        )
        conn.execute(
            """
            UPDATE opportunity_entity_maturation
            SET maturation_status='research_only', score_batch_id=NULL,
                readiness_reason=COALESCE(readiness_reason, 'theory_research 不参与核心评分'),
                updated_at=datetime('now')
            WHERE run_id=? AND entity_id IN (
              SELECT entity_id FROM opportunity_entity_research_profile
              WHERE run_id=? AND entity_research_mode='theory_research'
            )
            """,
            (run_id, run_id),
        )
        for entity in entities:
            open_p0, open_p1 = _open_issue_counts(conn, run_id, entity["id"])
            for factor in factors_for_entity_type(entity["entity_type"]):
                _evaluate_factor(conn, run_id, batch_id, entity["id"], factor.code, open_p0, open_p1)
            composite_id = _build_composite(conn, run_id, batch_id, entity, open_p0, open_p1)
            conn.execute(
                """
                UPDATE opportunity_entity_maturation
                SET maturation_status=?, score_batch_id=?, evidence_ref_uri=?, updated_at=datetime('now')
                WHERE run_id=? AND entity_id=?
                """,
                (
                    "blocked" if open_p0 else "scored",
                    batch_id,
                    f"opp://composite_score/{composite_id}",
                    run_id,
                    entity["id"],
                ),
            )
        for row in current:
            conn.execute(
                """
                UPDATE opportunity_score_batch
                SET score_batch_status='superseded', is_current=0, superseded_by_batch_id=?
                WHERE id=?
                """,
                (batch_id, row["id"]),
            )
            conn.execute("UPDATE opportunity_factor_score SET is_current=0, score_status='superseded' WHERE score_batch_id=?", (row["id"],))
            conn.execute("UPDATE opportunity_composite_score SET is_current=0, score_status='superseded', rating_status='superseded' WHERE score_batch_id=?", (row["id"],))
        conn.execute(
            """
            UPDATE opportunity_score_batch
            SET score_batch_status='completed', is_current=1, completed_at=datetime('now'),
                source_manifest_hash=?, factor_manifest_hash=?
            WHERE id=?
            """,
            (
                hash_json([r["id"] for r in conn.execute("SELECT id FROM opportunity_source WHERE run_id=?", (run_id,))]),
                hash_json([r["factor_code"] for r in conn.execute("SELECT factor_code FROM opportunity_factor_score WHERE score_batch_id=?", (batch_id,))]),
                batch_id,
            ),
        )
        conn.execute(
            """
            INSERT INTO opportunity_event_ledger(
              run_id, event_scope, system_event_type, event_direction, event_title,
              event_summary, evidence_ref_uri, event_payload_json
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                "system_provenance",
                "score_batch_completed",
                "not_applicable",
                "评分批次已完成",
                f"评分批次 {batch_id} 已按 {score_rule_version} 完成。",
                f"opp://score_batch/{batch_id}",
                _json({"score_batch_id": batch_id}),
            ),
        )
    except Exception as exc:
        conn.execute(
            "UPDATE opportunity_score_batch SET score_batch_status='failed', failure_reason=? WHERE id=?",
            (str(exc), batch_id),
        )
        raise
    return batch_id
