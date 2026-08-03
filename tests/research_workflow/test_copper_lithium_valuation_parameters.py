from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.pipeline.lithium_financial_profile_export import (
    build as build_lithium_financial_export,
)


ROOT = Path(__file__).resolve().parents[2]


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _dcf(flows: list[float], cost_of_equity: float, growth: float) -> float:
    explicit = sum(
        flow / ((1 + cost_of_equity) ** index)
        for index, flow in enumerate(flows, start=1)
    )
    terminal = (
        flows[-1]
        * (1 + growth)
        / (cost_of_equity - growth)
        / ((1 + cost_of_equity) ** len(flows))
    )
    return explicit + terminal


def test_copper_all_valuation_bounds_recompute_from_exposed_inputs() -> None:
    model = _json(
        ROOT
        / "config"
        / "copper_calculator_models"
        / "copper_calculator_model_v1.json"
    )
    for company in model["companies"]:
        methods = {row["method"]: row for row in company["valuationMethods"]}
        pe = methods["正常化市盈率"]
        pe_calc = pe["calculation"]
        profit = company["financials"][str(pe_calc["forecastYear"])]["netIncome"]
        assert pe["low"] == pytest.approx(
            profit * pe_calc["lowParameter"], abs=0.02
        )
        assert pe["high"] == pytest.approx(
            profit * pe_calc["highParameter"], abs=0.02
        )
        assert pe_calc["lowParameter"] < pe_calc["highParameter"]
        assert pe["note"]

        pb = methods["PB—ROE"]
        pb_calc = pb["calculation"]
        ending_equity = company["financials"][str(pb_calc["forecastYear"])]["equity"]
        assert pb_calc["basisLabel"] == "期末归母净资产"
        assert pb["low"] == pytest.approx(
            ending_equity * pb_calc["lowParameter"], abs=0.02
        )
        assert pb["high"] == pytest.approx(
            ending_equity * pb_calc["highParameter"], abs=0.02
        )
        assert "合理PB＝" in pb_calc["formula"]
        assert pb["note"]

        dcf = methods["股权现金流折现"]
        dcf_calc = dcf["calculation"]
        flows = [
            company["financials"][str(year)]["fcf"]
            for year in dcf_calc["forecastYears"]
        ]
        low_inputs = dcf_calc["lowValue"]
        high_inputs = dcf_calc["highValue"]
        assert dcf["low"] == pytest.approx(
            _dcf(
                flows,
                low_inputs["costOfEquityPct"] / 100,
                low_inputs["terminalGrowthPct"] / 100,
            ),
            abs=0.02,
        )
        assert dcf["high"] == pytest.approx(
            _dcf(
                flows,
                high_inputs["costOfEquityPct"] / 100,
                high_inputs["terminalGrowthPct"] / 100,
            ),
            abs=0.02,
        )
        assert dcf["low"] < dcf["high"]
        assert dcf["note"]


def test_lithium_core_range_and_all_reference_bounds_are_not_mechanical() -> None:
    model = _json(
        ROOT
        / "cache"
        / "lithium_research"
        / "models"
        / "lithium_company_independent_models_v1.json"
    )
    assert len(model["companies"]) == 13
    for company in model["companies"]:
        valuations = {row["method"]: row for row in company["valuations"]}
        if company["company"] == "西藏城投":
            assert company["independent_equity_value_range"]["low_rmb_bn"] is None
            assert company["independent_equity_value_range"]["high_rmb_bn"] is None
            assert "PB—ROE" not in valuations
            nav = valuations["条件化项目NAV"]
            assert nav["role"] == "未采用"
            assert nav["low_rmb_bn"] is None
            assert nav["high_rmb_bn"] is None
            continue

        pe = valuations["正常化市盈率"]
        pe_inputs = pe["inputs"]
        assert pe["role"] == "核心"
        assert pe["low_rmb_bn"] == pytest.approx(
            pe_inputs["net_income_rmb_bn"] * pe_inputs["pe_range"][0],
            abs=0.01,
        )
        assert pe["high_rmb_bn"] == pytest.approx(
            pe_inputs["net_income_rmb_bn"] * pe_inputs["pe_range"][1],
            abs=0.01,
        )
        assert company["independent_equity_value_range"]["low_rmb_bn"] == pytest.approx(
            pe["low_rmb_bn"]
        )
        assert company["independent_equity_value_range"]["high_rmb_bn"] == pytest.approx(
            pe["high_rmb_bn"]
        )
        assert pe["parameter_basis"]

        base_by_year = {
            row["year"]: row for row in company["scenarios"]["基准情景"]
        }
        pb = valuations["PB—ROE"]
        pb_inputs = pb["inputs"]
        equity = base_by_year[pb["forecast_year"]]["equity_rmb_bn"]
        assert pb["low_rmb_bn"] == pytest.approx(
            equity * pb_inputs["pb_range"][0], abs=0.02
        )
        assert pb["high_rmb_bn"] == pytest.approx(
            equity * pb_inputs["pb_range"][1], abs=0.02
        )
        assert pb_inputs["low_value_cost_of_equity_pct"] > (
            pb_inputs["high_value_cost_of_equity_pct"]
        )
        assert pb_inputs["low_value_terminal_growth_pct"] < (
            pb_inputs["high_value_terminal_growth_pct"]
        )
        assert pb["parameter_basis"]

        fcfe = valuations["股权自由现金流"]
        fcfe_inputs = fcfe["inputs"]
        flows = list(fcfe_inputs["fcfe_rmb_bn"])
        assert fcfe["low_rmb_bn"] == pytest.approx(
            _dcf(
                flows,
                fcfe_inputs["low_value_cost_of_equity_pct"] / 100,
                fcfe_inputs["low_value_terminal_growth_pct"] / 100,
            ),
            abs=0.02,
        )
        assert fcfe["high_rmb_bn"] == pytest.approx(
            _dcf(
                flows,
                fcfe_inputs["high_value_cost_of_equity_pct"] / 100,
                fcfe_inputs["high_value_terminal_growth_pct"] / 100,
            ),
            abs=0.02,
        )
        assert fcfe["role"] == "诊断"
        assert fcfe["parameter_basis"]


def test_lithium_unrated_company_explicitly_supersedes_old_valuation() -> None:
    export = build_lithium_financial_export()
    company = next(
        row
        for row in export["companies"]
        if row["security"]["canonical_name"] == "西藏城投"
    )
    valuation_run = next(
        row
        for row in company["model_runs"]
        if row["skill_name"] == "company_valuation_modeling"
    )
    assert "lithium_b_20260727:600773.SH:valuation:v3" in (
        valuation_run["supersedes_run_keys"]
    )
    assert len(valuation_run["outputs"]) == 1
    status = valuation_run["outputs"][0]
    assert status["output_name"] == "估值结论状态"
    assert status["value_text"] == "暂不评级"
    assert status["value_num"] is None
    assert status["range_low"] is None
    assert status["range_high"] is None
