from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.viewer.preflight import (
    DATABASE_TABLES,
    REQUIRED_PATHS,
    check_active_feature_data,
    check_databases,
    check_required_paths,
    run_preflight,
)
from tools.viewer.lithium_runtime import deployed_inputs, resolve_inputs


class ViewerDeploymentPreflightTests(unittest.TestCase):
    def _make_required_tree(self, root: Path) -> None:
        for relative in REQUIRED_PATHS:
            if relative in DATABASE_TABLES:
                continue
            path = root / relative
            if Path(relative).suffix:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("placeholder", encoding="utf-8")
            else:
                path.mkdir(parents=True, exist_ok=True)

    def _make_databases(self, root: Path) -> None:
        for relative, tables in DATABASE_TABLES.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path)
            for table in tables:
                conn.execute(f'CREATE TABLE "{table}" (id INTEGER)')
            conn.commit()
            conn.close()

    def test_old_five_directory_deployment_reports_missing_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for directory in ("data", "docs", "tools", "papers", "opportunity_lens"):
                (root / directory).mkdir()

            failures = check_required_paths(root)

            self.assertTrue(any("config/research_workflow.yaml" in item for item in failures))

    def test_database_check_is_read_only_and_accepts_required_tables(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._make_databases(root)

            self.assertEqual(check_databases(root), [])

    def test_complete_deployment_reaches_import_check(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._make_required_tree(root)
            self._make_databases(root)

            with patch(
                "tools.viewer.preflight.check_python_modules",
                return_value=[],
            ), patch(
                "tools.viewer.preflight.check_active_feature_data",
                return_value=[],
            ), patch(
                "tools.viewer.preflight.check_viewer_import",
                return_value=[],
            ) as import_check:
                failures = run_preflight(root)

            self.assertEqual(failures, [])
            import_check.assert_called_once_with(root)

    def test_calculator_models_are_required_deployment_inputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._make_required_tree(root)
            model_path = (
                root
                / "config/lithium_calculator_models"
                / "lithium_external_reconciliation_v1.json"
            )
            model_path.unlink()

            failures = check_required_paths(root)

            self.assertTrue(
                any(
                    "config/lithium_calculator_models/"
                    "lithium_external_reconciliation_v1.json" in item
                    for item in failures
                )
            )
            copper_path = (
                root
                / "config/copper_calculator_models"
                / "copper_calculator_model_v1.json"
            )
            copper_path.unlink()

            failures = check_required_paths(root)

            self.assertTrue(
                any(
                    "config/copper_calculator_models/"
                    "copper_calculator_model_v1.json" in item
                    for item in failures
                )
            )
            battery_path = (
                root
                / "config/battery_calculator_models"
                / "battery_calculator_model_v1.json"
            )
            battery_path.unlink()

            failures = check_required_paths(root)

            self.assertTrue(
                any(
                    "config/battery_calculator_models/"
                    "battery_calculator_model_v1.json" in item
                    for item in failures
                )
            )

    def test_active_battery_feature_rejects_mixed_old_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model_path = (
                root
                / "config/battery_calculator_models"
                / "battery_calculator_model_v1.json"
            )
            model_path.parent.mkdir(parents=True)
            model_path.write_text(
                '{"schemaVersion":"battery_calculator.model.v1",'
                '"companies":[{"companyId":1}]}',
                encoding="utf-8",
            )
            database = root / "data/research.db"
            database.parent.mkdir(parents=True)
            conn = sqlite3.connect(database)
            try:
                conn.execute(
                    "CREATE TABLE industry(id INTEGER PRIMARY KEY, name TEXT)"
                )
                conn.execute(
                    "CREATE TABLE industry_data_point("
                    "id INTEGER PRIMARY KEY, industry_id INTEGER)"
                )
                conn.execute(
                    "CREATE TABLE company_industry("
                    "company_id INTEGER, industry_id INTEGER)"
                )
                conn.commit()
            finally:
                conn.close()

            failures = check_active_feature_data(root)

            self.assertTrue(
                any("缺少锂电池行业记录" in item for item in failures)
            )

    def test_calculator_prefers_deployed_models_and_supports_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            deployed = deployed_inputs(root)
            deployed.project_ledger.parent.mkdir(parents=True, exist_ok=True)
            deployed.project_ledger.write_text("{}", encoding="utf-8")
            legacy_dir = root / "cache/lithium_research/models"
            legacy_dir.mkdir(parents=True)
            for name in (
                "lithium_company_independent_models_v1.json",
                "lithium_external_reconciliation_v1.json",
            ):
                (legacy_dir / name).write_text("{}", encoding="utf-8")

            legacy = resolve_inputs(root)
            self.assertTrue(legacy.used_legacy_cache)

            deployed.independent_model.parent.mkdir(parents=True)
            deployed.independent_model.write_text("{}", encoding="utf-8")
            deployed.reconciliation.write_text("{}", encoding="utf-8")

            primary = resolve_inputs(root)
            self.assertFalse(primary.used_legacy_cache)
            self.assertEqual(primary.independent_model, deployed.independent_model)

    def test_restart_script_uses_windows_line_endings(self):
        script = Path(__file__).resolve().parents[2] / "restart_viewer.bat"
        payload = script.read_bytes()

        self.assertIn(b"\r\n", payload)
        self.assertNotIn(b"\n", payload.replace(b"\r\n", b""))
        text = payload.decode("utf-8")
        self.assertIn("tools.viewer.app:app", text)
        self.assertIn("config\\research_workflow.yaml", text)
        self.assertNotIn("^| ConvertFrom-Json", text)


if __name__ == "__main__":
    unittest.main()
