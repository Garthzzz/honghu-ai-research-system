from __future__ import annotations

import inspect
import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import numpy as np

import tools.opportunity_lens.byd_luxshare_competition_model as competition_model
from tools.opportunity_lens.byd_luxshare_competition_model import (
    ARCHITECTURE_STATES,
    ENTRY_SCENARIOS,
    FINANCIAL_V2_SCHEMA,
    PROBABILITY_V2_SCHEMA,
    SCENARIOS,
    _joint_subset_arrays,
    build_model,
    calculate_financial_scenarios,
    joint_bernoulli_probabilities,
    run_probability_sensitivity,
    simulate_probability_tree,
    terminal_value,
    write_plotly_dashboard,
)


class BydLuxshareCompetitionModelTests(unittest.TestCase):
    @staticmethod
    def _v2_probability_config():
        return {
            "schema_version": PROBABILITY_V2_SCHEMA,
            "event_contract": {
                "version": "meaningful_entry.v1",
                "as_of_date": "2026-07-18",
                "horizons": {"3y": "2029-07-18", "5y": "2031-07-18"},
                "meaningful_entry": "800G+ 产品、客户资格、重复商业交付和规模阈值同时成立",
                "china_entry": "满足总进入且中国客户资格与重复交付闭环",
                "global_entry": "全球头部客户侧或监管侧闭环且满足有意义进入",
                "deterioration": "相对冻结反事实基线按 ASP、份额、毛利和 FCF 阈值分类",
            },
            "entrants": {
                "byd": {
                    "3y": [0.06, 0.12, 0.22],
                    "5y": [0.18, 0.30, 0.45],
                    "china_given_entry_3y": [0.55, 0.75, 0.90],
                    "china_given_entry_5y": [0.60, 0.78, 0.92],
                    "global_given_entry_3y": [0.02, 0.06, 0.15],
                    "global_given_entry_5y": [0.08, 0.20, 0.35],
                },
                "luxshare": {
                    "3y": [0.32, 0.45, 0.60],
                    "5y": [0.50, 0.66, 0.80],
                    "china_given_entry_3y": [0.65, 0.82, 0.94],
                    "china_given_entry_5y": [0.70, 0.85, 0.96],
                    "global_given_entry_3y": [0.08, 0.18, 0.32],
                    "global_given_entry_5y": [0.22, 0.40, 0.60],
                },
            },
            "frechet_dependence_lambda": {
                "entry": [0.15, 0.40, 0.65],
                "global": [0.25, 0.50, 0.75],
                "china": [0.20, 0.45, 0.70],
                "geography_overlap": [0.10, 0.35, 0.60],
            },
            "architecture": {
                "hybrid_probability": {
                    "3y": [0.15, 0.25, 0.35],
                    "5y": [0.25, 0.38, 0.52],
                },
                "cpo_incremental_risk_probability": {
                    "3y": [0.02, 0.04, 0.08],
                    "5y": [0.05, 0.10, 0.18],
                },
            },
        }

    def test_joint_distribution_preserves_marginals(self):
        result = joint_bernoulli_probabilities(0.35, 0.60, 0.45)
        self.assertAlmostEqual(sum(result.values()), 1.0)
        self.assertAlmostEqual(result["both"] + result["byd_only"], 0.35)
        self.assertAlmostEqual(result["both"] + result["luxshare_only"], 0.60)

    def test_subset_joint_respects_explicit_minimum_even_with_positive_lambda(self):
        result = _joint_subset_arrays(
            np.array([0.40]),
            np.array([0.20]),
            np.array([0.50]),
            np.array([0.10]),
            minimum_both=np.array([0.19]),
        )
        self.assertGreaterEqual(result["both"][0], 0.19)
        self.assertAlmostEqual(sum(values[0] for values in result.values()), 1.0)

    def test_probability_tree_is_coherent(self):
        config = {
            "entrants": {
                "byd": {
                    "3y": [0.10, 0.15, 0.20],
                    "5y": [0.25, 0.32, 0.42],
                    "global_given_entry_3y": [0.05, 0.10, 0.18],
                    "global_given_entry_5y": [0.12, 0.24, 0.38],
                },
                "luxshare": {
                    "3y": [0.30, 0.40, 0.50],
                    "5y": [0.48, 0.60, 0.72],
                    "global_given_entry_3y": [0.12, 0.22, 0.35],
                    "global_given_entry_5y": [0.25, 0.40, 0.58],
                },
            },
            "entry_dependence": [0.20, 0.40, 0.60],
            "global_dependence": [0.20, 0.45, 0.65],
            "architecture_override": [0.03, 0.06, 0.10],
            "severe_if_both_global": [0.20, 0.35, 0.55],
        }
        result = simulate_probability_tree(config, samples=20_000, seed=7)
        for horizon in ("3y", "5y"):
            probabilities = result["horizons"][horizon]["scenario_probability"]
            self.assertEqual(set(probabilities), set(SCENARIOS))
            self.assertTrue(math.isclose(sum(probabilities.values()), 1.0, abs_tol=1e-9))
        self.assertGreater(
            result["horizons"]["5y"]["marginal_probability"]["byd_meaningful_entry"],
            result["horizons"]["3y"]["marginal_probability"]["byd_meaningful_entry"],
        )

    def test_terminal_value_falls_when_wacc_rises(self):
        self.assertGreater(terminal_value(100, 0.10, 0.03), terminal_value(100, 0.14, 0.03))
        with self.assertRaisesRegex(ValueError, "自由现金流为正"):
            terminal_value(0, 0.12, 0.03)
        with self.assertRaisesRegex(ValueError, "自由现金流为正"):
            terminal_value(-1, 0.12, 0.03)

    def test_v2_probability_paths_are_monotone_and_have_intervals(self):
        result = simulate_probability_tree(
            self._v2_probability_config(), samples=20_000, seed=19
        )
        self.assertEqual(result["schema_version"], PROBABILITY_V2_SCHEMA)
        self.assertEqual(result["event_contract"]["version"], "meaningful_entry.v1")
        for minimum_difference in result["monotonic_parameter_path_audit"].values():
            self.assertGreaterEqual(minimum_difference, 0.0)
        for horizon in ("3y", "5y"):
            current = result["horizons"][horizon]
            self.assertEqual(set(current["scenario_probability"]), set(ENTRY_SCENARIOS))
            self.assertTrue(
                math.isclose(
                    sum(current["scenario_probability"].values()),
                    1.0,
                    abs_tol=1e-7,
                )
            )
            for summary in current["entry_state_probability_summary"].values():
                self.assertLessEqual(summary["p10"], summary["median"])
                self.assertLessEqual(summary["median"], summary["p90"])
                self.assertIn("outer_mc_standard_error", summary)
            marginal = current["marginal_probability"]
            self.assertLessEqual(
                marginal["byd_china_entry"], marginal["byd_meaningful_entry"]
            )
            self.assertLessEqual(
                marginal["luxshare_china_entry"],
                marginal["luxshare_meaningful_entry"],
            )
            self.assertLessEqual(
                marginal["byd_global_entry"], marginal["byd_meaningful_entry"]
            )
            self.assertLessEqual(
                marginal["luxshare_global_entry"],
                marginal["luxshare_meaningful_entry"],
            )
            self.assertTrue(
                math.isclose(
                    sum(current["geography_scope_probability"].values()),
                    1.0,
                    abs_tol=1e-7,
                )
            )
            for company_states in current[
                "company_geography_probability"
            ].values():
                self.assertTrue(
                    math.isclose(sum(company_states.values()), 1.0, abs_tol=1e-7)
                )
            self.assertTrue(
                math.isclose(
                    sum(current["china_entry_joint_probability"].values()),
                    1.0,
                    abs_tol=1e-7,
                )
            )
            self.assertTrue(
                math.isclose(
                    sum(current["global_entry_joint_probability"].values()),
                    1.0,
                    abs_tol=1e-7,
                )
            )
            # V2 的 E/F 是互斥状态：E 恰好一家进入全球头部客户，F 两家均进入。
            # 因而 E+F 必须等于“至少一家进入全球头部客户”。
            self.assertTrue(
                math.isclose(
                    current["scenario_probability"]["E"]
                    + current["scenario_probability"]["F"],
                    current["marginal_probability"]["at_least_one_global_entry"],
                    abs_tol=1e-7,
                )
            )
            self.assertTrue(
                math.isclose(
                    current["scenario_probability"]["F"],
                    current["marginal_probability"]["both_global_entry"],
                    abs_tol=1e-7,
                )
            )
        for metric in (
            "byd_china_entry",
            "luxshare_china_entry",
            "byd_global_entry",
            "luxshare_global_entry",
        ):
            self.assertGreaterEqual(
                result["horizons"]["5y"]["marginal_probability"][metric],
                result["horizons"]["3y"]["marginal_probability"][metric],
            )
        for audit in result["geography_set_invariant_audit"].values():
            self.assertGreaterEqual(
                audit["min_system_both_minus_byd_both"], -1e-12
            )
            self.assertGreaterEqual(
                audit["min_system_both_minus_luxshare_both"], -1e-12
            )
        self.assertLess(
            result["numerical_convergence"]["max_probability_sum_abs_error"],
            1e-10,
        )

    def test_v2_architecture_is_orthogonal_and_g_does_not_override_entry(self):
        result = simulate_probability_tree(
            self._v2_probability_config(), samples=20_000, seed=23
        )
        five = result["horizons"]["5y"]
        self.assertEqual(set(five["architecture_probability"]), set(ARCHITECTURE_STATES))
        self.assertTrue(
            math.isclose(sum(five["architecture_probability"].values()), 1.0, abs_tol=1e-7)
        )
        self.assertTrue(
            math.isclose(sum(five["scenario_probability"].values()), 1.0, abs_tol=1e-7)
        )
        self.assertAlmostEqual(
            five["incremental_risk_labels"]["G"]["probability"],
            five["architecture_probability"]["C"],
        )
        self.assertTrue(
            five["incremental_risk_labels"]["G"][
                "underlying_entry_states_preserved"
            ]
        )
        conditional = five["conditional_deterioration_probability"][
            "conditional_on_at_least_one_entry"
        ]
        self.assertTrue(
            math.isclose(
                sum(conditional[state]["mean"] for state in ("mild", "material", "severe")),
                1.0,
                abs_tol=1e-7,
            )
        )

    def test_sensitivity_uses_common_random_numbers(self):
        config = self._v2_probability_config()
        config["sensitivity_cases"] = {
            "no_op": {"label": "不改变输入", "override": {}}
        }
        base_config = dict(config)
        base_config.pop("sensitivity_cases")
        base = simulate_probability_tree(base_config, samples=20_000, seed=31)
        result = run_probability_sensitivity(
            config, base, samples=20_000, seed=31
        )
        self.assertEqual(
            result["seed_policy"],
            "common_random_numbers_same_seed_and_sample_count",
        )
        for horizon in ("3y", "5y"):
            deltas = result["cases"]["no_op"]["horizons"][horizon][
                "delta_vs_base"
            ]
            self.assertTrue(all(value == 0 for value in deltas.values()))

    def test_v2_financial_terminal_excludes_transient_capex_and_working_capital(self):
        years = [2027, 2031]
        baseline = {
            str(year): {
                "revenue_cny_yi": 100.0,
                "gross_margin_pct": 40.0,
                "net_margin_pct": 25.0,
                "fcf_margin_pct": 20.0,
                "normalized_fcf_margin_pct": 20.0,
            }
            for year in years
        }
        neutral = {
            "share_loss_pct": 0,
            "extra_asp_pressure_pct": 0,
            "gross_margin_shock_ppt": 0,
        }
        transient = {
            **neutral,
            "expansion_capex_pct_revenue": {"2027": 0, "2031": 10},
            "working_capital_change_pct_revenue": {"2027": 0, "2031": 5},
        }
        entry_shocks = {state: dict(neutral) for state in ENTRY_SCENARIOS}
        entry_shocks["F"] = transient
        config = {
            "schema_version": FINANCIAL_V2_SCHEMA,
            "valuation_date": "2026-07-18",
            "years": years,
            "gross_to_net_pass_through": 0.72,
            "terminal": {
                "terminal_date": "2031-12-31",
                "wacc": 0.12,
                "perpetual_growth": 0.03,
                "sensitivity_wacc": [0.10, 0.12, 0.14],
                "sensitivity_growth": [0.02, 0.03, 0.04],
            },
            "companies": {
                "demo": {
                    "display_name": "示例公司",
                    "baseline": baseline,
                    "entry_state_shocks": entry_shocks,
                    "architecture_shocks": {
                        state: dict(neutral) for state in ARCHITECTURE_STATES
                    },
                }
            },
        }
        entry_probability = {state: 0.0 for state in ENTRY_SCENARIOS}
        entry_probability["F"] = 1.0
        architecture_probability = {state: 0.0 for state in ARCHITECTURE_STATES}
        architecture_probability["P"] = 1.0
        result = calculate_financial_scenarios(
            config, entry_probability, architecture_probability
        )
        company = result["companies"]["demo"]
        final_row = company["cross_state_rows"]["F|P"][-1]
        self.assertEqual(final_row["normalized_fcf_cny_yi"], 20.0)
        self.assertEqual(final_row["fcf_cny_yi"], 5.0)
        self.assertEqual(
            company["terminal_value_by_cross_state_cny_yi"]["F|P"],
            company["terminal_value_by_cross_state_cny_yi"]["A|P"],
        )
        self.assertLess(
            company["discounted_terminal_value_by_cross_state_cny_yi"]["F|P"],
            company["terminal_value_by_cross_state_cny_yi"]["F|P"],
        )
        self.assertTrue(result["terminal_policy"]["uses_normalized_fcf"])

    def test_v2_probability_weighted_margins_reconcile_from_weighted_amounts(self):
        baseline = {
            "2031": {
                "revenue_cny_yi": 100.0,
                "gross_margin_pct": 40.0,
                "net_margin_pct": 20.0,
                "fcf_margin_pct": 10.0,
                "normalized_fcf_margin_pct": 10.0,
            }
        }
        neutral = {
            "share_loss_pct": 0,
            "extra_asp_pressure_pct": 0,
            "gross_margin_shock_ppt": 0,
        }
        entry_shocks = {state: dict(neutral) for state in ENTRY_SCENARIOS}
        entry_shocks["F"] = {
            **neutral,
            "share_loss_pct": 50.0,
            "gross_margin_shock_ppt": 10.0,
        }
        config = {
            "schema_version": FINANCIAL_V2_SCHEMA,
            "valuation_date": "2026-07-18",
            "years": [2031],
            "gross_to_net_pass_through": 0.72,
            "terminal": {
                "terminal_date": "2031-12-31",
                "wacc": 0.12,
                "perpetual_growth": 0.03,
                "sensitivity_wacc": [0.12],
                "sensitivity_growth": [0.03],
            },
            "companies": {
                "demo": {
                    "display_name": "示例公司",
                    "baseline": baseline,
                    "entry_state_shocks": entry_shocks,
                    "architecture_shocks": {
                        state: dict(neutral) for state in ARCHITECTURE_STATES
                    },
                }
            },
        }
        entry_probability = {state: 0.0 for state in ENTRY_SCENARIOS}
        entry_probability["A"] = 0.5
        entry_probability["F"] = 0.5
        architecture_probability = {state: 0.0 for state in ARCHITECTURE_STATES}
        architecture_probability["P"] = 1.0
        result = calculate_financial_scenarios(
            config, entry_probability, architecture_probability
        )
        row = result["companies"]["demo"]["probability_weighted_rows"][0]

        self.assertEqual(row["revenue_cny_yi"], 75.0)
        self.assertEqual(row["gross_profit_cny_yi"], 27.5)
        self.assertEqual(row["gross_margin_pct"], 36.67)
        self.assertNotEqual(row["gross_margin_pct"], (40.0 + 30.0) / 2)
        self.assertAlmostEqual(
            row["gross_profit_cny_yi"] / row["revenue_cny_yi"] * 100,
            row["gross_margin_pct"],
            delta=0.01,
        )
        self.assertAlmostEqual(
            row["net_income_cny_yi"] / row["revenue_cny_yi"] * 100,
            row["net_margin_pct"],
            delta=0.01,
        )
        self.assertAlmostEqual(
            row["normalized_fcf_cny_yi"] / row["revenue_cny_yi"] * 100,
            row["normalized_fcf_margin_pct"],
            delta=0.01,
        )
        self.assertAlmostEqual(
            row["fcf_cny_yi"] / row["revenue_cny_yi"] * 100,
            row["fcf_margin_pct"],
            delta=0.01,
        )

    def test_v2_nonpositive_fcf_never_calls_gordon_terminal(self):
        baseline = {
            "2031": {
                "revenue_cny_yi": 100.0,
                "gross_margin_pct": 30.0,
                "net_margin_pct": 10.0,
                "fcf_margin_pct": 8.0,
                "normalized_fcf_margin_pct": 8.0,
            }
        }
        neutral = {
            "share_loss_pct": 0,
            "extra_asp_pressure_pct": 0,
            "gross_margin_shock_ppt": 0,
        }
        entry_shocks = {state: dict(neutral) for state in ENTRY_SCENARIOS}
        entry_shocks["F"] = {
            **neutral,
            "normalized_other_fcf_drag_ppt": 20.0,
        }
        config = {
            "schema_version": FINANCIAL_V2_SCHEMA,
            "valuation_date": "2026-07-18",
            "years": [2031],
            "terminal": {
                "terminal_date": "2031-12-31",
                "wacc": 0.12,
                "perpetual_growth": 0.03,
                "sensitivity_wacc": [0.12],
                "sensitivity_growth": [0.03],
            },
            "companies": {
                "demo": {
                    "display_name": "示例公司",
                    "baseline": baseline,
                    "entry_state_shocks": entry_shocks,
                    "architecture_shocks": {
                        state: dict(neutral) for state in ARCHITECTURE_STATES
                    },
                }
            },
        }
        entry_probability = {state: 0.0 for state in ENTRY_SCENARIOS}
        entry_probability["A"] = 0.5
        entry_probability["F"] = 0.5
        architecture_probability = {state: 0.0 for state in ARCHITECTURE_STATES}
        architecture_probability["P"] = 1.0
        original_terminal_value = competition_model.terminal_value

        def positive_fcf_only(fcf, wacc, perpetual_growth):
            self.assertGreater(fcf, 0)
            return original_terminal_value(fcf, wacc, perpetual_growth)

        with mock.patch.object(
            competition_model,
            "terminal_value",
            side_effect=positive_fcf_only,
        ):
            result = calculate_financial_scenarios(
                config, entry_probability, architecture_probability
            )
        company = result["companies"]["demo"]
        self.assertEqual(company["terminal_value_by_cross_state_cny_yi"]["F|P"], 0)
        self.assertFalse(
            company["terminal_value_applicable_by_cross_state"]["F|P"]
        )
        self.assertIn(
            "不适用",
            company["terminal_value_inapplicable_reason_by_cross_state"]["F|P"],
        )
        self.assertEqual(
            company["terminal_value_zero_floor_by_cross_state_cny_yi"]["F|P"],
            0.0,
        )
        self.assertEqual(
            company["probability_weighted_terminal_zero_floor_uplift_cny_yi"],
            0.0,
        )
        self.assertEqual(
            company["probability_weighted_terminal_value_zero_floor_cny_yi"],
            company["probability_weighted_terminal_value_cny_yi"],
        )
        sensitivity = company["terminal_sensitivity"][0]
        self.assertEqual(
            sensitivity["aggregation_method"],
            "state_level_positive_normalized_fcf_only_gordon_"
            "then_probability_weight;nonpositive_states_"
            "marked_not_applicable_and_counted_as_zero",
        )
        self.assertEqual(
            sensitivity["terminal_value_zero_floor_cny_yi"],
            sensitivity["terminal_value_cny_yi"],
        )
        self.assertEqual(sensitivity["not_applicable_state_count"], 3)
        self.assertEqual(
            company["nonpositive_terminal_states"][0]["cross_state"], "F|P"
        )
        self.assertFalse(
            result["terminal_policy"]["zero_floor_sensitivity_is_reported"]
        )
        self.assertTrue(
            result["terminal_policy"]["positive_normalized_fcf_required"]
        )
        self.assertFalse(
            result["terminal_policy"]["liquidation_recovery_or_recapitalization_modeled"]
        )

    def test_v2_exposure_zero_and_full_income_boundaries(self):
        baseline = {
            "2031": {
                "revenue_cny_yi": 100.0,
                "gross_margin_pct": 40.0,
                "net_margin_pct": 25.0,
                "fcf_margin_pct": 20.0,
                "normalized_fcf_margin_pct": 20.0,
            }
        }
        neutral = {
            "share_loss_pct": 0,
            "extra_asp_pressure_pct": 0,
            "gross_margin_shock_ppt": 0,
        }
        entry_shocks = {state: dict(neutral) for state in ENTRY_SCENARIOS}
        entry_shocks["F"] = {
            **neutral,
            "share_loss_pct": 20.0,
            "extra_asp_pressure_pct": 10.0,
            "gross_margin_shock_ppt": 5.0,
            "expansion_capex_cny_yi": 10.0,
            "working_capital_change_cny_yi": 5.0,
        }
        config = {
            "schema_version": FINANCIAL_V2_SCHEMA,
            "valuation_date": "2026-07-18",
            "years": [2031],
            "terminal": {
                "terminal_date": "2031-12-31",
                "wacc": 0.12,
                "perpetual_growth": 0.03,
                "sensitivity_wacc": [0.12],
                "sensitivity_growth": [0.03],
            },
            "companies": {
                "demo": {
                    "display_name": "示例公司",
                    "baseline": baseline,
                    "entry_state_shocks": entry_shocks,
                    "architecture_shocks": {
                        state: dict(neutral) for state in ARCHITECTURE_STATES
                    },
                }
            },
        }
        entry_probability = {state: 0.0 for state in ENTRY_SCENARIOS}
        entry_probability["F"] = 1.0
        architecture_probability = {state: 0.0 for state in ARCHITECTURE_STATES}
        architecture_probability["P"] = 1.0

        config["companies"]["demo"]["high_speed_revenue_exposure_share"] = 0.0
        no_exposure = calculate_financial_scenarios(
            config, entry_probability, architecture_probability
        )["companies"]["demo"]
        no_exposure_row = no_exposure["cross_state_rows"]["F|P"][0]
        baseline_row = no_exposure["cross_state_rows"]["A|P"][0]
        for field in (
            "revenue_cny_yi",
            "gross_margin_pct",
            "net_income_cny_yi",
            "fcf_cny_yi",
        ):
            self.assertEqual(no_exposure_row[field], baseline_row[field])

        config["companies"]["demo"]["high_speed_revenue_exposure_share"] = 0.5
        half_exposure = calculate_financial_scenarios(
            config, entry_probability, architecture_probability
        )["companies"]["demo"]
        half_exposure_row = half_exposure["cross_state_rows"]["F|P"][0]
        self.assertEqual(half_exposure_row["revenue_cny_yi"], 86.0)
        self.assertEqual(half_exposure_row["gross_profit_cny_yi"], 32.6)
        self.assertEqual(half_exposure_row["gross_margin_pct"], 37.91)

        config["companies"]["demo"]["high_speed_revenue_exposure_share"] = 1.0
        full_exposure = calculate_financial_scenarios(
            config, entry_probability, architecture_probability
        )["companies"]["demo"]
        full_exposure_row = full_exposure["cross_state_rows"]["F|P"][0]
        self.assertEqual(full_exposure_row["revenue_cny_yi"], 72.0)
        self.assertEqual(
            full_exposure_row["revenue_cny_yi"],
            100.0 * (1.0 - 0.20) * (1.0 - 0.10),
        )
        self.assertEqual(full_exposure_row["gross_margin_pct"], 35.0)
        self.assertLess(
            full_exposure_row["fcf_cny_yi"], no_exposure_row["fcf_cny_yi"]
        )

    def test_dashboard_uses_human_labels_without_internal_probability_terms(self):
        probability_summary = {
            key: {"mean": value}
            for key, value in {
                "byd_china_entry": 0.10,
                "byd_global_entry": 0.02,
                "luxshare_china_entry": 0.35,
                "luxshare_global_entry": 0.12,
                "at_least_one_china_entry": 0.40,
                "at_least_one_global_entry": 0.13,
                "both_china_entry": 0.05,
                "both_global_entry": 0.01,
            }.items()
        }
        scenario_probability = {
            state: value
            for state, value in zip(
                ENTRY_SCENARIOS,
                (0.40, 0.20, 0.10, 0.10, 0.15, 0.05),
            )
        }
        model = {
            "probability": {
                "horizons": {
                    "3y": {
                        "marginal_probability_summary": probability_summary,
                    },
                    "5y": {
                        "marginal_probability_summary": probability_summary,
                        "scenario_probability": scenario_probability,
                        "architecture_probability": {
                            "P": 0.60,
                            "H": 0.30,
                            "C": 0.10,
                        },
                    },
                }
            },
            "market": {
                "rows": [
                    {
                        "year": 2031,
                        "normal_market_revenue_usd_bn": 25.33,
                        "qualified_supply_demand_ratio": 1.30,
                    }
                ]
            },
            "financial": {
                "companies": {
                    "demo": {
                        "display_name": "示例公司",
                        "probability_weighted_rows": [
                            {"year": 2031, "fcf_cny_yi": 100.0}
                        ],
                        "terminal_sensitivity": [
                            {
                                "wacc": 0.12,
                                "perpetual_growth": 0.03,
                                "terminal_value_cny_yi": 1000.0,
                            }
                        ],
                    }
                }
            },
        }
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "dashboard.html"
            write_plotly_dashboard(model, output_path)
            html = output_path.read_text(encoding="utf-8")

        self.assertIn("结构化工作判断，不是历史频率", html)
        self.assertIn("全公司收入均受竞争影响时的自由现金流上限压力测试", html)
        self.assertIn("正常化自由现金流为正时的持续经营终值", html)
        dashboard_source = inspect.getsource(write_plotly_dashboard)
        for forbidden in (
            "P10—P90",
            "正交架构维度",
            "A—F",
            "P/H/C",
            "signed",
            "zero-floor",
        ):
            self.assertNotIn(forbidden, dashboard_source)

    def test_v2_revenue_sensitivity_keeps_fixed_amount_shocks_unscaled(self):
        baseline = {
            "2031": {
                "revenue_cny_yi": 100.0,
                "gross_margin_pct": 40.0,
                "net_margin_pct": 25.0,
                "fcf_margin_pct": 20.0,
                "normalized_fcf_margin_pct": 20.0,
            }
        }
        neutral = {
            "share_loss_pct": 0,
            "extra_asp_pressure_pct": 0,
            "gross_margin_shock_ppt": 0,
        }
        fixed_cash_shock = {
            **neutral,
            "expansion_capex_cny_yi": 10.0,
            "working_capital_change_cny_yi": 5.0,
        }
        entry_shocks = {
            state: dict(neutral) for state in ENTRY_SCENARIOS
        }
        entry_shocks["F"] = fixed_cash_shock
        config = {
            "schema_version": FINANCIAL_V2_SCHEMA,
            "valuation_date": "2026-07-18",
            "years": [2031],
            "terminal": {
                "terminal_date": "2031-12-31",
                "wacc": 0.12,
                "perpetual_growth": 0.03,
                "sensitivity_wacc": [0.12],
                "sensitivity_growth": [0.03],
            },
            "companies": {
                "demo": {
                    "display_name": "示例公司",
                    "baseline": baseline,
                    "baseline_revenue_sensitivity": {
                        "low": [50.0],
                        "base": [100.0],
                        "high": [150.0],
                    },
                    "entry_state_shocks": entry_shocks,
                    "architecture_shocks": {
                        state: dict(neutral)
                        for state in ARCHITECTURE_STATES
                    },
                }
            },
        }
        entry_probability = {state: 0.0 for state in ENTRY_SCENARIOS}
        entry_probability["F"] = 1.0
        architecture_probability = {
            state: 0.0 for state in ARCHITECTURE_STATES
        }
        architecture_probability["P"] = 1.0
        result = calculate_financial_scenarios(
            config, entry_probability, architecture_probability
        )
        outputs = result["companies"]["demo"][
            "baseline_revenue_sensitivity_outputs"
        ]
        self.assertEqual(outputs["base"]["rows"][0]["actual_fcf_cny_yi"], 5.0)
        self.assertEqual(outputs["low"]["rows"][0]["actual_fcf_cny_yi"], -5.0)
        self.assertEqual(outputs["high"]["rows"][0]["actual_fcf_cny_yi"], 15.0)
        self.assertIn("固定金额", outputs["low"]["method"])

    def test_severe_scenario_reduces_fcf(self):
        years = [2027, 2028, 2029, 2030, 2031]
        baseline = {
            str(year): {
                "revenue_cny_yi": 100 + (year - 2027) * 10,
                "gross_margin_pct": 40,
                "net_margin_pct": 25,
                "fcf_margin_pct": 20,
            }
            for year in years
        }
        neutral = {
            "share_loss_pct": 0,
            "extra_asp_pressure_pct": 0,
            "gross_margin_shock_ppt": 0,
            "extra_capex_pct_revenue": 0,
            "working_capital_drag_pct_revenue": 0,
        }
        severe = {
            "share_loss_pct": {str(year): 2 * (year - 2026) for year in years},
            "extra_asp_pressure_pct": 8,
            "gross_margin_shock_ppt": 6,
            "extra_capex_pct_revenue": 2,
            "working_capital_drag_pct_revenue": 1,
        }
        shocks = {code: dict(neutral) for code in SCENARIOS}
        shocks["F"] = severe
        config = {
            "years": years,
            "gross_to_net_pass_through": 0.72,
            "terminal": {
                "wacc": 0.12,
                "perpetual_growth": 0.03,
                "sensitivity_wacc": [0.10, 0.12, 0.14],
                "sensitivity_growth": [0.02, 0.03, 0.04],
            },
            "companies": {
                "demo": {
                    "display_name": "示例公司",
                    "baseline": baseline,
                    "scenario_shocks": shocks,
                }
            },
        }
        probability = {code: 0.0 for code in SCENARIOS}
        probability["F"] = 1.0
        result = calculate_financial_scenarios(config, probability)
        severe_2031 = result["companies"]["demo"]["scenario_rows"]["F"][-1]["fcf_cny_yi"]
        baseline_2031 = baseline["2031"]["revenue_cny_yi"] * baseline["2031"]["fcf_margin_pct"] / 100
        self.assertLess(severe_2031, baseline_2031)

    def test_v2_financial_threshold_damage_classification_is_auditable(self):
        from tools.opportunity_lens.build_byd_luxshare_optical_competition_run_pack import (
            FINANCIAL_PATH,
            _load_json,
            _model_config,
        )

        model_config = _model_config(_load_json(FINANCIAL_PATH))
        model = build_model(
            model_config,
            samples=20_000,
            seed=20260718,
        )
        annual_schedule = model["financial"]["annual_probability_schedule"]
        annual_entry = annual_schedule["entry_state_probability"]
        annual_architecture = annual_schedule["architecture_probability"]
        for year in ("2026", "2027", "2028", "2029", "2030", "2031"):
            self.assertTrue(
                math.isclose(sum(annual_entry[year].values()), 1.0, abs_tol=1e-9)
            )
            self.assertTrue(
                math.isclose(
                    sum(annual_architecture[year].values()), 1.0, abs_tol=1e-9
                )
            )
            self.assertTrue(
                all(0.0 <= value <= 1.0 for value in annual_entry[year].values())
            )
            self.assertTrue(
                all(
                    0.0 <= value <= 1.0
                    for value in annual_architecture[year].values()
                )
            )
        cumulative_entry = [
            1.0 - annual_entry[str(year)]["A"]
            for year in range(2026, 2032)
        ]
        self.assertTrue(
            all(
                later + 1e-10 >= earlier
                for earlier, later in zip(
                    cumulative_entry, cumulative_entry[1:]
                )
            )
        )
        for state in ENTRY_SCENARIOS:
            self.assertAlmostEqual(
                annual_entry["2029"][state],
                model["probability"]["horizons"]["3y"][
                    "scenario_probability"
                ][state],
            )
            self.assertAlmostEqual(
                annual_entry["2031"][state],
                model["probability"]["horizons"]["5y"][
                    "scenario_probability"
                ][state],
            )
        for state in ARCHITECTURE_STATES:
            self.assertAlmostEqual(
                annual_architecture["2029"][state],
                model["probability"]["horizons"]["3y"][
                    "architecture_probability"
                ][state],
            )
            self.assertAlmostEqual(
                annual_architecture["2031"][state],
                model["probability"]["horizons"]["5y"][
                    "architecture_probability"
                ][state],
            )

        exposure = model["financial"]["exposure_sensitivity"]
        self.assertEqual(
            set(exposure["cases"]),
            {"exposure_50pct", "exposure_75pct", "exposure_100pct"},
        )
        self.assertTrue(
            exposure["cases"]["exposure_100pct"][
                "is_full_company_revenue_exposure_upper_bound"
            ]
        )
        for company_key in ("innolight", "eoptolink"):
            for field in (
                "2031_revenue_loss_pct",
                "2031_net_income_loss_pct",
                "2031_actual_fcf_loss_pct",
            ):
                losses = [
                    exposure["cases"][case]["companies"][company_key][field]
                    for case in (
                        "exposure_50pct",
                        "exposure_75pct",
                        "exposure_100pct",
                    )
                ]
                self.assertTrue(
                    all(
                        later + 0.02 >= earlier
                        for earlier, later in zip(losses, losses[1:])
                    )
                )
                normalized = [
                    losses[0] / 0.5,
                    losses[1] / 0.75,
                    losses[2] / 1.0,
                ]
                self.assertLess(max(normalized) - min(normalized), 0.03)

        entry_denominator = 1.0 - model["financial"]["entry_state_probability"]["A"]
        self.assertGreater(entry_denominator, 0.70)
        self.assertLess(entry_denominator, 0.75)
        for company_key in ("innolight", "eoptolink"):
            company = model["financial"]["companies"][company_key]
            summary = company["conditional_on_at_least_one_entry_2031"]
            self.assertAlmostEqual(
                summary["entry_probability_denominator"], entry_denominator, places=7
            )
            for field in ("revenue_cny_yi", "net_income_cny_yi", "fcf_cny_yi"):
                manual = sum(
                    probability
                    * next(
                        row
                        for row in company["cross_state_rows"][state]
                        if row["year"] == 2031
                    )[field]
                    for state, probability in model["financial"][
                        "cross_state_probability"
                    ].items()
                    if not state.startswith("A|")
                ) / entry_denominator
                self.assertAlmostEqual(summary["row"][field], manual, places=2)
                self.assertLess(
                    summary["row"][field], summary["reference_row"][field]
                )
            manual_terminal = sum(
                probability * company["terminal_value_by_cross_state_cny_yi"][state]
                for state, probability in model["financial"][
                    "cross_state_probability"
                ].items()
                if not state.startswith("A|")
            ) / entry_denominator
            self.assertAlmostEqual(
                summary["terminal_value_cny_yi"], manual_terminal, places=2
            )
            self.assertLess(
                summary["terminal_value_cny_yi"],
                summary["reference_terminal_value_cny_yi"],
            )

        expected_per_10pp = {
            "innolight": (1.175, 2.116, 4.589),
            "eoptolink": (1.368, 2.387, 5.520),
        }
        for company_key, expected in expected_per_10pp.items():
            full = exposure["cases"]["exposure_100pct"]["companies"][company_key]
            actual = (
                full["2031_revenue_loss_pct"] / 10.0,
                full["2031_net_income_loss_pct"] / 10.0,
                full["2031_actual_fcf_loss_pct"] / 10.0,
            )
            for actual_value, expected_value in zip(actual, expected):
                self.assertAlmostEqual(actual_value, expected_value, places=3)

        prior_bridge = model["probability"]["prior_update_bridge"]
        self.assertEqual(
            prior_bridge["validation_status"],
            "reconciled_to_probability_input_modes",
        )
        for horizon in ("3y", "5y"):
            for company in ("byd", "luxshare"):
                self.assertEqual(
                    prior_bridge["reconciliation"][horizon][company][
                        "reconciliation_error"
                    ],
                    0.0,
                )

        byd_inputs = model_config["probability"]["entrants"]["byd"]
        self.assertEqual(byd_inputs["3y"], [0.06, 0.13, 0.32])
        self.assertEqual(byd_inputs["5y"], [0.18, 0.32, 0.55])
        byd_updates = model_config["probability"]["prior_update_bridge"][
            "company_updates"
        ]["byd"]["updates"]
        update_ids = {row["update_id"] for row in byd_updates}
        self.assertIn("byd_no_public_named_800g_plus_sku", update_ids)
        sku_gap_update = next(
            row
            for row in byd_updates
            if row["update_id"] == "byd_no_public_named_800g_plus_sku"
        )
        self.assertEqual(
            sku_gap_update["delta_percentage_points"],
            {"3y": -5.0, "5y": -5.0},
        )
        self.assertEqual(sku_gap_update["claim_ids"], ["BYD-C03"])
        patent_update = next(
            row
            for row in byd_updates
            if row["update_id"] == "byd_systematic_vehicle_optical_patent_adjacency"
        )
        self.assertEqual(patent_update["delta_percentage_points"], {"3y": 1.0, "5y": 2.0})
        self.assertEqual(patent_update["claim_ids"], ["BYD-C04", "BYD-C13"])
        linkage = model["financial"]["geography_transmission_policy"]
        self.assertEqual(linkage["status"], "partial_reduced_form")
        self.assertIn("中国/全球概率矩阵用于地域诊断", linkage["notice"])
        for horizon in ("3y", "5y"):
            result = model["probability"]["horizons"][horizon][
                "financial_threshold_deterioration"
            ]
            conditional = result["conditional_on_at_least_one_entry"]
            self.assertTrue(
                math.isclose(sum(conditional.values()), 1.0, abs_tol=1e-7)
            )
            self.assertEqual(len(result["cross_state_classification"]), 18)
            self.assertLessEqual(result["probability_sum_error"], 1e-7)
            for company_distribution in result["conditional_by_company"].values():
                self.assertTrue(
                    math.isclose(
                        sum(company_distribution.values()),
                        1.0,
                        abs_tol=1e-7,
                    )
                )
            for row in result["cross_state_classification"]:
                if row["entry_state"] == "A":
                    self.assertEqual(
                        row["industry_worst_incumbent_classification"],
                        "not_applicable_no_entry",
                    )
                else:
                    self.assertIn(
                        row["industry_worst_incumbent_classification"],
                        ("mild", "material", "severe"),
                    )

        five_year_damage = model["probability"]["horizons"]["5y"][
            "financial_threshold_deterioration"
        ]["long_term_significant_damage"]
        entry_probability = model["probability"]["horizons"]["5y"][
            "financial_threshold_deterioration"
        ]["entry_probability_denominator"]
        self.assertGreaterEqual(
            five_year_damage["at_least_one_incumbent_conditional"],
            five_year_damage["both_incumbents_conditional"],
        )
        for company_key, conditional in five_year_damage[
            "conditional_by_company"
        ].items():
            self.assertTrue(
                math.isclose(
                    five_year_damage["unconditional_by_company"][company_key],
                    conditional * entry_probability,
                    abs_tol=1e-7,
                )
            )

        market = model["market"]
        slow_2031 = market["sensitivity_cases"]["slow"]["rows"][-1]
        base_2031 = market["rows"][-1]
        fast_2031 = market["sensitivity_cases"]["fast"]["rows"][-1]
        self.assertLess(
            slow_2031["total_ports_million"], base_2031["total_ports_million"]
        )
        self.assertLess(
            base_2031["total_ports_million"], fast_2031["total_ports_million"]
        )
        self.assertLess(
            slow_2031["normal_market_revenue_usd_bn"],
            base_2031["normal_market_revenue_usd_bn"],
        )
        self.assertLess(
            base_2031["normal_market_revenue_usd_bn"],
            fast_2031["normal_market_revenue_usd_bn"],
        )
        demand_slow = market["sensitivity_cases"]["demand_slow_supply_base"]["rows"][-1]
        demand_fast = market["sensitivity_cases"]["demand_fast_supply_base"]["rows"][-1]
        supply_slow = market["sensitivity_cases"]["supply_slow_demand_base"]["rows"][-1]
        supply_fast = market["sensitivity_cases"]["supply_fast_demand_base"]["rows"][-1]
        self.assertGreater(
            demand_slow["qualified_supply_demand_ratio"],
            base_2031["qualified_supply_demand_ratio"],
        )
        self.assertLess(
            demand_fast["qualified_supply_demand_ratio"],
            base_2031["qualified_supply_demand_ratio"],
        )
        self.assertLess(
            supply_slow["qualified_supply_demand_ratio"],
            base_2031["qualified_supply_demand_ratio"],
        )
        self.assertGreater(
            supply_fast["qualified_supply_demand_ratio"],
            base_2031["qualified_supply_demand_ratio"],
        )
        self.assertAlmostEqual(
            demand_fast["qualified_supply_demand_ratio"], 166 / 165, places=4
        )

        expected_sensitivity_cases = {
            "loose_entry_threshold",
            "strict_entry_threshold",
            "qualification_delay",
            "negative_dependence",
            "independent_events",
            "high_positive_dependence",
            "architecture_acceleration",
        }
        sensitivity_cases = model["probability_sensitivity"]["cases"]
        self.assertEqual(set(sensitivity_cases), expected_sensitivity_cases)
        for case in sensitivity_cases.values():
            for horizon in ("3y", "5y"):
                row = case["horizons"][horizon]
                for field in (
                    "byd_meaningful_entry",
                    "luxshare_meaningful_entry",
                    "at_least_one_entry",
                    "at_least_one_global_entry",
                    "architecture_c_probability",
                ):
                    self.assertGreaterEqual(row[field], 0.0)
                    self.assertLessEqual(row[field], 1.0)

        operating = model["financial"]["operating_assumptions"]
        self.assertEqual(operating["gross_to_net_pass_through"], 0.72)
        self.assertEqual(operating["terminal_wacc"], 0.12)
        self.assertEqual(operating["terminal_perpetual_growth"], 0.03)
        self.assertEqual(operating["valuation_date"], "2026-07-20")
        expected_risk_multipliers = {"innolight": 0.92, "eoptolink": 1.08}
        for company_key, expected_multiplier in expected_risk_multipliers.items():
            company = model["financial"]["companies"][company_key]
            self.assertEqual(company["risk_multiplier"], expected_multiplier)
            self.assertTrue(company["risk_multiplier_rationale"])
        self.assertIn(
            "BPS股本口径差异不参与",
            model["financial"]["companies"]["eoptolink"][
                "risk_multiplier_rationale"
            ],
        )

        for company in model["financial"]["companies"].values():
            repeated_input_states = {
                row["state"]
                for row in company["input_repetition_audit"]
                if row["dimension"] == "entry_state"
            }
            self.assertTrue({"B", "C", "D"}.issubset(repeated_input_states))
            for finding in company["input_repetition_audit"]:
                self.assertIn("相同输入序列", finding["interpretation"])
            bridge = company["valuation_bridge"]
            expected_baseline_proxy = sum(
                row["discounted_fcf_cny_yi"]
                for row in company["cross_state_rows"]["A|P"]
                if row["year"] > 2026
            ) + company["discounted_terminal_value_by_cross_state_cny_yi"]["A|P"]
            self.assertAlmostEqual(
                bridge["baseline_no_entry_operating_value_proxy_cny_yi"],
                expected_baseline_proxy,
                places=2,
            )
            self.assertIn("排除完整2026年FCF", bridge["proxy_definition"])
            self.assertIn("entry_only_discount_vs_A_P_pct", bridge)
            self.assertIn("architecture_only_discount_vs_A_P_pct", bridge)
            self.assertIn(
                "combined_entry_and_architecture_discount_vs_A_P_pct", bridge
            )
            revenue_outputs = company["baseline_revenue_sensitivity_outputs"]
            self.assertEqual(set(revenue_outputs), {"low", "base", "high"})
            base_sensitivity = revenue_outputs["base"]
            self.assertEqual(
                base_sensitivity["rows"],
                [
                    {
                        **row,
                        "actual_fcf_cny_yi": row["fcf_cny_yi"],
                        "discounted_actual_fcf_cny_yi": row[
                            "discounted_fcf_cny_yi"
                        ],
                    }
                    for row in company["probability_weighted_rows"]
                ],
            )
            self.assertEqual(
                base_sensitivity[
                    "probability_weighted_terminal_value_cny_yi"
                ],
                company["probability_weighted_terminal_value_cny_yi"],
            )
            self.assertEqual(
                base_sensitivity[
                    "probability_weighted_discounted_terminal_value_cny_yi"
                ],
                company[
                    "probability_weighted_discounted_terminal_value_cny_yi"
                ],
            )
            self.assertEqual(
                base_sensitivity[
                    "probability_weighted_operating_value_proxy_cny_yi"
                ],
                company["valuation_bridge"][
                    "probability_weighted_operating_value_proxy_cny_yi"
                ],
            )
            self.assertLess(
                revenue_outputs["low"][
                    "probability_weighted_operating_value_proxy_cny_yi"
                ],
                revenue_outputs["base"][
                    "probability_weighted_operating_value_proxy_cny_yi"
                ],
            )
            self.assertLess(
                revenue_outputs["base"][
                    "probability_weighted_operating_value_proxy_cny_yi"
                ],
                revenue_outputs["high"][
                    "probability_weighted_operating_value_proxy_cny_yi"
                ],
            )


if __name__ == "__main__":
    unittest.main()
