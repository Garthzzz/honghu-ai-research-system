#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""信源链路重构 P2 — 财联社电报 fetcher(JSON+sign 优先,playwright DOM 兜底)。

JSON:www.cls.cn 电报接口需 sign 签名(固定 app 参数 + 参数排序 → sha1 → md5)。
  ?? Q5:sign 失效 / 接口改版 → 返回 status='auth_expired'(显式告警,防静默失效被误当"今天没新闻")。
playwright:JSON 失败时抓 https://www.cls.cn/telegraph DOM 兜底。

fetch_cls(max_items) -> (items: list[dict], status: str)
  item = {title, url, content_text, publish_date, source_publisher='财联社电报'}
  status ∈ {'ok','auth_expired','error'}
?? 反 slop:抓不到返回 []+auth_expired,绝不编造电报。
"""
from __future__ import annotations
import hashlib, json, ssl, time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from datetime import datetime, timezone, timedelta

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_ctx = ssl.create_default_context(); _ctx.check_hostname = False; _ctx.verify_mode = ssl.CERT_NONE
# 真实端点(2026-06 实测):缓存版电报列表;sign = md5(sha1(sorted_querystring))
_API = "https://www.cls.cn/api/cache"
_SV = "8.7.9"


def _sign(params: dict) -> str:
    """cls web sign:sorted querystring → sha1 → md5(已对实测 sign 校验一致)。"""
    q = urlencode(sorted(params.items()))
    s1 = hashlib.sha1(q.encode("utf-8")).hexdigest()
    return hashlib.md5(s1.encode("utf-8")).hexdigest()


def _cst(ts) -> str | None:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone(timedelta(hours=8))).date().isoformat()
    except Exception:
        return None


def _fetch_json(max_items: int):
    base = {"app": "CailianpressWeb", "name": "telegraph", "os": "web", "sv": _SV}
    base["sign"] = _sign(base)
    url = _API + "?" + urlencode(base)
    req = Request(url, headers={"User-Agent": _UA, "Accept": "application/json",
                                "Referer": "https://www.cls.cn/telegraph"})
    with urlopen(req, timeout=15, context=_ctx) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    # 接口正常:errno==0 且 data.roll_data 有内容
    if not isinstance(d, dict) or d.get("errno") not in (0, None):
        raise RuntimeError(f"cls errno={d.get('errno')} msg={d.get('errmsg')}")
    data = d.get("data") or {}
    rolls = data.get("roll_data") or data.get("rollData") or []
    if not rolls:
        raise RuntimeError("cls roll_data empty(疑 sign 失效/改版)")
    items = []
    for it in rolls[:max_items]:
        if it.get("is_ad") or it.get("type") == 1:
            continue
        cid = it.get("id")
        content = (it.get("content") or it.get("brief") or "").strip()
        title = (it.get("title") or "").strip() or content
        if not content and not title:
            continue
        items.append({
            "title": title[:200],
            "url": f"https://www.cls.cn/detail/{cid}" if cid else (it.get("shareurl") or ""),
            "content_text": content,
            "publish_date": _cst(it.get("ctime")),
            "source_publisher": "财联社电报",
        })
    return [i for i in items if i["url"]]


def _fetch_playwright(max_items: int):
    from playwright.sync_api import sync_playwright
    out = []
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = b.new_context(user_agent=_UA, locale="zh-CN").new_page()
            page.goto("https://www.cls.cn/telegraph", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3500)
            # 电报条目通常在 .telegraph-content-box / .f-l.telegraph-content 之类;宽松抓取
            nodes = page.query_selector_all("[class*=telegraph-content]")
            for n in nodes[:max_items]:
                t = (n.inner_text() or "").strip()
                if not t:
                    continue
                link = ""
                try:
                    a = n.query_selector("a[href*='/detail/']")
                    if a:
                        link = "https://www.cls.cn" + (a.get_attribute("href") or "")
                except Exception:
                    pass
                out.append({"title": t[:200], "url": link or f"https://www.cls.cn/telegraph#{hash(t) & 0xffffff}",
                            "content_text": t, "publish_date": None, "source_publisher": "财联社电报"})
        finally:
            b.close()
    return out


def fetch_cls(max_items: int = 30):
    # ① JSON + sign
    try:
        items = _fetch_json(max_items)
        if items:
            return items, "ok"
    except Exception as e:
        json_err = str(e)[:120]
    else:
        json_err = "empty"
    # ② playwright 兜底
    try:
        items = _fetch_playwright(max_items)
        if items:
            return items, "ok"
    except Exception:
        pass
    # 两路皆败 → sign 失效/反爬 → auth_expired(显式告警)
    return [], "auth_expired"


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    items, st = fetch_cls(20)
    print(f"财联社电报:status={st} items={len(items)}")
    for it in items[:5]:
        print("  -", it["title"][:60], "|", it["url"])
