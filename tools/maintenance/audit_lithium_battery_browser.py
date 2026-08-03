#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Deterministic desktop/mobile audit for the lithium-battery B-track package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from tools.maintenance import audit_hdi_browser as shared


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "cache" / "lithium_battery_research" / "browser_audit"
PUBLIC_ARTIFACTS = [
    ROOT / "docs" / "industries" / name
    for name in (
        "锂电池.md",
        "锂电池_Q0_历史发展.md",
        "锂电池_Q1_竞争格局.md",
        "锂电池_Q2_市场空间.md",
        "锂电池_Q3_公司壁垒.md",
        "锂电池_Q4_行业特征.md",
        "锂电池_Q5_综述.md",
        "锂电池_Q6_政策与地缘政治.md",
        "锂电池_公司透视.md",
        "锂电池_估值对比.md",
        "锂电池_dimensions.json",
    )
]
PUBLIC_ARTIFACTS.extend(
    sorted(
        (
            ROOT
            / "tools"
            / "viewer"
            / "static"
            / "generated"
            / "lithium_battery"
        ).glob("battery_*.*")
    )
)
VIEWER_RESOURCES = [
    ROOT / "tools" / "viewer" / "app.py",
    ROOT / "tools" / "viewer" / "templates" / "base.html",
    ROOT / "tools" / "viewer" / "templates" / "industry.html",
    ROOT / "tools" / "viewer" / "templates" / "industry_companies.html",
    ROOT / "tools" / "viewer" / "templates" / "industry_valuation.html",
    ROOT / "tools" / "viewer" / "templates" / "company_tag.html",
    ROOT / "tools" / "viewer" / "templates" / "battery_calculator.html",
    ROOT / "tools" / "viewer" / "templates" / "battery_industry_comparison.html",
    ROOT / "tools" / "viewer" / "templates" / "tools_index.html",
    ROOT / "tools" / "viewer" / "static" / "styles.css",
    ROOT / "tools" / "viewer" / "static" / "theme.css",
    ROOT / "tools" / "viewer" / "static" / "v4.css",
]


def _route_states() -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = [
        {
            "route": "/industry/29",
            "tab_key": "main",
            "required": ["锂电池行业", "研究方法与数据", "核心结论"],
        },
        {
            "route": "/industry/29",
            "tab_key": "Q0",
            "required": ["本章综述", "历史与技术"],
        },
        {
            "route": "/industry/29",
            "tab_key": "Q1",
            "required": ["本章综述", "竞争格局"],
        },
        {
            "route": "/industry/29",
            "tab_key": "Q2",
            "required": ["本章综述", "市场空间"],
        },
        {
            "route": "/industry/29",
            "tab_key": "Q3",
            "required": ["本章综述", "公司壁垒"],
        },
        {
            "route": "/industry/29",
            "tab_key": "Q4",
            "required": ["本章综述", "行业经济性与估值"],
        },
        {
            "route": "/industry/29",
            "tab_key": "Q5",
            "required": ["本章综述", "核心结论"],
        },
        {
            "route": "/industry/29",
            "tab_key": "Q6",
            "required": ["本章综述", "政策与地缘政治"],
        },
        {
            "route": "/industry/29",
            "tab_key": "data",
            "required": ["数据点(共"],
        },
        {
            "route": "/industry/29/companies",
            "required": ["宁德时代", "比亚迪", "中创新航", "孚能科技"],
        },
        {
            "route": "/industry/29/valuation",
            "required": ["宁德时代", "PE / ROE 矩阵", "PB / ROE 矩阵"],
        },
        {
            "route": "/industry/lithium-battery/comparison",
            "required": ["锂电池行业比较与情景分析", "宁德时代", "孚能科技"],
        },
        {
            "route": "/tools/battery-calculator?company_id=254",
            "required": [
                "锂电池业务、现金流与估值计算器",
                "分业务量价与毛利",
                "经营、盈利、现金流与股东回报",
                "多方法估值与当前市场对照",
            ],
        },
    ]
    company_states = [
        (254, "宁德时代"),
        (414, "比亚迪"),
        (662, "国轩高科"),
        (663, "中创新航"),
        (664, "亿纬锂能"),
        (665, "瑞浦兰钧"),
        (666, "欣旺达"),
        (661, "鹏辉能源"),
        (667, "孚能科技"),
    ]
    for company_id, name in company_states:
        required = [
            name,
            "综合估值判断与交易观察区",
            "当前市场隐含预期",
            "多方法估值结果",
            "PE / PB Band 与资本回报路径",
            "主要价格暴露",
            "产能利用率",
        ]
        states.append(
            {
                "route": f"/company/{company_id}?industry_id=29",
                "required": required,
                "band_expectations": {
                    "pbBandChart": "plot",
                    "peBandChart": (
                        "empty" if company_id in {665, 667} else "plot"
                    ),
                },
            }
        )
    return states


def _audit_band_dom(
    page: Any,
    state: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Verify Plotly actually rendered, rather than relying on section text."""
    expectations = dict(state.get("band_expectations") or {})
    if not expectations:
        return result
    page.wait_for_timeout(700)
    checks: dict[str, Any] = {}
    for chart_id, expected in expectations.items():
        root = page.locator(f"#{chart_id}")
        rendered = root.locator(".plot-container,.main-svg").count() > 0
        empty = root.locator(".cp-empty").count() > 0
        empty_text = (
            root.locator(".cp-empty").first.inner_text().strip() if empty else ""
        )
        checks[chart_id] = {
            "expected": expected,
            "rendered": rendered,
            "empty": empty,
            "empty_text": empty_text,
        }
        if expected == "plot" and not rendered:
            result["issues"].append(
                f"{chart_id}具备有效历史样本但Plotly未渲染"
            )
        if expected == "empty" and (rendered or not empty or not empty_text):
            result["issues"].append(
                f"{chart_id}应显示可解释的数据不足提示，实际DOM不符合"
            )
    result["band_dom_checks"] = checks
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    shared.OUTPUT_DIR = OUTPUT_DIR
    states = _route_states()
    results: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        if not chrome.is_file():
            raise FileNotFoundError(chrome)
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=str(chrome),
            args=["--disable-gpu"],
        )
        try:
            desktop = browser.new_context(
                viewport={"width": 1440, "height": 1000},
                device_scale_factor=1,
                locale="zh-CN",
            )
            try:
                for state in states:
                    page = desktop.new_page()
                    result = shared._audit_route(
                        page,
                        args.base_url,
                        str(state["route"]),
                        "desktop",
                        required_text=list(state["required"]),
                        tab_key=state.get("tab_key"),
                    )
                    results.append(_audit_band_dom(page, state, result))
                    page.close()
                source_page = desktop.new_page()
                source_drawer = shared._audit_source_drawers(
                    source_page, args.base_url, states
                )
                source_page.close()
            finally:
                desktop.close()

            mobile = browser.new_context(
                viewport={"width": 390, "height": 844},
                device_scale_factor=1,
                is_mobile=True,
                locale="zh-CN",
            )
            try:
                for state in states:
                    page = mobile.new_page()
                    result = shared._audit_route(
                        page,
                        args.base_url,
                        str(state["route"]),
                        "mobile",
                        required_text=list(state["required"]),
                        tab_key=state.get("tab_key"),
                    )
                    results.append(_audit_band_dom(page, state, result))
                    page.close()
            finally:
                mobile.close()
        finally:
            browser.close()

    issues = [
        f"{row['viewport']} {row['route']}#{row.get('tab_key') or 'page'}: {issue}"
        for row in results
        for issue in row["issues"]
    ]
    issues.extend(
        f"source drawer: {issue}" for issue in source_drawer["issues"]
    )
    payload = {
        "schema_version": "lithium_battery.browser_audit.v1",
        "base_url": args.base_url,
        "public_artifact_hashes": shared._bound_resource_hashes(PUBLIC_ARTIFACTS),
        "viewer_resource_hashes": shared._bound_resource_hashes(VIEWER_RESOURCES),
        "status": "GREEN" if not issues else "RED",
        "route_count": len(results),
        "routes": results,
        "source_drawer": source_drawer,
        "issues": issues,
    }
    output = OUTPUT_DIR / "browser_audit.json"
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "status": payload["status"],
                "route_count": len(results),
                "issues": issues,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
