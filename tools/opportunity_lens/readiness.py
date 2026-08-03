from __future__ import annotations

import sqlite3


def compute_entity_readiness(conn: sqlite3.Connection, run_id: int, entity_id: int) -> dict:
    row = conn.execute(
        """
        SELECT COUNT(*) AS n,
               SUM(CASE WHEN factor_readiness_status IN ('ready','limited') THEN 1 ELSE 0 END) AS ready_n,
               AVG(coverage) AS coverage,
               AVG(confidence) AS confidence
        FROM opportunity_factor_readiness
        WHERE run_id=? AND entity_id=? AND factor_readiness_status!='not_applicable'
        """,
        (run_id, entity_id),
    ).fetchone()
    n = int(row["n"] or 0)
    ready_n = int(row["ready_n"] or 0)
    score = ready_n / n if n else 0.0
    if n == 0:
        status = "seed"
    elif score >= 0.8:
        status = "scoring_ready"
    elif score >= 0.5:
        status = "scoring_limited"
    else:
        status = "research_only"
    return {
        "readiness_score": round(score, 4),
        "coverage": round(float(row["coverage"] or 0), 4),
        "confidence": round(float(row["confidence"] or 0), 4),
        "maturation_status": status,
    }


def update_entity_maturation_from_readiness(conn: sqlite3.Connection, run_id: int, entity_id: int) -> dict:
    readiness = compute_entity_readiness(conn, run_id, entity_id)
    conn.execute(
        """
        UPDATE opportunity_entity_maturation
        SET maturation_status=?, readiness_score=?, readiness_reason=?, updated_at=datetime('now')
        WHERE run_id=? AND entity_id=?
        """,
        (
            readiness["maturation_status"],
            readiness["readiness_score"],
            "由因子就绪矩阵推导。",
            run_id,
            entity_id,
        ),
    )
    return readiness
