from __future__ import annotations

from tools.pipeline.copper_peer_financial_snapshot import A_TICKERS, HK_TICKERS
from tools.pipeline.extend_copper_valuation_peers import PEERS


def test_copper_peer_scope_has_only_requested_three_value_chain_groups() -> None:
    assert {row["category"] for row in PEERS} == {
        "资源矿山",
        "矿冶一体化",
        "铜加工材料",
    }
    assert len(PEERS) == 8
    assert all("铜箔" not in row["category"] for row in PEERS)
    assert {row["ticker"] for row in PEERS} == set(A_TICKERS) | set(HK_TICKERS)
    assert sum(row["category"] == "铜加工材料" for row in PEERS) == 3


def test_copper_peer_wind_scope_stays_below_permission_threshold() -> None:
    assert len(A_TICKERS) == 7
    assert len(A_TICKERS) <= 10
    assert HK_TICKERS == ("1258.HK",)
