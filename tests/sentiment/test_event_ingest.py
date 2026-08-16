from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SENTIMENT_DIR = ROOT / "tools" / "sentiment"
if str(SENTIMENT_DIR) not in sys.path:
    sys.path.insert(0, str(SENTIMENT_DIR))

import event_ingest
import recruit_weekly


class EventIngestTests(unittest.TestCase):
    def make_connection(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute(
            """CREATE TABLE event_item(
                 id INTEGER PRIMARY KEY,
                 title TEXT NOT NULL,
                 published_at TEXT,
                 fetched_at TEXT,
                 materiality TEXT,
                 sentiment TEXT,
                 summary_ai TEXT,
                 ai_tagged_by TEXT,
                 ai_tier INTEGER
               )"""
        )
        return con

    def test_fetch_failure_is_distinct_from_valid_empty_response(self):
        with mock.patch.object(event_ingest, "_post", return_value=None):
            self.assertIsNone(event_ingest.fetch_announcements("000001", "x", "szse"))
        with mock.patch.object(event_ingest, "_post", return_value={"announcements": []}):
            self.assertEqual(event_ingest.fetch_announcements("000001", "x", "szse"), [])

    def test_weekend_main_is_silent_and_never_opens_database_or_network(self):
        with mock.patch.object(event_ingest.quiet_hours, "is_weekend", return_value=True), \
             mock.patch.object(event_ingest.common, "get_senti_db") as db, \
             mock.patch.object(event_ingest, "_post") as post, \
             mock.patch("builtins.print") as output:
            self.assertEqual(event_ingest.main(), 0)
        db.assert_not_called()
        post.assert_not_called()
        output.assert_not_called()

    def test_weekend_recruit_task_is_silent_and_never_starts_children(self):
        weekend = mock.Mock()
        weekend.weekday.return_value = 6
        clock = mock.Mock()
        clock.now.return_value = weekend
        with mock.patch.object(recruit_weekly, "datetime", clock), \
             mock.patch.object(recruit_weekly.subprocess, "run") as child, \
             mock.patch("builtins.print") as output:
            self.assertEqual(recruit_weekly.main(), 0)
        child.assert_not_called()
        output.assert_not_called()

    def test_recruit_child_failure_is_propagated_and_stops_classification(self):
        weekday = mock.Mock()
        weekday.weekday.return_value = 0
        weekday.isocalendar.return_value = (2026, 34, 1)
        clock = mock.Mock()
        clock.now.return_value = weekday
        with mock.patch.object(recruit_weekly, "datetime", clock), \
             mock.patch.object(recruit_weekly, "run", return_value=False) as child, \
             mock.patch("tools.data_platform.run_domain_operation.install_operation_context"):
            self.assertEqual(recruit_weekly.main(), 2)
        child.assert_called_once_with("recruit_scrape.py")

    def test_pending_scores_are_recovered_newest_first_and_audited(self):
        con = self.make_connection()
        con.executemany(
            """INSERT INTO event_item(id,title,published_at,fetched_at)
               VALUES(?,?,?,?)""",
            [
                (1, "older", "2026-07-19T10:00:00+08:00", "2026-07-19T10:01:00+08:00"),
                (2, "newer", "2026-07-20T10:00:00+08:00", "2026-07-20T10:01:00+08:00"),
            ],
        )
        fake_client = mock.Mock()
        fake_client.enabled.return_value = True
        with mock.patch.object(event_ingest, "llm_client", fake_client), mock.patch.object(
            event_ingest,
            "judge",
            return_value=("高", "正面", "测试摘要"),
        ) as judge:
            result = event_ingest.score_pending(con, 1)
        self.assertEqual(result, {
            "pending_before": 2,
            "attempted": 1,
            "judged": 1,
            "pending_after": 1,
        })
        judge.assert_called_once_with("newer")
        row = con.execute("SELECT * FROM event_item WHERE id=2").fetchone()
        self.assertEqual((row["materiality"], row["sentiment"]), ("高", "正面"))
        self.assertEqual(row["ai_tagged_by"], "deepseek")
        con.close()


if __name__ == "__main__":
    unittest.main()
