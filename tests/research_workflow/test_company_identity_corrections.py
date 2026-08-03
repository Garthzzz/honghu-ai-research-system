from __future__ import annotations

import importlib
import sqlite3
import tempfile
import unittest
from pathlib import Path


migration = importlib.import_module("tools.migrations.014_company_identity_status_corrections")


class CompanyIdentityCorrectionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "research.db"
        conn = sqlite3.connect(self.db)
        conn.executescript(
            """
            CREATE TABLE company(
              id INTEGER PRIMARY KEY,name TEXT,ticker TEXT,listing_status TEXT,
              market TEXT,display_mode TEXT
            );
            INSERT INTO company VALUES(262,'双鸿','3324.TW','other_listed',NULL,'quantitative');
            INSERT INTO company VALUES(598,'新光电气','6967.T','listed','其他','quantitative');
            """
        )
        conn.commit(); conn.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_apply_is_exact_and_idempotent(self) -> None:
        conn = sqlite3.connect(self.db); conn.row_factory = sqlite3.Row
        self.assertEqual(migration.apply(conn), 2)
        migration.verify(conn)
        self.assertEqual(migration.apply(conn), 0)
        self.assertEqual(
            tuple(conn.execute("SELECT ticker,listing_status FROM company WHERE id=262").fetchone()),
            ("3324.TWO", "other_listed"),
        )
        self.assertEqual(
            tuple(conn.execute("SELECT ticker,listing_status,display_mode FROM company WHERE id=598").fetchone()),
            ("6967.T", "delisted", "qualitative_only"),
        )
        conn.close()

    def test_precondition_mismatch_aborts(self) -> None:
        conn = sqlite3.connect(self.db); conn.row_factory = sqlite3.Row
        conn.execute("UPDATE company SET ticker='WRONG' WHERE id=262")
        with self.assertRaisesRegex(RuntimeError, "拒绝覆盖"):
            migration.apply(conn)
        conn.close()


if __name__ == "__main__":
    unittest.main()
