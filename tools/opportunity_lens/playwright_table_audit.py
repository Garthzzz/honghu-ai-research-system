from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import Locator, Page, sync_playwright

from .artifact_freeze import build_artifact_freeze, sha256_bytes, sha256_text
from .browser_audit_contract import (
    BROWSER_AUDIT_SCHEMA_VERSION,
    BROWSER_AUDIT_SCRIPT_VERSION,
    EVIDENCE_DRAWER_RULE_VERSION,
    detect_raw_machine_date_fragments,
    expected_public_routes,
    record_browser_visual_audit,
    validate_browser_visual_audit,
)
from .constants import DB_PATH, ROOT
from .db import connect


DEFAULT_CHROME_PATHS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
)
VIEWPORTS = {
    "desktop": {"width": 1440, "height": 1000},
    "mobile": {"width": 390, "height": 844},
}
FORBIDDEN_DRAWER_PATTERNS = (
    re.compile(r"source_ref\s*:", re.IGNORECASE),
    re.compile(r"opp://", re.IGNORECASE),
    re.compile(r"file://", re.IGNORECASE),
    re.compile(r"[A-Za-z]:\\(?:quant|industry_demo)\\", re.IGNORECASE),
)
RAW_SOURCE_LEVEL_PATTERN = re.compile(
    r"\b(?:tier[_ -]?[0-9]+|primary_official|secondary_reputable|weak_gray|source_level_[a-z0-9_]+)\b",
    re.IGNORECASE,
)


def _chrome_path(explicit: Path | None) -> Path:
    if explicit is not None:
        path = explicit.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"浏览器不存在：{path}")
        return path
    for path in DEFAULT_CHROME_PATHS:
        if path.is_file():
            return path
    raise FileNotFoundError("未找到本机 Chrome/Edge；请用 --browser-executable 显式指定")


def _relative_screenshot(path: Path, project_root: Path) -> dict[str, str]:
    return {
        "ref": path.resolve().relative_to(project_root.resolve()).as_posix(),
        "hash": sha256_bytes(path.read_bytes()),
    }


def _visible(locator: Locator) -> bool:
    try:
        return locator.is_visible()
    except Exception:
        return False


def _global_overflow(page: Page) -> float:
    return float(
        page.evaluate(
            """
            () => {
              const root = document.documentElement;
              const body = document.body;
              return Math.max(0, Math.max(root.scrollWidth, body ? body.scrollWidth : 0) - root.clientWidth);
            }
            """
        )
    )


def _edge(table: Locator, *, right: bool) -> dict[str, Any]:
    return table.evaluate(
        """
        (table, right) => {
          const wrapper = table.closest('.opp-wide-scroll');
          if (!wrapper) return null;
          wrapper.scrollLeft = Number.MAX_SAFE_INTEGER;
          const maxScroll = wrapper.scrollLeft;
          wrapper.scrollLeft = right ? maxScroll : 0;
          const rect = wrapper.getBoundingClientRect();
          return {
            scroll_left: wrapper.scrollLeft,
            max_scroll_left: maxScroll,
            reached: right ? Math.abs(wrapper.scrollLeft - maxScroll) <= 3 : Math.abs(wrapper.scrollLeft) <= 1.5,
            container_geometry: {
              left: rect.left,
              right: rect.right,
              top: rect.top,
              bottom: rect.bottom,
              width: rect.width,
              height: rect.height
            }
          };
        }
        """,
        right,
    )


def _rightmost_geometry(table: Locator) -> dict[str, Any]:
    return table.evaluate(
        """
        (table) => {
          const wrapper = table.closest('.opp-wide-scroll');
          if (!wrapper) return null;
          const wrapperRect = wrapper.getBoundingClientRect();
          const containerLeft = wrapperRect.left;
          const containerRight = wrapperRect.right;
          const geometry = (element) => {
            const rect = element.getBoundingClientRect();
            const visible = rect.left >= containerLeft - 1.5 && rect.right <= containerRight + 1.5;
            return {
              left: rect.left,
              right: rect.right,
              top: rect.top,
              bottom: rect.bottom,
              width: rect.width,
              height: rect.height,
              container_left: containerLeft,
              container_right: containerRight,
              fully_visible: visible,
              clipped: !visible
            };
          };
          const header = table.querySelector('thead tr:last-child th:last-child')
            || table.querySelector('tr:first-child > *:last-child');
          const rows = Array.from(table.querySelectorAll('tbody tr'))
            .filter((row) => row.lastElementChild);
          return {
            header_text: header ? String(header.textContent || '').trim() : '',
            header_geometry: header ? geometry(header) : null,
            cell_geometries: rows.map((row) => geometry(row.lastElementChild))
          };
        }
        """
    )


def _audit_table(
    page: Page,
    table: Locator,
    *,
    index: int,
    screenshot_path: Path,
    project_root: Path,
) -> dict[str, Any]:
    issues: list[str] = []
    wrapper = table.locator(
        "xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' opp-wide-scroll ')][1]"
    )
    if wrapper.count() != 1:
        issues.append("表格缺少唯一的局部横向滚动容器")
    table.scroll_into_view_if_needed(timeout=30_000)
    page.wait_for_timeout(40)
    left = _edge(table, right=False)
    if left is None:
        issues.append("无法读取表格左边界")
        left = {}
    keyboard_reachable = False
    if wrapper.count() == 1:
        try:
            wrapper.focus()
            keyboard_reachable = bool(
                wrapper.evaluate("element => document.activeElement === element && element.tabIndex >= 0")
            )
        except Exception as exc:
            issues.append(f"滚动容器键盘聚焦失败：{exc}")
    if not keyboard_reachable:
        issues.append("表格滚动容器不能通过键盘聚焦")
    right = _edge(table, right=True)
    page.wait_for_timeout(50)
    rightmost = _rightmost_geometry(table)
    if right is None:
        issues.append("无法读取表格右边界")
        right = {}
    if rightmost is None:
        issues.append("无法读取最右列几何")
        rightmost = {"header_text": "", "header_geometry": None, "cell_geometries": []}
    if not rightmost.get("header_text"):
        issues.append("最右列标题为空")
    geometries = [rightmost.get("header_geometry"), *rightmost.get("cell_geometries", [])]
    if any(not isinstance(item, dict) or not item.get("fully_visible") for item in geometries):
        issues.append("滚动到最右端后仍有最右列单元格被裁切")
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    if wrapper.count() == 1:
        wrapper.screenshot(path=str(screenshot_path), animations="disabled", timeout=60_000)
    else:
        table.screenshot(path=str(screenshot_path), animations="disabled", timeout=60_000)
    screenshot = _relative_screenshot(screenshot_path, project_root)
    row_count = int(table.locator("tbody tr").count())
    column_count = int(
        table.evaluate(
            "table => (table.querySelectorAll('thead th').length || (table.rows[0] ? table.rows[0].cells.length : 0))"
        )
    )
    return {
        "index": index,
        "row_count": row_count,
        "column_count": column_count,
        "keyboard_reachable": keyboard_reachable,
        "left_edge": left,
        "right_edge": right,
        "rightmost_column": rightmost,
        "right_edge_screenshot_ref": screenshot["ref"],
        "right_edge_screenshot_hash": screenshot["hash"],
        "issues": issues,
    }


def _date_fields(drawer: Locator) -> list[dict[str, str]]:
    return drawer.evaluate(
        """
        drawer => Array.from(drawer.querySelectorAll('dt')).map((dt) => ({
          label: String(dt.textContent || '').trim(),
          value: dt.nextElementSibling ? String(dt.nextElementSibling.textContent || '').trim() : ''
        }))
        """
    )


def _raw_machine_date_issues(raw_dates: list[str]) -> list[str]:
    """Turn detected machine-formatted drawer dates into blocking audit issues."""
    fragments = [str(value).strip() for value in raw_dates if str(value).strip()]
    if not fragments:
        return []
    return [
        "证据抽屉日期字段仍含机器格式："
        + "、".join(dict.fromkeys(fragments))
    ]


def _factor_label_issues(metrics: list[dict[str, Any]]) -> list[str]:
    """Return blocking issues when a factor-card label is clipped or squeezed by its badge."""
    issues: list[str] = []
    for item in metrics:
        label = str(item.get("text") or "").strip() or "未命名因子"
        if item.get("clipped"):
            issues.append(f"因子标签“{label}”被裁切")
        if item.get("squeezed"):
            issues.append(f"因子标签“{label}”可用宽度过窄")
        if item.get("score_overlap"):
            issues.append(f"因子标签“{label}”与分数徽标重叠")
    return issues


def _audit_factor_labels(page: Page) -> dict[str, Any]:
    metrics: list[dict[str, Any]] = page.locator(".opp-heat-label:visible").evaluate_all(
        """
        labels => labels.map((label) => {
          const labelRect = label.getBoundingClientRect();
          const card = label.closest('a');
          const cardRect = card ? card.getBoundingClientRect() : labelRect;
          const score = card ? card.querySelector('b') : null;
          const scoreRect = score ? score.getBoundingClientRect() : null;
          const verticalOverlap = scoreRect
            ? Math.min(labelRect.bottom, scoreRect.bottom) - Math.max(labelRect.top, scoreRect.top) > 1
            : false;
          return {
            text: String(label.textContent || '').trim(),
            label_width: labelRect.width,
            card_width: cardRect.width,
            clipped: label.scrollWidth > label.clientWidth + 1 || label.scrollHeight > label.clientHeight + 1,
            squeezed: labelRect.width < Math.min(120, cardRect.width * 0.70),
            score_overlap: Boolean(scoreRect && verticalOverlap && labelRect.right > scoreRect.left - 2)
          };
        })
        """
    )
    return {
        "label_count": len(metrics),
        "metrics": metrics,
        "issues": _factor_label_issues(metrics),
    }


def _raw_math_markers(text: str) -> list[str]:
    """Return the raw LaTeX tokens that must never remain visible to readers."""

    return [
        marker
        for marker in ("$$", "\\operatorname", "\\frac", "\\mathcal", "\\qquad")
        if marker in text
    ]


def _audit_math_rendering(page: Page) -> dict[str, Any]:
    """Fail when public research exposes raw LaTeX instead of rendered maths.

    A route can legitimately contain no formula.  When it does contain one,
    KaTeX removes the delimiters and creates ``.katex-display`` nodes.  Checking
    the rendered body text catches the exact failure users see, rather than
    merely confirming that the source Markdown placed ``$$`` on separate lines.
    """

    body_text = page.locator("body").inner_text()
    raw_markers = _raw_math_markers(body_text)
    display_count = page.locator(".katex-display:visible").count()
    total_katex_count = page.locator(".katex:visible").count()
    inline_count = page.locator(".katex:not(.katex-display .katex):visible").count()
    issues = []
    if raw_markers:
        issues.append("数学公式未渲染，页面仍显示：" + "、".join(raw_markers))
    return {
        "display_formula_count": display_count,
        # Keep the historical field name, but make it report what the label says:
        # every visible KaTeX root, including those nested in display formulae.
        "visible_katex_node_count": total_katex_count,
        "inline_formula_count": inline_count,
        "raw_latex_markers": raw_markers,
        "issues": issues,
    }


def _audit_evidence_drawer(
    page: Page,
    *,
    route_slug: str,
    screenshot_path: Path,
    project_root: Path,
) -> dict[str, Any]:
    buttons = page.locator("[data-opp-evidence]")
    button_count = buttons.count()
    refs: list[str] = buttons.evaluate_all(
        "elements => [...new Set(elements.map((item) => item.getAttribute('data-opp-evidence')).filter(Boolean))]"
    )
    items: list[dict[str, Any]] = []
    drawer_screenshot: dict[str, str] | None = None
    overall_issues: list[str] = []
    for index, reference in enumerate(refs):
        activation_key = "Enter" if index % 2 == 0 else "Space"
        item_issues: list[str] = []
        # URI characters make a generated CSS selector unnecessarily fragile. Resolve the
        # first matching button index inside the DOM and keep raw references out of the audit.
        locator = page.locator("[data-opp-evidence]").nth(
            int(
                page.locator("[data-opp-evidence]").evaluate_all(
                    "(elements, ref) => elements.findIndex((item) => item.getAttribute('data-opp-evidence') === ref)",
                    reference,
                )
            )
        )
        locator.scroll_into_view_if_needed(timeout=30_000)
        locator.focus()
        button_focused = bool(locator.evaluate("element => document.activeElement === element"))
        api_status = 0
        try:
            with page.expect_response(
                lambda response: "/api/opportunity-lens/evidence/resolve" in response.url,
                timeout=30_000,
            ) as response_info:
                locator.press(activation_key)
            api_status = int(response_info.value.status)
        except Exception as exc:
            item_issues.append(f"键盘触发证据 API 失败：{exc}")
        drawer = page.locator("[data-opp-drawer]")
        try:
            page.wait_for_selector("[data-opp-drawer]:not([hidden]) [data-opp-drawer-body] h3", timeout=30_000)
        except Exception as exc:
            item_issues.append(f"证据抽屉未完成渲染：{exc}")
        drawer_visible = _visible(drawer) and not bool(drawer.get_attribute("hidden"))
        drawer_text = drawer.inner_text() if drawer_visible else ""
        headline_locator = drawer.locator("h3").first
        headline = headline_locator.inner_text().strip() if _visible(headline_locator) else ""
        drawer_overflow = float(
            drawer.evaluate("element => Math.max(0, element.scrollWidth - element.clientWidth)")
        ) if drawer_visible else -1.0
        forbidden = [pattern.pattern for pattern in FORBIDDEN_DRAWER_PATTERNS if pattern.search(drawer_text)]
        raw_dates = detect_raw_machine_date_fragments(
            _date_fields(drawer) if drawer_visible else [], drawer_text
        )
        raw_levels = list(dict.fromkeys(RAW_SOURCE_LEVEL_PATTERN.findall(drawer_text)))
        raw_json_visible = bool(
            drawer.locator("pre:visible").evaluate_all(
                "nodes => nodes.some((node) => /^[\\s]*[\\[{]/.test(String(node.textContent || '')))"
            )
        ) if drawer_visible else False
        human_checked = bool(headline and len(drawer_text.strip()) >= 20)
        if not button_focused:
            item_issues.append("证据按钮未取得键盘焦点")
        if api_status != 200:
            item_issues.append(f"证据 API 状态不是 200：{api_status}")
        if not drawer_visible:
            item_issues.append("证据抽屉不可见")
        if drawer_overflow > 3:
            item_issues.append(f"证据抽屉横向溢出 {drawer_overflow:.1f}px")
        if not headline:
            item_issues.append("证据抽屉标题为空")
        if not human_checked:
            item_issues.append("证据抽屉没有足够的人类可读内容")
        item_issues.extend(_raw_machine_date_issues(raw_dates))
        if drawer_screenshot is None and drawer_visible:
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            drawer.screenshot(path=str(screenshot_path), animations="disabled", timeout=60_000)
            drawer_screenshot = _relative_screenshot(screenshot_path, project_root)
        items.append(
            {
                "reference_hash": sha256_text(reference),
                "activation_key": activation_key,
                "button_focused": button_focused,
                "api_status": api_status,
                "drawer_visible": drawer_visible,
                "drawer_horizontal_overflow_px": drawer_overflow,
                "headline": headline,
                "drawer_text_hash": sha256_text(drawer_text),
                "forbidden_fragments": forbidden,
                "raw_machine_date_fragments": raw_dates,
                "raw_source_level_code_fragments": raw_levels,
                "raw_json_visible": raw_json_visible,
                "human_content_checked": human_checked,
                "issues": item_issues,
            }
        )
        if item_issues:
            overall_issues.append(f"{route_slug} 证据引用 #{index + 1}：{'；'.join(item_issues)}")
        close = drawer.locator("[data-opp-close]")
        if _visible(close):
            close.click()
    payload: dict[str, Any] = {
        "content_rule_version": EVIDENCE_DRAWER_RULE_VERSION,
        "button_count": button_count,
        "unique_reference_count": len(refs),
        "tested_reference_count": len(items),
        "items": items,
        "issues": overall_issues,
    }
    if drawer_screenshot is not None:
        payload["drawer_screenshot_ref"] = drawer_screenshot["ref"]
        payload["drawer_screenshot_hash"] = drawer_screenshot["hash"]
    return payload


def _audit_route(
    page: Page,
    *,
    base_url: str,
    route: str,
    route_index: int,
    viewport_name: str,
    output_dir: Path,
    project_root: Path,
) -> dict[str, Any]:
    issues: list[str] = []
    response = page.goto(base_url.rstrip("/") + route, wait_until="networkidle", timeout=120_000)
    page.evaluate("document.fonts && document.fonts.ready")
    page.wait_for_timeout(120)
    status = int(response.status) if response is not None else 0
    if status != 200:
        issues.append(f"HTTP 状态为 {status}")
    overflow = _global_overflow(page)
    if overflow > 3:
        issues.append(f"全页横向溢出 {overflow:.1f}px")
    route_dir = output_dir / viewport_name / f"route_{route_index:02d}"
    route_dir.mkdir(parents=True, exist_ok=True)
    full_path = route_dir / "full_page.png"
    page.screenshot(path=str(full_path), full_page=True, animations="disabled", timeout=120_000)
    full = _relative_screenshot(full_path, project_root)
    factor_labels = _audit_factor_labels(page)
    issues.extend(factor_labels["issues"])
    math_rendering = _audit_math_rendering(page)
    issues.extend(math_rendering["issues"])
    tables: list[dict[str, Any]] = []
    visible_tables = page.locator("table:visible")
    for table_index in range(visible_tables.count()):
        try:
            table_result = _audit_table(
                page,
                visible_tables.nth(table_index),
                index=table_index,
                screenshot_path=route_dir / f"table_{table_index:02d}_right.png",
                project_root=project_root,
            )
        except Exception as exc:
            table_result = {
                "index": table_index,
                "row_count": 0,
                "column_count": 0,
                "keyboard_reachable": False,
                "left_edge": {},
                "right_edge": {},
                "rightmost_column": {"header_text": "", "header_geometry": None, "cell_geometries": []},
                "right_edge_screenshot_ref": "",
                "right_edge_screenshot_hash": sha256_text(""),
                "issues": [f"表格审计异常：{exc}"],
            }
        tables.append(table_result)
        issues.extend(f"表格 {table_index + 1}：{item}" for item in table_result["issues"])
    drawer_result = _audit_evidence_drawer(
        page,
        route_slug=f"route_{route_index:02d}",
        screenshot_path=route_dir / "evidence_drawer.png",
        project_root=project_root,
    )
    issues.extend(drawer_result["issues"])
    return {
        "route": route,
        "status": status,
        "table_count": len(tables),
        "global_overflow_px": overflow,
        "factor_labels": factor_labels,
        "math_rendering": math_rendering,
        "tables": tables,
        "evidence_drawer": drawer_result,
        "screenshot_ref": full["ref"],
        "screenshot_hash": full["hash"],
        "screenshot_full_page": True,
        "issues": issues,
    }


def _simple_route_check(page: Page, *, base_url: str, route: str) -> dict[str, Any]:
    response = page.goto(base_url.rstrip("/") + route, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(80)
    h1 = page.locator("h1").first
    return {
        "route": route,
        "status": int(response.status) if response is not None else 0,
        "final_path": page.evaluate("location.pathname"),
        "redirected": page.evaluate("location.pathname") != route,
        "title": h1.inner_text().strip() if _visible(h1) else "",
        "global_overflow_px": _global_overflow(page),
        "table_count": page.locator("table:visible").count(),
    }


def run_audit(
    *,
    run_id: int,
    db_path: Path,
    project_root: Path,
    base_url: str,
    browser_executable: Path,
    output_root: Path,
) -> tuple[dict[str, Any], Path]:
    conn = connect(db_path, readonly=True)
    try:
        freeze = build_artifact_freeze(conn, run_id, project_root=project_root)
        routes = expected_public_routes(conn, run_id)
    finally:
        conn.close()
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    output_dir = (output_root / f"run_{run_id}_{stamp}").resolve()
    output_dir.relative_to(project_root.resolve())
    output_dir.mkdir(parents=True, exist_ok=False)
    viewports: dict[str, Any] = {}
    supplemental: dict[str, Any] = {"run1_8_regression": {}}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(browser_executable))
        try:
            for viewport_name, dimensions in VIEWPORTS.items():
                page = browser.new_page(viewport=dimensions, device_scale_factor=1)
                page.set_default_timeout(30_000)
                route_results: list[dict[str, Any]] = []
                for route_index, route in enumerate(routes):
                    route_results.append(
                        _audit_route(
                            page,
                            base_url=base_url,
                            route=route,
                            route_index=route_index,
                            viewport_name=viewport_name,
                            output_dir=output_dir,
                            project_root=project_root,
                        )
                    )
                viewport_issues = [
                    f"{item['route']}：{issue}"
                    for item in route_results
                    for issue in item["issues"]
                ]
                viewports[viewport_name] = {
                    "viewport": dimensions,
                    "route_count": len(route_results),
                    "routes": route_results,
                    "issues": viewport_issues,
                }
                supplemental["run1_8_regression"][viewport_name] = [
                    _simple_route_check(
                        page, base_url=base_url, route=f"/opportunity-lens/run/{legacy_run_id}"
                    )
                    for legacy_run_id in range(1, 9)
                ]
                page.close()
        finally:
            browser.close()
    top_issues = [
        f"{viewport_name}：{issue}"
        for viewport_name, payload in viewports.items()
        for issue in payload["issues"]
    ]
    for group_name, viewport_map in supplemental.items():
        for viewport_name, checks in viewport_map.items():
            for check in checks:
                if check["status"] != 200 or check["redirected"] or not check["title"]:
                    top_issues.append(
                        f"supplemental {group_name}/{viewport_name}/{check['route']} 未通过"
                    )
    manifest = {
        "schema_version": BROWSER_AUDIT_SCHEMA_VERSION,
        "script_version": BROWSER_AUDIT_SCRIPT_VERSION,
        "run_id": run_id,
        "pack_hash": freeze.pack_hash,
        "ui_bundle_hash": freeze.ui_bundle_hash,
        "browser_input_hash": freeze.browser_input_hash,
        "ui_file_count": freeze.ui_file_count,
        "routes": routes,
        "viewports": viewports,
        "supplemental_checks": supplemental,
        "browser_executable": browser_executable.name,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "issues": top_issues,
        "verdict": "GREEN" if not top_issues else "RED",
    }
    manifest_path = output_dir / "browser_visual_audit.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest, manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description="执行 Opportunity Lens Playwright 表格与证据抽屉审计")
    parser.add_argument("run_id", type=int)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--browser-executable", type=Path)
    parser.add_argument(
        "--output-root", type=Path, default=ROOT / "cache" / "opportunity_lens" / "browser_audit"
    )
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    manifest, manifest_path = run_audit(
        run_id=args.run_id,
        db_path=args.db.resolve(),
        project_root=project_root,
        base_url=args.base_url,
        browser_executable=_chrome_path(args.browser_executable),
        output_root=args.output_root.resolve(),
    )
    conn = connect(args.db, readonly=not args.record)
    try:
        freeze = build_artifact_freeze(conn, args.run_id, project_root=project_root)
        validation = validate_browser_visual_audit(
            manifest,
            expected_freeze=freeze,
            project_root=project_root,
            verify_screenshots=True,
            expected_routes=expected_public_routes(conn, args.run_id),
        )
        recorded_hash = None
        if args.record and validation.valid:
            recorded_hash = record_browser_visual_audit(
                conn,
                args.run_id,
                manifest,
                project_root=project_root,
                verify_screenshots=True,
            )
            conn.commit()
    except Exception:
        if args.record:
            conn.rollback()
        raise
    finally:
        conn.close()
    print(
        json.dumps(
            {
                "valid": validation.valid,
                "manifest_path": str(manifest_path),
                "manifest_hash": validation.manifest_hash,
                "browser_input_hash": freeze.browser_input_hash,
                "issues": validation.issues,
                "recorded": bool(recorded_hash),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not validation.valid:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
