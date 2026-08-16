from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import nullcontext
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "sentiment"))

import retail_windows_v2
import retail_window_tick
import senti3


RAW_DDL = """
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
  title TEXT,
  heat_value INTEGER,
  sampled INTEGER,
  publish_time TEXT,
  fetched_at TEXT,
  UNIQUE(company_id,source_layer,dedup_key)
);
"""


class RetailDataLayerTests(unittest.TestCase):
    def test_weekend_tick_is_silent_before_lock_database_or_child_process(self):
        weekend = mock.Mock()
        weekend.weekday.return_value = 5
        clock = mock.Mock()
        clock.now.return_value = weekend
        with mock.patch.object(retail_window_tick, "datetime", clock), \
             mock.patch.object(retail_window_tick, "exclusive_tick_lock") as lock, \
             mock.patch.object(retail_window_tick.common, "get_senti_db") as db, \
             mock.patch.object(retail_window_tick, "run_child") as child, \
             mock.patch("builtins.print") as output:
            self.assertEqual(retail_window_tick.main([]), 0)
        lock.assert_not_called()
        db.assert_not_called()
        child.assert_not_called()
        output.assert_not_called()

    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys=ON")
        self.con.executescript(RAW_DDL)
        retail_windows_v2.ensure_schema(self.con)

    def tearDown(self):
        self.con.close()

    def insert_raw(self, row_id, company_id, layer, platform, attitude, publish_time, heat=1):
        self.con.execute(
            """INSERT INTO senti_raw(
                 id,bucket_id,company_id,ticker,source_layer,platform,attitude,attitude_src,
                 dedup_key,title,heat_value,sampled,publish_time,fetched_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row_id,
                publish_time[:16],
                company_id,
                f"{company_id:06d}.SZ",
                layer,
                platform,
                attitude,
                "test",
                f"key-{row_id}",
                f"title-{row_id}",
                heat,
                1,
                publish_time,
                publish_time,
            ),
        )

    def test_orphaned_running_window_is_recovered_and_aggregated(self):
        window = senti3.market_window(date(2026, 7, 15), "morning")
        retail_windows_v2.ensure_window(self.con, window)
        retail_windows_v2.mark_window_status(self.con, window.window_id, "running")
        self.insert_raw(1, 10, "retail", "guba", 1, "2026-07-15T10:00:00+08:00")
        retail_windows_v2.map_retail_raw_rows(self.con)
        retail_window_tick._source_status(self.con, window.window_id, "guba", "running")
        self.con.commit()

        recovered = retail_window_tick.recover_stale_windows(self.con)

        self.assertEqual(recovered[0]["window_id"], window.window_id)
        ledger = self.con.execute(
            "SELECT status,raw_count,scored_count FROM retail_window_ledger WHERE window_id=?",
            (window.window_id,),
        ).fetchone()
        self.assertEqual(tuple(ledger), ("partial", 1, 1))
        source = self.con.execute(
            "SELECT status,error_code FROM retail_window_source_run WHERE window_id=? AND source='guba'",
            (window.window_id,),
        ).fetchone()
        self.assertEqual(source["status"], "failed")
        self.assertIn("stale_running_recovered", source["error_code"])
        self.assertEqual(
            self.con.execute(
                "SELECT COUNT(*) FROM senti_retail_window WHERE window_id=?",
                (window.window_id,),
            ).fetchone()[0],
            1,
        )
        retail_windows_v2.mark_window_status(self.con, window.window_id, "running")
        rerun = self.con.execute(
            "SELECT status,finished_at FROM retail_window_ledger WHERE window_id=?",
            (window.window_id,),
        ).fetchone()
        self.assertEqual(rerun["status"], "running")
        self.assertIsNone(rerun["finished_at"])

    def test_fresh_xinghan_checkpoint_delays_stale_recovery(self):
        window = senti3.market_window(date(2026, 7, 16), "morning")
        retail_windows_v2.ensure_window(self.con, window)
        retail_windows_v2.mark_window_status(self.con, window.window_id, "running")
        retail_window_tick._source_status(
            self.con, window.window_id, "xinghan", "running"
        )
        now = datetime.now(senti3.TZ)
        begin, end = window.segments[0]
        self.con.execute(
            """INSERT INTO yuqing_fetch_segment_run(
                 window_id,subject_id,request_variant,segment_start,segment_end,status,
                 snapshot_timestamp_ms,pages_committed,records_seen,error_code,
                 started_at,finished_at,updated_at)
               VALUES(?,?,?,?,?,'running',1,2,360,NULL,?,NULL,?)""",
            (
                window.window_id, "", "all",
                begin.isoformat(timespec="seconds"), end.isoformat(timespec="seconds"),
                now.isoformat(timespec="seconds"), now.isoformat(timespec="seconds"),
            ),
        )
        self.con.commit()

        fresh = retail_window_tick.fresh_orphaned_xinghan_windows(
            self.con, now=now
        )
        self.assertEqual(fresh, [window.window_id])

        old = (now - timedelta(minutes=11)).isoformat(timespec="seconds")
        self.con.execute(
            "UPDATE yuqing_fetch_segment_run SET updated_at=? WHERE window_id=?",
            (old, window.window_id),
        )
        self.con.commit()
        self.assertEqual(
            retail_window_tick.fresh_orphaned_xinghan_windows(self.con, now=now), []
        )
        retail_window_tick.recover_stale_windows(self.con)
        segment = self.con.execute(
            "SELECT status,error_code FROM yuqing_fetch_segment_run WHERE window_id=?",
            (window.window_id,),
        ).fetchone()
        self.assertEqual(segment["status"], "partial")
        self.assertIn("stale_running_recovered", segment["error_code"])

    def test_auto_backfill_only_scans_due_live_v2_gaps_after_cutover(self):
        legacy = senti3.market_window(date(2026, 7, 14), "preopen")
        retail_windows_v2.ensure_window(self.con, legacy)
        expected = []
        for slot in senti3.MARKET_WINDOW_SLOTS:
            window = senti3.market_window(date(2026, 7, 15), slot)
            retail_windows_v2.ensure_window(self.con, window)
            if slot == "morning":
                retail_windows_v2.mark_window_status(self.con, window.window_id, "complete")
                retail_window_tick._source_status(
                    self.con, window.window_id, "guba", "empty"
                )
                retail_window_tick._source_status(
                    self.con, window.window_id, "xinghan", "empty"
                )
                retail_window_tick._source_status(
                    self.con, window.window_id, "score", "complete"
                )
                retail_window_tick._source_status(
                    self.con, window.window_id, "kline", "complete"
                )
                retail_window_tick._source_status(
                    self.con, window.window_id, "guba", "empty"
                )
            else:
                retail_windows_v2.mark_window_status(self.con, window.window_id, "partial")
                expected.append(window.window_id)
        today = senti3.market_window(date(2026, 7, 16), "preopen")
        retail_windows_v2.ensure_window(self.con, today)

        due = retail_window_tick.due_auto_backfill_windows(
            self.con,
            now=datetime.fromisoformat("2026-07-16T11:00:00+08:00"),
            exclude_window_ids={today.window_id},
            start_date=date(2026, 7, 15),
            max_days=7,
            limit=3,
        )

        self.assertEqual([window.window_id for window in due], expected)
        self.assertNotIn(legacy.window_id, [window.window_id for window in due])

    def test_auto_backfill_cannot_reopen_three_day_finalized_or_expired_window(self):
        expired = senti3.market_window(date(2026, 7, 15), "preopen")
        finalized = senti3.market_window(date(2026, 7, 17), "preopen")
        retail_windows_v2.ensure_window(self.con, expired)
        retail_windows_v2.ensure_window(self.con, finalized)
        retail_windows_v2.mark_window_status(self.con, expired.window_id, "partial")
        retail_windows_v2.mark_window_status(self.con, finalized.window_id, "partial")
        self.con.execute(
            """UPDATE retail_window_ledger
               SET retention_state='purged_incomplete'
               WHERE window_id=?""",
            (finalized.window_id,),
        )
        self.con.commit()

        due = retail_window_tick.due_auto_backfill_windows(
            self.con,
            now=datetime.fromisoformat("2026-07-20T11:00:00+08:00"),
            start_date=date(2026, 7, 15),
            max_days=7,
            limit=10,
        )

        ids = [window.window_id for window in due]
        self.assertNotIn(expired.window_id, ids)
        self.assertNotIn(finalized.window_id, ids)

    def test_new_empty_guba_window_is_partial_until_second_success(self):
        window = senti3.market_window(date(2026, 7, 20), "morning")
        retail_windows_v2.ensure_window(self.con, window)
        for source, status in (
            ("xinghan", "empty"),
            ("score", "complete"),
            ("kline", "complete"),
        ):
            retail_window_tick._source_status(self.con, window.window_id, source, status)

        retail_window_tick._source_status(
            self.con,
            window.window_id,
            "guba",
            "failed",
            retail_window_tick.ChildResult("guba", 1, "", "blocked"),
        )
        self.assertEqual(
            retail_window_tick._empty_recheck_attempts(
                self.con, window.window_id, "guba"
            ),
            0,
        )
        retail_window_tick._source_status(self.con, window.window_id, "guba", "empty")
        first = retail_window_tick.reconcile_window(self.con, window.window_id)
        probe = self.con.execute(
            """SELECT status,records_seen,error_code FROM retail_window_source_run
               WHERE window_id=? AND source=?""",
            (
                window.window_id,
                retail_window_tick._empty_recheck_source("guba"),
            ),
        ).fetchone()
        self.assertEqual(first["status"], "partial")
        self.assertEqual((probe["status"], probe["records_seen"]), ("partial", 1))
        self.assertIn("empty_recheck_pending:1/2", probe["error_code"])

        retail_window_tick._source_status(self.con, window.window_id, "guba", "empty")
        second = retail_window_tick.reconcile_window(self.con, window.window_id)
        probe = self.con.execute(
            """SELECT status,records_seen,error_code FROM retail_window_source_run
               WHERE window_id=? AND source=?""",
            (
                window.window_id,
                retail_window_tick._empty_recheck_source("guba"),
            ),
        ).fetchone()
        self.assertEqual(second["status"], "complete")
        self.assertEqual((probe["status"], probe["records_seen"]), ("complete", 2))
        self.assertIn("legitimate_empty_confirmed:2/2", probe["error_code"])

    def test_legacy_complete_zero_row_window_is_rechecked_once_then_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "sentiment.db"
            seed = sqlite3.connect(db_path)
            seed.row_factory = sqlite3.Row
            seed.execute("PRAGMA foreign_keys=ON")
            seed.executescript(RAW_DDL)
            retail_windows_v2.ensure_schema(seed)
            window = senti3.market_window(date(2026, 7, 20), "morning")
            retail_windows_v2.ensure_window(seed, window)
            # Simulate a pre-fix row: the window and guba source both claimed
            # success while no raw/company row existed and no probe was stored.
            for source, status in (
                ("guba", "empty"),
                ("xinghan", "empty"),
                ("score", "complete"),
                ("kline", "complete"),
            ):
                seed.execute(
                    """INSERT INTO retail_window_source_run(
                         window_id,source,status,records_seen,inserted)
                       VALUES(?,?,?,?,0)""",
                    (window.window_id, source, status, 0),
                )
            retail_windows_v2.mark_window_status(seed, window.window_id, "complete")
            seed.commit()

            excluded = {
                senti3.market_window(date(2026, 7, 20), "preopen").window_id
            }
            due_before = retail_window_tick.due_auto_backfill_windows(
                seed,
                now=datetime.fromisoformat("2026-07-20T15:00:00+08:00"),
                exclude_window_ids=excluded,
                start_date=date(2026, 7, 20),
                max_days=1,
                limit=3,
            )
            self.assertEqual([item.window_id for item in due_before], [window.window_id])
            seed.close()

            def connect(**_kwargs):
                con = sqlite3.connect(db_path)
                con.row_factory = sqlite3.Row
                con.execute("PRAGMA foreign_keys=ON")
                return con

            executed = []

            def fake_child(command):
                executed.append(command.source)
                return retail_window_tick.ChildResult(command.source, 0, "ok", "")

            with mock.patch.object(
                retail_window_tick.common, "get_senti_db", side_effect=connect
            ), mock.patch.object(
                retail_window_tick.common, "assert_senti_only"
            ), mock.patch.object(
                retail_window_tick, "run_child", side_effect=fake_child
            ):
                code, result = retail_window_tick.execute_window(
                    window, guba_pages=1, score_max=0
                )
                second_code, second_result = retail_window_tick.execute_window(
                    window, guba_pages=1, score_max=0
                )

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "complete")
            self.assertEqual(executed, ["guba"])
            self.assertEqual(second_code, 0)
            self.assertEqual(second_result["skipped"], "idempotent")

            check = connect()
            probe = check.execute(
                """SELECT status,records_seen FROM retail_window_source_run
                   WHERE window_id=? AND source=?""",
                (
                    window.window_id,
                    retail_window_tick._empty_recheck_source("guba"),
                ),
            ).fetchone()
            due_after = retail_window_tick.due_auto_backfill_windows(
                check,
                now=datetime.fromisoformat("2026-07-20T15:00:00+08:00"),
                exclude_window_ids=excluded,
                start_date=date(2026, 7, 20),
                max_days=1,
                limit=3,
            )
            check.close()
            self.assertEqual((probe["status"], probe["records_seen"]), ("complete", 2))
            self.assertEqual(due_after, [])

            # A confirmed legal empty stays closed, while an impossible
            # raw/company aggregate mismatch is still selected for repair.
            mismatch = connect()
            mismatch.execute(
                "UPDATE retail_window_ledger SET raw_count=1 WHERE window_id=?",
                (window.window_id,),
            )
            due_mismatch = retail_window_tick.due_auto_backfill_windows(
                mismatch,
                now=datetime.fromisoformat("2026-07-20T15:00:00+08:00"),
                exclude_window_ids=excluded,
                start_date=date(2026, 7, 20),
                max_days=1,
                limit=3,
            )
            mismatch.close()
            self.assertEqual(
                [item.window_id for item in due_mismatch], [window.window_id]
            )

    def test_source_satisfaction_rechecks_new_unscored_rows(self):
        window = senti3.market_window(date(2026, 7, 20), "morning")
        retail_windows_v2.ensure_window(self.con, window)
        for source, status in (
            ("guba", "complete"),
            ("xinghan", "empty"),
            ("score", "complete"),
            ("kline", "complete"),
        ):
            retail_window_tick._source_status(self.con, window.window_id, source, status)
        self.assertTrue(retail_window_tick._source_is_satisfied(self.con, window.window_id, "score"))

        self.insert_raw(1, 10, "retail", "guba", None, "2026-07-20T10:00:00+08:00")
        retail_windows_v2.map_retail_raw_rows(self.con, raw_ids=[1])

        self.assertFalse(retail_window_tick._source_is_satisfied(self.con, window.window_id, "score"))
        self.assertTrue(retail_window_tick._source_is_satisfied(self.con, window.window_id, "guba"))
        self.assertFalse(retail_window_tick._source_is_satisfied(self.con, window.window_id, "missing"))

    def test_completed_non_weibo_audit_requires_all_media_request_only(self):
        window = senti3.market_window(date(2026, 7, 16), "preopen")
        retail_windows_v2.ensure_window(self.con, window)
        retail_window_tick._source_status(
            self.con, window.window_id, "xinghan", "complete"
        )

        def insert_segment(variant, begin, end):
            stamp = "2026-07-16T10:00:00+08:00"
            self.con.execute(
                """INSERT INTO yuqing_fetch_segment_run(
                     window_id,subject_id,request_variant,segment_start,segment_end,status,
                     snapshot_timestamp_ms,pages_committed,records_seen,error_code,
                     started_at,finished_at,updated_at)
                   VALUES(?,?,?,?,?,'complete',1,1,0,NULL,?,?,?)""",
                (
                    window.window_id,
                    "",
                    variant,
                    begin.isoformat(timespec="seconds"),
                    end.isoformat(timespec="seconds"),
                    stamp,
                    stamp,
                    stamp,
                ),
            )

        for begin, end in window.segments:
            insert_segment("all", begin, end)

        config = {
            "industry_subjects": {},
            "global_probe_subject": "",
        }
        with mock.patch.object(
            retail_window_tick.senti3, "load_layer_config", return_value=config
        ):
            self.assertTrue(
                retail_window_tick._source_is_satisfied(
                    self.con, window.window_id, "xinghan"
                )
            )

    def test_reconcile_requires_source_closure_then_sets_usable(self):
        window = senti3.market_window(date(2026, 7, 20), "morning")
        retail_windows_v2.ensure_window(self.con, window)
        for row_id in range(1, 12):
            self.insert_raw(
                row_id,
                10,
                "retail",
                "guba",
                1,
                f"2026-07-20T10:{row_id:02d}:00+08:00",
            )
        retail_windows_v2.map_retail_raw_rows(self.con)
        for source, status in (
            ("guba", "complete"),
            ("xinghan", "failed"),
            ("score", "complete"),
            ("kline", "failed"),
        ):
            retail_window_tick._source_status(self.con, window.window_id, source, status)

        partial = retail_window_tick.reconcile_window(self.con, window.window_id)
        row = self.con.execute(
            "SELECT scored_count,significant,usable FROM senti_retail_window WHERE window_id=?",
            (window.window_id,),
        ).fetchone()
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(tuple(row), (11, 1, 0))

        retail_window_tick._source_status(self.con, window.window_id, "xinghan", "empty")
        complete = retail_window_tick.reconcile_window(self.con, window.window_id)
        row = self.con.execute(
            "SELECT scored_count,significant,usable FROM senti_retail_window WHERE window_id=?",
            (window.window_id,),
        ).fetchone()
        self.assertEqual(complete["status"], "complete")
        self.assertFalse(complete["kline_ok"])
        self.assertEqual(tuple(row), (11, 1, 1))

    def test_execute_window_selectively_retries_only_failed_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "sentiment.db"
            seed = sqlite3.connect(db_path)
            seed.row_factory = sqlite3.Row
            seed.execute("PRAGMA foreign_keys=ON")
            seed.executescript(RAW_DDL)
            retail_windows_v2.ensure_schema(seed)
            window = senti3.market_window(date(2026, 7, 20), "morning")
            retail_windows_v2.ensure_window(seed, window)
            retail_windows_v2.mark_window_status(seed, window.window_id, "partial")
            retail_window_tick._source_status(seed, window.window_id, "guba", "empty")
            retail_window_tick._source_status(seed, window.window_id, "guba", "empty")
            for source, status in (
                ("xinghan", "failed"),
                ("score", "complete"),
                ("kline", "complete"),
            ):
                retail_window_tick._source_status(seed, window.window_id, source, status)
            seed.commit()
            seed.close()

            def connect(**_kwargs):
                con = sqlite3.connect(db_path)
                con.row_factory = sqlite3.Row
                con.execute("PRAGMA foreign_keys=ON")
                return con

            executed = []

            def fake_child(command):
                executed.append(command.source)
                return retail_window_tick.ChildResult(command.source, 0, "ok", "")

            with mock.patch.object(retail_window_tick.common, "get_senti_db", side_effect=connect), \
                 mock.patch.object(retail_window_tick.common, "assert_senti_only"), \
                 mock.patch.object(retail_window_tick, "run_child", side_effect=fake_child):
                code, result = retail_window_tick.execute_window(
                    window, guba_pages=1, score_max=0
                )

            self.assertEqual(code, 0)
            self.assertEqual(executed, ["xinghan"])
            self.assertEqual(result["executed_sources"], ["xinghan"])
            self.assertEqual(result["skipped_sources"], ["guba", "score", "kline"])
            self.assertEqual(result["status"], "complete")

    def test_controlled_historical_complete_window_is_read_only_idempotent(self):
        """An approved historical trial must not rewrite an already complete window.

        Normal production ticks still recheck legal-empty sources.  The controlled
        trial is deliberately bound to one reviewed historical session and only
        proves that the exact release can read and reconcile the established
        checkpoint without creating a new mutation payload for the same operation
        identity.
        """
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "sentiment.db"
            seed = sqlite3.connect(db_path)
            seed.row_factory = sqlite3.Row
            seed.execute("PRAGMA foreign_keys=ON")
            seed.executescript(RAW_DDL)
            retail_windows_v2.ensure_schema(seed)
            window = senti3.market_window(date(2026, 7, 16), "preopen")
            retail_windows_v2.ensure_window(seed, window)
            for source, status in (
                ("guba", "empty"),
                ("xinghan", "empty"),
                ("score", "complete"),
                ("kline", "complete"),
            ):
                retail_window_tick._source_status(
                    seed, window.window_id, source, status
                )
            retail_window_tick._set_empty_recheck_attempts(
                seed,
                window.window_id,
                "guba",
                retail_window_tick.EMPTY_RECHECK_REQUIRED_ATTEMPTS,
                timestamp="2026-07-16T10:00:00+08:00",
            )
            retail_windows_v2.mark_window_status(seed, window.window_id, "complete")
            seed.execute(
                "UPDATE retail_window_ledger SET retention_state='purged' WHERE window_id=?",
                (window.window_id,),
            )
            seed.commit()
            seed.close()

            def connect(**_kwargs):
                con = sqlite3.connect(db_path)
                con.row_factory = sqlite3.Row
                con.execute("PRAGMA foreign_keys=ON")
                return con

            with mock.patch.dict(
                retail_window_tick.os.environ,
                {
                    "HONGHU_TASK_CONTROLLED_TRIAL": "1",
                    "HONGHU_CONTROLLED_SESSION_DATE": "2026-07-16",
                },
            ), mock.patch.object(
                retail_window_tick.common, "get_senti_db", side_effect=connect
            ), mock.patch.object(
                retail_window_tick.common, "assert_senti_only"
            ), mock.patch.object(
                retail_window_tick, "_window_needs_empty_recheck"
            ) as recheck, mock.patch.object(
                retail_window_tick, "run_child"
            ) as child:
                code, result = retail_window_tick.execute_window(
                    window, guba_pages=1, score_max=0
                )

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["retention_state"], "purged")
            self.assertEqual(result["skipped"], "idempotent")
            recheck.assert_not_called()
            child.assert_not_called()

            with mock.patch.dict(
                retail_window_tick.os.environ,
                {
                    "HONGHU_TASK_CONTROLLED_TRIAL": "0",
                    "HONGHU_CONTROLLED_SESSION_DATE": "",
                },
            ), mock.patch.object(
                retail_window_tick.common, "get_senti_db", side_effect=connect
            ), mock.patch.object(
                retail_window_tick.common, "assert_senti_only"
            ):
                rejected_code, rejected = retail_window_tick.execute_window(
                    window, guba_pages=1, score_max=0
                )
            self.assertEqual(rejected_code, 2)
            self.assertEqual(
                rejected["error"], "retention_finalized_window_cannot_resume"
            )

    def test_execute_window_releases_parent_writer_before_child_and_uses_stable_phases(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "sentiment.db"
            seed = sqlite3.connect(db_path)
            seed.executescript(RAW_DDL)
            seed.close()
            connections = []
            connection_calls = []

            class TrackingConnection:
                def __init__(self):
                    self.connection = sqlite3.connect(db_path)
                    self.connection.row_factory = sqlite3.Row
                    self.connection.execute("PRAGMA foreign_keys=ON")
                    self.closed = False

                def close(self):
                    self.connection.close()
                    self.closed = True

                def __getattr__(self, name):
                    return getattr(self.connection, name)

            def connect(**kwargs):
                connection_calls.append(kwargs)
                con = TrackingConnection()
                connections.append(con)
                return con

            child_observations = []

            def fake_child(command):
                child_observations.append(
                    {
                        "source": command.source,
                        "all_parent_connections_closed": all(
                            con.closed for con in connections
                        ),
                    }
                )
                return retail_window_tick.ChildResult(command.source, 0, "ok", "")

            window = senti3.market_window(date(2026, 7, 20), "morning")
            command = retail_window_tick.ChildCommand("xinghan", "unused.py", (), 10)
            with mock.patch.dict(
                retail_window_tick.os.environ,
                {"HONGHU_OPERATION_ID": "sentiment:retail:2026-07-20-morning"},
            ), mock.patch.object(
                retail_window_tick.common, "get_senti_db", side_effect=connect
            ), mock.patch.object(
                retail_window_tick.common, "assert_senti_only"
            ), mock.patch.object(
                retail_window_tick, "build_commands", return_value=(command,)
            ), mock.patch.object(
                retail_window_tick, "run_child", side_effect=fake_child
            ):
                code, result = retail_window_tick.execute_window(
                    window, guba_pages=1, score_max=0
                )

            self.assertEqual(code, 2)
            self.assertFalse(result["ok"])
            self.assertEqual(
                child_observations,
                [{"source": "xinghan", "all_parent_connections_closed": True}],
            )
            self.assertTrue(all(con.closed for con in connections))
            self.assertEqual(
                [call["operation_id"] for call in connection_calls],
                [
                    "sentiment:retail:2026-07-20-morning:step:"
                    f"window:{window.window_id}:parent:initialize",
                    "sentiment:retail:2026-07-20-morning:step:"
                    f"window:{window.window_id}:parent:source:xinghan:start",
                    "sentiment:retail:2026-07-20-morning:step:"
                    f"window:{window.window_id}:parent:source:xinghan:map",
                    "sentiment:retail:2026-07-20-morning:step:"
                    f"window:{window.window_id}:parent:source:xinghan:finish",
                    "sentiment:retail:2026-07-20-morning:step:"
                    f"window:{window.window_id}:parent:reconcile",
                ],
            )
            self.assertEqual(
                {call["operation_scope"] for call in connection_calls},
                {"retail_window"},
            )

    def test_execute_window_closes_parent_connection_when_map_phase_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "sentiment.db"
            seed = sqlite3.connect(db_path)
            seed.executescript(RAW_DDL)
            seed.close()
            connections = []

            class TrackingConnection:
                def __init__(self):
                    self.connection = sqlite3.connect(db_path)
                    self.connection.row_factory = sqlite3.Row
                    self.closed = False

                def close(self):
                    self.connection.close()
                    self.closed = True

                def __getattr__(self, name):
                    return getattr(self.connection, name)

            def connect(**_kwargs):
                con = TrackingConnection()
                connections.append(con)
                return con

            window = senti3.market_window(date(2026, 7, 20), "morning")
            command = retail_window_tick.ChildCommand("xinghan", "unused.py", (), 10)
            with mock.patch.object(
                retail_window_tick.common, "get_senti_db", side_effect=connect
            ), mock.patch.object(
                retail_window_tick.common, "assert_senti_only"
            ), mock.patch.object(
                retail_window_tick, "build_commands", return_value=(command,)
            ), mock.patch.object(
                retail_window_tick,
                "run_child",
                return_value=retail_window_tick.ChildResult("xinghan", 0, "ok", ""),
            ), mock.patch.object(
                retail_window_tick.retail_windows_v2,
                "map_retail_raw_rows",
                side_effect=RuntimeError("synthetic mapping failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "synthetic mapping failure"):
                    retail_window_tick.execute_window(
                        window, guba_pages=1, score_max=0
                    )

            self.assertTrue(connections)
            self.assertTrue(all(con.closed for con in connections))

    def test_main_executes_current_window_before_backfill(self):
        current = senti3.market_window(date(2026, 7, 20), "morning")
        older = senti3.market_window(date(2026, 7, 17), "afternoon")
        order = []
        clock = mock.Mock()
        clock.now.return_value.weekday.return_value = 0

        class DummyConnection:
            def close(self):
                return None

        def fake_execute(window, **_kwargs):
            order.append(window.window_id)
            return 0, {
                "ok": True,
                "window_id": window.window_id,
                "status": "complete",
                "kline_ok": True,
            }

        with mock.patch.object(retail_window_tick, "datetime", clock), \
             mock.patch.object(retail_window_tick, "exclusive_tick_lock", return_value=nullcontext()), \
             mock.patch.object(retail_window_tick.common, "get_senti_db", return_value=DummyConnection()), \
             mock.patch.object(retail_window_tick.common, "assert_senti_only"), \
             mock.patch.object(retail_window_tick, "wait_for_fresh_orphaned_xinghan", return_value=None), \
             mock.patch.object(retail_window_tick, "recover_stale_windows", return_value=[]), \
             mock.patch.object(retail_window_tick, "resolve_window", return_value=current), \
             mock.patch.object(retail_window_tick, "due_auto_backfill_windows", return_value=[older]), \
             mock.patch.object(retail_window_tick, "execute_window", side_effect=fake_execute), \
             mock.patch("builtins.print"):
            code = retail_window_tick.main(["--slot", "morning"])

        self.assertEqual(code, 0)
        self.assertEqual(order, [current.window_id, older.window_id])

    def test_controlled_historical_trial_does_not_fan_out_to_auto_backfill(self):
        selected = senti3.market_window(date(2026, 7, 16), "preopen")
        order = []
        clock = mock.Mock()
        clock.now.return_value.weekday.return_value = 0

        class DummyConnection:
            def close(self):
                return None

        def fake_execute(window, **_kwargs):
            order.append(window.window_id)
            return 0, {
                "ok": True,
                "window_id": window.window_id,
                "status": "complete",
                "kline_ok": True,
            }

        with mock.patch.dict(
            retail_window_tick.os.environ,
            {
                "HONGHU_TASK_CONTROLLED_TRIAL": "1",
                "HONGHU_CONTROLLED_SESSION_DATE": "2026-07-16",
            },
        ), mock.patch.object(
            retail_window_tick, "datetime", clock
        ), mock.patch.object(
            retail_window_tick, "exclusive_tick_lock", return_value=nullcontext()
        ), mock.patch.object(
            retail_window_tick.common, "get_senti_db", return_value=DummyConnection()
        ), mock.patch.object(
            retail_window_tick.common, "assert_senti_only"
        ), mock.patch.object(
            retail_window_tick, "wait_for_fresh_orphaned_xinghan", return_value=None
        ), mock.patch.object(
            retail_window_tick, "recover_stale_windows", return_value=[]
        ), mock.patch.object(
            retail_window_tick, "resolve_window", return_value=selected
        ), mock.patch.object(
            retail_window_tick, "due_auto_backfill_windows"
        ) as due, mock.patch.object(
            retail_window_tick, "execute_window", side_effect=fake_execute
        ), mock.patch("builtins.print"):
            code = retail_window_tick.main(["--slot", "preopen"])

        self.assertEqual(code, 0)
        self.assertEqual(order, [selected.window_id])
        due.assert_not_called()

    def test_main_yields_history_backfill_when_newer_slot_became_due(self):
        current = senti3.market_window(date(2026, 7, 20), "morning")
        newer = senti3.market_window(date(2026, 7, 20), "afternoon")
        order = []
        clock = mock.Mock()
        clock.now.return_value.weekday.return_value = 0

        class DummyConnection:
            def close(self):
                return None

        def fake_execute(window, **_kwargs):
            order.append(window.window_id)
            return 0, {
                "ok": True, "window_id": window.window_id,
                "status": "complete", "kline_ok": True,
            }

        with mock.patch.object(retail_window_tick, "datetime", clock), \
             mock.patch.object(retail_window_tick, "exclusive_tick_lock", return_value=nullcontext()), \
             mock.patch.object(retail_window_tick.common, "get_senti_db", return_value=DummyConnection()), \
             mock.patch.object(retail_window_tick.common, "assert_senti_only"), \
             mock.patch.object(retail_window_tick, "wait_for_fresh_orphaned_xinghan", return_value=None), \
             mock.patch.object(retail_window_tick, "recover_stale_windows", return_value=[]), \
             mock.patch.object(retail_window_tick, "resolve_window", side_effect=[current, newer]), \
             mock.patch.object(retail_window_tick, "due_auto_backfill_windows") as due, \
             mock.patch.object(retail_window_tick, "execute_window", side_effect=fake_execute), \
             mock.patch("builtins.print") as printed:
            code = retail_window_tick.main(["--slot", "morning"])

        self.assertEqual(code, 0)
        self.assertEqual(order, [current.window_id])
        due.assert_not_called()
        payload = json.loads(printed.call_args.args[0])
        self.assertEqual(
            payload["auto_backfill"]["deferred_for_newer_window"], newer.window_id
        )

    def test_main_rechecks_newer_slot_between_each_history_backfill(self):
        current = senti3.market_window(date(2026, 7, 20), "preopen")
        older_one = senti3.market_window(date(2026, 7, 16), "morning")
        older_two = senti3.market_window(date(2026, 7, 16), "afternoon")
        newer = senti3.market_window(date(2026, 7, 20), "morning")
        order = []
        clock = mock.Mock()
        clock.now.return_value.weekday.return_value = 0

        class DummyConnection:
            def close(self):
                return None

        def fake_execute(window, **_kwargs):
            order.append(window.window_id)
            return 0, {
                "ok": True, "window_id": window.window_id,
                "status": "complete", "kline_ok": True,
            }

        # resolve_window: 主窗口、主窗口完成后的首次检查、第一项旧窗口前检查、
        # 第一项结束后第二次检查。最后一次模拟运行期间已跨过 14:00。
        with mock.patch.object(retail_window_tick, "datetime", clock), \
             mock.patch.object(retail_window_tick, "exclusive_tick_lock", return_value=nullcontext()), \
             mock.patch.object(retail_window_tick.common, "get_senti_db", return_value=DummyConnection()), \
             mock.patch.object(retail_window_tick.common, "assert_senti_only"), \
             mock.patch.object(retail_window_tick, "wait_for_fresh_orphaned_xinghan", return_value=None), \
             mock.patch.object(retail_window_tick, "recover_stale_windows", return_value=[]), \
             mock.patch.object(
                 retail_window_tick,
                 "resolve_window",
                 side_effect=[current, current, current, newer],
             ), \
             mock.patch.object(
                 retail_window_tick,
                 "due_auto_backfill_windows",
                 return_value=[older_one, older_two],
             ), \
             mock.patch.object(retail_window_tick, "execute_window", side_effect=fake_execute), \
             mock.patch("builtins.print") as printed:
            code = retail_window_tick.main(["--slot", "preopen"])

        self.assertEqual(code, 0)
        self.assertEqual(order, [current.window_id, older_one.window_id])
        payload = json.loads(printed.call_args.args[0])
        self.assertEqual(
            payload["auto_backfill"]["deferred_for_newer_window"], newer.window_id
        )

    def test_neutral_non_weibo_feed_keeps_full_content_and_skips_weekend(self):
        record = {
            "dedup_key": "feed-1",
            "post_id": "p1",
            "title": "标题",
            "text": "完整正文" * 100,
            "url": "https://example.test/p1",
            "author": "作者",
            "author_uid": "uid-1",
            "publish_time": "2026-07-20T10:00:00+08:00",
        }
        window_id = retail_windows_v2.store_yuqing_feed_record(
            self.con, record, platform="xueqiu", source_status="ok"
        )
        self.assertEqual(window_id, "2026-07-20:morning")
        row = self.con.execute("SELECT * FROM yuqing_feed_raw").fetchone()
        self.assertEqual(row["author_uid"], "uid-1")
        self.assertEqual(row["content_text"], record["text"])
        self.assertEqual(row["source_status"], "ok")
        weekend = dict(record, dedup_key="feed-2", publish_time="2026-07-18T10:00:00+08:00")
        self.assertIsNone(
            retail_windows_v2.store_yuqing_feed_record(self.con, weekend, platform="xueqiu")
        )
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM yuqing_feed_raw").fetchone()[0], 1)

    def test_generic_weibo_feed_is_rejected_before_storage(self):
        record = {
            "dedup_key": "weibo-feed",
            "post_id": "p-weibo",
            "text": "不进入散户库",
            "publish_time": "2026-07-20T10:00:00+08:00",
        }
        self.assertIsNone(
            retail_windows_v2.store_yuqing_feed_record(
                self.con, record, platform="weibo", source_status="ok"
            )
        )
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM yuqing_feed_raw").fetchone()[0], 0)

    def test_mapping_and_aggregation_are_retail_only(self):
        self.insert_raw(1, 10, "retail", "guba", 1, "2026-07-20T10:00:00+08:00", 5)
        self.insert_raw(2, 10, "retail", "weibo", 2, "2026-07-20T10:01:00+08:00", 1)
        self.insert_raw(3, 10, "news", "sina_news", 2, "2026-07-20T10:02:00+08:00", 99)
        self.insert_raw(4, 10, "retail", "guba", 1, "2026-07-18T10:00:00+08:00", 5)
        stat = retail_windows_v2.map_retail_raw_rows(self.con)
        self.assertEqual(stat, {"seen": 2, "mapped": 1, "excluded_non_session": 1, "invalid_time": 0})
        window_id = "2026-07-20:morning"
        retail_windows_v2.mark_window_status(self.con, window_id, "complete")
        retail_windows_v2.aggregate_window(self.con, window_id, significance_min=0)
        row = self.con.execute("SELECT * FROM senti_retail_window").fetchone()
        self.assertEqual(row["raw_count"], 1)
        self.assertEqual(row["scored_count"], 1)
        self.assertAlmostEqual(row["net_plain"], 1.0)
        self.assertAlmostEqual(row["weighted_pos"], 5.0)
        self.assertAlmostEqual(row["weighted_neg"], 0.0)
        self.assertEqual(row["aggregation_version"], retail_windows_v2.AGGREGATION_VERSION)
        self.assertTrue(row["aggregate_sha256"])
        self.assertEqual(
            json.loads(row["platform_label_json"]),
            {"guba": {"neg": 0, "neu": 0, "pos": 1}},
        )
        self.assertTrue(row["usable"])

    def test_daily_requires_all_three_complete_windows(self):
        times = (
            "2026-07-17T16:01:00+08:00",
            "2026-07-20T09:31:00+08:00",
            "2026-07-20T13:01:00+08:00",
        )
        for row_id, value in enumerate(times, start=1):
            self.insert_raw(row_id, 20, "retail", "guba", 1, value)
        retail_windows_v2.map_retail_raw_rows(self.con)
        for slot in senti3.MARKET_WINDOW_SLOTS:
            window_id = f"2026-07-20:{slot}"
            retail_windows_v2.mark_window_status(self.con, window_id, "complete")
            retail_windows_v2.aggregate_window(self.con, window_id, significance_min=0)
        daily = self.con.execute("SELECT * FROM senti_retail_trading_daily").fetchone()
        self.assertEqual(daily["raw_count"], 3)
        self.assertEqual(daily["completed_windows"], 3)
        self.assertEqual(daily["complete"], 1)
        self.assertEqual(daily["usable"], 1)
        self.assertAlmostEqual(daily["weighted_pos"], 3.0)
        self.assertEqual(
            daily["aggregation_version"],
            retail_windows_v2.AGGREGATION_VERSION,
        )
        self.assertTrue(daily["aggregate_sha256"])

        self.con.execute("DELETE FROM senti_raw")
        retail_windows_v2.aggregate_trading_day(
            self.con,
            "2026-07-20",
            significance_min=0,
        )
        rebuilt = self.con.execute(
            "SELECT * FROM senti_retail_trading_daily"
        ).fetchone()
        self.assertEqual(rebuilt["raw_count"], 3)
        self.assertAlmostEqual(rebuilt["net_weighted"], 1.0)

    def test_seal_blocks_active_window_and_marks_complete_window(self):
        window = senti3.market_window(date(2026, 7, 20), "morning")
        retail_windows_v2.ensure_window(self.con, window)
        retail_windows_v2.mark_window_status(
            self.con,
            window.window_id,
            "running",
        )
        with self.assertRaises(RuntimeError):
            retail_windows_v2.seal_window(self.con, window.window_id)

        self.insert_raw(
            1,
            10,
            "retail",
            "guba",
            1,
            "2026-07-20T10:00:00+08:00",
        )
        retail_windows_v2.map_retail_raw_rows(self.con)
        retail_windows_v2.mark_window_status(
            self.con,
            window.window_id,
            "complete",
        )
        result = retail_windows_v2.seal_window(
            self.con,
            window.window_id,
            grace_days=14,
            sealed_at="2026-08-10T12:00:00+08:00",
        )
        self.assertEqual(result["retention_state"], "sealed_complete")
        ledger = self.con.execute(
            """SELECT retention_state,sealed_at,raw_purge_after,
                      aggregate_sha256
               FROM retail_window_ledger WHERE window_id=?""",
            (window.window_id,),
        ).fetchone()
        self.assertEqual(ledger["retention_state"], "sealed_complete")
        self.assertTrue(ledger["aggregate_sha256"])

    def test_fair_scoring_round_robin_prevents_heat_starvation(self):
        window = senti3.market_window(date(2026, 7, 20), "morning")
        retail_windows_v2.ensure_window(self.con, window)
        row_id = 1
        for company_id, count in ((1, 5), (2, 1), (3, 1)):
            for offset in range(count):
                self.insert_raw(
                    row_id,
                    company_id,
                    "retail",
                    "guba",
                    None,
                    f"2026-07-20T10:{row_id:02d}:00+08:00",
                    heat=1000 - offset if company_id == 1 else 1,
                )
                row_id += 1
        retail_windows_v2.map_retail_raw_rows(self.con)
        selected, stat = retail_windows_v2.fair_score_candidate_ids(
            self.con, window.window_id, max_total=3
        )
        companies = {
            self.con.execute("SELECT company_id FROM senti_raw WHERE id=?", (row_id,)).fetchone()[0]
            for row_id in selected
        }
        self.assertEqual(companies, {1, 2, 3})
        self.assertEqual(stat["candidates"], 7)
        self.assertEqual(stat["remaining"], 4)

    def test_window_sample_is_stable_and_caps_each_company(self):
        window = senti3.market_window(date(2026, 7, 20), "morning")
        retail_windows_v2.ensure_window(self.con, window)
        row_id = 1
        for company_id in (1, 2):
            for offset in range(60):
                self.insert_raw(
                    row_id, company_id, "retail", "guba", None,
                    "2026-07-20T10:00:00+08:00", heat=100 - offset,
                )
                row_id += 1
        retail_windows_v2.map_retail_raw_rows(self.con)
        stat = retail_windows_v2.prepare_window_score_sample(
            self.con, window.window_id, max_per_company=50,
            top_by_heat=40, random_floor=10,
        )
        first = {
            row[0]
            for row in self.con.execute("SELECT id FROM senti_raw WHERE sampled=1")
        }
        by_company = dict(self.con.execute(
            "SELECT company_id,COUNT(*) FROM senti_raw WHERE sampled=1 GROUP BY company_id"
        ))
        self.assertEqual(stat["sampled"], 100)
        self.assertEqual(by_company, {1: 50, 2: 50})
        retail_windows_v2.prepare_window_score_sample(
            self.con, window.window_id, max_per_company=50,
            top_by_heat=40, random_floor=10,
        )
        second = {
            row[0]
            for row in self.con.execute("SELECT id FROM senti_raw WHERE sampled=1")
        }
        self.assertEqual(first, second)

    def test_missing_window_status_update_raises(self):
        with self.assertRaises(ValueError):
            retail_windows_v2.mark_window_status(self.con, "missing", "complete")

    def test_remap_removes_stale_weekend_mapping(self):
        self.insert_raw(1, 10, "retail", "guba", 1, "2026-07-20T10:00:00+08:00")
        retail_windows_v2.map_retail_raw_rows(self.con, raw_ids=[1])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM senti_raw_window").fetchone()[0], 1)
        self.con.execute(
            "UPDATE senti_raw SET publish_time='2026-07-18T10:00:00+08:00' WHERE id=1"
        )
        retail_windows_v2.map_retail_raw_rows(self.con, raw_ids=[1])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM senti_raw_window").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
