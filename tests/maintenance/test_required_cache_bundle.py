from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from tools.maintenance.build_required_cache_bundle import (
    DATABASES,
    DURABLE_MODEL_DIRECTORIES,
    collect_required_cache,
)


class RequiredCacheBundleTests(unittest.TestCase):
    def test_collects_config_database_and_durable_cache_without_temp_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "config").mkdir()
            config_file = root / "cache" / "configured" / "model.json"
            database_file = root / "cache" / "evidence" / "source.pdf"
            audit_file = root / "cache" / "audit" / "review.json"
            screenshot_file = root / "cache" / "browser_audit" / "page.png"
            temp_file = root / "cache" / "broadcast_validation" / "copy.json"
            for path, content in (
                (config_file, b"config"),
                (database_file, b"database"),
                (audit_file, b"audit"),
                (screenshot_file, b"screenshot"),
                (temp_file, b"temporary"),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            (root / "config" / "models.json").write_text(
                json.dumps({"model": "cache/configured/model.json"}),
                encoding="utf-8",
            )
            for relative in DURABLE_MODEL_DIRECTORIES:
                durable = root / relative / "durable.json"
                durable.parent.mkdir(parents=True, exist_ok=True)
                durable.write_text("{}", encoding="utf-8")
            for relative in DATABASES:
                database = root / relative
                database.parent.mkdir(parents=True, exist_ok=True)
                with closing(sqlite3.connect(database)) as conn:
                    conn.execute(
                        "CREATE TABLE artifact(id INTEGER PRIMARY KEY, file_path TEXT)"
                    )
                    if relative == "data/research.db":
                        conn.execute(
                            "INSERT INTO artifact(file_path) VALUES (?)",
                            ("cache/evidence/source.pdf",),
                        )
                        conn.execute(
                            "CREATE TABLE audit_artifact("
                            "id INTEGER PRIMARY KEY, manifest_json TEXT, screenshot_ref TEXT)"
                        )
                        conn.execute(
                            "INSERT INTO audit_artifact(manifest_json, screenshot_ref) VALUES (?, ?)",
                            (
                                json.dumps(
                                    {
                                        "audit_ref": "cache/audit/review.json",
                                        "screenshot_ref": "cache/browser_audit/page.png",
                                    }
                                ),
                                "cache/browser_audit/page.png",
                            ),
                        )
                    conn.commit()

            paths, manifest = collect_required_cache(root)
            relative_paths = {
                path.relative_to(root).as_posix()
                for path in paths
            }

            self.assertIn("cache/configured/model.json", relative_paths)
            self.assertIn("cache/evidence/source.pdf", relative_paths)
            self.assertIn("cache/audit/review.json", relative_paths)
            self.assertNotIn("cache/browser_audit/page.png", relative_paths)
            self.assertNotIn(
                "cache/broadcast_validation/copy.json",
                relative_paths,
            )
            self.assertEqual(manifest["file_count"], len(relative_paths))
            self.assertGreaterEqual(
                manifest["database_values_scanned"]["data/research.db"],
                1,
            )


if __name__ == "__main__":
    unittest.main()
