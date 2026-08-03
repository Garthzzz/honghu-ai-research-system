#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Desktop/mobile browser and calculator interaction audit for lithium research."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

from tools.maintenance import audit_hdi_browser as shared


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "cache" / "lithium_research" / "browser_audit"
INDUSTRY_DOC_NAMES = [
    "锂.md",
    "锂_Q0_历史发展.md",
    "锂_Q1_竞争格局.md",
    "锂_Q2_市场空间.md",
    "锂_Q3_公司壁垒.md",
    "锂_Q4_行业特征.md",
    "锂_Q5_资源政治.md",
    "锂_Q6_综述.md",
    "锂_Q7_补充.md",
    "锂_公司透视.md",
    "锂_估值对比.md",
    "碳酸锂.md",
    "碳酸锂_Q0_历史发展.md",
    "碳酸锂_Q1_竞争格局.md",
    "碳酸锂_Q2_市场空间.md",
    "碳酸锂_Q3_公司壁垒.md",
    "碳酸锂_Q4_行业特征.md",
    "碳酸锂_Q5_资源政治.md",
    "碳酸锂_Q6_综述.md",
    "碳酸锂_Q7_补充.md",
    "碳酸锂_公司透视.md",
    "碳酸锂_估值对比.md",
]
PUBLIC_ARTIFACTS = [
    ROOT / "docs" / "industries" / name for name in INDUSTRY_DOC_NAMES
]
VIEWER_RESOURCES = [
    ROOT / "tools" / "viewer" / "app.py",
    ROOT / "tools" / "financial" / "read_models.py",
    ROOT / "tools" / "viewer" / "templates" / "base.html",
    ROOT / "tools" / "viewer" / "templates" / "industry.html",
    ROOT / "tools" / "viewer" / "templates" / "industry_companies.html",
    ROOT / "tools" / "viewer" / "templates" / "industry_valuation.html",
    ROOT / "tools" / "viewer" / "templates" / "company_tag.html",
    ROOT / "tools" / "viewer" / "templates" / "lithium_calculator.html",
    ROOT / "tools" / "viewer" / "static" / "styles.css",
    ROOT / "tools" / "viewer" / "static" / "theme.css",
    ROOT / "tools" / "viewer" / "static" / "v4.css",
]
COMPANIES = [
    (640, "赣锋锂业"),
    (641, "融捷股份"),
    (642, "盛新锂能"),
    (643, "盐湖股份"),
    (644, "大中矿业"),
    (645, "雅化集团"),
    (646, "天华新能"),
    (647, "天齐锂业"),
    (648, "永杉锂业"),
    (649, "中矿资源"),
    (650, "藏格矿业"),
    (651, "西藏城投"),
    (652, "永兴材料"),
]


def _route_states(industry_filter: str = "both") -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = [
        {
            "route": "/research",
            "required": [
                "有色金属与新能源材料",
                "铜",
                "锂",
                "碳酸锂",
                "Q5 核心结论",
            ],
        },
        {
            "route": "/companies",
            "required": ["公司", "财务快照"],
        },
    ]
    industry_rows = {
        "锂": ((27, "锂"),),
        "碳酸锂": ((28, "碳酸锂"),),
        "both": ((27, "锂"), (28, "碳酸锂")),
    }[industry_filter]
    for industry_id, industry_name in industry_rows:
        states.extend(
            [
                {
                    "route": f"/industry/{industry_id}",
                    "tab_key": "main",
                    "required": [
                        industry_name,
                        "核心结论",
                        (
                            "投资结论"
                            if industry_id == 28
                            else "研究结论怎样转成行动"
                        ),
                    ],
                },
                *[
                    {
                        "route": f"/industry/{industry_id}",
                        "tab_key": f"Q{index}",
                        "required": ["本章综述"],
                    }
                    for index in range(8)
                ],
                {
                    "route": f"/industry/{industry_id}",
                    "tab_key": "data",
                    "required": ["数据点"],
                },
                {
                    "route": f"/industry/{industry_id}/companies",
                    "required": ["赣锋锂业", "天齐锂业", "中矿资源"],
                },
                {
                    "route": f"/industry/{industry_id}/valuation",
                    "required": ["估值对比", "有 PE/PB", "PE / ROE 矩阵"],
                },
            ]
        )
    company_context_ids: list[int] = []
    if industry_filter in {"锂", "both"}:
        company_context_ids.append(27)
    if industry_filter in {"碳酸锂", "both"}:
        company_context_ids.append(28)
    for company_industry_id in company_context_ids:
        for company_id, name in COMPANIES:
            states.append(
                {
                    "route": (
                        f"/company/{company_id}"
                        f"?industry_id={company_industry_id}"
                    ),
                    "required": [
                        name,
                        "综合估值判断与交易观察区",
                        "当前市场隐含预期",
                        "PB—ROE",
                        "PB Band",
                    ],
                }
            )
    states.append(
        {
            "route": "/tools/lithium-calculator?company_id=640",
            "required": [
                "碳酸锂项目与估值计算器",
                "简化模式",
                "锂矿项目明细",
                "公司锂矿/盐湖项目表",
                "公司经营与项目备注",
                "核心结果",
                "锂价敏感性与估值",
                "公司资源、利润与估值总览",
                "公司资源增长与长期业绩比较",
                "2030年业绩/2026年业绩",
                "2030年业绩/2025年业绩",
                "计算方法",
            ],
        }
    )
    return states


def _company_perspective_readability(page: Page) -> dict[str, Any]:
    """Catch semantic-width failures that overflow-only audits cannot see."""
    return page.evaluate(
        """
        () => {
          const body = document.querySelector('.company-perspective-body');
          if (!body) return {exists:false};
          const overview = body.querySelector('.cp-research-overview-table');
          const nameCells = overview
            ? Array.from(overview.querySelectorAll('tbody td:first-child'))
            : [];
          const names = nameCells.map(cell => {
            const style = getComputedStyle(cell);
            const lineHeight = parseFloat(style.lineHeight) ||
              parseFloat(style.fontSize) * 1.4;
            const rect = cell.getBoundingClientRect();
            const text = (cell.innerText || '').replace(/\\s+/g, '').trim();
            const textRange = document.createRange();
            textRange.selectNodeContents(cell);
            const lineTops = Array.from(textRange.getClientRects())
              .filter(item => item.width > 0 && item.height > 0)
              .map(item => Math.round(item.top * 2) / 2)
              .filter((value, index, values) => values.indexOf(value) === index);
            const renderedLines = Math.max(1, lineTops.length);
            return {
              text,
              width: rect.width,
              height: rect.height,
              lineHeight,
              renderedLines,
              oneCharacterPerLine:
                text.length >= 3 && renderedLines >= text.length - 0.35
            };
          });
          const headings = Array.from(
            body.querySelectorAll('h3.company-analysis-heading')
          );
          const wrappers = Array.from(body.querySelectorAll('.md-table-wrap'));
          return {
            exists:true,
            overviewTableCount: overview ? 1 : 0,
            overviewScrollWidth: overview ? overview.scrollWidth : 0,
            overviewWrapperWidth:
              overview?.closest('.md-table-wrap')?.clientWidth || 0,
            companyNameCells:names,
            companyHeadingCount:headings.length,
            companyMarkerCount:headings.filter(
              heading => heading.querySelector('.company-analysis-kicker')
            ).length,
            separatedTableCount:wrappers.filter(wrap => {
              const style=getComputedStyle(wrap);
              return parseFloat(style.borderTopWidth) >= 1 &&
                     parseFloat(style.borderBottomWidth) >= 1;
            }).length,
            tableWrapperCount:wrappers.length
          };
        }
        """
    )


def _research_sector_q5_readability(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """
        () => {
          const sector = Array.from(document.querySelectorAll('.research-sector'))
            .find(node => node.querySelector('h3')?.textContent.trim() ===
                          '有色金属与新能源材料');
          if (!sector) return {exists:false, q5IndustryCount:0, industries:[]};
          const cards=Array.from(sector.querySelectorAll('.ind-card'));
          return {
            exists:true,
            q5IndustryCount:cards.filter(
              card => card.querySelector('.ind-card-concl-label') &&
                      card.querySelectorAll('.ind-card-concl li').length > 0
            ).length,
            industries:cards.map(card => ({
              name:card.querySelector('.ind-card-name')?.textContent.trim() || '',
              conclusions:card.querySelectorAll('.ind-card-concl li').length
            }))
          };
        }
        """
    )


def _company_directory_readability(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """
        () => {
          const cards=Array.from(document.querySelectorAll('.co-card'));
          return {
            cardCount:cards.length,
            cardsWithFinancialSnapshot:cards.filter(
              card => card.querySelector('.co-source')
            ).length,
            cardsWithOldPlaceholder:cards.filter(
              card => card.textContent.includes(
                '公司画像已建立；业务简介仍按来源逐步补齐。'
              )
            ).length,
            cardsWithAllMetricDashes:cards.filter(card => {
              const values=Array.from(card.querySelectorAll('.co-metrics b'))
                .map(node => node.textContent.trim());
              return values.length === 4 && values.every(
                value => value === '—' || value === '暂缺'
              );
            }).length
          };
        }
        """
    )


def _audit_calculator_detail(
    page: Page,
    base_url: str,
    viewport_name: str,
    *,
    exercise_interactions: bool,
) -> dict[str, Any]:
    issues: list[str] = []
    response = page.goto(
        base_url + "/tools/lithium-calculator?company_id=640",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    page.wait_for_timeout(400)
    if response is None or response.status != 200:
        issues.append(f"HTTP status={response.status if response else None}")

    if not page.locator("#lcDetailedPanel").is_visible():
        issues.append("页面默认没有展示锂矿项目明细")
    if page.locator("#lcSimplePanel").is_visible():
        issues.append("页面默认错误进入简化模式")
    workbook_notes = page.locator("#lcWorkbookNotes .lc-workbook-note").count()
    if workbook_notes < 1:
        issues.append("公司经营与项目备注没有展示")
    workbook_project_rows = page.locator(
        '#lcProjectRows tr:has(select[data-k="type"] option[value="resource"]:checked)'
    ).count()
    if workbook_project_rows < 13:
        issues.append(
            f"赣锋锂业项目级资源记录没有完整展示: {workbook_project_rows}"
        )
    ownership_inputs = page.locator(
        '#lcProjectRows input[data-k="ownershipPct"]'
    ).count()
    if ownership_inputs < 13:
        issues.append(f"赣锋锂业逐矿权益输入缺失: {ownership_inputs}")
    first_status = page.locator(
        '#lcProjectRows tr:first-child textarea[data-k="status"]'
    ).input_value()
    if "年起计入模型" not in first_status:
        issues.append("逐矿项目没有明确模型权益计入起点")

    initial_profit = page.locator("#lcTerminalProfit").inner_text()
    page.locator("#lcPriceTerminal").fill("18")
    page.wait_for_timeout(100)
    changed_profit = page.locator("#lcTerminalProfit").inner_text()
    if changed_profit == initial_profit:
        issues.append("修改终局锂价后利润没有变化")

    detail_tab = page.locator('[data-mode="detailed"]')
    detail_tab.click()
    page.wait_for_timeout(150)
    if not page.locator("#lcDetailedPanel").is_visible():
        issues.append("项目明细模式未显示")
    before_rows = page.locator("#lcProjectRows tr").count()
    page.locator("#lcAddProject").click()
    after_rows = page.locator("#lcProjectRows tr").count()
    if after_rows != before_rows + 1:
        issues.append("新增项目未增加一行")
    annual_inputs = page.locator(
        '#lcProjectRows tr:first-child input[data-series="volumeByYear"]'
    ).count()
    if annual_inputs != 6:
        issues.append(f"逐项目年度产量没有完整覆盖2025—2030: {annual_inputs}")
    current_summary = page.locator(
        '#lcCompanySummaryRows tr:has-text("赣锋锂业") td:nth-child(4)'
    )
    attributable_before = current_summary.inner_text()
    page.locator(
        '#lcProjectRows tr:last-child input[data-series="volumeByYear"]'
        '[data-year="2030"]'
    ).fill("1")
    page.wait_for_timeout(100)
    attributable_after = current_summary.inner_text()
    if attributable_after == attributable_before:
        issues.append("新增项目没有进入跨公司权益资源汇总")

    geometry = shared._page_geometry(page)
    if geometry["bodyOverflowPx"] > 3:
        issues.append(f"项目明细模式整页横向溢出 {geometry['bodyOverflowPx']}px")
    bad_tables = [
        item["index"]
        for item in geometry["tables"]
        if not item["visibleRightAfterScroll"] or not item["visibleLeftAfterScroll"]
    ]
    if bad_tables:
        issues.append(f"项目明细模式最右列不可完整读取: {bad_tables}")

    if exercise_interactions:
        page.locator("#lcScenarioName").fill("浏览器审计情景")
        page.locator("#lcSave").click()
        saved_options = page.locator("#lcSaved option").count()
        if saved_options < 2:
            issues.append("保存情景后下拉列表没有新增情景")
        else:
            page.locator("#lcSaved").select_option(index=saved_options - 1)
            saved_profit = page.locator("#lcTerminalProfit").inner_text()
            page.locator("#lcPriceTerminal").fill("9")
            page.once("dialog", lambda dialog: dialog.accept())
            page.locator("#lcLoad").click()
            page.wait_for_timeout(100)
            if page.locator("#lcTerminalProfit").inner_text() != saved_profit:
                issues.append("载入已保存情景后结果没有恢复")
            page.once("dialog", lambda dialog: dialog.accept())
            page.locator("#lcDeleteSaved").click()
            if page.locator("#lcSaved option").count() != 1:
                issues.append("删除已保存情景后仍残留在列表")

        detail_tab.focus()
        page.keyboard.press("Tab")
        focused = page.evaluate(
            "() => Boolean(document.activeElement && document.activeElement !== document.body)"
        )
        if not focused:
            issues.append("键盘Tab未进入可聚焦控件")

    shot = OUTPUT_DIR / f"{viewport_name}_calculator_detailed.png"
    page.screenshot(path=str(shot), full_page=False)
    return {
        "viewport": viewport_name,
        "http_status": response.status if response else None,
        "initial_terminal_profit": initial_profit,
        "changed_terminal_profit": changed_profit,
        "project_rows_before_add": before_rows,
        "project_rows_after_add": after_rows,
        "annual_volume_inputs_in_first_project": annual_inputs,
        "workbook_note_count": workbook_notes,
        "workbook_resource_project_rows": workbook_project_rows,
        "ownership_input_count": ownership_inputs,
        "first_project_status": first_status,
        "summary_attributable_before_add": attributable_before,
        "summary_attributable_after_add": attributable_after,
        "geometry": geometry,
        "screenshot": str(shot.relative_to(ROOT)).replace("\\", "/"),
        "screenshot_sha256": shared._sha256(shot),
        "issues": issues,
    }


def main() -> None:
    global OUTPUT_DIR
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument(
        "--industry",
        choices=("both", "锂", "碳酸锂"),
        default="both",
        help="仅审计指定行业；锂优先重写期间可独立验收锂页面。",
    )
    parser.add_argument(
        "--part",
        choices=("all", "desktop", "mobile", "source", "calculator", "combine"),
        default="all",
        help="拆分执行长时间浏览器审计；combine 汇总已有分片。",
    )
    parser.add_argument(
        "--include-calculator",
        action="store_true",
        help="combine 时把独立计算器审计纳入总门禁。",
    )
    parser.add_argument(
        "--route-group",
        choices=("all", "industry", "company"),
        default="all",
        help="desktop/mobile 分片继续按行业页与公司页拆分。",
    )
    parser.add_argument("--shard-index", type=int, default=1)
    parser.add_argument("--shard-count", type=int, default=1)
    args = parser.parse_args()

    OUTPUT_DIR = OUTPUT_DIR / {
        "锂": "lithium",
        "碳酸锂": "lithium_carbonate",
        "both": "combined",
    }[args.industry]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    shared.OUTPUT_DIR = OUTPUT_DIR
    research_states = [
        state
        for state in _route_states(args.industry)
        if not str(state["route"]).startswith("/tools/")
    ]
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

    def write_part(name: str, payload: dict[str, Any]) -> Path:
        output = OUTPUT_DIR / f"browser_audit_{name}.json"
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "output": str(output),
                    "status": payload.get("status"),
                    "route_count": len(payload.get("routes") or []),
                    "source_count": (payload.get("source_drawer") or {}).get(
                        "checked_count"
                    ),
                    "issues": payload.get("issues") or [],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return output

    def route_part(viewport_name: str) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        if args.route_group == "industry":
            states_for_part = [
                state
                for state in research_states
                if not str(state["route"]).startswith("/company/")
            ]
        elif args.route_group == "company":
            states_for_part = [
                state
                for state in research_states
                if str(state["route"]).startswith("/company/")
            ]
        else:
            states_for_part = research_states
        if args.shard_count < 1 or not 1 <= args.shard_index <= args.shard_count:
            raise ValueError("shard-index 必须位于 1..shard-count")
        states_for_part = states_for_part[
            args.shard_index - 1 :: args.shard_count
        ]
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=str(chrome),
                args=["--disable-gpu"],
            )
            if viewport_name == "desktop":
                context = browser.new_context(
                    viewport={"width": 1440, "height": 1000},
                    device_scale_factor=1,
                )
            else:
                context = browser.new_context(
                    viewport={"width": 390, "height": 844},
                    device_scale_factor=1,
                    is_mobile=True,
                )
            for state in states_for_part:
                page = context.new_page()
                route = str(state["route"])
                result = shared._audit_route(
                    page,
                    args.base_url,
                    route,
                    viewport_name,
                    required_text=list(state["required"]),
                    tab_key=state.get("tab_key"),
                )
                if route == "/companies":
                    readability = _company_directory_readability(page)
                    result["company_directory_readability"] = readability
                    if readability.get("cardsWithOldPlaceholder"):
                        result["issues"].append("公司列表仍出现旧的机械占位简介")
                    if readability.get("cardsWithFinancialSnapshot", 0) < 1:
                        result["issues"].append("公司列表没有读取财务快照来源")
                elif route.startswith("/industry/") and route.endswith("/companies"):
                    readability = _company_perspective_readability(page)
                    result["company_perspective_readability"] = readability
                    if readability.get("overviewTableCount") != 1:
                        result["issues"].append("公司透视缺少语义宽表")
                    bad_names = [
                        item.get("text")
                        for item in readability.get("companyNameCells") or []
                        if item.get("oneCharacterPerLine")
                        or float(item.get("width") or 0) < 96
                    ]
                    if bad_names:
                        result["issues"].append(
                            f"公司名仍被逐字换行或列宽不足: {bad_names}"
                        )
                    if readability.get("companyHeadingCount", 0) < 13:
                        result["issues"].append(
                            "研究与分析区缺少13家公司段落定位标题"
                        )
                    if readability.get("companyMarkerCount") != readability.get(
                        "companyHeadingCount"
                    ):
                        result["issues"].append("公司段落标题缺少可视标签")
                    if readability.get("separatedTableCount") != readability.get(
                        "tableWrapperCount"
                    ):
                        result["issues"].append("研究正文表格仍有边界不清的容器")
                elif route == "/research":
                    readability = _research_sector_q5_readability(page)
                    result["metal_sector_q5_readability"] = readability
                    if readability.get("q5IndustryCount") != 3:
                        result["issues"].append(
                            f"有色板块Q5核心结论未覆盖3个行业: {readability}"
                        )
                results.append(result)
                page.close()
            context.close()
            browser.close()
        issues = [
            f"{row['viewport']} {row['route']}#{row.get('tab_key') or 'page'}: {issue}"
            for row in results
            for issue in row["issues"]
        ]
        return {
            "schema_version": "lithium.browser_audit.part.v1",
            "industry_filter": args.industry,
            "part": (
                f"{viewport_name}_{args.route_group}_"
                f"s{args.shard_index}of{args.shard_count}"
            ),
            "base_url": args.base_url,
            "routes": results,
            "status": "GREEN" if not issues else "RED",
            "issues": issues,
        }

    def source_part() -> dict[str, Any]:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=str(chrome),
                args=["--disable-gpu"],
            )
            context = browser.new_context(
                viewport={"width": 1440, "height": 1000},
                device_scale_factor=1,
            )
            page = context.new_page()
            source_drawer = shared._audit_source_drawers(
                page,
                args.base_url,
                research_states,
            )
            page.close()
            context.close()
            browser.close()
        issues = [
            f"source drawer: {issue}" for issue in source_drawer["issues"]
        ]
        return {
            "schema_version": "lithium.browser_audit.part.v1",
            "industry_filter": args.industry,
            "part": "source",
            "base_url": args.base_url,
            "source_drawer": source_drawer,
            "status": "GREEN" if not issues else "RED",
            "issues": issues,
        }

    def calculator_part() -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=str(chrome),
                args=["--disable-gpu"],
            )
            for viewport_name, viewport, is_mobile in (
                ("desktop", {"width": 1440, "height": 1000}, False),
                ("mobile", {"width": 390, "height": 844}, True),
            ):
                context = browser.new_context(
                    viewport=viewport,
                    device_scale_factor=1,
                    is_mobile=is_mobile,
                )
                page = context.new_page()
                results.append(
                    _audit_calculator_detail(
                        page,
                        args.base_url,
                        viewport_name,
                        exercise_interactions=viewport_name == "desktop",
                    )
                )
                page.close()
                context.close()
            browser.close()
        issues = [
            f"calculator {row['viewport']}: {issue}"
            for row in results
            for issue in row["issues"]
        ]
        return {
            "schema_version": "lithium.browser_audit.part.v1",
            "industry_filter": args.industry,
            "part": "calculator",
            "base_url": args.base_url,
            "calculator_interaction": results,
            "status": "GREEN" if not issues else "RED",
            "issues": issues,
        }

    def combine() -> dict[str, Any]:
        required_parts: list[str] = []
        for viewport in ("desktop", "mobile"):
            for group, shard_count in (("industry", 4), ("company", 2)):
                complete_name = f"{viewport}_{group}_s1of1"
                complete_path = (
                    OUTPUT_DIR / f"browser_audit_{complete_name}.json"
                )
                if complete_path.exists():
                    required_parts.append(complete_name)
                    continue
                required_parts.extend(
                    f"{viewport}_{group}_s{index}of{shard_count}"
                    for index in range(1, shard_count + 1)
                )
        required_parts.append("source")
        if args.include_calculator:
            required_parts.append("calculator")
        loaded: dict[str, dict[str, Any]] = {}
        for name in required_parts:
            path = OUTPUT_DIR / f"browser_audit_{name}.json"
            if not path.exists():
                raise FileNotFoundError(f"缺少浏览器审计分片: {path}")
            loaded[name] = json.loads(path.read_text(encoding="utf-8"))
        routes = [
            row
            for name in required_parts
            if name != "source" and name != "calculator"
            for row in loaded[name].get("routes") or []
        ]
        calculator_results = (
            loaded.get("calculator", {}).get("calculator_interaction") or []
        )
        source_drawer = loaded["source"].get("source_drawer") or {}
        issues = [
            issue
            for name in required_parts
            for issue in loaded[name].get("issues") or []
        ]
        return {
            "schema_version": "lithium.browser_audit.v2",
            "industry_filter": args.industry,
            "base_url": args.base_url,
            "public_artifact_hashes": shared._bound_resource_hashes(
                PUBLIC_ARTIFACTS
            ),
            "viewer_resource_hashes": shared._bound_resource_hashes(
                VIEWER_RESOURCES
            ),
            "included_parts": required_parts,
            "status": "GREEN" if not issues else "RED",
            "route_count": len(routes),
            "routes": routes,
            "calculator_interaction": calculator_results,
            "source_drawer": source_drawer,
            "issues": issues,
        }

    if args.part == "desktop":
        payload = route_part("desktop")
    elif args.part == "mobile":
        payload = route_part("mobile")
    elif args.part == "source":
        payload = source_part()
    elif args.part == "calculator":
        payload = calculator_part()
    elif args.part == "combine":
        payload = combine()
        output = OUTPUT_DIR / "browser_audit.json"
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "output": str(output),
                    "status": payload["status"],
                    "route_count": payload["route_count"],
                    "source_count": payload["source_drawer"].get(
                        "checked_count"
                    ),
                    "included_parts": payload["included_parts"],
                    "issues": payload["issues"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        if payload["issues"]:
            raise SystemExit(1)
        return
    else:
        raise ValueError(
            "--part all 已停用，请分四次执行 desktop/mobile × "
            "industry/company，再执行 source 与 combine。"
        )

    output_part = (
        (
            f"{args.part}_{args.route_group}_"
            f"s{args.shard_index}of{args.shard_count}"
        )
        if args.part in {"desktop", "mobile"}
        else args.part
    )
    write_part(output_part, payload)
    if payload.get("issues"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
