from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.maintenance.validate_sqlite_migration import compare_databases


class MigrationValidatorTests(unittest.TestCase):
    def test_rejects_business_row_change_and_accepts_explicit_metadata_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            before = Path(tmp) / "before.db"
            after = Path(tmp) / "after.db"
            for path in (before, after):
                conn = sqlite3.connect(path)
                conn.executescript(
                    """
                    PRAGMA foreign_keys=ON;
                    CREATE TABLE business(id INTEGER PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    INSERT INTO business(value) VALUES('stable');
                    INSERT INTO schema_meta VALUES('version', 'v1');
                    """
                )
                conn.commit()
                conn.close()

            conn = sqlite3.connect(after)
            conn.execute("INSERT INTO schema_meta VALUES('workflow', 'v2')")
            conn.commit()
            conn.close()
            accepted = compare_databases(before, after, allowed_row_count_changes={"schema_meta"})
            self.assertTrue(accepted["passed"])

            conn = sqlite3.connect(after)
            conn.execute("INSERT INTO business(value) VALUES('unexpected')")
            conn.commit()
            conn.close()
            rejected = compare_databases(before, after, allowed_row_count_changes={"schema_meta"})
            self.assertFalse(rejected["passed"])
            self.assertEqual(rejected["unexpected_row_count_changes"][0]["table"], "business")


if __name__ == "__main__":
    unittest.main()
