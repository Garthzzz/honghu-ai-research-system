#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""东财股吧抓取(Playwright 真浏览器)。返回**帖级**记录(含标题/链接/校验后时间),
供:发帖量(小时/日)+ T3 情绪方向分(对标题跑 DeepSeek)。
?? T1 修复:时间只从行的【最后一个单元格】解析(标题里的 NN-NN 数字区间不再误判为月日);
   支持 'YYYY-MM-DD HH:MM' / 'MM-DD HH:MM' / 'HH:MM';??校验门:非法日历日期/小时一律 None(拒绝入库)。
?? 反slop:抓不到返回 [](绝不编造);校验失败计数返回,不写垃圾。
"""
from __future__ import annotations
import os, sys, re, time
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
TZ = timezone(timedelta(hours=8))
GUBA_LIST_API = "https://gbapi.eastmoney.com/webarticlelist/api/Article/WebArticleList"
GUBA_LIST_PROXY = "https://mguba.eastmoney.com/mguba2020/interface/GetData.aspx"
GUBA_API_PAGE_SIZE = 50  # The endpoint overlaps pages when ps > 50.
_FULL = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$")
_MD = re.compile(r"^(\d{1,2})-(\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?$")
_HM = re.compile(r"^(\d{1,2}):(\d{2})$")
_NUM = re.compile(r"^\s*([\d.]+)\s*(万)?")
_PID = re.compile(r"/news,\d+,(\d+)")
_ROW_JS = """els => els.map(tr => {
  const tds = tr.querySelectorAll('td');
  const a = tr.querySelector('a[href*="/news,"]') || tr.querySelector('td:nth-child(3) a') || tr.querySelector('a');
  const txt = el => el ? (el.textContent||'').trim() : '';
  return {
    read: tds[0] ? txt(tds[0]) : '',
    reply: tds[1] ? txt(tds[1]) : '',
    title: a ? txt(a) : (tds[2] ? txt(tds[2]) : ''),
    href: a ? (a.getAttribute('href')||'') : '',
    tm: tds.length ? txt(tds[tds.length-1]) : ''
  };
})"""


class _GubaListParser(HTMLParser):
    """Parse the server-rendered list table without executing site JavaScript."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._cells = None
        self._cell = None
        self._title_parts = None
        self._title_anchor_depth = 0
        self._href = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr" and "listitem" in (attrs.get("class") or "").split():
            self._cells = []
            self._cell = None
            self._title_parts = []
            self._title_anchor_depth = 0
            self._href = ""
            return
        if self._cells is None:
            return
        if tag == "td":
            self._cells.append([])
            self._cell = len(self._cells) - 1
        elif tag == "a" and self._cell == 2 and not self._href:
            self._href = attrs.get("href") or ""
            self._title_anchor_depth = 1
        elif tag == "a" and self._title_anchor_depth:
            self._title_anchor_depth += 1

    def handle_data(self, data):
        if self._cells is None or self._cell is None:
            return
        self._cells[self._cell].append(data)
        if self._cell == 2 and self._title_anchor_depth:
            self._title_parts.append(data)

    def handle_endtag(self, tag):
        if self._cells is None:
            return
        if tag == "a" and self._title_anchor_depth:
            self._title_anchor_depth -= 1
        elif tag == "td":
            self._cell = None
        elif tag == "tr":
            cells = ["".join(parts).strip() for parts in self._cells]
            if cells:
                self.rows.append({
                    "read": cells[0] if len(cells) > 0 else "",
                    "reply": cells[1] if len(cells) > 1 else "",
                    "title": "".join(self._title_parts).strip() or (cells[2] if len(cells) > 2 else ""),
                    "href": self._href,
                    "tm": cells[-1],
                })
            self._cells = self._cell = self._title_parts = None
            self._title_anchor_depth = 0
            self._href = ""


def _parse_server_rows(html):
    parser = _GubaListParser()
    parser.feed(html or "")
    parser.close()
    return parser.rows


def _empty_server_page_reason(html):
    """Classify a row-less response; only a structurally valid empty table is complete."""
    html = html or ""
    if any(marker in html for marker in ("身份核实", "拖动下方滑块", "captcha")):
        return "challenge"
    table = re.search(r"<table\b[^>]*\bdefault_list\b[^>]*>(.*?)</table>", html, re.I | re.S)
    if table is None:
        return "unexpected_markup"
    # A valid exhausted page contains only its header row.  More rows mean the
    # upstream markup changed and our listitem selector/parser drifted.
    return "empty" if len(re.findall(r"<tr\b", table.group(1), re.I)) <= 1 else "selector_drift"


class _HTTPListPage:
    """Playwright-page-compatible adapter backed by Eastmoney's WAP JSON API."""

    def __init__(self, session):
        self.session = session
        self.rows = []
        self.last_empty_reason = None

    def goto(self, url, **_kwargs):
        match = re.search(r"list,(\d+)(?:_(\d+))?\.html", url)
        if match is None:
            raise ValueError(f"unexpected guba list URL: {url}")
        code = match.group(1)
        page = int(match.group(2) or 1)
        query = {
            "code": code,
            "p": page,
            "ps": GUBA_API_PAGE_SIZE,
            # Publication-time order is the requested post window.  Sorting
            # by last reply would mix bumped old posts into a new-post count.
            "sorttype": 0,
            "plat": "wap",
            "version": 300,
            "product": "guba",
            "deviceid": 1,
        }
        errors = []
        payload = None
        try:
            response = self.session.get(
                GUBA_LIST_API, params=query,
                headers={"Referer": f"https://mguba.eastmoney.com/mguba/list/{code}"},
                timeout=(8, 30),
            )
            response.raise_for_status()
            candidate = response.json()
            if candidate.get("rc") == 1 and isinstance(candidate.get("re"), list):
                payload = candidate
            else:
                errors.append(f"direct_rc={candidate.get('rc')!r}")
        except Exception as exc:
            errors.append(f"direct={type(exc).__name__}")
        if payload is None:
            # Official mobile-page proxy is independent from the desktop-list
            # anti-bot route and is a reliable fallback when gbapi returns rc=0.
            try:
                param = (f"code={code}&p={page}&ps={GUBA_API_PAGE_SIZE}&sorttype=0")
                response = self.session.post(
                    GUBA_LIST_PROXY,
                    data={
                        "param": param, "plat": "wap", "version": "200",
                        "path": "/webarticlelist/api/Article/WebArticleList",
                        "env": "1", "origin": "", "ctoken": "", "utoken": "",
                    },
                    headers={
                        "Referer": f"https://mguba.eastmoney.com/mguba/list/{code}",
                        "Origin": "https://mguba.eastmoney.com",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    timeout=(8, 30),
                )
                response.raise_for_status()
                candidate = response.json()
                if candidate.get("rc") == 1 and isinstance(candidate.get("re"), list):
                    payload = candidate
                else:
                    errors.append(f"proxy_rc={candidate.get('rc')!r}")
            except Exception as exc:
                errors.append(f"proxy={type(exc).__name__}")
        if payload is None:
            raise RuntimeError("guba_api_failed:" + ",".join(errors))
        self.rows = []
        for item in payload["re"]:
            post_id = str(item.get("post_id") or "").strip()
            publish_time = str(item.get("post_publish_time") or "").strip()
            if not post_id:
                continue
            raw_title = item.get("post_title") or item.get("post_content") or ""
            title = unescape(re.sub(r"<[^>]+>", " ", str(raw_title)))
            title = re.sub(r"\s+", " ", title).strip()
            self.rows.append({
                "read": str(item.get("post_click_count") or ""),
                "reply": str(item.get("post_comment_count") or ""),
                "title": title,
                "href": f"/news,{code},{post_id}.html",
                "tm": publish_time,
                "pt": publish_time,
                "top": bool(item.get("post_top_status")),
            })
        self.last_empty_reason = "empty" if not self.rows else None

    def wait_for_timeout(self, _milliseconds):
        return None

    def eval_on_selector_all(self, *_args):
        return list(self.rows)


def _browser_channels():
    """Return a deterministic launch order without assuming bundled Chromium exists.

    Windows production machines commonly have system Chrome/Edge but omit the
    Playwright-managed browser download.  Prefer those installed channels there;
    keep bundled Chromium first on other platforms and retain explicit fallbacks.
    """
    configured = (os.environ.get("PLAYWRIGHT_BROWSER_CHANNEL") or "").strip()
    preferred = (["chrome", "msedge", None] if sys.platform.startswith("win")
                 else [None, "chrome", "msedge"])
    ordered = ([configured] if configured else []) + preferred
    result = []
    for channel in ordered:
        if channel not in result:
            result.append(channel)
    return result


def _launch_browser(playwright, *, headless=True):
    errors = []
    args = ["--disable-blink-features=AutomationControlled"]
    for channel in _browser_channels():
        kwargs = {"headless": headless, "args": args}
        if channel:
            kwargs["channel"] = channel
        try:
            return playwright.chromium.launch(**kwargs)
        except Exception as exc:
            label = channel or "bundled-chromium"
            errors.append(f"{label}:{type(exc).__name__}:{str(exc).splitlines()[0][:100]}")
    raise RuntimeError("no usable Playwright browser; " + " | ".join(errors))


def _to_int(tok):
    m = _NUM.match(tok or "")
    if not m:
        return None
    v = float(m.group(1))
    if m.group(2) == "万":
        v *= 10000
    return int(v)


def parse_time(s, now=None):
    """东财时间字段(最后单元格)→ (ts_hour, trade_date, hour, posted_at_iso) 或 None(校验门拒绝)。"""
    s = (s or "").strip()
    now = now or datetime.now(TZ)
    yr = mo = da = None
    hh = mm = ss = 0
    m = _FULL.match(s)
    if m:
        yr, mo, da = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if m.group(4):
            hh, mm = int(m.group(4)), int(m.group(5))
            ss = int(m.group(6) or 0)
    elif _MD.match(s):
        m = _MD.match(s)
        mo, da = int(m.group(1)), int(m.group(2))
        if m.group(3):
            hh, mm = int(m.group(3)), int(m.group(4))
        yr = now.year
        if mo > now.month + 1:                 # 跨年回推:月份比当前晚很多 → 去年
            yr -= 1
    elif _HM.match(s):
        m = _HM.match(s)
        hh, mm = int(m.group(1)), int(m.group(2))
        yr, mo, da = now.year, now.month, now.day
    else:
        return None
    # ?? 校验门:合法日历 + 合法时分
    if not (1 <= mo <= 12 and 1 <= da <= 31 and 0 <= hh <= 23
            and 0 <= mm <= 59 and 0 <= ss <= 59):
        return None
    try:
        dt = datetime(yr, mo, da, hh, mm, ss, tzinfo=TZ)
    except ValueError:
        return None
    if dt > now + timedelta(days=1):           # 不允许未来
        return None
    return (dt.strftime("%Y-%m-%dT%H:00"), dt.strftime("%Y-%m-%d"), hh,
            dt.isoformat(timespec="minutes"))


def _post_id(href):
    if not href:
        return None
    m = _PID.search(href)
    if m:
        return m.group(1)
    nums = re.findall(r"(\d{6,})", href)
    return nums[-1] if nums else href[:60]


_PIDTS = re.compile(r"^(20\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})")


def _ts_from_pid(pid, now):
    """新版 post_id 前 14 位是【原帖发布时间】YYYYMMDDHHMMSS → (ts_hour,date,hour,posted_at)。
    ??比列表'最后更新时间'更准(避免被顶旧帖污染)。旧序列号 id 无时间 → None。"""
    m = _PIDTS.match(str(pid))
    if not m:
        return None
    yr, mo, da, hh, mm, ss = (int(g) for g in m.groups())
    if not (1 <= mo <= 12 and 1 <= da <= 31 and 0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    try:
        dt = datetime(yr, mo, da, hh, mm, tzinfo=TZ)
    except ValueError:
        return None
    if dt > now + timedelta(days=1):
        return None
    return (dt.strftime("%Y-%m-%dT%H:00"), dt.strftime("%Y-%m-%d"), hh, dt.isoformat(timespec="minutes"))


def _fetch_page_sequence(pg, code, *, pages, window_start=None):
    """在复用 page 上翻到时间边界；达到页数上限但未越界即显式 truncated。"""
    posts, bad, page_errors = [], 0, 0
    now = datetime.now(TZ)
    if window_start is not None:
        if window_start.tzinfo is None:
            raise ValueError("window_start must be timezone-aware")
        window_start = window_start.astimezone(TZ)
    seen = set()
    boundary_reached = False
    incomplete_reason = None
    for pageno in range(1, int(pages) + 1):
        url = (f"https://guba.eastmoney.com/list,{code}.html" if pageno == 1
               else f"https://guba.eastmoney.com/list,{code}_{pageno}.html")
        try:
            pg.goto(url, timeout=30000, wait_until="domcontentloaded")
            pg.wait_for_timeout(1700)
            rows = pg.eval_on_selector_all("table.default_list tr.listitem", _ROW_JS)
        except Exception:
            page_errors += 1
            incomplete_reason = f"page_fetch_error:page={pageno}"
            break
        if not rows:
            empty_reason = getattr(pg, "last_empty_reason", None)
            if pageno == 1:
                incomplete_reason = f"{empty_reason or 'empty'}:first_page"
            elif empty_reason in {"challenge", "unexpected_markup", "selector_drift"}:
                incomplete_reason = f"{empty_reason}:page={pageno}"
            else:
                # A normal empty later page proves that the board has no older rows.
                boundary_reached = True
            break
        activity_times = []
        boundary_rows = 0
        for r in rows:
            activity = parse_time(r.get("tm"), now)
            pid = _post_id(r.get("href"))
            if not pid or pid in seen:
                continue
            # Pinned rows are editorial inserts, not pagination-order evidence.
            if not r.get("top"):
                boundary_rows += 1
                if activity:
                    activity_times.append(datetime.fromisoformat(activity[3]))
            # WAP API supplies the exact publish time.  Legacy server HTML can
            # still recover a timestamp from newer timestamp-shaped post IDs.
            explicit_time = parse_time(r.get("pt"), now) if r.get("pt") else None
            pidt = explicit_time or _ts_from_pid(pid, now)
            if pidt:
                ts_hour, trade_date, hour, posted_at = pidt
                caliber = "post_time_api" if explicit_time else "post_time"
            else:
                pt = activity
                if not pt:
                    bad += 1
                    continue
                ts_hour, trade_date, hour, posted_at = pt
                caliber = "last_update"
            seen.add(pid)
            href = r.get("href") or ""
            purl = (href if href.startswith("http") else
                    ("https:" + href) if href.startswith("//") else
                    ("https://guba.eastmoney.com" + href) if href.startswith("/") else None)
            posts.append({"post_id": str(pid), "post_url": purl, "posted_at": posted_at,
                          "ts_hour": ts_hour, "trade_date": trade_date, "time_caliber": caliber,
                          "title": (r.get("title") or "").strip()[:200],
                          "read": _to_int(r.get("read")), "reply": _to_int(r.get("reply"))})
        # 列表按最后回复时间倒序；整页活动时间都早于窗口起点后，后续页不可能
        # 再出现窗口内新帖。使用列表时间而非原帖时间，避免被顶旧帖干扰边界。
        if (window_start is not None and boundary_rows > 0
                and len(activity_times) == boundary_rows
                and activity_times and max(activity_times) < window_start):
            boundary_reached = True
            break
        time.sleep(0.35)
    errors = []
    if page_errors:
        errors.append(f"page_fetch_errors:{page_errors}")
    if incomplete_reason:
        errors.append(incomplete_reason)
    elif not boundary_reached:
        errors.append(f"truncated:max_pages={pages}")
    return posts, bad, "|".join(errors) if errors else None


class GubaBrowser:
    """兼容旧调用名；生产抓取复用轻量 HTTP session，避开浏览器验证码页。"""

    def __init__(self, *, headless=True):
        self.headless = headless
        self._session = self.page = None

    def _open_session(self):
        if self._session is not None:
            self._session.close()
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": ("Mozilla/5.0 (Linux; Android 13; Pixel 7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/124.0.0.0 Mobile Safari/537.36"),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
            "Referer": "https://guba.eastmoney.com/",
        })
        self.page = _HTTPListPage(self._session)

    def __enter__(self):
        self._open_session()
        return self

    def fetch(self, code, pages=8, *, window_start=None, with_status=True):
        if self.page is None:
            raise RuntimeError("GubaBrowser is not open")
        result = _fetch_page_sequence(
            self.page, code, pages=pages, window_start=window_start
        )
        # A fresh session recovers transient challenge/empty/HTTP pages.  Do not
        # retry a genuine max-page truncation: that requires a larger page cap.
        if result[2] and "truncated:max_pages" not in result[2]:
            first = result
            self._open_session()
            retry = _fetch_page_sequence(
                self.page, code, pages=pages, window_start=window_start
            )
            result = max((first, retry), key=lambda item: (item[2] is None, len(item[0])))
        return result if with_status else result[:2]

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._session is not None:
                self._session.close()
        except Exception:
            pass
        self.page = self._session = None


def fetch_guba_posts(code, pages=8, headless=True, with_status=False, window_start=None):
    """单公司兼容入口；生产全量抓取使用 :class:`GubaBrowser` 复用 HTTP 会话。"""
    bad = 0
    try:
        with GubaBrowser(headless=headless) as browser:
            posts, bad, error = browser.fetch(
                code, pages=pages, window_start=window_start, with_status=True
            )
    except Exception as e:
        print(f"  [guba {code}] fetch err: {type(e).__name__} {str(e)[:60]}", file=sys.stderr)
        error = f"{type(e).__name__}:{str(e)[:120]}"
        return ([], bad, error) if with_status else ([], bad)
    return (posts, bad, error) if with_status else (posts, bad)


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "300308"
    pages = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    posts, bad = fetch_guba_posts(code, pages)
    print(f"东财股吧 {code} {pages}页 → 帖 {len(posts)} | 时间校验失败 {bad}")
    from collections import Counter
    bydate = Counter(p["trade_date"] for p in posts)
    for d in sorted(bydate, reverse=True):
        print(f"  {d}: {bydate[d]} 帖")
    print("样例帖:")
    for p in posts[:4]:
        print(f"  [{p['posted_at']}] pid={p['post_id']} 「{p['title'][:30]}」 read={p['read']}")
