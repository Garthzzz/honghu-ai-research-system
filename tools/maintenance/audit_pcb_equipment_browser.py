#!/usr/bin/env python
"""Read-only desktop/mobile browser audit for the PCB-equipment research pages."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "research.db"
DEFAULT_BUNDLE = ROOT / "cache" / "pcb_equipment_research" / "candidate_bundle_manifest.json"
DEFAULT_OUTPUT = ROOT / "cache" / "pcb_equipment_research" / "browser_audit"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _slug(route: str) -> str:
    value = route.strip("/") or "home"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value.replace("?", "_").replace("=", "-"))


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve().relative_to(ROOT)).replace("\\", "/"),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--port", type=int, default=5097)
    args = parser.parse_args()

    db_path = args.db.resolve()
    bundle_path = args.bundle.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if not CHROME.is_file():
        raise FileNotFoundError(CHROME)

    conn = sqlite3.connect(db_path)
    company_ids = [
        int(row[0]) for row in conn.execute(
            "SELECT company_id FROM company_industry WHERE industry_id=23 ORDER BY company_id"
        )
    ]
    conn.close()
    routes = [
        "/industry/23",
        "/industry/23/companies",
        "/industry/23/valuation",
        *[f"/company/{company_id}?industry_id=23" for company_id in company_ids],
    ]

    from tools.viewer import app as viewer

    viewer.DB_PATH = db_path
    server = make_server("127.0.0.1", args.port, viewer.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{args.port}"

    results: list[dict[str, Any]] = []
    table_results: list[dict[str, Any]] = []
    source_locations: dict[str, str] = {}
    source_results: list[dict[str, Any]] = []
    findings: list[str] = []
    screenshots: list[Path] = []
    viewports = {
        "desktop": {"width": 1440, "height": 1000},
        "mobile": {"width": 390, "height": 844},
    }

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, executable_path=str(CHROME))
            for viewport_name, viewport in viewports.items():
                context = browser.new_context(viewport=viewport, locale="zh-CN")
                page = context.new_page()
                for route in routes:
                    response = page.goto(base_url + route, wait_until="networkidle", timeout=45_000)
                    status = response.status if response else None
                    page.wait_for_timeout(150)
                    geometry = page.evaluate(
                        """() => ({
                          scrollWidth: document.documentElement.scrollWidth,
                          clientWidth: document.documentElement.clientWidth,
                          bodyScrollWidth: document.body.scrollWidth
                        })"""
                    )
                    overflow = max(geometry["scrollWidth"], geometry["bodyScrollWidth"]) > geometry["clientWidth"] + 1
                    route_result = {
                        "viewport": viewport_name,
                        "route": route,
                        "status": status,
                        "geometry": geometry,
                        "whole_page_horizontal_overflow": overflow,
                    }
                    results.append(route_result)
                    if status != 200:
                        findings.append(f"{viewport_name} {route}: HTTP {status}")
                    if overflow:
                        findings.append(f"{viewport_name} {route}: whole-page horizontal overflow")

                    shot = output_dir / f"{viewport_name}__{_slug(route)}.jpg"
                    page.screenshot(path=str(shot), full_page=True, type="jpeg", quality=68)
                    screenshots.append(shot)

                    refs = page.locator("[data-source-id]")
                    for index in range(refs.count()):
                        source_id = refs.nth(index).get_attribute("data-source-id")
                        if source_id and source_id not in source_locations:
                            source_locations[source_id] = route

                    tables = page.locator("table")
                    for index in range(tables.count()):
                        table = tables.nth(index)
                        # Industry sections live in tabs. Reveal the table's hidden ancestors exactly
                        # as the tab switcher would before measuring and capturing that section.
                        table.evaluate(
                            """node => {
                              let current = node;
                              while (current && current !== document.body) {
                                const style = getComputedStyle(current);
                                if (style.display === 'none') current.style.display = 'block';
                                if (style.visibility === 'hidden') current.style.visibility = 'visible';
                                current = current.parentElement;
                              }
                            }"""
                        )
                        region = table.locator(
                            "xpath=ancestor::*[contains(concat(' ',normalize-space(@class),' '),' cp-table-scroll ')][1]"
                        )
                        if region.count() == 0:
                            region = table
                        right_check = region.evaluate(
                            """node => {
                              node.scrollLeft = node.scrollWidth;
                              const table = node.querySelector('table');
                              const rows = table ? Array.from(table.rows) : [];
                              const cells = rows.map(row => row.cells[row.cells.length - 1]).filter(Boolean);
                              const nr = node.getBoundingClientRect();
                              const rights = cells.map(cell => cell.getBoundingClientRect().right);
                              const lefts = cells.map(cell => cell.getBoundingClientRect().left);
                              return {
                                clientWidth: node.clientWidth,
                                scrollWidth: node.scrollWidth,
                                scrollLeft: node.scrollLeft,
                                containerLeft: nr.left,
                                containerRight: nr.right,
                                lastCellMinLeft: lefts.length ? Math.min(...lefts) : null,
                                lastCellMaxRight: rights.length ? Math.max(...rights) : null,
                                rightmostVisible: rights.length ? Math.max(...rights) <= nr.right + 1 : true,
                                notClippedOnLeft: lefts.length ? Math.max(...lefts) >= nr.left - 1 : true
                              };
                            }"""
                        )
                        record = {
                            "viewport": viewport_name,
                            "route": route,
                            "table_index": index,
                            **right_check,
                        }
                        table_results.append(record)
                        if not right_check["rightmostVisible"]:
                            findings.append(f"{viewport_name} {route} table {index}: rightmost column clipped")
                        table_shot = output_dir / f"{viewport_name}__{_slug(route)}__table-{index}-right.jpg"
                        region.screenshot(path=str(table_shot), type="jpeg", quality=76)
                        screenshots.append(table_shot)
                context.close()

            # Every unique evidence reference is opened with the keyboard in a real browser.
            context = browser.new_context(viewport=viewports["desktop"], locale="zh-CN")
            page = context.new_page()
            for ordinal, (source_id, route) in enumerate(sorted(source_locations.items(), key=lambda item: int(item[0]))):
                print(f"source-drawer {source_id} {route}", flush=True)
                page.goto(base_url + route, wait_until="networkidle", timeout=45_000)
                ref = page.locator(f'[data-source-id="{source_id}"]').first
                if ref.count() == 0:
                    findings.append(f"source {source_id}: reference disappeared from {route}")
                    continue
                ref.evaluate(
                    """node => {
                      let current = node;
                      while (current && current !== document.body) {
                        const style = getComputedStyle(current);
                        if (style.display === 'none') current.style.display = 'block';
                        if (style.visibility === 'hidden') current.style.visibility = 'visible';
                        current = current.parentElement;
                      }
                      if (!node.hasAttribute('tabindex')) node.setAttribute('tabindex', '0');
                    }"""
                )
                try:
                    with page.expect_response(
                        lambda response, sid=source_id: f"/api/source/{sid}" in response.url,
                        timeout=8_000,
                    ) as response_info:
                        ref.focus()
                        ref.press("Enter")
                    api_response = response_info.value
                except Exception as exc:
                    findings.append(f"source {source_id}: keyboard open did not request API ({type(exc).__name__})")
                    continue
                page.locator("#trace-modal:not([hidden])").wait_for(state="visible", timeout=10_000)
                title = page.locator("#trace-modal-title").inner_text().strip()
                error_visible = page.locator("#trace-modal-error:not([hidden])").count() > 0
                modal_overflow = page.locator("#trace-modal .trace-modal").evaluate(
                    "node => node.scrollWidth > node.clientWidth + 1"
                )
                record = {
                    "source_id": int(source_id),
                    "route": route,
                    "api_status": api_response.status,
                    "title": title,
                    "drawer_visible": True,
                    "drawer_error_visible": error_visible,
                    "drawer_horizontal_overflow": modal_overflow,
                }
                source_results.append(record)
                if api_response.status != 200 or error_visible or modal_overflow:
                    findings.append(f"source {source_id}: drawer/API audit failed")
                if not title or title.startswith("source #") or title in {"加载中…", "—"}:
                    findings.append(f"source {source_id}: non-human-readable title")
                if ordinal < 8:
                    drawer_shot = output_dir / f"source-{source_id}-drawer.jpg"
                    page.locator("#trace-modal .trace-modal").screenshot(
                        path=str(drawer_shot), type="jpeg", quality=78
                    )
                    screenshots.append(drawer_shot)
                page.locator("[data-trace-close]").first.click()
            context.close()
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)

    code_artifacts = [
        ROOT / "tools" / "viewer" / "app.py",
        ROOT / "tools" / "viewer" / "templates" / "industry.html",
        ROOT / "tools" / "viewer" / "templates" / "industry_companies.html",
        ROOT / "tools" / "viewer" / "templates" / "industry_valuation.html",
        ROOT / "tools" / "viewer" / "templates" / "company_tag.html",
        ROOT / "tools" / "viewer" / "templates" / "base.html",
        ROOT / "tools" / "viewer" / "static" / "styles.css",
        ROOT / "tools" / "viewer" / "static" / "v4.css",
    ]
    payload = {
        "schema_version": "pcb_equipment.browser_audit.v1",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "candidate_database": _artifact(db_path),
        "candidate_bundle": _artifact(bundle_path),
        "viewer_artifacts": [_artifact(path) for path in code_artifacts],
        "viewports": viewports,
        "route_count": len(routes),
        "route_viewport_checks": results,
        "table_checks": table_results,
        "unique_source_reference_count": len(source_locations),
        "source_drawer_checks": source_results,
        "screenshots": [_artifact(path) for path in screenshots],
        "findings": findings,
        "verdict": "GREEN" if not findings else "RED",
    }
    output = output_dir / "browser_audit.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "sha256": _sha256(output),
        "verdict": payload["verdict"],
        "routes": len(routes),
        "route_viewport_checks": len(results),
        "tables": len(table_results),
        "unique_sources": len(source_locations),
        "findings": findings,
    }, ensure_ascii=False, indent=2))
    if findings:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
