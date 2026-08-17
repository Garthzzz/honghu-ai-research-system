from __future__ import annotations

import sys
import unittest
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "sentiment"))

import retail_window_tick
import senti3
import senti_fetch_xinghan


class MarketWindowTests(unittest.TestCase):
    def dt(self, value: str) -> datetime:
        return datetime.fromisoformat(value).replace(tzinfo=senti3.TZ)

    def test_monday_preopen_is_split_and_excludes_weekend(self):
        window = senti3.market_window(date(2026, 7, 20), "preopen")
        self.assertEqual(window.window_id, "2026-07-20:preopen")
        self.assertEqual(window.window_start, self.dt("2026-07-17T16:00"))
        self.assertEqual(window.window_end, self.dt("2026-07-20T09:30"))
        self.assertEqual(
            window.segments,
            (
                (self.dt("2026-07-17T16:00"), self.dt("2026-07-18T00:00")),
                (self.dt("2026-07-20T00:00"), self.dt("2026-07-20T09:30")),
            ),
        )
        self.assertEqual(window.effective_minutes, 1050)

    def test_exact_half_open_boundaries(self):
        cases = {
            "2026-07-17T15:59": "2026-07-17:afternoon",
            "2026-07-17T16:00": "2026-07-20:preopen",
            "2026-07-20T09:29": "2026-07-20:preopen",
            "2026-07-20T09:30": "2026-07-20:morning",
            "2026-07-20T13:00": "2026-07-20:afternoon",
            "2026-07-20T16:00": "2026-07-21:preopen",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(senti3.market_window_for_timestamp(self.dt(value)).window_id, expected)

    def test_weekend_and_holiday_are_not_mapped(self):
        self.assertIsNone(senti3.market_window_for_timestamp(self.dt("2026-07-18T10:00")))
        trading_days = {date(2026, 7, 17), date(2026, 7, 21)}
        self.assertIsNone(
            senti3.market_window_for_timestamp(self.dt("2026-07-20T10:00"), trading_days)
        )
        friday_close = senti3.market_window_for_timestamp(
            self.dt("2026-07-17T16:00"), trading_days
        )
        self.assertEqual(friday_close.window_id, "2026-07-21:preopen")

    def test_naive_datetime_is_rejected(self):
        with self.assertRaises(ValueError):
            senti3.market_window_for_timestamp(datetime(2026, 7, 20, 10, 0))

    def test_xinghan_range_split_never_requests_weekend(self):
        segments = senti_fetch_xinghan.weekday_segments(
            self.dt("2026-07-17T16:00"), self.dt("2026-07-20T09:30")
        )
        self.assertEqual(
            segments,
            [
                (self.dt("2026-07-17T16:00"), self.dt("2026-07-18T00:00")),
                (self.dt("2026-07-20T00:00"), self.dt("2026-07-20T09:30")),
            ],
        )

    def test_slot_resolution_and_commands(self):
        window = retail_window_tick.resolve_window(
            now=self.dt("2026-07-20T14:00"), slot="morning"
        )
        self.assertEqual(window.window_id, "2026-07-20:morning")
        commands = retail_window_tick.build_commands(window, guba_pages=2, score_max=0)
        self.assertEqual([item.source for item in commands], ["guba", "xinghan", "score", "kline"])
        self.assertIn("2026-07-20:morning", commands[0].args)
        self.assertIn("--require-complete", commands[2].args)
        self.assertEqual(commands[3].args[:2], ("--mode", "intraday"))
        preopen = retail_window_tick.build_commands(
            senti3.market_window(date(2026, 7, 20), "preopen")
        )
        afternoon = retail_window_tick.build_commands(
            senti3.market_window(date(2026, 7, 20), "afternoon")
        )
        self.assertEqual(preopen[3].args[:2], ("--mode", "full"))
        self.assertEqual(afternoon[3].args[:2], ("--mode", "close"))
        self.assertEqual(
            preopen[3].args[-4:],
            ("--session-date", "2026-07-20", "--slot", "preopen"),
        )
        self.assertEqual(
            afternoon[3].args[-4:],
            ("--session-date", "2026-07-20", "--slot", "afternoon"),
        )
        self.assertIsNone(
            retail_window_tick.resolve_window(
                now=self.dt("2026-07-18T14:00"), slot="morning"
            )
        )

    def test_live_auto_backfill_policy_is_bounded(self):
        start, max_days, max_windows = retail_window_tick.auto_backfill_policy()
        self.assertEqual(start, date(2026, 7, 15))
        self.assertEqual(max_days, 3)
        self.assertEqual(max_windows, 3)


if __name__ == "__main__":
    unittest.main()
