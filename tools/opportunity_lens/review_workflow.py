from __future__ import annotations

import hashlib
import json
import sqlite3

from tools.research_core.config import resolve_track_config
from tools.research_core.manifest import is_sha256_hash

from .event_ledger import append_system_event
from .validators import validate_enum


def enqueue_review(
    conn: sqlite3.Connection,
    run_id: int,
    object_uri: str,
    entity_id: int | None = None,
    audit_issue_id: int | None = None,
) -> int:
    return int(
        conn.execute(
            """
            INSERT INTO opportunity_review_queue(
              run_id, entity_id, audit_issue_id, object_uri, review_status, review_decision
            ) VALUES(?,?,?,?,?,?)
            """,
            (run_id, entity_id, audit_issue_id, object_uri, "pending", "no_decision"),
        ).lastrowid
    )


def apply_review_decision(
    conn: sqlite3.Connection,
    review_id: int,
    decision: str,
    reviewer: str,
    note: str | None = None,
) -> None:
    validate_enum("review_decision", decision)
    row = conn.execute("SELECT * FROM opportunity_review_queue WHERE id=?", (review_id,)).fetchone()
    if not row:
        raise KeyError(review_id)
    status = {
        "approve": "approved",
        "reject": "rejected",
        "request_revision": "in_review",
        "waive": "waived",
        "resolve": "resolved",
        "reopen": "reopened",
        "no_decision": row["review_status"],
    }[decision]
    conn.execute(
        """
        UPDATE opportunity_review_queue
        SET review_status=?, review_decision=?, reviewer=?, reviewer_note=?,
            updated_at=datetime('now')
        WHERE id=?
        """,
        (status, decision, reviewer, note, review_id),
    )
    append_system_event(
        conn,
        row["run_id"],
        title="Human review decision",
        system_event_type="human_review_decision",
        payload={"review_id": review_id, "decision": decision, "status": status, "reviewer": reviewer},
        evidence_ref_uri=row["object_uri"],
    )


def record_agent_review(
    conn: sqlite3.Connection,
    run_id: int,
    round_no: int,
    role: str,
    verdict: str,
    reconciliation_status: str,
    findings_json: str = "[]",
    *,
    review_stage: str = "unspecified",
    reviewer_id: str | None = None,
    review_kind: str = "legacy",
    input_artifact_hash: str | None = None,
    output_artifact_hash: str | None = None,
) -> int:
    validate_enum("review_verdict", verdict)
    validate_enum("reconciliation_status", reconciliation_status)
    if review_kind not in {"deterministic", "independent", "human", "legacy"}:
        raise ValueError(f"未知 review_kind: {review_kind}")
    if review_kind != "legacy":
        canonical_stages = set(resolve_track_config("c").get("review", {}).get("canonical_review_stages", []))
        if review_stage not in canonical_stages:
            raise ValueError(f"未知 review_stage: {review_stage}")
        if not reviewer_id:
            raise ValueError("非 legacy review 必须记录 reviewer_id")
        if not input_artifact_hash or not output_artifact_hash:
            raise ValueError("非 legacy review 必须记录 input/output artifact hash")
        if not is_sha256_hash(input_artifact_hash) or not is_sha256_hash(output_artifact_hash):
            raise ValueError("非 legacy review 的 artifact hash 格式非法")
    try:
        findings = json.loads(findings_json or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError("findings_json 必须是合法 JSON") from exc
    if not isinstance(findings, list):
        raise ValueError("findings_json 顶层必须是数组")
    normalized_findings = json.dumps(findings, ensure_ascii=False, sort_keys=True)
    findings_hash = "sha256:" + hashlib.sha256(normalized_findings.encode("utf-8")).hexdigest()
    return int(
        conn.execute(
            """
            INSERT INTO opportunity_agent_review_log(
              run_id, review_round, reviewer_role, review_verdict,
              reconciliation_status, findings_json, review_stage, reviewer_id,
              review_kind, input_artifact_hash, output_artifact_hash, findings_hash
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                round_no,
                role,
                verdict,
                reconciliation_status,
                normalized_findings,
                review_stage,
                reviewer_id,
                review_kind,
                input_artifact_hash,
                output_artifact_hash,
                findings_hash,
            ),
        ).lastrowid
    )


def record_quality_gate(
    conn: sqlite3.Connection,
    run_id: int,
    gate_name: str,
    verdict: str,
    findings: list[dict] | None = None,
    artifact_refs: list[str] | None = None,
    *,
    gate_version: str,
) -> int:
    if verdict not in {"GREEN", "YELLOW", "RED"}:
        raise ValueError(f"未知 gate verdict: {verdict}")
    canonical_gates = set(resolve_track_config("c").get("review", {}).get("deterministic_gates", []))
    if gate_name not in canonical_gates:
        raise ValueError(f"未知 deterministic gate: {gate_name}")
    if findings is not None and not isinstance(findings, list):
        raise ValueError("quality gate findings 必须是数组")
    if artifact_refs is not None and not isinstance(artifact_refs, list):
        raise ValueError("quality gate artifact_refs 必须是数组")
    findings_json = json.dumps(findings or [], ensure_ascii=False, sort_keys=True)
    artifact_json = json.dumps(artifact_refs or [], ensure_ascii=False, sort_keys=True)
    digest_payload = json.dumps(
        {
            "gate_name": gate_name,
            "verdict": verdict,
            "findings": json.loads(findings_json),
            "artifact_refs": json.loads(artifact_json),
            "gate_version": gate_version,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    result_hash = "sha256:" + hashlib.sha256(digest_payload.encode("utf-8")).hexdigest()
    return int(
        conn.execute(
            """
            INSERT INTO opportunity_quality_gate_result(
              run_id, gate_name, gate_verdict, findings_json,
              artifact_ref_json, gate_version, result_hash
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (run_id, gate_name, verdict, findings_json, artifact_json, gate_version, result_hash),
        ).lastrowid
    )
