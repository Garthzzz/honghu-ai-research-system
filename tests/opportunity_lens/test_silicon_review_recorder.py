from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.opportunity_lens import silicon_review_recorder as recorder
from tools.opportunity_lens.artifact_freeze import ArtifactFreeze, sha256_bytes
from tools.opportunity_lens.browser_audit_contract import BrowserAuditValidation
from tools.opportunity_lens.db import connect
from tools.opportunity_lens.migrate import init_db
from tools.opportunity_lens.publication import PublicationGateReport


class SiliconReviewRecorderTests(unittest.TestCase):
    RUN_ID = 10
    RUN_SLUG = "20260720_silicon_wafer_equipment_landscape_2026_2030"
    PACK_HASH = "sha256:" + "1" * 64
    UI_HASH = "sha256:" + "2" * 64
    BROWSER_INPUT_HASH = "sha256:" + "3" * 64
    BROWSER_MANIFEST_HASH = "sha256:" + "4" * 64

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.db_path = self.root / "temporary_opportunity_lens.db"
        init_db(self.db_path)
        self.freeze = ArtifactFreeze(
            run_id=self.RUN_ID,
            pack_hash=self.PACK_HASH,
            ui_bundle_hash=self.UI_HASH,
            browser_input_hash=self.BROWSER_INPUT_HASH,
            ui_file_count=5,
            pack_schema_version="opportunity_lens.run_pack.v2",
        )
        conn = connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO opportunity_run(
                  id,question,research_question,display_title,run_mode,run_status,
                  run_readiness_status,evidence_policy,schema_version,
                  api_contract_version,score_rule_version,source_tier_version,
                  search_protocol_version,report_template_version,pdf_export_version
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    self.RUN_ID,
                    "硅片设备研究测试",
                    "硅片设备研究测试",
                    "硅片设备研究测试",
                    "c_open",
                    "under_review",
                    "reviewable",
                    "balanced",
                    "schema.test",
                    "api.test",
                    "score.test",
                    "source.test",
                    "search.test",
                    "report.test",
                    "pdf.test",
                ),
            )
            pack_manifest = {
                "pack_slug": self.RUN_SLUG,
                "pack_hash": self.PACK_HASH,
                "pack_schema_version": "opportunity_lens.run_pack.v2",
            }
            conn.execute(
                """
                INSERT INTO opportunity_run_manifest(
                  run_id,manifest_type,manifest_json,manifest_hash,
                  workflow_contract_version,pack_schema_version
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    self.RUN_ID,
                    "manual_research_pack",
                    json.dumps(pack_manifest, ensure_ascii=False, sort_keys=True),
                    self.PACK_HASH,
                    "research.workflow.v2",
                    "opportunity_lens.run_pack.v2",
                ),
            )
            conn.execute(
                """
                INSERT INTO opportunity_run_manifest(
                  run_id,manifest_type,manifest_json,manifest_hash,
                  workflow_contract_version,pack_schema_version
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    self.RUN_ID,
                    "browser_visual_audit",
                    "{}",
                    self.BROWSER_MANIFEST_HASH,
                    "research.workflow.v2",
                    "opportunity_lens.run_pack.v2",
                ),
            )
            conn.commit()
        finally:
            conn.close()
        self.manifest_path = self._create_review_files_and_manifest()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _review_payload(self, stage: str) -> dict:
        payload = {
            "run_id": self.RUN_ID,
            "run_slug": self.RUN_SLUG,
            "review_stage": stage,
            "reviewer_role": f"independent_{stage}_reviewer",
            "reviewer_id": f"test-{stage}-reviewer",
            "review_kind": "deterministic" if stage == "browser" else "independent",
            "review_verdict": "GREEN",
            "reconciliation_status": "resolved",
            "findings": [],
            "input_artifact_hash": (
                self.BROWSER_INPUT_HASH if stage == "browser" else self.PACK_HASH
            ),
        }
        if stage == "browser":
            payload["output_artifact_hash"] = self.BROWSER_MANIFEST_HASH
        return payload

    def _write_json(self, path: Path, payload: dict) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return sha256_bytes(path.read_bytes())

    def _create_review_files_and_manifest(self) -> Path:
        review_dir = self.root / "reviews"
        review_payloads = {
            stage: self._review_payload(stage) for stage in recorder.REVIEW_STAGES
        }
        artifact_hashes: dict[str, str] = {}
        for stage in recorder.REVIEW_STAGES[:-1]:
            artifact_hashes[stage] = self._write_json(
                review_dir / f"{stage}.json",
                review_payloads[stage],
            )
        review_payloads["final"]["bindings"] = {
            "pack_hash": self.PACK_HASH,
            "browser_manifest_hash": self.BROWSER_MANIFEST_HASH,
            "review_artifact_hashes": {
                stage: artifact_hashes[stage]
                for stage in recorder.PRE_FINAL_REVIEW_STAGES
            },
        }
        artifact_hashes["final"] = self._write_json(
            review_dir / "final.json",
            review_payloads["final"],
        )
        manifest = {
            "schema_version": recorder.REVIEW_MANIFEST_SCHEMA_VERSION,
            "run_id": self.RUN_ID,
            "run_slug": self.RUN_SLUG,
            "review_round": 1,
            "artifact_freeze": {
                "pack_hash": self.PACK_HASH,
                "ui_bundle_hash": self.UI_HASH,
                "browser_input_hash": self.BROWSER_INPUT_HASH,
            },
            "browser_manifest_hash": self.BROWSER_MANIFEST_HASH,
            "reviews": [
                {
                    "stage": stage,
                    "artifact_path": (review_dir / f"{stage}.json")
                    .relative_to(self.root)
                    .as_posix(),
                    "artifact_sha256": artifact_hashes[stage],
                }
                for stage in recorder.REVIEW_STAGES
            ],
        }
        path = self.root / "review_manifest.json"
        self._write_json(path, manifest)
        return path

    def _browser_validation(self) -> BrowserAuditValidation:
        return BrowserAuditValidation(
            valid=True,
            manifest_hash=self.BROWSER_MANIFEST_HASH,
            manifest={},
            freeze=self.freeze,
        )

    def _run_with_gate(self, gate_callback):
        with (
            patch.object(recorder, "build_artifact_freeze", return_value=self.freeze),
            patch.object(
                recorder,
                "validate_latest_browser_visual_audit",
                return_value=self._browser_validation(),
            ),
            patch.object(recorder, "evaluate_publication_gate", side_effect=gate_callback),
        ):
            return recorder.record_silicon_reviews(
                db_path=self.db_path,
                run_id=self.RUN_ID,
                review_manifest_path=self.manifest_path,
                project_root=self.root,
            )

    def _green_gate(self, conn: sqlite3.Connection, run_id: int, **kwargs):
        self.assertTrue(conn.in_transaction)
        self.assertEqual(run_id, self.RUN_ID)
        count = conn.execute(
            "SELECT COUNT(*) FROM opportunity_agent_review_log WHERE run_id=?",
            (run_id,),
        ).fetchone()[0]
        self.assertEqual(count, 7)
        return PublicationGateReport(run_id=run_id, eligible=True, details={"checked": True})

    def _review_count(self) -> int:
        conn = connect(self.db_path, readonly=True)
        try:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM opportunity_agent_review_log WHERE run_id=?",
                    (self.RUN_ID,),
                ).fetchone()[0]
            )
        finally:
            conn.close()

    def _replace_manifest_reference_hash(self, stage: str, digest: str) -> None:
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        reference = next(item for item in manifest["reviews"] if item["stage"] == stage)
        reference["artifact_sha256"] = digest
        self._write_json(self.manifest_path, manifest)

    def test_records_exactly_seven_reviews_with_current_bindings(self) -> None:
        result = self._run_with_gate(self._green_gate)
        self.assertTrue(result["publication_gate_eligible"])
        self.assertEqual([item["stage"] for item in result["recorded"]], list(recorder.REVIEW_STAGES))

        conn = connect(self.db_path, readonly=True)
        try:
            rows = conn.execute(
                """
                SELECT review_stage,review_kind,input_artifact_hash,output_artifact_hash
                FROM opportunity_agent_review_log
                WHERE run_id=? ORDER BY id
                """,
                (self.RUN_ID,),
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(len(rows), 7)
        for row in rows:
            stage = row["review_stage"]
            expected_input = (
                self.BROWSER_INPUT_HASH if stage == "browser" else self.PACK_HASH
            )
            self.assertEqual(row["input_artifact_hash"], expected_input)
            self.assertEqual(
                row["review_kind"],
                "deterministic" if stage == "browser" else "independent",
            )
            if stage == "browser":
                self.assertEqual(row["output_artifact_hash"], self.BROWSER_MANIFEST_HASH)
            else:
                artifact_path = self.root / "reviews" / f"{stage}.json"
                self.assertEqual(row["output_artifact_hash"], sha256_bytes(artifact_path.read_bytes()))

    def test_review_file_hash_drift_writes_nothing(self) -> None:
        evidence_path = self.root / "reviews" / "evidence.json"
        evidence_path.write_bytes(evidence_path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "evidence review 文件 hash 不一致"):
            self._run_with_gate(self._green_gate)
        self.assertEqual(self._review_count(), 0)

    def test_final_must_bind_all_five_actual_review_hashes(self) -> None:
        final_path = self.root / "reviews" / "final.json"
        final_payload = json.loads(final_path.read_text(encoding="utf-8"))
        final_payload["bindings"]["review_artifact_hashes"]["science"] = "sha256:" + "9" * 64
        final_hash = self._write_json(final_path, final_payload)
        self._replace_manifest_reference_hash("final", final_hash)
        with self.assertRaisesRegex(ValueError, "final review 对 science 审核文件的绑定不一致"):
            self._run_with_gate(self._green_gate)
        self.assertEqual(self._review_count(), 0)

    def test_browser_review_must_be_deterministic_and_bind_latest_audit(self) -> None:
        browser_path = self.root / "reviews" / "browser.json"
        browser_payload = json.loads(browser_path.read_text(encoding="utf-8"))
        browser_payload["review_kind"] = "independent"
        browser_hash = self._write_json(browser_path, browser_payload)
        self._replace_manifest_reference_hash("browser", browser_hash)
        with self.assertRaisesRegex(ValueError, "browser review_kind 必须为 deterministic"):
            self._run_with_gate(self._green_gate)
        self.assertEqual(self._review_count(), 0)

    def test_gate_failure_rolls_back_all_seven_rows(self) -> None:
        def blocked_gate(conn: sqlite3.Connection, run_id: int, **kwargs):
            self.assertTrue(conn.in_transaction)
            count = conn.execute(
                "SELECT COUNT(*) FROM opportunity_agent_review_log WHERE run_id=?",
                (run_id,),
            ).fetchone()[0]
            self.assertEqual(count, 7)
            return PublicationGateReport(
                run_id=run_id,
                eligible=False,
                blockers=["forced temporary gate failure"],
            )

        with self.assertRaisesRegex(ValueError, "forced temporary gate failure"):
            self._run_with_gate(blocked_gate)
        self.assertEqual(self._review_count(), 0)

    def test_existing_reviews_are_not_duplicated(self) -> None:
        self._run_with_gate(self._green_gate)
        self.assertEqual(self._review_count(), 7)
        with self.assertRaisesRegex(ValueError, "拒绝重复写入 reviewer 记录"):
            self._run_with_gate(self._green_gate)
        self.assertEqual(self._review_count(), 7)

    def test_run_one_to_nine_are_always_rejected(self) -> None:
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest["run_id"] = 9
        self._write_json(self.manifest_path, manifest)
        with (
            patch.object(recorder, "build_artifact_freeze", return_value=self.freeze),
            patch.object(
                recorder,
                "validate_latest_browser_visual_audit",
                return_value=self._browser_validation(),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "拒绝修改 run1-run9"):
                recorder.record_silicon_reviews(
                    db_path=self.db_path,
                    run_id=9,
                    review_manifest_path=self.manifest_path,
                    project_root=self.root,
                )
        self.assertEqual(self._review_count(), 0)


if __name__ == "__main__":
    unittest.main()
