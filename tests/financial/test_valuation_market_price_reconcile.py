from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from tools.financial import valuation_market_price_reconcile as target


BEIJING = ZoneInfo("Asia/Shanghai")


def test_reconcile_fetches_exact_six_and_uses_fill_only_writer(monkeypatch) -> None:
    calls = []

    class Repo:
        def committed_task_result(self, *_args):
            return None

        def a_share_members(self):
            return [
                {"security_id": index, "canonical_ticker": f"00000{index}.SZ"}
                for index in range(1, 7)
            ]

        def backfill_market_prices(self, trade_date, slot, observed_at, items, **kwargs):
            calls.append((trade_date, slot, observed_at, items, kwargs))
            return {"status": "completed", "reconciled_count": len(items)}

    monkeypatch.setenv("HONGHU_POSTGRES_RUNTIME_CONFIG", "runtime.json")
    monkeypatch.setattr(target, "_repository", lambda _path: Repo())
    monkeypatch.setattr(target, "load_wind_http_client", object)
    monkeypatch.setattr(
        target, "a_share_trading_day_evidence", lambda *_args, **_kwargs: {"is_trading_day": True}
    )
    monkeypatch.setattr(
        target,
        "fetch_intraday_market_quote",
        lambda ticker, **_kwargs: {
            "share_price_value": 10,
            "share_price_currency": "CNY",
            "share_price_unit": "元",
            "share_price_raw_field": "rt_last",
            "source_ref": f"Wind WSQ.rt_last+rt_mkt_cap+rt_susp_flag:{ticker}",
        },
    )
    result = target.run(now=datetime(2026, 8, 19, 17, 0, tzinfo=BEIJING))
    assert result["reconciled_count"] == 6
    assert calls[0][1] == "1510"
    assert len(calls[0][3]) == 6
    assert {item["security_id"] for item in calls[0][3]} == set(range(1, 7))
    assert all(len(item["share_price_raw_sha256"]) == 64 for item in calls[0][3])


def test_reconcile_replays_before_calling_wind(monkeypatch) -> None:
    class Repo:
        def committed_task_result(self, *_args):
            return {"status": "completed", "reconciled_count": 6}

    monkeypatch.setenv("HONGHU_POSTGRES_RUNTIME_CONFIG", "runtime.json")
    monkeypatch.setattr(target, "_repository", lambda _path: Repo())
    monkeypatch.setattr(
        target, "load_wind_http_client", lambda: (_ for _ in ()).throw(AssertionError("Wind called"))
    )
    result = target.run(now=datetime(2026, 8, 19, 17, 0, tzinfo=BEIJING))
    assert result == {"status": "completed", "reconciled_count": 6}
