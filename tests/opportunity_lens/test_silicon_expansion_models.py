from __future__ import annotations

import math

import pytest

from tools.opportunity_lens.silicon_expansion_models import (
    allocate_order_recognition,
    calculate_equipment_pool,
    calculate_equipment_scenarios,
    calculate_project_demand,
    calculate_wafer_demand_scenarios,
    equipment_intensity_per_100k_wspm,
    extrapolate_msi,
    msi_to_average_wspm,
    msi_to_million_wafers,
    native_wspm_to_300mm_equivalent,
    validate_tam_sam_som,
    wafer_area_square_inches,
)


def _minimal_demand_inputs() -> dict:
    return {
        "model_id": "test",
        "years": [2026, 2027, 2028, 2029, 2030],
        "aggregate_conversion_assumptions": {
            "device_utilization": 0.85,
            "prime_wafer_procurement_range": {
                "low": {
                    "utilization": 0.8,
                    "process_input_factor": 1.02,
                    "inventory_factor": 0.97,
                },
                "high": {
                    "utilization": 0.9,
                    "process_input_factor": 1.04,
                    "inventory_factor": 1.03,
                },
            },
        },
        "project_ramp_assumptions": {
            "year_end_nameplate_share_at_production_year": {
                "downside": 0.3,
                "base": 0.5,
                "upside": 0.7,
            },
            "operating_utilization_of_installed_capacity": {
                "downside": 0.78,
                "base": 0.88,
                "upside": 0.95,
            },
        },
        "public_aggregate_inputs": {
            "global_300mm_wspm_2028": 11_100_000,
            "global_300mm_cagr_2024_2028": 0.07,
            "advanced_le_7nm_wspm_2024": 850_000,
            "advanced_le_7nm_wspm_2028": 1_400_000,
            "global_total_8in_eq_wspm_2025": 33_600_000,
            "global_total_capacity_growth_2026": 0.05,
            "global_total_capacity_growth_2027": 0.05,
            "current_300mm_growth_2026": 0.07,
            "current_300mm_growth_2027_2029": 0.07,
            "current_200mm_wspm_2026": 7_700_000,
            "current_200mm_growth_2026": 0.03,
            "current_200mm_growth_2027": 0.03,
            "current_200mm_growth_2028": 0.01,
            "current_200mm_growth_2029": 0.02,
            "memory_300mm_wspm_2026": 4_100_000,
            "memory_300mm_wspm_2027": 4_200_000,
            "silicon_300mm_shipments_msi_2028": 10_800,
        },
        "post_2028_assumptions": {
            "global_300mm_growth_2029": {"downside": 0.05, "base": 0.07, "upside": 0.09},
            "global_300mm_growth_2030": {"downside": 0.02, "base": 0.04, "upside": 0.06},
            "total_8in_equivalent_growth_2028_2030": {"downside": 0.02, "base": 0.04, "upside": 0.06},
        },
        "bottom_up_disclosed_increment_projects": [
            {
                "project_id": "P1",
                "name": "可核验项目",
                "nameplate_incremental_wspm": 10_000,
                "production_year": 2026,
                "production_year_by_scenario": {
                    "downside": 2027,
                    "base": 2026,
                    "upside": 2026,
                },
                "full_capacity_year": 2028,
                "segment": "mature_logic_300mm",
                "capacity_derivation": {
                    "annual_wafers": 120_000,
                    "months_per_year": 12,
                },
            }
        ],
        "inventory_factors": {"downside": 0.97, "base": 1.0, "upside": 1.03},
        "process_input_factors": {"mature_logic_300mm": 1.02},
        "official_200mm_model_assumptions": {
            "utilization": 0.85,
            "process_input_factor": 1.03,
            "growth_2030": {"downside": 0.0, "base": 0.02, "upside": 0.04},
        },
        "forecast_backtest_inputs": {
            "forecast_msi": 13_328,
            "actual_msi": 12_973,
            "source_ids": ["S007", "S005"],
        },
        "source_refs_by_output": {
            "aggregate_300mm": ["S001"],
            "official_200mm_capacity": ["S065"],
            "memory_and_product_mix": ["S001"],
        },
    }


def test_area_and_msi_conversion_round_trip_scale() -> None:
    area = wafer_area_square_inches(300)
    assert math.isclose(area, 109.5633, rel_tol=1e-5)
    million_wafers = msi_to_million_wafers(12_973, diameter_mm=300)
    assert math.isclose(million_wafers * area, 12_973, rel_tol=1e-12)
    assert math.isclose(
        msi_to_average_wspm(12_973, diameter_mm=300),
        million_wafers * 1_000_000 / 12,
        rel_tol=1e-12,
    )


def test_native_200mm_starts_convert_by_area_not_diameter() -> None:
    assert math.isclose(
        native_wspm_to_300mm_equivalent(900_000, diameter_mm=200),
        400_000,
        rel_tol=1e-12,
    )


def test_project_demand_does_not_apply_manufacturing_yield() -> None:
    output = calculate_project_demand(
        [
            {
                "project_name": "示例200mm项目",
                "nominal_wspm": 100_000,
                "diameter_mm": 200,
                "ramp_by_year": {"2027": 0.5},
                "utilization_by_year": {"2027": 0.8},
                "procurement_adjustment_by_year": {"2027": 1.0},
            }
        ],
        years=[2027],
    )
    row = output["by_project"][0]["annual_results"][0]
    assert row["annual_native_wafers"] == 480_000
    assert math.isclose(row["annual_300mm_equivalent_wafers"], 480_000 * 4 / 9)
    assert "未再乘制造良率" in output["method_note"]


def test_project_procurement_adjustment_is_bounded() -> None:
    with pytest.raises(ValueError, match="0.75 到 1.25"):
        calculate_project_demand(
            [
                {
                    "project_name": "错误库存修正",
                    "nominal_wspm": 100_000,
                    "diameter_mm": 300,
                    "ramp_by_year": {2026: 1.0},
                    "utilization_by_year": {2026: 1.0},
                    "procurement_adjustment_by_year": {2026: 1.5},
                }
            ],
            years=[2026],
        )


def test_equipment_intensity_and_project_budget_units() -> None:
    per_100k = equipment_intensity_per_100k_wspm(929.48)
    assert math.isclose(per_100k, 11.15376, rel_tol=1e-12)
    projects = calculate_equipment_pool(
        [
            {
                "project_name": "示例抛光片项目",
                "process_type": "300mm_polished",
                "incremental_wspm": 100_000,
                "execution_probability": 0.8,
            }
        ],
        intensity_by_process={
            "300mm_polished": {"low": 900.0, "base": 1_000.0, "high": 1_100.0}
        },
    )
    budget = projects[0]["equipment_budget_rmb_100m"]
    adjusted = projects[0]["risk_adjusted_budget_rmb_100m"]
    assert budget == {"low": 10.8, "base": 12.0, "high": 13.2}
    assert adjusted == pytest.approx({"low": 8.64, "base": 9.6, "high": 10.56})


def test_equipment_complete_build_condition_is_not_mislabeled_as_probability() -> None:
    projects = calculate_equipment_pool(
        [
            {
                "project_name": "条件建设项目",
                "process_type": "300mm_polished",
                "incremental_wspm": 100_000,
                "conditional_execution_switch": 1,
            }
        ],
        intensity_by_process={
            "300mm_polished": {"low": 900.0, "base": 1_000.0, "high": 1_100.0}
        },
    )
    row = projects[0]
    assert row["conditional_execution_switch"] == 1
    assert row["conditional_budget_rmb_100m"] == row["equipment_budget_rmb_100m"]
    assert "execution_probability" not in row
    assert "risk_adjusted_budget_rmb_100m" not in row
    with pytest.raises(ValueError, match="只能为0或1"):
        calculate_equipment_pool(
            [
                {
                    "project_name": "错误条件开关",
                    "process_type": "300mm_polished",
                    "incremental_wspm": 100_000,
                    "conditional_execution_switch": 0.5,
                }
            ],
            intensity_by_process={
                "300mm_polished": {"low": 900.0, "base": 1_000.0, "high": 1_100.0}
            },
        )


def test_timing_only_allocates_existing_budget() -> None:
    allocation = allocate_order_recognition(100.0, {2026: 0.2, 2027: 0.5, 2028: 0.3})
    assert sum(allocation.values()) == pytest.approx(100.0)
    with pytest.raises(ValueError, match="合计必须为 1"):
        allocate_order_recognition(100.0, {2026: 0.2, 2027: 0.5})


def test_equipment_scenarios_preserve_project_and_annual_totals() -> None:
    output = calculate_equipment_scenarios(
        [
            {
                "project_name": "在建项目",
                "scenario_amounts_rmb_100m": {"low": 10, "base": 20, "high": 30},
                "annual_weights": {2026: 0.25, 2027: 0.75},
            },
            {
                "project_name": "规划项目",
                "scenario_amounts_rmb_100m": {"low": 0, "base": 0, "high": 10},
                "annual_weights": {2026: 0.0, 2027: 1.0},
            },
        ],
        years=[2026, 2027],
    )
    assert output["scenarios_rmb_100m"] == pytest.approx(
        {"low": 10, "base": 20, "high": 40}
    )
    annual = {row["year"]: row for row in output["annual_totals_rmb_100m"]}
    assert annual[2026] == pytest.approx(
        {"year": 2026, "low": 2.5, "base": 5.0, "high": 7.5}
    )
    assert annual[2027] == pytest.approx(
        {"year": 2027, "low": 7.5, "base": 15.0, "high": 32.5}
    )
    for scenario in ("low", "base", "high"):
        assert sum(row[scenario] for row in annual.values()) == pytest.approx(
            output["scenarios_rmb_100m"][scenario]
        )


def test_equipment_scenarios_reject_misordered_amounts() -> None:
    with pytest.raises(ValueError, match="low <= base <= high"):
        calculate_equipment_scenarios(
            [
                {
                    "project_name": "错误情景",
                    "scenario_amounts_rmb_100m": {"low": 20, "base": 10, "high": 30},
                    "annual_weights": {2026: 1.0},
                }
            ],
            years=[2026],
        )


def test_extrapolation_requires_explicit_contiguous_rates() -> None:
    output = extrapolate_msi(15_485, {2029: 0.05, 2030: 0.04}, anchor_year=2028)
    assert output[2029] == pytest.approx(16_259.25)
    assert output[2030] == pytest.approx(16_909.62)
    with pytest.raises(ValueError, match="连续"):
        extrapolate_msi(15_485, {2030: 0.04}, anchor_year=2028)


def test_tam_sam_som_order_is_enforced() -> None:
    assert validate_tam_sam_som(tam=100, sam=60, som=20) == {
        "tam": 100.0,
        "sam": 60.0,
        "som": 20.0,
    }
    with pytest.raises(ValueError, match="SOM <= SAM <= TAM"):
        validate_tam_sam_som(tam=100, sam=40, som=50)


def test_demand_model_recomputes_memory_and_public_balance_proxy() -> None:
    output = calculate_wafer_demand_scenarios(
        _minimal_demand_inputs(), total_project_count=31
    )
    memory = output["memory_and_product_mix"]["public_anchor"]
    assert memory["global_memory_300mm_wspm_2026"] == 4_100_000
    assert memory["global_memory_300mm_wspm_2027"] == 4_200_000
    proxy = output["public_supply_demand_proxy"]
    assert proxy["equivalent_average_300mm_wafers_per_month_lower_bound"] > 8_200_000
    assert proxy["shipment_to_installed_capacity_ratio_lower_bound_pct"] == pytest.approx(
        74.0, abs=0.02
    )
    assert "不是供需缺口" in proxy["boundary"]


def test_demand_model_rejects_one_sided_memory_anchor() -> None:
    inputs = _minimal_demand_inputs()
    del inputs["public_aggregate_inputs"]["memory_300mm_wspm_2027"]
    with pytest.raises(ValueError, match="必须同时提供"):
        calculate_wafer_demand_scenarios(inputs, total_project_count=31)


def test_demand_project_ramp_separates_year_end_share_average_share_and_utilization() -> None:
    output = calculate_wafer_demand_scenarios(
        _minimal_demand_inputs(), total_project_count=1
    )
    project = output["bottom_up_disclosed_wspm_subset"]["base"]["by_project"][0]
    rows = {row["year"]: row for row in project["annual"]}

    assert rows[2026]["year_end_nameplate_share"] == 0.5
    assert rows[2026]["annual_average_installed_nameplate_share"] == 0.25
    assert rows[2026]["operating_utilization_of_installed_capacity"] == 0.88
    assert rows[2026]["effective_annual_average_nameplate_utilization"] == 0.22
    assert rows[2026]["annual_prime_wafer_procurement"] == 26_928

    assert rows[2028]["year_end_nameplate_share"] == 1.0
    assert rows[2028]["annual_average_installed_nameplate_share"] == 0.875
    assert rows[2028]["effective_annual_average_nameplate_utilization"] == 0.77
    assert rows[2028]["annual_prime_wafer_procurement"] == 94_248


def test_demand_project_production_year_is_scenario_specific() -> None:
    output = calculate_wafer_demand_scenarios(
        _minimal_demand_inputs(), total_project_count=1
    )
    downside = output["bottom_up_disclosed_wspm_subset"]["downside"]["by_project"][0]
    base = output["bottom_up_disclosed_wspm_subset"]["base"]["by_project"][0]
    assert downside["production_year_used"] == 2027
    assert base["production_year_used"] == 2026
    downside_rows = {row["year"]: row for row in downside["annual"]}
    base_rows = {row["year"]: row for row in base["annual"]}
    assert downside_rows[2026]["annual_prime_wafer_procurement"] == 0
    assert base_rows[2026]["annual_prime_wafer_procurement"] > 0


def test_demand_model_rejects_full_capacity_before_production() -> None:
    inputs = _minimal_demand_inputs()
    inputs["bottom_up_disclosed_increment_projects"][0]["full_capacity_year"] = 2025
    with pytest.raises(ValueError, match="满产年份早于投产年份"):
        calculate_wafer_demand_scenarios(inputs, total_project_count=1)


def test_demand_model_exposes_input_contract_and_unit_reverse_checks() -> None:
    inputs = _minimal_demand_inputs()
    output = calculate_wafer_demand_scenarios(inputs, total_project_count=1)
    assumptions = output["aggregate_300mm"]["conversion_assumptions"]
    assert assumptions == inputs["aggregate_conversion_assumptions"]
    checks = output["unit_reverse_checks"]
    assert checks
    assert all(row["pass"] for row in checks)
    assert any("年产能转月产能" in row["check"] for row in checks)
