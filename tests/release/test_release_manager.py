from __future__ import annotations

import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.release.manager import (
    ReleaseError,
    activate_release,
    build_release,
    inspect_sqlite_contract,
    preflight_release,
    resolve_current_release,
    rollback_release,
    verify_release,
)


class ReleaseManagerTests(unittest.TestCase):
    def _git(self, root: Path, *args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(root), *args], text=True, encoding="utf-8"
        ).strip()

    def _make_repo(self, root: Path) -> tuple[str, str]:
        files = {
            "requirements.lock.txt": "# fixture\n",
            "restart_viewer.bat": "@echo off\r\n",
            "WindPy.py": "# fixture\n",
            "config/research_workflow.yaml": "contract_version: test\n",
            "config/battery_calculator_models/battery_calculator_model_v1.json": "{}\n",
            "config/copper_calculator_models/copper_calculator_model_v1.json": "{}\n",
            "config/lithium_calculator_models/lithium_company_independent_models_v1.json": "{}\n",
            "config/lithium_calculator_models/lithium_external_reconciliation_v1.json": "{}\n",
            "config/lithium_calculator_project_ledger.json": "{}\n",
            "tools/viewer/app.py": "VALUE = 1\n",
            "tools/viewer/templates/base.html": "fixture\n",
            "tools/viewer/static/app.css": "fixture\n",
            "tools/viewer/static/vendor/plotly.min.js": "fixture\n",
            "opportunity_lens/intake_templates/request.md": "fixture\n",
            "docs/governance.md": "not deployable\n",
        }
        policy = {
            "schema_version": "honghu.deployment_policy.v1",
            "include_exact": ["WindPy.py", "requirements.lock.txt", "restart_viewer.bat"],
            "include_prefixes": ["config/", "opportunity_lens/intake_templates/", "tools/"],
            "forbidden_prefixes": ["data/", "papers/", "tools/dynamic/secrets/"],
            "forbidden_suffixes": [".db", ".log"],
            "external_runtime_closure": [
                {
                    "id": "research-content",
                    "authority": "content_root",
                    "path_contracts": [
                        {
                            "path": "docs/industries",
                            "presence": "required",
                            "kind": "directory",
                        },
                        {
                            "path": "papers",
                            "presence": "required",
                            "kind": "directory",
                        },
                        {
                            "path": "docs/themes",
                            "presence": "optional",
                            "kind": "directory",
                        },
                    ],
                }
            ],
        }
        compatibility = {
            "schema_version": "honghu.release_schema_compatibility.v1",
            "backend": "sqlite-transition",
            "forward_only_migrations": [],
            "required_tables": {
                "research.db": ["industry", "source", "company"],
                "sentiment.db": ["senti_raw", "stock_kline", "funda_semi_nodes"],
                "opportunity_lens.db": [
                    "opportunity_run",
                    "opportunity_source",
                    "opportunity_entity",
                ],
                "financial.db": [
                    "financial_security",
                    "financial_observation",
                    "financial_model_run",
                ],
            },
        }
        files["config/deployment_policy.json"] = json.dumps(policy)
        files["config/release_schema_compatibility.json"] = json.dumps(compatibility)
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="")
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        self._git(root, "config", "user.name", "Phase2 Test")
        self._git(root, "config", "user.email", "phase2@example.invalid")
        self._git(root, "add", ".")
        self._git(root, "commit", "-q", "-m", "first")
        first = self._git(root, "rev-parse", "HEAD")
        (root / "tools/viewer/app.py").write_text("VALUE = 2\n", encoding="utf-8")
        self._git(root, "add", "tools/viewer/app.py")
        self._git(root, "commit", "-q", "-m", "second")
        return first, self._git(root, "rev-parse", "HEAD")

    def _make_data(self, root: Path) -> None:
        definitions = {
            "research.db": ["industry", "source", "company"],
            "sentiment.db": ["senti_raw", "stock_kline", "funda_semi_nodes"],
            "opportunity_lens.db": [
                "opportunity_run",
                "opportunity_source",
                "opportunity_entity",
            ],
            "financial.db": [
                "financial_security",
                "financial_observation",
                "financial_model_run",
            ],
        }
        root.mkdir(parents=True)
        for name, tables in definitions.items():
            conn = sqlite3.connect(root / name)
            try:
                for table in tables:
                    conn.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
                conn.commit()
            finally:
                conn.close()

    def test_exact_commit_build_activation_and_code_only_rollback(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repo = base / "repo"
            repo.mkdir()
            first, second = self._make_repo(repo)
            deploy = base / "deploy"
            data = base / "data"
            content = base / "content"
            state = deploy / "runtime"
            self._make_data(data)
            (content / "docs/industries").mkdir(parents=True)
            (content / "papers").mkdir()

            first_manifest = build_release(repo, deploy, commit=first)
            second_manifest = build_release(repo, deploy, commit=second)
            duplicate_manifest = build_release(repo, base / "deploy-copy", commit=second)
            self.assertEqual(first_manifest["commit_sha"], first)
            self.assertEqual(second_manifest["commit_sha"], second)
            self.assertEqual(
                second_manifest["manifest_sha256"], duplicate_manifest["manifest_sha256"]
            )
            self.assertFalse(first_manifest["contains_live_data"])
            self.assertNotIn("docs/governance.md", {x["path"] for x in first_manifest["files"]})

            report = preflight_release(
                deploy / "releases" / first,
                data_root=data,
                content_root=content,
                state_root=state,
            )
            self.assertTrue(report["ok"], report)
            content_contract = report["runtime_closure"]["external_content_contract"]
            self.assertEqual(content_contract["required_missing"], [])
            self.assertEqual(content_contract["optional_missing"], ["docs/themes"])
            schema = inspect_sqlite_contract(data, first_manifest["schema_compatibility"])
            activate_release(deploy, first, actor="test", schema_report=schema)
            activate_release(deploy, second, actor="test", schema_report=schema)
            rollback_release(deploy, actor="test", schema_report=schema)
            current_release, pointer = resolve_current_release(deploy)
            self.assertEqual(pointer["commit_sha"], first)
            self.assertEqual(current_release.name, first)
            ledger = (deploy / "runtime/deployment_ledger.jsonl").read_text(encoding="utf-8")
            self.assertIn("code_only_rollback", ledger)

    def test_preflight_fails_closed_for_required_content_but_not_optional_theme_markdown(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repo = base / "repo"
            repo.mkdir()
            _, commit = self._make_repo(repo)
            deploy = base / "deploy"
            data = base / "data"
            content = base / "content"
            state = deploy / "runtime"
            self._make_data(data)
            (content / "docs/industries").mkdir(parents=True)
            (content / "papers").mkdir()
            build_release(repo, deploy, commit=commit)
            release = deploy / "releases" / commit

            optional_missing = preflight_release(
                release, data_root=data, content_root=content, state_root=state
            )
            self.assertTrue(optional_missing["ok"], optional_missing)
            contract = optional_missing["runtime_closure"]["external_content_contract"]
            self.assertEqual(contract["optional_missing"], ["docs/themes"])

            (content / "papers").rmdir()
            required_missing = preflight_release(
                release, data_root=data, content_root=content, state_root=state
            )
            self.assertFalse(required_missing["ok"])
            contract = required_missing["runtime_closure"]["external_content_contract"]
            self.assertEqual(contract["required_missing"], ["papers"])
            self.assertTrue(
                any("missing required external content path: papers" in item
                    for item in required_missing["failures"])
            )

    def test_release_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repo = base / "repo"
            repo.mkdir()
            _, second = self._make_repo(repo)
            deploy = base / "deploy"
            build_release(repo, deploy, commit=second)
            release = deploy / "releases" / second
            (release / "tools/viewer/app.py").write_text("tampered\n", encoding="utf-8")
            with self.assertRaises(ReleaseError):
                verify_release(release)

    def test_schema_contract_rejects_missing_required_column(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / "data"
            self._make_data(data)
            contract = {
                "schema_version": "honghu.release_schema_compatibility.v1",
                "backend": "sqlite-transition",
                "databases": {
                    "research.db": {
                        "required_objects": {
                            "industry": {
                                "type": "table",
                                "required_columns": ["id", "missing_contract_column"],
                            }
                        },
                        "probe_queries": [
                            {"id": "reader", "sql": "SELECT id FROM industry LIMIT 1"}
                        ],
                    }
                },
            }
            report = inspect_sqlite_contract(data, contract)
            self.assertFalse(report["compatible"])
            self.assertTrue(any("missing_contract_column" in item for item in report["failures"]))


if __name__ == "__main__":
    unittest.main()
