from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
DEFAULT_OUTPUT = ROOT / "cache" / "workflow_refactor_20260712" / "viewer" / "browser_audit.json"

ROUTES = (
    ("research", "/research", False),
    ("companies", "/companies", False),
    ("company_1", "/company/1", False),
    ("industry_22", "/industry/22", False),
    ("industry_22_companies", "/industry/22/companies", False),
    ("industry_22_valuation", "/industry/22/valuation", False),
    ("opportunity_home", "/opportunity-lens", True),
    ("request_generator", "/opportunity-lens/request-generator", True),
    ("run8", "/opportunity-lens/run/8", True),
    ("run8_theory", "/opportunity-lens/entity/69", True),
    ("run8_market", "/opportunity-lens/entity/72", True),
    ("run8_target", "/opportunity-lens/target/1206", True),
    ("run8_factor", "/opportunity-lens/factor/2045", True),
    ("run8_metric_slot", "/opportunity-lens/metric-slot/2036", True),
    ("run8_export", "/opportunity-lens/run/8/export", True),
    ("run8_audit", "/opportunity-lens/run/8/audit", True),
    ("run8_supplement", "/opportunity-lens/run/8/supplement", True),
)

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 1000},
    "mobile": {"width": 390, "height": 844},
}

MACHINE_MARKERS = (
    "opp://source/",
    "source_ref:",
    "原文地址：",
    "本地底稿：",
    "原始 JSON",
    "机器可读的可视化数据",
)
MACHINE_ENUMS = (
    "c_hybrid",
    "c_open_with_seed",
    "published",
    "C_INTAKE_CONTRACT_V1",
    "pass_with_note",
    "weak_source_only",
    "core_eligible",
    "early_signal_only",
    "excluded_from_scoring",
    "source_id",
)
PUBLIC_MACHINE_LABELS = (
    "a_share",
    "other_listed",
    "private_subsidiary",
    "parent_subsidiary",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _screenshot_nonblank(path: Path) -> dict[str, Any]:
    with Image.open(path).convert("RGB") as image:
        stat = ImageStat.Stat(image)
        extrema = image.getextrema()
        dynamic_range = max(high - low for low, high in extrema)
        mean = tuple(round(value, 2) for value in stat.mean)
        return {"width": image.width, "height": image.height, "dynamic_range": dynamic_range, "mean_rgb": mean, "nonblank": dynamic_range >= 12}


def _dom_audit(page, *, opportunity: bool) -> dict[str, Any]:
    return page.evaluate(
        r"""({opportunity, markers, machineEnums, publicMachineLabels}) => {
          const bodyText = document.body ? document.body.innerText : '';
          const overflow = Math.max(0, document.documentElement.scrollWidth - window.innerWidth);
          const visible = el => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
          };
          const leaking = Array.from(document.querySelectorAll('td,th,button,a,.opp-tag,.opp-priority-tag'))
            .filter(visible)
            .filter(el => {
              const s = getComputedStyle(el);
              return el.scrollWidth > el.clientWidth + 3 && s.overflowX === 'visible' && s.whiteSpace === 'nowrap';
            })
            .slice(0, 20)
            .map(el => ({tag: el.tagName, text: (el.innerText || '').slice(0, 80), client: el.clientWidth, scroll: el.scrollWidth}));
          const mirrorResults = [];
          if (opportunity) {
            document.querySelectorAll('.opp-scroll-mirror:not([hidden])').forEach(mirror => {
              const wrapper = mirror.nextElementSibling;
              if (!wrapper || !wrapper.classList.contains('opp-wide-scroll')) return;
              const max = Math.max(0, mirror.scrollWidth - mirror.clientWidth);
              const target = Math.min(37, max);
              mirror.scrollLeft = target;
              mirror.dispatchEvent(new Event('scroll'));
              mirrorResults.push({target, wrapper: wrapper.scrollLeft, synced: Math.abs(wrapper.scrollLeft - target) <= 1});
            });
          }
          return {
            title: document.title,
            body_length: bodyText.length,
            page_overflow_px: overflow,
            machine_markers: opportunity ? markers.filter(marker => bodyText.includes(marker)) : [],
            machine_enums: opportunity ? machineEnums.filter(value => bodyText.includes(value)) : [],
            public_machine_labels: publicMachineLabels.filter(value => bodyText.includes(value)),
            katex_count: opportunity ? document.querySelectorAll('.opp-page .katex,.opp-drawer .katex').length : 0,
            visible_mirror_count: opportunity ? document.querySelectorAll('.opp-scroll-mirror:not([hidden])').length : 0,
            mirror_results: mirrorResults,
            leaking_nowrap_elements: leaking,
            broken_dollar_pattern: /\$\s*\n\s*[0-9A-Za-z]/.test(bodyText),
            raw_json_pre_count: opportunity ? Array.from(document.querySelectorAll('.opp-page pre'))
              .filter(el => /^[\[{]/.test((el.textContent || '').trim())).length : 0,
          };
        }""",
        {
            "opportunity": opportunity,
            "markers": list(MACHINE_MARKERS),
            "machineEnums": list(MACHINE_ENUMS),
            "publicMachineLabels": list(PUBLIC_MACHINE_LABELS),
        },
    )


def audit(
    base_url: str,
    output: Path,
    chrome: Path,
    *,
    allowed_db_drift: set[str] | None = None,
) -> dict[str, Any]:
    allowed_db_drift = allowed_db_drift or set()
    screenshot_dir = output.parent / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    db_paths = [
        ROOT / "data" / name
        for name in ("research.db", "sentiment.db", "opportunity_lens.db", "financial.db")
    ]
    before_hashes = {path.name: _sha256(path) for path in db_paths}
    pages: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    screenshot_names = {
        "research", "companies", "company_1", "opportunity_home", "request_generator", "run8", "run8_theory",
        "run8_market", "run8_target", "run8_factor", "run8_metric_slot", "run8_audit",
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=str(chrome))
        try:
            for viewport_name, viewport in VIEWPORTS.items():
                context = browser.new_context(viewport=viewport, locale="zh-CN")
                try:
                    for name, route, opportunity in ROUTES:
                        page = context.new_page()
                        console_errors: list[str] = []
                        page_errors: list[str] = []
                        bad_responses: list[dict[str, Any]] = []
                        page.on("console", lambda msg, target=console_errors: target.append(msg.text) if msg.type == "error" else None)
                        page.on("pageerror", lambda exc, target=page_errors: target.append(str(exc)))
                        page.on(
                            "response",
                            lambda response, target=bad_responses: target.append({"status": response.status, "url": response.url})
                            if response.status >= 400 and response.url.startswith(base_url)
                            else None,
                        )
                        response = page.goto(base_url + route, wait_until="domcontentloaded", timeout=30000)
                        page.wait_for_timeout(350)
                        status = response.status if response else None
                        dom = _dom_audit(page, opportunity=opportunity)
                        drawer = None
                        if name == "run8_market" and viewport_name == "desktop":
                            button = page.locator("[data-opp-evidence]").first
                            if button.count():
                                button.click()
                                page.wait_for_timeout(250)
                                drawer = page.locator("[data-opp-drawer]").evaluate(
                                    """(el, args) => {
                                      const text = (el.innerText || '').slice(0, 2400);
                                      return {
                                        hidden: el.hidden,
                                        text,
                                        links: el.querySelectorAll('a').length,
                                        machine_markers: args.markers.filter(value => text.includes(value)),
                                        machine_enums: args.enums.filter(value => text.includes(value)),
                                      };
                                    }""",
                                    {"markers": list(MACHINE_MARKERS), "enums": list(MACHINE_ENUMS)},
                                )
                        screenshot_meta = None
                        if name in screenshot_names:
                            screenshot_path = screenshot_dir / f"{viewport_name}_{name}.png"
                            page.screenshot(path=str(screenshot_path), full_page=False)
                            screenshot_meta = {"path": str(screenshot_path), **_screenshot_nonblank(screenshot_path)}
                        record = {
                            "viewport": viewport_name,
                            "name": name,
                            "route": route,
                            "status": status,
                            "dom": dom,
                            "drawer": drawer,
                            "console_errors": console_errors,
                            "page_errors": page_errors,
                            "bad_responses": bad_responses,
                            "screenshot": screenshot_meta,
                        }
                        pages.append(record)
                        reasons = []
                        if status != 200:
                            reasons.append(f"HTTP {status}")
                        if dom["body_length"] < 80:
                            reasons.append("正文过短")
                        if dom["page_overflow_px"] > 3:
                            reasons.append(f"整页横向溢出 {dom['page_overflow_px']}px")
                        if dom["machine_markers"]:
                            reasons.append(f"可见机器字段 {dom['machine_markers']}")
                        if dom["machine_enums"]:
                            reasons.append(f"可见机器枚举 {dom['machine_enums']}")
                        if dom["public_machine_labels"]:
                            reasons.append(f"可见证券机器标签 {dom['public_machine_labels']}")
                        if dom["katex_count"]:
                            reasons.append(f"KaTeX={dom['katex_count']}")
                        if any(not item["synced"] for item in dom["mirror_results"]):
                            reasons.append("顶部横向滚动条不同步")
                        if dom["leaking_nowrap_elements"]:
                            reasons.append("nowrap 文本越界")
                        if dom["broken_dollar_pattern"]:
                            reasons.append("美元文本疑似断裂")
                        if dom["raw_json_pre_count"]:
                            reasons.append(f"页面直接展示 raw JSON pre={dom['raw_json_pre_count']}")
                        if console_errors or page_errors or bad_responses:
                            reasons.append("浏览器错误或失败资源")
                        if screenshot_meta and not screenshot_meta["nonblank"]:
                            reasons.append("截图疑似空白")
                        if drawer is not None and (drawer["hidden"] or drawer["links"] < 1 or len(drawer["text"]) < 60):
                            reasons.append("证据抽屉不完整")
                        if drawer is not None and (drawer["machine_markers"] or drawer["machine_enums"]):
                            reasons.append(
                                f"证据抽屉可见机器字段 {drawer['machine_markers'] + drawer['machine_enums']}"
                            )
                        if reasons:
                            failures.append({"viewport": viewport_name, "route": route, "reasons": reasons})
                        page.close()
                finally:
                    context.close()
        finally:
            browser.close()

    after_hashes = {path.name: _sha256(path) for path in db_paths}
    db_hash_drift = sorted(
        name for name, before_hash in before_hashes.items() if after_hashes.get(name) != before_hash
    )
    unexpected_db_hash_drift = sorted(set(db_hash_drift) - allowed_db_drift)
    if unexpected_db_hash_drift:
        failures.append({
            "route": "GET no-write",
            "reasons": [f"数据库 hash 在浏览器审计前后变化: {unexpected_db_hash_drift}"],
        })
    return {
        "passed": not failures,
        "base_url": base_url,
        "chrome": str(chrome),
        "page_count": len(pages),
        "before_db_hashes": before_hashes,
        "after_db_hashes": after_hashes,
        "db_hash_drift": db_hash_drift,
        "allowed_db_drift": sorted(allowed_db_drift),
        "unexpected_db_hash_drift": unexpected_db_hash_drift,
        "failures": failures,
        "pages": pages,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="A/B/C viewer 的 Playwright 桌面/移动只读验收")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--chrome", type=Path, default=DEFAULT_CHROME)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--allow-db-drift",
        action="append",
        default=[],
        choices=("research.db", "sentiment.db", "opportunity_lens.db", "financial.db"),
        help="显式声明审计期间由外部已知 writer 造成的 DB hash 漂移；默认不允许",
    )
    args = parser.parse_args()
    if not args.chrome.is_file():
        raise FileNotFoundError(f"Chrome 不存在: {args.chrome}")
    result = audit(
        args.base_url.rstrip("/"),
        args.output,
        args.chrome,
        allowed_db_drift=set(args.allow_db_drift),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "passed": result["passed"],
        "page_count": result["page_count"],
        "failure_count": len(result["failures"]),
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
