from __future__ import annotations

import json
import math
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from tools.opportunity_lens.run16_financial_portfolio_model import (
    ModelContractError,
    _rank_positions,
    _select_candidates,
    _spearman,
    build_independent_model,
)
from tools.opportunity_lens.run16_external_reconciliation import (
    _report_medians_by_basis,
    _sell_side_period,
)
from tools.opportunity_lens.build_run16_company_financial_export import (
    _sell_side_benchmark_reconciliations,
)
from tools.financial.repository import ALLOWED_BENCHMARK_TYPES


def _input(value: float, unit: str, rationale: str = "测试中的显式独立假设") -> dict:
    return {
        "value": value,
        "unit": unit,
        "basis_type": "internal_estimate",
        "as_of": "2026-07-30",
        "source_ref": "test:evidence-ledger",
        "rationale": rationale,
    }


def _year(growth: float, net_margin: float) -> dict:
    return {
        "revenue_growth_pct": _input(growth, "%"),
        "gross_margin_pct": _input(45.0, "%"),
        "parent_net_margin_pct": _input(net_margin, "%"),
        "ocf_margin_pct": _input(22.0, "%"),
        "capex_margin_pct": _input(5.0, "%"),
        "total_assets_growth_pct": _input(8.0, "%"),
        "dividend_payout_pct": _input(30.0, "%"),
        "buyback_100m_cny": _input(0.0, "亿元人民币"),
        "other_equity_change_100m_cny": _input(0.0, "亿元人民币"),
    }


def _company(index: int, *, loss: bool = False, stable_roe: bool = True) -> dict:
    ticker = f"60000{index}.SH"
    base_margin = -5.0 if loss else 15.0
    return {
        "ticker": ticker,
        "name": f"测试公司{index}",
        "company_id": index,
        "economic_mechanism": "企业软件订阅与AI增值服务共同驱动收入和利润率",
        "data_quality": "medium",
        "scenarios": {
            "downside": {str(year): _year(2.0, base_margin - 3.0) for year in (2026, 2027, 2028)},
            "base": {str(year): _year(8.0, base_margin) for year in (2026, 2027, 2028)},
            "upside": {str(year): _year(14.0, base_margin + 3.0) for year in (2026, 2027, 2028)},
        },
        "valuation_methods": {
            "pe": {
                "enabled": True,
                "role": "核心",
                "target_year": 2027,
                "multiple_low": _input(20.0, "倍"),
                "multiple_high": _input(28.0, "倍"),
            },
            "dcf": {
                "enabled": True,
                "role": "参考",
                "cost_of_equity_low_pct": _input(9.0, "%"),
                "cost_of_equity_high_pct": _input(11.0, "%"),
                "terminal_growth_low_pct": _input(2.0, "%"),
                "terminal_growth_high_pct": _input(3.0, "%"),
            },
            "pb_roe": {
                "enabled": True,
                "role": "诊断",
                "stable_roe": stable_roe,
                "stability_evidence": ["test:three-year-normalized-roe"],
                "cost_of_equity_low_pct": _input(9.0, "%"),
                "cost_of_equity_high_pct": _input(11.0, "%"),
                "terminal_pb_low": _input(1.0, "倍"),
                "terminal_pb_high": _input(1.3, "倍"),
                "convergence_years": _input(5.0, "年"),
            },
            "reverse_pe_year": 2027,
        },
        "portfolio": {
            "eligible": True,
            "scopes": ["applications", "full_chain"],
            "direction": "AI应用" if index % 2 else "AI基础设施",
            "direction_score": _input(70 + index, "分"),
            "quality_score": _input(75 + index, "分"),
            "evidence_score": _input(72 + index, "分"),
            "valuation_score": _input(60 + index, "分"),
            "risk_score": _input(35 + index, "分"),
        },
    }


def _to_compact(company: dict) -> dict:
    company = json.loads(json.dumps(company))
    scenarios = company.pop("scenarios")
    compact = {}
    for metric in scenarios["base"]["2026"]:
        seed = scenarios["base"]["2026"][metric]
        compact[metric] = {
            "values": {
                scenario: {
                    year: scenarios[scenario][year][metric]["value"]
                    for year in ("2026", "2027", "2028")
                }
                for scenario in ("downside", "base", "upside")
            },
            **{key: value for key, value in seed.items() if key != "value"},
        }
    company["forecast_assumptions"] = compact
    return company


def _snapshot(companies: list[dict]) -> dict:
    start = date(2026, 1, 1)
    current = {}
    reported = {period: {} for period in ("20211231", "20221231", "20231231", "20241231", "20251231", "20250331", "20260331")}
    histories = {}
    universe = []
    for index, company in enumerate(companies, start=1):
        ticker = company["ticker"]
        universe.append({"ticker": ticker, "name": company["name"], "key": ticker})
        current[ticker] = {
            "CLOSE": 20.0 + index,
            "MKT_CAP_ARD": (400.0 + index * 50.0) * 1e8,
            "FREE_FLOAT_MARKET_CAP_CNY_100M": 250.0 + index * 30.0,
            "PE_TTM": 25.0,
            "PB_LF": 3.0,
        }
        for period in reported:
            reported[period][ticker] = {
                "OPER_REV": (100.0 + index * 10.0) * 1e8,
                "NP_BELONGTO_PARCOMSH": (12.0 + index) * 1e8,
                "NET_CASH_FLOWS_OPER_ACT": (20.0 + index) * 1e8,
                "CASH_PAY_ACQ_CONST_FIOLTA": (5.0 + index / 10.0) * 1e8,
                "TOT_ASSETS": (220.0 + index * 10.0) * 1e8,
                "TOT_EQUITY": (120.0 + index * 5.0) * 1e8,
                "TOT_LIAB": 100.0 * 1e8,
                "ROE": 12.0,
                "ROA2": 6.0,
                "GROSSPROFITMARGIN": 45.0,
                "NETPROFITMARGIN": 12.0,
            }
        histories[ticker] = []
        for day in range(180):
            # Different deterministic waves avoid identical-return histories.
            close = 20.0 + index + day * 0.02 + math.sin(day / (3.0 + index)) * (0.2 + index / 20)
            histories[ticker].append(
                {"date": str(start + timedelta(days=day)), "close_forward_adjusted": close}
            )
    return {
        "snapshot_version": "run16.ai_actual_market_history.v1",
        "stage": "actual_before_consensus",
        "trade_date": "2026-07-30",
        "universe": universe,
        "request_audit": {"consensus_fields_read": []},
        "wind": {"current": current, "reported": reported, "price_history": histories},
    }


def _assumptions(companies: list[dict]) -> dict:
    return {
        "independent_before_consensus": True,
        "as_of_date": "2026-07-30",
        "companies": companies,
        "portfolio_policies": {
            "concentrated": {
                "min_holdings": 2,
                "max_holdings": 3,
                "max_weight_pct": 55.0,
                "max_direction_weight_pct": 60.0,
                "cash_weight_pct": 0.0,
                "max_pair_correlation": 0.9999,
                "min_overlap_days": 100,
                "correlation_window_days": 245,
                "rolling_60d_diagnostic_threshold": 0.9999,
                "anchor_mix": {"free_float": 0.4, "equal": 0.3, "inverse_volatility": 0.3},
                "score_weights": {"direction_score": 0.1, "quality_score": 0.2, "evidence_score": 0.25, "valuation_score": 0.3, "risk_score": 0.15},
                "active_tilt_strength": 0.25,
                "active_tilt_min": 0.85,
                "active_tilt_max": 1.15,
                "conviction_theme_by_scope": {
                    "applications": "测试方向",
                    "full_chain": "测试方向",
                },
                "conviction_directions_by_scope": {
                    "applications": ["AI应用", "AI基础设施"],
                    "full_chain": ["AI应用", "AI基础设施"],
                },
            },
            "balanced": {
                "min_holdings": 2,
                "max_holdings": 4,
                "max_weight_pct": 45.0,
                "max_direction_weight_pct": 60.0,
                "cash_weight_pct": 0.0,
                "max_pair_correlation": 0.9999,
                "min_overlap_days": 100,
                "correlation_window_days": 245,
                "anchor_mix": {"free_float": 0.3, "equal": 0.35, "inverse_volatility": 0.35},
                "score_weights": {"direction_score": 0.1, "quality_score": 0.2, "evidence_score": 0.25, "valuation_score": 0.3, "risk_score": 0.15},
                "active_tilt_strength": 0.25,
                "active_tilt_min": 0.85,
                "active_tilt_max": 1.15,
            },
            "risk_diversified": {
                "min_holdings": 2,
                "max_holdings": 4,
                "max_weight_pct": 40.0,
                "max_direction_weight_pct": 60.0,
                "cash_weight_pct": 10.0,
                "max_pair_correlation": 0.9999,
                "min_overlap_days": 100,
                "correlation_window_days": 245,
                "anchor_mix": {"free_float": 0.15, "equal": 0.25, "inverse_volatility": 0.6},
                "score_weights": {"direction_score": 0.1, "quality_score": 0.2, "evidence_score": 0.25, "valuation_score": 0.3, "risk_score": 0.15},
                "active_tilt_strength": 0.25,
                "active_tilt_min": 0.85,
                "active_tilt_max": 1.15,
            },
        },
        "stress_scenarios": [
            {
                "name": "应用兑现延后与估值压缩",
                "description": "收入增长、净利率和估值同时承压",
                "direction_shocks": {
                    "default": {
                        "revenue_growth_delta_pp": _input(-5.0, "百分点"),
                        "parent_net_margin_delta_pp": _input(-2.0, "百分点"),
                        "ocf_margin_delta_pp": _input(-2.0, "百分点"),
                        "capex_margin_delta_pp": _input(1.0, "百分点"),
                        "valuation_multiple_change_pct": _input(-15.0, "%"),
                    }
                },
            }
        ],
    }


class Run16FinancialPortfolioModelTests(unittest.TestCase):
    def _run(self, companies: list[dict], assumptions: dict | None = None) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            actual_path = root / "actual.json"
            assumption_path = root / "assumptions.json"
            actual_path.write_text(json.dumps(_snapshot(companies)), encoding="utf-8")
            assumption_path.write_text(
                json.dumps(assumptions or _assumptions(companies)), encoding="utf-8"
            )
            return build_independent_model([actual_path], assumption_path)

    def test_financial_bridges_valuation_portfolios_and_stress_are_reproducible(self) -> None:
        companies = [_company(index) for index in range(1, 5)]
        payload = self._run(companies)
        self.assertTrue(payload["independent_before_consensus"])
        self.assertFalse(payload["external_consensus_read"])
        self.assertEqual(payload["sanity"]["verdict"], "GREEN")
        row = payload["companies"]["600001.SH"]["scenarios"]["base"]["2026"]
        self.assertAlmostEqual(row["revenue_100m_cny"], 118.8, places=2)
        self.assertAlmostEqual(row["fcf_100m_cny"], row["ocf_100m_cny"] - row["capex_100m_cny"], places=2)
        # 2026权益桥以已披露Q1归母权益125亿元为起点，只加入剩余年度利润，
        # 再扣按FY2025归母净利润估算的Q1后支付分红。
        self.assertAlmostEqual(row["equity_bridge_opening_100m_cny"], 125.0, places=2)
        self.assertAlmostEqual(
            row["dividend_base_parent_net_income_100m_cny"], 13.0, places=2
        )
        self.assertAlmostEqual(row["dividends_100m_cny"], 3.9, places=2)
        self.assertAlmostEqual(row["ending_parent_equity_100m_cny"], 125.92, places=2)
        self.assertGreaterEqual(
            row["ending_total_assets_100m_cny"],
            row["ending_parent_equity_100m_cny"],
        )
        self.assertAlmostEqual(
            row["accounting_asset_floor_100m_cny"],
            row["ending_parent_equity_100m_cny"],
            places=2,
        )
        y27 = payload["companies"]["600001.SH"]["scenarios"]["base"]["2027"]
        self.assertAlmostEqual(
            y27["dividend_base_parent_net_income_100m_cny"],
            row["parent_net_income_100m_cny"],
            places=2,
        )
        candidate = payload["companies"]["600001.SH"]["portfolio_candidate"]
        self.assertEqual(
            candidate["scorecard_contract_version"],
            "run16.portfolio_scorecard.v2",
        )
        for key, ledger in candidate["score_ledger"].items():
            self.assertEqual(ledger["basis_type"], "implied")
            self.assertAlmostEqual(
                ledger["value"],
                min(
                    100.0,
                    sum(float(item["awarded_points"]) for item in ledger["criteria"]),
                ),
                places=6,
            )
        methods = payload["companies"]["600001.SH"]["valuation_methods"]
        self.assertEqual(next(item for item in methods if item["method"] == "Forward PE")["status"], "calculated")
        self.assertEqual(next(item for item in methods if item["method"].startswith("PB—ROE"))["status"], "calculated")
        self.assertEqual(len(payload["portfolios"]), 6)
        for portfolio in payload["portfolios"]:
            total = sum(row["weight_pct"] for row in portfolio["holdings"]) + portfolio["cash_weight_pct"]
            self.assertAlmostEqual(total, 100.0, places=2)
            self.assertLessEqual(max(portfolio["direction_weight_pct"].values()), 60.0)
            self.assertLessEqual(
                portfolio["effective_number_of_holdings"],
                len(portfolio["holdings"]),
            )
            self.assertGreater(
                portfolio["portfolio_risk_diagnostics"]["annualized_volatility_pct"],
                0.0,
            )
            self.assertAlmostEqual(
                portfolio["portfolio_risk_diagnostics"]["risk_contribution_sum_pct"],
                100.0,
                places=2,
            )
            self.assertIn("60", portfolio["weight_sensitivity"]["weights_by_window_pct"])
            self.assertIn("245", portfolio["weight_sensitivity"]["weights_by_window_pct"])
            self.assertIn("correlation_60d", portfolio["correlation_diagnostics"][0])
            self.assertIn("rolling_60d_peak", portfolio["correlation_diagnostics"][0])
            for holding in portfolio["holdings"]:
                self.assertIn("free_float", holding["anchor_components"])
                self.assertGreaterEqual(holding["active_tilt_multiplier"], 0.85)
                self.assertLessEqual(holding["active_tilt_multiplier"], 1.15)
                self.assertIsNotNone(holding["risk_contribution_pct"])
        self.assertTrue(
            all("混合锚" in row["formula"] for row in payload["portfolio_formula_audit"])
        )
        self.assertEqual(len(payload["stress_tests"]), 1)
        self.assertTrue(payload["output_hash"].startswith("sha256:"))

    def test_normalization_preserves_reported_actual_and_records_adjustment(self) -> None:
        companies = [_company(index) for index in range(1, 5)]
        companies[0]["normalization_overrides"] = {
            "parent_net_income_100m_cny": {
                **_input(10.0, "亿元人民币", "剔除重大公允价值变动后的研究口径"),
                "affected_reported_item": "重大非经常性公允价值变动",
                "adjustment_reason": "报告净利润不代表核心经营盈利能力",
            },
            "q1_2026_parent_net_income_100m_cny": {
                **_input(8.0, "亿元人民币", "剔除一季度重大公允价值变动后的研究口径"),
                "affected_reported_item": "2026Q1重大公允价值变动",
                "adjustment_reason": "季度账面利润不可直接年化",
            },
        }
        payload = self._run(companies)
        baseline = payload["companies"]["600001.SH"]["baseline"]
        self.assertEqual(baseline["reported_actual_before_normalization"]["parent_net_income_100m_cny"], 13.0)
        self.assertEqual(baseline["parent_net_income_100m_cny"], 10.0)
        self.assertEqual(baseline["normalization_adjustments"][0]["adjustment_100m_cny"], -3.0)
        self.assertEqual(baseline["current_year_q1_checkpoint"]["parent_net_income_100m_cny"], 8.0)
        self.assertEqual(baseline["reported_q1_actual_before_normalization"]["parent_net_income_100m_cny"], 13.0)

    def test_compact_forecast_series_schema_is_equivalent(self) -> None:
        companies = [_to_compact(_company(index)) for index in range(1, 5)]
        payload = self._run(companies)
        row = payload["companies"]["600001.SH"]["scenarios"]["base"]["2026"]
        self.assertEqual(row["revenue_100m_cny"], 118.8)
        self.assertEqual(payload["sanity"]["verdict"], "GREEN")

    def test_asset_bridge_applies_accounting_floor_when_profit_outgrows_assets(self) -> None:
        companies = [_company(index) for index in range(1, 5)]
        for scenario in ("downside", "base", "upside"):
            for year in (2026, 2027, 2028):
                row = companies[0]["scenarios"][scenario][str(year)]
                row["revenue_growth_pct"] = _input(100.0, "%")
                row["gross_margin_pct"] = _input(90.0, "%")
                row["parent_net_margin_pct"] = _input(80.0, "%")
                row["total_assets_growth_pct"] = _input(0.0, "%")
                row["dividend_payout_pct"] = _input(0.0, "%")
        payload = self._run(companies)
        self.assertEqual(payload["sanity"]["verdict"], "GREEN")
        for scenario in ("downside", "base", "upside"):
            for year in (2026, 2027, 2028):
                row = payload["companies"]["600001.SH"]["scenarios"][scenario][str(year)]
                self.assertTrue(row["asset_floor_applied"])
                self.assertGreaterEqual(
                    row["ending_total_assets_100m_cny"],
                    row["ending_parent_equity_100m_cny"],
                )
                self.assertAlmostEqual(
                    row["ending_total_assets_100m_cny"],
                    row["accounting_asset_floor_100m_cny"],
                    places=2,
                )

    def test_candidate_shortfall_preserves_name_cap_by_raising_cash(self) -> None:
        companies = [_company(index) for index in range(1, 5)]
        assumptions = _assumptions(companies)
        policy = assumptions["portfolio_policies"]["risk_diversified"]
        policy.update(
            {
                "target_min_holdings": 4,
                "max_weight_pct": 12.0,
                "cash_weight_pct": 10.0,
            }
        )
        payload = self._run(companies, assumptions)
        portfolios = [
            row for row in payload["portfolios"] if row["portfolio_type"] == "risk_diversified"
        ]
        self.assertEqual(len(portfolios), 2)
        for portfolio in portfolios:
            self.assertEqual(portfolio["requested_cash_weight_pct"], 10.0)
            self.assertEqual(portfolio["cash_weight_pct"], 52.0)
            self.assertEqual(
                portfolio["cash_capacity_adjustment"]["candidate_capacity_cash_increase_pct"],
                42.0,
            )
            self.assertLessEqual(
                max(row["weight_pct"] for row in portfolio["holdings"]), 12.0
            )

    def test_rank_positions_treat_publicly_equal_float_tails_as_ties(self) -> None:
        left = _rank_positions(
            {"A": 12.0000000004, "B": 12.0, "C": 11.9999999996}
        )
        right = _rank_positions(
            {"A": 11.9999999997, "B": 12.0000000002, "C": 12.0}
        )
        self.assertEqual(left, {"A": 2.0, "B": 2.0, "C": 2.0})
        self.assertEqual(right, {"A": 2.0, "B": 2.0, "C": 2.0})
        self.assertEqual(_spearman(left, right), 1.0)

    def test_rank_positions_use_average_rank_for_partial_ties(self) -> None:
        ranks = _rank_positions(
            {"A": 12.004, "B": 12.001, "C": 10.004, "D": 10.001, "E": 8.0}
        )
        self.assertEqual(
            ranks,
            {"A": 1.5, "B": 1.5, "C": 3.5, "D": 3.5, "E": 5.0},
        )
        same_order = _rank_positions(
            {"A": 13.0, "B": 13.0, "C": 9.0, "D": 9.0, "E": 7.0}
        )
        self.assertEqual(_spearman(ranks, same_order), 1.0)

    def test_sell_side_profit_benchmarks_do_not_mix_accounting_bases(self) -> None:
        reports = [
            {
                "institution": "Morgan Stanley",
                "publish_date": "2026-07-28",
                "revenue": {"values": {"2027": 8100}},
                "profit": {
                    "basis": "ModelWare net income，卖方调整口径",
                    "values": {"2027": 2400},
                },
                "eps": {"basis": "摊薄EPS", "values": {"2027": 5.2}},
            },
            {
                "institution": "华泰证券",
                "publish_date": "2026-04-24",
                "revenue": {"values": {"2027": 8300}},
                "profit": {"basis": "归母净利润", "values": {"2027": 2200}},
                "eps": {"basis": "基本EPS", "values": {"2027": 4.8}},
            },
        ]
        grouped = _report_medians_by_basis(reports)
        period = _sell_side_period(
            {
                "revenue_medians": grouped["revenue"],
                "eps_medians_by_basis": grouped["eps_by_basis"],
                "profit_medians_by_basis": grouped["profit_by_basis"],
            },
            2027,
        )
        self.assertEqual(period["revenue_median"]["median"], 82.0)
        self.assertEqual(period["revenue_median"]["sample_size"], 2)
        self.assertTrue(period["eps_basis_heterogeneous"])
        self.assertNotIn(
            "median",
            period["eps_medians_by_basis"]["adjusted_eps_diluted"],
        )
        self.assertEqual(
            period["eps_medians_by_basis"]["adjusted_eps_diluted"]["single_forecast"],
            5.2,
        )
        self.assertEqual(
            period["eps_medians_by_basis"]["parent_profit_eps_basic"]["single_forecast"],
            4.8,
        )
        self.assertTrue(period["profit_basis_heterogeneous"])
        self.assertNotIn(
            "median",
            period["profit_medians_by_basis"]["adjusted_net_profit"],
        )
        self.assertEqual(
            period["profit_medians_by_basis"]["adjusted_net_profit"]["single_forecast"],
            24.0,
        )
        self.assertEqual(
            period["profit_medians_by_basis"]["parent_net_profit"]["single_forecast"],
            22.0,
        )

    def test_same_basis_sell_side_profit_requires_two_reports_for_median(self) -> None:
        reports = [
            {
                "institution": "机构甲",
                "publish_date": "2026-06-01",
                "profit": {"basis": "归母净利润", "values": {"2027": 1000}},
                "eps": {"basis": "最新摊薄每股收益", "values": {"2027": 1.0}},
            },
            {
                "institution": "机构乙",
                "publish_date": "2026-07-01",
                "profit": {"basis": "归属于母公司净利润", "values": {"2027": 1200}},
                "eps": {"basis": "最新摊薄每股收益", "values": {"2027": 1.2}},
            },
        ]
        grouped = _report_medians_by_basis(reports)
        result = grouped["profit_by_basis"]["parent_net_profit"]["2027"]
        self.assertEqual(result["status"], "same_metric_median")
        self.assertEqual(result["median"], 11.0)
        self.assertEqual(result["sample_size"], 2)
        self.assertEqual(result["publish_dates"], ["2026-06-01", "2026-07-01"])
        eps = grouped["eps_by_basis"]["parent_profit_eps_diluted"]["2027"]
        self.assertEqual(eps["median"], 1.1)
        self.assertEqual(eps["sample_size"], 2)

    def test_company_export_keeps_sell_side_benchmarks_separate_from_wind(self) -> None:
        reports = [
            {
                "institution": "Morgan Stanley",
                "publish_date": "2026-07-28",
                "revenue": {"values": {"2027": 8100}},
                "profit": {
                    "basis": "ModelWare net income，卖方调整口径",
                    "values": {"2027": 2400},
                },
                "eps": {"values": {"2027": 5.2}},
            },
            {
                "institution": "华泰证券",
                "publish_date": "2026-04-24",
                "revenue": {"values": {"2027": 8300}},
                "profit": {"basis": "归母净利润", "values": {"2027": 2200}},
                "eps": {"basis": "最新摊薄每股收益", "values": {"2027": 4.8}},
            },
        ]
        grouped = _report_medians_by_basis(reports)
        benchmark_set = _sell_side_period(
            {
                "revenue_medians": grouped["revenue"],
                "eps_medians_by_basis": grouped["eps_by_basis"],
                "profit_medians_by_basis": grouped["profit_by_basis"],
            },
            2027,
        )
        exported = _sell_side_benchmark_reconciliations(
            "688111.SH",
            {
                "periods": [{
                    "year": 2027,
                    "independent": {
                        "revenue_100m_cny": 80.0,
                        "parent_net_income_100m_cny": 21.0,
                    },
                    "sell_side_report_median": benchmark_set,
                }]
            },
            {
                ("688111.SH", "Morgan Stanley", "2026-07-28"): 0,
                ("688111.SH", "华泰证券", "2026-04-24"): 1,
            },
        )
        self.assertIn("sell_side_report", ALLOWED_BENCHMARK_TYPES)
        self.assertEqual(len(exported), 5)
        self.assertTrue(all(row["benchmark_type"] == "sell_side_report" for row in exported))
        revenue = next(row for row in exported if row["metric_name"] == "revenue")
        self.assertEqual(revenue["benchmark_value"], 82.0)
        self.assertEqual(revenue["decomposition"]["benchmark_record_type"], "same_basis_median")
        self.assertEqual(revenue["decomposition"]["sample_size"], 2)
        adjusted = next(
            row for row in exported
            if row["decomposition"]["accounting_basis_group"] == "adjusted_net_profit"
        )
        self.assertIsNone(adjusted["independent_value"])
        self.assertEqual(adjusted["benchmark_value"], 24.0)
        parent = next(
            row for row in exported
            if row["decomposition"]["accounting_basis_group"] == "parent_net_profit"
        )
        self.assertEqual(parent["independent_value"], 21.0)
        self.assertEqual(parent["benchmark_value"], 22.0)
        self.assertTrue(
            all(row["decomposition"]["wind_and_sell_side_kept_separate"] for row in exported)
        )

    def test_loss_company_skips_pe_and_unstable_roe_skips_pb_roe(self) -> None:
        companies = [_company(1, loss=True, stable_roe=False)] + [_company(index) for index in range(2, 5)]
        payload = self._run(companies)
        methods = payload["companies"]["600001.SH"]["valuation_methods"]
        self.assertEqual(next(item for item in methods if item["method"] == "Forward PE")["status"], "skipped")
        self.assertEqual(next(item for item in methods if item["method"].startswith("PB—ROE"))["status"], "skipped")

    def test_consensus_contamination_and_unannotated_assumption_are_rejected(self) -> None:
        companies = [_company(index) for index in range(1, 5)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            actual_path = root / "actual.json"
            assumption_path = root / "assumptions.json"
            snapshot = _snapshot(companies)
            snapshot["wind"]["consensus"] = {"600001.SH": {"WEST_SALES_FY1": 999}}
            actual_path.write_text(json.dumps(snapshot), encoding="utf-8")
            assumption_path.write_text(json.dumps(_assumptions(companies)), encoding="utf-8")
            with self.assertRaises(ModelContractError):
                build_independent_model([actual_path], assumption_path)

            snapshot["wind"].pop("consensus")
            actual_path.write_text(json.dumps(snapshot), encoding="utf-8")
            bad = _assumptions(companies)
            bad["companies"][0]["scenarios"]["base"]["2026"]["revenue_growth_pct"] = 8.0
            assumption_path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(ModelContractError):
                build_independent_model([actual_path], assumption_path)

    def test_balanced_selection_handles_uneven_direction_groups(self) -> None:
        candidates = [
            {"ticker": "A", "direction": "办公智能", "adjusted_float_cap": 100.0},
            {"ticker": "B", "direction": "企业软件", "adjusted_float_cap": 90.0},
            {"ticker": "C", "direction": "企业软件", "adjusted_float_cap": 80.0},
            {"ticker": "D", "direction": "企业软件", "adjusted_float_cap": 70.0},
        ]
        selected = _select_candidates(candidates, "balanced", 4)
        self.assertEqual([row["ticker"] for row in selected], ["A", "B", "C", "D"])


if __name__ == "__main__":
    unittest.main()
