from __future__ import annotations

import sqlite3
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "sentiment"))

import migrate_retail_windows_v2 as migration
import register_new_stocks


SENTI_DDL = """
CREATE TABLE senti_company (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  ticker TEXT
);
CREATE TABLE company_alias (
  id INTEGER PRIMARY KEY,
  company_id INTEGER NOT NULL,
  ticker TEXT NOT NULL,
  alias TEXT NOT NULL,
  alias_type TEXT,
  UNIQUE(company_id,alias)
);
CREATE TABLE senti_raw (
  id INTEGER PRIMARY KEY,
  bucket_id TEXT NOT NULL,
  company_id INTEGER NOT NULL,
  ticker TEXT NOT NULL,
  source_layer TEXT NOT NULL,
  platform TEXT NOT NULL,
  attitude INTEGER,
  attitude_src TEXT,
  dedup_key TEXT NOT NULL,
  post_id TEXT,
  title TEXT,
  url TEXT,
  author TEXT,
  author_uid TEXT,
  heat_value INTEGER,
  sampled INTEGER,
  publish_time TEXT,
  reason TEXT,
  as_of TEXT,
  fetched_at TEXT,
  backfilled INTEGER DEFAULT 0,
  UNIQUE(company_id,source_layer,dedup_key)
);
"""


class IdentityMigrationTests(unittest.TestCase):
    def setUp(self):
        self.senti = sqlite3.connect(":memory:")
        self.senti.row_factory = sqlite3.Row
        self.senti.execute("PRAGMA foreign_keys=ON")
        self.senti.executescript(SENTI_DDL)
        self.research = sqlite3.connect(":memory:")
        self.research.row_factory = sqlite3.Row
        self.research.execute(
            "CREATE TABLE company(id INTEGER PRIMARY KEY,name TEXT NOT NULL,ticker TEXT)"
        )
        self.research.execute(
            "INSERT INTO company(id,name,ticker) VALUES(?,?,?)", (100, "测试公司", "000100.SZ")
        )
        self.redirect = (migration.IdentityRedirect(900001, 100, "测试公司"),)
        self.verified = (
            migration.VerifiedSentiCompany(900001, "测试公司", "000100.SZ"),
        )
        self.senti.execute(
            "INSERT INTO senti_company(id,name,ticker) VALUES(?,?,NULL)", (900001, "测试公司")
        )
        self.senti.execute(
            "INSERT INTO company_alias(company_id,ticker,alias,alias_type) VALUES(?,?,?,?)",
            (900001, "测试公司", "测试公司", "name"),
        )

    def tearDown(self):
        self.research.close()
        self.senti.close()

    def add_raw(self, row_id, company_id, dedup_key, attitude, heat, title):
        self.senti.execute(
            """INSERT INTO senti_raw(
                 id,bucket_id,company_id,ticker,source_layer,platform,attitude,attitude_src,
                 dedup_key,post_id,title,heat_value,sampled,publish_time,fetched_at,backfilled)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row_id,
                "2026-07-20T09:30",
                company_id,
                "OLD" if company_id == 900001 else "000100.SZ",
                "retail",
                "guba",
                attitude,
                "test",
                dedup_key,
                dedup_key,
                title,
                heat,
                1,
                "2026-07-20T10:00:00+08:00",
                "2026-07-20T10:05:00+08:00",
                0,
            ),
        )

    def test_collision_merge_alias_sync_and_idempotence(self):
        self.add_raw(1, 900001, "same", 1, 10, "旧行有标签")
        self.add_raw(10, 100, "same", None, 3, "")
        self.add_raw(2, 900001, "old-only", 2, 5, "仅旧身份")
        result = migration.apply_migration(
            self.senti,
            self.research,
            redirects=self.redirect,
            verified_companies=self.verified,
            rebuild_legacy=False,
        )
        self.assertEqual(result["raw"], {"moved": 1, "deduplicated": 1, "remapped": 2})
        rows = self.senti.execute("SELECT * FROM senti_raw ORDER BY id").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["company_id"] == 100 for row in rows))
        merged = self.senti.execute("SELECT * FROM senti_raw WHERE dedup_key='same'").fetchone()
        self.assertEqual(merged["attitude"], 1)
        self.assertEqual(merged["heat_value"], 10)
        self.assertEqual(merged["ticker"], "000100.SZ")
        aliases = {
            (row["alias"], row["ticker"], row["alias_type"])
            for row in self.senti.execute("SELECT * FROM company_alias WHERE company_id=100")
        }
        self.assertEqual(
            aliases,
            {
                ("测试公司", "000100.SZ", "name"),
                ("000100.SZ", "000100.SZ", "ticker"),
                ("000100", "000100.SZ", "code"),
            },
        )
        self.assertEqual(
            self.senti.execute("SELECT COUNT(*) FROM senti_company WHERE id=900001").fetchone()[0], 0
        )
        self.assertEqual(
            self.senti.execute("SELECT COUNT(*) FROM senti_raw_window").fetchone()[0], 2
        )
        # 重跑不复制、不丢行。
        migration.apply_migration(
            self.senti,
            self.research,
            redirects=self.redirect,
            verified_companies=self.verified,
            rebuild_legacy=False,
        )
        self.assertEqual(self.senti.execute("SELECT COUNT(*) FROM senti_raw").fetchone()[0], 2)
        self.assertFalse(self.senti.execute("PRAGMA foreign_key_check").fetchall())

    def test_name_mismatch_aborts(self):
        self.senti.execute("UPDATE senti_company SET name='错误公司' WHERE id=900001")
        with self.assertRaises(ValueError):
            migration.apply_migration(
                self.senti,
                self.research,
                redirects=self.redirect,
                verified_companies=self.verified,
                rebuild_legacy=False,
            )

    def test_provider_ss_suffix_is_normalized_to_research_canonical_in_all_company_tables(self):
        self.research.execute(
            "INSERT INTO company(id,name,ticker) VALUES(?,?,?)", (200, "上交所公司", "603228.SH")
        )
        self.senti.execute(
            "INSERT INTO senti_company(id,name,ticker) VALUES(?,?,?)",
            (200, "上交所公司", "603228.SS"),
        )
        self.senti.execute(
            "INSERT INTO senti_raw(id,bucket_id,company_id,ticker,source_layer,platform,"
            "dedup_key,fetched_at) VALUES(?,?,?,?,?,?,?,?)",
            (20, "2026-07-15T09:30", 200, "603228.SS", "retail", "guba", "ss-row", "now"),
        )
        self.senti.execute(
            "INSERT INTO company_alias(company_id,ticker,alias,alias_type) VALUES(?,?,?,?)",
            (200, "603228.SS", "603228.SS", "legacy_ticker"),
        )
        research_companies = migration._research_company_map(self.research)
        changed = migration.sync_canonical_research_tickers(self.senti, research_companies)
        self.assertEqual(changed, {"company_alias": 1, "senti_company": 1, "senti_raw": 1})
        self.assertEqual(
            self.senti.execute("SELECT ticker FROM senti_company WHERE id=200").fetchone()[0],
            "603228.SH",
        )
        self.assertEqual(
            self.senti.execute("SELECT ticker FROM senti_raw WHERE company_id=200").fetchone()[0],
            "603228.SH",
        )
        self.assertEqual(
            self.senti.execute("SELECT ticker FROM company_alias WHERE company_id=200").fetchone()[0],
            "603228.SH",
        )
        self.assertEqual(
            migration.sync_canonical_research_tickers(self.senti, research_companies), {}
        )

    def test_production_redirect_set_is_exact(self):
        pairs = {(item.old_company_id, item.canonical_company_id) for item in migration.IDENTITY_REDIRECTS}
        self.assertEqual(
            pairs,
            {
                (900001, 557), (900003, 555), (900004, 392), (900015, 448),
                (900017, 556), (900018, 535), (900019, 388), (900024, 532),
                (900025, 583), (900031, 520),
            },
        )
        verified = migration.VERIFIED_SENTI_COMPANIES
        self.assertEqual(len(verified), 31)
        self.assertEqual({item.company_id for item in verified}, set(range(900001, 900032)))
        self.assertTrue(all(item.ticker and item.ticker != item.name for item in verified))
        self.assertEqual(
            {item.company_id: item.ticker for item in verified}[900015], "688820.SH"
        )


class RegistrationRegressionTests(unittest.TestCase):
    def test_verified_registration_never_recreates_redirects_or_name_ticker(self):
        con = sqlite3.connect(":memory:")
        con.executescript(
            """
            CREATE TABLE senti_company(
              id INTEGER PRIMARY KEY,name TEXT UNIQUE,ticker TEXT,industry TEXT,created_at TEXT,note TEXT
            );
            CREATE TABLE company_alias(
              id INTEGER PRIMARY KEY,company_id INTEGER,ticker TEXT NOT NULL,
              alias TEXT,alias_type TEXT,UNIQUE(company_id,alias)
            );
            CREATE TABLE company_id_redirect(
              old_company_id INTEGER PRIMARY KEY,canonical_company_id INTEGER
            );
            """
        )
        con.executemany(
            "INSERT INTO company_id_redirect VALUES(?,?)",
            [(item.old_company_id, item.canonical_company_id) for item in migration.IDENTITY_REDIRECTS],
        )
        names = [item.name for item in migration.VERIFIED_SENTI_COMPANIES]
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache"
            cache.mkdir()
            (cache / "_t1_universe.json").write_text(
                json.dumps({"new_outside": names}, ensure_ascii=False), encoding="utf-8"
            )
            with mock.patch.object(register_new_stocks, "ROOT", Path(tmp)):
                register_new_stocks.register_stocks(con, "2026-07-15T12:00:00+08:00")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM senti_company").fetchone()[0], 21)
        self.assertEqual(
            con.execute(
                "SELECT COUNT(*) FROM senti_company WHERE ticker IS NULL OR TRIM(ticker)='' OR ticker=name"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            con.execute(
                "SELECT COUNT(*) FROM senti_company WHERE id IN "
                "(SELECT old_company_id FROM company_id_redirect)"
            ).fetchone()[0],
            0,
        )
        con.close()


if __name__ == "__main__":
    unittest.main()
