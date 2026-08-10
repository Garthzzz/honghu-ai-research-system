from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from tools.maintenance.apply_project_cleanup import execute_cleanup
from tools.maintenance.project_artifacts import (
    FEATURE_RETIREMENT_AUTHORIZATION,
    FEATURE_RETIREMENT_SCHEMA_VERSION,
    build_inventory,
    initial_classification,
    normalize_feature_retirement_spec,
    _io_path,
    _should_scan_references,
)


class ProjectCleanupTests(unittest.TestCase):
    @staticmethod
    def _retirement_spec(paths: list[str], *, batch: str = "retire_obsolete_panel") -> dict:
        return {
            "schema_version": FEATURE_RETIREMENT_SCHEMA_VERSION,
            "authorization": FEATURE_RETIREMENT_AUTHORIZATION,
            "batch": batch,
            "reason": "用户明确要求退役已完成业务切换的旧功能",
            "paths": paths,
        }

    @staticmethod
    def _write_file(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_generated_bytecode_is_deletable_inside_protected_source_tree(self):
        classification, batch, *_ = initial_classification("tools/viewer/__pycache__/app.pyc")
        self.assertEqual(classification, "delete_redundant")
        self.assertEqual(batch, "generated_temp")

    def test_only_live_database_sidecars_are_protected(self):
        codegraph_class, codegraph_batch, *_ = initial_classification(".codegraph/codegraph.db-wal")
        live_class, *_ = initial_classification("data/research.db-wal")
        self.assertEqual((codegraph_class, codegraph_batch), ("delete_redundant", "generated_temp"))
        self.assertEqual(live_class, "keep_live")

    def test_verified_funda_mirror_is_classified_as_duplicate(self):
        classification, batch, *_ = initial_classification("1/docs/reports/example.pdf")
        self.assertEqual((classification, batch), ("delete_redundant", "duplicate_mirror"))

    def test_cache_validation_databases_and_browser_images_are_candidates(self):
        db_class, db_batch, *_ = initial_classification("cache/rehearsal/temp.db")
        image_class, image_batch, *_ = initial_classification(
            "cache/opportunity_lens/browser_audit/run_1/full_page.png"
        )
        source_class, *_ = initial_classification(
            "cache/opportunity_lens/source_documents/official_notice.pdf"
        )
        self.assertEqual((db_class, db_batch), ("delete_redundant", "validation_databases"))
        self.assertEqual((image_class, image_batch), ("delete_redundant", "generated_visual"))
        self.assertEqual(source_class, "pending_review")

    def test_deployment_extract_copies_are_regenerable_candidates(self):
        classification, batch, _, recovery, _ = initial_classification(
            "cache/cache_bundle_validation_20260729/industry_demo/cache/model.json"
        )
        self.assertEqual(
            (classification, batch, recovery),
            ("delete_redundant", "deployment_validation", "regenerate"),
        )
        installed_class, installed_batch, _, installed_recovery, _ = (
            initial_classification(
                "cache/installer_e2e_20260729/industry_demo/data/research.db"
            )
        )
        self.assertEqual(
            (installed_class, installed_batch, installed_recovery),
            ("delete_redundant", "deployment_validation", "regenerate"),
        )
        self.assertFalse(
            _should_scan_references(
                "cache/broadcast_validation/extract/manifest.json",
                classification="delete_redundant",
                batch="deployment_validation",
                size=128,
            )
        )

    def test_scoped_inventory_only_reads_explicit_regenerable_prefix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            backup = base / "backup"
            disposable = root / "cache" / "installer_lock_simulation" / "payload.bin"
            durable = root / "cache" / "opportunity_lens" / "run_pack.json"
            disposable.parent.mkdir(parents=True)
            durable.parent.mkdir(parents=True)
            backup.mkdir()
            disposable.write_bytes(b"disposable")
            durable.write_text('{"durable": true}', encoding="utf-8")

            payload = build_inventory(
                root,
                backup_path=backup,
                include_prefixes=["cache/installer_lock_simulation"],
            )

            self.assertEqual(
                [record["path"] for record in payload["records"]],
                ["cache/installer_lock_simulation/payload.bin"],
            )
            self.assertEqual(
                payload["scope"]["include_prefixes"],
                ["cache/installer_lock_simulation"],
            )
            self.assertEqual(payload["reference_scan"]["text_files_scanned"], 0)
            self.assertTrue(durable.is_file())

    def test_scoped_inventory_rejects_glob_missing_and_secrets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            backup = base / "backup"
            root.mkdir()
            backup.mkdir()
            for value, expected in (
                ("cache/*", "glob"),
                ("cache/missing", "does not exist"),
                ("tools/dynamic/secrets", "must not select"),
            ):
                with self.subTest(value=value):
                    with self.assertRaisesRegex((ValueError, FileNotFoundError), expected):
                        build_inventory(
                            root,
                            backup_path=backup,
                            include_prefixes=[value],
                        )

    @unittest.skipUnless(os.name == "nt", "Windows extended-length path regression")
    def test_scoped_cleanup_supports_windows_extended_length_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            backup = base / "backup"
            target = (
                root
                / "cache"
                / "broadcast_validation"
                / ("a" * 100)
                / ("b" * 100)
                / "payload.bin"
            )
            backup.mkdir()
            _io_path(target).parent.mkdir(parents=True)
            _io_path(target).write_bytes(b"long-path")
            self.assertGreater(len(str(target.resolve())), 260)

            inventory = build_inventory(
                root,
                backup_path=backup,
                include_prefixes=["cache/broadcast_validation"],
            )
            self.assertEqual(len(inventory["records"]), 1)
            self.assertEqual(inventory["records"][0]["size"], len(b"long-path"))
            manifest = root / "inventory.json"
            manifest.write_text(json.dumps(inventory), encoding="utf-8")

            applied = execute_cleanup(
                manifest,
                batches={"deployment_validation"},
                apply=True,
            )
            self.assertEqual(applied["completed_count"], 1)
            self.assertFalse(_io_path(target).exists())

    def test_browser_audit_json_is_retained_and_rotated_viewer_log_is_generated(self):
        audit_class, *_ = initial_classification("cache/browser_old/browser_visual_audit.json")
        log_class, log_batch, *_ = initial_classification(
            "cache/viewer.log.20260720_211621.bak"
        )
        self.assertEqual(audit_class, "pending_review")
        self.assertEqual((log_class, log_batch), ("delete_redundant", "generated_temp"))

    def test_retirement_audits_are_moved_to_central_history(self):
        classification, batch, _, _, target = initial_classification(
            "cache/retire_example_manifest.json"
        )
        self.assertEqual((classification, batch), ("retain_verbatim_history", "historical_reference"))
        self.assertEqual(
            target,
            "archive/project_history/cleanup_manifests/retirements_20260721/retire_example_manifest.json",
        )

    def test_live_opportunity_manifest_protects_referenced_browser_image(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            backup = base / "backup"
            image = root / "cache" / "browser_audit" / "full_page.png"
            db = root / "data" / "opportunity_lens.db"
            image.parent.mkdir(parents=True)
            db.parent.mkdir(parents=True)
            backup.mkdir()
            image.write_bytes(b"image")
            import sqlite3
            con = sqlite3.connect(db)
            con.execute(
                "CREATE TABLE opportunity_run_manifest(id INTEGER PRIMARY KEY,manifest_json TEXT)"
            )
            con.execute(
                "INSERT INTO opportunity_run_manifest(manifest_json) VALUES(?)",
                (json.dumps({"screenshots": ["cache/browser_audit/full_page.png"]}),),
            )
            con.commit()
            con.close()

            payload = build_inventory(root, backup_path=backup)
            record = next(
                item for item in payload["records"]
                if item["path"] == "cache/browser_audit/full_page.png"
            )
            self.assertEqual(record["classification"], "keep_live")
            self.assertIn("live_database_file_reference", record["protected_reasons"])

    def test_duplicate_readme_is_not_demoted_by_generic_basename_reference(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            backup = base / "backup"
            duplicate = root / "1" / "docs" / "fundaskills" / "README.md"
            reference = root / "AGENTS.md"
            duplicate.parent.mkdir(parents=True)
            backup.mkdir()
            duplicate.write_text("duplicate", encoding="utf-8")
            reference.write_text("README.md", encoding="utf-8")

            payload = build_inventory(root, backup_path=backup)
            record = next(item for item in payload["records"] if item["path"] == "1/docs/fundaskills/README.md")

            self.assertEqual(record["classification"], "delete_redundant")
            self.assertEqual(record["batch"], "duplicate_mirror")

    def test_explicit_internal_backup_is_not_demoted_by_live_basename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            backup = base / "backup"
            old_copy = root / "backup_before_company_profile_20260601_012322" / "pipeline" / "db_writer.py"
            live_copy = root / "tools" / "pipeline" / "db_writer.py"
            old_copy.parent.mkdir(parents=True)
            live_copy.parent.mkdir(parents=True)
            backup.mkdir()
            old_copy.write_text("old", encoding="utf-8")
            live_copy.write_text("db_writer.py", encoding="utf-8")

            payload = build_inventory(root, backup_path=backup)
            record = next(item for item in payload["records"] if item["path"] == old_copy.relative_to(root).as_posix())

            self.assertEqual(record["classification"], "delete_redundant")
            self.assertEqual(record["batch"], "internal_backup")

    def test_explicit_historical_cache_is_not_demoted_by_run_pack_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            backup = base / "backup"
            old_pack = root / "cache" / "removed_opportunity_lens_runs_20260704" / "run_pack.json"
            live_text = root / "AGENTS.md"
            old_pack.parent.mkdir(parents=True)
            backup.mkdir()
            old_pack.write_text("old", encoding="utf-8")
            live_text.write_text("run_pack.json", encoding="utf-8")

            payload = build_inventory(root, backup_path=backup)
            record = next(item for item in payload["records"] if item["path"] == old_pack.relative_to(root).as_posix())

            self.assertEqual(record["classification"], "delete_redundant")
            self.assertEqual(record["batch"], "historical_cache")

    def test_inventory_does_not_hash_or_read_secret_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            backup = base / "backup"
            secret = root / "tools" / "dynamic" / "secrets" / "token.txt"
            secret.parent.mkdir(parents=True)
            backup.mkdir()
            secret.write_text("DO_NOT_EXPOSE_UNIQUE_SECRET", encoding="utf-8")

            payload = build_inventory(root, backup_path=backup)
            record = next(item for item in payload["records"] if item["path"].endswith("token.txt"))

            self.assertEqual(record["classification"], "keep_live")
            self.assertIsNone(record["sha256"])
            self.assertNotIn("DO_NOT_EXPOSE_UNIQUE_SECRET", json.dumps(payload, ensure_ascii=False))
            self.assertEqual(
                payload["reference_scan"]["secret_content_excluded"],
                "tools/dynamic/secrets/",
            )

    def test_cleanup_defaults_to_dry_run_then_applies_regenerable_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            backup = base / "backup"
            target = root / "cache" / "item.tmp"
            target.parent.mkdir(parents=True)
            backup.mkdir()
            target.write_text("temporary", encoding="utf-8")
            inventory = build_inventory(root, backup_path=backup)
            target_record = next(
                record for record in inventory["records"] if record["path"] == "cache/item.tmp"
            )
            self.assertNotIn("retirement_spec_hash", target_record)
            self.assertNotIn("retirement_peer_references", target_record)
            self.assertNotIn("feature_retirement", inventory)
            manifest = root / "inventory.json"
            manifest.write_text(json.dumps(inventory), encoding="utf-8")

            dry_run = execute_cleanup(manifest, batches={"generated_temp"})
            self.assertEqual(dry_run["planned_count"], 1)
            self.assertEqual(dry_run["completed_count"], 0)
            self.assertTrue(target.exists())

            applied = execute_cleanup(manifest, batches={"generated_temp"}, apply=True)
            self.assertEqual(applied["completed_count"], 1)
            self.assertFalse(target.exists())

    def test_cleanup_rejects_hash_drift(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            backup = base / "backup"
            target = root / "cache" / "item.tmp"
            target.parent.mkdir(parents=True)
            backup.mkdir()
            target.write_text("before", encoding="utf-8")
            inventory = build_inventory(root, backup_path=backup)
            manifest = root / "inventory.json"
            manifest.write_text(json.dumps(inventory), encoding="utf-8")
            target.write_text("after", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "SHA256"):
                execute_cleanup(manifest, batches={"generated_temp"}, apply=True)

    def test_cleanup_rejects_protected_path_even_if_manifest_is_tampered(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            backup = base / "backup"
            target = root / "AGENTS.md"
            root.mkdir()
            backup.mkdir()
            target.write_text("active", encoding="utf-8")
            inventory = build_inventory(root, backup_path=backup)
            record = next(item for item in inventory["records"] if item["path"] == "AGENTS.md")
            record.update(
                {"classification": "delete_redundant", "batch": "tampered", "recovery": "regenerate"}
            )
            manifest = root / "inventory.json"
            manifest.write_text(json.dumps(inventory), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "保护路径"):
                execute_cleanup(manifest, batches={"tampered"}, apply=True)
            self.assertTrue(target.exists())

    def test_cleanup_rejects_history_destination_outside_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            backup = base / "backup"
            target = root / "old.md"
            root.mkdir()
            backup.mkdir()
            target.write_text("history", encoding="utf-8")
            inventory = build_inventory(root, backup_path=backup)
            record = next(item for item in inventory["records"] if item["path"] == "old.md")
            record.update(
                {
                    "classification": "retain_verbatim_history",
                    "batch": "history",
                    "target_path": str(base / "escape.md"),
                    "recovery": "regenerate",
                }
            )
            manifest = root / "inventory.json"
            manifest.write_text(json.dumps(inventory), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "archive/project_history"):
                execute_cleanup(manifest, batches={"history"}, apply=True)
            self.assertTrue(target.exists())

    def test_feature_retirement_requires_exact_spec_backup_and_second_authorization(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            backup = base / "backup"
            backup.mkdir()
            page_name = "key" + "word.html"
            detail_name = "key" + "word_detail.html"
            job_name = "key" + "word_aggregate.py"
            contents = {
                f"tools/viewer/templates/{page_name}": f"retired detail: {detail_name}",
                f"tools/viewer/templates/{detail_name}": "retired detail",
                f"tools/sentiment/{job_name}": "print('retired')",
            }
            for rel, content in contents.items():
                self._write_file(root / rel, content)
                self._write_file(backup / rel, content)

            spec = self._retirement_spec(list(contents), batch="retire_keyword_sentiment")
            inventory = build_inventory(root, backup_path=backup, feature_retirement=spec)
            records = [
                record
                for record in inventory["records"]
                if record["classification"] == "retire_feature"
            ]
            self.assertEqual({record["path"] for record in records}, set(contents))
            self.assertTrue(all(record["batch"] == "retire_keyword_sentiment" for record in records))
            self.assertTrue(all(record["retirement_spec_hash"] for record in records))
            detail_record = next(
                record
                for record in records
                if record["path"].endswith(detail_name)
            )
            self.assertEqual(
                detail_record["retirement_peer_references"],
                [f"tools/viewer/templates/{page_name}"],
            )
            manifest = root / "inventory.json"
            manifest.write_text(json.dumps(inventory), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "authorize-feature-retirement"):
                execute_cleanup(manifest, batches={"retire_keyword_sentiment"})

            dry_run = execute_cleanup(
                manifest,
                batches={"retire_keyword_sentiment"},
                authorized_retirement_batches={"retire_keyword_sentiment"},
            )
            self.assertEqual(dry_run["planned_count"], 3)
            self.assertEqual(dry_run["completed_count"], 0)
            self.assertTrue(all((root / rel).is_file() for rel in contents))

            applied = execute_cleanup(
                manifest,
                batches={"retire_keyword_sentiment"},
                authorized_retirement_batches={"retire_keyword_sentiment"},
                apply=True,
            )
            self.assertEqual(applied["completed_count"], 3)
            self.assertEqual(
                applied["authorized_feature_retirement_batches"],
                ["retire_keyword_sentiment"],
            )
            self.assertTrue(all(not (root / rel).exists() for rel in contents))
            self.assertTrue((root / "tools" / "viewer" / "templates").is_dir())
            self.assertTrue(all((backup / rel).is_file() for rel in contents))

    def test_feature_retirement_rejects_glob_directory_database_secret_and_maintenance(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "project"
            root.mkdir()
            self._write_file(root / "data" / "retired.sqlite-wal", "not a database")
            self._write_file(root / "tools" / "dynamic" / "secrets" / "token.txt", "secret")
            self._write_file(root / "tools" / "maintenance" / "retired_helper.py", "pass")
            (root / "tools" / "viewer" / "templates").mkdir(parents=True)

            invalid_cases = {
                "glob": ["tools/viewer/templates/*.html"],
                "目录": ["tools/viewer/templates"],
                "SQLite": ["data/retired.sqlite-wal"],
                "secrets": ["tools/dynamic/secrets/token.txt"],
                "maintenance": ["tools/maintenance/retired_helper.py"],
                "POSIX": [r"tools\viewer\templates\retired.html"],
            }
            for expected, paths in invalid_cases.items():
                with self.subTest(paths=paths):
                    with self.assertRaisesRegex((ValueError, FileNotFoundError), expected):
                        normalize_feature_retirement_spec(
                            self._retirement_spec(paths),
                            root=root,
                        )

    def test_feature_retirement_rescans_and_rejects_new_active_reference(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            backup = base / "backup"
            backup.mkdir()
            rel = "tools/viewer/templates/retired_panel.html"
            self._write_file(root / rel, "retired")
            self._write_file(backup / rel, "retired")
            inventory = build_inventory(
                root,
                backup_path=backup,
                feature_retirement=self._retirement_spec([rel]),
            )
            manifest = root / "inventory.json"
            manifest.write_text(json.dumps(inventory), encoding="utf-8")
            self._write_file(
                root / "tools" / "viewer" / "app.py",
                'render_template("retired_panel.html")',
            )

            with self.assertRaisesRegex(ValueError, "当前活动文本"):
                execute_cleanup(
                    manifest,
                    batches={"retire_obsolete_panel"},
                    authorized_retirement_batches={"retire_obsolete_panel"},
                )
            self.assertTrue((root / rel).is_file())

    def test_feature_retirement_rejects_same_size_wrong_backup_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            backup = base / "backup"
            backup.mkdir()
            rel = "tools/sentiment/retired_panel_job.py"
            self._write_file(root / rel, "alpha")
            self._write_file(backup / rel, "omega")
            inventory = build_inventory(
                root,
                backup_path=backup,
                feature_retirement=self._retirement_spec([rel]),
            )
            manifest = root / "inventory.json"
            manifest.write_text(json.dumps(inventory), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "备份 SHA256"):
                execute_cleanup(
                    manifest,
                    batches={"retire_obsolete_panel"},
                    authorized_retirement_batches={"retire_obsolete_panel"},
                )
            self.assertTrue((root / rel).is_file())

    def test_feature_retirement_ignores_ambiguous_bare_workflow_basename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            backup = base / "backup"
            backup.mkdir()
            rel = "tools/legacy/manifest.json"
            self._write_file(root / rel, "{}")
            self._write_file(backup / rel, "{}")
            self._write_file(root / "AGENTS.md", "manifest.json")

            inventory = build_inventory(
                root,
                backup_path=backup,
                feature_retirement=self._retirement_spec([rel]),
            )
            record = next(item for item in inventory["records"] if item["path"] == rel)

            self.assertEqual(record["classification"], "retire_feature")
            self.assertEqual(record["retirement_peer_references"], [])

    def test_feature_retirement_still_rejects_exact_workflow_artifact_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            backup = base / "backup"
            backup.mkdir()
            rel = "tools/legacy/manifest.json"
            self._write_file(root / rel, "{}")
            self._write_file(backup / rel, "{}")
            self._write_file(root / "AGENTS.md", rel)

            inventory = build_inventory(
                root,
                backup_path=backup,
                feature_retirement=self._retirement_spec([rel]),
            )
            record = next(item for item in inventory["records"] if item["path"] == rel)
            self.assertEqual(record["active_references"], ["AGENTS.md"])
            manifest = root / "inventory.json"
            manifest.write_text(json.dumps(inventory), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "仍被活动文本引用"):
                execute_cleanup(
                    manifest,
                    batches={"retire_obsolete_panel"},
                    authorized_retirement_batches={"retire_obsolete_panel"},
                )

    def test_feature_retirement_rejects_tampered_spec_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            backup = base / "backup"
            backup.mkdir()
            rel = "tools/sentiment/retired_panel_job.py"
            self._write_file(root / rel, "retired")
            self._write_file(backup / rel, "retired")
            inventory = build_inventory(
                root,
                backup_path=backup,
                feature_retirement=self._retirement_spec([rel]),
            )
            inventory["feature_retirement"]["reason"] = "这是被篡改后的未授权退役理由"
            manifest = root / "inventory.json"
            manifest.write_text(json.dumps(inventory), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "spec hash"):
                execute_cleanup(
                    manifest,
                    batches={"retire_obsolete_panel"},
                    authorized_retirement_batches={"retire_obsolete_panel"},
                )
            self.assertTrue((root / rel).is_file())


if __name__ == "__main__":
    unittest.main()
