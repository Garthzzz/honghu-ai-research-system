from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.financial.valuation_ai_refresh import _candidate, _review_existing_version
from tools.financial.valuation_tracker import (
    WORKBOOK_SHA256,
    ValuationTrackerRepository,
    load_seed,
)
from tools.financial.valuation_tracker_seed import REVIEWED_WORKBOOK_SEED_SHA256
from tools.financial.valuation_tracker_history_seed import (
    REVIEWED_HISTORY_SHA256,
    load_history,
)


ROOT = Path(__file__).resolve().parents[2]


def test_frozen_workbook_seed_preserves_all_rows_and_explicit_correction() -> None:
    import hashlib

    assert hashlib.sha256(
        (ROOT / "config/valuation_tracker/workbook_seed_v1.json").read_bytes()
    ).hexdigest() == REVIEWED_WORKBOOK_SEED_SHA256
    seed = load_seed(ROOT / "config/valuation_tracker/workbook_seed_v1.json")
    assert seed["workbook_sha256"] == WORKBOOK_SHA256
    assert len(seed["rows"]) == 7
    assert [row["source_row_number"] for row in seed["rows"]] == list(range(2, 9))
    zijin = seed["rows"][0]
    assert zijin["source_row"]["股票代码"] == "601889"
    assert zijin["canonical_ticker"] == "601899.SH"
    assert zijin["identity_correction"]["corrected"] is True
    mmg = seed["rows"][2]
    assert mmg["currency"] == "HKD"
    assert "港元" in mmg["source_row"]["市值天花板预估（亿元）"]


def test_reviewed_history_has_exact_ranges_contexts_and_truthful_first_versions() -> None:
    payload = load_history(ROOT / "config/valuation_tracker/valuation_history_v2.json")
    assert payload["artifact_sha256"] == REVIEWED_HISTORY_SHA256
    assert len(payload["versions"]) == 11
    by_company = {}
    for version in payload["versions"]:
        by_company.setdefault(version["company_id"], []).append(version)
        assert 0 < version["lower_value"] <= version["base_value"] <= version["upper_value"]
        assert len(version["valuation_methods"]) >= 2
        assert len(version["sources"]) >= 2
        for field in (
            "operating_context", "profit_context", "cash_flow_context",
            "shareholder_return_context", "market_context", "frozen_input",
        ):
            assert version[field]
    assert {key: len(value) for key, value in by_company.items()} == {
        635: 2, 634: 2, 636: 2, 650: 2, 705: 1, 706: 1, 707: 1,
    }
    assert all(row["currency"] == "HKD" for row in by_company[636])


def test_alert_is_red_only_for_fresh_same_currency_threshold_breach() -> None:
    now = datetime.now(timezone.utc)
    row = {
        "max_snapshot_age_hours": 48,
        "researcher_ratio_threshold": 1,
        "ai_ratio_threshold": 0.8,
        "market_snapshot": {
            "market_cap_value": 100,
            "currency": "CNY",
            "trading_status": "trading",
            "observed_at": now.isoformat(),
        },
        "researcher_version": {"ceiling_value": 100, "currency": "CNY"},
        "latest_ai_version": {"ceiling_value": 200, "currency": "CNY"},
        "previous_ai_version": {"ceiling_value": 160, "currency": "CNY"},
    }
    ValuationTrackerRepository._decorate(row, now=now)
    assert row["researcher_ratio"] == 1
    assert row["researcher_alert"] is True
    assert row["ai_ratio"] == 0.5
    assert row["ai_alert"] is False
    assert row["ai_change_pct"] == 25


def test_stale_or_currency_mismatch_is_not_a_false_red_alert() -> None:
    now = datetime.now(timezone.utc)
    row = {
        "max_snapshot_age_hours": 48,
        "researcher_ratio_threshold": 0.1,
        "ai_ratio_threshold": 0.1,
        "market_snapshot": {
            "market_cap_value": 1000,
            "currency": "CNY",
            "trading_status": "trading",
            "observed_at": (now - timedelta(days=3)).isoformat(),
        },
        "researcher_version": {"ceiling_value": 1, "currency": "CNY"},
        "latest_ai_version": {"ceiling_value": 1, "currency": "HKD"},
        "previous_ai_version": None,
    }
    ValuationTrackerRepository._decorate(row, now=now)
    assert row["snapshot_stale"] is True
    assert row["researcher_alert"] is False
    assert row["ai_alert"] is False
    assert row["researcher_comparison_note"] == "市值快照已过期"


def test_suspended_or_missing_trade_status_never_triggers_alert() -> None:
    now = datetime.now(timezone.utc)
    for status, note in (
        ("suspended", "证券停牌，当前不判断"),
        (None, "交易状态不可得，当前不判断"),
    ):
        row = {
            "max_snapshot_age_hours": 48,
            "researcher_ratio_threshold": 0.1,
            "ai_ratio_threshold": 0.1,
            "market_snapshot": {
                "market_cap_value": 1000,
                "currency": "CNY",
                "trading_status": status,
                "observed_at": now.isoformat(),
            },
            "researcher_version": {"ceiling_value": 1, "currency": "CNY"},
            "latest_ai_version": None,
            "previous_ai_version": None,
        }
        ValuationTrackerRepository._decorate(row, now=now)
        assert row["researcher_alert"] is False
        assert row["researcher_ratio"] is None
        assert row["researcher_comparison_note"] == note


def test_monthly_ai_candidate_reuses_multiple_existing_methods() -> None:
    member = {
        "member_id": 1,
        "company_id": 635,
        "security_id": 616,
        "latest_ai_version": None,
    }
    bundle = {
        "valuation_model_runs": [
            {
                "id": 1,
                "run_key": "pe",
                "model_name": "正常化市盈率估值",
                "status": "frozen_independent",
                "valuation_date": "2026-07-24",
                "assumptions": {"company_detail_summary": {"operating_analysis": "经营复核"}},
                "outputs": [{
                    "output_name": "目标市值", "range_low": 8000,
                    "range_high": 12000, "unit": "亿元人民币", "formula": "利润×适用PE",
                }],
                "reconciliations": [{"benchmark_source_label": "近期卖方预测"}],
            },
            {
                "id": 2,
                "run_key": "pb",
                "model_name": "PB—ROE资产回报估值",
                "status": "reviewed",
                "valuation_date": "2026-07-24",
                "assumptions": {},
                "outputs": [{
                    "output_name": "目标市值", "range_low": 7000,
                    "range_high": 10000, "unit": "亿元人民币", "formula": "权益×适用PB",
                }],
                "reconciliations": [],
            },
        ],
        "current_metrics": {}, "historical_table": [], "forecast_table": [],
    }
    result = _candidate(member, bundle)
    assert result is not None
    assert result["ceiling_value"] == 11000
    assert len(result["valuation_methods"]) == 2
    assert "统一固定PE" in result["method_summary"]
    assert result["frozen_input"]["company_id"] == 635


def test_monthly_review_keeps_complete_prior_model_without_inventing_change() -> None:
    history = load_history(ROOT / "config/valuation_tracker/valuation_history_v2.json")
    prior = next(
        row for row in reversed(history["versions"])
        if row["company_id"] == 707
    )
    prior = {**prior, "version_id": 99, "input_sha256": "1" * 64, "output_sha256": "2" * 64}
    member = {
        "member_id": 7, "company_id": 707, "security_id": 999,
        "latest_ai_version": prior,
        "market_snapshot": {"share_price_value": 35.96, "market_cap_value": 638.52},
    }
    candidate = _review_existing_version(member)
    assert candidate is not None
    assert candidate["lower_value"] <= candidate["base_value"] <= candidate["upper_value"]
    assert candidate["frozen_input"]["previous_version_id"] == 99
    assert "+0.00%" in candidate["change_reason"]


def test_range_price_hk_migration_is_fail_closed_and_keeps_bootstrap_compatibility() -> None:
    source = (ROOT / "migrations/postgresql/0024_valuation_ranges_share_price_hk.sql").read_text(encoding="utf-8")
    assert "lower_value<=base_value AND base_value<=upper_value" in source
    assert "fill_legacy_valuation_range_v1" in source
    assert "share_price_value numeric" in source
    assert "slot IN ('1140','1510','1610')" in source
    assert "Wind.tdays:HKEX" in source
    assert "record_market_batch_v2" in source
    assert "seed_ai_history_v2" in source


def test_price_reconciliation_is_fill_only_and_append_audited() -> None:
    source = (
        ROOT / "migrations/postgresql/0025_valuation_market_price_reconciliation.sql"
    ).read_text(encoding="utf-8")
    assert "share_price_observed_at timestamptz" in source
    assert "share_price_source_ref text" in source
    assert "backfill_market_price_v1" in source
    assert "v_snapshot.share_price_value IS NOT NULL" in source
    assert "fill_missing_share_price" in source
    assert "fields_overwritten',false" in source
    assert "valuation_tracker.assert_writer_v1" in source
    assert "pg_advisory_xact_lock" in source
    assert "REVOKE ALL ON FUNCTION valuation_tracker.backfill_market_price_v1" in source


def test_postgres_migration_has_separate_slots_versions_and_narrow_grants() -> None:
    source = (ROOT / "migrations/postgresql/0021_valuation_tracker.sql").read_text(encoding="utf-8")
    assert "UNIQUE(security_id,trade_date,slot,provider)" in source
    assert "record_ai_candidates_v1" in source
    assert "replay_task_result_v1" in source
    assert "'scheduled_ai','candidate'" in source
    assert "human_values_overwritten',false" in source
    assert "REVOKE ALL ON ALL FUNCTIONS IN SCHEMA valuation_tracker FROM PUBLIC" in source
    assert 'TO :"writer_role"' in source
    assert "status IN ('published','superseded')" in source
    assert "p_calendar_evidence->'is_trading_day' IS DISTINCT FROM 'true'::jsonb" in source
    assert "p_calendar_evidence->'is_trading_day' IS DISTINCT FROM 'false'::jsonb" in source
    assert "v_input_sha:=encode(sha256" in source
    assert "v_output_sha:=encode(sha256" in source
    assert "count(DISTINCT x->>'run_key')" in source
    assert "count(DISTINCT (x->>'run_id')::bigint)" in source
    assert "jsonb_typeof(p_batch) IS DISTINCT FROM 'array'" in source
    assert "trading_status text NOT NULL" in source


def test_ai_change_is_not_computed_across_currencies() -> None:
    now = datetime.now(timezone.utc)
    row = {
        "max_snapshot_age_hours": 48,
        "researcher_ratio_threshold": 1,
        "ai_ratio_threshold": 1,
        "market_snapshot": None,
        "researcher_version": None,
        "published_ai_version": None,
        "latest_ai_version": {"ceiling_value": 100, "currency": "CNY"},
        "previous_ai_version": {"ceiling_value": 100, "currency": "HKD"},
    }
    ValuationTrackerRepository._decorate(row, now=now)
    assert row["ai_change_pct"] is None


def test_published_ai_remains_alert_authority_when_new_candidate_exists() -> None:
    now = datetime.now(timezone.utc)
    row = {
        "max_snapshot_age_hours": 48,
        "researcher_ratio_threshold": 1,
        "ai_ratio_threshold": 1,
        "market_snapshot": {
            "market_cap_value": 100,
            "currency": "CNY",
            "trading_status": "trading",
            "observed_at": now.isoformat(),
        },
        "researcher_version": None,
        "published_ai_version": {"version_id": 9, "ceiling_value": 200, "currency": "CNY"},
        "latest_ai_version": {"version_id": 10, "ceiling_value": 50, "currency": "CNY"},
        "previous_ai_version": None,
    }
    ValuationTrackerRepository._decorate(row, now=now)
    assert row["ai_alert_version"]["version_id"] == 9
    assert row["ai_ratio"] == 0.5
    assert row["ai_alert"] is False


def test_monthly_ai_rejects_two_outputs_from_one_run_and_non_equity_outputs() -> None:
    member = {
        "member_id": 1,
        "company_id": 635,
        "security_id": 616,
        "latest_ai_version": None,
    }
    one_run = {
        "id": 1,
        "run_key": "mixed",
        "model_name": "混合输出",
        "status": "reviewed",
        "valuation_date": "2026-08-19",
        "outputs": [
            {"output_name": "目标市值", "range_low": 90, "range_high": 100, "unit": "亿元人民币"},
            {"output_name": "股权价值", "range_low": 95, "range_high": 105, "unit": "CNY亿元"},
            {"output_name": "目标价每股", "range_low": 10, "range_high": 12, "unit": "CNY/股"},
        ],
    }
    assert _candidate(member, {"valuation_model_runs": [one_run]}) is None


def test_monthly_ai_rejects_unreconciled_multi_method_outputs() -> None:
    member = {
        "member_id": 1, "company_id": 635, "security_id": 616,
        "latest_ai_version": None,
    }
    runs = []
    for run_id, run_key in ((1, "pe"), (2, "pb")):
        runs.append({
            "id": run_id, "run_key": run_key, "model_name": run_key,
            "status": "reviewed", "valuation_date": "2026-08-19",
            "outputs": [{
                "output_name": "目标市值", "range_low": 90,
                "range_high": 100, "unit": "亿元人民币",
            }],
            "reconciliations": [],
        })
    assert _candidate(member, {"valuation_model_runs": runs}) is None


def test_no_candidate_migration_records_audited_monthly_evaluation() -> None:
    source = (
        ROOT / "migrations/postgresql/0022_valuation_ai_no_candidate_run.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS valuation_tracker.ai_refresh_run" in source
    assert "record_ai_no_candidates_v1" in source
    assert "array_agg(member_id ORDER BY member_id)" in source
    assert "human_values_overwritten',false" in source
    assert "valuation_tracker.assert_writer_v1" in source
    assert "REVOKE ALL ON FUNCTION" in source


def test_realtime_market_provenance_migration_corrects_and_fences_raw_field() -> None:
    source = (
        ROOT / "migrations/postgresql/0023_valuation_market_realtime_provenance.sql"
    ).read_text(encoding="utf-8")
    assert "migration_0023_correct_market_provenance" in source
    assert "source_ref NOT LIKE 'Wind WSQ.rt_mkt_cap+rt_susp_flag:%'" in source
    assert "SET raw_field='rt_mkt_cap'" in source
    assert "CHECK(raw_field='rt_mkt_cap')" in source
    assert "v_item->>'raw_field' IS DISTINCT FROM 'rt_mkt_cap'" in source
    assert "v_item->>'raw_field'" in source


def test_monthly_ai_ignores_general_financial_model_runs() -> None:
    member = {
        "member_id": 1,
        "company_id": 635,
        "security_id": 616,
        "latest_ai_version": None,
    }
    fake = {
        "id": 1,
        "run_key": "profit",
        "model_name": "盈利预测",
        "status": "reviewed",
        "outputs": [{
            "output_name": "FY1净利润",
            "range_low": 90,
            "range_high": 100,
            "unit": "亿元人民币",
        }],
    }
    assert _candidate(member, {"model_runs": [fake], "valuation_model_runs": []}) is None
