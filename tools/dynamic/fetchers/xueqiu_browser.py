#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""雪球无头浏览器抓取 —— 用真实 Chromium 执行阿里云 WAF 的 JS 挑战(纯 HTTP 过不了),
注入 user 登录 cookie,页内 same-origin fetch 时间线 API,返回 raw statuses 列表。

依赖:playwright + chromium(`python -m playwright install chromium`)。
惰性导入 playwright —— 未安装时由调用方 try/except 兜底,不影响其余 fetcher。

可复用:fetch_statuses(uid, cookie_str, ua) -> list[dict]。
?? 反 slop:抓不到返回 [](绝不编造)。WAF 挑战在真实浏览器内执行后设 acw_sc__v2,
   随后页内 fetch 自带该令牌 + 登录 cookie,即可拿到真 JSON。
"""
from __future__ import annotations
import json

PAGE_TPL = "https://xueqiu.com/u/{uid}"
API_TPL  = "/v4/statuses/user_timeline.json?user_id={uid}&page=1"


def _cookies(cookie_str, domain=".xueqiu.com"):
    """整段 Cookie 头 → playwright add_cookies 格式。"""
    out = []
    for kv in (cookie_str or "").split(";"):
        kv = kv.strip()
        if "=" not in kv:
            continue
        n, v = kv.split("=", 1)
        out.append({"name": n.strip(), "value": v.strip(), "domain": domain, "path": "/"})
    return out


def fetch_statuses(uid, cookie_str, ua, timeout_ms=30000, settle_ms=3500):
    """返回雪球 user_timeline 的 raw statuses 列表(失败 → [])。"""
    from playwright.sync_api import sync_playwright   # 惰性导入

    statuses = []
    with sync_playwright() as p:
        b = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        try:
            ctx = b.new_context(user_agent=ua, locale="zh-CN", viewport={"width": 1366, "height": 768})
            # 抹掉 navigator.webdriver,降低 headless 被识别概率
            ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
            if cookie_str:
                ctx.add_cookies(_cookies(cookie_str))
            page = ctx.new_page()
            page.goto(PAGE_TPL.format(uid=uid), wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(settle_ms)                 # 等 WAF 挑战自解
            if "aliyun_waf" in page.content():               # 仍在挑战页 → reload 再等一轮
                page.reload(wait_until="networkidle", timeout=timeout_ms)
                page.wait_for_timeout(settle_ms)
            # 页内 same-origin fetch:自带 WAF 通过令牌 + 登录 cookie
            txt = page.evaluate(
                "async (api) => { const r = await fetch(api, {headers:{'Accept':'application/json'}}); return await r.text(); }",
                API_TPL.format(uid=uid),
            )
            statuses = (json.loads(txt) or {}).get("statuses") or []
        finally:
            b.close()
    return statuses


if __name__ == "__main__":   # 手测:python xueqiu_browser.py <uid>
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    from pathlib import Path
    uid = sys.argv[1] if len(sys.argv) > 1 else "5519392453"
    ck_f = Path(__file__).resolve().parent.parent / "secrets" / "xueqiu_cookies.txt"
    ck = ck_f.read_text(encoding="utf-8").strip() if ck_f.exists() else None
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    st = fetch_statuses(uid, ck, ua)
    print(f"statuses={len(st)}")
    for s in st[:3]:
        import re
        print(" -", re.sub(r"<[^>]+>", "", s.get("text") or s.get("description") or "")[:60])
