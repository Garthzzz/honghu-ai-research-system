from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from tools.viewer.app import app


CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


def _number(text: str) -> float:
    match = re.search(r"-?[\d,]+(?:\.\d+)?", text.replace("\u2212", "-"))
    if not match:
        raise AssertionError(f"文本中没有数值: {text!r}")
    return float(match.group(0).replace(",", ""))


def _value(locator) -> float:
    return float(locator.input_value())


def _text_value(locator) -> float:
    return _number(locator.inner_text())


def _fill(locator, value: float) -> None:
    locator.fill(f"{value:.8f}")
    locator.page.wait_for_timeout(30)


def _select_by_text(select, text: str) -> None:
    option = select.locator("option", has_text=text).first
    select.select_option(value=option.get_attribute("value"))


@pytest.fixture(scope="module")
def calculator_browser() -> Iterator[tuple[str, object]]:
    playwright = pytest.importorskip("playwright.sync_api")
    if not CHROME.is_file():
        pytest.skip("本机没有可用于计算器回归测试的 Chrome")

    server = None
    for port in range(58765, 58800):
        try:
            server = make_server("127.0.0.1", port, app, threaded=True)
            break
        except OSError:
            continue
    if server is None:
        pytest.skip("没有可用于浏览器回归测试的安全本地端口")
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


def _new_page(calculator_browser, route: str):
    base_url, browser = calculator_browser
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    errors: list[str] = []
    page.on(
        "console",
        lambda message: errors.append(message.text)
        if message.type == "error"
        else None,
    )
    response = page.goto(base_url + route, wait_until="domcontentloaded")
    assert response is not None and response.status == 200
    page.wait_for_timeout(150)
    return context, page, errors


def test_copper_project_to_profit_cashflow_and_valuation_chain(
    calculator_browser,
) -> None:
    context, page, errors = _new_page(
        calculator_browser, "/tools/copper-calculator?company_id=635"
    )
    try:
        row = page.locator("#ccProjectRows tr").first
        production = row.locator(
            'input[data-series="productionKt"][data-year="2027"]'
        )
        c1 = row.locator('input[data-series="c1UsdLb"][data-year="2027"]')
        ownership = row.locator('input[data-key="ownershipPct"]')
        capex = row.locator(
            'input[data-series="incrementalCapex"][data-year="2027"]'
        )
        price = page.locator('input[data-price="2027"]')
        fx = page.locator('input[data-state="fxUsdCny"]')
        tax = page.locator('input[data-state="afterTaxConversion"]')
        cash_conversion = page.locator('input[data-state="cashConversion"]')

        def output(metric: str) -> float:
            return _text_value(
                page.locator(f'[data-financial-output="{metric}:2027"]')
            )

        initial = {
            key: output(key)
            for key in ("revenue", "netIncome", "ocf", "capex", "fcf")
        }
        initial_production = _value(production)
        own = _value(ownership) / 100
        delta_production = 10.0
        copper_price = _value(price)
        c1_value = _value(c1)
        fx_value = _value(fx)
        tax_value = _value(tax) / 100
        cash_value = _value(cash_conversion)
        _fill(production, initial_production + delta_production)

        expected_revenue_delta = (
            delta_production * own * copper_price * fx_value / 100_000
        )
        expected_ni_delta = (
            delta_production
            * own
            * (copper_price - c1_value * 2204.62262)
            * fx_value
            / 100_000
            * tax_value
        )
        assert output("revenue") - initial["revenue"] == pytest.approx(
            expected_revenue_delta, abs=0.03
        )
        assert output("netIncome") - initial["netIncome"] == pytest.approx(
            expected_ni_delta, abs=0.03
        )
        assert output("ocf") - initial["ocf"] == pytest.approx(
            expected_ni_delta * cash_value, abs=0.03
        )
        assert output("capex") == pytest.approx(initial["capex"], abs=0.01)
        assert output("fcf") - initial["fcf"] == pytest.approx(
            expected_ni_delta * cash_value, abs=0.03
        )

        before_c1 = {
            key: output(key) for key in ("netIncome", "ocf", "fcf")
        }
        delta_c1 = 0.10
        _fill(c1, c1_value + delta_c1)
        expected_c1_ni_delta = (
            -(initial_production + delta_production)
            * own
            * delta_c1
            * 2204.62262
            * fx_value
            / 100_000
            * tax_value
        )
        assert output("netIncome") - before_c1["netIncome"] == pytest.approx(
            expected_c1_ni_delta, abs=0.03
        )
        assert output("ocf") - before_c1["ocf"] == pytest.approx(
            expected_c1_ni_delta * cash_value, abs=0.03
        )
        assert output("fcf") - before_c1["fcf"] == pytest.approx(
            expected_c1_ni_delta * cash_value, abs=0.03
        )

        before_capex = output("fcf")
        _fill(capex, _value(capex) + 10)
        assert output("capex") - initial["capex"] == pytest.approx(10, abs=0.01)
        assert output("fcf") - before_capex == pytest.approx(-10, abs=0.01)

        # 输入上下限次序颠倒时，页面仍输出按数值排序的估值区间。
        pe_low = page.locator('[data-valuation-low-param="0"]')
        pe_high = page.locator('[data-valuation-high-param="0"]')
        _fill(pe_low, 11)
        _fill(pe_high, 9)
        net_income = output("netIncome")
        assert _text_value(page.locator('[data-valuation-low="0"]')) == pytest.approx(
            net_income * 9, abs=0.12
        )
        assert _text_value(
            page.locator('[data-valuation-high="0"]')
        ) == pytest.approx(net_income * 11, abs=0.12)

        pb_low = page.locator('[data-valuation-low-param="1"]')
        pb_high = page.locator('[data-valuation-high-param="1"]')
        equity = output("equity")
        _fill(pb_low, 3)
        _fill(pb_high, 2)
        assert _text_value(page.locator('[data-valuation-low="1"]')) == pytest.approx(
            equity * 2, abs=0.05
        )
        assert _text_value(
            page.locator('[data-valuation-high="1"]')
        ) == pytest.approx(equity * 3, abs=0.05)

        dcf_low_ke = page.locator('[data-valuation-dcf-ke="2:low"]')
        dcf_low_g = page.locator('[data-valuation-dcf-g="2:low"]')
        dcf_high_ke = page.locator('[data-valuation-dcf-ke="2:high"]')
        dcf_high_g = page.locator('[data-valuation-dcf-g="2:high"]')
        _fill(dcf_low_ke, 12)
        _fill(dcf_low_g, 2)
        _fill(dcf_high_ke, 10)
        _fill(dcf_high_g, 3)

        flows = [
            _text_value(page.locator(f'[data-financial-output="fcf:{year}"]'))
            for year in (2026, 2027, 2028)
        ]

        def dcf_value(ke_pct: float, growth_pct: float) -> float:
            ke = ke_pct / 100
            growth = growth_pct / 100
            explicit = sum(
                flow / ((1 + ke) ** index)
                for index, flow in enumerate(flows, start=1)
            )
            terminal = (
                flows[-1]
                * (1 + growth)
                / (ke - growth)
                / ((1 + ke) ** len(flows))
            )
            return explicit + terminal

        expected_low = dcf_value(12, 2)
        expected_high = dcf_value(10, 3)
        assert _text_value(page.locator('[data-valuation-low="2"]')) == pytest.approx(
            expected_low, abs=0.12
        )
        assert _text_value(
            page.locator('[data-valuation-high="2"]')
        ) == pytest.approx(expected_high, abs=0.12)
        assert not errors
    finally:
        context.close()


def test_copper_financial_inputs_historical_chain_and_state_lifecycle(
    calculator_browser,
) -> None:
    context, page, errors = _new_page(
        calculator_browser, "/tools/copper-calculator?company_id=635"
    )
    try:
        def input_for(metric: str, year: int):
            return page.locator(
                f'input[data-finance="{metric}"][data-year="{year}"]'
            )

        def output(metric: str, year: int) -> float:
            return _text_value(
                page.locator(f'[data-financial-output="{metric}:{year}"]')
            )

        ocf_2025 = input_for("ocf", 2025)
        capex_2025 = input_for("capex", 2025)
        assert output("fcf", 2025) == pytest.approx(
            _value(ocf_2025) - _value(capex_2025), abs=0.01
        )
        _fill(ocf_2025, _value(ocf_2025) + 10)
        _fill(capex_2025, _value(capex_2025) + 3)
        assert output("fcf", 2025) == pytest.approx(
            _value(ocf_2025) - _value(capex_2025), abs=0.01
        )

        year = 2027
        revenue = input_for("revenue", year)
        net_income = input_for("netIncome", year)
        ocf = input_for("ocf", year)
        capex = input_for("capex", year)
        equity = input_for("equity", year)
        buyback = input_for("buyback", year)
        payout = page.locator(f'input[data-payout="{year}"]')

        _fill(revenue, _value(revenue) + 100)
        _fill(net_income, _value(net_income) + 20)
        assert output("netMargin", year) == pytest.approx(
            output("netIncome", year) / output("revenue", year) * 100,
            abs=0.02,
        )

        _fill(equity, _value(equity) + 200)
        assert output("roe", year) == pytest.approx(
            output("netIncome", year) / output("equity", year) * 100,
            abs=0.02,
        )

        fcf_before = output("fcf", year)
        _fill(ocf, _value(ocf) + 10)
        assert output("fcf", year) - fcf_before == pytest.approx(10, abs=0.01)
        _fill(capex, _value(capex) + 4)
        assert output("fcf", year) == pytest.approx(
            output("ocf", year) - output("capex", year), abs=0.01
        )

        _fill(payout, 50)
        _fill(buyback, 5)
        assert output("dividend", year) == pytest.approx(
            output("netIncome", year) * 0.5, abs=0.02
        )
        assert output("cashReturn", year) == pytest.approx(
            output("dividend", year) + 5, abs=0.01
        )

        # 新增、删除、保存、载入和重置均应恢复同一条计算链。
        baseline_rows = page.locator("#ccProjectRows tr").count()
        baseline_ni = output("netIncome", 2027)
        page.locator("#ccAddProject").click()
        assert page.locator("#ccProjectRows tr").count() == baseline_rows + 1
        last = page.locator("#ccProjectRows tr").last
        _fill(last.locator('input[data-key="ownershipPct"]'), 50)
        _fill(
            last.locator(
                'input[data-series="productionKt"][data-year="2027"]'
            ),
            100,
        )
        assert output("netIncome", 2027) != pytest.approx(baseline_ni, abs=0.01)
        page.once("dialog", lambda dialog: dialog.accept())
        last.locator("button[data-remove]").click()
        assert page.locator("#ccProjectRows tr").count() == baseline_rows
        assert output("netIncome", 2027) == pytest.approx(baseline_ni, abs=0.02)

        page.locator("#ccScenarioName").fill("自动化公式回归")
        saved_ni = output("netIncome", year)
        page.locator("#ccSave").click()
        page.locator("#ccSaved").select_option(index=1)
        _fill(net_income, _value(net_income) + 30)
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#ccLoad").click()
        assert output("netIncome", year) == pytest.approx(saved_ni, abs=0.01)
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#ccReset").click()
        assert page.locator("#ccMessage").inner_text() == "已恢复冻结研究基准。"

        _select_by_text(page.locator("#ccCompany"), "洛阳钼业")
        assert "洛阳钼业" in page.locator("#ccCompanyMeta").inner_text()
        assert page.locator("#ccProjectRows tr").count() == 2
        assert not errors
    finally:
        context.close()


def test_lithium_detailed_project_price_tax_and_valuation_chain(
    calculator_browser,
) -> None:
    context, page, errors = _new_page(
        calculator_browser, "/tools/lithium-calculator?company_id=640"
    )
    try:
        profit = page.locator("#lcTerminalProfit")
        first = page.locator("#lcProjectRows tr").first
        volume = first.locator(
            'input[data-series="volumeByYear"][data-year="2030"]'
        )
        cost = first.locator(
            'input[data-series="costByYear"][data-year="2030"]'
        )
        ownership = first.locator('input[data-k="ownershipPct"]')
        price = page.locator("#lcPriceTerminal")
        income_tax = page.locator("#lcIncomeTaxRate")
        before = _text_value(profit)
        own = _value(ownership) / 100
        price_value = _value(price)
        cost_value = _value(cost)
        after_tax_value = 1 - _value(income_tax) / 100

        _fill(volume, _value(volume) + 1)
        assert _text_value(profit) - before == pytest.approx(
            own * (price_value / 1.13 - cost_value / 1.13) * after_tax_value,
            abs=0.03,
        )

        before_cost = _text_value(profit)
        current_volume = _value(volume)
        _fill(cost, cost_value + 1)
        assert _text_value(profit) - before_cost == pytest.approx(
            -current_volume * own / 1.13 * after_tax_value, abs=0.03
        )

        before_ownership = _text_value(profit)
        old_ownership = _value(ownership)
        _fill(ownership, old_ownership + 1)
        assert _text_value(profit) - before_ownership == pytest.approx(
            current_volume
            * 0.01
            * (price_value - (cost_value + 1))
            / 1.13
            * after_tax_value,
            abs=0.03,
        )

        # 价格变化作用于全部利润归属资源量；所得税仅作用于资源和加工税前利润。
        total_equity_resource = page.evaluate(
            """
            () => Array.from(document.querySelectorAll('#lcProjectRows tr'))
              .filter(row => row.querySelector('select[data-k="type"]')?.value === 'resource'
                && row.querySelector('input[data-k="enabled"]')?.checked)
              .reduce((sum,row) => {
                const volume = Number(row.querySelector(
                  'input[data-series="volumeByYear"][data-year="2030"]'
                )?.value || 0);
                const ownership = Number(
                  row.querySelector('input[data-k="ownershipPct"]')?.value || 0
                ) / 100;
                return sum + volume * ownership;
              }, 0)
            """
        )
        before_price = _text_value(profit)
        _fill(price, price_value + 2)
        assert _text_value(profit) - before_price == pytest.approx(
            total_equity_resource * 2 / 1.13 * after_tax_value, abs=0.05
        )

        target_low = page.locator("#lcTargetPeLow")
        target_high = page.locator("#lcTargetPeHigh")
        _fill(target_low, 10)
        _fill(target_high, 5)
        terminal_profit = _text_value(profit)
        target_bounds = [
            _number(part) for part in page.locator("#lcTargetCap").inner_text().split("—")
        ]
        assert target_bounds[0] == pytest.approx(
            max(0, terminal_profit * 5), abs=0.06
        )
        assert target_bounds[1] == pytest.approx(
            max(0, terminal_profit * 10), abs=0.06
        )

        rows_before = page.locator("#lcProjectRows tr").count()
        profit_before_add = _text_value(profit)
        page.locator("#lcAddProject").click()
        added = page.locator("#lcProjectRows tr").last
        _fill(added.locator('input[data-k="ownershipPct"]'), 50)
        _fill(
            added.locator(
                'input[data-series="volumeByYear"][data-year="2030"]'
            ),
            10,
        )
        _fill(
            added.locator('input[data-series="costByYear"][data-year="2030"]'),
            6,
        )
        expected_add = 5 * (_value(price) / 1.13 - 6 / 1.13) * after_tax_value
        assert _text_value(profit) - profit_before_add == pytest.approx(
            expected_add, abs=0.05
        )
        page.once("dialog", lambda dialog: dialog.accept())
        added.locator("button[data-remove]").click()
        assert page.locator("#lcProjectRows tr").count() == rows_before
        assert _text_value(profit) == pytest.approx(profit_before_add, abs=0.02)

        page.locator("#lcAddProject").click()
        added = page.locator("#lcProjectRows tr").last
        added.locator('select[data-k="type"]').select_option("processing")
        added = page.locator("#lcProjectRows tr").last
        _fill(added.locator('input[data-k="ownershipPct"]'), 50)
        _fill(
            added.locator(
                'input[data-series="volumeByYear"][data-year="2030"]'
            ),
            10,
        )
        _fill(
            added.locator(
                'input[data-series="processingMarginByYear"][data-year="2030"]'
            ),
            2,
        )
        assert _text_value(profit) - profit_before_add == pytest.approx(
            5 * 2 / 1.13 * after_tax_value, abs=0.04
        )
        page.once("dialog", lambda dialog: dialog.accept())
        added.locator("button[data-remove]").click()

        page.locator("#lcAddProject").click()
        added = page.locator("#lcProjectRows tr").last
        added.locator('select[data-k="type"]').select_option("other")
        added = page.locator("#lcProjectRows tr").last
        _fill(added.locator('input[data-k="ownershipPct"]'), 50)
        _fill(
            added.locator(
                'input[data-series="fixedProfitByYear"][data-year="2030"]'
            ),
            10,
        )
        assert _text_value(profit) - profit_before_add == pytest.approx(5, abs=0.02)
        page.once("dialog", lambda dialog: dialog.accept())
        added.locator("button[data-remove]").click()

        before_disable = _text_value(profit)
        current_volume = _value(volume)
        current_cost = _value(cost)
        current_own = _value(ownership) / 100
        first.locator('input[data-k="enabled"]').uncheck()
        assert _text_value(profit) - before_disable == pytest.approx(
            -current_volume
            * current_own
            * (_value(price) - current_cost)
            / 1.13
            * after_tax_value,
            abs=0.05,
        )
        first.locator('input[data-k="enabled"]').check()
        assert _text_value(profit) == pytest.approx(profit_before_add, abs=0.02)

        # 资源价格跌破现金成本时允许显示负利润，不把压力情景截断为零。
        _fill(price, 0)
        assert _text_value(profit) < 0
        assert not errors
    finally:
        context.close()


def test_lithium_simple_mode_full_formula_and_state_lifecycle(
    calculator_browser,
) -> None:
    context, page, errors = _new_page(
        calculator_browser, "/tools/lithium-calculator?company_id=640"
    )
    try:
        page.locator('[data-mode="simple"]').click()
        assert page.locator("#lcSimplePanel").is_visible()
        values = {
            "lcSimpleResourceVolume": 20,
            "lcSimpleCost": 6,
            "lcSimpleProcessingVolume": 10,
            "lcSimpleMargin": 2,
            "lcSimpleOther": 5,
            "lcSimpleCorporate": 3,
        }
        for element_id, value in values.items():
            _fill(page.locator(f"#{element_id}"), value)
        _fill(page.locator("#lcPriceTerminal"), 15)
        _fill(page.locator("#lcIncomeTaxRate"), 30)
        expected = (
            20 * (15 - 6) / 1.13 * 0.70
            + 10 * 2 / 1.13 * 0.70
            + 5
            - 3
        )
        assert _text_value(page.locator("#lcTerminalProfit")) == pytest.approx(
            expected, abs=0.03
        )

        current_company_row = page.locator(
            '#lcGrowthSummaryRows tr:has-text("赣锋锂业")'
        )
        # 2030利润是倒数第4列；跨公司汇总必须读取当前会话状态。
        assert _text_value(current_company_row.locator("td").nth(-4)) == pytest.approx(
            expected, abs=0.03
        )

        page.locator("#lcScenarioName").fill("简化公式回归")
        page.locator("#lcSave").click()
        page.locator("#lcSaved").select_option(index=1)
        saved_profit = _text_value(page.locator("#lcTerminalProfit"))
        _fill(page.locator("#lcSimpleOther"), 20)
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#lcLoad").click()
        assert _text_value(page.locator("#lcTerminalProfit")) == pytest.approx(
            saved_profit, abs=0.01
        )

        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#lcReset").click()
        assert page.locator("#lcMessage").inner_text() == "已恢复冻结研究默认值。"
        _select_by_text(page.locator("#lcCompany"), "天齐锂业")
        assert "天齐锂业" in page.locator("#lcCompanyMeta").inner_text()
        assert not errors
    finally:
        context.close()


def test_lithium_project_cashflow_and_dynamic_valuation_chain(
    calculator_browser,
) -> None:
    context, page, errors = _new_page(
        calculator_browser, "/tools/lithium-calculator?company_id=640"
    )
    try:
        row = page.locator("#lcProjectRows tr").first
        volume = row.locator(
            'input[data-series="volumeByYear"][data-year="2027"]'
        )
        cost = row.locator(
            'input[data-series="costByYear"][data-year="2027"]'
        )
        capex = row.locator(
            'input[data-series="incrementalCapexByYear"][data-year="2027"]'
        )
        ownership = row.locator('input[data-k="ownershipPct"]')
        price = page.locator("#lcPriceTerminal")
        income_tax = page.locator("#lcIncomeTaxRate")
        cash_conversion = page.locator("#lcCashConversion")

        def output(metric: str, year: int = 2027) -> float:
            return _text_value(
                page.locator(f'[data-financial-output="{metric}:{year}"]')
            )

        initial = {
            key: output(key)
            for key in ("revenue", "netIncome", "ocf", "capex", "fcf")
        }
        delta_volume = 1.0
        own = _value(ownership) / 100
        expected_revenue_delta = delta_volume * own * _value(price) / 1.13
        expected_ni_delta = (
            delta_volume
            * own
            * (_value(price) - _value(cost))
            / 1.13
            * (1 - _value(income_tax) / 100)
        )
        _fill(volume, _value(volume) + delta_volume)
        assert output("revenue") - initial["revenue"] == pytest.approx(
            expected_revenue_delta, abs=0.03
        )
        assert output("netIncome") - initial["netIncome"] == pytest.approx(
            expected_ni_delta, abs=0.03
        )
        assert output("ocf") - initial["ocf"] == pytest.approx(
            expected_ni_delta * _value(cash_conversion), abs=0.03
        )
        assert output("fcf") - initial["fcf"] == pytest.approx(
            expected_ni_delta * _value(cash_conversion), abs=0.03
        )

        before_capex = output("fcf")
        _fill(capex, _value(capex) + 3)
        assert output("capex") - initial["capex"] == pytest.approx(3, abs=0.01)
        assert output("fcf") - before_capex == pytest.approx(-3, abs=0.01)

        pe_low = page.locator('[data-valuation-multiple="0:low"]')
        pe_high = page.locator('[data-valuation-multiple="0:high"]')
        _fill(pe_low, 11)
        _fill(pe_high, 9)
        net_income = output("netIncome")
        assert _text_value(
            page.locator('[data-lc-valuation-low="0"]')
        ) == pytest.approx(net_income * 9, abs=0.12)
        assert _text_value(
            page.locator('[data-lc-valuation-high="0"]')
        ) == pytest.approx(net_income * 11, abs=0.12)
        assert not errors
    finally:
        context.close()


@pytest.mark.parametrize(
    ("route", "save_id", "name_id", "saved_id"),
    [
        (
            "/industry/lithium/comparison",
            "lcCompareSave",
            "lcCompareScenarioName",
            "lcCompareSaved",
        ),
        (
            "/industry/copper/comparison",
            "ccCompareSave",
            "ccCompareScenarioName",
            "ccCompareSaved",
        ),
        (
            "/industry/lithium-battery/comparison",
            "compareSave",
            "compareScenarioName",
            "compareSaved",
        ),
    ],
)
def test_industry_comparison_pages_save_scenarios_without_overflow(
    calculator_browser,
    route: str,
    save_id: str,
    name_id: str,
    saved_id: str,
) -> None:
    context, page, errors = _new_page(calculator_browser, route)
    try:
        assert (
            page.evaluate(
                "document.documentElement.scrollWidth"
                " - document.documentElement.clientWidth"
            )
            == 0
        )
        page.locator(f"#{name_id}").fill("跨公司回归")
        page.locator(f"#{save_id}").click()
        assert page.locator(f"#{saved_id} option").count() >= 2
        assert not errors
    finally:
        context.close()


def test_copper_comparison_price_filter_growth_and_valuation_chain(
    calculator_browser,
) -> None:
    context, page, errors = _new_page(
        calculator_browser, "/industry/copper/comparison"
    )
    try:
        page.locator("#ccSensitivityPrices").fill("9000,13000")
        page.wait_for_timeout(120)
        rows = page.locator("#ccSensitivityRows tr")
        assert rows.count() == 2
        low_profit = _text_value(rows.nth(0).locator("td").nth(2))
        high_profit = _text_value(rows.nth(1).locator("td").nth(2))
        assert high_profit > low_profit
        assert "亿元" in rows.nth(1).locator("td").nth(6).inner_text()

        compare_before = page.locator("#ccCompareRows tr").count()
        growth_before = page.locator("#ccGrowthRows tr").count()
        first_check = page.locator("#ccCompareChecks input").first
        first_check.uncheck()
        page.wait_for_timeout(80)
        assert page.locator("#ccCompareRows tr").count() == compare_before - 1
        assert page.locator("#ccGrowthRows tr").count() == growth_before - 1
        assert page.locator("#ccCompareKpis .cc-compare-kpi").first.inner_text().startswith(
            str(compare_before - 1)
        )
        assert not errors
    finally:
        context.close()


def test_calculator_financial_charts_and_numeric_headers_do_not_overlap(
    calculator_browser,
) -> None:
    routes = [
        ("/tools/battery-calculator", "#financialChart"),
        ("/tools/copper-calculator?company_id=635", "#ccFinancialChart"),
        ("/tools/lithium-calculator?company_id=640", "#lcFinancialChart"),
    ]
    for route, selector in routes:
        context, page, errors = _new_page(calculator_browser, route)
        try:
            page.wait_for_selector(f"{selector} .main-svg", timeout=5000)
            geometry = page.evaluate(
                f"""
                () => {{
                  const chart = document.querySelector('{selector}');
                  const legend = chart.querySelector('.legend');
                  const modebar = chart.querySelector('.modebar-container');
                  const lr = legend?.getBoundingClientRect();
                  const mr = modebar?.getBoundingClientRect();
                  const overlap = lr && mr && !(
                    lr.right <= mr.left || mr.right <= lr.left ||
                    lr.bottom <= mr.top || mr.bottom <= lr.top
                  );
                  return {{
                    chartWidth: chart.getBoundingClientRect().width,
                    chartHeight: chart.getBoundingClientRect().height,
                    panelWidth: chart.closest('section').getBoundingClientRect().width,
                    periodCount: Number(chart.dataset.periodCount),
                    seriesCount: Number(chart.dataset.seriesCount),
                    preferredWidth: Number(chart.dataset.preferredWidth),
                    preferredHeight: Number(chart.dataset.preferredHeight),
                    traceCount: chart.querySelectorAll('.trace').length,
                    overlap: Boolean(overlap)
                  }};
                }}
                """
            )
            assert geometry["chartWidth"] > 250
            assert geometry["chartWidth"] <= 960
            assert geometry["chartWidth"] < geometry["panelWidth"]
            assert geometry["chartHeight"] == geometry["preferredHeight"]
            assert geometry["periodCount"] >= 3
            assert geometry["preferredWidth"] == min(
                960, max(680, 500 + geometry["periodCount"] * 75)
            )
            assert geometry["preferredHeight"] == min(
                420,
                max(
                    340,
                    300
                    + geometry["periodCount"] * 10
                    + max(0, geometry["seriesCount"] - 4) * 8,
                ),
            )
            assert geometry["traceCount"] >= 5
            assert not geometry["overlap"]
            assert not errors
        finally:
            context.close()

    context, page, errors = _new_page(
        calculator_browser, "/tools/battery-calculator"
    )
    try:
        alignment = page.evaluate(
            """
            () => [...document.querySelectorAll('#resultTable thead th')]
              .slice(1)
              .map((th, index) => {
                const td = document.querySelector(
                  `#resultTable tbody tr td:nth-child(${index + 2})`
                );
                return [getComputedStyle(th).textAlign, getComputedStyle(td).textAlign];
              })
            """
        )
        assert alignment
        assert all(header == value == "right" for header, value in alignment)
        assert not errors
    finally:
        context.close()


def test_tools_page_exposes_all_industry_comparison_entries(
    calculator_browser,
) -> None:
    context, page, errors = _new_page(calculator_browser, "/tools")
    try:
        hrefs = page.locator(".comparison-link").evaluate_all(
            "(nodes) => nodes.map(node => node.getAttribute('href'))"
        )
        assert hrefs == [
            "/industry/lithium/comparison",
            "/industry/copper/comparison",
            "/industry/lithium-battery/comparison",
        ]
        assert not errors
    finally:
        context.close()


def test_lithium_battery_is_grouped_with_metals_and_shown_in_chain(
    calculator_browser,
) -> None:
    context, page, errors = _new_page(calculator_browser, "/research")
    try:
        metals = page.locator(
            ".research-sector",
            has=page.locator("h3", has_text="有色金属与新能源材料"),
        )
        assert metals.count() == 1
        assert "锂电池" in metals.inner_text()
        other = page.locator(
            ".research-sector",
            has=page.locator("h3", has_text="其他研究"),
        )
        if other.count():
            assert "锂电池" not in other.inner_text()
        assert not errors
    finally:
        context.close()

    context, page, errors = _new_page(calculator_browser, "/industry-chain")
    try:
        page.wait_for_selector(".metals-chain-card .rx-plotly", timeout=5000)
        assert "锂电池" in page.locator(".metals-chain-card").inner_text()
        assert "锂电池" in page.locator(".metals-chain-card").inner_html()
        assert not errors
    finally:
        context.close()


@pytest.mark.parametrize(
    ("route", "prefix", "action_class", "note_class"),
    [
        (
            "/tools/copper-calculator?company_id=635",
            "cc",
            "cc-action",
            "cc-note-cell",
        ),
        (
            "/tools/lithium-calculator?company_id=640",
            "lc",
            "lc-action",
            "lc-note-cell",
        ),
    ],
)
def test_calculator_table_edges_decimals_and_scroll_sync(
    calculator_browser,
    route: str,
    prefix: str,
    action_class: str,
    note_class: str,
) -> None:
    context, page, errors = _new_page(calculator_browser, route)
    try:
        project_table = page.locator(f"#{prefix}ProjectRows").locator("xpath=..")
        scroll = project_table.locator("xpath=..")
        top_scroll = scroll.locator("xpath=preceding-sibling::*[1]")
        scroll.evaluate("(node) => node.scrollLeft = node.scrollWidth")
        page.wait_for_timeout(50)
        geometry = page.evaluate(
            f"""
            () => {{
              const table = document.querySelector('#{prefix}ProjectRows').closest('table');
              const wrap = table.parentElement;
              const action = table.querySelector('th.{action_class}');
              const note = table.querySelector('th.{note_class}');
              const last = table.rows[table.rows.length - 1].cells[
                table.rows[table.rows.length - 1].cells.length - 1
              ];
              const wr = wrap.getBoundingClientRect(), lr = last.getBoundingClientRect();
              return {{
                bodyOverflow: document.body.scrollWidth - innerWidth,
                lastVisible: lr.left >= wr.left - 3 && lr.right <= wr.right + 3,
                actionWidth: action.getBoundingClientRect().width,
                actionBackground: getComputedStyle(action).backgroundColor,
                noteWhiteSpace: getComputedStyle(note).whiteSpace
              }};
            }}
            """
        )
        assert geometry["bodyOverflow"] <= 3
        assert geometry["lastVisible"]
        assert geometry["actionWidth"] >= 90
        assert geometry["actionBackground"] != "rgba(0, 0, 0, 0)"
        assert geometry["noteWhiteSpace"] == "normal"

        top_scroll.evaluate("(node) => node.scrollLeft = 137")
        page.wait_for_timeout(30)
        assert abs(
            top_scroll.evaluate("(node) => node.scrollLeft")
            - scroll.evaluate("(node) => node.scrollLeft")
        ) <= 1

        numeric_values = page.locator(
            f"#{prefix}ProjectRows input[type=number]:not([disabled])"
        ).evaluate_all("(nodes) => nodes.slice(0, 20).map(node => node.value)")
        assert numeric_values
        assert all(re.fullmatch(r"-?\d+\.\d{2}", value) for value in numeric_values)
        assert not errors
    finally:
        context.close()
