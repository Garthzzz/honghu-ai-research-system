from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .constants import (
    EARLY_SIGNAL_RULE_VERSION,
    EVIDENCE_POLICY_VERSION,
    INTAKE_CONTRACT_VERSION,
    PDF_CONTRACT_VERSION,
    SCORE_RULE_VERSION,
)


def file_hash(path: str | Path) -> str | None:
    p = Path(path)
    if not p.exists():
        return None
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def build_manifest(
    *,
    run_id: int,
    export_job_id: int,
    html_snapshot_path: str | None,
    pdf_path: str | None,
    asset_dir: str | None,
    source_manifest_hash: str | None,
    score_manifest_hash: str | None,
    status: str,
    error_message: str | None = None,
    intake_summary: dict | None = None,
    early_signal_summary: dict | None = None,
) -> dict:
    return {
        "run_id": run_id,
        "export_job_id": export_job_id,
        "export_status": status,
        "pdf_contract_version": PDF_CONTRACT_VERSION,
        "score_rule_version": SCORE_RULE_VERSION,
        "intake_contract_version": INTAKE_CONTRACT_VERSION,
        "evidence_policy_version": EVIDENCE_POLICY_VERSION,
        "early_signal_rule_version": EARLY_SIGNAL_RULE_VERSION,
        "intake_summary": intake_summary or {},
        "early_signal_summary": early_signal_summary or {},
        "html_snapshot_path": html_snapshot_path,
        "pdf_path": pdf_path,
        "asset_dir": asset_dir,
        "source_manifest_hash": source_manifest_hash,
        "score_manifest_hash": score_manifest_hash,
        "html_snapshot_hash": file_hash(html_snapshot_path) if html_snapshot_path else None,
        "pdf_hash": file_hash(pdf_path) if pdf_path else None,
        "error_message": error_message,
    }


def write_manifest(path: str | Path, manifest: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(p)
