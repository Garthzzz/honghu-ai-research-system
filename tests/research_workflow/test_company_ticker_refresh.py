from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.pipeline import refresh_company_tickers as tickers


CATALOG = [
    {"ts_code": "000001.SZ", "name": "平安银行", "fullname": "平安银行股份有限公司", "exchange": "SZSE", "board": "主板", "list_status": "L", "list_date": "19910403", "delist_date": None},
    {"ts_code": "688820.SH", "name": "盛合晶微", "fullname": "盛合晶微半导体有限公司", "exchange": "SSE", "board": "科创板", "list_status": "L", "list_date": "20260421", "delist_date": None},
    {"ts_code": "600000.SH", "name": "浦发银行", "fullname": "上海浦东发展银行股份有限公司", "exchange": "SSE", "board": "主板", "list_status": "L", "list_date": "19991110", "delist_date": None},
]


class CompanyTickerRefreshTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "research.db"
        conn = sqlite3.connect(self.db)
        conn.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE company(
              id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, ticker TEXT,
              listing_status TEXT, market TEXT CHECK(market IS NULL OR market IN ('A股','港股','美股','其他'))
            );
            INSERT INTO company VALUES(1,'平安银行',NULL,NULL,NULL);
            INSERT INTO company VALUES(2,'盛合晶微',NULL,'private',NULL);
            INSERT INTO company VALUES(3,'未知公司',NULL,NULL,NULL);
            INSERT INTO company VALUES(4,'历史别名','600000.SH','a_share','A股');
            """
        )
        conn.commit(); conn.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_exact_only_manifest_and_apply(self) -> None:
        manifest = tickers.build_manifest(self.db, CATALOG, generated_at="2026-07-15T04:00:00+00:00")
        self.assertEqual(manifest["summary"]["proposed_updates"], 2)
        by_id = {row["company_id"]: row for row in manifest["companies"]}
        self.assertEqual(by_id[1]["proposed_ticker"], "000001.SZ")
        self.assertEqual(by_id[2]["proposed_ticker"], "688820.SH")
        self.assertEqual(by_id[3]["status"], "unmatched")
        self.assertEqual(by_id[4]["status"], "existing_ticker")
        self.assertEqual(by_id[4]["existing_validation"], "a_share_name_alias_or_mismatch")
        result = tickers.apply_manifest(self.db, manifest)
        self.assertEqual(result["updated"], 2)
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT ticker,listing_status,market FROM company WHERE id=1").fetchone(), ("000001.SZ", "a_share", "A股"))
        self.assertEqual(conn.execute("SELECT ticker,listing_status FROM company WHERE id=2").fetchone(), ("688820.SH", "a_share"))
        self.assertEqual(conn.execute("SELECT ticker FROM company WHERE id=4").fetchone()[0], "600000.SH")
        conn.close()

    def test_stale_manifest_and_tamper_are_rejected(self) -> None:
        manifest = tickers.build_manifest(self.db, CATALOG, generated_at="2026-07-15T04:00:00+00:00")
        manifest["companies"][0]["proposed_ticker"] = "999999.SZ"
        with self.assertRaisesRegex(ValueError, "run_id"):
            tickers.validate_manifest(manifest)
        manifest = tickers.build_manifest(self.db, CATALOG, generated_at="2026-07-15T04:00:00+00:00")
        conn = sqlite3.connect(self.db); conn.execute("UPDATE company SET name='名称变化' WHERE id=3"); conn.commit(); conn.close()
        with self.assertRaisesRegex(RuntimeError, "全集已变化"):
            tickers.apply_manifest(self.db, manifest)


if __name__ == "__main__":
    unittest.main()
