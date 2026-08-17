#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""信源链路重构 P0 — X(twitter)playwright 登录态抓取(D3 正式路线)。

无 storage_state / 登录态失效 → 撞登录墙 → 返回 status='auth_expired'(绝不编造)。
时间盒 + 有限尝试(铁律:不对 x.com 高频重试)。headless;session 0 非交互态很可能失效(见 DESIGN §2.1)。

fetch_timeline(handle, storage_state_path, max_posts) -> (posts: list[dict], status: str)
  status ∈ {'ok','auth_expired','error'}
"""
from __future__ import annotations
import json, re
from pathlib import Path

PROFILE = "https://x.com/{handle}"


def _looks_login_wall(page) -> bool:
    try:
        u = page.url or ""
        if "/login" in u or "/i/flow/login" in u or "/account/access" in u:
            return True
        html = page.content()
        if 'data-testid="loginButton"' in html or "Sign in to X" in html or "Something went wrong" in html:
            # 仍可能有内容;只有在没有 tweet 时才判墙(下方调用处结合 posts 判断)
            return ("article" not in html)
    except Exception:
        return False
    return False


def fetch_timeline(handle: str, storage_state_path: str | None, max_posts: int = 15,
                   timeout_ms: int = 20000, settle_ms: int = 3500):
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return [], "error"

    ss = None
    if storage_state_path:
        p = Path(storage_state_path)
        if p.exists() and p.stat().st_size > 2:
            try:
                json.loads(p.read_text(encoding="utf-8"))   # 验证是合法 storage_state
                ss = str(p)
            except Exception:
                ss = None

    posts, status = [], "error"
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True,
                               args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
        try:
            ctx = b.new_context(storage_state=ss, locale="en-US",
                                viewport={"width": 1280, "height": 1600},
                                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"))
            ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
            page = ctx.new_page()
            page.goto(PROFILE.format(handle=handle), wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(settle_ms)
            try:
                page.wait_for_selector("article", timeout=6000)
            except Exception:
                pass
            arts = page.query_selector_all("article")
            for a in arts[:max_posts]:
                try:
                    txt = (a.inner_text() or "").strip()
                except Exception:
                    txt = ""
                if not txt:
                    continue
                pid = None
                try:
                    for lk in a.query_selector_all("a[href*='/status/']"):
                        m = re.search(r"/status/(\d+)", lk.get_attribute("href") or "")
                        if m:
                            pid = m.group(1); break
                except Exception:
                    pass
                if not pid:
                    continue
                posts.append({"post_id": pid,
                              "post_url": f"https://x.com/{handle}/status/{pid}",
                              "posted_at": None,
                              "content_text": re.sub(r"\s+\n", "\n", txt)[:1000],
                              "content_html": "", "has_media": False})
            if posts:
                status = "ok"
            elif _looks_login_wall(page):
                status = "auth_expired"
            else:
                status = "auth_expired"   # 无墙但 0 帖(headless 被风控/空)→ 按需登录处理,不编造
        except Exception:
            status = "error"
        finally:
            b.close()
    # 去重 post_id
    seen, uniq = set(), []
    for p in posts:
        if p["post_id"] in seen:
            continue
        seen.add(p["post_id"]); uniq.append(p)
    return uniq, status


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    h = sys.argv[1] if len(sys.argv) > 1 else "dylan522p"
    from tools.runtime_paths import resolve_runtime_layout
    root = Path(__file__).resolve().parents[3]
    ssf = resolve_runtime_layout(root).content_root / "tools" / "dynamic" / "secrets" / "x_storage_state.json"
    posts, st = fetch_timeline(h, str(ssf))
    print(f"@{h}: status={st} posts={len(posts)}")
    for p in posts[:3]:
        print("  -", p["content_text"][:80].replace("\n", " "))
