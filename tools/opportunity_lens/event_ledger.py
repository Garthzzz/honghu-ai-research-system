from __future__ import annotations

import json
import sqlite3
from typing import Any

from .validators import validate_state_transition


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def append_business_event(
    conn: sqlite3.Connection,
    run_id: int,
    title: str,
    event_type: str,
    event_category: str,
    event_direction: str,
    entity_id: int | None = None,
    summary: str | None = None,
    event_date: str | None = None,
    dedupe_key: str | None = None,
    evidence_ref_uri: str | None = None,
    score_effect: str = "none",
    confidence: float = 0.5,
) -> int:
    existing = None
    if dedupe_key:
        existing = conn.execute(
            """
            SELECT id FROM opportunity_event_ledger
            WHERE run_id=? AND dedupe_key=? AND event_scope='business'
            ORDER BY id LIMIT 1
            """,
            (run_id, dedupe_key),
        ).fetchone()
    if existing:
        return int(existing["id"])
    return int(
        conn.execute(
            """
            INSERT INTO opportunity_event_ledger(
              run_id, entity_id, event_scope, event_type, event_category, event_direction,
              event_title, event_summary, event_date, dedupe_key, confidence,
              score_effect, evidence_ref_uri
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                entity_id,
                "business",
                event_type,
                event_category,
                event_direction,
                title,
                summary,
                event_date,
                dedupe_key,
                confidence,
                score_effect,
                evidence_ref_uri,
            ),
        ).lastrowid
    )


def append_system_event(
    conn: sqlite3.Connection,
    run_id: int,
    title: str,
    system_event_type: str,
    payload: dict | None = None,
    summary: str | None = None,
    evidence_ref_uri: str | None = None,
) -> int:
    return int(
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
                system_event_type,
                "not_applicable",
                title,
                summary,
                evidence_ref_uri,
                _json(payload or {}),
            ),
        ).lastrowid
    )


def record_transition(
    conn: sqlite3.Connection,
    run_id: int,
    object_type: str,
    object_id: int,
    from_status: str | None,
    to_status: str,
    reason: str,
    evidence_ref_uri: str | None = None,
) -> int:
    validate_state_transition(object_type, from_status, to_status)
    transition_id = int(
        conn.execute(
            """
            INSERT INTO opportunity_state_transition(
              run_id, object_type, object_id, from_status, to_status,
              transition_reason, evidence_ref_uri
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (run_id, object_type, object_id, from_status, to_status, reason, evidence_ref_uri),
        ).lastrowid
    )
    append_system_event(
        conn,
        run_id,
        title=f"{object_type} status changed",
        system_event_type="run_state_transition" if object_type == "run" else "other_system",
        payload={
            "transition_id": transition_id,
            "object_type": object_type,
            "object_id": object_id,
            "from_status": from_status,
            "to_status": to_status,
        },
        evidence_ref_uri=f"opp://event/{transition_id}" if evidence_ref_uri is None else evidence_ref_uri,
    )
    return transition_id
