from __future__ import annotations

import sqlite3

from .constants import (
    API_CONTRACT_VERSION,
    PDF_CONTRACT_VERSION,
    SCHEMA_VERSION,
    SCORE_RULE_VERSION,
    SOURCE_LADDER_VERSION,
)
from .event_ledger import record_transition
from .intake_contract import default_intake_for_question, require_valid_intake_contract, save_intake_contract
from .intake_parser import parse_intake_payload
from .state_registry import RUN_TRANSITIONS


def create_run(
    conn: sqlite3.Connection,
    research_question: str | None = None,
    run_mode: str = "c_open_with_seed",
    requested_by: str = "manual",
    problem_statement: str | None = None,
    display_title: str | None = None,
    question: str | None = None,
    available_materials_choice: str = "A",
    evidence_policy: str = "balanced",
    intake_contract_payload: dict | None = None,
) -> int:
    canonical_question = str(research_question or question or "").strip()
    if not canonical_question:
        raise ValueError("research_question 不能为空")
    intake_payload = intake_contract_payload or default_intake_for_question(canonical_question, evidence_policy)
    intake_payload.setdefault("research_question", canonical_question)
    intake_payload.setdefault("available_materials_choice", available_materials_choice)
    intake_payload.setdefault("evidence_policy", evidence_policy)
    intake_contract = parse_intake_payload(intake_payload)
    run_id = int(
        conn.execute(
            """
            INSERT INTO opportunity_run(
              question, research_question, display_title, run_mode, run_status, run_readiness_status, requested_by,
              problem_statement, evidence_policy, data_cutoff_at, schema_version, api_contract_version,
              score_rule_version, source_tier_version, search_protocol_version,
              report_template_version, pdf_export_version
            ) VALUES(?,?,?,?,?,?,?,?,?,datetime('now'),?,?,?,?,?,?,?)
            """,
            (
                canonical_question,
                intake_contract["research_question"],
                display_title,
                run_mode,
                "created",
                "draft",
                requested_by,
                problem_statement or canonical_question,
                intake_contract["evidence_policy"],
                SCHEMA_VERSION,
                API_CONTRACT_VERSION,
                SCORE_RULE_VERSION,
                SOURCE_LADDER_VERSION,
                "C_SEARCH_PROTOCOL_V1",
                "C_REPORT_TEMPLATE_V1",
                PDF_CONTRACT_VERSION,
            ),
        ).lastrowid
    )
    conn.execute("INSERT INTO opportunity_run_stats(run_id) VALUES(?)", (run_id,))
    save_intake_contract(conn, run_id, intake_contract, raw_payload=intake_contract_payload or intake_payload)
    record_transition(conn, run_id, "run", run_id, None, "created", "扫描任务已创建")
    return run_id


def advance_run(conn: sqlite3.Connection, run_id: int, to_status: str, reason: str) -> None:
    row = conn.execute("SELECT run_status FROM opportunity_run WHERE id=?", (run_id,)).fetchone()
    if not row:
        raise KeyError(run_id)
    from_status = row["run_status"]
    allowed = set(RUN_TRANSITIONS.get(from_status, set()))
    if to_status not in allowed:
        raise ValueError(f"非法 run 状态迁移: {from_status} -> {to_status}")
    if to_status == "intake_validated":
        require_valid_intake_contract(conn, run_id)
    record_transition(conn, run_id, "run", run_id, from_status, to_status, reason)
    conn.execute(
        "UPDATE opportunity_run SET run_status=?, updated_at=datetime('now') WHERE id=?",
        (to_status, run_id),
    )


def mark_reviewable(conn: sqlite3.Connection, run_id: int) -> None:
    row = conn.execute("SELECT run_status FROM opportunity_run WHERE id=?", (run_id,)).fetchone()
    if not row:
        raise KeyError(run_id)
    if row["run_status"] not in {"under_review", "completed"}:
        raise ValueError(f"只有 under_review/completed run 可以标记 reviewable，当前为 {row['run_status']}")
    conn.execute(
        "UPDATE opportunity_run SET run_readiness_status='reviewable', updated_at=datetime('now') WHERE id=?",
        (run_id,),
    )
