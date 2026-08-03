from __future__ import annotations

from tools.opportunity_lens.run18_nev_model import METHOD_WEIGHTS, build_model


def test_three_independent_methods_are_preserved() -> None:
    model = build_model()
    assert sum(METHOD_WEIGHTS.values()) == 1.0
    assert set(METHOD_WEIGHTS) == {
        "industry_total",
        "brand_bottom_up",
        "upstream_leading",
    }
    for row in model["ensemble_forecast"]:
        assert set(row["method_inputs_10k"]) == set(METHOD_WEIGHTS)


def test_ensemble_forecast_balances_production_sales_exports_and_inventory() -> None:
    model = build_model()
    assert [row["month"] for row in model["ensemble_forecast"]] == [
        "2026-08",
        "2026-09",
        "2026-10",
    ]
    for row in model["ensemble_forecast"]:
        production = row["production_10k"]
        assert production["low"] <= production["point"] <= production["high"]
        expected = (
            production["point"]
            - row["domestic_retail_10k"]["point"]
            - row["china_factory_export_10k"]["point"]
        )
        assert abs(expected - row["system_inventory_flow_10k"]["point"]) <= 0.11


def test_historical_inventory_bridge_and_scope_split() -> None:
    model = build_model()
    assert len(model["history_12m"]) == 12
    for row in model["history_12m"]:
        expected = row["production"] - row["retail"] - row["export"]
        assert abs(expected - row["system_inventory_flow"]) <= 0.11
    for total, autonomous in zip(
        model["ensemble_forecast"], model["autonomous_supplement"], strict=True
    ):
        assert total["month"] == autonomous["month"]
        assert autonomous["production_10k"]["point"] < total["production_10k"]["point"]
        assert 0 < autonomous["share_of_total_point_pct"] < 100


def test_upstream_leading_claim_is_not_overstated() -> None:
    model = build_model()
    diagnostics = model["upstream_model_diagnostics"]
    assert diagnostics["backtest"]["same_month_correlation"] > 0.9
    assert diagnostics["leading_test"]["one_month_lead_correlation"] < 0.3
    assert diagnostics["lfp_test"]["one_month_lead_correlation"] < 0.1


def test_company_ownership_and_upstream_bridges_reconcile() -> None:
    model = build_model()
    checks = model["checks"]
    assert checks["company_point_balance_pass"]
    assert checks["ownership_reconciliation_pass"]
    assert checks["upstream_regression_pass"]
    assert checks["upstream_interval_rounding_pass"]

    for company in model["brand_company_bridge"]["companies"]:
        for row in company["months"]:
            point_balance = (
                row["production_10k"]["point"]
                - row["domestic_sales_10k"]["point"]
                - row["china_factory_export_10k"]["point"]
            )
            assert abs(point_balance - row["inventory_change_10k"]["point"]) <= 1e-9

    for row in model["ownership_bridge"]:
        parts = sum(
            row[key]
            for key in (
                "identified_chinese_system_10k",
                "identified_chinese_brand_jv_10k",
                "identified_foreign_brand_jv_10k",
                "foreign_wholly_owned_10k",
                "unidentified_tail_10k",
            )
        )
        assert abs(parts - row["brand_total_10k"]) <= 0.11


def test_decimal_half_up_and_upstream_display_precision_are_reproducible() -> None:
    model = build_model()
    ensemble = {row["month"]: row for row in model["ensemble_forecast"]}
    assert ensemble["2026-08"]["system_inventory_flow_10k"]["low"] == -38.65
    assert ensemble["2026-09"]["system_inventory_flow_10k"]["low"] == -41.35
    assert ensemble["2026-10"]["system_inventory_flow_10k"]["low"] == -39.15
    assert ensemble["2026-10"]["system_inventory_flow_10k"]["point"] == -5.95

    for row in model["upstream_forecast_bridge"]:
        point_battery = row["battery_installation_gwh"]["point"]
        reproduced = 30.8279 + 1.48028 * point_battery
        assert abs(reproduced - row["regression_output_before_error_10k"]["point"]) < 0.051
