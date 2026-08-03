from __future__ import annotations

"""Atomically record the seven publication reviews for a silicon-wafer run.

The review manifest is deliberately small.  It binds one run and one current
artifact freeze to seven independently written JSON review artifacts::

    {
      "schema_version": "opportunity_lens.silicon_review_manifest.v1",
      "run_id": 10,
      "run_slug": "20260720_silicon_wafer_equipment_landscape_2026_2030",
      "review_round": 1,
      "artifact_freeze": {
        "pack_hash": "sha256:...",
        "ui_bundle_hash": "sha256:...",
        "browser_input_hash": "sha256:..."
      },
      "browser_manifest_hash": "sha256:...",
      "reviews": [
        {
          "stage": "evidence",
          "artifact_path": "cache/.../evidence.json",
          "artifact_sha256": "sha256:..."
        }
      ]
    }

Each referenced JSON object must carry ``run_id``, ``run_slug``,
``review_stage``, ``reviewer_role``, ``reviewer_id``, ``review_kind``,
``review_verdict``, ``reconciliation_status``, ``findings`` and
``input_artifact_hash``.  The browser review must additionally carry
``output_artifact_hash`` equal to the latest recorded browser visual-audit
manifest.  The final review must carry this binding object::

    {
      "bindings": {
        "pack_hash": "sha256:...",
        "browser_manifest_hash": "sha256:...",
        "review_artifact_hashes": {
          "evidence": "sha256:...",
          "calculation": "sha256:...",
          "science": "sha256:...",
          "financial": "sha256:...",
          "writing": "sha256:..."
        }
      }
    }

Review JSON files are the recorded outputs for every non-browser stage.  The
browser stage output is the browser manifest itself.  This avoids a
self-referential hash inside a review file while retaining full provenance.
"""

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_PROJECT_ROOT = SCRIPT_PATH.parents[2]
if str(DEFAULT_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(DEFAULT_PROJECT_ROOT))

from tools.opportunity_lens.artifact_freeze import (  # noqa: E402
    ArtifactFreeze,
    build_artifact_freeze,
    latest_manual_pack_manifest,
    normalize_sha256,
    sha256_bytes,
)
from tools.opportunity_lens.browser_audit_contract import (  # noqa: E402
    BrowserAuditValidation,
    validate_latest_browser_visual_audit,
)
from tools.opportunity_lens.db import connect  # noqa: E402
from tools.opportunity_lens.publication import (  # noqa: E402
    PublicationGateReport,
    evaluate_publication_gate,
)
from tools.opportunity_lens.review_workflow import record_agent_review  # noqa: E402


REVIEW_MANIFEST_SCHEMA_VERSION = "opportunity_lens.silicon_review_manifest.v1"
REVIEW_STAGES = (
    "evidence",
    "calculation",
    "science",
    "financial",
    "writing",
    "browser",
    "final",
)
PRE_FINAL_REVIEW_STAGES = REVIEW_STAGES[:5]
NON_BROWSER_STAGES = frozenset(stage for stage in REVIEW_STAGES if stage != "browser")
ALLOWED_NON_BROWSER_KINDS = frozenset({"independent", "human"})
SILICON_RUN_SLUGS = frozenset(
    {
        "20260720_silicon_wafer_equipment_landscape_2026_2030",
        "20260720_silicon_wafer_fab_demand_2026_2030",
    }
)


@dataclass(frozen=True)
class ValidatedReview:
    stage: str
    reviewer_role: str
    reviewer_id: str
    review_kind: str
    findings: list[Any]
    artifact_path: Path
    artifact_hash: str
    input_artifact_hash: str
    output_artifact_hash: str


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"JSON 不允许非有限数值常量: {value}")


def _load_json_object(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"无法读取{label}: {path}") from exc
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{label}必须是 UTF-8 JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label}顶层必须是 JSON 对象: {path}")
    return payload, raw


def _resolve_project_json(project_root: Path, raw_path: Any, *, label: str) -> Path:
    value = str(raw_path or "").strip()
    if not value:
        raise ValueError(f"{label}路径为空")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{label}不存在: {candidate}") from exc
    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise ValueError(f"{label}必须位于 project-root 内: {resolved}") from exc
    if not resolved.is_file() or resolved.suffix.lower() != ".json":
        raise ValueError(f"{label}必须是 JSON 文件: {resolved}")
    return resolved


def _required_text(payload: dict[str, Any], key: str, *, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}.{key} 必须是非空字符串")
    return value.strip()


def _normalize_declared_hash(value: Any, *, field: str) -> str:
    return normalize_sha256(value, field=field)


def _validate_manifest_identity(
    manifest: dict[str, Any],
    *,
    run_id: int,
    run_slug: str,
    freeze: ArtifactFreeze,
    browser_manifest_hash: str,
) -> int:
    if manifest.get("schema_version") != REVIEW_MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            "review manifest schema_version 不匹配: "
            f"expected={REVIEW_MANIFEST_SCHEMA_VERSION!r}, "
            f"actual={manifest.get('schema_version')!r}"
        )
    if manifest.get("run_id") != run_id:
        raise ValueError(
            f"review manifest run_id 不匹配: expected={run_id}, actual={manifest.get('run_id')!r}"
        )
    if manifest.get("run_slug") != run_slug:
        raise ValueError(
            "review manifest run_slug 不匹配: "
            f"expected={run_slug!r}, actual={manifest.get('run_slug')!r}"
        )
    review_round = manifest.get("review_round", 1)
    if not isinstance(review_round, int) or isinstance(review_round, bool) or review_round <= 0:
        raise ValueError("review manifest review_round 必须是正整数")

    declared_freeze = manifest.get("artifact_freeze")
    if not isinstance(declared_freeze, dict):
        raise ValueError("review manifest 缺少 artifact_freeze 对象")
    expected_freeze = {
        "pack_hash": freeze.pack_hash,
        "ui_bundle_hash": freeze.ui_bundle_hash,
        "browser_input_hash": freeze.browser_input_hash,
    }
    for key, expected in expected_freeze.items():
        actual = _normalize_declared_hash(
            declared_freeze.get(key),
            field=f"review_manifest.artifact_freeze.{key}",
        )
        if actual != expected:
            raise ValueError(
                f"review manifest 的 {key} 已过期: expected={expected}, actual={actual}"
            )
    declared_browser_hash = _normalize_declared_hash(
        manifest.get("browser_manifest_hash"),
        field="review_manifest.browser_manifest_hash",
    )
    if declared_browser_hash != browser_manifest_hash:
        raise ValueError(
            "review manifest 未绑定最新 browser_visual_audit: "
            f"expected={browser_manifest_hash}, actual={declared_browser_hash}"
        )
    return review_round


def _review_references(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_reviews = manifest.get("reviews")
    if not isinstance(raw_reviews, list):
        raise ValueError("review manifest reviews 必须是数组")
    references: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(raw_reviews):
        if not isinstance(item, dict):
            raise ValueError(f"review manifest reviews[{index}] 必须是对象")
        stage = _required_text(item, "stage", label=f"reviews[{index}]")
        if stage not in REVIEW_STAGES:
            raise ValueError(f"review manifest 包含未知 stage: {stage}")
        if stage in references:
            raise ValueError(f"review manifest stage 重复: {stage}")
        references[stage] = item
    missing = [stage for stage in REVIEW_STAGES if stage not in references]
    extra = sorted(set(references) - set(REVIEW_STAGES))
    if missing or extra or len(references) != len(REVIEW_STAGES):
        raise ValueError(
            f"review manifest 必须恰好包含七个 stage; missing={missing}, extra={extra}"
        )
    return references


def _validate_review_identity(
    review: dict[str, Any],
    *,
    stage: str,
    run_id: int,
    run_slug: str,
    freeze: ArtifactFreeze,
    browser_manifest_hash: str,
    artifact_path: Path,
    artifact_hash: str,
) -> ValidatedReview:
    label = f"{stage} review"
    if review.get("run_id") != run_id:
        raise ValueError(
            f"{label} run_id 不匹配: expected={run_id}, actual={review.get('run_id')!r}"
        )
    if review.get("run_slug") != run_slug:
        raise ValueError(
            f"{label} run_slug 不匹配: expected={run_slug!r}, actual={review.get('run_slug')!r}"
        )
    if review.get("review_stage") != stage:
        raise ValueError(
            f"{label} review_stage 不匹配: actual={review.get('review_stage')!r}"
        )
    if review.get("review_verdict") != "GREEN":
        raise ValueError(f"{label} review_verdict 必须为 GREEN")
    if review.get("reconciliation_status") != "resolved":
        raise ValueError(f"{label} reconciliation_status 必须为 resolved")

    reviewer_role = _required_text(review, "reviewer_role", label=label)
    reviewer_id = _required_text(review, "reviewer_id", label=label)
    review_kind = _required_text(review, "review_kind", label=label)
    if stage == "browser":
        if review_kind != "deterministic":
            raise ValueError("browser review_kind 必须为 deterministic")
        expected_input = freeze.browser_input_hash
    else:
        if review_kind not in ALLOWED_NON_BROWSER_KINDS:
            raise ValueError(
                f"{label} review_kind 必须为 independent 或 human，实际为 {review_kind!r}"
            )
        expected_input = freeze.pack_hash
    actual_input = _normalize_declared_hash(
        review.get("input_artifact_hash"),
        field=f"{stage}.input_artifact_hash",
    )
    if actual_input != expected_input:
        raise ValueError(
            f"{label} 输入已过期: expected={expected_input}, actual={actual_input}"
        )

    findings = review.get("findings")
    if not isinstance(findings, list):
        raise ValueError(f"{label}.findings 必须是数组")

    output_hash = artifact_hash
    if stage == "browser":
        declared_output = _normalize_declared_hash(
            review.get("output_artifact_hash"),
            field="browser.output_artifact_hash",
        )
        if declared_output != browser_manifest_hash:
            raise ValueError(
                "browser review 输出未绑定最新 browser_visual_audit: "
                f"expected={browser_manifest_hash}, actual={declared_output}"
            )
        output_hash = browser_manifest_hash

    return ValidatedReview(
        stage=stage,
        reviewer_role=reviewer_role,
        reviewer_id=reviewer_id,
        review_kind=review_kind,
        findings=findings,
        artifact_path=artifact_path,
        artifact_hash=artifact_hash,
        input_artifact_hash=actual_input,
        output_artifact_hash=output_hash,
    )


def _validate_final_bindings(
    final_payload: dict[str, Any],
    *,
    freeze: ArtifactFreeze,
    browser_manifest_hash: str,
    reviews: dict[str, ValidatedReview],
) -> None:
    bindings = final_payload.get("bindings")
    if not isinstance(bindings, dict):
        raise ValueError("final review 缺少 bindings 对象")
    pack_hash = _normalize_declared_hash(
        bindings.get("pack_hash"),
        field="final.bindings.pack_hash",
    )
    if pack_hash != freeze.pack_hash:
        raise ValueError(
            f"final review pack 绑定已过期: expected={freeze.pack_hash}, actual={pack_hash}"
        )
    browser_hash = _normalize_declared_hash(
        bindings.get("browser_manifest_hash"),
        field="final.bindings.browser_manifest_hash",
    )
    if browser_hash != browser_manifest_hash:
        raise ValueError(
            "final review browser manifest 绑定已过期: "
            f"expected={browser_manifest_hash}, actual={browser_hash}"
        )
    review_hashes = bindings.get("review_artifact_hashes")
    if not isinstance(review_hashes, dict):
        raise ValueError("final review 缺少 bindings.review_artifact_hashes 对象")
    actual_keys = set(review_hashes)
    expected_keys = set(PRE_FINAL_REVIEW_STAGES)
    if actual_keys != expected_keys:
        raise ValueError(
            "final review 必须恰好绑定前五份审核文件: "
            f"missing={sorted(expected_keys - actual_keys)}, "
            f"extra={sorted(actual_keys - expected_keys)}"
        )
    for stage in PRE_FINAL_REVIEW_STAGES:
        declared = _normalize_declared_hash(
            review_hashes.get(stage),
            field=f"final.bindings.review_artifact_hashes.{stage}",
        )
        expected = reviews[stage].artifact_hash
        if declared != expected:
            raise ValueError(
                f"final review 对 {stage} 审核文件的绑定不一致: "
                f"expected={expected}, actual={declared}"
            )


def _validate_review_artifacts(
    manifest: dict[str, Any],
    *,
    project_root: Path,
    run_id: int,
    run_slug: str,
    freeze: ArtifactFreeze,
    browser_manifest_hash: str,
) -> list[ValidatedReview]:
    references = _review_references(manifest)
    payloads: dict[str, dict[str, Any]] = {}
    validated: dict[str, ValidatedReview] = {}
    for stage in REVIEW_STAGES:
        reference = references[stage]
        path = _resolve_project_json(
            project_root,
            reference.get("artifact_path"),
            label=f"{stage} review artifact",
        )
        payload, raw = _load_json_object(path, label=f"{stage} review artifact")
        actual_hash = sha256_bytes(raw)
        expected_hash = _normalize_declared_hash(
            reference.get("artifact_sha256"),
            field=f"review_manifest.reviews.{stage}.artifact_sha256",
        )
        if actual_hash != expected_hash:
            raise ValueError(
                f"{stage} review 文件 hash 不一致: expected={expected_hash}, actual={actual_hash}"
            )
        payloads[stage] = payload
        validated[stage] = _validate_review_identity(
            payload,
            stage=stage,
            run_id=run_id,
            run_slug=run_slug,
            freeze=freeze,
            browser_manifest_hash=browser_manifest_hash,
            artifact_path=path,
            artifact_hash=actual_hash,
        )
    _validate_final_bindings(
        payloads["final"],
        freeze=freeze,
        browser_manifest_hash=browser_manifest_hash,
        reviews=validated,
    )
    return [validated[stage] for stage in REVIEW_STAGES]


def _current_run_slug(conn: sqlite3.Connection, run_id: int) -> str:
    pack = latest_manual_pack_manifest(conn, run_id)
    slug = str(pack.get("pack_slug") or "").strip()
    if not slug:
        raise ValueError("manual_research_pack 缺少 pack_slug")
    return slug


def _validate_target_run(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row:
    if run_id <= 9:
        raise ValueError("硅片审核记录器拒绝修改 run1-run9")
    row = conn.execute(
        "SELECT id,run_status,run_readiness_status FROM opportunity_run WHERE id=?",
        (run_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"run 不存在: {run_id}")
    if row["run_status"] != "under_review" or row["run_readiness_status"] != "reviewable":
        raise ValueError(
            f"run {run_id} 不是 under_review/reviewable: "
            f"{row['run_status']}/{row['run_readiness_status']}"
        )
    return row


def _ensure_no_existing_reviews(conn: sqlite3.Connection, run_id: int) -> None:
    rows = conn.execute(
        """
        SELECT review_stage,COUNT(*) AS row_count
        FROM opportunity_agent_review_log
        WHERE run_id=?
        GROUP BY review_stage
        ORDER BY review_stage
        """,
        (run_id,),
    ).fetchall()
    if rows:
        summary = {str(row["review_stage"]): int(row["row_count"]) for row in rows}
        raise ValueError(f"拒绝重复写入 reviewer 记录；当前已有记录: {summary}")


def record_silicon_reviews(
    *,
    db_path: str | Path,
    run_id: int,
    review_manifest_path: str | Path,
    project_root: str | Path = DEFAULT_PROJECT_ROOT,
) -> dict[str, Any]:
    """Validate and atomically insert all seven publication review stages."""

    root = Path(project_root).resolve()
    manifest_path = _resolve_project_json(
        root,
        review_manifest_path,
        label="review manifest",
    )
    manifest, _ = _load_json_object(manifest_path, label="review manifest")

    conn = connect(Path(db_path))
    gate: PublicationGateReport | None = None
    recorded: list[dict[str, Any]] = []
    freeze: ArtifactFreeze | None = None
    run_slug = ""
    browser_manifest_hash = ""
    try:
        conn.execute("BEGIN IMMEDIATE")
        _validate_target_run(conn, run_id)
        run_slug = _current_run_slug(conn, run_id)
        if run_slug not in SILICON_RUN_SLUGS:
            raise ValueError(f"run slug 不属于本次两个硅片研究: {run_slug}")
        freeze = build_artifact_freeze(conn, run_id, project_root=root)
        browser_validation: BrowserAuditValidation = validate_latest_browser_visual_audit(
            conn,
            run_id,
            project_root=root,
            verify_screenshots=True,
        )
        if not browser_validation.valid or not browser_validation.manifest_hash:
            raise ValueError(
                "最新 browser_visual_audit 未通过: "
                + "; ".join(browser_validation.issues or ["缺少 manifest hash"])
            )
        browser_manifest_hash = _normalize_declared_hash(
            browser_validation.manifest_hash,
            field="latest_browser_visual_audit.manifest_hash",
        )
        review_round = _validate_manifest_identity(
            manifest,
            run_id=run_id,
            run_slug=run_slug,
            freeze=freeze,
            browser_manifest_hash=browser_manifest_hash,
        )
        reviews = _validate_review_artifacts(
            manifest,
            project_root=root,
            run_id=run_id,
            run_slug=run_slug,
            freeze=freeze,
            browser_manifest_hash=browser_manifest_hash,
        )
        _ensure_no_existing_reviews(conn, run_id)

        for review in reviews:
            review_id = record_agent_review(
                conn,
                run_id,
                review_round,
                review.reviewer_role,
                "GREEN",
                "resolved",
                json.dumps(review.findings, ensure_ascii=False, sort_keys=True),
                review_stage=review.stage,
                reviewer_id=review.reviewer_id,
                review_kind=review.review_kind,
                input_artifact_hash=review.input_artifact_hash,
                output_artifact_hash=review.output_artifact_hash,
            )
            recorded.append(
                {
                    "stage": review.stage,
                    "review_id": review_id,
                    "review_artifact_hash": review.artifact_hash,
                    "recorded_output_hash": review.output_artifact_hash,
                }
            )

        gate = evaluate_publication_gate(
            conn,
            run_id,
            project_root=root,
            verify_browser_screenshots=True,
        )
        if not gate.eligible:
            raise ValueError(
                "七阶段 reviewer 写入后发布门禁仍被阻塞: " + "; ".join(gate.blockers)
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    assert freeze is not None and gate is not None
    return {
        "db": str(Path(db_path).resolve()),
        "run_id": run_id,
        "run_slug": run_slug,
        "review_manifest": str(manifest_path),
        "artifact_freeze": freeze.as_dict(),
        "browser_manifest_hash": browser_manifest_hash,
        "recorded": recorded,
        "publication_gate_eligible": gate.eligible,
        "publication_gate_details": gate.details,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="校验真实 JSON 审核文件，并在单事务内记录硅片研究的七阶段 reviewer"
    )
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--review-manifest", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    result = record_silicon_reviews(
        db_path=args.db,
        run_id=args.run_id,
        review_manifest_path=args.review_manifest,
        project_root=args.project_root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
