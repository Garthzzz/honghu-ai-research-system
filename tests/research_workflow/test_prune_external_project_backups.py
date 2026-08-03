from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.maintenance.prune_external_project_backups import prune_external_backups


TEST_TEMP_ROOT = Path(__file__).resolve().parents[2] / "cache"


class PruneExternalProjectBackupsTests(unittest.TestCase):
    def _project(self, parent: Path) -> Path:
        root = parent / "industry_demo_fixture"
        latest = root / "backup" / "latest"
        latest.mkdir(parents=True)
        archive = latest / "industry_demo_latest.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("BACKUP_CONTENT_MANIFEST.json", "{}")
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        manifest = {
            "archive": archive.name,
            "archive_size": archive.stat().st_size,
            "archive_sha256": digest,
            "version": "test",
            "databases": [
                {"integrity_check": "ok", "foreign_key_issues": 0}
                for _ in range(4)
            ],
        }
        (latest / "backup_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (latest / "BACKUP_INFO.md").write_text("test", encoding="utf-8")
        return root

    def test_dry_run_and_apply_only_match_project_backup_rollback_or_cleanup_safety_siblings(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temp:
            parent = Path(temp)
            root = self._project(parent)
            old_backup = parent / "industry_demo_fixture_backup_older"
            rollback = parent / "industry_demo_fixture_rollback_safety"
            cleanup_safety = parent / "industry_demo_fixture_cleanup_safety_20260729"
            unrelated = parent / "quant_platform_backup"
            similar = parent / "industry_demo_fixture_notes"
            for path in (old_backup, rollback, cleanup_safety, unrelated, similar):
                path.mkdir()
                (path / "marker.txt").write_text(path.name, encoding="utf-8")

            dry_run = prune_external_backups(root)
            self.assertEqual(dry_run["planned_count"], 3)
            self.assertTrue(old_backup.exists())
            applied = prune_external_backups(root, apply=True)
            self.assertEqual(applied["removed_count"], 3)
            self.assertFalse(old_backup.exists())
            self.assertFalse(rollback.exists())
            self.assertFalse(cleanup_safety.exists())
            self.assertTrue(unrelated.exists())
            self.assertTrue(similar.exists())
            self.assertTrue((root / "backup" / "latest").is_dir())


if __name__ == "__main__":
    unittest.main()
