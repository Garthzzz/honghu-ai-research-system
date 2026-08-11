from __future__ import annotations

import importlib
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tools.pipeline import market_snapshot_utils as snapshots
from tools.pipeline import refresh_company_financial_metrics as refresh
from tools.pipeline import tushare_provider


migration = importlib.import_module("tools.migrations.013_company_financial_metrics")


class _FixedDateTime(datetime):
    """Keep fixed-date financial fixtures deterministic across calendar days."""

    @classmethod
    def now(cls, tz=None):
        return cls(2026, 7, 15, 12, 0, 0, tzinfo=tz)


BASE_SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE industry (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE source (
    id INTEGER PRIMARY KEY,
    title TEXT,
    source_type TEXT,
    publisher TEXT,
    publish_date TEXT,
    quality_tier INTEGER,
    is_forward_looking INTEGER,
    value_layer TEXT,
    fetch_method TEXT,
    source_credibility TEXT,
    language TEXT,
    is_primary_source INTEGER,
    source_subtype TEXT,
    url TEXT,
    source_url TEXT,
    domain TEXT,
    fetch_timestamp TEXT,
    note TEXT
);
CREATE TABLE company (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    ticker TEXT,
    listing_status TEXT,
    pe_ttm REAL,
    pe_forward REAL,
    pb REAL,
    ps_ttm REAL,
    ev_ebitda REAL,
    peg REAL,
    roe REAL,
    roa REAL,
    market_cap_value REAL,
    market_cap_unit TEXT,
    market_cap_cny REAL,
    market_cap_usd REAL,
    valuation_as_of TEXT,
    valuation_source_id INTEGER REFERENCES source(id)
);
CREATE TABLE company_industry (
    company_id INTEGER NOT NULL REFERENCES company(id),
    industry_id INTEGER NOT NULL REFERENCES industry(id),
    PRIMARY KEY(company_id, industry_id)
);
CREATE TABLE industry_data_point (
    id INTEGER PRIMARY KEY,
    industry_id INTEGER NOT NULL REFERENCES industry(id),
    metric TEXT NOT NULL,
    period TEXT,
    value_num REAL,
    value_text TEXT,
    unit TEXT,
    is_forecast INTEGER DEFAULT 0,
    as_of_date TEXT,
    sentiment TEXT,
    source_id INTEGER NOT NULL REFERENCES source(id),
    source_excerpt TEXT,
    note TEXT,
    company_id INTEGER REFERENCES company(id),
    extraction_method TEXT,
    last_verified_at TEXT
);
"""


def _method(field: str, *, inferred: bool = False) -> dict[str, object]:
    result: dict[str, object] = {
        "extraction_method": "inferred" if inferred else "web_fetch",
        "api_fields": [f"api.{field}"],
    }
    if inferred:
        result["formula"] = f"formula for {field}"
    return result


class CompanyFinancialRefreshTest(unittest.TestCase):
    def setUp(self) -> None:
        self.datetime_patcher = mock.patch.object(refresh, "datetime", _FixedDateTime)
        self.datetime_patcher.start()
        self.addCleanup(self.datetime_patcher.stop)
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "research-test.db"
        self.financial_db_path = Path(self.tempdir.name) / "financial.db"
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(BASE_SCHEMA)
            conn.executemany(
                "INSERT INTO industry(id,name) VALUES(?,?)",
                [(1, "行业一"), (2, "行业二")],
            )
            conn.executemany(
                "INSERT INTO company(id,name,ticker,listing_status) VALUES(?,?,?,?)",
                [
                    (1, "Alpha", "000001.SZ", "a_share"),
                    (2, "阿尔法", "000001.SZ", "a_share"),
                    (3, "PrivateCo", None, "private"),
                    (4, "Orphan", "NVDA", "us"),
                    (5, "NVIDIA", "NVDA", "us"),
                    (6, "MissingTicker", None, "listed"),
                ],
            )
            conn.executemany(
                "INSERT INTO company_industry(company_id,industry_id) VALUES(?,?)",
                [(1, 1), (2, 2), (3, 1), (5, 2), (6, 1)],
            )
            migration.migrate(conn)
            conn.commit()
        finally:
            conn.close()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def fake_fetcher(*, ticker: str, yf_symbol: str, fx: object) -> dict[str, object]:
        del fx
        if ticker == "000001.SZ":
            values = {
                "pe_ttm": 10.0,
                "pb": 2.0,
                "ps_ttm": 3.0,
                "market_cap_cny": 100.0,
                "market_cap_usd": 14.29,
                "roe": 15.0,
                "roa": 7.0,
                "eps_ttm": 2.0,
                "bps_mrq": 10.0,
            }
            return {
                "source": "tushare",
                "symbol": "000001.SZ",
                "currency": "CNY",
                "per_share_currency": "CNY",
                "trade_date": "2026-07-14",
                "financial_metrics_as_of": "2026-03-31",
                "field_as_of": {
                    key: "2026-07-14" if key in refresh.MARKET_FIELDS else "2026-03-31"
                    for key in values
                },
                "field_methods": {
                    key: _method(key, inferred=key == "market_cap_usd")
                    for key in values
                },
                **values,
            }
        if yf_symbol != "NVDA":
            raise AssertionError(f"unexpected yfinance symbol: {yf_symbol}")
        values = {
            "pe_ttm": 25.0,
            "pe_forward": 22.0,
            "pb": 12.0,
            "roe": 40.0,
            "roa": 20.0,
            "eps_ttm": 4.0,
            "bps_mrq": 8.0,
        }
        return {
            "source": "yfinance",
            "symbol": yf_symbol,
            "currency": "USD",
            "per_share_currency": "USD",
            "trade_date": "2026-07-14",
            "financial_metrics_as_of": "2026-04-30",
            "field_as_of": {
                key: "2026-07-14" if key in refresh.MARKET_FIELDS else "2026-04-30"
                for key in values
            },
            "field_methods": {key: _method(key) for key in values},
            **values,
        }

    def build_fetch_manifest(self, fetcher=None) -> dict[str, object]:
        return refresh.build_refresh_manifest(
            self.db_path,
            fetch=True,
            fetcher=fetcher or self.fake_fetcher,
            fx_provider=lambda: {"USD": 7.0, "CNY": 1.0},
            generated_at="2026-07-15T02:00:00+00:00",
        )

    def test_migration_is_idempotent_and_keeps_rows(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            before = conn.execute("SELECT COUNT(*) FROM company").fetchone()[0]
            self.assertEqual(migration.migrate(conn), [])
            migration.verify(conn)
            after = conn.execute("SELECT COUNT(*) FROM company").fetchone()[0]
            self.assertEqual(before, after)
            fk_targets = {
                row[3]
                for row in conn.execute("PRAGMA foreign_key_list(company)")
                if row[2] == "source"
            }
            self.assertIn("financial_metrics_source_id", fk_targets)
        finally:
            conn.close()

    def test_dry_run_never_calls_provider_and_covers_every_company(self) -> None:
        provider = mock.Mock(side_effect=AssertionError("provider must not be called"))
        manifest = refresh.build_refresh_manifest(
            self.db_path,
            fetch=False,
            fetcher=provider,
            fx_provider=mock.Mock(side_effect=AssertionError("FX must not be called")),
            generated_at="2026-07-15T02:00:00+00:00",
        )
        self.assertEqual(manifest["mode"], "dry_run")
        self.assertEqual(manifest["summary"]["total_companies"], 6)
        provider.assert_not_called()

    def test_fetch_deduplicates_ticker_and_marks_all_blocked_rows(self) -> None:
        calls: list[str] = []

        def fetcher(**kwargs):
            calls.append(kwargs["ticker"])
            return self.fake_fetcher(**kwargs)

        manifest = self.build_fetch_manifest(fetcher)
        self.assertCountEqual(calls, ["000001.SZ", "NVDA"])
        by_id = {entry["company_id"]: entry for entry in manifest["companies"]}
        self.assertEqual(by_id[1]["status"], "success")
        self.assertEqual(by_id[2]["status"], "success")
        self.assertTrue(by_id[1]["writes_data_points"])
        self.assertFalse(by_id[2]["writes_data_points"])
        self.assertEqual(by_id[3]["status"], "not_applicable_nonpublic")
        self.assertEqual(by_id[4]["status"], "success")
        self.assertIn("missing_industry_relation", by_id[4]["reasons"])
        self.assertFalse(by_id[4]["writes_data_points"])
        self.assertTrue(by_id[5]["writes_data_points"])
        self.assertEqual(by_id[6]["status"], "blocked_no_ticker")

    def test_wind_primary_tushare_fill_keeps_field_level_provenance(self) -> None:
        def composite_fetcher(*, ticker: str, yf_symbol: str, fx: object):
            if ticker != "000001.SZ":
                return self.fake_fetcher(ticker=ticker, yf_symbol=yf_symbol, fx=fx)
            wind = {
                "source": "wind",
                "symbol": ticker,
                "currency": "CNY",
                "per_share_currency": "CNY",
                "trade_date": "2026-07-14",
                "financial_metrics_as_of": "2026-07-14",
                "pe_ttm": 10.0,
                "roe": 15.0,
                "field_as_of": {
                    "pe_ttm": "2026-07-14",
                    "roe": "2026-07-14",
                },
                "field_methods": {
                    "pe_ttm": _method("wind.pe_ttm"),
                    "roe": _method("wind.roe_ttm"),
                },
            }
            tushare = {
                "source": "tushare",
                "symbol": ticker,
                "currency": "CNY",
                "per_share_currency": "CNY",
                "trade_date": "2026-07-14",
                "financial_metrics_as_of": "2026-03-31",
                "roa": 7.0,
                "field_as_of": {"roa": "2026-03-31"},
                "field_methods": {"roa": _method("tushare.roa")},
            }
            return snapshots._merge_wind_tushare_snapshots(wind, tushare)

        manifest = self.build_fetch_manifest(composite_fetcher)
        entry = next(row for row in manifest["companies"] if row["company_id"] == 1)
        self.assertEqual(entry["snapshot"]["provider"], "wind")
        self.assertEqual(entry["snapshot"]["field_providers"]["pe_ttm"], "wind")
        self.assertEqual(entry["snapshot"]["field_providers"]["roa"], "tushare")

        refresh.apply_refresh_manifest(self.db_path, manifest)
        conn = sqlite3.connect(self.financial_db_path)
        try:
            provenance = dict(
                conn.execute(
                    """SELECT o.metric_name,o.provider
                         FROM financial_observation o
                         JOIN financial_security_company_link l ON l.security_id=o.security_id
                        WHERE l.research_company_id=1"""
                ).fetchall()
            )
            self.assertEqual(provenance["pe_ttm"], "wind")
            self.assertEqual(provenance["roe"], "wind")
            self.assertEqual(provenance["roa"], "tushare")
        finally:
            conn.close()

        conn = sqlite3.connect(self.db_path)
        try:
            aggregate_sources = conn.execute(
                """SELECT valuation.fetch_method, financial.fetch_method
                   FROM company AS c
                   LEFT JOIN source AS valuation ON valuation.id=c.valuation_source_id
                   LEFT JOIN source AS financial ON financial.id=c.financial_metrics_source_id
                   WHERE c.id=1"""
            ).fetchone()
            self.assertEqual(aggregate_sources, (None, None))
        finally:
            conn.close()

    def test_apply_writes_only_financial_db_and_one_fact_set_per_ticker(self) -> None:
        manifest = self.build_fetch_manifest()
        expected_dp_count = sum(
            len(entry["snapshot"]["values"])
            for entry in manifest["companies"]
            if entry.get("status") == "success" and entry.get("writes_data_points")
        )
        result = refresh.apply_refresh_manifest(self.db_path, manifest)
        self.assertEqual(result["company_updates"], 0)
        self.assertFalse(result["research_company_aggregate_written"])
        self.assertEqual(result["data_points_inserted"], 0)
        self.assertEqual(result["financial_observations_inserted"], expected_dp_count)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM company WHERE id IN (1,2,4,5) ORDER BY id"
            ).fetchall()
            self.assertTrue(all(row["eps_ttm"] is None for row in rows))
            self.assertTrue(all(row["bps_mrq"] is None for row in rows))
            self.assertTrue(all(row["financial_metrics_source_id"] is None for row in rows))
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM industry_data_point").fetchone()[0],
                0,
            )
        finally:
            conn.close()

        finance = sqlite3.connect(self.financial_db_path)
        try:
            self.assertEqual(
                finance.execute("SELECT COUNT(*) FROM financial_observation").fetchone()[0],
                expected_dp_count,
            )
            self.assertEqual(
                {row[0] for row in finance.execute("SELECT research_company_id FROM financial_security_company_link")},
                {1, 2, 4, 5},
            )
        finally:
            finance.close()

        second = refresh.apply_refresh_manifest(self.db_path, manifest)
        self.assertEqual(second["financial_observations_inserted"], 0)
        self.assertEqual(second["financial_observations_unchanged"], expected_dp_count * 2)

    def test_missing_fields_do_not_erase_existing_values_or_financial_date(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """UPDATE company
                   SET pe_ttm=99, roe=77, financial_metrics_as_of='2025-12-31'
                   WHERE id IN (1,2,5)"""
            )
            conn.commit()
        finally:
            conn.close()

        def pb_only(*, ticker: str, yf_symbol: str, fx: object) -> dict[str, object]:
            del ticker, fx
            return {
                "source": "yfinance" if yf_symbol == "NVDA" else "tushare",
                "symbol": yf_symbol,
                "trade_date": "2026-07-14",
                "pb": 3.5,
                "field_as_of": {"pb": "2026-07-14"},
                "field_methods": {"pb": _method("pb")},
            }

        manifest = self.build_fetch_manifest(pb_only)
        refresh.apply_refresh_manifest(
            self.db_path, manifest, write_legacy_company_aggregate=True
        )
        conn = sqlite3.connect(self.db_path)
        try:
            for row in conn.execute(
                "SELECT pe_ttm,pb,roe,financial_metrics_as_of FROM company WHERE id IN (1,2,5)"
            ):
                self.assertEqual(row, (99.0, 3.5, 77.0, "2025-12-31"))
        finally:
            conn.close()

    def test_writer_failure_rolls_back_company_and_source_updates(self) -> None:
        manifest = self.build_fetch_manifest()
        with mock.patch.object(
            refresh,
            "upsert_financial_observation",
            side_effect=RuntimeError("injected writer failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected writer failure"):
                refresh.apply_refresh_manifest(self.db_path, manifest)
        conn = sqlite3.connect(self.db_path)
        try:
            self.assertIsNone(
                conn.execute("SELECT pe_ttm FROM company WHERE id=1").fetchone()[0]
            )
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM source").fetchone()[0], 0)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM industry_data_point").fetchone()[0],
                0,
            )
        finally:
            conn.close()
        finance = sqlite3.connect(self.financial_db_path)
        try:
            self.assertEqual(finance.execute("SELECT COUNT(*) FROM financial_observation").fetchone()[0], 0)
            self.assertEqual(finance.execute("SELECT COUNT(*) FROM financial_source_snapshot").fetchone()[0], 0)
        finally:
            finance.close()

    def test_manifest_rejects_rehashed_industry_and_evidence_tampering(self) -> None:
        manifest = self.build_fetch_manifest()
        tampered = json.loads(json.dumps(manifest))
        company = next(row for row in tampered["companies"] if row["company_id"] == 1)
        company["canonical_industry_id"] = 2
        tampered["run_id"] = refresh._compute_run_id(tampered)
        with self.assertRaisesRegex(ValueError, "canonical_industry_id"):
            refresh.validate_manifest(tampered)

        tampered = json.loads(json.dumps(manifest))
        company = next(row for row in tampered["companies"] if row["company_id"] == 2)
        company["writes_data_points"] = True
        tampered["run_id"] = refresh._compute_run_id(tampered)
        with self.assertRaisesRegex(ValueError, "writes_data_points"):
            refresh.validate_manifest(tampered)

    def test_older_field_as_of_cannot_roll_back_current_value(self) -> None:
        refresh.apply_refresh_manifest(
            self.db_path,
            self.build_fetch_manifest(),
            write_legacy_company_aggregate=True,
        )

        def older_pb(*, ticker: str, yf_symbol: str, fx: object) -> dict[str, object]:
            del fx
            provider = "tushare" if ticker == "000001.SZ" else "yfinance"
            symbol = ticker if provider == "tushare" else yf_symbol
            return {
                "source": provider,
                "symbol": symbol,
                "trade_date": "2026-07-10",
                "pb": 1.0,
                "field_as_of": {"pb": "2026-07-10"},
                "field_methods": {"pb": _method("pb")},
            }

        older = self.build_fetch_manifest(older_pb)
        result = refresh.apply_refresh_manifest(
            self.db_path, older, write_legacy_company_aggregate=True
        )
        self.assertGreaterEqual(result["fields_skipped_older_as_of"], 4)
        conn = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(
                conn.execute("SELECT pb FROM company WHERE id=1").fetchone()[0],
                2.0,
            )
        finally:
            conn.close()

    def test_same_provider_same_period_revises_in_place_with_audit_trail(self) -> None:
        manifest = self.build_fetch_manifest()
        refresh.apply_refresh_manifest(self.db_path, manifest)
        conn = sqlite3.connect(self.financial_db_path)
        try:
            before = conn.execute("SELECT COUNT(*) FROM financial_observation").fetchone()[0]
        finally:
            conn.close()

        revised = json.loads(json.dumps(manifest))
        revised["generated_at"] = "2026-07-15T03:00:00+00:00"
        for company_id in (1, 2):
            entry = next(row for row in revised["companies"] if row["company_id"] == company_id)
            entry["snapshot"]["values"]["pb"] = 2.5
        revised["run_id"] = refresh._compute_run_id(revised)
        result = refresh.apply_refresh_manifest(self.db_path, revised)
        self.assertEqual(result["financial_observations_revised"], 1)
        conn = sqlite3.connect(self.financial_db_path)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM financial_observation").fetchone()[0], before)
            row = conn.execute(
                """SELECT o.value_num,r.previous_payload_json
                     FROM financial_observation o
                     JOIN financial_security_company_link l ON l.security_id=o.security_id
                     JOIN financial_observation_revision r ON r.observation_id=o.id
                    WHERE l.research_company_id=1 AND o.metric_name='pb'"""
            ).fetchone()
            self.assertEqual(row[0], 2.5)
            self.assertIn('"value_num":2.0', row[1])
        finally:
            conn.close()

    def test_rehashed_swapped_snapshots_are_rejected_by_security_identity(self) -> None:
        manifest = self.build_fetch_manifest()
        tampered = json.loads(json.dumps(manifest))
        first = next(row for row in tampered["companies"] if row["company_id"] == 1)
        second = next(row for row in tampered["companies"] if row["company_id"] == 5)
        first["snapshot"], second["snapshot"] = second["snapshot"], first["snapshot"]
        tampered["run_id"] = refresh._compute_run_id(tampered)
        with self.assertRaisesRegex(ValueError, "snapshot.symbol"):
            refresh.validate_manifest(tampered)

    def test_missing_future_and_stale_field_dates_fail_closed(self) -> None:
        cases = (
            ({}, "missing_or_invalid_as_of"),
            ({"pe_ttm": "2026-07-16"}, "future_as_of"),
            ({"pe_ttm": "2026-05-01"}, "stale_as_of_over_31d"),
        )
        for field_as_of, warning in cases:
            with self.subTest(warning=warning):
                clean = refresh.sanitize_snapshot(
                    {
                        "source": "yfinance",
                        "symbol": "NVDA",
                        "pe_ttm": 20,
                        "field_as_of": field_as_of,
                        "field_methods": {"pe_ttm": _method("pe_ttm")},
                    },
                    reference_date=datetime(2026, 7, 15).date(),
                )
                self.assertEqual(clean["status"], "no_data")
                self.assertEqual(clean["values"], {})
                self.assertIn(f"pe_ttm:{warning}", clean["warnings"])

    def test_explicit_nonpositive_pe_clears_legacy_value(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE company SET pe_ttm=-8, valuation_as_of='2026-06-30' WHERE id IN (1,2)"
            )
            conn.commit()
        finally:
            conn.close()

        def negative_pe(*, ticker: str, yf_symbol: str, fx: object) -> dict[str, object]:
            del fx
            provider = "tushare" if ticker == "000001.SZ" else "yfinance"
            symbol = ticker if provider == "tushare" else yf_symbol
            return {
                "source": provider,
                "symbol": symbol,
                "trade_date": "2026-07-14",
                "pe_ttm": -12.0,
                "pb": 2.0,
                "field_as_of": {"pe_ttm": "2026-07-14", "pb": "2026-07-14"},
                "field_methods": {"pe_ttm": _method("pe_ttm"), "pb": _method("pb")},
            }

        manifest = self.build_fetch_manifest(negative_pe)
        entry = next(row for row in manifest["companies"] if row["company_id"] == 1)
        self.assertEqual(entry["snapshot"]["field_statuses"]["pe_ttm"]["status"], "not_applicable")
        result = refresh.apply_refresh_manifest(
            self.db_path, manifest, write_legacy_company_aggregate=True
        )
        self.assertGreaterEqual(result["nonpositive_pe_cleared"], 2)
        conn = sqlite3.connect(self.db_path)
        try:
            self.assertIsNone(conn.execute("SELECT pe_ttm FROM company WHERE id=1").fetchone()[0])
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM industry_data_point WHERE metric='市盈率PE_TTM'"
                ).fetchone()[0],
                0,
            )
        finally:
            conn.close()


class ProviderMappingTest(unittest.TestCase):
    def test_strict_fx_fetch_does_not_silently_use_dated_fallbacks(self) -> None:
        class FailedTicker:
            def __init__(self, symbol: str):
                del symbol

            def get_info(self):
                raise RuntimeError("offline")

        fake_module = types.SimpleNamespace(Ticker=FailedTicker)
        with mock.patch.dict(sys.modules, {"yfinance": fake_module}):
            rates = snapshots.fetch_fx_rates(allow_fallback=False)
        self.assertEqual(rates, {"CNY": 1.0})

    def test_tushare_fields_and_ttm_derivation(self) -> None:
        with (
            mock.patch.object(snapshots, "tushare_available", return_value=True),
            mock.patch.object(
                snapshots,
                "fetch_daily_basic_latest",
                return_value={
                    "trade_date": "20260714",
                    "close": 20,
                    "pe_ttm": 10,
                    "pb": 2,
                    "ps_ttm": 3,
                    "total_mv": 1_000_000,
                },
            ),
            mock.patch.object(
                snapshots,
                "fetch_fina_indicator_latest",
                return_value={
                    "end_date": "20260331",
                    "eps": 0.5,
                    "bps": 8,
                    "roe": 12.3,
                    "roa": 5.4,
                },
            ),
            mock.patch.object(snapshots, "fetch_cashflow_latest", return_value={}),
        ):
            result = snapshots._from_tushare("000001.SZ", {"USD": 7.0})
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["trade_date"], "2026-07-14")
        self.assertEqual(result["financial_metrics_as_of"], "2026-03-31")
        self.assertEqual(result["eps_ttm"], 2.0)
        self.assertEqual(result["bps_mrq"], 8.0)
        self.assertEqual(result["field_as_of"]["eps_ttm"], "2026-07-14")
        self.assertEqual(
            result["field_methods"]["eps_ttm"]["extraction_method"],
            "inferred",
        )
        self.assertEqual(
            result["field_methods"]["eps_ttm"]["inputs"][
                "financial_statement_as_of"
            ],
            "2026-03-31",
        )

    def test_yfinance_falls_back_to_auditable_per_share_formulas(self) -> None:
        class EmptyFrame:
            index: list[object] = []

        class FakeTicker:
            def get_info(self):
                return {
                    "currency": "USD",
                    "currentPrice": 100,
                    "trailingPE": 20,
                    "priceToBook": 4,
                    "marketCap": 1_000_000_000,
                    "returnOnEquity": 0.2,
                    "returnOnAssets": 0.1,
                    "regularMarketTime": datetime(
                        2026, 7, 14, tzinfo=timezone.utc
                    ).timestamp(),
                    "mostRecentQuarter": datetime(
                        2026, 4, 30, tzinfo=timezone.utc
                    ).timestamp(),
                }

            def get_cashflow(self, freq: str):
                self.assert_frequency(freq)
                return EmptyFrame()

            def get_income_stmt(self, freq: str):
                self.assert_frequency(freq)
                return EmptyFrame()

            @staticmethod
            def assert_frequency(freq: str) -> None:
                if freq != "yearly":
                    raise AssertionError(freq)

        fake_module = types.SimpleNamespace(Ticker=lambda symbol: FakeTicker())
        with mock.patch.dict(sys.modules, {"yfinance": fake_module}):
            result = snapshots._from_yfinance("NVDA", {"CNY": 1.0})
        self.assertEqual(result["trade_date"], "2026-07-14")
        self.assertEqual(result["financial_metrics_as_of"], "2026-04-30")
        self.assertEqual(result["eps_ttm"], 5.0)
        self.assertEqual(result["bps_mrq"], 25.0)
        self.assertEqual(result["market_cap_usd"], 10.0)
        self.assertIsNone(result["market_cap_cny"])
        self.assertEqual(
            result["field_methods"]["bps_mrq"]["extraction_method"],
            "inferred",
        )

    def test_yfinance_without_real_market_or_report_timestamp_fails_closed(self) -> None:
        class EmptyFrame:
            index: list[object] = []

        class FakeTicker:
            def get_info(self):
                return {
                    "currency": "USD",
                    "currentPrice": 100,
                    "trailingPE": 20,
                    "priceToBook": 4,
                    "trailingEps": 5,
                    "bookValue": 25,
                    "marketCap": 1_000_000_000,
                    "returnOnEquity": 0.2,
                }

            def get_cashflow(self, freq: str):
                return EmptyFrame()

            def get_income_stmt(self, freq: str):
                return EmptyFrame()

        fake_module = types.SimpleNamespace(Ticker=lambda symbol: FakeTicker())
        with mock.patch.dict(sys.modules, {"yfinance": fake_module}):
            result = snapshots._from_yfinance("NVDA", {"USD": 7.0, "CNY": 1.0})
        self.assertEqual(result["trade_date"], "")
        self.assertEqual(result["financial_metrics_as_of"], "")
        for field in refresh.NUMERIC_FIELDS:
            self.assertIsNone(result[field], field)

    def test_yfinance_per_share_values_follow_quote_not_financial_currency(self) -> None:
        class EmptyFrame:
            index: list[object] = []

        class FakeTicker:
            def get_info(self):
                return {
                    "currency": "HKD",
                    "financialCurrency": "CNY",
                    "regularMarketTime": datetime(2026, 7, 14, tzinfo=timezone.utc).timestamp(),
                    "mostRecentQuarter": datetime(2026, 3, 31, tzinfo=timezone.utc).timestamp(),
                    "currentPrice": 472.60,
                    "trailingPE": 16.957302,
                    "priceToBook": 3.2726452,
                    "trailingEps": 27.87,
                    "bookValue": 144.40918,
                    "marketCap": 4_500_000_000_000,
                }

            def get_cashflow(self, freq: str):
                return EmptyFrame()

            def get_income_stmt(self, freq: str):
                return EmptyFrame()

        fake_module = types.SimpleNamespace(Ticker=lambda symbol: FakeTicker())
        with mock.patch.dict(sys.modules, {"yfinance": fake_module}):
            result = snapshots._from_yfinance(
                "0700.HK", {"HKD": 0.92, "USD": 7.0, "CNY": 1.0}
            )
        self.assertEqual(result["per_share_currency"], "HKD")
        self.assertEqual(result["financial_currency"], "CNY")
        self.assertAlmostEqual(result["pe_ttm"] * result["eps_ttm"], result["price"], delta=0.2)
        self.assertAlmostEqual(result["pb"] * result["bps_mrq"], result["price"], delta=1.0)

    def test_yfinance_cashflow_values_follow_financial_not_quote_currency(self) -> None:
        class CashflowFrame:
            index = ["CapitalExpenditure", "OperatingCashFlow"]
            columns: list[object] = []

            class Row:
                def __init__(self, value: float):
                    self.value = value

                def dropna(self):
                    return self

                @property
                def empty(self) -> bool:
                    return False

                @property
                def index(self):
                    return [datetime(2025, 12, 31)]

                def __getitem__(self, key):
                    if key in (0, datetime(2025, 12, 31)):
                        return self.value
                    raise KeyError(key)

                @property
                def iloc(self):
                    return self

            def __init__(self):
                self.rows = {
                    "CapitalExpenditure": self.Row(-4_088_000_000),
                    "OperatingCashFlow": self.Row(18_768_000_000),
                }

            @property
            def loc(self):
                return self

            def __getitem__(self, key):
                return self.rows[key]

        class EmptyIncomeFrame:
            index: list[object] = []

        class FakeTicker:
            def get_info(self):
                return {
                    "currency": "HKD",
                    "financialCurrency": "CNY",
                    "regularMarketTime": datetime(
                        2026, 7, 14, tzinfo=timezone.utc
                    ).timestamp(),
                    "mostRecentQuarter": datetime(
                        2025, 12, 31, tzinfo=timezone.utc
                    ).timestamp(),
                    "currentPrice": 40,
                    "trailingPE": 20,
                    "priceToBook": 2,
                    "marketCap": 100_000_000_000,
                    "operatingCashflow": 18_768_000_000,
                }

            def get_cashflow(self, freq: str):
                self.assert_frequency(freq)
                return CashflowFrame()

            def get_income_stmt(self, freq: str):
                self.assert_frequency(freq)
                return EmptyIncomeFrame()

            @staticmethod
            def assert_frequency(freq: str) -> None:
                if freq != "yearly":
                    raise AssertionError(freq)

        fake_module = types.SimpleNamespace(Ticker=lambda symbol: FakeTicker())
        with mock.patch.dict(sys.modules, {"yfinance": fake_module}):
            result = snapshots._from_yfinance(
                "0285.HK", {"HKD": 0.8631, "CNY": 1.0, "USD": 6.7768}
            )
        self.assertEqual(result["currency"], "HKD")
        self.assertEqual(result["financial_currency"], "CNY")
        self.assertEqual(result["operating_cash_flow"], 187.68)
        self.assertEqual(result["capex_value"], 40.88)

    def test_yfinance_minor_unit_quote_is_normalized_to_major_currency(self) -> None:
        class EmptyFrame:
            index: list[object] = []

        class FakeTicker:
            def get_info(self):
                return {
                    "currency": "GBp",
                    "financialCurrency": "GBP",
                    "regularMarketTime": datetime(2026, 7, 14, tzinfo=timezone.utc).timestamp(),
                    "lastFiscalYearEnd": datetime(2025, 12, 31, tzinfo=timezone.utc).timestamp(),
                    "currentPrice": 8974.0,
                    "trailingPE": 37.86498,
                    "priceToBook": 2.2895193,
                    "trailingEps": 2.37,
                    "bookValue": 39.196,
                    "marketCap": 70_000_000_000,
                }

            def get_cashflow(self, freq: str):
                return EmptyFrame()

            def get_income_stmt(self, freq: str):
                return EmptyFrame()

        fake_module = types.SimpleNamespace(Ticker=lambda symbol: FakeTicker())
        with mock.patch.dict(sys.modules, {"yfinance": fake_module}):
            result = snapshots._from_yfinance(
                "LSEG.L", {"GBP": 9.2, "USD": 7.0, "CNY": 1.0}
            )
        self.assertEqual(result["quote_currency_raw"], "GBp")
        self.assertEqual(result["currency"], "GBP")
        self.assertEqual(result["per_share_currency"], "GBP")
        self.assertAlmostEqual(result["price"], 89.74, places=2)
        self.assertAlmostEqual(result["pe_ttm"] * result["eps_ttm"], result["price"], places=1)
        self.assertAlmostEqual(result["pb"] * result["bps_mrq"], result["price"], places=1)

    def test_tushare_provider_requests_eps_and_bps(self) -> None:
        with mock.patch.object(tushare_provider, "call_tushare", return_value=[]) as call:
            tushare_provider.fetch_fina_indicator_latest("000001.SZ")
            tushare_provider.fetch_fina_indicator_rows("000001.SZ")
        for invocation in call.call_args_list:
            fields = invocation.args[2]
            self.assertIn("eps", fields.split(","))
            self.assertIn("bps", fields.split(","))

    def test_tushare_provider_requests_balance_and_employee_audit_fields(self) -> None:
        with mock.patch.object(tushare_provider, "call_tushare", return_value=[]) as call:
            tushare_provider.fetch_balancesheet_rows("000001.SZ", years=("2018", "2026"))
            tushare_provider.fetch_stock_company_latest("000001.SZ")
        balance_fields = call.call_args_list[0].args[2].split(",")
        for field in (
            "total_assets",
            "accounts_receiv",
            "inventories",
            "fix_assets",
            "cip",
            "contract_liab",
            "total_hldr_eqy_exc_min_int",
        ):
            self.assertIn(field, balance_fields)
        company_fields = call.call_args_list[1].args[2].split(",")
        self.assertIn("employees", company_fields)
        self.assertIn("main_business", company_fields)
        self.assertIn("business_scope", company_fields)


if __name__ == "__main__":
    unittest.main()
