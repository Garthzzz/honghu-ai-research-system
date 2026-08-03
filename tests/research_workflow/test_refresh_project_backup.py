from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path

from tools.maintenance.refresh_project_backup import (
    LIVE_DATABASES,
    _filesystem_path,
    refresh_backup,
)


TEST_TEMP_ROOT = Path(__file__).resolve().parents[2] / "cache"


class RefreshProjectBackupTests(unittest.TestCase):
    def test_windows_filesystem_path_uses_extended_length_prefix(self) -> None:
        path = Path("D:/") / ("长路径" * 100) / "report.pdf"
        converted = str(_filesystem_path(path))
        if __import__("os").name == "nt":
            self.assertTrue(converted.startswith("\\\\?\\"), converted)
        else:
            self.assertEqual(converted, str(path))

    def _project(self, parent: Path) -> Path:
        root = parent / "industry_demo_fixture"
        (root / "data").mkdir(parents=True)
        (root / "tools" / "dynamic" / "secrets").mkdir(parents=True)
        (root / "cache" / "__pycache__").mkdir(parents=True)
        (root / "cache" / "cache_bundle_validation_fixture").mkdir(parents=True)
        (root / "docs").mkdir(parents=True)
        (root / "docs" / "active.md").write_text("活动文档", encoding="utf-8")
        (root / "tools" / "dynamic" / "secrets" / "token.txt").write_text(
            "do-not-copy", encoding="utf-8"
        )
        (root / "cache" / "__pycache__" / "x.pyc").write_bytes(b"generated")
        (root / "cache" / "scheduler.lock").write_bytes(b"1")
        (
            root
            / "cache"
            / "cache_bundle_validation_fixture"
            / "extracted.json"
        ).write_text("temporary", encoding="utf-8")
        for relative in LIVE_DATABASES:
            database = root / relative
            with closing(sqlite3.connect(database)) as conn:
                conn.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT)")
                conn.execute("INSERT INTO sample(value) VALUES ('live')")
                conn.commit()
        (root / "data" / "research.db-wal").write_bytes(b"transient")
        return root

    def test_refresh_creates_one_verified_latest_and_excludes_sensitive_transients(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temp:
            parent = Path(temp)
            root = self._project(parent)
            result = refresh_backup(root, version="测试版一", reason="单元测试")
            latest = root / "backup" / "latest"
            archive_path = latest / "industry_demo_latest.zip"
            self.assertTrue(archive_path.is_file())
            self.assertEqual(result["archive_sha256"], json.loads(
                (latest / "backup_manifest.json").read_text(encoding="utf-8")
            )["archive_sha256"])
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                self.assertIn("docs/active.md", names)
                self.assertIn("data/research.db", names)
                self.assertIn("data/financial.db", names)
                self.assertNotIn("tools/dynamic/secrets/token.txt", names)
                self.assertNotIn("data/research.db-wal", names)
                self.assertNotIn("cache/__pycache__/x.pyc", names)
                self.assertNotIn("cache/scheduler.lock", names)
                self.assertNotIn(
                    "cache/cache_bundle_validation_fixture/extracted.json",
                    names,
                )
                self.assertIsNone(archive.testzip())
            self.assertEqual([path.name for path in (root / "backup").iterdir()], ["latest"])
            self.assertFalse(any(parent.glob("industry_demo_fixture_backup_build_*")))

    def test_second_refresh_atomically_replaces_previous_version(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temp:
            parent = Path(temp)
            root = self._project(parent)
            refresh_backup(root, version="测试版一", reason="第一次")
            (root / "docs" / "active.md").write_text("第二版", encoding="utf-8")
            refresh_backup(root, version="测试版二", reason="第二次")
            latest = root / "backup" / "latest"
            manifest = json.loads((latest / "backup_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["version"], "测试版二")
            self.assertEqual([path.name for path in (root / "backup").iterdir()], ["latest"])
            with zipfile.ZipFile(latest / "industry_demo_latest.zip") as archive:
                self.assertEqual(archive.read("docs/active.md").decode("utf-8"), "第二版")


if __name__ == "__main__":
    unittest.main()
