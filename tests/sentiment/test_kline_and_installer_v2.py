from __future__ import annotations

import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "sentiment"))

import stock_kline_fetch
import senti_fetch_guba
import eastmoney_guba
import retail_window_tick


class KlineUniverseTests(unittest.TestCase):
    def setUp(self):
        self.research = sqlite3.connect(":memory:")
        self.research.row_factory = sqlite3.Row
        self.research.execute(
            "CREATE TABLE company(id INTEGER PRIMARY KEY,name TEXT,ticker TEXT,listing_status TEXT)"
        )
        self.research.executemany(
            "INSERT INTO company VALUES(?,?,?,?)",
            (
                (1, "A", "000001.SZ", "a_share"),
                (2, "B", "NVDA", "us"),
                (3, "bad", "名称不是ticker", None),
                (4, "canonical", None, "a_share"),
                (5, "SHINKO", "6967.T", "delisted"),
                (598, "SHINKO stale status", "6967.T", "listed"),
            ),
        )
        self.senti = sqlite3.connect(":memory:")
        self.senti.row_factory = sqlite3.Row
        self.senti.executescript(
            """
            CREATE TABLE senti_company(id INTEGER PRIMARY KEY,name TEXT,ticker TEXT);
            CREATE TABLE company_id_redirect(old_company_id INTEGER PRIMARY KEY,canonical_company_id INTEGER);
            CREATE TABLE company_alias(id INTEGER PRIMARY KEY,company_id INTEGER,ticker TEXT,alias TEXT);
            INSERT INTO senti_company VALUES(900001,'redirected','000002.SZ');
            INSERT INTO senti_company VALUES(900002,'verified','000003.SZ');
            INSERT INTO company_id_redirect VALUES(900001,1);
            INSERT INTO company_alias VALUES(1,4,'688888.SH','canonical');
            """
        )

    def tearDown(self):
        self.research.close()
        self.senti.close()

    def test_dynamic_universe_and_redirect_filter(self):
        universe = stock_kline_fetch.load_universe(self.research, self.senti)
        self.assertEqual(
            {(item.company_id, item.ticker) for item in universe},
            {(1, "000001.SZ"), (2, "NVDA"), (4, "688888.SH"), (900002, "000003.SZ")},
        )
        selected = stock_kline_fetch.load_universe(
            self.research, self.senti, tickers={"NVDA"}
        )
        self.assertEqual([(item.company_id, item.ticker) for item in selected], [(2, "NVDA")])

    def test_guba_universe_includes_verified_local_and_excludes_redirect(self):
        research = mock.Mock()
        cursor = mock.Mock()
        cursor.fetchall.return_value = [
            {"id": 1, "name": "A", "ticker": "000001.SZ"},
        ]
        research.execute.return_value = cursor
        with mock.patch.object(
            senti_fetch_guba.common, "research_ro_conn", return_value=research
        ):
            universe = senti_fetch_guba.load_universe(self.senti)
        self.assertEqual(
            {(company_id, ticker) for company_id, _, ticker in universe},
            {(1, "000001.SZ"), (900002, "000003.SZ")},
        )

    def test_yfinance_exception_and_empty_are_explicit(self):
        with mock.patch.object(stock_kline_fetch.yf, "Ticker", side_effect=RuntimeError("boom")):
            rows, error = stock_kline_fetch.fetch_yfinance("NVDA", period="30d", interval="1d")
        self.assertEqual(rows, [])
        self.assertIn("RuntimeError:boom", error)

        empty_history = mock.Mock(empty=True)
        ticker = mock.Mock()
        ticker.history.return_value = empty_history
        with mock.patch.object(stock_kline_fetch.yf, "Ticker", return_value=ticker):
            rows, error = stock_kline_fetch.fetch_yfinance("NVDA", period="30d", interval="1d")
        self.assertEqual((rows, error), ([], "empty_result"))

    def test_yfinance_stale_nonempty_daily_is_retried_to_expected_session(self):
        def frame(day):
            return pd.DataFrame(
                {"Open": [10.0], "High": [11.0], "Low": [9.0],
                 "Close": [10.5], "Volume": [100.0]},
                index=pd.DatetimeIndex([day], tz="America/New_York"),
            )

        ticker = mock.Mock()
        ticker.history.side_effect = [frame("2026-07-13"), frame("2026-07-14")]
        with mock.patch.object(stock_kline_fetch.yf, "Ticker", return_value=ticker):
            rows, error = stock_kline_fetch.fetch_yfinance(
                "NVDA",
                period="30d",
                interval="1d",
                now=datetime(2026, 7, 15, 5, 0, tzinfo=ZoneInfo("America/New_York")),
            )
        self.assertEqual(error, "stale_latest_repaired:2026-07-14")
        self.assertEqual(rows[-1]["ts"], "2026-07-14")
        self.assertEqual(ticker.history.call_count, 2)
        self.assertEqual(ticker.history.call_args_list[1].kwargs["end"], "2026-07-15")
        self.assertTrue(ticker.history.call_args_list[1].kwargs["repair"])

    def test_yfinance_daily_rejects_missing_volume_suspension_fill(self):
        fake = pd.DataFrame(
            {"Open": [41750.0], "High": [41750.0], "Low": [41750.0],
             "Close": [41750.0], "Volume": [float("nan")]},
            index=pd.DatetimeIndex(["2026-07-14"], tz="Asia/Seoul"),
        )
        ticker = mock.Mock()
        ticker.history.return_value = fake
        with mock.patch.object(stock_kline_fetch.yf, "Ticker", return_value=ticker):
            rows, error = stock_kline_fetch.fetch_yfinance(
                "025560.KS", period="30d", interval="1d"
            )
        self.assertEqual(rows, [])
        self.assertEqual(error, "no_valid_ohlc")

    def test_yahoo_symbol_override_and_incremental_modes(self):
        self.assertEqual(stock_kline_fetch.yf_ticker("3324.TW"), "3324.TWO")
        self.assertEqual(stock_kline_fetch.yf_ticker("09888.HK"), "9888.HK")
        self.assertEqual(stock_kline_fetch.yf_ticker("00001.HK"), "0001.HK")
        with mock.patch.object(stock_kline_fetch, "is_a_share_ticker", return_value=False), mock.patch.object(
            stock_kline_fetch,
            "fetch_yfinance",
            return_value=([{"ts": "x"}], None),
        ) as fetch:
            result = stock_kline_fetch.fetch_ticker(
                "3324.TW", days=10, m60=40, mode="intraday"
            )
        self.assertFalse(result["request_daily"])
        self.assertEqual(result["errors"], [])
        fetch.assert_called_once_with("3324.TW", period="5d", interval="60m")

    def test_fetch_ticker_propagates_missing_frequencies(self):
        with mock.patch.object(stock_kline_fetch, "is_a_share_ticker", return_value=False), mock.patch.object(
            stock_kline_fetch,
            "fetch_yfinance",
            side_effect=[([], "daily down"), ([], "hourly down")],
        ):
            result = stock_kline_fetch.fetch_ticker("NVDA", days=60, m60=80)
        self.assertEqual(result["errors"], ["daily_missing", "60m_missing"])
        self.assertIn("yfinance_daily:daily down", result["warnings"])

    def test_a_share_hourly_batch_fallback_clears_false_failure(self):
        row = {"ts": "2026-07-15 10:30", "o": 1, "h": 2, "l": 1, "c": 2,
               "vol": 10, "amount": 20, "source": "tushare", "source_url": "official"}
        cache = {"920060.BJ": {"request_hourly": True, "hourly": [],
                                "errors": ["60m_missing"], "warnings": []}}
        with mock.patch.object(
            stock_kline_fetch, "fetch_realtime_hourly_tushare",
            return_value=({"920060.BJ": [row]}, None),
        ) as fallback:
            audit = stock_kline_fetch.apply_realtime_hourly_fallback(cache)
        fallback.assert_called_once_with(["920060.BJ"])
        self.assertEqual(audit, {"requested": 1, "filled": 1, "error": None})
        self.assertEqual(cache["920060.BJ"]["errors"], [])
        self.assertEqual(cache["920060.BJ"]["hourly"][0]["source"], "tushare")

    def test_intraday_a_share_skips_yahoo_before_batch_fallback(self):
        with mock.patch.object(
            stock_kline_fetch, "fetch_yfinance"
        ) as yahoo:
            result = stock_kline_fetch.fetch_ticker(
                "000001.SZ", days=60, m60=80, mode="intraday"
            )
        yahoo.assert_not_called()
        self.assertEqual(result["errors"], ["60m_missing"])
        self.assertFalse(
            any(str(item).startswith("yfinance_60m:") for item in result["warnings"])
        )


class InstallerSafetyTests(unittest.TestCase):
    def test_three_slot_tasks_share_one_recoverable_process_lock(self):
        with tempfile.TemporaryDirectory() as td:
            lock_path = Path(td) / "retail.lock"
            outcome = []
            with retail_window_tick.exclusive_tick_lock(lock_path):
                def contend():
                    try:
                        with retail_window_tick.exclusive_tick_lock(
                            lock_path, timeout_seconds=0.05, poll_seconds=0.01
                        ):
                            outcome.append("unexpected_acquire")
                    except TimeoutError:
                        outcome.append("queued")

                thread = threading.Thread(target=contend)
                thread.start()
                thread.join(timeout=1)
            self.assertEqual(outcome, ["queued"])
            with retail_window_tick.exclusive_tick_lock(
                lock_path, timeout_seconds=0.05, poll_seconds=0.01
            ):
                outcome.append("recovered")
            self.assertEqual(outcome[-1], "recovered")

    def test_installer_is_dry_run_by_default_and_has_three_weekday_slots(self):
        text = (ROOT / "tools" / "sentiment" / "install_retail_window_tasks.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("[switch]$Apply", text)
        self.assertIn("if (-not $Apply)", text)
        for value in ("10:00", "10:30", "14:00", "17:00", "Monday", "Friday"):
            self.assertIn(value, text)
        self.assertIn("IndustryDemo_EventIngest", text)
        self.assertIn("IndustryDemo_SentimentRetention", text)
        self.assertIn('Plan IndustryDemo_EventIngest: Monday-Friday', text)
        self.assertIn(
            'Plan IndustryDemo_SentimentRetention: Monday-Friday',
            text,
        )
        self.assertIn(
            "-m tools.maintenance.sentiment_retention --apply",
            text,
        )
        self.assertNotIn('New-ScheduledTaskTrigger `\n        -Daily', text)
        self.assertNotIn('RepetitionInterval (New-TimeSpan -Hours 1)', text)
        self.assertIn('--max-llm 600 --per-stock 30', text)
        self.assertIn('$EventPythonExe', text)
        self.assertNotIn('$KeepLegacyTask', text)
        self.assertIn('Unregister-ScheduledTask -TaskName "IndustryDemo_SentiTick"', text)
        self.assertIn("-ExecutionTimeLimit (New-TimeSpan -Hours 8)", text)
        self.assertIn("-AllowStartIfOnBatteries", text)
        self.assertIn("-DontStopIfGoingOnBatteries", text)
        self.assertEqual(text.count("-WorkingDirectory $Root"), 3)
        self.assertLess(
            text.index('Register-ScheduledTask `\n        -TaskName "IndustryDemo_EventIngest"'),
            text.index('Unregister-ScheduledTask -TaskName "IndustryDemo_SentiTick"'),
        )

    def test_production_guba_depth_comes_from_config_and_timeouts_cover_full_universe(self):
        self.assertEqual(retail_window_tick.DEFAULT_GUBA_PAGES, 128)
        window = retail_window_tick.senti3.market_window(
            retail_window_tick.date(2026, 7, 15), "preopen"
        )
        commands = {item.source: item for item in retail_window_tick.build_commands(window)}
        self.assertEqual(commands["guba"].args[-1], "128")
        self.assertGreaterEqual(commands["guba"].timeout, 10800)
        self.assertGreaterEqual(commands["xinghan"].timeout, 6 * 60 * 60)
        self.assertGreaterEqual(retail_window_tick.TICK_LOCK_TIMEOUT_SECONDS, 8 * 60 * 60)
        self.assertGreaterEqual(commands["score"].timeout, 7200)
        forced = {
            item.source: item
            for item in retail_window_tick.build_commands(window, force=True)
        }
        self.assertIn("--force", forced["xinghan"].args)


class GubaBrowserLaunchTests(unittest.TestCase):
    def test_windows_prefers_installed_chrome_channel(self):
        browser = object()
        playwright = mock.Mock()
        playwright.chromium.launch.return_value = browser
        with mock.patch.object(eastmoney_guba.sys, "platform", "win32"):
            self.assertIs(eastmoney_guba._launch_browser(playwright), browser)
        kwargs = playwright.chromium.launch.call_args.kwargs
        self.assertEqual(kwargs["channel"], "chrome")
        self.assertTrue(kwargs["headless"])

    def test_browser_launch_falls_back_to_edge(self):
        browser = object()
        playwright = mock.Mock()
        playwright.chromium.launch.side_effect = [RuntimeError("chrome missing"), browser]
        with mock.patch.object(eastmoney_guba.sys, "platform", "win32"):
            self.assertIs(eastmoney_guba._launch_browser(playwright), browser)
        channels = [call.kwargs.get("channel") for call in playwright.chromium.launch.call_args_list]
        self.assertEqual(channels, ["chrome", "msedge"])


if __name__ == "__main__":
    unittest.main()
