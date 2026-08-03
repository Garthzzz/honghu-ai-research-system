from __future__ import annotations

import json
from pathlib import Path

from .constants import DB_PATH, EXPORT_ROOT
from .db import connect
from .export_manifest import build_manifest, write_manifest


def create_pdf_export_job(
    run_id: int,
    requested_by: str = "manual",
    db_path: str | Path = DB_PATH,
    export_root: str | Path = EXPORT_ROOT,
) -> int:
    """创建可追溯导出任务，并明确暂缓 PDF 渲染。

    当前实现不会声称已经安装 PDF 渲染器。它只生成 HTML 快照和 manifest，
    然后用清晰原因记录失败状态。
    """
    conn = connect(db_path)
    try:
        score_batch = conn.execute(
            "SELECT id, source_manifest_hash, input_manifest_hash FROM opportunity_score_batch WHERE run_id=? AND is_current=1",
            (run_id,),
        ).fetchone()
        job_id = int(
            conn.execute(
                """
                INSERT INTO opportunity_export_job(
                  run_id, score_batch_id, export_type, export_scope, export_status, requested_by
                ) VALUES(?,?,?,?,?,?)
                """,
                (run_id, score_batch["id"] if score_batch else None, "pdf", "run_report", "queued", requested_by),
            ).lastrowid
        )
        artifact_dir = Path(export_root) / str(run_id) / str(job_id)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        html_path = artifact_dir / "snapshot.html"
        manifest_path = artifact_dir / "manifest.json"
        conn.execute(
            "UPDATE opportunity_export_job SET export_status='rendering_html', artifact_dir=?, html_snapshot_path=?, manifest_path=?, updated_at=datetime('now') WHERE id=?",
            (str(artifact_dir), str(html_path), str(manifest_path), job_id),
        )
        intake = conn.execute(
            """
            SELECT research_question, available_materials_choice, intake_material_type,
                   evidence_policy, intake_contract_version, intake_contract_hash
            FROM opportunity_intake_contract
            WHERE run_id=?
            """,
            (run_id,),
        ).fetchone()
        early_rows = conn.execute(
            """
            SELECT early_signal_score, early_signal_strength_label, research_priority_score,
                   research_priority_label, core_score_changed_by_overlay
            FROM opportunity_early_signal_aggregate
            WHERE run_id=?
            ORDER BY research_priority_score DESC NULLS LAST
            """,
            (run_id,),
        ).fetchall()
        intake_summary = dict(intake) if intake else {}
        early_signal_summary = {
            "count": len(early_rows),
            "items": [dict(row) for row in early_rows],
            "core_score_changed_by_overlay": any(row["core_score_changed_by_overlay"] for row in early_rows),
        }
        html_path.write_text(
            "<!doctype html><meta charset='utf-8'><title>机会透镜导出暂缓</title>"
            f"<h1>机会透镜扫描 {run_id}</h1>"
            f"<p>研究问题：{intake_summary.get('research_question', '未记录')}</p>"
            f"<p>证据策略：{intake_summary.get('evidence_policy', '未记录')}</p>"
            "<p>早期信号只作为研究优先级 overlay，不改变核心 14 因子评分。</p>"
            "<p>HTML 快照已生成；当前实现暂缓接入 PDF 渲染器。</p>",
            encoding="utf-8",
        )
        error_message = "PDF 渲染器暂缓接入：HTML 快照和 manifest 已生成，但没有声称生成真实 PDF。"
        manifest = build_manifest(
            run_id=run_id,
            export_job_id=job_id,
            html_snapshot_path=str(html_path),
            pdf_path=None,
            asset_dir=str(artifact_dir / "assets"),
            source_manifest_hash=score_batch["source_manifest_hash"] if score_batch else None,
            score_manifest_hash=score_batch["input_manifest_hash"] if score_batch else None,
            status="failed",
            error_message=error_message,
            intake_summary=intake_summary,
            early_signal_summary=early_signal_summary,
        )
        write_manifest(manifest_path, manifest)
        conn.execute(
            """
            UPDATE opportunity_export_job
            SET export_status='failed', export_manifest_json=?, error_message=?,
                updated_at=datetime('now'), completed_at=datetime('now')
            WHERE id=?
            """,
            (json.dumps(manifest, ensure_ascii=False, sort_keys=True), error_message, job_id),
        )
        conn.commit()
        return job_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
