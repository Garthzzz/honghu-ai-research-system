from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.financial.accounting_sanity import (
    normalize_nonmeaningful_annual_roe,
)
from tools.financial.db import initialize_database
from tools.financial.opportunity_profile_export import (
    EXPORT_SCHEMA_VERSION,
    import_export,
    validate_export,
)
from tools.financial.read_models import company_bundle


class OpportunityProfileExportTests(unittest.TestCase):
    def test_validate_rejects_source_channel_not_supported_by_repository(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifact = root / "source.json"
            artifact.write_text('{"source":"research"}\n', encoding="utf-8")
            artifact_hash = "sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()
            payload = {
                "export_schema_version": EXPORT_SCHEMA_VERSION,
                "research_run_ref": "test:invalid-source-channel",
                "as_of_date": "2026-07-30",
                "source_artifacts": [{"path": str(artifact), "sha256": artifact_hash}],
                "companies": [{
                    "research_company_id": 99,
                    "security": {"canonical_name": "Test Company", "ticker": "000099.SZ"},
                    "source_snapshots": [{
                        "key": "research",
                        "provider": "internal_research",
                        "source_channel": "research_pack",
                        "source_ref": "research:test",
                        "title": "Research pack",
                    }],
                    "model_runs": [],
                    "observations": [],
                }],
            }
            with self.assertRaisesRegex(ValueError, "source_channel"):
                validate_export(payload, export_path=root / "export.json")

    def test_validate_rejects_internal_numeric_observation_without_formula(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifact = root / "source.json"
            artifact.write_text('{"source":"model"}\n', encoding="utf-8")
            artifact_hash = "sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()
            payload = {
                "export_schema_version": EXPORT_SCHEMA_VERSION,
                "research_run_ref": "test:internal-observation-formula",
                "as_of_date": "2026-07-30",
                "source_artifacts": [{"path": str(artifact), "sha256": artifact_hash}],
                "companies": [{
                    "research_company_id": 99,
                    "security": {"canonical_name": "Test Company", "ticker": "000099.SZ"},
                    "source_snapshots": [{
                        "key": "model",
                        "provider": "internal_model",
                        "source_channel": "internal_calculation",
                        "source_ref": "model:test",
                        "title": "Frozen model",
                    }],
                    "model_runs": [],
                    "observations": [{
                        "metric_name": "revenue",
                        "value_num": 100.0,
                        "unit": "CNY 100m",
                        "fact_type": "internal_estimate",
                        "as_of_date": "2026-07-30",
                        "provider": "internal_model",
                        "quality_status": "usable",
                        "source_snapshot_key": "model",
                    }],
                }],
            }
            with self.assertRaisesRegex(ValueError, "内部模型观察值必须保存公式"):
                validate_export(payload, export_path=root / "export.json")

    def test_reviewed_model_cannot_register_independent_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifact = root / "source.json"
            artifact.write_text('{"source":"market"}\n', encoding="utf-8")
            artifact_hash = "sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()
            payload = {
                "export_schema_version": EXPORT_SCHEMA_VERSION,
                "research_run_ref": "test:reviewed-reconciliation",
                "as_of_date": "2026-07-30",
                "source_artifacts": [{"path": str(artifact), "sha256": artifact_hash}],
                "companies": [{
                    "research_company_id": 99,
                    "security": {"canonical_name": "测试公司", "ticker": "000099.SZ"},
                    "source_snapshots": [],
                    "model_runs": [{
                        "run_key": "test:reviewed-with-reconciliation",
                        "skill_name": "company_valuation_modeling",
                        "model_name": "市场诊断",
                        "model_role": "diagnostic",
                        "finalization": "reviewed",
                        "inputs": [{"input_name": "市值"}],
                        "outputs": [{"output_name": "隐含利润"}],
                        "reconciliations": [{
                            "benchmark_source_ref": "market:test",
                        }],
                    }],
                    "observations": [],
                }],
            }
            with self.assertRaisesRegex(ValueError, "reviewed"):
                validate_export(payload, export_path=root / "export.json")

    def test_export_rejects_usable_roe_when_equity_denominator_is_nonpositive(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifact = root / "source.json"
            artifact.write_text('{"source":"wind"}\n', encoding="utf-8")
            artifact_hash = (
                "sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()
            )
            export_path = root / "export.json"
            observations = [
                {
                    "metric_name": "total_equity",
                    "value_num": -6.89,
                    "unit": "亿元人民币",
                    "fiscal_year": 2021,
                    "fiscal_period": "FY",
                    "frequency": "annual",
                    "fact_type": "actual",
                    "period_end": "2021-12-31",
                    "as_of_date": "2021-12-31",
                    "provider": "wind",
                    "raw_feature_name": "Wind WSS.tot_equity",
                    "quality_status": "usable",
                },
                {
                    "metric_name": "roe",
                    "value_num": -7777.1309,
                    "unit": "%",
                    "fiscal_year": 2021,
                    "fiscal_period": "FY",
                    "frequency": "annual",
                    "fact_type": "actual",
                    "period_end": "2021-12-31",
                    "as_of_date": "2021-12-31",
                    "provider": "wind",
                    "raw_feature_name": "Wind WSS.roe",
                    "quality_status": "usable",
                },
            ]
            payload = {
                "export_schema_version": EXPORT_SCHEMA_VERSION,
                "research_run_ref": "test:roe-sanity",
                "as_of_date": "2021-12-31",
                "source_artifacts": [
                    {"path": str(artifact), "sha256": artifact_hash}
                ],
                "companies": [{
                    "research_company_id": 99,
                    "security": {
                        "canonical_name": "测试公司",
                        "ticker": "000099.SZ",
                        "market": "A股",
                    },
                    "source_snapshots": [],
                    "model_runs": [],
                    "observations": observations,
                }],
            }
            with self.assertRaisesRegex(ValueError, "必须标记 not_applicable"):
                validate_export(payload, export_path=export_path)

            payload["companies"][0]["observations"] = (
                normalize_nonmeaningful_annual_roe(observations)
            )
            validated = validate_export(payload, export_path=export_path)
            self.assertEqual(validated["company_count"], 1)

    def test_export_imports_reviewed_valuation_and_keeps_all_implied_periods(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifact = root / "model.json"
            artifact.write_text('{"frozen":true}\n', encoding="utf-8")
            artifact_hash = "sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()
            export_path = root / "export.json"
            db_path = root / "financial.db"
            initialize_database(db_path)
            payload = {
                "export_schema_version": EXPORT_SCHEMA_VERSION,
                "research_run_ref": "opportunity_lens:test:1",
                "as_of_date": "2026-07-23",
                "source_artifacts": [{"path": str(artifact), "sha256": artifact_hash}],
                "companies": [{
                    "research_company_id": 99,
                    "security": {
                        "canonical_name": "测试公司",
                        "ticker": "000099.SZ",
                        "market": "A股",
                        "listing_status": "a_share",
                        "reporting_currency": "CNY",
                    },
                    "source_snapshots": [{
                        "key": "model",
                        "provider": "internal_model",
                        "source_channel": "internal_calculation",
                        "source_ref": "model:test",
                        "title": "测试冻结模型",
                        "as_of_date": "2026-07-23",
                        "content_hash": artifact_hash,
                    }],
                    "model_runs": [{
                        "run_key": "test:reverse-pe",
                        "skill_name": "company_valuation_modeling",
                        "model_name": "反向市盈率诊断",
                        "model_role": "diagnostic",
                        "valuation_date": "2026-07-23",
                        "finalization": "reviewed",
                        "inputs": [{
                            "input_name": "当前市值",
                            "value_num": 200,
                            "unit": "亿元人民币",
                            "period_or_as_of_date": "2026-07-23",
                            "source_ref": artifact_hash + "#market_cap",
                            "input_type": "external_consensus",
                            "formula_or_method": "估值日市场快照",
                        }],
                        "outputs": [{
                            "output_name": "FY1市盈率",
                            "value_num": 20,
                            "unit": "倍",
                            "period_or_as_of_date": "2027",
                            "formula": "市值÷归母净利润",
                            "substitution": "200÷10＝20",
                            "dependency_group": "reverse_pe",
                            "conclusion": "诊断当前价格要求。",
                        }],
                    }],
                    "observations": [
                        {
                            "metric_name": "pe_forward",
                            "value_num": 20,
                            "unit": "倍",
                            "fiscal_year": 2027,
                            "fiscal_period": "FY1",
                            "frequency": "annual",
                            "fact_type": "implied",
                            "as_of_date": "2026-07-23",
                            "provider": "internal_model",
                            "raw_feature_name": "当前市值对应的独立预测市盈率",
                            "formula": "市值÷归母净利润",
                            "quality_status": "usable",
                            "scenario_name": "独立盈利路径",
                            "source_snapshot_key": "model",
                            "model_run_key": "test:reverse-pe",
                        },
                        {
                            "metric_name": "pe_forward",
                            "value_num": 16,
                            "unit": "倍",
                            "fiscal_year": 2028,
                            "fiscal_period": "FY2",
                            "frequency": "annual",
                            "fact_type": "implied",
                            "as_of_date": "2026-07-23",
                            "provider": "internal_model",
                            "raw_feature_name": "当前市值对应的独立预测市盈率",
                            "formula": "市值÷归母净利润",
                            "quality_status": "usable",
                            "scenario_name": "独立盈利路径",
                            "source_snapshot_key": "model",
                            "model_run_key": "test:reverse-pe",
                        },
                    ],
                }],
            }
            export_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )

            validation = validate_export(payload, export_path=export_path)
            self.assertEqual(validation["model_run_count"], 1)
            summary = import_export(payload, export_path=export_path, db_path=db_path)
            self.assertEqual(summary["models_inserted"], 1)
            self.assertEqual(summary["observations_inserted"], 2)

            bundle = company_bundle(99, db_path=db_path)
            self.assertIsNotNone(bundle)
            assert bundle is not None
            self.assertEqual(len(bundle["valuation_model_runs"]), 1)
            self.assertEqual(bundle["valuation_model_runs"][0]["status"], "reviewed")
            self.assertEqual(
                bundle["valuation_model_runs"][0]["inputs"][0]["source_label"],
                "市场或一致预期快照",
            )
            self.assertEqual(
                [row["period"] for row in bundle["implied_expectations"]],
                ["2027（FY1）", "2028（FY2）"],
            )

            replacement = json.loads(json.dumps(payload, ensure_ascii=False))
            next_model = replacement["companies"][0]["model_runs"][0]
            next_model["run_key"] = "test:reverse-pe:v2"
            next_model["supersedes_run_keys"] = ["test:reverse-pe"]
            for observation in replacement["companies"][0]["observations"]:
                observation["model_run_key"] = "test:reverse-pe:v2"
            export_path.write_text(
                json.dumps(replacement, ensure_ascii=False),
                encoding="utf-8",
            )
            replacement_summary = import_export(
                replacement,
                export_path=export_path,
                db_path=db_path,
            )
            self.assertEqual(replacement_summary["models_inserted"], 1)
            self.assertEqual(replacement_summary["models_superseded"], 1)
            refreshed = company_bundle(99, db_path=db_path)
            assert refreshed is not None
            self.assertEqual(
                [row["run_key"] for row in refreshed["valuation_model_runs"]],
                ["test:reverse-pe:v2"],
            )


if __name__ == "__main__":
    unittest.main()
