from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from tools.viewer.app import app
from tools.financial.read_models import company_bundle


ROOT = Path(__file__).resolve().parents[2]
POLICY_MODEL = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "models"
    / "battery_policy_scenarios_v1.json"
)
HK_VALUATION_MODEL = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "models"
    / "battery_hk_valuation_history_v1.json"
)
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


def _number(text: str) -> float:
    match = re.search(r"-?[\d,]+(?:\.\d+)?", text.replace("\u2212", "-"))
    if not match:
        raise AssertionError(f"文本中没有数值: {text!r}")
    return float(match.group(0).replace(",", ""))


def test_policy_ledger_has_reproducible_unit_sensitivities() -> None:
    model = json.loads(POLICY_MODEL.read_text(encoding="utf-8"))
    units = model["unitSensitivities"]
    assert len(model["policies"]) == 16
    assert len(model["companyExposures"]) == 9
    assert {row["region"] for row in model["politicalOutlook"]} == {
        "中国",
        "美国",
        "欧盟",
        "印度、东南亚与中东非",
        "拉丁美洲",
        "关键矿产与材料",
    }
    assert units["chinaConsumptionTaxGrossPerRmb10bnEligibleRevenue"][
        "2026"
    ] == pytest.approx(0.66666667)
    assert units["chinaConsumptionTaxGrossPerRmb10bnEligibleRevenue"][
        "2027"
    ] == pytest.approx(2.66666667)
    assert units["chinaExportRebateLossPerRmb10bnEligibleExportRevenue"][
        "2026"
    ] == pytest.approx(2.25)
    assert units["chinaExportRebateLossPerRmb10bnEligibleExportRevenue"][
        "2027"
    ] == pytest.approx(9.0)
    assert units["usTariffGrossPerRmb10bnDirectExportRevenue"][
        "allYears"
    ] == pytest.approx(25.0)
    assert units["us45xGrossPer10GwhCellAndModuleAtFullEligibility"][
        "annualUsdMillion"
    ] == pytest.approx(450)
    assert units["euInterestSavingPerEur500mLoanAt5Pct"][
        "annualEurMillion"
    ] == pytest.approx(25)


def test_hk_valuation_history_has_no_look_ahead_and_correct_band_status() -> None:
    model = json.loads(HK_VALUATION_MODEL.read_text(encoding="utf-8"))
    rows = {row["ticker"]: row for row in model["companies"]}
    assert rows["3931.HK"]["pbObservations"] >= 12
    assert rows["3931.HK"]["positivePeObservations"] >= 12
    assert rows["0666.HK"]["pbObservations"] >= 12
    assert rows["0666.HK"]["positivePeObservations"] < 12
    for company in rows.values():
        for observation in company["observations"]:
            assert observation["date"] >= observation["financialAvailableFrom"]
            assert observation["pbApprox"] > 0
            assert observation["hkdCny"] > 0
    calb = company_bundle(663)
    rept = company_bundle(665)
    assert calb is not None and rept is not None
    assert calb["asset_return"]["pe_price_band"] is not None
    assert calb["asset_return"]["pb_price_band"] is not None
    assert rept["asset_return"]["pb_price_band"] is not None
    assert rept["asset_return"]["pe_price_band"] is None
    assert (
        rept["asset_return"]["pe_price_band_availability"]["status"]
        == "insufficient_monthly_history"
    )


@pytest.fixture(scope="module")
def battery_browser() -> Iterator[tuple[str, object]]:
    playwright = pytest.importorskip("playwright.sync_api")
    if not CHROME.is_file():
        pytest.skip("本机没有可用于锂电池计算器回归测试的 Chrome")
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    manager = playwright.sync_playwright().start()
    browser = manager.chromium.launch(
        headless=True,
        executable_path=str(CHROME),
        args=["--disable-gpu"],
    )
    try:
        yield f"http://127.0.0.1:{server.server_port}", browser
    finally:
        browser.close()
        manager.stop()
        server.shutdown()
        thread.join(timeout=5)


def _new_page(battery_browser, path: str, width: int = 1440):
    base_url, browser = battery_browser
    context = browser.new_context(viewport={"width": width, "height": 1100})
    page = context.new_page()
    errors: list[str] = []
    page.on(
        "console",
        lambda message: errors.append(message.text)
        if message.type == "error"
        else None,
    )
    response = page.goto(base_url + path, wait_until="domcontentloaded")
    assert response is not None and response.status == 200
    page.wait_for_timeout(200)
    return context, page, errors


def _fill_policy(page, field: str, year_index: int, value: float) -> None:
    locator = page.locator(
        f'input[data-policy="{field}"][data-index="{year_index}"]'
    )
    locator.fill(f"{value:.8f}")
    page.wait_for_timeout(40)


def _policy_output(page, metric: str, year: int) -> float:
    return _number(
        page.locator(f'[data-policy-output="{metric}:{year}"]').inner_text()
    )


def test_battery_policy_inputs_flow_to_profit_cashflow_and_valuation(
    battery_browser,
) -> None:
    context, page, errors = _new_page(
        battery_browser, "/tools/battery-calculator?company_id=254"
    )
    try:
        for year in (2026, 2027, 2028):
            assert _policy_output(page, "adjustedNetIncome", year) == pytest.approx(
                _policy_output(page, "netIncome", year), abs=0.01
            )
            assert _policy_output(page, "adjustedFcf", year) == pytest.approx(
                _policy_output(page, "fcf", year), abs=0.01
            )

        revenue_2026 = page.evaluate("results[0].revenue")
        tax_rate_2026 = page.evaluate("state.inputs.taxRate[0]")
        _fill_policy(page, "domesticEligibleRevenueShare", 0, 100)
        _fill_policy(page, "consumptionTaxRate", 0, 2 / 3)
        _fill_policy(page, "taxPassThrough", 0, 0)
        _fill_policy(page, "upstreamTaxDeductible", 0, 0)
        expected_consumption = revenue_2026 * (2 / 3) / 100
        assert _policy_output(
            page, "consumptionTaxHit", 2026
        ) == pytest.approx(expected_consumption, abs=0.02)
        assert (
            _policy_output(page, "netIncome", 2026)
            - _policy_output(page, "adjustedNetIncome", 2026)
        ) == pytest.approx(
            expected_consumption * (1 - tax_rate_2026), abs=0.03
        )

        _fill_policy(page, "exportEligibleRevenueShare", 0, 100)
        _fill_policy(page, "exportRebateLossRate", 0, 2.25)
        _fill_policy(page, "exportPassThrough", 0, 0)
        assert _policy_output(page, "exportRebateHit", 2026) == pytest.approx(
            revenue_2026 * 0.0225, abs=0.03
        )

        _fill_policy(page, "usDirectExportRevenueShare", 0, 100)
        _fill_policy(page, "usTariffRate", 0, 25)
        _fill_policy(page, "usSupplierAbsorption", 0, 100)
        assert _policy_output(page, "usTariffHit", 2026) == pytest.approx(
            revenue_2026 * 0.25, abs=0.03
        )

        _fill_policy(page, "usLocalEligibleGwh", 0, 10)
        _fill_policy(page, "us45xEligibility", 0, 100)
        _fill_policy(page, "us45xUtilization", 0, 100)
        assert _policy_output(page, "us45xCredit", 2026) == pytest.approx(
            10 * (35 + 10) * 7.15 / 100, abs=0.01
        )

        _fill_policy(page, "euInterestFreeLoanRmb100m", 0, 50)
        _fill_policy(page, "euAlternativeBorrowingRate", 0, 5)
        _fill_policy(page, "euComplianceCapex", 0, 3)
        assert _policy_output(page, "euInterestSaving", 2026) == pytest.approx(
            2.5, abs=0.01
        )
        assert _policy_output(page, "euComplianceCapex", 2026) == pytest.approx(
            3, abs=0.01
        )

        page.locator("#resetPolicyShares").click()
        _fill_policy(page, "domesticEligibleRevenueShare", 0, 1)
        _fill_policy(page, "consumptionTaxRate", 0, 2 / 3)
        _fill_policy(page, "taxPassThrough", 0, 0)
        _fill_policy(page, "upstreamTaxDeductible", 0, 0)
        page.locator("#valuationYear").select_option("2026")
        page.locator("#includePolicyValuation").check()
        adjusted_ni = _policy_output(page, "adjustedNetIncome", 2026)
        pe_floor = min(
            float(page.locator("#peLow").input_value()),
            float(page.locator("#peHigh").input_value()),
        )
        target_low = _number(
            page.locator('[data-valuation-card="0"] b').inner_text()
        )
        if adjusted_ni > 0:
            assert target_low == pytest.approx(adjusted_ni * pe_floor, abs=0.1)
        assert not errors
    finally:
        context.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_battery_policy_comparison_page_is_complete_and_contained(
    battery_browser, width: int
) -> None:
    context, page, errors = _new_page(
        battery_browser, "/industry/lithium-battery/comparison", width=width
    )
    try:
        assert page.locator("#policyOutlookGrid article").count() == 6
        assert page.locator("#policySensitivityGrid > div").count() == 4
        assert page.locator("#policyExposureBody tr").count() == 9
        assert page.locator('#policyExposureBody a[href^="/company/"]').count() == 9
        body_overflow = page.evaluate("document.body.scrollWidth - innerWidth")
        assert body_overflow <= 3
        assert not errors
    finally:
        context.close()
