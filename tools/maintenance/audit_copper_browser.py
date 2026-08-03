#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Desktop/mobile Playwright audit for the copper industry B-track pages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from tools.maintenance import audit_hdi_browser as shared


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "cache" / "copper_research" / "browser_audit"
PUBLIC_ARTIFACTS = [
    ROOT / "docs" / "industries" / "铜.md",
    ROOT / "docs" / "industries" / "铜_Q0_历史发展.md",
    ROOT / "docs" / "industries" / "铜_Q1_竞争格局.md",
    ROOT / "docs" / "industries" / "铜_Q2_市场空间.md",
    ROOT / "docs" / "industries" / "铜_Q3_公司壁垒.md",
    ROOT / "docs" / "industries" / "铜_Q4_行业特征.md",
    ROOT / "docs" / "industries" / "铜_Q5_资源政治.md",
    ROOT / "docs" / "industries" / "铜_Q6_综述.md",
    ROOT / "docs" / "industries" / "铜_Q7_补充.md",
    ROOT / "docs" / "industries" / "铜_公司透视.md",
    ROOT / "docs" / "industries" / "铜_估值对比.md",
]
VIEWER_RESOURCES = [
    ROOT / "tools" / "viewer" / "app.py",
    ROOT / "tools" / "viewer" / "templates" / "base.html",
    ROOT / "tools" / "viewer" / "templates" / "industry.html",
    ROOT / "tools" / "viewer" / "templates" / "industry_companies.html",
    ROOT / "tools" / "viewer" / "templates" / "industry_valuation.html",
    ROOT / "tools" / "viewer" / "templates" / "company_tag.html",
    ROOT / "tools" / "viewer" / "templates" / "copper_calculator.html",
    ROOT / "tools" / "viewer" / "static" / "styles.css",
    ROOT / "tools" / "viewer" / "static" / "theme.css",
    ROOT / "tools" / "viewer" / "static" / "v4.css",
]


def _route_states() -> list[dict[str, Any]]:
    return [
        {
            "route": "/industry/26",
            "tab_key": "main",
            "required": ["铜行业", "供需判断", "三家公司结论"],
        },
        {
            "route": "/industry/26",
            "tab_key": "Q0",
            "required": ["本章综述", "历史发展"],
        },
        {
            "route": "/industry/26",
            "tab_key": "Q1",
            "required": ["本章综述", "竞争格局"],
        },
        {
            "route": "/industry/26",
            "tab_key": "Q2",
            "required": ["本章综述", "短期平衡与长期缺口"],
        },
        {
            "route": "/industry/26",
            "tab_key": "Q3",
            "required": ["本章综述", "公司壁垒"],
        },
        {
            "route": "/industry/26",
            "tab_key": "Q4",
            "required": ["本章综述", "行业特征"],
        },
        {
            "route": "/industry/26",
            "tab_key": "Q5",
            "required": ["本章综述", "资源政治"],
        },
        {
            "route": "/industry/26",
            "tab_key": "Q6",
            "required": ["本章综述", "综合判断"],
        },
        {
            "route": "/industry/26",
            "tab_key": "Q7",
            "required": ["本章综述", "模型、监控与资料边界"],
        },
        {
            "route": "/industry/26",
            "tab_key": "data",
            "required": ["数据点(共"],
        },
        {
            "route": "/industry/26/companies",
            "required": ["紫金矿业", "洛阳钼业", "五矿资源"],
        },
        {
            "route": "/industry/26/valuation",
            "required": ["紫金矿业", "洛阳钼业", "五矿资源"],
        },
        {
            "route": "/company/635?industry_id=26",
            "required": [
                "紫金矿业",
                "综合估值判断与交易观察区",
                "当前市场隐含预期",
                "PB Band",
                "PE Band",
            ],
        },
        {
            "route": "/company/634?industry_id=26",
            "required": [
                "洛阳钼业",
                "综合估值判断与交易观察区",
                "当前市场隐含预期",
                "PB Band",
                "PE Band",
            ],
        },
        {
            "route": "/company/636?industry_id=26",
            "required": [
                "五矿资源",
                "综合估值判断与交易观察区",
                "当前市场隐含预期",
            ],
        },
        {
            "route": "/tools/copper-calculator?company_id=635",
            "required": [
                "铜矿项目、现金流与股东回报计算器",
                "项目、投产路径与年度经营参数",
                "经营、盈利、现金流与股东回报",
                "多方法估值与当前市场对照",
            ],
        },
    ]


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
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=str(chrome),
            args=["--disable-gpu"],
        )
        desktop = browser.new_context(
            viewport={"width": 1440, "height": 1000}, device_scale_factor=1
        )
        for state in states:
            page = desktop.new_page()
            results.append(
                shared._audit_route(
                    page,
                    args.base_url,
                    str(state["route"]),
                    "desktop",
                    required_text=list(state["required"]),
                    tab_key=state.get("tab_key"),
                )
            )
            page.close()
        source_page = desktop.new_page()
        source_drawer = shared._audit_source_drawers(
            source_page, args.base_url, states
        )
        source_page.close()
        desktop.close()

        mobile = browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=1,
            is_mobile=True,
        )
        for state in states:
            page = mobile.new_page()
            results.append(
                shared._audit_route(
                    page,
                    args.base_url,
                    str(state["route"]),
                    "mobile",
                    required_text=list(state["required"]),
                    tab_key=state.get("tab_key"),
                )
            )
            page.close()
        mobile.close()
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
        "schema_version": "copper.browser_audit.v1",
        "base_url": args.base_url,
        "public_artifact_hashes": shared._bound_resource_hashes(
            PUBLIC_ARTIFACTS
        ),
        "viewer_resource_hashes": shared._bound_resource_hashes(
            VIEWER_RESOURCES
        ),
        "status": "GREEN" if not issues else "RED",
        "route_count": len(results),
        "routes": results,
        "source_drawer": source_drawer,
        "issues": issues,
    }
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
