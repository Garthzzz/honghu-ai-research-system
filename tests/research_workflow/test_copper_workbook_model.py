from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
WORKBOOK = ROOT / "碳酸锂标的估值测算20260606.xlsx"
MODEL = (
    ROOT
    / "cache"
    / "copper_research"
    / "models"
    / "copper_independent_models_v2.json"
)
RECONCILIATION = (
    ROOT
    / "cache"
    / "copper_research"
    / "models"
    / "copper_external_reconciliation_v2.json"
)
EXPORT = ROOT / "cache" / "copper_research" / "copper_financial_profile_export.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_hash(payload: object) -> str:
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_reference_workbook_is_bound_to_the_v2_freeze() -> None:
    model = _json(MODEL)
    contract = model["inputs"]["reference_workbook"]

    assert model["schema_version"] == "copper.independent_model.freeze.v2"
    assert contract["sha256"] == _file_hash(WORKBOOK)
    assert contract["sheet_count"] == 14
    assert contract["formula_count"] > 100
    assert set(contract["formula_contract"]) == {
        "project_attributable_output",
        "resource_profit_grid",
        "other_business_valuation",
        "implied_resource_equity_value",
        "implied_resource_pe",
        "cross_company_resource_value",
        "cross_company_resource_multiple",
    }
    assert all(
        formula.startswith("=")
        for formula in contract["formula_contract"].values()
    )
    assert "不迁移锂行业13%增值税" in contract["transfer_policy"]


def test_copper_price_grids_are_complete_monotonic_and_hash_bound() -> None:
    model = _json(MODEL)
    assert model["input_sha256"] == _canonical_hash(model["inputs"])
    assert model["output_sha256"] == _canonical_hash(model["outputs"])

    companies = model["outputs"]["companies"]
    assert {company["ticker"] for company in companies} == {
        "601899.SH",
        "603993.SH",
        "1208.HK",
    }
    expected_prices = [8000.0, 9500.0, 11000.0, 11500.0, 12500.0, 14500.0]
    for company in companies:
        bridge = company["valuation"]["workbook_style_commodity_bridge"]
        rows = bridge["price_sensitivity"]
        profit_key = (
            "attributable_net_income_usd_bn"
            if company["ticker"] == "1208.HK"
            else "attributable_net_income_rmb_bn"
        )
        assert [row["copper_price_usd_t"] for row in rows] == expected_prices
        profits = [row[profit_key] for row in rows]
        assert all(left < right for left, right in zip(profits, profits[1:]))
        base_profit = company["scenarios"]["基准情景"][1][profit_key]
        grid_profit = next(
            row[profit_key]
            for row in rows
            if row["copper_price_usd_t"] == 11500.0
        )
        assert grid_profit == pytest.approx(base_profit, abs=0.005)


def test_market_implied_resource_values_recompute_from_current_market() -> None:
    reconciliation = _json(RECONCILIATION)
    assert reconciliation["schema_version"] == "copper.external_reconciliation.v2"
    assert reconciliation["content_sha256"] == _canonical_hash(
        {
            key: value
            for key, value in reconciliation.items()
            if key != "content_sha256"
        }
    )

    for name in ("紫金矿业", "洛阳钼业"):
        diagnostic = reconciliation["companies"][name][
            "workbook_style_resource_diagnostic"
        ]
        residual = diagnostic["non_copper_corporate_residual_profit_bn"]
        low_multiple, high_multiple = diagnostic[
            "residual_profit_multiple_range"
        ]
        current_cap = diagnostic["current_market_cap_bn"]
        expected_low = max(0.0, current_cap - residual * high_multiple)
        expected_high = max(0.0, current_cap - residual * low_multiple)
        actual_low, actual_high = diagnostic[
            "resource_implied_equity_value_range_bn"
        ]
        assert actual_low == pytest.approx(expected_low, abs=0.001)
        assert actual_high == pytest.approx(expected_high, abs=0.001)

    mmg = reconciliation["companies"]["五矿资源"][
        "workbook_style_resource_diagnostic"
    ]
    assert mmg["current_group_implied_pe"] == pytest.approx(
        mmg["current_market_cap_usd_bn_proxy"]
        / mmg["base_group_net_income_usd_bn"],
        abs=0.01,
    )
    assert "不能被资本化成正的" in mmg["limitations"]


def test_financial_export_supersedes_v1_and_keeps_diagnostic_separate() -> None:
    export = _json(EXPORT)
    assert export["research_run_ref"] == "copper_b_20260726"
    assert len(export["companies"]) == 3
    for company in export["companies"]:
        models = company["model_runs"]
        assert len(models) == 5
        versions = {
            model["model_name"]: model["run_key"].rsplit(":", 1)[-1]
            for model in models
        }
        assert versions == {
            "权益产量—铜价—成本—归母现金流桥": "v2",
            "正常化市盈率估值": "v5",
            "PB—ROE资产回报估值": "v5",
            "股权自由现金流折现": "v5",
            "铜价—资源利润—市场隐含估值诊断": "v2",
        }
        assert all(model["supersedes_run_keys"] for model in models)
        diagnostic = next(
            model
            for model in models
            if model["model_name"] == "铜价—资源利润—市场隐含估值诊断"
        )
        assert diagnostic["model_role"] == "diagnostic"
        assert diagnostic["finalization"] == "reviewed"


def test_public_copper_documents_describe_the_loaded_workbook() -> None:
    q7 = (ROOT / "docs" / "industries" / "铜_Q7_补充.md").read_text(
        encoding="utf-8"
    )
    valuation = (ROOT / "docs" / "industries" / "铜_估值对比.md").read_text(
        encoding="utf-8"
    )
    company = (ROOT / "docs" / "industries" / "铜_公司透视.md").read_text(
        encoding="utf-8"
    )

    assert "在本项目及D盘可检索范围内未找到" not in q7
    assert "权益铜税后利润代理" in q7
    assert "参考工作簿迁移：铜价、资源利润和当前市场隐含估值" in valuation
    assert "8,000 | 723.79 / 11.58" in valuation
    assert "参考工作簿框架下的市场隐含资源估值" in company
