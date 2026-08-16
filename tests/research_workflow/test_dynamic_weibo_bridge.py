from __future__ import annotations

import sqlite3
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from tools.dynamic import scheduler, seed_3a, voice_ingest
from tools.dynamic.fetchers import voice_fetcher


RESEARCH_SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE opinion_leader(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  platform TEXT NOT NULL,
  account_handle TEXT,
  region TEXT,
  is_active INTEGER NOT NULL DEFAULT 1,
  last_fetched_at TEXT,
  updated_at TEXT
);
CREATE TABLE voice_post(
  id INTEGER PRIMARY KEY,
  leader_id INTEGER NOT NULL REFERENCES opinion_leader(id),
  post_url TEXT,
  post_id TEXT NOT NULL,
  posted_at TEXT,
  content_text TEXT,
  content_html TEXT,
  has_media INTEGER,
  fetch_timestamp TEXT,
  last_verified_at TEXT,
  ai_summary TEXT,
  ai_tagged_by TEXT,
  is_ai_relevant INTEGER,
  UNIQUE(leader_id,post_id)
);
"""


SCHEDULE_SCHEMA = """
CREATE TABLE opinion_leader(
  id INTEGER PRIMARY KEY,
  region TEXT,
  platform TEXT,
  account_handle TEXT,
  fetch_frequency_minutes INTEGER
);
CREATE TABLE fetch_schedule(
  id INTEGER PRIMARY KEY,
  target_type TEXT,
  target_id INTEGER,
  target_label TEXT,
  frequency_minutes INTEGER,
  next_run_at TEXT,
  last_run_at TEXT,
  status TEXT,
  error_count INTEGER DEFAULT 0,
  last_error TEXT,
  is_active INTEGER DEFAULT 1,
  is_running INTEGER DEFAULT 0,
  running_started_at TEXT,
  updated_at TEXT
);
"""


class WeiboKolApiFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "research.db"
        con = sqlite3.connect(self.db)
        con.executescript(RESEARCH_SCHEMA)
        con.execute(
            "INSERT INTO opinion_leader(id,name,platform,account_handle,region) "
            "VALUES(1,'大才子','weibo','1673580867','cn')"
        )
        con.commit()
        con.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def connection(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        return con

    def test_exact_author_api_result_is_upserted_and_longer_body_is_reenriched(self) -> None:
        class Fetcher:
            last_status = "ok"

            def __init__(self) -> None:
                self.body = "本人原文"

            def fetch(self, leader):
                self.seen = dict(leader)
                return [{
                    "post_id": "p-1",
                    "post_url": "https://weibo.com/1673580867/p-1",
                    "posted_at": "2026-07-21T09:00:00+08:00",
                    "content_text": self.body,
                    "content_html": "",
                    "has_media": False,
                }]

        fetcher = Fetcher()
        con = self.connection()
        leader = con.execute("SELECT * FROM opinion_leader WHERE id=1").fetchone()
        with mock.patch.object(voice_ingest, "make_fetcher", return_value=fetcher):
            first = voice_ingest.fetch_leader(con, leader)
            self.assertEqual((first.got, first.inserted, first.updated, first.status), (1, 1, 0, "ok"))
            con.execute(
                "UPDATE voice_post SET ai_summary='旧摘要',ai_tagged_by='deepseek_funnel',is_ai_relevant=1"
            )
            con.commit()
            fetcher.body = "本人后来取得的更完整原文"
            second = voice_ingest.fetch_leader(con, leader)
        self.assertEqual((second.inserted, second.updated), (0, 1))
        row = con.execute(
            "SELECT content_text,ai_summary,ai_tagged_by,is_ai_relevant FROM voice_post"
        ).fetchone()
        self.assertEqual(row["content_text"], fetcher.body)
        self.assertEqual(row[1:], (None, None, None))
        self.assertEqual(fetcher.seen["account_handle"], "1673580867")
        con.close()

    def test_api_failure_does_not_advance_leader_or_write_posts(self) -> None:
        failed = mock.Mock()
        failed.last_status = "auth_expired"
        failed.fetch.return_value = []
        con = self.connection()
        leader = con.execute("SELECT * FROM opinion_leader WHERE id=1").fetchone()
        with mock.patch.object(voice_ingest, "make_fetcher", return_value=failed):
            outcome = voice_ingest.fetch_leader(con, leader)
        self.assertEqual(outcome.status, "auth_expired")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM voice_post").fetchone()[0], 0)
        self.assertIsNone(
            con.execute("SELECT last_fetched_at FROM opinion_leader WHERE id=1").fetchone()[0]
        )
        con.close()

    def test_weibo_fetcher_uses_yuqing_api_only(self) -> None:
        post = {"post_id": "p-1"}
        fetcher = voice_fetcher.WeiboFetcher({"mode": "api", "api": {"media_types": [4]}})
        with (
            mock.patch.object(voice_fetcher, "_try_kuaisearch", return_value=([post], "ok", True)) as api,
            mock.patch.object(voice_fetcher, "_cookie") as cookie,
            mock.patch.object(voice_fetcher, "_get") as http,
        ):
            self.assertEqual(fetcher.fetch({"account_handle": "1673580867"}), [post])
        api.assert_called_once_with(fetcher.cfg, "1673580867", media_types=[4])
        cookie.assert_not_called()
        http.assert_not_called()


class VoiceExitCodeContractTest(unittest.TestCase):
    @staticmethod
    def outcome(status: str) -> voice_ingest.FetchOutcome:
        return voice_ingest.FetchOutcome(0, 0, 0, status)

    def test_transient_shared_token_statuses_defer_without_masking_real_failure(self) -> None:
        leader = mock.MagicMock()
        for status in voice_ingest.DEFERRED_STATUSES:
            self.assertEqual(
                voice_ingest._result_exit_code([(leader, self.outcome(status))]),
                voice_ingest.EXIT_DEFERRED,
            )
        self.assertEqual(
            voice_ingest._result_exit_code([
                (leader, self.outcome("cached_stale")),
                (leader, self.outcome("system_error")),
            ]),
            voice_ingest.EXIT_SYSTEM,
        )

    def test_successful_api_check_without_recent_author_post_is_not_a_failure(self) -> None:
        leader = mock.MagicMock()
        self.assertEqual(
            voice_ingest._result_exit_code([(leader, self.outcome("api_miss"))]),
            0,
        )


class SchedulerContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "research.db"
        con = sqlite3.connect(self.db)
        con.executescript(SCHEDULE_SCHEMA)
        con.execute("INSERT INTO opinion_leader VALUES(1,'cn','weibo','1673580867',30)")
        con.execute(
            """INSERT INTO fetch_schedule(
                 id,target_type,target_id,target_label,frequency_minutes,next_run_at,
                 status,error_count,is_active,is_running)
               VALUES(1,'voice_leader',1,'大才子',60,NULL,'active',0,1,0)"""
        )
        con.commit()
        con.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_all_voice_leaders_use_global_hourly_frequency(self) -> None:
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM fetch_schedule WHERE id=1").fetchone()
        self.assertEqual(scheduler.freq_for(con, row), 60)
        con.close()

    def test_voice_window_is_beijing_09_to_17_inclusive(self) -> None:
        self.assertFalse(scheduler.voice_window_open(datetime(2026, 7, 21, 8, 59)))
        self.assertTrue(scheduler.voice_window_open(datetime(2026, 7, 21, 9, 0)))
        self.assertTrue(scheduler.voice_window_open(datetime(2026, 7, 21, 17, 0)))
        self.assertFalse(scheduler.voice_window_open(datetime(2026, 7, 21, 17, 1)))
        self.assertEqual(
            scheduler.next_allowed_voice_time(datetime(2026, 7, 24, 18, 0)),
            datetime(2026, 7, 27, 9, 0),
        )

    def test_voice_tick_outside_window_does_not_fetch_or_touch_schedule(self) -> None:
        fixed = datetime.fromisoformat("2026-07-21T17:15:00")
        with (
            mock.patch.object(scheduler, "DB", self.db),
            mock.patch.object(scheduler.quiet_hours, "is_weekend", return_value=False),
            mock.patch.object(scheduler.quiet_hours, "in_quiet_hours", return_value=False),
            mock.patch.object(scheduler, "now", return_value=fixed),
            mock.patch.object(scheduler, "run_fetch") as run_fetch,
            mock.patch.object(scheduler, "log"),
        ):
            scheduler.tick()
        run_fetch.assert_not_called()
        con = sqlite3.connect(self.db)
        self.assertIsNone(con.execute("SELECT next_run_at FROM fetch_schedule WHERE id=1").fetchone()[0])
        con.close()

    def test_weekend_tick_is_silent_and_does_not_touch_db(self) -> None:
        with (
            mock.patch.object(scheduler, "DB", self.db),
            mock.patch.object(scheduler.quiet_hours, "is_weekend", return_value=True),
            mock.patch.object(scheduler, "run_fetch") as run_fetch,
            mock.patch.object(scheduler, "log") as log,
        ):
            self.assertIsNone(scheduler.tick())
        run_fetch.assert_not_called()
        log.assert_not_called()

    def test_deferred_child_does_not_increment_failure_or_pause(self) -> None:
        fixed = datetime.fromisoformat("2026-07-21T12:00:00")
        deferred = scheduler.ScheduledFetchDeferred("shared token busy")
        with (
            mock.patch.object(scheduler, "DB", self.db),
            mock.patch.object(scheduler.quiet_hours, "is_weekend", return_value=False),
            mock.patch.object(scheduler.quiet_hours, "in_quiet_hours", return_value=False),
            mock.patch.object(scheduler, "run_fetch", side_effect=deferred),
            mock.patch.object(scheduler, "now", return_value=fixed),
            mock.patch.object(scheduler, "log"),
        ):
            scheduler.tick()
        con = sqlite3.connect(self.db)
        row = con.execute(
            "SELECT status,error_count,last_error,is_running,next_run_at FROM fetch_schedule WHERE id=1"
        ).fetchone()
        self.assertEqual(row[:4], ("active", 0, None, 0))
        self.assertEqual(row[4], "2026-07-21T12:15:00")
        con.close()

    def test_voice_exit_22_is_scheduler_deferred(self) -> None:
        row = {"target_type": "voice_leader", "target_id": 1, "target_label": "大才子"}
        completed = subprocess.CompletedProcess(
            args=["python"], returncode=voice_ingest.EXIT_DEFERRED,
            stdout='VOICE_INGEST_RESULT {"exit_code": 22}', stderr="cached_stale",
        )
        with (
            mock.patch.object(scheduler.subprocess, "run", return_value=completed),
            mock.patch.dict(
                scheduler.os.environ,
                {
                    "HONGHU_RELEASE_BOOTSTRAP": "C:/candidate/direct_candidate.py",
                    "HONGHU_LOCKED_SITE_PACKAGES": "C:/candidate/site-packages",
                    "HONGHU_OPERATION_ID": "stage5:test:voice",
                },
            ),
            mock.patch.object(scheduler, "log"),
        ):
            with self.assertRaises(scheduler.ScheduledFetchDeferred):
                scheduler.run_fetch(None, row)


class SeedProvenanceTest(unittest.TestCase):
    def test_weibo_source_is_updated_to_targeted_api_provenance(self) -> None:
        con = sqlite3.connect(":memory:")
        con.execute(
            """CREATE TABLE source(
                 id INTEGER PRIMARY KEY,source_url TEXT,note TEXT,fetch_method TEXT,
                 source_subtype TEXT,fetch_timestamp TEXT)"""
        )
        con.execute(
            "INSERT INTO source(id,source_url,fetch_method,source_subtype) "
            "VALUES(1,'https://weibo.com/u/123','yuqing_feed_bridge','voice_weibo')"
        )
        source_id, created = seed_3a.get_or_create_source(
            con.cursor(), title="微博作者 · 微博", stype="自媒体", publisher="微博",
            url="https://weibo.com/u/123", subtype="voice_weibo",
            credibility="unverified", tier=3, language="zh",
            fetch_method="yuqing_api_author",
        )
        self.assertEqual((source_id, created), (1, False))
        self.assertEqual(
            con.execute("SELECT fetch_method,source_subtype FROM source WHERE id=1").fetchone(),
            ("yuqing_api_author", "voice_weibo"),
        )
        con.close()

    def test_all_historical_weibo_sources_get_api_provenance(self) -> None:
        con = sqlite3.connect(":memory:")
        con.executescript(
            """
            CREATE TABLE source(id INTEGER PRIMARY KEY,fetch_method TEXT,source_subtype TEXT);
            CREATE TABLE opinion_leader(id INTEGER PRIMARY KEY,platform TEXT,source_id INTEGER);
            INSERT INTO source VALUES(1,'yuqing_feed_bridge','voice_weibo');
            INSERT INTO source VALUES(2,'scrape_twitter','voice_twitter');
            INSERT INTO opinion_leader VALUES(10,'weibo',1);
            INSERT INTO opinion_leader VALUES(11,'twitter',2);
            """
        )
        self.assertEqual(seed_3a.migrate_all_weibo_source_provenance(con.cursor()), 1)
        self.assertEqual(
            con.execute("SELECT fetch_method FROM source WHERE id=1").fetchone()[0],
            "yuqing_api_author",
        )
        self.assertEqual(
            con.execute("SELECT fetch_method FROM source WHERE id=2").fetchone()[0],
            "scrape_twitter",
        )
        con.close()


if __name__ == "__main__":
    unittest.main()
