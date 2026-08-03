from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

from tools.financial.read_models import company_bundle


ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "models"
    / "battery_independent_models_v1.json"
)
SUPPLY_DEMAND_PATH = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "models"
    / "battery_industry_supply_demand_v1.json"
)
CLAIMS_PATH = (
    ROOT
    / "cache"
    / "claims"
    / "lithium_battery_b_20260728_01_core_claims.json"
)
DOCS_DIR = ROOT / "docs" / "industries"
RESEARCH_DB = ROOT / "data" / "research.db"
FINANCIAL_DB = ROOT / "data" / "financial.db"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_nine_company_models_reconcile_operating_to_financial_results() -> None:
    payload = _load(MODEL_PATH)
    assert len(payload["companies"]) == 9
    for company in payload["companies"]:
        previous_equity = float(company["inputs"]["openingEquity"])
        cash_conversion = company["inputs"]["cashConversion"]
        for index, forecast in enumerate(company["forecast"]):
            segment_revenue = sum(float(row["revenue"]) for row in forecast["segments"])
            segment_gross_profit = sum(
                float(row["grossProfit"]) for row in forecast["segments"]
            )
            assert forecast["revenue"] == pytest.approx(segment_revenue, rel=1e-12)
            assert forecast["grossProfit"] == pytest.approx(
                segment_gross_profit, rel=1e-12
            )
            expected_pretax = (
                segment_gross_profit
                - float(forecast["operatingExpenses"])
                + float(forecast["otherPretax"])
            )
            assert forecast["pretaxProfit"] == pytest.approx(
                expected_pretax, rel=1e-12
            )
            expected_net_income = (
                expected_pretax * (1 - float(forecast["taxRate"]))
                - float(forecast["minorityInterest"])
            )
            assert forecast["netIncome"] == pytest.approx(
                expected_net_income, rel=1e-12
            )
            assert forecast["ocf"] == pytest.approx(
                float(forecast["netIncome"]) * float(cash_conversion[index]),
                rel=1e-12,
            )
            assert forecast["freeCashFlow"] == pytest.approx(
                float(forecast["ocf"]) - float(forecast["capex"]), rel=1e-12
            )
            expected_ending_equity = (
                previous_equity
                + float(forecast["netIncome"])
                - float(forecast["dividends"])
            )
            assert forecast["endingEquity"] == pytest.approx(
                expected_ending_equity, rel=1e-12
            )
            previous_equity = float(forecast["endingEquity"])


def test_all_valuation_ranges_recalculate_from_disclosed_parameters() -> None:
    payload = _load(MODEL_PATH)
    for company in payload["companies"]:
        methods = {row["method"]: row for row in company["valuationMethods"]}
        pe = methods["正常化市盈率"]
        pb = methods["PB—ROE"]
        implied = methods["当前市场隐含市盈率"]
        assert pe["valueLow"] == pytest.approx(
            float(pe["basisValue"]) * float(pe["lowParameter"]), rel=1e-12
        )
        assert pe["valueHigh"] == pytest.approx(
            float(pe["basisValue"]) * float(pe["highParameter"]), rel=1e-12
        )
        assert pb["valueLow"] == pytest.approx(
            float(pb["basisValue"]) * float(pb["lowParameter"]), rel=1e-12
        )
        assert pb["valueHigh"] == pytest.approx(
            float(pb["basisValue"]) * float(pb["highParameter"]), rel=1e-12
        )
        assert implied["impliedMultiple"] == pytest.approx(
            float(company["marketCapRmb100m"]) / float(implied["basisValue"]),
            rel=1e-12,
        )
        assert pe["valueLow"] <= pe["valueHigh"]
        assert pb["valueLow"] <= pb["valueHigh"]


def test_supply_demand_model_keeps_measurements_separate_and_recalculates() -> None:
    payload = _load(SUPPLY_DEMAND_PATH)
    path = payload["demandModel"]["evPath"]
    assert path[0]["year"] == 2025
    assert path[0]["evBatteryDeploymentTwh"] == pytest.approx(1.2)
    assert path[-1]["year"] == 2030
    assert path[-1]["evBatteryDeploymentTwh"] == pytest.approx(3.0)
    cagr = float(payload["demandModel"]["evAnchorCagrPct"]) / 100
    for index, row in enumerate(path):
        assert row["evBatteryDeploymentTwh"] == pytest.approx(
            1.2 * (1 + cagr) ** index,
            abs=0.0001,
        )
    bridge = payload["chinaFlowBridge2026H1"]
    assert bridge["productionMinusSalesGwh"] == pytest.approx(
        bridge["productionGwh"] - bridge["salesGwh"]
    )
    assert "不得直接相加" in payload["demandModel"]["nonAdditivityWarning"]
    assert payload["scenarioContract"]["probabilitiesAssigned"] is False


def test_claims_and_live_research_db_keep_financial_vendor_data_separate() -> None:
    claims = _load(CLAIMS_PATH)
    assert claims["meta"]["evidence_accounting"]["observation_count"] == 229
    assert (
        claims["meta"]["evidence_accounting"]["parallel_research_fact_count"]
        == 215
    )
    conn = sqlite3.connect(RESEARCH_DB)
    try:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM industry_data_point WHERE industry_id=29"
            ).fetchone()[0]
            == 229
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM company_profile WHERE industry_id=29"
            ).fetchone()[0]
            == 9
        )
        metrics = {
            row[0]
            for row in conn.execute(
                "SELECT metric FROM industry_data_point WHERE industry_id=29"
            )
        }
    finally:
        conn.close()
    forbidden_financial_metrics = {
        "PE",
        "PB",
        "PS",
        "ROE",
        "ROA",
        "归母净利润",
        "经营现金流",
        "资本开支",
        "市值",
    }
    assert not (metrics & forbidden_financial_metrics)


def test_public_documents_have_four_sections_links_and_valid_citations() -> None:
    paths = [
        DOCS_DIR / "锂电池.md",
        *(DOCS_DIR / f"锂电池_Q{index}_{suffix}.md" for index, suffix in (
            (0, "历史发展"),
            (1, "竞争格局"),
            (2, "市场空间"),
            (3, "公司壁垒"),
            (4, "行业特征"),
            (5, "综述"),
            (6, "政策与地缘政治"),
        )),
        DOCS_DIR / "锂电池_公司透视.md",
        DOCS_DIR / "锂电池_估值对比.md",
    ]
    conn = sqlite3.connect(RESEARCH_DB)
    try:
        valid_source_ids = {
            int(row[0]) for row in conn.execute("SELECT id FROM source")
        }
    finally:
        conn.close()
    cited: set[int] = set()
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "问题" in text
        assert "研究方法与数据" in text
        assert "研究与分析" in text
        assert "总结" in text
        assert not re.search(
            r"canonical|intake|字段完成度|参数 owner|本节专属边界|决策验证债",
            text,
            flags=re.IGNORECASE,
        )
        cited.update(int(value) for value in re.findall(r"\^src:(\d+)", text))
    assert cited
    assert cited <= valid_source_ids

    company_text = (DOCS_DIR / "锂电池_公司透视.md").read_text(encoding="utf-8")
    for company_id in (254, 414, 661, 662, 663, 664, 665, 666, 667):
        assert f"/company/{company_id}" in company_text
    assert company_text.count("### 问题") == 9
    assert company_text.count("### 研究方法与数据") == 9
    assert company_text.count("### 研究与分析") == 9
    assert company_text.count("### 总结") == 9


def test_company_pages_route_to_frozen_pb_framework_and_band_availability() -> None:
    for company_id in (254, 414, 661, 662, 663, 664, 665, 666, 667):
        bundle = company_bundle(company_id, db_path=FINANCIAL_DB)
        assert bundle is not None
        framework = bundle["valuation_framework"]
        assert framework["model_run_key"].startswith("lithium_battery_b_20260728:")
        assert framework["cycle_sensitivity"] != "尚未完成专项判断"
        assert framework["price_exposure"] != "尚未形成可追溯结论"
        assert framework["profit_driver"] != "尚未形成可追溯结论"
        assert bundle["asset_return"]["pb_price_band_availability"]["status"] == "ready"
    assert (
        company_bundle(663, db_path=FINANCIAL_DB)["asset_return"][
            "pe_price_band_availability"
        ]["status"]
        == "ready"
    )
