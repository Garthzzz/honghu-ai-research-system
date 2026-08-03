from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.financial.build_copper_calculator_model import compile_model


ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = (
    ROOT
    / "config"
    / "copper_calculator_models"
    / "copper_calculator_model_v1.json"
)
TEMPLATE_PATH = (
    ROOT / "tools" / "viewer" / "templates" / "copper_calculator.html"
)


def test_checked_in_copper_model_matches_compiler() -> None:
    checked_in = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    assert checked_in == compile_model()


def test_copper_model_has_three_complete_company_cases() -> None:
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    assert model["schemaVersion"] == "copper_calculator.model.v1"
    assert model["freeze"]["independentModelFrozenBeforeExternalReconciliation"]

    companies = {row["name"]: row for row in model["companies"]}
    assert set(companies) == {"紫金矿业", "洛阳钼业", "五矿资源"}
    assert len(companies["紫金矿业"]["projects"]) >= 7
    assert len(companies["洛阳钼业"]["projects"]) == 2
    assert len(companies["五矿资源"]["projects"]) == 3
    assert companies["五矿资源"]["workbookTables"]
    mmg_reference_dcf = next(
        row
        for row in companies["五矿资源"]["valuationMethods"]
        if row["method"] == "参考工作簿DCF"
    )
    assert mmg_reference_dcf["low"] == pytest.approx(179.0926392304857)
    assert mmg_reference_dcf["high"] == pytest.approx(179.0926392304857)

    for company in companies.values():
        assert company["companyId"] > 0
        assert company["currentMarketValue"] > 0
        assert company["valuationMethods"]
        assert company["sources"]
        for year in ("2026", "2027", "2028"):
            row = company["financials"][year]
            assert row["netIncome"] > 0
            assert row["ocf"] > 0
            assert row["capex"] > 0
            assert row["fcf"] == pytest.approx(row["ocf"] - row["capex"])


def test_copper_projects_have_editable_operating_chain() -> None:
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    for company in model["companies"]:
        for project in company["projects"]:
            assert project["name"]
            assert project["status"]
            assert project["note"]
            assert 0 < project["ownershipPct"] <= 100
            for year in ("2025", "2026", "2027", "2028"):
                assert year in project["productionKt"]
                assert year in project["c1UsdLb"]
                assert year in project["incrementalCapex"]


def test_copper_template_exposes_requested_controls() -> None:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "逐项目修改产量、权益、C1成本、投产时间" in template
    assert "经营现金流" in template
    assert "资本开支" in template
    assert "自由现金流" in template
    assert "分红＋回购" in template
    assert "cc-scroll-top" in template
    assert "新增项目" in template
    assert "研究备注" in template
    assert "原表" not in template
    assert "数据身份" not in template
    assert "fxUsdCny)/100000" in template
    assert "1/100000" in template
    assert "cc-valuation-table" in template
    assert "updateFinancialOutputs" in template
    assert "updateValuationOutputs" in template
    assert "lowParameter" in template
    assert "highParameter" in template
    assert "期末归母净资产" in template
    assert "情景ROE" in template
    assert 'class="cc-action">操作</th>' in template
    assert "toFixed(2)" in template
    assert "const revenue=num(working.revenue),ocf=num(working.ocf),capex=num(working.capex),fcf=ocf-capex" in template
