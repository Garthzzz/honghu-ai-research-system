from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "sentiment"))

import migrate_retire_hbm_topic as migration


TOPIC_DDL = """
CREATE TABLE topic_meta (
  topic_id TEXT PRIMARY KEY, name TEXT, industry_id INTEGER, as_of TEXT,
  p25_q TEXT, p50_q TEXT, p75_q TEXT, narrative_md TEXT, params_status TEXT
);
CREATE TABLE topic_path (
  topic_id TEXT, quarter TEXT, q_idx INTEGER, p_event_by_T REAL, mean_value REAL,
  src_ref TEXT, PRIMARY KEY(topic_id, quarter)
);
CREATE TABLE topic_scenario (
  topic_id TEXT, scenario TEXT, description TEXT, p25 REAL, p50 REAL, p75 REAL,
  peak_value REAL, src_ref TEXT, PRIMARY KEY(topic_id, scenario)
);
CREATE TABLE topic_tornado (
  topic_id TEXT, factor_label TEXT, base REAL, high REAL, low REAL,
  total_range REAL, src_ref TEXT, PRIMARY KEY(topic_id, factor_label)
);
CREATE TABLE topic_fact (
  id INTEGER PRIMARY KEY, topic_id TEXT, grp TEXT, key TEXT, entity TEXT,
  period TEXT, value_num REAL, value_text TEXT, unit TEXT, src_ref TEXT, as_of TEXT
);
CREATE TABLE unrelated_data(id INTEGER PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO unrelated_data VALUES(1, 'must-survive');
INSERT INTO topic_meta(topic_id,name) VALUES('hbm-inflection','HBM/存储 供给拐点');
INSERT INTO topic_fact(id,topic_id,key) VALUES
  (1,'hbm-inflection','fact-1'),(2,'hbm-inflection','fact-2');
INSERT INTO topic_scenario(topic_id,scenario) VALUES('hbm-inflection','Base');
INSERT INTO topic_tornado(topic_id,factor_label) VALUES('hbm-inflection','yield');
INSERT INTO topic_path(topic_id,quarter) VALUES('hbm-inflection','2026Q3');
"""


class RetireHbmTopicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "sentiment.db"
        con = sqlite3.connect(self.db)
        con.executescript(TOPIC_DDL)
        con.commit()
        con.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _objects(self) -> set[str]:
        con = sqlite3.connect(self.db)
        try:
            return {
                row[0]
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        finally:
            con.close()

    def test_default_dry_run_reports_without_writing(self) -> None:
        before = self.db.read_bytes()
        report = migration.retire(self.db)

        self.assertEqual(report["mode"], "dry_run")
        self.assertEqual(set(report["objects_present"]), set(migration.TABLES))
        self.assertEqual(report["rows_to_delete_total"], 6)
        self.assertEqual(before, self.db.read_bytes())
        self.assertTrue(set(migration.TABLES).issubset(self._objects()))

    def test_apply_drops_only_allowlisted_tables_and_is_idempotent(self) -> None:
        report = migration.retire(self.db, apply=True)

        self.assertEqual(report["mode"], "apply")
        self.assertEqual(report["rows_deleted_total"], 6)
        self.assertEqual(report["remaining"], {})
        self.assertEqual(report["foreign_key_issues"], 0)
        self.assertEqual(report["integrity_check"], "ok")
        self.assertTrue(set(migration.TABLES).isdisjoint(self._objects()))

        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(
                con.execute("SELECT value FROM unrelated_data WHERE id=1").fetchone()[0],
                "must-survive",
            )
        finally:
            con.close()

        second = migration.retire(self.db, apply=True)
        self.assertEqual(second["rows_deleted_total"], 0)
        self.assertEqual(second["integrity_check"], "ok")

    def test_unexpected_object_type_fails_closed(self) -> None:
        con = sqlite3.connect(self.db)
        con.execute("DROP TABLE topic_fact")
        con.execute("CREATE VIEW topic_fact AS SELECT 1 AS id")
        con.commit()
        con.close()

        with self.assertRaisesRegex(RuntimeError, "对象类型异常"):
            migration.retire(self.db, apply=True)

        # 类型预检失败发生在事务删除之前，其余四张专题表必须仍在。
        objects = self._objects()
        self.assertTrue(set(migration.TABLES[1:]).issubset(objects))
        self.assertIn("unrelated_data", objects)

    def test_canonical_schema_no_longer_creates_topic_tables(self) -> None:
        schema = (ROOT / "tools" / "sentiment" / "schema_sentiment.sql").read_text(
            encoding="utf-8"
        )
        fresh = Path(self.tmp.name) / "fresh.db"
        con = sqlite3.connect(fresh)
        try:
            con.executescript(schema)
            objects = {
                row[0]
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
                )
            }
            self.assertTrue(set(migration.TABLES).isdisjoint(objects))
            self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
