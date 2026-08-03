from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.research_core.config import publish_review_stages, resolve_track_config
from tools.research_core.manifest import (
    ExecutionManifest,
    GateResult,
    ReviewRecord,
    is_sha256_hash,
)

from .artifact_freeze import (
    ArtifactFreezeError,
    build_artifact_freeze,
    is_strict_v2_run,
    normalize_sha256,
)
from .browser_audit_contract import validate_latest_browser_visual_audit
from .constants import DB_PATH, ROOT
from .db import connect
from .workflow import advance_run


@dataclass
class PublicationGateReport:
    run_id: int
    eligible: bool
    blockers: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


def _hash_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _quality_gate_hash_is_valid(row: sqlite3.Row) -> bool:
    try:
        payload = {
            "gate_name": row["gate_name"],
            "verdict": row["gate_verdict"],
            "findings": json.loads(row["findings_json"] or "[]"),
            "artifact_refs": json.loads(row["artifact_ref_json"] or "[]"),
            "gate_version": row["gate_version"],
        }
    except (json.JSONDecodeError, TypeError):
        return False
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return row["result_hash"] == _hash_text(canonical)


def _review_findings_hash_is_valid(row: sqlite3.Row) -> bool:
    try:
        findings = json.loads(row["findings_json"] or "[]")
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(findings, list):
        return False
    normalized = json.dumps(findings, ensure_ascii=False, sort_keys=True)
    return row["findings_hash"] == _hash_text(normalized)


def evaluate_publication_gate(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    project_root: str | Path = ROOT,
    verify_browser_screenshots: bool = True,
) -> PublicationGateReport:
    run = conn.execute("SELECT * FROM opportunity_run WHERE id=?", (run_id,)).fetchone()
    if not run:
        raise KeyError(run_id)
    blockers: list[str] = []
    open_p0 = int(conn.execute(
        """
        SELECT COUNT(*) FROM opportunity_audit_issue
        WHERE run_id=? AND audit_severity='p0'
          AND audit_issue_status IN ('open','in_review','reopened')
        """,
        (run_id,),
    ).fetchone()[0])
    if open_p0:
        blockers.append(f"存在 {open_p0} 个未关闭 P0")

    gate_rows = conn.execute(
        "SELECT * FROM opportunity_quality_gate_result WHERE run_id=? ORDER BY id",
        (run_id,),
    ).fetchall()
    latest_gates: dict[str, sqlite3.Row] = {}
    for row in gate_rows:
        latest_gates[row["gate_name"]] = row
        if not _quality_gate_hash_is_valid(row):
            blockers.append(f"确定性质量门禁记录 hash 校验失败: {row['gate_name']}#{row['id']}")
    red_gates = sorted(name for name, row in latest_gates.items() if row["gate_verdict"] == "RED")
    if red_gates:
        blockers.append(f"确定性质量门禁为 RED: {red_gates}")
    profile = resolve_track_config("c")
    required_gates = profile.get("review", {}).get("deterministic_gates", [])
    for required_gate in required_gates:
        if required_gate not in latest_gates:
            blockers.append(f"缺少确定性质量门禁: {required_gate}")

    # 只约束正在走现行发布流程的 V2 staged run。历史 published 状态不会被
    # 反向解释为通过了新合同，也不会因查看旧记录而被追溯重验。
    strict_v2 = run["run_status"] == "under_review" and is_strict_v2_run(conn, run_id)
    freeze = None
    if strict_v2:
        try:
            freeze = build_artifact_freeze(conn, run_id, project_root=project_root)
        except ArtifactFreezeError as exc:
            blockers.append(f"当前研究包无法形成发布冻结指纹: {exc}")

    review_rows = conn.execute(
        "SELECT * FROM opportunity_agent_review_log WHERE run_id=? ORDER BY id",
        (run_id,),
    ).fetchall()
    latest_reviews: dict[str, sqlite3.Row] = {}
    for row in review_rows:
        latest_reviews[row["review_stage"]] = row
    market_linked_count = int(conn.execute(
        """
        SELECT COUNT(DISTINCT m.entity_id)
        FROM opportunity_entity_maturation m
        LEFT JOIN opportunity_entity_research_profile p
          ON p.run_id=m.run_id AND p.entity_id=m.entity_id
        WHERE m.run_id=? AND COALESCE(p.entity_research_mode,'market_linked')='market_linked'
        """,
        (run_id,),
    ).fetchone()[0])
    security_target_count = int(conn.execute(
        "SELECT COUNT(*) FROM opportunity_entity_investment_target WHERE run_id=? AND target_type='security'",
        (run_id,),
    ).fetchone()[0])
    review_signals = ["public_ui"]
    if market_linked_count:
        review_signals.append("market_linked")
    if security_target_count:
        review_signals.append("security_target")
    required_stages = publish_review_stages("c", review_signals)
    for stage in required_stages:
        row = latest_reviews.get(stage)
        if row is None:
            blockers.append(f"缺少 reviewer 记录: {stage}")
            continue
        if row["review_verdict"] != "GREEN":
            blockers.append(f"reviewer 最新结论不是 GREEN: {stage}")
        if row["reconciliation_status"] not in {"resolved", "not_applicable"}:
            blockers.append(f"reviewer findings 未闭环: {stage}")
        allowed_kinds = {"deterministic", "independent", "human"} if stage == "browser" else {"independent", "human"}
        if row["review_kind"] not in allowed_kinds:
            blockers.append(f"required reviewer 类型非法: {stage}={row['review_kind']}")
        if not row["reviewer_id"]:
            blockers.append(f"reviewer 缺少 reviewer_id: {stage}")
        if not row["input_artifact_hash"]:
            blockers.append(f"reviewer 缺少输入 artifact hash: {stage}")
        if not row["output_artifact_hash"]:
            blockers.append(f"reviewer 缺少输出 artifact hash: {stage}")
        if row["input_artifact_hash"] and not is_sha256_hash(row["input_artifact_hash"]):
            blockers.append(f"reviewer 输入 artifact hash 格式非法: {stage}")
        if row["output_artifact_hash"] and not is_sha256_hash(row["output_artifact_hash"]):
            blockers.append(f"reviewer 输出 artifact hash 格式非法: {stage}")
        if not _review_findings_hash_is_valid(row):
            blockers.append(f"reviewer findings hash 校验失败: {stage}")
        if strict_v2 and freeze is not None and row["input_artifact_hash"]:
            expected_input_hash = (
                freeze.browser_input_hash if stage == "browser" else freeze.pack_hash
            )
            try:
                actual_input_hash = normalize_sha256(
                    row["input_artifact_hash"],
                    field=f"reviewer.{stage}.input_artifact_hash",
                )
            except ArtifactFreezeError:
                actual_input_hash = None
            if actual_input_hash is not None and actual_input_hash != expected_input_hash:
                blockers.append(
                    f"reviewer 已过期，未绑定当前产物: {stage}; "
                    f"expected={expected_input_hash}, actual={actual_input_hash}"
                )
    final = latest_reviews.get("final")
    if final is not None and final["review_kind"] not in {"independent", "human"}:
        blockers.append("final reviewer 必须是 independent 或 human，不能只用确定性脚本自报")

    browser_audit = None
    if strict_v2 and freeze is not None:
        browser_audit = validate_latest_browser_visual_audit(
            conn,
            run_id,
            project_root=project_root,
            verify_screenshots=verify_browser_screenshots,
        )
        if not browser_audit.valid:
            blockers.extend(
                f"browser visual audit 未通过: {issue}" for issue in browser_audit.issues
            )
        browser_review = latest_reviews.get("browser")
        if (
            browser_review is not None
            and browser_audit.manifest_hash is not None
            and browser_review["output_artifact_hash"] != browser_audit.manifest_hash
        ):
            blockers.append(
                "browser reviewer 输出 hash 未绑定最新 browser_visual_audit manifest: "
                f"expected={browser_audit.manifest_hash}, "
                f"actual={browser_review['output_artifact_hash']}"
            )

    if run["run_status"] != "under_review":
        blockers.append(f"run_status 必须是 under_review，当前为 {run['run_status']}")
    if run["run_readiness_status"] != "reviewable":
        blockers.append(f"run_readiness_status 必须是 reviewable，当前为 {run['run_readiness_status']}")

    return PublicationGateReport(
        run_id=run_id,
        eligible=not blockers,
        blockers=blockers,
        details={
            "open_p0": open_p0,
            "quality_gates": {name: row["gate_verdict"] for name, row in latest_gates.items()},
            "review_stages": {name: row["review_verdict"] for name, row in latest_reviews.items()},
            "required_review_stages": required_stages,
            "market_linked_count": market_linked_count,
            "security_target_count": security_target_count,
            "strict_artifact_binding": strict_v2,
            "artifact_freeze": freeze.as_dict() if freeze is not None else None,
            "browser_visual_audit": {
                "valid": browser_audit.valid,
                "manifest_hash": browser_audit.manifest_hash,
                "issues": browser_audit.issues,
            } if browser_audit is not None else None,
        },
    )


def _synchronize_shared_execution_manifest(
    conn: sqlite3.Connection,
    run_id: int,
    report: PublicationGateReport,
) -> None:
    row = conn.execute(
        """
        SELECT id,manifest_json FROM opportunity_run_manifest
        WHERE run_id=? AND manifest_type='research_execution_manifest'
        ORDER BY id DESC LIMIT 1
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        return
    manifest = ExecutionManifest.from_dict(json.loads(row["manifest_json"]))
    manifest.gates = []
    gate_rows = conn.execute(
        "SELECT * FROM opportunity_quality_gate_result WHERE run_id=? ORDER BY id",
        (run_id,),
    ).fetchall()
    latest_gates: dict[str, sqlite3.Row] = {}
    for gate_row in gate_rows:
        latest_gates[gate_row["gate_name"]] = gate_row
    for gate_name in resolve_track_config("c").get("review", {}).get("deterministic_gates", []):
        gate_row = latest_gates[gate_name]
        manifest.record_gate(GateResult(
            gate=gate_name,
            verdict=gate_row["gate_verdict"],
            findings=json.loads(gate_row["findings_json"] or "[]"),
            artifact_refs=json.loads(gate_row["artifact_ref_json"] or "[]"),
            checked_at=gate_row["created_at"],
        ))

    manifest.reviews = []
    review_rows = conn.execute(
        "SELECT * FROM opportunity_agent_review_log WHERE run_id=? ORDER BY id",
        (run_id,),
    ).fetchall()
    for review_row in review_rows:
        if review_row["review_kind"] == "legacy":
            continue
        manifest.record_review(ReviewRecord(
            stage=review_row["review_stage"],
            reviewer_role=review_row["reviewer_role"],
            reviewer_id=review_row["reviewer_id"],
            review_kind=review_row["review_kind"],
            verdict=review_row["review_verdict"],
            reconciliation_status=review_row["reconciliation_status"],
            findings=json.loads(review_row["findings_json"] or "[]"),
            input_artifact_hash=review_row["input_artifact_hash"],
            output_artifact_hash=review_row["output_artifact_hash"],
            reviewed_at=review_row["created_at"],
        ))
    manifest.set_review_plan(report.details["required_review_stages"])
    if not manifest.evaluate_publication(open_p0=report.details["open_p0"]):
        raise ValueError("共享 execution manifest 与 DB 发布门禁不一致: " + "；".join(manifest.publication["blockers"]))
    payload = manifest.as_dict()
    conn.execute(
        "UPDATE opportunity_run_manifest SET manifest_json=?,manifest_hash=? WHERE id=?",
        (json.dumps(payload, ensure_ascii=False, sort_keys=True), payload["manifest_hash"], row["id"]),
    )


def publish_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    reason: str,
    project_root: str | Path = ROOT,
    verify_browser_screenshots: bool = True,
) -> PublicationGateReport:
    report = evaluate_publication_gate(
        conn,
        run_id,
        project_root=project_root,
        verify_browser_screenshots=verify_browser_screenshots,
    )
    if not report.eligible:
        raise ValueError("Opportunity Lens 发布门禁未通过: " + "；".join(report.blockers))
    advance_run(conn, run_id, "completed", reason)
    conn.execute(
        """
        UPDATE opportunity_run
        SET run_readiness_status='published', completed_at=datetime('now'), updated_at=datetime('now')
        WHERE id=?
        """,
        (run_id,),
    )
    _synchronize_shared_execution_manifest(conn, run_id, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="对已暂存的 Opportunity Lens run 执行发布门禁")
    parser.add_argument("run_id", type=int)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--reason", default="V2 reviewer 与发布门禁全部通过")
    args = parser.parse_args()
    conn = connect(args.db)
    try:
        report = publish_run(conn, args.run_id, reason=args.reason)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(json.dumps({
        "run_id": report.run_id,
        "eligible": report.eligible,
        "details": report.details,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
