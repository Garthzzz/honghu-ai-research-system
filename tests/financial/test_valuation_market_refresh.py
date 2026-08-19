from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from tools.pipeline.wind_http_provider import (
    a_share_trading_day_evidence,
    fetch_intraday_market_cap,
)


class FakeWind:
    def __init__(self, dates, trade_status="交易"):
        self.dates = dates
        self.trade_status = trade_status
        self.calendar_calls = []
        self.wss_calls = []

    def tdays(self, start, end, options):
        self.calendar_calls.append((start, end, options))
        return SimpleNamespace(ErrorCode=0, Data=[self.dates], Times=[])

    def wss(self, ticker, fields, options, **_kwargs):
        self.wss_calls.append((ticker, fields, options))
        return SimpleNamespace(
            ErrorCode=0,
            dfData=pd.DataFrame([{
                "MKT_CAP_ARD": 123_456_000_000.0,
                "TRADE_STATUS": self.trade_status,
            }]),
        )


def test_trade_day_requires_exact_sse_and_szse_calendar_matches() -> None:
    client = FakeWind(["2026-08-19"])
    evidence = a_share_trading_day_evidence("2026-08-19", client=client)
    assert evidence["is_trading_day"] is True
    assert evidence["weekday_heuristic_used"] is False
    assert {call[2] for call in client.calendar_calls} == {
        "TradingCalendar=SSE", "TradingCalendar=SZSE"
    }


def test_exchange_holiday_returns_non_trading_day() -> None:
    evidence = a_share_trading_day_evidence("2026-10-01", client=FakeWind([]))
    assert evidence["is_trading_day"] is False


def test_intraday_market_cap_uses_same_day_and_cny_yi_conversion() -> None:
    client = FakeWind(["2026-08-19"])
    value = fetch_intraday_market_cap(
        "601899.SH", trade_date="2026-08-19", client=client
    )
    assert value["market_cap_value"] == 1234.56
    assert value["currency"] == "CNY"
    assert value["trading_status"] == "trading"
    assert client.wss_calls == [
        ("601899.SH", "mkt_cap_ard,trade_status", "tradeDate=20260819;unit=1")
    ]


def test_intraday_market_cap_preserves_suspension_as_non_comparable_state() -> None:
    value = fetch_intraday_market_cap(
        "601899.SH", trade_date="2026-08-19", client=FakeWind([], "停牌")
    )
    assert value["trading_status"] == "suspended"
