from __future__ import annotations

import sqlite3


def flag_for_audit(severity: str, status: str) -> str:
    if status not in {"open", "in_review", "reopened"}:
        return "none"
    if severity == "p0":
        return "red"
    if severity == "p1":
        return "yellow"
    return "none"


def run_flag_summary(conn: sqlite3.Connection, run_id: int) -> dict:
    rows = conn.execute(
        """
        SELECT audit_severity, audit_issue_status, issue_title
        FROM opportunity_audit_issue
        WHERE run_id=?
        ORDER BY CASE audit_severity WHEN 'p0' THEN 0 WHEN 'p1' THEN 1 WHEN 'p2' THEN 2 ELSE 3 END, id
        """,
        (run_id,),
    ).fetchall()
    red = yellow = 0
    top = None
    for row in rows:
        flag = flag_for_audit(row["audit_severity"], row["audit_issue_status"])
        if flag == "red":
            red += 1
            top = top or row["issue_title"]
        elif flag == "yellow":
            yellow += 1
            top = top or row["issue_title"]
    return {"red": red, "yellow": yellow, "top_reason": top, "level": "red" if red else ("yellow" if yellow else "none")}
