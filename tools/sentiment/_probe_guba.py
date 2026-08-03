#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""临时:探东财股吧 DOM 结构,定位帖子行选择器与字段顺序。"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    ctx = b.new_context(user_agent=UA, locale="zh-CN")
    pg = ctx.new_page()
    pg.goto("https://guba.eastmoney.com/list,300308.html", timeout=30000, wait_until="domcontentloaded")
    pg.wait_for_timeout(2500)
    for sel in ["div.articleh", "tr.listitem", ".default_list tr", "table.default_list tbody tr"]:
        try:
            n = pg.locator(sel).count()
        except Exception:
            n = -1
        print(f"selector {sel!r:40} count={n}")
    print("\n--- div.articleh 前 5 行 innerText ---")
    loc = pg.locator("div.articleh")
    cnt = loc.count()
    for i in range(min(cnt, 5)):
        t = loc.nth(i).inner_text().replace("\n", " | ")
        print(f"  [{i}] {t[:120]}")
    # 帖子链接样例
    print("\n--- 帖子链接样例(前5)---")
    hrefs = pg.eval_on_selector_all("div.articleh a", "els => els.map(e => e.getAttribute('href')).filter(h => h && h.indexOf('300308') >= 0).slice(0,5)")
    for h in hrefs:
        print("  ", h)
    b.close()
