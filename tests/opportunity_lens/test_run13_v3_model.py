from __future__ import annotations

import unittest

from tools.opportunity_lens.run13_financial_model import build_model
from tools.opportunity_lens.run13_pack_builder import build_pack


class Run13V4ModelTests(unittest.TestCase):
    def test_significant_damage_threshold_matches_probability_bucket(self):
        model = build_model()
        probability = model["probability_model"]
        contract = probability["competition_severity_contract"]
        self.assertIn("不足20%", contract["温和或可吸收的竞争加剧"])
        self.assertIn("20%至30%", contract["明显竞争恶化"])
        self.assertIn("30%以上", contract["严重结构性恶化"])

        significant = probability["significant_damage_probability"]
        self.assertNotIn("exposure_assumptions_non_external_fact", significant)
        for horizon in ("3y", "5y"):
            entry = probability["joint_results_pct"][horizon]["central"][
                "at_least_one_pct"
            ]
            distribution = probability[
                "conditional_competition_distributions_pct"
            ][horizon]["基准判断"]
            expected = round(
                entry
                * (
                    distribution["明显竞争恶化_pct"]
                    + distribution["严重结构性恶化_pct"]
                )
                / 100
            )
            self.assertEqual(
                significant["central_pct"][f"innolight_{horizon}"], expected
            )
            self.assertEqual(
                significant["central_pct"][f"eoptolink_{horizon}"], expected
            )

    def test_horizon_and_financial_downgrade_are_explicit(self):
        model = build_model()
        self.assertEqual(model["model_version"], "run13.independent_model.v4")
        horizon = model["probability_model"]["event_contract"][
            "horizon_definition"
        ]
        self.assertIn("2029年7月22日", horizon)
        self.assertIn("2031年7月22日", horizon)
        self.assertEqual(
            model["financial_model_level"]["level"],
            "Level 3 财务桥接与条件压力测试",
        )
        for company in ("innolight", "eoptolink"):
            self.assertTrue({"2023", "2024", "2025"}.issubset(model["actuals"][company]))
            self.assertGreaterEqual(len(model["baseline"][company]), 6)

    def test_probability_and_financial_outputs_are_not_false_precision(self):
        model = build_model()
        damage = model["probability_model"]["significant_damage_probability"]
        self.assertEqual(damage["central_pct"]["innolight_3y"], 26)
        self.assertEqual(damage["central_pct"]["innolight_5y"], 40)
        self.assertEqual(damage["sensitivity_range_pct"]["innolight_3y"], [17, 36])
        self.assertEqual(damage["sensitivity_range_pct"]["innolight_5y"], [30, 51])

    def test_entrant_group_cases_separate_revenue_profit_and_cash(self):
        model = build_model()
        luxshare = model["entrant_business_cases"]["luxshare"][
            "成为全球重要第二供应商"
        ][-1]
        byd = model["entrant_business_cases"]["byd"][
            "成为全球重要第二供应商"
        ][-1]
        self.assertEqual(luxshare["year"], 2031)
        self.assertEqual(luxshare["optical_revenue_cny_100m"], 500.0)
        self.assertEqual(luxshare["incremental_parent_net_income_cny_100m"], 60.0)
        self.assertEqual(luxshare["optical_project_free_cash_flow_cny_100m"], 28.0)
        self.assertEqual(byd["optical_revenue_cny_100m"], 300.0)
        self.assertAlmostEqual(byd["listed_parent_attribution_pct"], 65.76)
        self.assertEqual(byd["incremental_parent_net_income_cny_100m"], 13.81)
        self.assertEqual(byd["optical_project_free_cash_flow_cny_100m"], -7.2)

    def test_pack_has_four_separate_entities_and_human_facing_links(self):
        pack = build_pack()
        entity_keys = {item["key"] for item in pack["entities"]}
        self.assertEqual(
            entity_keys,
            {
                "byd_entry_risk",
                "luxshare_entry_risk",
                "innolight_profitability_risk",
                "eoptolink_profitability_risk",
            },
        )
        self.assertEqual(
            {item["ticker"] for item in pack["entity_investment_targets"]},
            {"002594.SZ", "002475.SZ", "300308.SZ", "300502.SZ"},
        )
        public_text = "\n".join(
            item["body_markdown"]
            for item in [*pack["sections"], *pack["entity_sections"]]
        )
        self.assertNotIn("Wind内网代理", public_text)
        self.assertNotIn("ErrorCode=-1", public_text)
        self.assertIn("[中际旭创](/company/1)", public_text)
        self.assertIn("[新易盛](/company/2)", public_text)
        self.assertIn("[立讯精密](/company/14)", public_text)
        self.assertIn("[比亚迪](/company/414)", public_text)
        self.assertIn("全球第二供应商情景在2031年使用14%", public_text)
        self.assertIn("PB、ROE、ROA与估值结论", public_text)


if __name__ == "__main__":
    unittest.main()
