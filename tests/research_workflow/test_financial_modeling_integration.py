from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.financial.accounting_sanity import (
    annual_roe_sanity_reasons,
    normalize_nonmeaningful_annual_roe,
)
from tools.financial.db import connect, initialize_database, verify_database
from tools.financial.modeling import build_three_year_forecast, external_event_shock
from tools.financial.read_models import (
    _current_metrics_view,
    _model_implied_expectations,
    _paired_return_points,
    _public_model_substitution,
    _asset_return_view,
    _valuation_band_availability,
    _valuation_band_history,
    peer_asset_return_rows,
)
from tools.financial.repository import (
    create_model_run,
    freeze_independent_model,
    record_external_reconciliation,
    record_model_inputs,
    record_model_outputs,
    upsert_observation,
    upsert_security,
)
from tools.financial.valuation import (
    book_value_profit_bridge,
    dcf_fcff_valuation,
    dividend_discount_valuation,
    historical_pb_band,
    historical_pb_roa,
    historical_pb_roe,
    multistage_pb_roe_valuation,
    nav_valuation,
    peer_pb_model,
    peer_multiple_valuation,
    pb_double_click_decomposition,
    residual_income_valuation,
    risk_adjusted_npv,
    sotp_valuation,
    sustainable_growth_pb_valuation,
    synthesize_models,
    target_multiple_bridge,
    valuation_method_gate,
    wilcox_pb_roe_valuation,
)
from tools.pipeline.ensure_listed_company_profile import ensure_listed_company_profile
from tools.research_core.model_routing import route_modeling_skills
from tools.research_core.search_channels import build_gap_search_tasks, build_search_plan


HASH = "sha256:" + "a" * 64


class FinancialModelingIntegrationTests(unittest.TestCase):
    def test_model_substitution_is_researcher_readable_and_two_decimal(self) -> None:
        self.assertEqual(
            _public_model_substitution("1.6500×18—24＝29.7000—39.6000"),
            "1.65×18.00—24.00＝29.70—39.60",
        )
        self.assertEqual(
            _public_model_substitution('{"fcfe_rmb_bn":[620,690],"cost_of_equity_pct":11.5}'),
            "股权自由现金流（十亿元）＝620.00—690.00；股权资本成本（%）＝11.50",
        )

    def test_reverse_valuation_model_outputs_fill_market_implied_section(self) -> None:
        rows = _model_implied_expectations([{
            "id": 7,
            "skill_name": "company_valuation_modeling",
            "model_name": "股权自由现金流",
            "valuation_date": "2026-08-20",
            "forecast_end": "2028",
            "outputs": [{
                "output_name": "当前市值隐含归母净利润",
                "value_num": 17.57,
                "unit": "亿欧元",
                "period_or_as_of_date": "2028",
                "formula": "当前市值÷目标市盈率",
                "substitution": "36.8959÷21.00＝1.7570",
            }],
        }])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["metric_name"], "net_income")
        self.assertEqual(rows[0]["scenario_name"], "模型反推")
        self.assertEqual(rows[0]["substitution"], "36.8959÷21.00＝1.7570")

    def test_nonmeaningful_annual_roe_is_excluded_but_shown_as_not_applicable(self) -> None:
        observations = [
            {
                "id": 1, "metric_name": "total_equity", "value_num": 7.32,
                "fiscal_year": 2020, "fiscal_period": "FY",
                "period_end": "2020-12-31", "fact_type": "actual",
                "provider": "wind", "quality_status": "usable",
            },
            {
                "id": 2, "metric_name": "total_equity", "value_num": -6.89,
                "fiscal_year": 2021, "fiscal_period": "FY",
                "period_end": "2021-12-31", "fact_type": "actual",
                "provider": "wind", "quality_status": "usable",
            },
            {
                "id": 3, "metric_name": "total_equity", "value_num": 34.52,
                "fiscal_year": 2022, "fiscal_period": "FY",
                "period_end": "2022-12-31", "fact_type": "actual",
                "provider": "wind", "quality_status": "usable",
            },
            {
                "id": 4, "metric_name": "total_equity", "value_num": 38.50,
                "fiscal_year": 2023, "fiscal_period": "FY",
                "period_end": "2023-12-31", "fact_type": "actual",
                "provider": "wind", "quality_status": "usable",
            },
            {
                "id": 5, "metric_name": "roe", "value_num": -7777.1309,
                "fiscal_year": 2021, "fiscal_period": "FY",
                "period_end": "2021-12-31", "as_of_date": "2021-12-31",
                "fact_type": "actual", "frequency": "annual",
                "provider": "wind", "quality_status": "usable",
            },
            {
                "id": 6, "metric_name": "roe", "value_num": -30.7923,
                "fiscal_year": 2022, "fiscal_period": "FY",
                "period_end": "2022-12-31", "as_of_date": "2022-12-31",
                "fact_type": "actual", "frequency": "annual",
                "provider": "wind", "quality_status": "usable",
            },
            {
                "id": 7, "metric_name": "roe", "value_num": 3.70,
                "fiscal_year": 2023, "fiscal_period": "FY",
                "period_end": "2023-12-31", "as_of_date": "2023-12-31",
                "fact_type": "actual", "frequency": "annual",
                "provider": "wind", "quality_status": "usable",
            },
        ]
        reasons = annual_roe_sanity_reasons(observations)
        self.assertEqual(set(reasons), {2021, 2022})

        normalized = normalize_nonmeaningful_annual_roe(observations)
        by_year = {
            int(row["fiscal_year"]): row
            for row in normalized
            if row["metric_name"] == "roe"
        }
        self.assertIsNone(by_year[2021]["value_num"])
        self.assertEqual(by_year[2021]["quality_status"], "not_applicable")
        self.assertEqual(by_year[2022]["value_text"], "不适用")
        self.assertEqual(by_year[2023]["value_num"], 3.70)

        metrics: dict[str, list[dict[str, object]]] = {}
        for row in normalized:
            metrics.setdefault(str(row["metric_name"]), []).append(row)
        view = _asset_return_view(metrics)
        self.assertEqual(
            [row["fiscal_year"] for row in view["roe_history"]],
            [2023],
        )
        self.assertEqual(
            [row["fiscal_year"] for row in view["roe_history_display"]],
            [2021, 2022, 2023],
        )
        self.assertEqual(view["roe_history_excluded_count"], 2)
        self.assertEqual(view["roe_history_summary"]["average"], 3.70)

    def test_current_a_share_fields_use_wind_then_field_level_fallback(self) -> None:
        metrics = {
            "roe": [
                {"id": 1, "metric_name": "roe", "value_num": 12.0, "fact_type": "actual", "provider": "tushare", "raw_feature_name": "roe", "as_of_date": "2026-07-23", "quality_status": "usable"},
                {"id": 2, "metric_name": "roe", "value_num": 18.0, "fact_type": "actual", "provider": "wind", "raw_feature_name": "Wind WSS.roe", "as_of_date": "2026-07-22", "quality_status": "usable"},
                {"id": 3, "metric_name": "roe", "value_num": 16.0, "fact_type": "market", "provider": "wind", "raw_feature_name": "Wind WSS.roe_ttm", "as_of_date": "2026-07-22", "quality_status": "usable"},
            ],
            "roa": [
                {"id": 4, "metric_name": "roa", "value_num": 6.0, "fact_type": "actual", "provider": "tushare", "raw_feature_name": "roa", "as_of_date": "2026-07-23", "quality_status": "usable"},
            ],
            "eps_ttm": [
                {"id": 5, "metric_name": "eps_ttm", "value_num": 0.70, "fact_type": "actual", "provider": "tushare", "raw_feature_name": "eps", "as_of_date": "2026-07-23", "quality_status": "usable"},
                {"id": 6, "metric_name": "eps_ttm", "value_num": 0.74, "fact_type": "market", "provider": "wind", "raw_feature_name": "Wind WSS.eps_ttm", "as_of_date": "2026-07-22", "quality_status": "usable"},
            ],
            "bps_mrq": [
                {"id": 7, "metric_name": "bps_mrq", "value_num": 5.41, "fact_type": "market", "provider": "wind", "raw_feature_name": "Wind WSS.bps_new", "as_of_date": "2026-07-22", "quality_status": "usable"},
            ],
        }
        current = _current_metrics_view(metrics)
        self.assertEqual(current["roe"]["value_num"], 16.0)
        self.assertEqual(current["roe"]["provider_label"], "Wind")
        self.assertEqual(current["roa"]["provider_label"], "Tushare")
        self.assertEqual(current["eps_ttm"]["value_num"], 0.74)
        self.assertEqual(current["eps_ttm"]["provider_label"], "Wind")
        self.assertEqual(current["bps_mrq"]["provider_label"], "Wind")

    def test_monthly_point_in_time_history_never_replaces_current_snapshot(self) -> None:
        metrics = {
            "close": [
                {"id": 1, "value_num": 120.0, "fact_type": "market", "frequency": "snapshot", "provider": "yfinance", "raw_feature_name": "yfinance.info.currentPrice", "as_of_date": "2026-08-18", "quality_status": "usable"},
                {"id": 2, "value_num": 123.6, "fact_type": "market", "frequency": "monthly", "provider": "yfinance", "raw_feature_name": "yfinance.history.month_end_close", "as_of_date": "2026-08-31", "quality_status": "usable"},
            ],
            "pe_ttm": [
                {"id": 3, "value_num": 31.0, "fact_type": "market", "frequency": "snapshot", "provider": "yfinance", "raw_feature_name": "yfinance.info.trailingPE", "as_of_date": "2026-08-18", "quality_status": "usable"},
                {"id": 4, "value_num": 28.74, "fact_type": "market", "frequency": "monthly", "provider": "yfinance", "raw_feature_name": "yfinance.derived.point_in_time.pe_ttm", "as_of_date": "2026-08-31", "quality_status": "limited"},
            ],
            "pb": [
                {"id": 5, "value_num": 6.1, "fact_type": "market", "frequency": "snapshot", "provider": "yfinance", "raw_feature_name": "yfinance.info.priceToBook", "as_of_date": "2026-08-18", "quality_status": "usable"},
                {"id": 6, "value_num": 5.64, "fact_type": "market", "frequency": "monthly", "provider": "yfinance", "raw_feature_name": "yfinance.derived.point_in_time.pb", "as_of_date": "2026-08-31", "quality_status": "limited"},
            ],
        }
        current = _current_metrics_view(metrics)
        self.assertEqual(current["close"]["value_num"], 120.0)
        self.assertEqual(current["pe_ttm"]["value_num"], 31.0)
        self.assertEqual(current["pb"]["value_num"], 6.1)
        self.assertEqual(current["pe_ttm"]["raw_feature_name"], "yfinance.info.trailingPE")

    def test_price_band_uses_only_aligned_wind_wsd_rows(self) -> None:
        metrics = {"close": [], "pb": []}
        for index in range(12):
            observed = f"2025-{index + 1:02d}-28"
            metrics["close"].append({
                "id": index + 1, "metric_name": "close", "value_num": 10 + index,
                "fact_type": "market", "provider": "wind",
                "raw_feature_name": "Wind WSD.close", "as_of_date": observed,
                "quality_status": "usable",
            })
            metrics["pb"].append({
                "id": index + 20, "metric_name": "pb", "value_num": 1 + index / 10,
                "fact_type": "market", "provider": "wind",
                "raw_feature_name": "Wind WSD.pb_lf", "as_of_date": observed,
                "quality_status": "usable",
            })
        band = _valuation_band_history(metrics, "pb")
        self.assertIsNotNone(band)
        assert band is not None
        self.assertEqual(len(band["rows"]), 12)
        self.assertAlmostEqual(
            band["rows"][0]["base_per_share"],
            band["rows"][0]["close"] / band["rows"][0]["multiple"],
        )

    def test_price_band_snapshot_does_not_inflate_monthly_history(self) -> None:
        metrics = {"close": [], "pb": []}
        for index in range(11):
            observed = f"2025-{index + 1:02d}-28"
            metrics["close"].append({
                "id": index + 1, "metric_name": "close", "value_num": 10 + index,
                "fact_type": "market", "provider": "wind", "frequency": "monthly",
                "raw_feature_name": "Wind WSD.close", "as_of_date": observed,
                "quality_status": "usable",
            })
            metrics["pb"].append({
                "id": index + 20, "metric_name": "pb", "value_num": 1 + index / 10,
                "fact_type": "market", "provider": "wind", "frequency": "monthly",
                "raw_feature_name": "Wind WSD.pb_lf", "as_of_date": observed,
                "quality_status": "usable",
            })
        metrics["close"].append({
            "id": 100, "metric_name": "close", "value_num": 30,
            "fact_type": "market", "provider": "wind", "frequency": "snapshot",
            "raw_feature_name": "Wind WSS.close", "as_of_date": "2025-12-31",
            "quality_status": "usable",
        })
        metrics["pb"].append({
            "id": 101, "metric_name": "pb", "value_num": 2.5,
            "fact_type": "market", "provider": "wind", "frequency": "snapshot",
            "raw_feature_name": "Wind WSS.pb_lf", "as_of_date": "2025-12-31",
            "quality_status": "usable",
        })
        self.assertIsNone(_valuation_band_history(metrics, "pb"))
        availability = _valuation_band_availability(metrics, "pb")
        self.assertEqual(availability["status"], "insufficient_monthly_history")
        self.assertEqual(availability["sample_size"], 11)
        self.assertTrue(availability["current_multiple_available"])

    def test_non_wind_current_pb_reports_history_gap_not_interface_failure(self) -> None:
        metrics = {
            "close": [],
            "pb": [{
                "id": 1, "metric_name": "pb", "value_num": 3.2,
                "fact_type": "market", "provider": "yfinance",
                "frequency": "snapshot", "raw_feature_name": "yfinance.priceToBook",
                "as_of_date": "2026-07-24", "quality_status": "usable",
            }],
        }
        availability = _valuation_band_availability(metrics, "pb")
        self.assertEqual(
            availability["status"],
            "provider_monthly_history_not_loaded",
        )
        self.assertEqual(availability["sample_size"], 0)
        self.assertTrue(availability["current_multiple_available"])
        self.assertEqual(
            availability["message"],
            "历史估值带待补：需要至少12个月同口径月末数据，当前为0个月。",
        )

    def test_yfinance_point_in_time_history_is_usable_and_never_called_ttm_fact(self) -> None:
        metrics = {"close": [], "pb": []}
        for month in range(1, 13):
            observed = f"2025-{month:02d}-28"
            metrics["close"].append({
                "id": month, "metric_name": "close", "value_num": 20 + month,
                "fact_type": "market", "provider": "yfinance", "frequency": "monthly",
                "raw_feature_name": "yfinance.history.month_end_close",
                "as_of_date": observed, "quality_status": "usable",
            })
            metrics["pb"].append({
                "id": 20 + month, "metric_name": "pb", "value_num": 2 + month / 10,
                "fact_type": "market", "provider": "yfinance", "frequency": "monthly",
                "raw_feature_name": "yfinance.derived.point_in_time.pb",
                "as_of_date": observed, "quality_status": "limited",
            })
        metrics["pb"].append({
            "id": 99, "metric_name": "pb", "value_num": 3.4,
            "fact_type": "market", "provider": "yfinance", "frequency": "snapshot",
            "raw_feature_name": "yfinance.priceToBook", "as_of_date": "2026-08-20",
            "quality_status": "usable",
        })
        band = _valuation_band_history(metrics, "pb")
        self.assertIsNotNone(band)
        assert band is not None
        self.assertEqual(len(band["rows"]), 12)
        self.assertIn("点时近似", band["history_basis"])
        self.assertIn("不是Yahoo Finance历史TTM字段", band["boundary"])

    def test_practical_pb_roe_bridge_band_and_double_click_keep_boundaries_visible(self) -> None:
        bridge = book_value_profit_bridge(
            opening_book_value=100,
            net_income_path=[20, 24, 28],
            payout_path=[0.25, 0.25, 0.25],
        )
        self.assertAlmostEqual(bridge["ending_book_value"], 154)
        self.assertAlmostEqual(bridge["path"][0]["roe"], 20 / 107.5)
        self.assertIn("简化权益桥", bridge["boundary"])

        double_click = pb_double_click_decomposition(
            opening_book_value=100,
            ending_book_value=154,
            current_pb=2,
            target_pb=1.5,
        )
        self.assertAlmostEqual(double_click["current_market_value"], 200)
        self.assertAlmostEqual(double_click["book_value_contribution"], 108)
        self.assertAlmostEqual(double_click["pb_rerating_contribution"], -77)
        self.assertAlmostEqual(double_click["target_market_value"], 231)

        band = historical_pb_band(range(1, 13), current_pb=11)
        self.assertEqual(band["sample_size"], 12)
        self.assertGreater(band["current_percentile"], 0.8)
        self.assertIn("不是合理价值", band["boundary"])
        with self.assertRaises(ValueError):
            historical_pb_band(range(1, 12), current_pb=5)

    def test_pb_return_pairing_deduplicates_legacy_snapshot_and_labels_quarter(self) -> None:
        returns = [
            {
                "id": 1,
                "fact_type": "actual",
                "provider": "tushare",
                "period_end": "2026-03-31",
                "as_of_date": "2026-03-31",
                "fiscal_year": None,
                "fiscal_period": None,
                "value_num": 1.65,
            },
            {
                "id": 2,
                "fact_type": "actual",
                "provider": "tushare",
                "period_end": "2026-03-31",
                "as_of_date": "2026-03-31",
                "fiscal_year": 2026,
                "fiscal_period": None,
                "value_num": 1.65,
            },
        ]
        pb = [
            {
                "id": 3,
                "fact_type": "market",
                "provider": "tushare",
                "as_of_date": "2026-07-14",
                "value_num": 3.55,
            },
            {
                "id": 4,
                "fact_type": "market",
                "provider": "tushare",
                "as_of_date": "2026-07-14",
                "value_num": 3.55,
            },
        ]

        points = _paired_return_points(returns, pb)

        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["period"], "2026Q1")

    def test_four_skill_router_matches_task_matrix_without_loading_unrelated_models(self) -> None:
        cases = (
            ("公司未来利润", "预测某上市公司未来利润", {"company_financial_modeling"}),
            ("普通公司估值", "估值某上市公司合理价值", {"company_financial_modeling", "company_valuation_modeling"}),
            ("竞争者进入", "竞争者进入后如何影响公司利润和估值", {"company_financial_modeling", "company_valuation_modeling", "probability_scenario_modeling"}),
            ("行业空间", "测算高端设备市场空间和供需", {"industry_supply_demand_modeling"}),
            ("新闻核验", "只核验某公司招聘和专利事实", set()),
        )
        for title, question, expected in cases:
            with self.subTest(title=title):
                actual = {row.skill_name for row in route_modeling_skills(
                    track="c", title=title, research_question=question,
                )}
                self.assertEqual(actual, expected)

    def test_search_channels_are_independent_and_second_round_is_gap_bound(self) -> None:
        plan = build_search_plan(
            track="a", research_question="市场空间多大", requirement_questions=["供给是否过剩"],
        )
        self.assertEqual(set(plan["channels"]), {"report", "web"})
        by_axis: dict[str, set[str]] = {}
        for row in plan["tasks"]:
            by_axis.setdefault(row["axis_key"], set()).add(row["source_channel"])
        self.assertTrue(by_axis)
        self.assertTrue(all(channels == {"report", "web"} for channels in by_axis.values()))
        round_two = build_gap_search_tasks(gaps=[{
            "gap_id": "gap.latest_capacity", "axis_key": "capacity",
            "question": "最新产能", "query": "最新投产与延期证据",
        }])
        self.assertEqual({row.source_channel for row in round_two}, {"report", "web"})
        self.assertTrue(all(row.gap_trigger == "gap.latest_capacity" for row in round_two))

    def test_independent_forecast_freezes_before_consensus_and_keeps_auditable_ledger(self) -> None:
        forecast = build_three_year_forecast([
            {"fiscal_year": year, "revenue": revenue, "gross_margin": .4,
             "operating_expenses": 20, "net_interest": 1, "tax_rate": .2,
             "minority_interest": 0, "diluted_shares": 10,
             "average_equity": 80 + (year - 2027) * 10,
             "average_total_assets": 160 + (year - 2027) * 20}
            for year, revenue in ((2027, 100), (2028, 115), (2029, 130))
        ])
        self.assertTrue(forecast["independent_freeze_hash"].startswith("sha256:"))
        self.assertAlmostEqual(forecast["forecast"][0]["roe"], 15.2 / 80)
        self.assertAlmostEqual(forecast["forecast"][0]["roa"], 15.2 / 160)
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "financial.db"
            initialize_database(db_path)
            conn = connect(db_path)
            try:
                security_id = upsert_security(conn, research_company_id=1, canonical_name="测试公司", ticker="1.SZ", market="A股")
                model_id = create_model_run(
                    conn, run_key="test-finance", security_id=security_id,
                    skill_name="company_financial_modeling", model_name="财务桥", model_role="primary",
                )
                record_model_inputs(conn, model_id, [{
                    "input_name": "FY1收入", "value_num": 100, "unit": "亿元",
                    "period_or_as_of_date": "2027", "source_ref": "official:annual-report",
                    "input_type": "derived_fact", "formula_or_method": "历史基线与订单桥",
                }])
                record_model_outputs(conn, model_id, [{
                    "output_name": "FY1归母净利润", "value_num": 15.2, "unit": "亿元",
                    "period_or_as_of_date": "2027", "formula": "税前利润×(1-税率)",
                    "substitution": "19×(1-20%)=15.2", "dependency_group": "base_financials",
                }])
                input_hash, output_hash = freeze_independent_model(conn, model_id)
                self.assertTrue(input_hash.startswith("sha256:"))
                self.assertTrue(output_hash.startswith("sha256:"))
                record_external_reconciliation(
                    conn, model_id, benchmark_type="consensus",
                    benchmark_source_ref="wind:consensus:2026-07-22",
                    metric_name="net_income", period="FY1", independent_value=15.2,
                    benchmark_value=14.8, unit="亿元", decomposition={"收入差异": .4},
                    conclusion="差异由收入假设解释。",
                )
                conn.commit()
                row = conn.execute("SELECT status,independent_before_consensus,input_hash,output_hash FROM financial_model_run").fetchone()
                self.assertEqual(tuple(row), ("reconciled", 1, input_hash, output_hash))
            finally:
                conn.close()

    def test_event_probability_is_not_multiplied_into_conditional_financial_impact(self) -> None:
        common = dict(
            baseline_revenue=100, exposed_revenue_share=.5, direct_share_loss=.1,
            conditional_share_loss=.2, offset_revenue=2, baseline_gross_margin=.4,
            extra_price_pressure=.05, variable_cost_relief=.01,
            operating_expense_change=1, tax_rate=.2,
        )
        low = external_event_shock(**common, event_probability=.1)
        high = external_event_shock(**common, event_probability=.9)
        self.assertEqual(low["revenue"], high["revenue"])
        self.assertEqual(low["after_tax_profit_change"], high["after_tax_profit_change"])
        self.assertIn("分列", low["probability_usage"])

    def test_valuation_gates_soft_adjustments_pb_models_and_model_clusters(self) -> None:
        gates = valuation_method_gate(
            normalized_profit_positive=False, ebitda_positive=False,
            revenue_economically_meaningful=True, full_fcff_inputs_available=False,
            book_value_economically_meaningful=True, high_leverage=True,
            asset_nav_inputs_available=True, pipeline_rnpv_inputs_available=True,
            dividend_model_applicable=True,
            sustainable_roe_available=True, cost_of_equity_available=True,
            roe_fade_period_supported=True,
        )
        self.assertEqual(gates["forward_pe"]["status"], "not_applicable")
        self.assertEqual(gates["pb_roa"]["status"], "required_diagnostic")
        self.assertEqual(gates["nav"]["status"], "core_or_reference")
        self.assertEqual(gates["rnpv"]["status"], "core_or_reference")
        self.assertEqual(gates["ddm"]["status"], "core_or_reference")
        self.assertEqual(gates["wilcox_pb_roe"]["status"], "reference")
        bridge = target_multiple_bridge(base_multiple=20, adjustments=[{
            "label": "竞争风险折价", "multiple_points": -3, "reason": "客户集中",
            "source_ref": "source:1", "as_of_date": "2026-07-22",
        }])
        self.assertEqual(bridge["target_multiple"], 17)
        peer = peer_multiple_valuation(
            [{"name": name, "multiple": value} for name, value in (("甲", 16), ("乙", 18), ("丙", 20))],
            forecast_metric=10, metric_name="归母净利润",
        )
        self.assertEqual(peer["equity_value"], 180)
        history = [
            {"period": "2023", "roe": 10, "roa": 5, "pb": 1.2},
            {"period": "2024", "roe": 12, "roa": 6, "pb": 1.5},
            {"period": "2025", "roe": 14, "roa": 7, "pb": 1.9},
            {"period": "2025", "roe": 99, "roa": 99, "pb": 99},
        ]
        roe = historical_pb_roe(history, current_roe=13)
        roa = historical_pb_roa(history, current_roa=6.5)
        self.assertEqual(roe["sample_size"], 3)
        self.assertEqual(roa["sample_size"], 3)
        self.assertIn("descriptive_band_low", roe)
        self.assertEqual(roe["response_transform"], "ln(pb)")
        self.assertIn("ln(合理PB)", roe["formula"])
        self.assertGreater(roe["descriptive_band_low"], 0)
        peer_pb = peer_pb_model(
            [
                {"pb": 1.2, "roe": 10},
                {"pb": 1.5, "roe": 12},
                {"pb": 1.9, "roe": 14},
            ],
            target={"roe": 13}, feature_names=("roe",),
        )
        self.assertEqual(peer_pb["response_transform"], "ln(pb)")
        self.assertGreater(peer_pb["reasonable_pb"], 0)

        wilcox = wilcox_pb_roe_valuation(
            expected_sustainable_roe=.20, cost_of_equity=.08,
            fade_years=15, terminal_pb=1, opening_book_value=100,
        )
        self.assertAlmostEqual(wilcox["reasonable_pb"], 6.049647, places=5)
        self.assertAlmostEqual(wilcox["equity_value"], 604.9647, places=3)
        stable_pb = sustainable_growth_pb_valuation(
            sustainable_roe=.12, payout_ratio=.5, cost_of_equity=.08,
        )
        self.assertAlmostEqual(stable_pb["sustainable_growth"], .06)
        self.assertAlmostEqual(stable_pb["reasonable_pb"], 3.18)
        forward_stable_pb = sustainable_growth_pb_valuation(
            sustainable_roe=.12, payout_ratio=.5, cost_of_equity=.08,
            roe_basis="forward_period",
        )
        self.assertAlmostEqual(forward_stable_pb["reasonable_pb"], 3.0)
        staged_pb = multistage_pb_roe_valuation(
            [
                {"name": "高增长", "years": 2, "roe": .18, "payout_ratio": .3},
                {"name": "回归期", "years": 3, "roe": .14, "payout_ratio": .45},
            ],
            opening_book_value=100, cost_of_equity=.10,
            terminal_roe=.09, terminal_payout_ratio=.7,
        )
        self.assertEqual(len(staged_pb["annual_trace"]), 5)
        self.assertGreater(staged_pb["reasonable_pb"], 0)
        one_stage = multistage_pb_roe_valuation(
            [{"name": "显式期", "years": 1, "roe": .10, "payout_ratio": .5}],
            opening_book_value=100, cost_of_equity=.10,
            terminal_roe=.08, terminal_payout_ratio=.75,
        )
        self.assertAlmostEqual(one_stage["annual_trace"][0]["closing_book_value"], 105)
        self.assertAlmostEqual(one_stage["terminal_value_present_value"], 78.75 / 1.10)
        dcf = dcf_fcff_valuation(fcff_path=[10, 11, 12], wacc=.1, terminal_growth=.03, net_debt=5)
        residual = residual_income_valuation(
            opening_book_value=100, roe_path=[.15, .14, .13], payout_path=[.3, .3, .3],
            cost_of_equity=.1, terminal_roe=.11, terminal_growth=.03,
        )
        residual_timing = residual_income_valuation(
            opening_book_value=100, roe_path=[.10], payout_path=[0],
            cost_of_equity=.10, terminal_roe=.12, terminal_growth=.02,
        )
        self.assertAlmostEqual(residual_timing["equity_value"], 125.0)
        combined = synthesize_models([
            {"model_name": "DCF", "role": "core", "dependency_group": "cash_flow", "equity_value": dcf["equity_value"]},
            {"model_name": "残余收益", "role": "core", "dependency_group": "asset_return", "equity_value": residual["equity_value"]},
        ])
        self.assertEqual(len(combined["clusters"]), 2)
        self.assertIn("不对高度相关模型机械平均", combined["aggregation_rule"])

        sotp = sotp_valuation([
            {"name": "设备", "enterprise_value": 80, "method": "EV/EBITDA", "source_ref": "model:equipment", "as_of_date": "2026-07-22"},
            {"name": "材料", "enterprise_value": 40, "method": "PE", "source_ref": "model:materials", "as_of_date": "2026-07-22"},
        ], net_debt=10)
        self.assertEqual(sotp["equity_value"], 110)
        nav = nav_valuation([
            {"name": "矿权", "gross_value": 100, "haircut": .2, "source_ref": "official:reserve", "as_of_date": "2026-07-22"},
        ], [{"name": "净债务", "value": 30, "source_ref": "official:balance-sheet", "as_of_date": "2026-07-22"}])
        self.assertEqual(nav["equity_value"], 50)
        rnpv = risk_adjusted_npv([
            {"name": "管线A", "success_value": 100, "success_probability": .5,
             "years_to_value": 2, "cost_to_complete_pv": 10,
             "probability_basis": "公开参考类别", "source_ref": "trial:A", "as_of_date": "2026-07-22"},
        ], discount_rate=.1)
        self.assertGreater(rnpv["equity_value"], 30)
        ddm = dividend_discount_valuation(dividend_path=[5, 6, 7], cost_of_equity=.1, terminal_growth=.03)
        self.assertGreater(ddm["equity_value"], 0)

    def test_verified_company_provisioning_links_research_and_financial_without_guessing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            research = Path(td) / "research.db"
            financial = Path(td) / "financial.db"
            conn = sqlite3.connect(research)
            conn.executescript("""
                PRAGMA foreign_keys=ON;
                CREATE TABLE company(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,ticker TEXT,market TEXT,
                  note TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,listing_status TEXT
                );
                CREATE TABLE company_identity_alias(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,canonical_company_id INTEGER NOT NULL,
                  alias TEXT NOT NULL,alias_type TEXT NOT NULL,source TEXT NOT NULL,
                  UNIQUE(canonical_company_id,alias),FOREIGN KEY(canonical_company_id) REFERENCES company(id)
                );
            """)
            conn.commit(); conn.close()
            result = ensure_listed_company_profile(
                canonical_name="测试股份", ticker="000001.SZ", market="A股",
                listing_status="a_share", verification_source_ref="exchange:000001",
                aliases=["Test Corp"], research_db_path=research, financial_db_path=financial,
            )
            self.assertTrue(result["created"])
            conn = sqlite3.connect(research)
            conn.execute("UPDATE company SET market=NULL WHERE id=?", (result["company_id"],))
            conn.commit()
            conn.close()
            result_again = ensure_listed_company_profile(
                canonical_name="测试股份", ticker="000001.SZ", market="A股",
                listing_status="a_share", verification_source_ref="exchange:000001",
                aliases=["Test Corp"], research_db_path=research, financial_db_path=financial,
            )
            self.assertEqual(result_again["company_id"], result["company_id"])
            conn = sqlite3.connect(research)
            self.assertEqual(
                conn.execute(
                    "SELECT market FROM company WHERE id=?", (result["company_id"],)
                ).fetchone()[0],
                "A股",
            )
            conn.close()
            self.assertEqual(verify_database(financial)["foreign_key_issues"], 0)
            fconn = connect(financial)
            try:
                self.assertEqual(fconn.execute("SELECT COUNT(*) FROM financial_security_company_link").fetchone()[0], 1)
                security_id = int(fconn.execute("SELECT id FROM financial_security").fetchone()[0])
                for metric, value, fact_type, unit in (
                    ("pb", 1.8, "market", "倍"), ("roe", 12.0, "actual", "%"),
                    ("roa", 6.0, "actual", "%"), ("total_assets", 200, "actual", "亿元"),
                    ("book_value", 100, "actual", "亿元"),
                ):
                    upsert_observation(
                        fconn, security_id=security_id, metric_name=metric, value_num=value,
                        unit=unit, period_end="2025-12-31", frequency="annual",
                        fact_type=fact_type, as_of_date="2026-04-30", provider="tushare",
                        raw_feature_name=metric,
                    )
                fconn.commit()
            finally:
                fconn.close()
            peers = peer_asset_return_rows([result["company_id"]], db_path=financial)
            self.assertEqual(len(peers), 1)
            self.assertEqual(peers[0]["pb"]["value_num"], 1.8)
            self.assertEqual(peers[0]["equity_multiplier"], 2.0)


if __name__ == "__main__":
    unittest.main()
