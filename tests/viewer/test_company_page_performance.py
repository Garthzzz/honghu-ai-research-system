from __future__ import annotations

import sqlite3
from unittest import mock

from tools.financial import read_models
from tools.viewer import app as viewer


def _financial_fixture(path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE financial_security (
            id INTEGER PRIMARY KEY,
            research_company_id INTEGER,
            ticker TEXT,
            canonical_name TEXT,
            market TEXT
        );
        CREATE TABLE financial_security_company_link (
            security_id INTEGER,
            research_company_id INTEGER
        );
        CREATE TABLE financial_source_snapshot (
            id INTEGER PRIMARY KEY,
            title TEXT,
            publisher TEXT,
            source_channel TEXT,
            source_ref TEXT
        );
        CREATE TABLE financial_observation (
            id INTEGER PRIMARY KEY,
            security_id INTEGER,
            metric_name TEXT,
            fact_type TEXT,
            value_num REAL,
            value_text TEXT,
            unit TEXT,
            period_end TEXT,
            as_of_date TEXT,
            fiscal_year INTEGER,
            fiscal_period TEXT,
            quality_status TEXT,
            provider TEXT,
            raw_feature_name TEXT,
            scenario_name TEXT,
            source_snapshot_id INTEGER,
            formula TEXT
        );
        INSERT INTO financial_security VALUES
            (1, 101, '000001.SZ', '甲公司', 'A股'),
            (2, 102, '000002.SZ', '乙公司', 'A股');
        INSERT INTO financial_source_snapshot VALUES
            (1, 'Wind快照', 'Wind', 'api', 'wind://snapshot');
        INSERT INTO financial_observation VALUES
            (1, 1, 'pe_ttm', 'market', 12.5, NULL, '倍', NULL,
             '2026-08-18', NULL, NULL, 'active', 'wind', 'wss.pe_ttm',
             'reported', 1, NULL),
            (2, 1, 'revenue', 'actual', 100.0, NULL, '亿元', '2025-12-31',
             '2026-03-31', 2025, 'FY', 'active', 'wind', 'wss.revenue',
             'reported', 1, NULL),
            (3, 1, 'eps', 'consensus', 2.2, NULL, '元/股', NULL,
             '2026-08-18', 2026, 'FY1', 'active', 'wind', 'consensus.eps',
             'base', 1, NULL),
            (4, 2, 'pb', 'market', 1.8, NULL, '倍', NULL,
             '2026-08-18', NULL, NULL, 'active', 'wind', 'wss.pb_lf',
             'reported', 1, NULL);
        """
    )
    connection.commit()
    connection.close()


def test_company_page_summary_batch_opens_financial_domain_once(tmp_path) -> None:
    database = tmp_path / "financial.db"
    _financial_fixture(database)
    original_connect = read_models.connect
    calls = []

    def counted_connect(*args, **kwargs):
        calls.append((args, kwargs))
        return original_connect(*args, **kwargs)

    with mock.patch.object(read_models, "connect", side_effect=counted_connect):
        result = read_models.company_page_summaries_batch(
            [101, 102], db_path=database,
        )

    assert len(calls) == 1
    assert result[101]["security"]["ticker"] == "000001.SZ"
    assert result[101]["current_metrics"]["pe_ttm"]["value_num"] == 12.5
    assert result[101]["current_metrics"]["pe_ttm"]["source_title"] == "Wind快照"
    assert result[101]["historical_table"][0]["metrics"]["revenue"]["value"] == 100.0
    assert result[101]["forecast_table"][0]["consensus"]["eps"]["value"] == 2.2
    assert result[102]["current_metrics"]["pb"]["value_num"] == 1.8


def test_industry_overlay_uses_one_batch_and_preserves_ticker_guard() -> None:
    rows = [
        {
            "company_id": 101,
            "ticker": "000001.SZ",
            # research.db keeps legacy compatibility aggregates.  A stale but
            # non-null value must not beat the financial_data authority.
            "pe_ttm": 99.0,
            "pb": 8.8,
            "peg": 9.9,
            "gross_margin": 88.0,
            "net_margin": 77.0,
            "valuation_as_of": "2020-01-01",
            "financial_metrics_as_of": "2020-12-31",
            "financials_as_of": "2020-12-31",
            "ocf_unit": "旧单位",
            "per_share_currency": "USD",
            "revenue_series": '[{"period":"2020","value":999}]',
            "net_income_series": '[{"period":"2020","value":888}]',
            "forecast_revenue_year1": 999.0,
            "forecast_eps_year1": 99.0,
        },
        {"company_id": 102, "ticker": "000002.SZ", "pb": 2.2},
        {"company_id": 103, "ticker": "", "pe_ttm": 77.0},
        {"company_id": 104, "ticker": "000004.SZ", "pe_ttm": 66.0},
        {
            "company_id": 204,
            "ticker": "000836.SZ",
            "pe_ttm": 5.0,
            "pb": 1.0,
        },
    ]
    summaries = {
        101: {
            "security": {"ticker": "000001.SZ"},
            "current_metrics": {
                "pe_ttm": {
                    "value_num": 12.5,
                    "provider_label": "Wind",
                    "source_title": "Wind快照",
                    "as_of_date": "2026-08-18",
                    "unit": "倍",
                }
            },
            "historical_table": [{
                "period": "2025",
                "period_end": "2025-12-31",
                "metrics": {
                    "gross_margin": {
                        "value": 30.0,
                        "provider": "wind",
                        "source_title": "Wind年报快照",
                        "as_of_date": "2026-04-30",
                    }
                },
            }],
            "forecast_table": [{
                "horizon": "FY1",
                "consensus": {
                    "revenue": {
                        "value": 120.0,
                        "unit": "亿元人民币",
                        "provider": "wind",
                        "source_title": "Wind一致预期",
                        "as_of_date": "2026-08-18",
                    },
                    "eps": {
                        "value": 2.2,
                        "unit": "CNY/股",
                        "provider": "wind",
                        "source_title": "Wind一致预期",
                        "as_of_date": "2026-08-18",
                    },
                },
            }],
        },
        102: {
            # A mismatched canonical security must never overlay this row.
            "security": {"ticker": "999999.SZ"},
            "current_metrics": {
                "pb": {"value_num": 1.8, "provider_label": "Wind"}
            },
            "historical_table": [],
            "forecast_table": [],
        },
        103: {
            "security": {"ticker": "000003.SZ"},
            "current_metrics": {
                "pe_ttm": {"value_num": 13.0, "provider_label": "Wind"}
            },
            "historical_table": [],
            "forecast_table": [],
        },
        104: {
            "security": {"ticker": ""},
            "current_metrics": {
                "pe_ttm": {"value_num": 14.0, "provider_label": "Wind"}
            },
            "historical_table": [],
            "forecast_table": [],
        },
        204: {
            "security": {"ticker": "000836.SZ"},
            # Explicitly unavailable observations are omitted by the current view.
            # Accepting the authority must still suppress legacy multiples.
            "current_metrics": {},
            "historical_table": [],
            "forecast_table": [],
        },
    }
    with mock.patch.object(
        viewer,
        "financial_company_page_summaries_batch",
        return_value=summaries,
    ) as batch, mock.patch.object(
        viewer,
        "financial_company_bundle",
        side_effect=AssertionError("industry pages must not load per-company bundles"),
    ):
        result = viewer._overlay_industry_financial_rows(
            rows, include_profile_series=True,
        )

    batch.assert_called_once()
    assert rows[0]["pe_ttm"] == 12.5
    assert rows[0]["pb"] is None
    assert rows[0]["peg"] is None
    assert rows[0]["gross_margin"] == 30.0
    assert rows[0]["net_margin"] is None
    assert rows[0]["valuation_as_of"] == "2026-08-18"
    assert rows[0]["financial_metrics_as_of"] is None
    assert rows[0]["financials_as_of"] == "2026-04-30"
    assert rows[0]["ocf_unit"] is None
    assert rows[0]["per_share_currency"] is None
    assert "2020" not in rows[0]["revenue_series"]
    assert rows[0]["net_income_series"] == "[]"
    assert rows[0]["forecast_revenue_year1"] == 120.0
    assert rows[0]["forecast_eps_year1"] == 2.2
    assert rows[0]["forecast_as_of_date"] == "2026-08-18"
    assert rows[0]["_provider_by_metric"]["pe_ttm"] == "Wind"
    assert rows[1]["pb"] == 2.2
    assert rows[2]["pe_ttm"] == 77.0
    assert rows[3]["pe_ttm"] == 66.0
    assert rows[4]["pe_ttm"] is None
    assert rows[4]["pb"] is None
    assert rows[4]["peg"] is None
    assert rows[4]["financials_as_of"] is None
    assert rows[4]["ocf_unit"] is None
    assert rows[4]["per_share_currency"] is None
    assert rows[4]["revenue_series"] == "[]"
    assert rows[4]["net_income_series"] == "[]"
    assert set(result) == {101, 204}


def test_industry_overlay_rebuilds_canonical_iso_per_share_currencies() -> None:
    expected_by_unit = {
        "CNY/股": "CNY",
        "JPY/股": "JPY",
        "USD/股": "USD",
        "EUR/股": "EUR",
    }
    for offset, (unit, expected) in enumerate(expected_by_unit.items(), start=1):
        company_id = 700 + offset
        ticker = f"TEST{offset}"
        rows = [{
            "company_id": company_id,
            "ticker": ticker,
            "per_share_currency": "LEGACY",
        }]
        summaries = {
            company_id: {
                "security": {"ticker": ticker},
                "current_metrics": {
                    "eps_ttm": {
                        "value_num": 1.0,
                        "unit": unit,
                        "provider_label": "Wind",
                        "as_of_date": "2026-08-18",
                    }
                },
                "historical_table": [],
                "forecast_table": [],
            }
        }
        with mock.patch.object(
            viewer,
            "financial_company_page_summaries_batch",
            return_value=summaries,
        ):
            viewer._overlay_industry_financial_rows(rows)
        assert rows[0]["per_share_currency"] == expected


def test_request_queries_reuse_and_teardown_domain_connections() -> None:
    research = sqlite3.connect(":memory:")
    research.row_factory = sqlite3.Row
    research.execute("CREATE TABLE sample (id INTEGER)")
    research.executemany("INSERT INTO sample VALUES (?)", [(1,), (2,)])
    sentiment = sqlite3.connect(":memory:")
    sentiment.row_factory = sqlite3.Row
    sentiment.execute("CREATE TABLE sample (id INTEGER)")
    sentiment.executemany("INSERT INTO sample VALUES (?)", [(3,), (4,)])

    with mock.patch.object(viewer, "get_db", return_value=research) as research_open, \
         mock.patch.object(viewer, "senti_conn", return_value=sentiment) as sentiment_open:
        with viewer.app.test_request_context("/company/101"):
            assert viewer.query_one("SELECT id FROM sample ORDER BY id LIMIT 1")["id"] == 1
            assert len(viewer.query_all("SELECT id FROM sample")) == 2
            assert viewer.senti_one("SELECT id FROM sample ORDER BY id LIMIT 1")["id"] == 3
            assert len(viewer.senti_all("SELECT id FROM sample")) == 2

        research_open.assert_called_once()
        sentiment_open.assert_called_once()

    for connection in (research, sentiment):
        try:
            connection.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            pass
        else:
            raise AssertionError("request teardown must close the read connection")
