from __future__ import annotations

import json
import math
from pathlib import Path

from openpyxl import load_workbook

from tools.financial.build_lithium_calculator_ledger import compile_ledger


ROOT = Path(__file__).resolve().parents[2]


def _workbook() -> Path:
    matches = [
        path
        for path in ROOT.glob("*20260606.xlsx")
        if not path.name.startswith("~$")
    ]
    assert len(matches) == 1
    return matches[0]


def test_workbook_project_ledger_preserves_mines_and_notes() -> None:
    ledger = compile_ledger(_workbook())
    assert ledger["schema_version"] == "lithium_calculator.project_ledger.v4"
    assert ledger["company_count"] == 11
    assert ledger["project_count"] == 36
    assert ledger["vat_rate_pct"] == 13.0
    assert ledger["income_tax_rate_pct"] == 15.0
    assert ledger["cost_basis"] == "含税完全成本"

    by_name = {row["name"]: row for row in ledger["companies"]}
    ganfeng = by_name["赣锋锂业"]
    assert ganfeng["projectCount"] == 13
    assert ganfeng["workbookNoteCount"] == 4
    assert ganfeng["projects"][0]["modelEquityStartYear"] == 2025
    assert any(
        "布谷马西钾" in row["text"] for row in ganfeng["workbookNotes"]
    )
    cauchari = next(
        row for row in ganfeng["projects"] if "Cauchari" in row["name"]
    )
    assert "布谷马西钾" not in cauchari["note"]
    tianqi = by_name["天齐锂业"]
    atacama = next(
        row for row in tianqi["projects"] if "Atacama" in row["name"]
    )
    assert atacama["ownershipPct"] == 22.16
    assert atacama["profitAttributionPct"] == 6.648
    assert atacama["workbookIncomeTaxFactorPresent"] is False
    salt_lake = by_name["盐湖股份"]
    chaerhan = salt_lake["projects"][0]
    assert chaerhan["ownershipPct"] == 51.42
    assert chaerhan["profitAttributionPct"] == 70.0
    assert chaerhan["workbookIncomeTaxFactorPresent"] is True


def test_resource_profit_uses_tax_inclusive_price_and_full_cost() -> None:
    ledger = compile_ledger(_workbook())
    by_name = {row["name"]: row for row in ledger["companies"]}

    def resource_profit(company_name: str, year: int, price: float) -> float:
        company = by_name[company_name]
        pre_tax = sum(
            project["grossVolumeByYear"][str(year)]
            * project["profitAttributionPct"]
            / 100.0
            * (
                price / 1.13
                - project["costByYear"][str(year)] / 1.13
            )
            for project in company["projects"]
        )
        return pre_tax * (1.0 - ledger["income_tax_rate_pct"] / 100.0)

    value_book = load_workbook(_workbook(), data_only=True, read_only=False)
    # Standard project formulas and explicit 70% profit sharing reconcile
    # exactly to the source workbook's cached detailed-sheet results.
    assert math.isclose(
        resource_profit("华友钴业", 2025, 8.0),
        value_book["华友钴业"]["E12"].value,
        rel_tol=0,
        abs_tol=1e-9,
    )
    assert math.isclose(
        resource_profit("盐湖股份", 2025, 8.0),
        value_book["盐湖股份"]["E16"].value,
        rel_tol=0,
        abs_tol=1e-9,
    )
    # The Atacama row in the old workbook omitted the final 15% income-tax
    # deduction after its 30% profit-sharing factor.  The corrected calculator
    # follows the newly confirmed rule and therefore applies 0.85 once after
    # aggregating all project pre-tax profit.
    tianqi = by_name["天齐锂业"]
    expected = sum(
        project["grossVolumeByYear"]["2025"]
        * project["profitAttributionPct"]
        / 100.0
        * (
            8.0 / 1.13 - project["costByYear"]["2025"] / 1.13
        )
        for project in tianqi["projects"]
    ) * 0.85
    assert math.isclose(
        resource_profit("天齐锂业", 2025, 8.0),
        expected,
        rel_tol=0,
        abs_tol=1e-12,
    )


def test_checked_in_ledger_matches_workbook_semantics() -> None:
    generated = compile_ledger(_workbook())
    checked_in = json.loads(
        (
            ROOT / "config" / "lithium_calculator_project_ledger.json"
        ).read_text(encoding="utf-8")
    )
    generated.pop("generated_at_utc", None)
    checked_in.pop("generated_at_utc", None)
    assert checked_in == generated


def test_calculator_defaults_to_visible_mine_detail() -> None:
    template = (
        ROOT / "tools" / "viewer" / "templates"
        / "lithium_calculator.html"
    ).read_text(encoding="utf-8")
    assert 'class="lc-panel lc-single-panel" id="lcDetailedPanel"' in template
    assert 'class="lc-panel lc-single-panel lc-hidden" id="lcSimplePanel"' in template
    assert "公司锂矿/盐湖项目表" in template
    assert "公司经营与项目备注" in template
    assert "2030年业绩/2026年业绩" in template
    assert "2030年业绩/2025年业绩" in template
    assert "当前市值/2030利润" not in template
    assert "let state=null,mode='detailed'" in template
    assert "原表" not in template
    assert "数据身份" not in template
    assert 'class="lc-note-cell">研究备注</th>' in template
    assert "lc-scroll-top" in template
    assert 'class="ownership-column"' in template
    assert 'data-k="status" rows="2"' in template
    assert "lcTargetPeLow" in template
    assert "lcTargetPeHigh" in template
    assert "目标市值区间" in template
    assert "toFixed(2)" in template
    assert 'class="lc-action">操作</th>' in template
    assert 'data-k="ownershipPct"' in template
    assert 'type="number" min="0" max="100" step=".01"' in template
    assert "企业所得税率（%）" in template
    assert "含税锂价÷1.13－含税完全成本÷1.13" in template
    assert "资源税前利润合计×（1－企业所得税率）" in template
    assert "资源利润归属" in template
    assert "profitAttributionPct" in template
    assert "税后归母转换系数（%）" not in template
