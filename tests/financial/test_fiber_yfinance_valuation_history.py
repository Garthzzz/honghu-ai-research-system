from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3
import tempfile

from tools.financial.db import connect, initialize_database
from tools.financial.fiber_yfinance_valuation_history import (
    _available_from,
    apply,
    _load_verified,
    _observations,
)
from tools.financial.repository import upsert_observation, upsert_security


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "config" / "financial" / "fiber_yfinance_valuation_history_v1.json"


def test_frozen_fiber_history_has_exact_identity_and_at_least_twelve_months() -> None:
    payload = _load_verified(ARTIFACT)
    assert payload["contentSha256"] == "47257da1e0b5061e07a1dfffc1beed03d03d3638552051cec6a37714489d8e25"
    companies = {int(item["company_id"]): item for item in payload["companies"]}
    assert {key: value["ticker"] for key, value in companies.items()} == {
        59: "5802.T", 203: "GLW", 704: "PRY.MI",
    }
    for company in companies.values():
        assert company["pbObservations"] >= 12
        assert company["positivePeObservations"] >= 12
        for item in company["observations"]:
            assert item["financialAvailableFrom"] <= item["date"]
            assert item["close"] > 0 and item["pbApprox"] > 0


def test_annual_financial_anchor_never_looks_ahead() -> None:
    assert _available_from(date(2025, 3, 31)).isoformat() == "2025-05-30"
    assert _available_from(date(2025, 12, 31)).isoformat() == "2026-04-30"
    rows = _observations(
        [{"date": "2026-04-29", "close": 20}, {"date": "2026-04-30", "close": 20}],
        [{
            "periodEnd": "2025-12-31", "availableFrom": "2026-04-30",
            "eps": 2, "bps": 10,
        }],
    )
    assert len(rows) == 1
    assert rows[0]["peAnnualApprox"] == 10
    assert rows[0]["pbApprox"] == 2


def test_frozen_history_applies_idempotently_to_financial_database() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "financial.db"
        initialize_database(db_path)
        connection = connect(db_path)
        try:
            for company_id, name, ticker, currency in (
                (59, "住友电气工业", "5802.T", "JPY"),
                (203, "康宁", "GLW", "USD"),
                (704, "Prysmian", "PRY.MI", "EUR"),
            ):
                upsert_security(
                    connection,
                    research_company_id=company_id,
                    canonical_name=name,
                    ticker=ticker,
                    market="海外",
                    listing_status="上市",
                    reporting_currency=currency,
                )
            connection.commit()
        finally:
            connection.close()
        first = apply(ARTIFACT, db_path=db_path)
        second = apply(ARTIFACT, db_path=db_path)
        assert first["counts"]["inserted"] > 300
        assert second["counts"]["unchanged"] == first["counts"]["inserted"]
        assert all(min(values.values()) >= 12 for values in second["readback"].values())


def test_observation_upsert_supports_production_projection_without_unique_index() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE financial_observation(
          id INTEGER PRIMARY KEY, observation_key TEXT, security_id INTEGER,
          metric_name TEXT, value_num REAL, value_text TEXT, unit TEXT,
          currency TEXT, period_start TEXT, period_end TEXT, fiscal_year INTEGER,
          fiscal_period TEXT, frequency TEXT, fact_type TEXT, as_of_date TEXT,
          announcement_date TEXT, provider TEXT, raw_feature_name TEXT,
          source_snapshot_id INTEGER, formula TEXT, input_refs_json TEXT,
          quality_status TEXT, scenario_name TEXT, model_run_id INTEGER,
          legacy_ref TEXT, updated_at TEXT
        );
        CREATE TABLE financial_observation_revision(
          id INTEGER PRIMARY KEY, observation_id INTEGER,
          previous_payload_json TEXT, replacement_payload_json TEXT,
          revision_reason TEXT
        );
        """
    )
    base = dict(
        security_id=1, metric_name="pb", value_num=2.0, unit="倍",
        frequency="monthly", fact_type="market", as_of_date="2026-07-31",
        provider="yfinance", raw_feature_name="derived.pb",
        quality_status="limited", scenario_name="reported",
    )
    _, inserted = upsert_observation(connection, return_status=True, **base)
    _, unchanged = upsert_observation(connection, return_status=True, **base)
    _, revised = upsert_observation(
        connection, return_status=True, **{**base, "value_num": 2.5}
    )
    assert (inserted, unchanged, revised) == ("inserted", "unchanged", "revised")
    assert connection.execute("SELECT count(*) FROM financial_observation").fetchone()[0] == 1
    assert connection.execute("SELECT value_num FROM financial_observation").fetchone()[0] == 2.5
    assert connection.execute("SELECT count(*) FROM financial_observation_revision").fetchone()[0] == 1
