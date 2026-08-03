from __future__ import annotations

import sqlite3

from .event_ledger import append_system_event
from .validators import validate_enum


def create_audit_issue(
    conn: sqlite3.Connection,
    run_id: int,
    affected_uri: str,
    issue_type: str,
    severity: str,
    title: str,
    detail: str | None = None,
    entity_id: int | None = None,
    evidence_ref_uri: str | None = None,
) -> int:
    validate_enum("audit_issue_type", issue_type)
    validate_enum("audit_severity", severity)
    issue_id = int(
        conn.execute(
            """
            INSERT INTO opportunity_audit_issue(
              run_id, entity_id, affected_uri, audit_issue_type, audit_severity,
              audit_issue_status, issue_title, issue_detail, evidence_ref_uri
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (run_id, entity_id, affected_uri, issue_type, severity, "open", title, detail, evidence_ref_uri),
        ).lastrowid
    )
    append_system_event(
        conn,
        run_id,
        title="审计问题已打开",
        system_event_type="audit_issue_status_change",
        payload={"audit_issue_id": issue_id, "status": "open", "severity": severity},
        evidence_ref_uri=f"opp://audit_issue/{issue_id}",
    )
    return issue_id


def create_policy_gate_issue(
    conn: sqlite3.Connection,
    run_id: int,
    affected_uri: str,
    title: str,
    detail: str,
    *,
    entity_id: int | None = None,
    evidence_ref_uri: str | None = None,
    severity: str = "p1",
) -> int:
    return create_audit_issue(
        conn,
        run_id,
        affected_uri=affected_uri,
        issue_type="policy_gate_violation",
        severity=severity,
        title=title,
        detail=detail,
        entity_id=entity_id,
        evidence_ref_uri=evidence_ref_uri,
    )


def waive_issue(conn: sqlite3.Connection, issue_id: int, reviewer: str, reason: str) -> None:
    if not reviewer or not reason:
        raise ValueError("豁免需要 reviewer 和 reason")
    row = conn.execute("SELECT run_id FROM opportunity_audit_issue WHERE id=?", (issue_id,)).fetchone()
    if not row:
        raise KeyError(issue_id)
    conn.execute(
        """
        UPDATE opportunity_audit_issue
        SET audit_issue_status='waived', reviewer=?, waiver_reason=?,
            resolved_at=datetime('now'), updated_at=datetime('now')
        WHERE id=?
        """,
        (reviewer, reason, issue_id),
    )
    append_system_event(
        conn,
        row["run_id"],
        title="审计问题已豁免",
        system_event_type="audit_issue_status_change",
        payload={"audit_issue_id": issue_id, "status": "waived", "reviewer": reviewer},
        evidence_ref_uri=f"opp://audit_issue/{issue_id}",
    )


def issue_counts(conn: sqlite3.Connection, run_id: int) -> dict:
    rows = conn.execute(
        """
        SELECT audit_severity, audit_issue_status, COUNT(*) AS n
        FROM opportunity_audit_issue
        WHERE run_id=?
        GROUP BY audit_severity, audit_issue_status
        """,
        (run_id,),
    ).fetchall()
    out = {"open_p0": 0, "open_p1": 0, "total_open": 0, "total": 0}
    for row in rows:
        n = int(row["n"])
        out["total"] += n
        if row["audit_issue_status"] in {"open", "in_review", "reopened"}:
            out["total_open"] += n
            if row["audit_severity"] == "p0":
                out["open_p0"] += n
            if row["audit_severity"] == "p1":
                out["open_p1"] += n
    return out


def publication_blocked(conn: sqlite3.Connection, run_id: int) -> bool:
    return issue_counts(conn, run_id)["open_p0"] > 0
