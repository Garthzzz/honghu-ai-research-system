from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from tools.financial import valuation_market_refresh

from tools.pipeline.wind_http_provider import (
    a_share_trading_day_evidence,
    fetch_intraday_market_cap,
)


class FakeWind:
    def __init__(self, dates, suspension_flag=0):
        self.dates = dates
        self.suspension_flag = suspension_flag
        self.calendar_calls = []
        self.wsq_calls = []

    def tdays(self, start, end, options):
        self.calendar_calls.append((start, end, options))
        return SimpleNamespace(ErrorCode=0, Data=[self.dates], Times=[])

    def wsq(self, ticker, fields, **_kwargs):
        self.wsq_calls.append((ticker, fields))
        return SimpleNamespace(
            ErrorCode=0,
            dfData=pd.DataFrame([{
                "RT_MKT_CAP": 123_456_000_000.0,
                "RT_SUSP_FLAG": self.suspension_flag,
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
    assert value["raw_field"] == "rt_mkt_cap"
    assert client.wsq_calls == [("601899.SH", "rt_mkt_cap,rt_susp_flag")]


def test_intraday_market_cap_preserves_suspension_as_non_comparable_state() -> None:
    value = fetch_intraday_market_cap(
        "601899.SH", trade_date="2026-08-19", client=FakeWind([], 1)
    )
    assert value["trading_status"] == "suspended"


def test_refresh_passes_realtime_raw_field_into_persisted_batch(monkeypatch) -> None:
    class Repo:
        def committed_task_result(self, *_args):
            return None

        def a_share_members(self):
            return [
                {"member_id": idx, "security_id": idx, "canonical_ticker": ticker}
                for idx, ticker in enumerate(
                    ("601899.SH", "603993.SH", "000408.SZ", "000960.SZ", "600301.SH", "000426.SZ"),
                    start=1,
                )
            ]

        def record_market_batch(self, _date, _slot, _observed_at, _provider, _evidence, items, **_kwargs):
            assert {item["raw_field"] for item in items} == {"rt_mkt_cap"}
            return {"status": "completed", "observed_count": len(items)}

    monkeypatch.setenv("HONGHU_POSTGRES_RUNTIME_CONFIG", "ignored.json")
    monkeypatch.setattr(valuation_market_refresh, "_repository", lambda _path: Repo())
    monkeypatch.setattr(valuation_market_refresh, "load_wind_http_client", lambda: object())
    monkeypatch.setattr(
        valuation_market_refresh,
        "a_share_trading_day_evidence",
        lambda *_args, **_kwargs: {"is_trading_day": True},
    )
    monkeypatch.setattr(
        valuation_market_refresh,
        "fetch_intraday_market_cap",
        lambda *_args, **_kwargs: {
            "market_cap_value": 100,
            "currency": "CNY",
            "unit": "亿元",
            "raw_field": "rt_mkt_cap",
            "trading_status": "trading",
            "source_ref": "Wind WSQ.rt_mkt_cap+rt_susp_flag:test:2026-08-19",
        },
    )
    result = valuation_market_refresh.run(
        "1140", now=pd.Timestamp("2026-08-19T11:40:00+08:00").to_pydatetime()
    )
    assert result["observed_count"] == 6
