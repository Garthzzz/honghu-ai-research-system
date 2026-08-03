from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "sentiment"))

import senti_score


class SentiScoreRetryV2Test(unittest.TestCase):
    def setUp(self) -> None:
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.execute(
            "CREATE TABLE senti_raw(id INTEGER PRIMARY KEY,title TEXT,attitude INTEGER,reason TEXT)"
        )
        self.con.executemany(
            "INSERT INTO senti_raw(id,title) VALUES(?,?)",
            [(1, "标题一"), (2, "标题二"), (3, "标题三"), (4, "标题四")],
        )
        self.rows = self.con.execute("SELECT id,title FROM senti_raw ORDER BY id").fetchall()

    def tearDown(self) -> None:
        self.con.close()

    def test_only_invalid_rows_are_retried_with_smaller_batch(self) -> None:
        first = [("看涨", "正向"), (None, None), ("中性", "观望"), (None, None)]
        second = [("看跌", "负向"), ("看涨", "正向")]
        with mock.patch.object(senti_score, "classify_batch", side_effect=[first, second]) as classify:
            labeled, pending, stats = senti_score.classify_rows_with_retries(
                self.con, self.rows, batch_size=4, retry_passes=3
            )

        self.assertEqual(labeled, 4)
        self.assertEqual(pending, [])
        self.assertEqual([call.args[0] for call in classify.call_args_list], [
            ["标题一", "标题二", "标题三", "标题四"],
            ["标题二", "标题四"],
        ])
        self.assertEqual([item["batch"] for item in stats], [4, 2])
        attitudes = [row[0] for row in self.con.execute(
            "SELECT attitude FROM senti_raw ORDER BY id"
        )]
        self.assertEqual(attitudes, [1, 2, 3, 1])

    def test_exhausted_retry_leaves_null_instead_of_fabricating_neutral(self) -> None:
        with mock.patch.object(
            senti_score, "classify_batch", return_value=[(None, None)]
        ):
            labeled, pending, stats = senti_score.classify_rows_with_retries(
                self.con, self.rows[:1], batch_size=14, retry_passes=4
            )

        self.assertEqual(labeled, 0)
        self.assertEqual([row["id"] for row in pending], [1])
        self.assertEqual([item["batch"] for item in stats], [14, 7, 3, 1])
        self.assertIsNone(self.con.execute(
            "SELECT attitude FROM senti_raw WHERE id=1"
        ).fetchone()[0])

    def test_systemic_invalid_output_trips_zero_progress_breaker(self) -> None:
        self.con.executemany(
            "INSERT INTO senti_raw(id,title) VALUES(?,?)",
            [(row_id, f"标题{row_id}") for row_id in range(5, 61)],
        )
        rows = self.con.execute("SELECT id,title FROM senti_raw ORDER BY id").fetchall()
        with mock.patch.object(
            senti_score, "classify_batch", side_effect=lambda batch: [(None, None)] * len(batch)
        ) as classify:
            labeled, pending, stats = senti_score.classify_rows_with_retries(
                self.con, rows, batch_size=14, retry_passes=4
            )

        self.assertEqual(labeled, 0)
        self.assertEqual(len(pending), 60)
        self.assertEqual(classify.call_count, 5)
        self.assertEqual(stats[-1]["halted"], "zero_progress_circuit_breaker")

    def test_call_budget_keeps_unprocessed_rows_pending(self) -> None:
        with mock.patch.object(
            senti_score, "classify_batch", return_value=[(None, None), (None, None)]
        ) as classify:
            labeled, pending, stats = senti_score.classify_rows_with_retries(
                self.con, self.rows, batch_size=2, retry_passes=4, max_calls=1
            )

        self.assertEqual(labeled, 0)
        self.assertEqual([row["id"] for row in pending], [1, 2, 3, 4])
        self.assertEqual(classify.call_count, 1)
        self.assertEqual(stats[-1]["halted"], "call_budget_exhausted")


if __name__ == "__main__":
    unittest.main()
