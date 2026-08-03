from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import yaml

from tools.pipeline import db_writer
from tools.pipeline.data_source_policy import assert_provider_allowed, normalize_provider
from tools.pipeline.ingest_research import source_key
from tools.research_core.brief import compile_research_brief
from tools.research_core.config import (
    WorkflowConfigError,
    brief_contract_version,
    cache_contract_version,
    clear_workflow_config_cache,
    load_workflow_config,
    manifest_contract_version,
    publish_review_stages,
    resolve_track_config,
    validate_modeling_skill_assets,
)
from tools.research_core.content_cache import ContentAddressedCache
from tools.research_core.manifest import ExecutionManifest, GateResult, ReviewRecord, hash_json
from tools.research_core.quality import build_review_plan


HASH_X = "sha256:" + "a" * 64
HASH_Y = "sha256:" + "b" * 64
HASH_Z = "sha256:" + "c" * 64


class CoreWorkflowContractTests(unittest.TestCase):
    def test_config_has_canonical_tracks_and_market_policy(self):
        config = load_workflow_config()
        self.assertEqual(config["contract_version"], "research.workflow.v2")
        self.assertEqual(set(config["tracks"]), {"a", "b", "c"})
        self.assertEqual(
            set(resolve_track_config("b")["market_data"]["allowed_providers"]),
            {"api_wind", "api_tushare", "api_yfinance"},
        )
        wind_policy = resolve_track_config("b")["market_data"]["a_share"]["wind_request_policy"]
        self.assertTrue(wind_policy["require_explicit_user_permission_for_large_request"])
        self.assertTrue(wind_policy["forbid_chunking_to_evade_limits"])
        self.assertEqual(wind_policy["unapproved_max_securities_per_request"], 10)

    def test_config_cache_invalidates_on_file_change_and_returns_safe_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow.yaml"
            original = Path("config/research_workflow.yaml").read_text(encoding="utf-8")
            path.write_text(original, encoding="utf-8")
            clear_workflow_config_cache()
            first = load_workflow_config(path)
            first["tracks"]["a"]["label"] = "caller mutation"
            self.assertNotEqual(load_workflow_config(path)["tracks"]["a"]["label"], "caller mutation")
            path.write_text(original.replace("A 轨纯研报行业研究", "A 轨缓存失效测试"), encoding="utf-8")
            self.assertEqual(load_workflow_config(path)["tracks"]["a"]["label"], "A 轨缓存失效测试")
            clear_workflow_config_cache()

    def test_viewer_contract_load_is_decoupled_from_backend_skill_assets(self):
        config = load_workflow_config()
        with tempfile.TemporaryDirectory() as tmp:
            empty_deployment_root = Path(tmp)
            self.assertEqual(config["contract_version"], "research.workflow.v2")
            with self.assertRaises(WorkflowConfigError):
                validate_modeling_skill_assets(
                    config=config,
                    root=empty_deployment_root,
                )

    def test_c_track_public_output_review_contract_keys_are_mandatory(self):
        base = load_workflow_config()
        mutations = {
            "public_output_contract": lambda cfg: cfg["tracks"]["c"].pop("public_output_contract"),
            "public_output_required_flag": lambda cfg: cfg["tracks"]["c"]["public_output_contract"].pop("require_formula_translation"),
            "writing_review_check": lambda cfg: cfg["tracks"]["c"]["writing_review_checks"].remove("no_low_information_or_redundant_tables"),
            "browser_review_check": lambda cfg: cfg["tracks"]["c"]["browser_review_checks"].remove("rightmost_header_and_cells_are_fully_visible"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow.yaml"
            for name, mutate in mutations.items():
                with self.subTest(name=name):
                    payload = deepcopy(base)
                    mutate(payload)
                    path.write_text(
                        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                        encoding="utf-8",
                    )
                    clear_workflow_config_cache()
                    with self.assertRaises(WorkflowConfigError):
                        load_workflow_config(path)
            clear_workflow_config_cache()

    def test_brief_manifest_and_cache_versions_come_from_machine_contract(self):
        brief = compile_research_brief(
            track="a", title="版本测试", research_question="版本是否一致？"
        )
        manifest = ExecutionManifest(run_key="version-contract", track="a")
        with tempfile.TemporaryDirectory() as tmp:
            cache_record = ContentAddressedCache(tmp).put_text("versioned")
        self.assertEqual(brief.brief_version, brief_contract_version())
        self.assertEqual(manifest.manifest_version, manifest_contract_version())
        self.assertEqual(cache_record["cache_contract_version"], cache_contract_version())

    def test_b_brief_is_prompt_union_default_without_exact_duplicates(self):
        default_item = resolve_track_config("a")["default_coverage"][0]
        brief = compile_research_brief(
            track="b",
            title="测试行业",
            research_question="测试行业是否值得跟踪",
            prompt_requirements=[
                default_item,
                {
                    "question": "客户验证和订单兑现",
                    "output_hint": "Q3",
                    "acceptance_criteria": "至少两条独立官方证据",
                },
            ],
            decision_use="决定研究优先级",
            must_include=["订单", "订单"],
            exclusions=["光伏口径"],
            scope={"geography": ["全球", "中国"]},
            time_window={"core": "2025-2027"},
            quality_floor={"industry_main": 15000},
        )
        questions = [item.question for item in brief.requirements]
        self.assertEqual(questions.count(default_item), 1)
        self.assertIn("客户验证和订单兑现", questions)
        merged = next(item for item in brief.requirements if item.question == default_item)
        self.assertEqual(merged.origin, "default+prompt")
        prompt_item = next(item for item in brief.requirements if item.question == "客户验证和订单兑现")
        self.assertEqual(prompt_item.output_hint, "Q3")
        self.assertEqual(prompt_item.acceptance_criteria, "至少两条独立官方证据")
        self.assertEqual(brief.decision_use, "决定研究优先级")
        self.assertEqual(brief.must_include, ["订单"])
        self.assertEqual(brief.scope["geography"], ["全球", "中国"])
        self.assertEqual(brief.quality_floor["industry_main"], 15000)
        self.assertIn("q6_supplement", brief.required_artifacts)

    def test_brief_does_not_delete_semantically_similar_but_distinct_prompt_requirements(self):
        brief = compile_research_brief(
            track="b",
            title="测试行业",
            research_question="研究订单",
            prompt_requirements=["分析订单变化", "分析订单结构变化"],
        )
        prompt_questions = [item.question for item in brief.requirements if item.origin == "prompt"]
        self.assertEqual(prompt_questions, ["分析订单变化", "分析订单结构变化"])

    def test_content_cache_reports_real_hit(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = ContentAddressedCache(tmp)
            first = cache.put_text("same content", metadata={"url": "https://example.com/a"})
            second = cache.put_text("same content", metadata={"url": "https://example.com/a"})
            third = cache.put_text("same content", metadata={"url": "https://example.com/b"})
            self.assertFalse(first["cache_hit"])
            self.assertTrue(second["cache_hit"])
            self.assertTrue(second["metadata_hit"])
            self.assertFalse(third["metadata_hit"])
            self.assertEqual(first["hash"], second["hash"])
            self.assertEqual(cache.read_bytes(first["hash"], suffix=".txt"), b"same content")
            self.assertEqual(
                cache.provenance_records(first["hash"], suffix=".txt"),
                [{"url": "https://example.com/a"}, {"url": "https://example.com/b"}],
            )

    def test_content_cache_detects_provenance_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = ContentAddressedCache(tmp)
            result = cache.put_text("same content", metadata={"url": "https://example.com/a"})
            metadata_path = Path(result["metadata_path"])
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            payload["provenance"]["url"] = "https://example.com/tampered"
            metadata_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(IOError):
                cache.provenance_records(result["hash"], suffix=".txt")

    def test_manifest_requires_final_green(self):
        manifest = ExecutionManifest(run_key="x", track="c")
        for gate in resolve_track_config("c")["review"]["deterministic_gates"]:
            manifest.record_gate(GateResult(gate, "GREEN"))
        manifest.set_review_plan(["evidence", "science", "writing", "final"])
        for stage in ("evidence", "science", "writing"):
            manifest.record_review(
                ReviewRecord(
                    stage,
                    f"{stage}_reviewer",
                    "GREEN",
                    "resolved",
                    reviewer_id=f"independent-{stage}",
                    input_artifact_hash=HASH_X,
                    output_artifact_hash=HASH_Y,
                )
            )
        manifest.record_review(
            ReviewRecord(
                "final", "final", "RED", "pending", reviewer_id="independent-final",
                input_artifact_hash=HASH_X, output_artifact_hash=HASH_Y,
            )
        )
        self.assertFalse(manifest.evaluate_publication())
        manifest.record_review(
            ReviewRecord(
                "final", "final", "GREEN", "resolved", reviewer_id="independent-final",
                input_artifact_hash=HASH_Y, output_artifact_hash=HASH_Z,
            )
        )
        self.assertTrue(manifest.evaluate_publication())

    def test_manifest_hash_detects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            manifest = ExecutionManifest(run_key="tamper", track="a")
            manifest.write(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["run_key"] = "changed"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError):
                ExecutionManifest.read(path)

    def test_manifest_requires_self_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text(json.dumps({"run_key": "missing", "track": "a"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                ExecutionManifest.read(path)

    def test_manifest_rejects_unsupported_contract_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            manifest = ExecutionManifest(run_key="version", track="a")
            payload = manifest.as_dict()
            payload["workflow_contract_version"] = "research.workflow.v999"
            payload.pop("manifest_hash")
            payload["manifest_hash"] = hash_json(payload)
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError):
                ExecutionManifest.read(path)

    def test_review_plan_uses_canonical_stage_names_and_skips_contract_reviewer(self):
        stages = [task.stage for task in build_review_plan(
            track="c",
            artifacts={"calculations", "scoring", "company_financials", "public_markdown", "public_ui"},
        )]
        self.assertEqual(
            stages,
            ["evidence", "calculation", "science", "financial", "writing", "browser", "final"],
        )
        self.assertNotIn("contract", stages)
        self.assertEqual(
            publish_review_stages("c", ["public_ui", "market_linked", "security_target"]),
            ["evidence", "calculation", "science", "financial", "writing", "browser", "final"],
        )

    def test_ab_web_source_requires_real_url(self):
        with self.assertRaises(ValueError):
            source_key({"title": "只有标题的二手材料", "source_ref": "missing-url"})
        key = source_key({"title": "官方页面", "source_url": "https://example.com/source"})
        self.assertEqual((key.kind, key.value), ("url", "https://example.com/source"))

    def test_market_provider_aliases_and_bans_are_canonical(self):
        self.assertEqual(normalize_provider("Tushare"), "api_tushare")
        self.assertEqual(normalize_provider("Yahoo Finance"), "api_yfinance")
        self.assertEqual(normalize_provider("Wind"), "api_wind")
        self.assertEqual(normalize_provider("WindPy"), "api_wind")
        for provider in ("Wind", "WindPy", "api_wind"):
            with self.subTest(provider=provider):
                assert_provider_allowed(provider)
        for provider in ("Akshare", "other_vendor"):
            with self.subTest(provider=provider), self.assertRaises(RuntimeError):
                assert_provider_allowed(provider)


class DataPointWriterTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE industry(id INTEGER PRIMARY KEY);
            CREATE TABLE source(id INTEGER PRIMARY KEY);
            CREATE TABLE company(id INTEGER PRIMARY KEY);
            CREATE TABLE industry_data_point(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              industry_id INTEGER NOT NULL,
              metric TEXT NOT NULL,
              period TEXT NOT NULL,
              value_num REAL,
              value_text TEXT,
              unit TEXT NOT NULL,
              is_forecast INTEGER NOT NULL,
              as_of_date TEXT,
              sentiment TEXT,
              source_id INTEGER NOT NULL,
              source_excerpt TEXT NOT NULL,
              note TEXT,
              company_id INTEGER,
              extraction_method TEXT NOT NULL
            );
            INSERT INTO industry(id) VALUES(1);
            INSERT INTO source(id) VALUES(1);
            INSERT INTO company(id) VALUES(1);
            """
        )

    def tearDown(self):
        self.conn.close()

    def item(self, **overrides):
        value = {
            "industry_id": 1,
            "metric": "市场规模",
            "period": "2026",
            "unit": "亿元",
            "source_id": 1,
            "source_excerpt": "原文明确给出市场规模。",
            "extraction_method": "pdf_direct",
            "value_num": 10.0,
            "company_id": 1,
        }
        value.update(overrides)
        return value

    def test_rejects_legacy_method_for_new_data(self):
        with self.assertRaises(db_writer.DataPointWriteError):
            db_writer.write_data_point(self.conn, **self.item(extraction_method="unknown"), auto_consensus=False)

    def test_rejects_non_finite_and_missing_reference(self):
        with self.assertRaises(db_writer.DataPointWriteError):
            db_writer.write_data_point(self.conn, **self.item(value_num=float("nan")), auto_consensus=False)
        with self.assertRaises(db_writer.DataPointWriteError):
            db_writer.write_data_point(self.conn, **self.item(source_id=99), auto_consensus=False)

    def test_inferred_requires_calculation_note(self):
        with self.assertRaises(db_writer.DataPointWriteError):
            db_writer.write_data_point(self.conn, **self.item(extraction_method="inferred"), auto_consensus=False)

    def test_bulk_write_is_atomic(self):
        with self.assertRaises(db_writer.DataPointWriteError):
            db_writer.bulk_write_data_points(
                self.conn,
                [self.item(metric="有效"), self.item(metric="")],
                auto_consensus=False,
            )
        count = self.conn.execute("SELECT COUNT(*) FROM industry_data_point").fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
