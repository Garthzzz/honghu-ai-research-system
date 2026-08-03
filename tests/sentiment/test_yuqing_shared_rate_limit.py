from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
FETCHERS = ROOT / "tools" / "dynamic" / "fetchers"
SENTIMENT = ROOT / "tools" / "sentiment"
for path in (FETCHERS, SENTIMENT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import kuaisearch_client
import senti3
import voice_fetcher
from yuqing_rate_limit import SharedSubjectInfosLimiter


class SharedSubjectInfosLimiterTest(unittest.TestCase):
    def test_clients_share_atomic_state_and_enforce_65_second_floor(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [100.0]
            clock = lambda: now[0]
            first = SharedSubjectInfosLimiter(
                cache_dir=directory, interval_seconds=65, clock=clock,
            )
            second = SharedSubjectInfosLimiter(
                cache_dir=directory, interval_seconds=65, clock=clock,
            )

            self.assertTrue(first.try_acquire().acquired)
            denied = second.try_acquire()
            self.assertFalse(denied.acquired)
            self.assertEqual(denied.reason, "cooldown")
            self.assertEqual(denied.retry_after_seconds, 65.0)
            self.assertEqual(
                (Path(directory) / "rl_infos.txt").read_text(),
                (Path(directory) / "last_call.txt").read_text(),
            )

            now[0] = 164.9
            self.assertFalse(second.try_acquire().acquired)
            now[0] = 165.0
            self.assertTrue(second.try_acquire().acquired)

    def test_nonblocking_client_yields_while_other_process_lock_is_held(self):
        with tempfile.TemporaryDirectory() as directory:
            owner = SharedSubjectInfosLimiter(cache_dir=directory)
            contender = SharedSubjectInfosLimiter(cache_dir=directory)
            with owner._lock(blocking=False) as acquired:
                self.assertTrue(acquired)
                decision = contender.try_acquire()
            self.assertFalse(decision.acquired)
            self.assertEqual(decision.reason, "busy")

    def test_legacy_senti3_wrapper_uses_shared_limiter_and_floor(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(senti3, "CACHE_YUQING", Path(directory)):
            limiter = senti3.RateLimiter("infos", 1)
        self.assertEqual(limiter.interval, 65.0)
        self.assertIsInstance(limiter._shared, SharedSubjectInfosLimiter)


class KuaiSearchSharedLimiterTest(unittest.TestCase):
    def _client(self, directory):
        with mock.patch.object(kuaisearch_client, "CACHEDIR", Path(directory)), \
             mock.patch.object(kuaisearch_client, "load_token", return_value="test-token"):
            return kuaisearch_client.KuaiSearchClient(
                {"cache_ttl_sec": 0, "min_interval_sec": 1}
            )

    def test_busy_window_fetch_returns_stale_with_explicit_status_and_no_api_call(self):
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            cache_path = client._cache_path([])
            cache_path.write_text(
                json.dumps({"_pulled_at": 0, "records": [{"id": "old"}]}),
                encoding="utf-8",
            )
            decision = mock.Mock(
                acquired=False, reason="busy", retry_after_seconds=65.0
            )
            with mock.patch.object(client.rate_limiter, "try_acquire", return_value=decision), \
                 mock.patch.object(client, "_post") as post:
                records = client.pull_recent([])

            self.assertEqual(records, [{"id": "old"}])
            self.assertEqual(client.last_status, "cached_stale")
            self.assertIn("busy", client.last_rate_limit_reason)
            post.assert_not_called()

    def test_busy_without_cache_is_rate_limited_and_does_not_call_api(self):
        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            decision = mock.Mock(
                acquired=False, reason="cooldown", retry_after_seconds=12.5
            )
            with mock.patch.object(client.rate_limiter, "try_acquire", return_value=decision), \
                 mock.patch.object(client, "_post") as post:
                records = client.pull_recent([])

            self.assertEqual(records, [])
            self.assertEqual(client.last_status, "rate_limited")
            post.assert_not_called()

    def test_manual_wait_mode_uses_blocking_shared_limiter(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(kuaisearch_client, "CACHEDIR", Path(directory)), \
                 mock.patch.object(kuaisearch_client, "load_token", return_value="test-token"):
                client = kuaisearch_client.KuaiSearchClient({
                    "cache_ttl_sec": 0, "wait_for_token": True, "wait_timeout_sec": 9,
                })
            decision = mock.Mock(acquired=True, reason="acquired", retry_after_seconds=0)
            with mock.patch.object(client.rate_limiter, "acquire", return_value=decision) as acquire, \
                 mock.patch.object(client.rate_limiter, "try_acquire") as try_acquire, \
                 mock.patch.object(client, "_post", return_value=([], "ok")):
                self.assertEqual(client.pull_recent([4]), [])
        acquire.assert_called_once_with(timeout_seconds=9.0)
        try_acquire.assert_not_called()

    def test_malformed_http_200_is_not_cached_as_a_valid_empty_result(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{}'

        with tempfile.TemporaryDirectory() as directory:
            client = self._client(directory)
            with mock.patch.object(
                kuaisearch_client._OPENER, "open", return_value=Response()
            ):
                records, status = client._post("subject/infos", {})
        self.assertEqual(records, [])
        self.assertEqual(status, "error")

    def test_kol_request_body_uses_weibo_key_accounts_and_exact_uid(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(kuaisearch_client, "CACHEDIR", Path(directory)), \
                 mock.patch.object(kuaisearch_client, "load_token", return_value="test-token"):
                client = kuaisearch_client.KuaiSearchClient({
                    "account_type": "3", "sites": ["新浪微博"],
                    "cache_ttl_sec": 0, "min_interval_sec": 65,
                })
            acquired = mock.Mock(acquired=True, reason="ok", retry_after_seconds=0)
            captured = {}

            def fake_post(endpoint, body):
                captured.update(body)
                return [], "ok"

            with mock.patch.object(client.rate_limiter, "try_acquire", return_value=acquired), \
                 mock.patch.object(client, "_post", side_effect=fake_post):
                client.pull_recent([4])

        self.assertEqual(captured["mediaType"], [4])
        self.assertEqual(captured["accountType"], "3")
        self.assertEqual(captured["sites"], ["新浪微博"])
        self.assertTrue(client._author_match(
            {"authorInfo": {"authorUserAccountNum": "1673580867"}}, "1673580867"
        ))
        self.assertFalse(client._author_match(
            {"content": "提到1673580867", "authorInfo": {"authorUserAccountNum": "other"}},
            "1673580867",
        ))

    def test_xueqiu_fallback_preserves_cached_stale_when_no_fresh_fallback(self):
        fetcher = voice_fetcher.XueqiuFetcher({"mode": "api"})
        with mock.patch.object(
            voice_fetcher, "_try_kuaisearch", return_value=([], "cached_stale", True)
        ), mock.patch.object(voice_fetcher, "_cookie", return_value=None), \
             mock.patch.object(voice_fetcher, "_get", side_effect=RuntimeError("offline")):
            records = fetcher.fetch({"account_handle": "123"})
        self.assertEqual(records, [])
        self.assertEqual(fetcher.last_status, "cached_stale")


if __name__ == "__main__":
    unittest.main()
