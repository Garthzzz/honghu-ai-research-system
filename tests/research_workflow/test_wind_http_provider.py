from __future__ import annotations

import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pandas as pd

from tools.pipeline import wind_http_provider as wind


class FakeWindClient:
    def __init__(self) -> None:
        self.offsets: list[int] = []
        self.wss_calls: list[tuple[str, str, str]] = []

    def tdaysoffset(self, offset: int, date_value: str, options: str):
        del date_value, options
        self.offsets.append(offset)
        target = "2026-07-22T00:00:00.000" if offset == 0 else "2026-07-21T00:00:00.000"
        return SimpleNamespace(ErrorCode=0, Data=[[target]], Times=[])

    def wss(self, ticker: str, fields: str, options: str):
        self.wss_calls.append((ticker, fields, options))
        row = {
            "CLOSE": 1308.0,
            "PE_TTM": 19.767933,
            "PE_EST_FTM": 18.351952,
            "PB_LF": 7.021799,
            "PS_TTM": 9.49835,
            "MKT_CAP_ARD": 1_635_106_734_108.0,
            "ROE_TTM": 30.5341,
            "ROA2_TTM": 35.8274,
            "EPS_TTM": 66.167765,
            "BPS_NEW": 186.2771,
            "EV2_TO_EBITDA": 13.797541,
            "PEG": float("nan"),
        }
        return SimpleNamespace(ErrorCode=0, dfData=pd.DataFrame([row], index=[ticker]))


class WindHttpProviderTests(unittest.TestCase):
    def test_large_wind_request_requires_explicit_permission(self) -> None:
        wind.assert_wind_request_scope(
            security_count=1,
            field_count=12,
            estimated_observations=12,
        )
        with self.assertRaises(wind.WindLargeRequestPermissionRequired):
            wind.assert_wind_request_scope(
                security_count=5_500,
                field_count=12,
                estimated_observations=66_000,
            )
        wind.assert_wind_request_scope(
            security_count=5_500,
            field_count=12,
            estimated_observations=66_000,
            large_request_approved=True,
        )

    def test_latest_completed_trade_date_is_conservative_before_close(self) -> None:
        client = FakeWindClient()
        shanghai = timezone(timedelta(hours=8))
        before_close = datetime(2026, 7, 22, 10, 0, tzinfo=shanghai)
        after_close = datetime(2026, 7, 22, 17, 0, tzinfo=shanghai)
        self.assertEqual(
            wind.latest_completed_trade_date(client=client, now=before_close),
            "2026-07-21",
        )
        self.assertEqual(
            wind.latest_completed_trade_date(client=client, now=after_close),
            "2026-07-22",
        )
        self.assertEqual(client.offsets, [-1, 0])

    def test_snapshot_converts_market_cap_and_keeps_field_contract(self) -> None:
        client = FakeWindClient()
        snapshot = wind.fetch_current_market_financial_snapshot(
            "600519.SH",
            fx={"USD": 7.0},
            trade_date="2026-07-21",
            client=client,
        )
        self.assertEqual(snapshot["source"], "wind")
        self.assertEqual(snapshot["symbol"], "600519.SH")
        self.assertEqual(snapshot["market_cap_cny"], 16351.07)
        self.assertEqual(snapshot["market_cap_usd"], 2335.87)
        self.assertAlmostEqual(snapshot["pe_ttm"], 19.767933)
        self.assertIsNone(snapshot["peg"])
        self.assertEqual(snapshot["field_as_of"]["bps_mrq"], "2026-07-21")
        self.assertIn("快照日而非底层报告期", snapshot["field_methods"]["bps_mrq"]["basis"])
        self.assertIn("tradeDate=20260721", client.wss_calls[0][2])


if __name__ == "__main__":
    unittest.main()
