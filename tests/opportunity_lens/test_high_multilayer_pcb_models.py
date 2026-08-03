from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.opportunity_lens.high_multilayer_pcb_models import calculate
from tools.opportunity_lens.build_high_multilayer_pcb_supply_demand_run_pack import (
    _fact_data_point,
    _fact_source,
    _normalize_source_provenance,
)
from tools.opportunity_lens.silicon_run_pack_support import _coverage_multiplier


ROOT = Path(__file__).resolve().parents[2]
INPUTS = ROOT / "opportunity_lens/research_outputs/20260720_high_multilayer_pcb_supply_demand_2026_2030/model_inputs.json"


class HighMultilayerPcbModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inputs = json.loads(INPUTS.read_text(encoding="utf-8"))
        cls.outputs = calculate(cls.inputs)

    def test_architecture_mix_sums_to_one(self) -> None:
        for row in self.outputs["yearly_architecture"].values():
            self.assertAlmostEqual(sum(row["mix"].values()), 1.0, places=5)

    def test_unit_conversion_is_dimensionally_consistent(self) -> None:
        row = self.outputs["scenarios"]["base"]["rows"][0]
        expected = (
            row["ai_server_units_million"]
            * row["weighted_strict_area_m2_per_server"]
            * row["blended_asp_usd_per_m2"]
            / 1000.0
        )
        self.assertAlmostEqual(row["bottom_up_demand_usd_bn"], expected, places=3)

    def test_noncomparable_market_reference_is_not_supply_denominator(self) -> None:
        self.assertFalse(
            self.outputs["cross_check"]
            ["noncomparable_22plus_market_reference_used_as_supply_denominator"]
        )

    def test_scenario_demand_is_ordered(self) -> None:
        self.assertTrue(self.outputs["cross_check"]["scenario_ordering_2030"])

    def test_supply_balance_reconciles(self) -> None:
        for path in self.outputs["conditional_supply_paths"].values():
            for row in path["rows"]:
                self.assertAlmostEqual(
                    row["conditional_supply_area_million_m2"]
                    - row["base_demand_area_million_m2"],
                    row["conditional_supply_minus_demand_area_million_m2"],
                    places=3,
                )

    def test_uncalibrated_price_and_margin_forecast_is_not_emitted(self) -> None:
        self.assertNotIn("elasticity", self.inputs)
        for path in self.outputs["conditional_supply_paths"].values():
            for row in path["rows"]:
                self.assertNotIn("illustrative_price_change_pct", row)
                self.assertNotIn("illustrative_gross_margin_change_ppt", row)

    def test_required_supply_growth_is_physical_area_threshold(self) -> None:
        base = self.outputs["scenarios"]["base"]["rows"]
        expected = (
            base[-1]["strict_demand_area_million_m2"]
            / base[0]["strict_demand_area_million_m2"]
        ) ** (1 / 4) - 1
        self.assertAlmostEqual(
            self.outputs["cross_check"]["base_required_effective_supply_area_cagr_2026_2030"],
            expected,
            places=5,
        )
        for path in self.outputs["conditional_supply_paths"].values():
            self.assertFalse(self.outputs["cross_check"]["conditional_supply_anchor_is_observed"])
            self.assertEqual(
                path["rows"][0]["conditional_supply_area_million_m2"],
                base[0]["strict_demand_area_million_m2"],
            )

    def test_china_demand_share_uses_each_scenario_band(self) -> None:
        bands = {"conservative": "low", "base": "base", "optimistic": "high"}
        for scenario_key, band in bands.items():
            scenario = self.outputs["scenarios"][scenario_key]
            self.assertEqual(scenario["china_end_demand_share_band"], band)
            for row in scenario["rows"]:
                expected = self.inputs["china_end_demand_share"][band][str(row["year"])]
                self.assertAlmostEqual(row["china_end_demand_share_assumption"], expected)
                self.assertAlmostEqual(
                    row["china_end_demand_usd_bn"] + row["overseas_end_demand_usd_bn"],
                    row["bottom_up_demand_usd_bn"],
                    places=3,
                )

    def test_factor_coverage_thresholds_are_stable_at_decimal_boundaries(self) -> None:
        self.assertEqual(_coverage_multiplier(0.50), 0.60)
        self.assertEqual(_coverage_multiplier(0.65), 0.85)
        self.assertEqual(_coverage_multiplier(0.80), 1.00)
        self.assertEqual(_coverage_multiplier(0.35 + 0.30), 0.85)
        self.assertEqual(_coverage_multiplier(0.50 - 0.000001), 0.00)
        self.assertEqual(_coverage_multiplier(0.65 - 0.000001), 0.60)
        self.assertEqual(_coverage_multiplier(0.80 - 0.000001), 0.85)

    def test_joint_derivations_keep_explicit_lineage_without_new_evidence_groups(self) -> None:
        ledger_path = ROOT / "cache/opportunity_lens/high_multilayer_pcb_20260720/agent_demand_bom/ledger.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        facts = {str(row["fact_id"]): row for row in ledger["facts"]}
        expected = {
            "DF006": ["DMD-DF001", "DMD-DF005"],
            "AR004": ["DMD-AR001", "DMD-AR002", "DMD-AR003"],
            "PB012": ["DMD-AR001", "DMD-AR002", "DMD-AR003", "DMD-PB004", "DMD-PB005"],
        }
        sources = {
            fact_id: _fact_source("DMD", facts[fact_id], ledger_path)
            for fact_id in {"DF001", "DF006", "AR001", "AR004", "PB012"}
        }
        _normalize_source_provenance(list(sources.values()))
        for fact_id, underlying_refs in expected.items():
            source = _fact_source("DMD", facts[fact_id], ledger_path)
            point = _fact_data_point("DMD", facts[fact_id], source)
            self.assertNotIn("url", source)
            self.assertEqual(source["publisher"], "本研究计算底稿")
            self.assertEqual(source["underlying_source_refs"], underlying_refs)
            self.assertEqual(point["underlying_source_refs"], underlying_refs)
            self.assertFalse(str(source["independence_key"]).startswith("derived:"))
        self.assertEqual(
            sources["DF006"]["independence_key"],
            sources["DF001"]["independence_key"],
        )
        self.assertEqual(
            sources["AR004"]["independence_key"],
            sources["AR001"]["independence_key"],
        )
        self.assertEqual(
            sources["PB012"]["independence_key"],
            sources["AR001"]["independence_key"],
        )

    def test_latest_wus_judgments_share_one_group_and_remain_qualified(self) -> None:
        ledger = json.loads(
            (
                ROOT
                / "cache/opportunity_lens/high_multilayer_pcb_20260720/agent_supply_company/ledger.json"
            ).read_text(encoding="utf-8")
        )
        rows = [row for row in ledger["facts"] if str(row["fact_id"]).startswith("SUP-WUS-00")]
        latest = [row for row in rows if row["fact_id"] in {"SUP-WUS-007", "SUP-WUS-008", "SUP-WUS-009"}]
        self.assertEqual(len(latest), 3)
        self.assertEqual({row["independence_key"] for row in latest}, {"issuer:wus:20260624-ir"})
        self.assertEqual({row["source_review_status"] for row in latest}, {"pass_with_note"})


if __name__ == "__main__":
    unittest.main()
