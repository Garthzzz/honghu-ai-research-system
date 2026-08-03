from __future__ import annotations

import sys
import unittest
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "sentiment"))

import xinghan_client
import senti_fetch_xinghan


class XinghanPaginationV2Test(unittest.TestCase):
    @staticmethod
    def _client(**kwargs):
        with mock.patch.object(xinghan_client, "load_token", return_value="test-token"):
            return xinghan_client.XinghanWindowClient(**kwargs)

    def test_full_last_page_at_safety_limit_is_truncated(self):
        client = self._client(interval_sec=0, max_pages=2)
        page = [{"id": str(i), "title": f"row{i}"} for i in range(xinghan_client.PAGE_MAX)]
        with mock.patch.object(client, "_post", side_effect=[(page, "ok"), (page, "ok")]):
            rows = client.fetch_window(subject_id="", begin_ms=1, end_ms=2)
        self.assertTrue(rows)
        self.assertEqual(client.last_status, "truncated")

    def test_short_page_proves_completion(self):
        client = self._client(interval_sec=0, max_pages=2)
        page = [{"id": "one", "title": "row"}]
        with mock.patch.object(client, "_post", return_value=(page, "ok")):
            rows = client.fetch_window(subject_id="", begin_ms=1, end_ms=2)
        self.assertEqual(len(rows), 1)
        self.assertEqual(client.last_status, "ok")

    def test_page_iterator_reuses_snapshot_and_resumes_exact_offset(self):
        client = self._client(interval_sec=0, max_pages=2)
        full = [{"id": str(i), "title": f"row{i}"}
                for i in range(xinghan_client.PAGE_MAX)]
        seen_bodies = []

        def post(body):
            seen_bodies.append(body)
            return (full, "ok") if len(seen_bodies) == 1 else ([], "ok")

        with mock.patch.object(client, "_post", side_effect=post):
            pages = list(client.iter_window_pages(
                subject_id="subject", begin_ms=1, end_ms=2,
                snapshot_timestamp_ms=123456789,
                start_offset=2 * xinghan_client.PAGE_MAX,
            ))

        self.assertEqual([body["timestamp"] for body in seen_bodies], [123456789] * 2)
        self.assertEqual(
            [body["offset"] for body in seen_bodies],
            [2 * xinghan_client.PAGE_MAX, 3 * xinghan_client.PAGE_MAX],
        )
        self.assertEqual([page.terminal for page in pages], [False, True])
        self.assertEqual(client.last_status, "ok")

    def test_http_429_retries_the_same_page_instead_of_aborting_window(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({"code": 200, "data": {"records": []}}).encode()

        limited = HTTPError("https://example.invalid", 429, "limited", {"Retry-After": "0"}, None)
        client = self._client(
            interval_sec=0, max_pages=1, rate_limit_retries=1, rate_limit_backoff_sec=0
        )
        with mock.patch.object(client.rl, "acquire"), \
             mock.patch.object(xinghan_client._OPENER, "open", side_effect=[limited, Response()]), \
             mock.patch.object(xinghan_client.time, "sleep") as sleep:
            records, status = client._post({"id": ""})

        self.assertEqual((records, status), ([], "ok"))
        self.assertEqual(client.rate_limit_hits, 1)
        self.assertEqual(client.calls, 1)
        sleep.assert_called_once_with(0.0)

    def test_retry_after_http_date_is_honored(self):
        error = HTTPError(
            "https://example.invalid", 429, "limited",
            {"Retry-After": "Thu, 01 Jan 1970 00:02:00 GMT"}, None,
        )
        client = self._client(interval_sec=0)
        with mock.patch.object(xinghan_client.time, "time", return_value=60.0):
            self.assertEqual(client._rate_limit_wait(error, 0), 60.0)

    def test_http_200_without_explicit_records_is_not_a_complete_empty_page(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{}'

        client = self._client(interval_sec=0)
        with mock.patch.object(client.rl, "acquire"), \
             mock.patch.object(xinghan_client._OPENER, "open", return_value=Response()):
            records, status = client._post({"id": ""})
        self.assertEqual(records, [])
        self.assertEqual(status, "error")

    def test_partial_window_resumes_with_overlap(self):
        con = sqlite3.connect(":memory:")
        con.execute(
            "CREATE TABLE yuqing_feed_raw(window_id TEXT,publish_time TEXT)"
        )
        con.execute(
            "INSERT INTO yuqing_feed_raw VALUES(?,?)",
            ("2026-07-16:preopen", "2026-07-16T05:10:01+08:00"),
        )
        tz = timezone(timedelta(hours=8))
        begin = datetime(2026, 7, 16, 0, 0, tzinfo=tz)
        end = datetime(2026, 7, 16, 9, 30, tzinfo=tz)

        resumed = senti_fetch_xinghan.continuation_begin(
            con,
            window_id="2026-07-16:preopen",
            begin=begin,
            end=end,
            overlap_seconds=180,
        )
        con.close()

        self.assertEqual(resumed, datetime(2026, 7, 16, 5, 7, 1, tzinfo=tz))

    def test_truncated_safety_block_continues_in_same_fetch_run(self):
        class Client:
            instance = None

            def __init__(self, **_kwargs):
                type(self).instance = self
                self.last_status = "ok"
                self.calls = 2
                self.billed = 181
                self.rate_limit_hits = 0
                self.requests = []

            def iter_window_pages(self, *, begin_ms, snapshot_timestamp_ms,
                                  start_offset, **_kwargs):
                self.requests.append((begin_ms, snapshot_timestamp_ms, start_offset))
                if len(self.requests) == 1:
                    self.last_status = "ok"
                    yield xinghan_client.XinghanPage(
                        records=[], offset=0, next_offset=xinghan_client.PAGE_MAX,
                        terminal=False, raw_count=xinghan_client.PAGE_MAX,
                    )
                    self.last_status = "truncated"
                else:
                    self.last_status = "ok"
                    yield xinghan_client.XinghanPage(
                        records=[], offset=xinghan_client.PAGE_MAX,
                        next_offset=2 * xinghan_client.PAGE_MAX,
                        terminal=True, raw_count=1,
                    )

        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        window = senti_fetch_xinghan.parse_window_id("2026-07-16:preopen")
        senti_fetch_xinghan.retail_windows_v2.ensure_schema(con)
        senti_fetch_xinghan.retail_windows_v2.ensure_window(con, window)
        con.commit()
        begin = int(datetime(
            2026, 7, 15, 16, 0, tzinfo=timezone(timedelta(hours=8))
        ).timestamp() * 1000)
        end = begin + 8 * 60 * 60 * 1000
        config = {
            "rate_limit": {
                "max_continuation_chunks_per_segment": 2,
                "resume_overlap_seconds": 180,
            }
        }
        with mock.patch.object(senti_fetch_xinghan, "XinghanWindowClient", Client), \
             mock.patch.object(senti_fetch_xinghan, "resolve_subjects", return_value=[""]), \
             mock.patch.object(
                 senti_fetch_xinghan, "_store_page_records", return_value=0,
             ):
            result = senti_fetch_xinghan.fetch_range(
                con,
                begin_ms=begin,
                end_ms=end,
                backfilled=0,
                alias_idx=mock.Mock(),
                lcfg=config,
                expected_window_id="2026-07-16:preopen",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(
            [item[2] for item in Client.instance.requests],
            [0, xinghan_client.PAGE_MAX],
        )
        self.assertEqual(
            Client.instance.requests[0][1], Client.instance.requests[1][1]
        )
        self.assertEqual(
            con.execute("SELECT COUNT(*) FROM yuqing_fetch_checkpoint").fetchone()[0], 0
        )
        segment = con.execute(
            "SELECT status,pages_committed,records_seen FROM yuqing_fetch_segment_run"
        ).fetchone()
        self.assertEqual(tuple(segment), ("complete", 2, 181))
        con.close()

    def test_failed_page_keeps_exact_snapshot_and_offset_for_restart(self):
        class Client:
            instances = []

            def __init__(self, **_kwargs):
                self.last_status = "ok"
                self.calls = 1
                self.billed = xinghan_client.PAGE_MAX
                self.rate_limit_hits = 0
                self.requests = []
                type(self).instances.append(self)

            def iter_window_pages(self, *, snapshot_timestamp_ms, start_offset, **_kwargs):
                self.requests.append((snapshot_timestamp_ms, start_offset))
                if len(type(self).instances) == 1:
                    self.last_status = "ok"
                    yield xinghan_client.XinghanPage(
                        records=[], offset=start_offset,
                        next_offset=start_offset + xinghan_client.PAGE_MAX,
                        terminal=False, raw_count=xinghan_client.PAGE_MAX,
                    )
                    self.last_status = "rate_limited"
                else:
                    self.last_status = "ok"
                    yield xinghan_client.XinghanPage(
                        records=[], offset=start_offset,
                        next_offset=start_offset + xinghan_client.PAGE_MAX,
                        terminal=True, raw_count=7,
                    )

        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        window = senti_fetch_xinghan.parse_window_id("2026-07-16:morning")
        senti_fetch_xinghan.retail_windows_v2.ensure_schema(con)
        senti_fetch_xinghan.retail_windows_v2.ensure_window(con, window)
        con.commit()
        begin, end = window.segments[0]
        config = {"rate_limit": {"max_continuation_chunks_per_segment": 1}}
        patches = (
            mock.patch.object(senti_fetch_xinghan, "XinghanWindowClient", Client),
            mock.patch.object(senti_fetch_xinghan, "resolve_subjects", return_value=[""]),
            mock.patch.object(senti_fetch_xinghan, "_store_page_records", return_value=0),
        )
        with patches[0], patches[1], patches[2]:
            first = senti_fetch_xinghan.fetch_range(
                con, begin_ms=senti_fetch_xinghan.senti3.to_ms(begin),
                end_ms=senti_fetch_xinghan.senti3.to_ms(end), backfilled=0,
                alias_idx=mock.Mock(), lcfg=config,
                expected_window_id=window.window_id,
            )
            checkpoint = con.execute(
                "SELECT snapshot_timestamp_ms,next_offset FROM yuqing_fetch_checkpoint"
            ).fetchone()
            self.assertFalse(first["ok"])
            self.assertEqual(checkpoint["next_offset"], xinghan_client.PAGE_MAX)

            second = senti_fetch_xinghan.fetch_range(
                con, begin_ms=senti_fetch_xinghan.senti3.to_ms(begin),
                end_ms=senti_fetch_xinghan.senti3.to_ms(end), backfilled=0,
                alias_idx=mock.Mock(), lcfg=config,
                expected_window_id=window.window_id,
            )

        self.assertTrue(second["ok"])
        self.assertEqual(
            Client.instances[1].requests[0],
            (checkpoint["snapshot_timestamp_ms"], xinghan_client.PAGE_MAX),
        )
        self.assertEqual(
            con.execute("SELECT COUNT(*) FROM yuqing_fetch_checkpoint").fetchone()[0], 0
        )
        self.assertEqual(
            con.execute("SELECT status FROM yuqing_fetch_segment_run").fetchone()[0],
            "complete",
        )
        con.close()

    @staticmethod
    def _formal_window_connection(window_id="2026-07-16:morning"):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        window = senti_fetch_xinghan.parse_window_id(window_id)
        senti_fetch_xinghan.retail_windows_v2.ensure_schema(con)
        senti_fetch_xinghan.retail_windows_v2.ensure_window(con, window)
        con.commit()
        return con, window

    def test_formal_window_requests_only_explicit_non_weibo_media_types(self):
        class Client:
            instances = []

            def __init__(self, **_kwargs):
                self.last_status = "ok"
                self.calls = 0
                self.billed = 0
                self.rate_limit_hits = 0
                self.requests = []
                type(self).instances.append(self)

            def iter_window_pages(self, *, subject_id, media_types,
                                  snapshot_timestamp_ms, start_offset, **_kwargs):
                self.calls += 1
                self.requests.append(
                    (subject_id, tuple(media_types), snapshot_timestamp_ms, start_offset)
                )
                self.last_status = "empty"
                yield xinghan_client.XinghanPage(
                    records=[], offset=start_offset,
                    next_offset=start_offset + xinghan_client.PAGE_MAX,
                    terminal=True, raw_count=0,
                )

        con, window = self._formal_window_connection()
        begin, end = window.segments[0]
        with mock.patch.object(senti_fetch_xinghan, "XinghanWindowClient", Client), \
             mock.patch.object(senti_fetch_xinghan, "resolve_subjects", return_value=[""]):
            result = senti_fetch_xinghan.fetch_range(
                con,
                begin_ms=senti_fetch_xinghan.senti3.to_ms(begin),
                end_ms=senti_fetch_xinghan.senti3.to_ms(end),
                backfilled=0,
                alias_idx=mock.Mock(),
                lcfg={},
                expected_window_id=window.window_id,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(len(Client.instances), 1)
        self.assertEqual(
            [(row[0], row[1]) for row in Client.instances[0].requests],
            [("", senti_fetch_xinghan.NON_WEIBO_MEDIA_TYPES)],
        )
        self.assertEqual(
            [tuple(row) for row in con.execute(
                """SELECT subject_id,request_variant,status
                   FROM yuqing_fetch_segment_run ORDER BY request_variant"""
            )],
            [("", "all", "complete")],
        )
        self.assertTrue(any("variant=ALL" in key for key in result["status"]))
        con.close()

    def test_non_weibo_checkpoint_resumes_same_snapshot_and_offset(self):
        class Client:
            instances = []

            def __init__(self, **_kwargs):
                self.last_status = "ok"
                self.calls = 0
                self.billed = 0
                self.rate_limit_hits = 0
                self.requests = []
                type(self).instances.append(self)

            def iter_window_pages(self, *, subject_id, media_types,
                                  snapshot_timestamp_ms, start_offset, **_kwargs):
                self.calls += 1
                request = (
                    subject_id, tuple(media_types), snapshot_timestamp_ms, start_offset,
                )
                self.requests.append(request)
                if len(type(self).instances) == 1:
                    self.last_status = "ok"
                    yield xinghan_client.XinghanPage(
                        records=[], offset=start_offset,
                        next_offset=start_offset + xinghan_client.PAGE_MAX,
                        terminal=False, raw_count=xinghan_client.PAGE_MAX,
                    )
                    self.last_status = "rate_limited"
                    return
                self.last_status = "ok"
                yield xinghan_client.XinghanPage(
                    records=[], offset=start_offset,
                    next_offset=start_offset + xinghan_client.PAGE_MAX,
                    terminal=True, raw_count=7,
                )

        con, window = self._formal_window_connection()
        begin, end = window.segments[0]
        config = {
            "rate_limit": {"max_continuation_chunks_per_segment": 1},
        }
        with mock.patch.object(senti_fetch_xinghan, "XinghanWindowClient", Client), \
             mock.patch.object(senti_fetch_xinghan, "resolve_subjects", return_value=[""]):
            first = senti_fetch_xinghan.fetch_range(
                con,
                begin_ms=senti_fetch_xinghan.senti3.to_ms(begin),
                end_ms=senti_fetch_xinghan.senti3.to_ms(end),
                backfilled=0, alias_idx=mock.Mock(), lcfg=config,
                expected_window_id=window.window_id,
            )
            checkpoint = con.execute(
                """SELECT request_variant,snapshot_timestamp_ms,next_offset
                   FROM yuqing_fetch_checkpoint"""
            ).fetchone()
            second = senti_fetch_xinghan.fetch_range(
                con,
                begin_ms=senti_fetch_xinghan.senti3.to_ms(begin),
                end_ms=senti_fetch_xinghan.senti3.to_ms(end),
                backfilled=0, alias_idx=mock.Mock(), lcfg=config,
                expected_window_id=window.window_id,
            )

        self.assertFalse(first["ok"])
        self.assertEqual(checkpoint["request_variant"], "all")
        self.assertEqual(checkpoint["next_offset"], xinghan_client.PAGE_MAX)
        self.assertTrue(second["ok"])
        self.assertEqual(len(Client.instances[1].requests), 1)
        resumed = Client.instances[1].requests[0]
        self.assertEqual(
            (resumed[0], resumed[1]),
            ("", senti_fetch_xinghan.NON_WEIBO_MEDIA_TYPES),
        )
        self.assertEqual(resumed[2], checkpoint["snapshot_timestamp_ms"])
        self.assertEqual(resumed[3], xinghan_client.PAGE_MAX)
        self.assertEqual(
            [tuple(row) for row in con.execute(
                "SELECT request_variant,status FROM yuqing_fetch_segment_run ORDER BY request_variant"
            )],
            [("all", "complete")],
        )
        con.close()

    def test_formal_window_keeps_single_non_weibo_request(self):
        class Client:
            instance = None

            def __init__(self, **_kwargs):
                type(self).instance = self
                self.last_status = "ok"
                self.calls = 0
                self.billed = 0
                self.rate_limit_hits = 0
                self.requests = []

            def iter_window_pages(self, *, subject_id, media_types, start_offset, **_kwargs):
                self.calls += 1
                self.requests.append((subject_id, tuple(media_types)))
                self.last_status = "empty"
                yield xinghan_client.XinghanPage(
                    records=[], offset=start_offset,
                    next_offset=start_offset + xinghan_client.PAGE_MAX,
                    terminal=True, raw_count=0,
                )

        con, window = self._formal_window_connection()
        begin, end = window.segments[0]
        with mock.patch.object(senti_fetch_xinghan, "XinghanWindowClient", Client), \
             mock.patch.object(senti_fetch_xinghan, "resolve_subjects", return_value=[""]):
            result = senti_fetch_xinghan.fetch_range(
                con,
                begin_ms=senti_fetch_xinghan.senti3.to_ms(begin),
                end_ms=senti_fetch_xinghan.senti3.to_ms(end),
                backfilled=0, alias_idx=mock.Mock(),
                lcfg={},
                expected_window_id=window.window_id,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(
            Client.instance.requests,
            [("", senti_fetch_xinghan.NON_WEIBO_MEDIA_TYPES)],
        )
        self.assertEqual(
            con.execute(
                "SELECT GROUP_CONCAT(request_variant) FROM yuqing_fetch_segment_run"
            ).fetchone()[0],
            "all",
        )
        con.close()

    def test_legacy_range_also_excludes_weibo(self):
        class Client:
            instance = None

            def __init__(self, **_kwargs):
                type(self).instance = self
                self.last_status = "ok"
                self.calls = 0
                self.billed = 0
                self.rate_limit_hits = 0
                self.requests = []

            def iter_window_pages(self, *, subject_id, media_types, start_offset, **_kwargs):
                self.calls += 1
                self.requests.append((subject_id, tuple(media_types)))
                self.last_status = "empty"
                yield xinghan_client.XinghanPage(
                    records=[], offset=start_offset,
                    next_offset=start_offset + xinghan_client.PAGE_MAX,
                    terminal=True, raw_count=0,
                )

        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        with mock.patch.object(senti_fetch_xinghan, "XinghanWindowClient", Client), \
             mock.patch.object(senti_fetch_xinghan, "resolve_subjects", return_value=[""]):
            result = senti_fetch_xinghan.fetch_range(
                con, begin_ms=1, end_ms=2, backfilled=0,
                alias_idx=mock.Mock(), lcfg={},
                expected_window_id=None,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(
            Client.instance.requests,
            [("", senti_fetch_xinghan.NON_WEIBO_MEDIA_TYPES)],
        )
        self.assertEqual(
            con.execute("SELECT COUNT(*) FROM yuqing_fetch_segment_run").fetchone()[0], 0
        )
        con.close()

    def test_page_write_exception_rolls_back_records_and_keeps_prior_checkpoint(self):
        class Client:
            def __init__(self, **_kwargs):
                self.last_status = "ok"
                self.calls = 1
                self.billed = 1
                self.rate_limit_hits = 0

            def iter_window_pages(self, *, start_offset, **_kwargs):
                self.last_status = "ok"
                yield xinghan_client.XinghanPage(
                    records=[{"dedup_key": "row"}],
                    offset=start_offset,
                    next_offset=start_offset + xinghan_client.PAGE_MAX,
                    terminal=True,
                    raw_count=1,
                )

        con, window = self._formal_window_connection()
        con.execute("CREATE TABLE page_effect(value TEXT)")
        con.commit()
        begin, end = window.segments[0]

        def fail_mid_page(connection, **_kwargs):
            connection.execute("INSERT INTO page_effect VALUES('must_rollback')")
            raise RuntimeError("injected page write failure")

        with mock.patch.object(senti_fetch_xinghan, "XinghanWindowClient", Client), \
             mock.patch.object(senti_fetch_xinghan, "resolve_subjects", return_value=[""]), \
             mock.patch.object(
                 senti_fetch_xinghan, "_store_page_records", side_effect=fail_mid_page,
             ):
            with self.assertRaisesRegex(RuntimeError, "injected page write failure"):
                senti_fetch_xinghan.fetch_range(
                    con,
                    begin_ms=senti_fetch_xinghan.senti3.to_ms(begin),
                    end_ms=senti_fetch_xinghan.senti3.to_ms(end),
                    backfilled=0, alias_idx=mock.Mock(),
                    lcfg={},
                    expected_window_id=window.window_id,
                )

        self.assertEqual(con.execute("SELECT COUNT(*) FROM page_effect").fetchone()[0], 0)
        checkpoint = con.execute(
            """SELECT request_variant,next_offset,pages_committed,records_seen
               FROM yuqing_fetch_checkpoint"""
        ).fetchone()
        self.assertEqual(tuple(checkpoint), ("all", 0, 0, 0))
        segment = con.execute(
            "SELECT status,pages_committed,records_seen FROM yuqing_fetch_segment_run"
        ).fetchone()
        self.assertEqual(tuple(segment), ("running", 0, 0))
        con.close()

    def test_old_checkpoint_schema_migrates_to_all_variant_idempotently(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        ddl = senti_fetch_xinghan.retail_windows_v2.V2_DDL
        legacy_ddl = ddl.replace("  request_variant      TEXT NOT NULL,\n", "").replace(
            "PRIMARY KEY(window_id, subject_id, request_variant, segment_start, segment_end)",
            "PRIMARY KEY(window_id, subject_id, segment_start, segment_end)",
        )
        con.executescript(legacy_ddl)
        con.execute(
            """INSERT INTO retail_window_ledger(
                 window_id,window_version,session_date,slot,window_start,window_end,
                 scheduled_for,segments_json,effective_minutes,status)
               VALUES('2026-07-16:morning','v','2026-07-16','morning','a','b','c','[]',1,'running')"""
        )
        con.execute(
            """INSERT INTO yuqing_fetch_checkpoint VALUES(
                 '2026-07-16:morning','','a','b',1,2,3,180,180,1,180,'now','now')"""
        )
        con.execute(
            """INSERT INTO yuqing_fetch_segment_run VALUES(
                 '2026-07-16:morning','','a','b','partial',3,1,180,'rate_limited',
                 'now','now','now')"""
        )

        senti_fetch_xinghan.retail_windows_v2.ensure_schema(con)
        senti_fetch_xinghan.retail_windows_v2.ensure_schema(con)

        expected_pk = [
            "window_id", "subject_id", "request_variant", "segment_start", "segment_end",
        ]
        for table in ("yuqing_fetch_checkpoint", "yuqing_fetch_segment_run"):
            info = con.execute(f"PRAGMA table_info({table})").fetchall()
            actual_pk = [
                row["name"] for row in sorted(
                    (row for row in info if row["pk"]), key=lambda row: row["pk"]
                )
            ]
            self.assertEqual(actual_pk, expected_pk)
            self.assertEqual(
                con.execute(f"SELECT request_variant FROM {table}").fetchone()[0],
                "all",
            )
            self.assertEqual(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 1)
        con.close()


if __name__ == "__main__":
    unittest.main()
