from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "cache/chint_run15"
RUN_DIR = (
    ROOT
    / "opportunity_lens/research_outputs"
    / "20260725_chint_pv_profit_quality_run15"
)


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class Run15FinancialModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.wind = _load(CACHE / "wind_financial_snapshot_20260726.json")
        cls.reconciliation = _load(
            CACHE / "run15_external_reconciliation.json"
        )
        cls.model = _load(CACHE / "run15_chint_financial_model.json")
        cls.household_group_bridge = _load(
            CACHE / "run15_household_to_group_valuation_bridge.json"
        )
        cls.pack = _load(RUN_DIR / "run15_pack_stage.json")
        cls.export = _load(
            RUN_DIR / "company_financial_profile_export_v1.json"
        )
        cls.bridge_export = _load(
            RUN_DIR / "company_financial_profile_export_bridge_v1.json"
        )

    def test_wind_is_available_and_core_market_fields_are_present(self):
        self.assertEqual(self.wind["wind"]["status"], "ok")
        current = self.wind["wind"]["current"]
        for field in (
            "price",
            "market_cap_cny",
            "pe_ttm",
            "pe_forward",
            "pb",
            "roe",
            "roa",
            "eps_ttm",
            "bps_mrq",
        ):
            self.assertIsNotNone(current[field], field)
        self.assertIsNone(current["peg"])

    def test_financial_benchmark_uses_only_recent_two_quarters(self):
        policy = self.reconciliation["report_selection_policy"]
        cutoff = date.fromisoformat(policy["cutoff_date"])
        rows = self.reconciliation["benchmark_rows"]
        self.assertEqual(len(rows), 5)
        self.assertEqual(
            {row["institution"] for row in rows},
            {
                "国联民生证券",
                "光大证券",
                "兴业证券",
                "长江证券",
                "摩根士丹利",
            },
        )
        self.assertTrue(
            all(date.fromisoformat(row["report_date"]) >= cutoff for row in rows)
        )
        self.assertEqual(
            policy["older_company_reports_used_in_current_median"], 0
        )
        ms = next(
            row for row in rows if row["institution"] == "摩根士丹利"
        )
        self.assertEqual(
            ms["coverage_status"], "discontinued_on_report_date"
        )
        self.assertIn("wind_consensus", self.reconciliation)

    def test_equity_bridge_and_risk_sensitivities_reconcile(self):
        valuation = self.model["valuation"]
        bridge = valuation["estimated_2026_parent_equity_bridge"]
        expected = (
            bridge["beginning_parent_equity_100m_cny"]
            + bridge["parent_net_income_100m_cny"]
            - bridge["cash_dividend_100m_cny"]
        )
        self.assertAlmostEqual(
            expected, bridge["ending_parent_equity_100m_cny"], places=2
        )
        sensitivities = {
            row["name"]: row
            for row in self.model["risk_sensitivities"][
                "unit_sensitivities"
            ]
        }
        expense = sensitivities["经营与融资等扣减率每提高1个百分点"]
        self.assertAlmostEqual(
            expense["after_tax_parent_profit_impact_100m_cny"],
            4.46,
            places=2,
        )
        risk_2028 = self.model["risk_sensitivities"]["scenario_deltas"][2]
        self.assertAlmostEqual(
            risk_2028["parent_net_income_change_pct"], -49.68, places=2
        )
        self.assertAlmostEqual(
            risk_2028["free_cash_flow_change_pct"], -68.19, places=2
        )

    def test_public_report_names_institutions_and_dates(self):
        financial = next(
            row
            for row in self.pack["sections"]
            if row["section_key"] == "financial_model"
        )["body_markdown"]
        for text in (
            "国联民生，2026-04-16",
            "光大，2026-04-21",
            "兴业，2026-04-27",
            "长江，2026-05-07",
            "摩根士丹利，2026-05-18",
            "Wind一致预期，2026-07-24",
        ):
            self.assertIn(text, financial)
        self.assertNotIn("四家机构中位数", financial)
        self.assertIn("扣减率只比基准高1个百分点", financial)

    def test_company_export_uses_wind_as_primary_and_supersedes_old_models(
        self,
    ):
        company = self.export["companies"][0]
        market = [
            row for row in company["observations"]
            if row["fact_type"] == "market"
        ]
        for metric in ("pe_ttm", "pb", "roe", "roa", "eps", "bps"):
            row = next(item for item in market if item["metric_name"] == metric)
            self.assertEqual(row["provider"], "wind")
        tushare_market = [
            row for row in market if row["provider"] == "tushare"
        ]
        self.assertEqual(
            [row["metric_name"] for row in tushare_market],
            ["dividend_yield"],
        )
        for run in company["model_runs"]:
            self.assertTrue(run["run_key"].endswith(":v5"))
            self.assertGreaterEqual(len(run["supersedes_run_keys"]), 4)

    def test_core_valuation_is_derived_from_strict_method_intersection(self):
        valuation = self.model["valuation"]
        ranges = [
            (
                row["equity_value_low_100m_cny"],
                row["equity_value_high_100m_cny"],
            )
            for row in valuation["methods"]
        ]
        expected = [
            max(row[0] for row in ranges),
            min(row[1] for row in ranges),
        ]
        self.assertEqual(
            valuation["research_core_value_range_100m_cny"],
            expected,
        )
        self.assertEqual(
            valuation["research_core_price_range_cny"],
            [29.38, 31.5],
        )
        self.assertIn(
            "严格交集",
            valuation["research_core_derivation"]["method"],
        )

    def test_household_case_scales_to_portfolio_without_multiplying_one_off_loss(
        self,
    ):
        bridge = self.household_group_bridge
        portfolio = bridge["portfolio_calibration"]
        inputs = bridge["official_inputs"]
        expected_basic_revenue = (
            inputs["minimum_generation_guarantee_capacity_gw"]
            * 1_000_000_000
            * inputs["basic_om_price_cny_per_w_year"]
            / 100_000_000
        )
        self.assertAlmostEqual(
            portfolio["annualized_basic_om_revenue_100m_cny"],
            expected_basic_revenue,
            places=3,
        )
        self.assertAlmostEqual(
            portfolio["annualized_om_gross_profit_100m_cny"],
            portfolio["annualized_net_om_revenue_100m_cny"]
            * inputs["om_gross_margin_2024_pct"]
            / 100,
            places=3,
        )
        self.assertIn(
            "不能把一次屋顶维修机械乘到全部27GW",
            bridge["method_boundary"]["principle"],
        )

    def test_group_liability_and_price_decision_reconcile(self):
        bridge = self.household_group_bridge
        liability = bridge["tail_liability_diagnostics"]
        self.assertAlmostEqual(
            liability["expected_liabilities_to_2025_parent_ni_pct"],
            7.1619508841 / 45.01 * 100,
            places=2,
        )
        valuation = bridge["group_cash_flow_and_valuation"]
        self.assertEqual(valuation["current_market"]["price_cny"], 24.57)
        self.assertAlmostEqual(
            valuation["base_2026"]["pe_on_current_market_cap"],
            528.0 / 54.9,
            places=2,
        )
        self.assertEqual(
            valuation["risk_2026"]["price_at_current_pe_ttm_cny"],
            22.41,
        )
        self.assertEqual(
            bridge["price_decision_framework"][1]["price_range_cny"],
            "22—23",
        )

    def test_public_entity_connects_household_contract_to_group_valuation(self):
        section = next(
            row
            for row in self.pack["entity_sections"]
            if row["section_key"]
            == "household_contract_cashflow_case_deep_research"
        )
        body = section["body_markdown"]
        for expected in (
            "组合基础运维收入＝保障容量×基础运维单价",
            "27GW×0.0386元/W·年＝约10.42亿元",
            "2025年预计负债",
            "22—23元且经营现金流",
            "29.38—31.50元进入基准价值兑现区",
        ):
            self.assertIn(expected, body)
        self.assertNotIn(
            "对正泰的投资判断，应继续追踪",
            body,
        )
        self.assertLessEqual(body.count("\n|---"), 3)

    def test_bridge_export_updates_wind_market_and_company_summary(self):
        company = self.bridge_export["companies"][0]
        observations = {
            row["metric_name"]: row for row in company["observations"]
        }
        self.assertEqual(observations["close"]["value_num"], 24.57)
        self.assertEqual(observations["close"]["provider"], "wind")
        run = company["model_runs"][0]
        self.assertTrue(run["run_key"].endswith(":v2"))
        self.assertEqual(run["model_role"], "diagnostic")
        self.assertEqual(run["finalization"], "reviewed")
        summary = run["assumptions"]["company_detail_summary"]
        self.assertIn("不是风险收益比足够突出的强买点", summary["conclusion"])
        self.assertIn("22—23元", summary["buy_point_analysis"])


if __name__ == "__main__":
    unittest.main()
