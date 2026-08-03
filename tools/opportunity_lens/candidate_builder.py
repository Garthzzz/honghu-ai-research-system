from __future__ import annotations

import sqlite3

from .validators import normalize_entity_type


def create_candidate(
    conn: sqlite3.Connection,
    run_id: int,
    name: str,
    entity_type_hint: str,
    stage: str = "candidate",
    reason: str | None = None,
) -> int:
    return int(
        conn.execute(
            """
            INSERT INTO opportunity_candidate_entity(
              run_id, candidate_stage, name, entity_type_hint, reason
            ) VALUES(?,?,?,?,?)
            """,
            (run_id, stage, name, normalize_entity_type(entity_type_hint), reason),
        ).lastrowid
    )


def promote_candidate_to_entity(
    conn: sqlite3.Connection,
    candidate_id: int,
    canonical_name: str | None = None,
) -> int:
    candidate = conn.execute("SELECT * FROM opportunity_candidate_entity WHERE id=?", (candidate_id,)).fetchone()
    if not candidate:
        raise KeyError(candidate_id)
    entity_type = normalize_entity_type(candidate["entity_type_hint"] or "segment")
    name = canonical_name or candidate["name"]
    existing = conn.execute(
        "SELECT id FROM opportunity_entity WHERE entity_type=? AND canonical_name=?",
        (entity_type, name),
    ).fetchone()
    if existing:
        entity_id = int(existing["id"])
    else:
        entity_id = int(
            conn.execute(
                """
                INSERT INTO opportunity_entity(entity_type, taxonomy_level, canonical_name, display_name)
                VALUES(?,?,?,?)
                """,
                (entity_type, entity_type, name, name),
            ).lastrowid
        )
    conn.execute(
        """
        UPDATE opportunity_candidate_entity
        SET candidate_stage='merged_to_entity', entity_id=?, updated_at=datetime('now')
        WHERE id=?
        """,
        (entity_id, candidate_id),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO opportunity_entity_maturation(
          run_id, entity_id, maturation_status, readiness_score, readiness_reason
        ) VALUES(?,?,?,?,?)
        """,
        (candidate["run_id"], entity_id, "seed", 0.2, "Promoted from discovery candidate."),
    )
    return entity_id
