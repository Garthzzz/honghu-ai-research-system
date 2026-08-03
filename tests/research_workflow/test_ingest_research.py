from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.pipeline import ingest_research
from tools.research_core.manifest import ExecutionManifest
from tools.research_core.workflow import ResearchWorkflowRun


SCHEMA = """
CREATE TABLE industry(id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE source(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT, source_type TEXT, publisher TEXT, publish_date TEXT,
  quality_tier INTEGER, is_forward_looking INTEGER, file_path TEXT,
  value_layer TEXT, fetch_method TEXT, source_credibility TEXT,
  language TEXT, is_primary_source INTEGER, source_subtype TEXT,
  url TEXT, source_url TEXT, key_arguments TEXT,
  fetch_timestamp TEXT, domain TEXT, content_snapshot_path TEXT
);
CREATE TABLE source_entity(
  source_id INTEGER, entity_type TEXT, entity_id INTEGER, coverage TEXT,
  UNIQUE(source_id, entity_type, entity_id)
);
CREATE TABLE company(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE);
CREATE TABLE company_industry(company_id INTEGER, industry_id INTEGER, UNIQUE(company_id, industry_id));
CREATE TABLE industry_data_point(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  industry_id INTEGER NOT NULL, metric TEXT NOT NULL, period TEXT NOT NULL,
  value_num REAL, value_text TEXT, unit TEXT NOT NULL, is_forecast INTEGER NOT NULL,
  as_of_date TEXT, sentiment TEXT, source_id INTEGER NOT NULL,
  source_excerpt TEXT NOT NULL, note TEXT, company_id INTEGER,
  extraction_method TEXT NOT NULL
);
"""


class UnifiedIngestTests(unittest.TestCase):
    def _prepare(self, root: Path, *, valid: bool) -> Path:
        (root / "cache" / "claims").mkdir(parents=True)
        (root / "papers" / "demo").mkdir(parents=True)
        (root / "papers" / "demo" / "report.pdf").write_bytes(b"fixture")
        payload = {
            "_meta": {"scope": "历史 claims 字符串范围"},
            "sources": [
                {
                    "source_file": "report.pdf",
                    "title": "测试原始研报",
                    "source_type": "卖方深度",
                    "publisher": "测试机构",
                    "publish_date": "2026-07-01",
                    "quality_tier": 2,
                    "language": "zh-CN",
                }
            ],
            "data_points": [
                {
                    "source_file": "report.pdf",
                    "company": "测试公司",
                    "metric": "" if not valid else "收入",
                    "period": "2026",
                    "value_num": 12.0,
                    "unit": "亿元",
                    "source_excerpt": "原文给出 2026 年收入 12 亿元。",
                    "extraction_method": "pdf_direct",
                }
            ],
            "key_arguments": [],
        }
        (root / "cache" / "claims" / "demo_1_claims.json").write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        db_path = root / "research.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO industry(id,name) VALUES(1,'测试行业')")
        conn.commit()
        conn.close()
        return db_path

    @staticmethod
    def _connect(path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def test_success_writes_manifest_and_parallel_fact_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = self._prepare(root, valid=True)
            with (
                patch.object(ingest_research, "ROOT", root),
                patch.object(ingest_research.db_writer, "get_db", side_effect=lambda: self._connect(db_path)),
                patch.object(ingest_research.consensus_compute, "recompute_all", return_value=(0, 0)),
            ):
                result = ingest_research.ingest(
                    track="a",
                    industry_id=1,
                    tag="demo",
                    papers_subdir="demo",
                )
            self.assertEqual(result["data_points_written"], 1)
            self.assertEqual(result["parallel_research_fact_count"], 1)
            self.assertTrue(Path(result["brief_path"]).is_file())
            self.assertTrue(Path(result["manifest_path"]).is_file())
            manifest = ExecutionManifest.read(result["manifest_path"])
            brief = json.loads(Path(result["brief_path"]).read_text(encoding="utf-8"))
            self.assertEqual(brief["scope"], {"description": "历史 claims 字符串范围"})
            self.assertEqual(
                {gate.gate for gate in manifest.gates},
                {"contract", "evidence_integrity", "provenance", "duplication", "scope_and_units"},
            )
            self.assertEqual(manifest.required_reviews, ["evidence", "final"])
            self.assertEqual(manifest.reviews, [])
            self.assertTrue(all(item.status == "pending" for item in manifest.requirement_coverage.values()))
            self.assertEqual(result["content_cache_hits"], 0)
            conn = self._connect(db_path)
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM source").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM company").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM industry_data_point").fetchone()[0], 1)
            finally:
                conn.close()

    def test_invalid_record_rolls_back_source_company_and_data_point(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = self._prepare(root, valid=False)
            with (
                patch.object(ingest_research, "ROOT", root),
                patch.object(ingest_research.db_writer, "get_db", side_effect=lambda: self._connect(db_path)),
                patch.object(ingest_research.consensus_compute, "recompute_all", return_value=(0, 0)),
            ):
                with self.assertRaises(ValueError):
                    ingest_research.ingest(
                        track="b",
                        industry_id=1,
                        tag="demo",
                        papers_subdir="demo",
                    )
            conn = self._connect(db_path)
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM source").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM company").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM industry_data_point").fetchone()[0], 0)
            finally:
                conn.close()

    def test_legacy_extraction_method_is_not_silently_coerced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = self._prepare(root, valid=True)
            claim_path = root / "cache" / "claims" / "demo_1_claims.json"
            payload = json.loads(claim_path.read_text(encoding="utf-8"))
            payload["data_points"][0]["extraction_method"] = "template_estimate"
            claim_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with (
                patch.object(ingest_research, "ROOT", root),
                patch.object(ingest_research.db_writer, "get_db", side_effect=lambda: self._connect(db_path)),
                patch.object(ingest_research.consensus_compute, "recompute_all", return_value=(0, 0)),
            ):
                with self.assertRaises(ValueError):
                    ingest_research.ingest(track="a", industry_id=1, tag="demo", papers_subdir="demo")
            conn = self._connect(db_path)
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM industry_data_point").fetchone()[0], 0)
            finally:
                conn.close()

    def test_allow_invalid_records_does_not_create_ghost_company(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = self._prepare(root, valid=False)
            with (
                patch.object(ingest_research, "ROOT", root),
                patch.object(ingest_research.db_writer, "get_db", side_effect=lambda: self._connect(db_path)),
                patch.object(ingest_research.consensus_compute, "recompute_all", return_value=(0, 0)),
            ):
                result = ingest_research.ingest(
                    track="a",
                    industry_id=1,
                    tag="demo",
                    papers_subdir="demo",
                    allow_invalid_records=True,
                )
            self.assertEqual(len(result["invalid_records"]), 1)
            conn = self._connect(db_path)
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM company").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM industry_data_point").fetchone()[0], 0)
            finally:
                conn.close()

    def test_invalid_key_argument_is_governed_by_strict_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = self._prepare(root, valid=True)
            claim_path = root / "cache" / "claims" / "demo_1_claims.json"
            payload = json.loads(claim_path.read_text(encoding="utf-8"))
            payload["key_arguments"] = [{"source_file": "report.pdf", "claim": ""}]
            claim_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with (
                patch.object(ingest_research, "ROOT", root),
                patch.object(ingest_research.db_writer, "get_db", side_effect=lambda: self._connect(db_path)),
                patch.object(ingest_research.consensus_compute, "recompute_all", return_value=(0, 0)),
            ):
                with self.assertRaises(ValueError):
                    ingest_research.ingest(track="b", industry_id=1, tag="demo", papers_subdir="demo")
            conn = self._connect(db_path)
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM source").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM industry_data_point").fetchone()[0], 0)
            finally:
                conn.close()

    def test_b_track_without_request_preserves_ingest_but_blocks_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = self._prepare(root, valid=True)
            with (
                patch.object(ingest_research, "ROOT", root),
                patch.object(ingest_research.db_writer, "get_db", side_effect=lambda: self._connect(db_path)),
                patch.object(ingest_research.consensus_compute, "recompute_all", return_value=(0, 0)),
            ):
                result = ingest_research.ingest(track="b", industry_id=1, tag="demo", papers_subdir="demo")
            run = ResearchWorkflowRun.load(Path(result["manifest_path"]).parent)
            latest_gates = {gate.gate: gate for gate in run.manifest.gates}
            self.assertEqual(latest_gates["contract"].verdict, "RED")
            blocked = [item for item in run.manifest.requirement_coverage.values() if item.status == "blocked"]
            self.assertEqual(len(blocked), 1)
            self.assertIn("原始 B 轨 prompt", blocked[0].note)
            self.assertFalse(run.evaluate_publication())

    def test_b_track_request_is_compiled_and_cache_history_are_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = self._prepare(root, valid=True)
            request_path = root / "request.json"
            request_path.write_text(json.dumps({
                "run_key": "demo",
                "track": "b",
                "title": "测试行业 B 轨",
                "research_question": "测试行业客户订单是否兑现？",
                "prompt_requirements": [{
                    "question": "核验客户订单与现金流",
                    "acceptance_criteria": "至少两条独立官方证据",
                }],
            }, ensure_ascii=False), encoding="utf-8")
            with (
                patch.object(ingest_research, "ROOT", root),
                patch.object(ingest_research.db_writer, "get_db", side_effect=lambda: self._connect(db_path)),
                patch.object(ingest_research.consensus_compute, "recompute_all", return_value=(0, 0)),
            ):
                first = ingest_research.ingest(
                    track="b", industry_id=1, tag="demo", papers_subdir="demo",
                    workflow_request_path=request_path,
                )
                second = ingest_research.ingest(
                    track="b", industry_id=1, tag="demo", papers_subdir="demo",
                    workflow_request_path=request_path,
                )
            run = ResearchWorkflowRun.load(Path(second["manifest_path"]).parent)
            self.assertIn("核验客户订单与现金流", [item.question for item in run.brief.requirements])
            self.assertEqual({gate.gate: gate.verdict for gate in run.manifest.gates}["contract"], "GREEN")
            self.assertEqual(first["content_cache_hits"], 0)
            self.assertEqual(second["content_cache_hits"], 1)
            self.assertEqual(first["data_points_written"], 1)
            self.assertEqual(first["data_points_reused"], 0)
            self.assertEqual(second["data_points_written"], 0)
            self.assertEqual(second["data_points_reused"], 1)
            conn = self._connect(db_path)
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM industry_data_point"
                    ).fetchone()[0],
                    1,
                )
            finally:
                conn.close()
            history = list((Path(second["manifest_path"]).parent / "history").glob("*/manifest.json"))
            self.assertEqual(len(history), 1)


if __name__ == "__main__":
    unittest.main()
