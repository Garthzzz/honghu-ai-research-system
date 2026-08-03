#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Deterministic desktop/mobile browser audit for the HDI B-track package."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "cache" / "hdi_research" / "browser_audit"
PUBLIC_ARTIFACTS = [
    ROOT / "docs" / "industries" / "HDI板.md",
    ROOT / "docs" / "industries" / "HDI板_Q0_历史发展.md",
    ROOT / "docs" / "industries" / "HDI板_Q1_竞争格局.md",
    ROOT / "docs" / "industries" / "HDI板_公司透视.md",
    ROOT / "docs" / "industries" / "HDI板_估值对比.md",
    ROOT / "docs" / "industries" / "HDI板_Q2_市场空间.md",
    ROOT / "docs" / "industries" / "HDI板_Q3_公司壁垒.md",
    ROOT / "docs" / "industries" / "HDI板_Q4_行业特征.md",
    ROOT / "docs" / "industries" / "HDI板_Q5_综述.md",
]
VIEWER_RESOURCES = [
    ROOT / "tools" / "viewer" / "app.py",
    ROOT / "tools" / "viewer" / "templates" / "base.html",
    ROOT / "tools" / "viewer" / "templates" / "industry.html",
    ROOT / "tools" / "viewer" / "templates" / "industry_companies.html",
    ROOT / "tools" / "viewer" / "templates" / "industry_valuation.html",
    ROOT / "tools" / "viewer" / "templates" / "company_tag.html",
    ROOT / "tools" / "viewer" / "static" / "styles.css",
    ROOT / "tools" / "viewer" / "static" / "theme.css",
    ROOT / "tools" / "viewer" / "static" / "v4.css",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bound_resource_hashes(paths: list[Path]) -> dict[str, str]:
    missing = [str(path.relative_to(ROOT)) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"浏览器审计缺少待绑定资源: {missing}")
    return {
        str(path.relative_to(ROOT)).replace("\\", "/"): f"sha256:{_sha256(path)}"
        for path in paths
    }


def _page_geometry(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """
        () => {
          const body = document.body;
          const tables = Array.from(document.querySelectorAll('table'))
            .filter(table => table.getClientRects().length > 0 && getComputedStyle(table).visibility !== 'hidden')
            .map((table, index) => {
            const tableOwnsScroll = table.scrollWidth > table.clientWidth + 3;
            const wrap = tableOwnsScroll
              ? table
              : (table.closest('.cp-table-scroll,.table-scroll,.md-table-wrap,[role="region"]') || table.parentElement);
            const before = {
              index,
              rows: table.rows.length,
              columns: table.rows.length ? table.rows[0].cells.length : 0,
              tableScrollWidth: table.scrollWidth,
              wrapClientWidth: wrap ? wrap.clientWidth : 0,
              wrapScrollWidth: wrap ? wrap.scrollWidth : 0,
              wrapTag: wrap ? wrap.tagName : null,
              wrapClass: wrap ? wrap.className : null,
              scrollLeftBefore: wrap ? wrap.scrollLeft : 0
            };
            if (wrap) wrap.scrollLeft = Math.max(0, wrap.scrollWidth - wrap.clientWidth);
            const lastCells = Array.from(table.rows).map(row => row.cells[row.cells.length - 1]).filter(Boolean);
            const wrapRect = wrap ? wrap.getBoundingClientRect() : null;
            const visibleRight = lastCells.every(cell => !wrapRect || cell.getBoundingClientRect().right <= wrapRect.right + 3);
            const visibleLeft = lastCells.every(cell => !wrapRect || cell.getBoundingClientRect().left >= wrapRect.left - 3);
            return {
              ...before,
              scrollLeftAfter: wrap ? wrap.scrollLeft : 0,
              visibleRightAfterScroll: visibleRight,
              visibleLeftAfterScroll: visibleLeft
            };
          });
          const images = Array.from(document.querySelectorAll('main img,.content img,.md-body img'))
            .filter(img => img.getClientRects().length > 0 && getComputedStyle(img).visibility !== 'hidden')
            .map((img, index) => ({
            index,
            src: img.getAttribute('src'),
            complete: img.complete,
            naturalWidth: img.naturalWidth,
            naturalHeight: img.naturalHeight,
            clientWidth: img.clientWidth,
            clientHeight: img.clientHeight
          }));
          return {
            viewportWidth: window.innerWidth,
            bodyClientWidth: body.clientWidth,
            bodyScrollWidth: body.scrollWidth,
            bodyOverflowPx: Math.max(0, body.scrollWidth - window.innerWidth),
            tables,
            images,
            title: document.title,
            h1: document.querySelector('h1')?.textContent?.trim() || ''
          };
        }
        """
    )


def _audit_route(
    page: Page,
    base_url: str,
    route: str,
    viewport_name: str,
    *,
    required_text: list[str] | None = None,
    tab_key: str | None = None,
) -> dict[str, Any]:
    console_errors: list[str] = []
    page.on(
        "console",
        lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
    )
    response = page.goto(base_url + route, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(500)
    if tab_key:
        tab = page.locator(f'.tab-btn[data-tab="{tab_key}"]')
        if tab.count() != 1:
            raise RuntimeError(f"{route}缺少唯一Tab: {tab_key}")
        tab.click()
        page.wait_for_timeout(250)
        panel = page.locator(f"#tab-{tab_key}")
        if panel.count() != 1 or not panel.is_visible():
            raise RuntimeError(f"{route}未能激活Tab: {tab_key}")
    page.locator("details").evaluate_all(
        "(items) => items.forEach((item) => { item.open = true; })"
    )
    page.wait_for_timeout(150)
    geometry = _page_geometry(page)
    body_text = (
        page.locator(f"#tab-{tab_key}").inner_text()
        if tab_key
        else page.locator("body").inner_text()
    )
    missing_text = [text for text in (required_text or []) if text not in body_text]
    issues: list[str] = []
    if response is None or response.status != 200:
        issues.append(f"HTTP status={response.status if response else None}")
    if geometry["bodyOverflowPx"] > 3:
        issues.append(f"整页横向溢出 {geometry['bodyOverflowPx']}px")
    bad_tables = [
        item["index"]
        for item in geometry["tables"]
        if not item["visibleRightAfterScroll"] or not item["visibleLeftAfterScroll"]
    ]
    if bad_tables:
        issues.append(f"表格滚动到右端后最右列不可完整读取: {bad_tables}")
    bad_images = [
        item["index"]
        for item in geometry["images"]
        if not item["complete"] or item["naturalWidth"] <= 0
    ]
    if bad_images:
        issues.append(f"图片未加载: {bad_images}")
    if missing_text:
        issues.append(f"缺关键文本: {missing_text}")
    internal_identifiers = sorted(
        set(re.findall(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b", body_text))
    )
    if internal_identifiers:
        issues.append(f"公开正文暴露内部 snake_case 标识符: {internal_identifiers}")
    if console_errors:
        issues.append(f"console errors: {console_errors[:5]}")
    state = f"tab_{tab_key}" if tab_key else "page"
    safe = (
        route.strip("/").replace("/", "_").replace("?", "_").replace("=", "_")
        or "root"
    )
    safe = f"{safe}_{state}"
    table_screenshots: list[dict[str, Any]] = []
    tables = page.locator("table:visible")
    for index in range(tables.count()):
        table = tables.nth(index)
        target_state = table.evaluate(
            """
            (table, index) => {
              const ownsScroll = table.scrollWidth > table.clientWidth + 3;
              const semanticWrap = table.closest(
                '.cp-table-scroll,.table-scroll,.md-table-wrap,[role="region"]'
              );
              const target = ownsScroll ? table : (semanticWrap || table);
              const scrollLeftBefore = target.scrollLeft;
              target.scrollLeft = Math.max(0, target.scrollWidth - target.clientWidth);
              target.dataset.hdiAuditTarget = String(index);
              return {
                tableIndex: index,
                targetTag: target.tagName,
                targetClass: target.className,
                targetClientWidth: target.clientWidth,
                targetScrollWidth: target.scrollWidth,
                scrollLeftBefore,
                scrollLeftAfter: target.scrollLeft,
                targetIsTable: target === table
              };
            }
            """,
            index,
        )
        target = page.locator(f'[data-hdi-audit-target="{index}"]')
        if target.count() != 1:
            raise RuntimeError(
                f"{route}#{tab_key or 'page'} table[{index}]缺少唯一局部截图目标"
            )
        table_shot = OUTPUT_DIR / f"{viewport_name}_{safe}_table_{index}_right.png"
        target.first.screenshot(path=str(table_shot))
        table_text = table.evaluate(
            "element => (element.innerText || '').replace(/\\s+/g, ' ').trim()"
        )
        table_screenshots.append(
            {
                "table_index": index,
                "target": target_state,
                "screenshot": str(table_shot.relative_to(ROOT)).replace("\\", "/"),
                "screenshot_sha256": _sha256(table_shot),
                # 两张不同表的最右侧局部可能合法地完全相同，例如右侧都为
                # “来源/新鲜度”列。内容指纹用于区分这种情况与真的重复表或
                # 错误复用同一截图目标。
                "table_text_sha256": hashlib.sha256(
                    str(table_text).encode("utf-8")
                ).hexdigest(),
            }
        )
    table_hash_locations: dict[str, list[dict[str, Any]]] = {}
    for row in table_screenshots:
        table_hash_locations.setdefault(row["screenshot_sha256"], []).append(row)
    duplicate_table_screenshots = {
        digest: [int(row["table_index"]) for row in matched]
        for digest, matched in table_hash_locations.items()
        if (
            len(matched) > 1
            and len({row["table_text_sha256"] for row in matched}) == 1
        )
    }
    if duplicate_table_screenshots:
        issues.append(
            f"同一路由多张表复用相同局部截图: {duplicate_table_screenshots}"
        )
    if tab_key:
        page.locator(f"#tab-{tab_key}").evaluate(
            "element => element.scrollIntoView({block: 'start', inline: 'nearest'})"
        )
    else:
        page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(100)
    shot = OUTPUT_DIR / f"{viewport_name}_{safe}.png"
    page.screenshot(path=str(shot), full_page=False)
    return {
        "route": route,
        "tab_key": tab_key,
        "viewport": viewport_name,
        "http_status": response.status if response else None,
        "geometry": geometry,
        "required_text_missing": missing_text,
        "internal_snake_case_identifiers": internal_identifiers,
        "console_errors": console_errors,
        "screenshot": str(shot.relative_to(ROOT)).replace("\\", "/"),
        "screenshot_sha256": _sha256(shot),
        "right_edge_table_screenshots": table_screenshots,
        "duplicate_table_screenshot_hashes": duplicate_table_screenshots,
        "issues": issues,
    }


def _audit_source_drawers(
    page: Page,
    base_url: str,
    route_states: list[dict[str, Any]],
) -> dict[str, Any]:
    source_locations: dict[str, dict[str, Any]] = {}

    def activate(state: dict[str, Any]) -> None:
        route = str(state["route"])
        page.goto(base_url + route, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(250)
        tab_key = state.get("tab_key")
        if tab_key:
            tab = page.locator(f'.tab-btn[data-tab="{tab_key}"]')
            if tab.count() != 1:
                raise RuntimeError(f"{route}缺少来源审计Tab: {tab_key}")
            tab.click()
            page.wait_for_timeout(150)
        page.locator("details").evaluate_all(
            "(items) => items.forEach((item) => { item.open = true; })"
        )
        page.wait_for_timeout(100)

    for state in route_states:
        activate(state)
        refs = page.locator("sup.src-ref:visible")
        for index in range(refs.count()):
            source_id = refs.nth(index).get_attribute("data-source-id")
            if source_id:
                source_locations.setdefault(source_id, dict(state))
    if not source_locations:
        return {"status": "RED", "checked_count": 0, "issues": ["公开路由没有可点击来源引用"]}

    ordered = sorted(source_locations, key=lambda value: int(value))
    representative_indices = {0, len(ordered) // 2, len(ordered) - 1}
    checked: list[dict[str, Any]] = []
    issues: list[str] = []
    active_state = ""
    for index, source_id in enumerate(ordered):
        state = source_locations[source_id]
        route = str(state["route"])
        state_key = f"{route}#{state.get('tab_key') or 'page'}"
        if state_key != active_state:
            activate(state)
            active_state = state_key
        ref = page.locator(
            f'sup.src-ref[data-source-id="{source_id}"]:visible'
        ).first
        if ref.count() == 0:
            issues.append(
                f"source {source_id}: 原路由/Tab找不到可见来源按钮 {state_key}"
            )
            continue
        ref.scroll_into_view_if_needed()
        ref.focus()
        ref.press("Enter" if index % 2 == 0 else " ")
        page.locator("#trace-modal").wait_for(state="visible", timeout=10000)
        page.wait_for_function(
            "() => document.querySelector('#trace-modal-title').textContent !== '加载中…'",
            timeout=10000,
        )
        api_response = page.context.request.get(
            f"{base_url}/api/source/{source_id}",
            timeout=10000,
        )
        title = page.locator("#trace-modal-title").inner_text().strip()
        publisher = page.locator("#trace-publisher").inner_text().strip()
        publish_date = page.locator("#trace-date").inner_text().strip()
        tier = page.locator("#trace-tier").inner_text().strip()
        error_visible = page.locator("#trace-modal-error").is_visible()
        drawer_text = page.locator(".trace-modal").inner_text()
        geometry = page.locator(".trace-modal").evaluate(
            """
            el => ({
              clientWidth: el.clientWidth,
              scrollWidth: el.scrollWidth,
              right: el.getBoundingClientRect().right,
              viewportWidth: window.innerWidth
            })
            """
        )
        row_issues: list[str] = []
        if api_response.status != 200:
            row_issues.append(f"API status={api_response.status}")
        if not title or title.startswith("source #"):
            row_issues.append("来源标题不可读")
        if not publisher or publisher == "—":
            row_issues.append("发布方不可读")
        if not publish_date or publish_date == "—":
            row_issues.append("发布日期不可读")
        if not tier.startswith("tier "):
            row_issues.append("来源等级不可读")
        if error_visible:
            row_issues.append("来源抽屉显示错误")
        if geometry["scrollWidth"] > geometry["clientWidth"] + 3:
            row_issues.append("来源抽屉横向溢出")
        forbidden = [
            token
            for token in ("opp://", "source_ref:", "raw JSON", "cache/hdi_research")
            if token in drawer_text
        ]
        if forbidden:
            row_issues.append(f"抽屉暴露内部字段: {forbidden}")
        screenshot = None
        screenshot_sha256 = None
        if index in representative_indices:
            shot = OUTPUT_DIR / f"source_drawer_{source_id}.png"
            page.locator(".trace-modal").screenshot(path=str(shot))
            screenshot = str(shot.relative_to(ROOT)).replace("\\", "/")
            screenshot_sha256 = _sha256(shot)
        checked.append(
            {
                "source_id": source_id,
                "route": route,
                "tab_key": state.get("tab_key"),
                "activation_key": "Enter" if index % 2 == 0 else "Space",
                "api_status": api_response.status,
                "title": title,
                "publisher": publisher,
                "publish_date": publish_date,
                "tier": tier,
                "geometry": geometry,
                "screenshot": screenshot,
                "screenshot_sha256": screenshot_sha256,
                "issues": row_issues,
            }
        )
        issues.extend(f"source {source_id}: {item}" for item in row_issues)
        page.keyboard.press("Escape")
        page.locator("#trace-modal").wait_for(state="hidden", timeout=5000)

    return {
        "status": "GREEN" if not issues and len(checked) == len(ordered) else "RED",
        "unique_source_count": len(ordered),
        "checked_count": len(checked),
        "checked": checked,
        "issues": issues,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    route_states = [
        {"route": "/industry/24", "tab_key": "main", "required": ["HDI", "产业链"]},
        {"route": "/industry/24", "tab_key": "Q0", "required": ["HDI为何出现"]},
        {"route": "/industry/24", "tab_key": "Q1", "required": ["全球与中国市场有多集中"]},
        {"route": "/industry/24", "tab_key": "Q2", "required": ["全球HDI的基准市场有多大"]},
        {"route": "/industry/24", "tab_key": "Q3", "required": ["高阶HDI怎样制造"]},
        {"route": "/industry/24", "tab_key": "Q4", "required": ["HDI公司的收入怎样形成"]},
        {"route": "/industry/24", "tab_key": "Q5", "required": ["核心判断"]},
        {"route": "/industry/24", "tab_key": "Q6", "required": ["补充"]},
        {"route": "/industry/24", "tab_key": "data", "required": ["数据点(共"]},
        {
            "route": "/industry/24/companies",
            "required": ["华通电脑", "胜宏科技", "近期进展"],
        },
        {
            "route": "/industry/24/valuation",
            "required": ["胜宏科技", "鹏鼎控股"],
        },
        {
            "route": "/company/555?industry_id=24",
            "required": ["HDI", "综合估值判断与交易观察区", "2027年经营与估值三情景", "当前市场隐含预期"],
        },
        {
            "route": "/company/556?industry_id=24",
            "required": ["HDI", "综合估值判断与交易观察区", "2027年经营与估值三情景", "当前市场隐含预期"],
        },
        {
            "route": "/company/558?industry_id=24",
            "required": ["HDI", "综合估值判断与交易观察区", "2027年经营与估值三情景", "当前市场隐含预期"],
        },
        {
            "route": "/company/633?industry_id=24",
            "required": ["HDI", "综合估值判断与交易观察区", "2027年经营与估值三情景", "当前市场隐含预期"],
        },
        {"route": "/company/589?industry_id=24", "required": ["HDI", "全球份额"]},
        {"route": "/company/218?industry_id=24", "required": ["HDI", "AT&S"]},
        {"route": "/company/562?industry_id=24", "required": ["HDI", "Ultra-HDI"]},
    ]
    # The company-page audit covers the full HDI comparison universe.  Only the
    # six core leaders are expected to have complete forward models; the
    # remaining pages must still render current metrics, peer diagnostics and an
    # honest valuation-band availability explanation.
    route_states.extend(
        [
            {
                "route": "/company/326?industry_id=24",
                "required": ["HDI", "沪电股份", "综合估值判断与交易观察区", "PB Band"],
            },
            {
                "route": "/company/472?industry_id=24",
                "required": ["HDI", "深南电路", "综合估值判断与交易观察区", "PB Band"],
            },
            {
                "route": "/company/467?industry_id=24",
                "required": ["HDI", "欣兴电子", "同行诊断"],
            },
            {
                "route": "/company/561?industry_id=24",
                "required": ["HDI", "臻鼎科技", "同行诊断"],
            },
            {
                "route": "/company/563?industry_id=24",
                "required": ["HDI", "健鼎科技", "同行诊断"],
            },
            {
                "route": "/company/582?industry_id=24",
                "required": ["HDI", "方正科技", "PB Band", "同行诊断"],
            },
            {
                "route": "/company/583?industry_id=24",
                "required": ["HDI", "生益电子", "PB Band", "同行诊断"],
            },
            {
                "route": "/company/593?industry_id=24",
                "required": ["HDI", "名幸电子", "同行诊断"],
            },
        ]
    )
    results: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        browser = playwright.chromium.launch(
            headless=True, executable_path=str(chrome), args=["--disable-gpu"]
        )
        desktop = browser.new_context(
            viewport={"width": 1440, "height": 1000}, device_scale_factor=1
        )
        for state in route_states:
            page = desktop.new_page()
            results.append(
                _audit_route(
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
        source_drawer = _audit_source_drawers(
            source_page,
            args.base_url,
            route_states,
        )
        source_page.close()
        desktop.close()

        mobile = browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=1,
            is_mobile=True,
        )
        for state in route_states:
            page = mobile.new_page()
            results.append(
                _audit_route(
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
    screenshot_locations: dict[str, list[str]] = {}
    for row in results:
        screenshot_locations.setdefault(row["screenshot_sha256"], []).append(
            f"{row['viewport']}:{row['route']}#{row.get('tab_key') or 'page'}"
        )
    duplicate_screenshots = {
        digest: locations
        for digest, locations in screenshot_locations.items()
        if len(locations) > 1
    }
    if duplicate_screenshots:
        issues.append(
            f"不同路由/Tab产生相同页面截图哈希: {duplicate_screenshots}"
        )
    issues.extend(f"source drawer: {issue}" for issue in source_drawer["issues"])
    payload = {
        "schema_version": "hdi.browser_audit.v2",
        "base_url": args.base_url,
        "public_artifact_hashes": _bound_resource_hashes(PUBLIC_ARTIFACTS),
        "viewer_resource_hashes": _bound_resource_hashes(VIEWER_RESOURCES),
        "status": "GREEN" if not issues else "RED",
        "route_count": len(results),
        "routes": results,
        "source_drawer": source_drawer,
        "duplicate_route_screenshot_hashes": duplicate_screenshots,
        "issues": issues,
    }
    output = OUTPUT_DIR / "browser_audit.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "status": payload["status"], "issues": issues}, ensure_ascii=False, indent=2))
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
