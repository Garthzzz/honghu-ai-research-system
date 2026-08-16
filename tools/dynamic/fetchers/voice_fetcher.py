#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
D1 意见领袖抓取 — 可复用 ABC + 工厂 + 优先级 fallback(铁律 11/14)

BaseFetcher(ABC):fetch(leader) -> List[VoicePostCandidate] + healthcheck() -> bool
XueqiuFetcher / XFetcher:既有优先级链；WeiboFetcher 仅调用舆情 API。
VoicePostCandidate = {post_id, post_url, posted_at, content_text, content_html, has_media}

反 slop:抓不到返回 [](绝不编造推文);内容 verbatim;post_id 用于去重。
反爬:非微博平台沿用 UA/平台间隔；微博只走舆情 API，不访问微博网页或 cookie。
新增平台 = 新增一个 BaseFetcher 子类 + config.platforms 加一段(不改 scheduler/ingest)。
"""
from __future__ import annotations
import sys, io, ssl, json, time, re
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from xml.etree import ElementTree as ET
from email.utils import parsedate_to_datetime

ROOT = Path(__file__).resolve().parent.parent.parent.parent
from tools.runtime_paths import resolve_runtime_layout
SECRETS = resolve_runtime_layout(ROOT).content_root / "tools" / "dynamic" / "secrets"
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
]
TIMEOUT = 12
# 桌面 UA（当前仅供非微博既有浏览器抓取链使用）
_DESKTOP_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
_ctx = ssl.create_default_context(); _ctx.check_hostname = False; _ctx.verify_mode = ssl.CERT_NONE
_TAG = re.compile(r"<[^>]+>")
_ua_i = [0]


def _ua():
    _ua_i[0] = (_ua_i[0] + 1) % len(UA_POOL)
    return UA_POOL[_ua_i[0]]


def _get(url, extra_headers=None):
    h = {"User-Agent": _ua(), "Accept": "*/*"}
    if extra_headers:
        h.update(extra_headers)
    req = Request(url, headers=h)
    with urlopen(req, timeout=TIMEOUT, context=_ctx) as r:
        return r.read()


def _cookie(platform):
    f = SECRETS / f"{platform}_cookies.txt"
    return f.read_text(encoding="utf-8").strip() if f.exists() else None


def _strip(s):
    return _TAG.sub("", s or "").strip()


def _try_kuaisearch(platform_cfg, uid, media_types):
    """API-first 抓取(智慧星光舆情快搜)。返回 (posts, status, used)。
    used=False 表示该平台未启用 API(mode!=api)→ 调用方走原 cookie/访客流。
    精准:client 内部按作者 uid 硬过滤,只返回本人发言(不抓提及)。"""
    if (platform_cfg or {}).get("mode") != "api":
        return [], "ok", False
    try:
        try:
            from .kuaisearch_client import KuaiSearchClient, load_token
        except ImportError:
            from kuaisearch_client import KuaiSearchClient, load_token
    except Exception:
        return [], "error", True
    if not load_token():
        return [], "auth_expired", True          # 无 key → 按需登录态(交给老路径兜底)
    api_cfg = (platform_cfg.get("api") or {})
    mt = media_types if media_types is not None else api_cfg.get("media_types")
    try:
        cli = KuaiSearchClient(api_cfg)
        posts = cli.fetch_leader_posts(str(uid), media_types=mt)
        return posts, cli.last_status, True
    except Exception:
        return [], "error", True


class BaseFetcher(ABC):
    platform = "base"
    last_status = "ok"      # ok | empty | auth_expired —— ingest 据此做三态告警

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}
        self.last_status = "ok"

    @abstractmethod
    def fetch(self, leader: dict) -> list[dict]:
        ...

    def healthcheck(self) -> bool:
        return True


class XueqiuFetcher(BaseFetcher):
    platform = "xueqiu"

    def fetch(self, leader):
        uid = leader["account_handle"]
        # API-first:舆情快搜(platforms.xueqiu.mode=api)。雪球无独立媒体枚举 → 全媒体拉取后按 uid 过滤。
        posts, st, used = _try_kuaisearch(self.cfg, uid, media_types=[])
        if used and posts:
            self.last_status = st
            return posts            # 命中本人发言即返回;其余(empty/api_miss/auth_expired/rate_limited/error)一律落老路径兜底(保功能)
        ck = _cookie("xueqiu")
        statuses = []
        # 优先:无头浏览器过阿里云 WAF JS 挑战(纯 HTTP 必被拦);需 playwright + cookie
        if ck:
            try:
                from xueqiu_browser import fetch_statuses
                statuses = fetch_statuses(uid, ck, _DESKTOP_UA)
            except Exception:
                statuses = []
        # 兜底:纯 HTTP(cookie 偶含 WAF 通过令牌时可用;否则 WAF → 空)
        if not statuses:
            try:
                url = f"https://xueqiu.com/v4/statuses/user_timeline.json?user_id={uid}&page=1"
                raw = _get(url, {"Cookie": ck} if ck else None)
                statuses = json.loads(raw.decode("utf-8", "replace")).get("statuses") or []
            except Exception:
                statuses = []
        posts = []
        for s in statuses:
            pid = str(s.get("id"))
            posts.append({"post_id": pid,
                          "post_url": (f"https://xueqiu.com{s.get('target','')}" if s.get("target")
                                       else f"https://xueqiu.com/{uid}/{pid}"),
                          "posted_at": _ts(s.get("created_at")),
                          "content_text": _strip(s.get("text") or s.get("description") or ""),
                          "content_html": s.get("text") or "", "has_media": bool(s.get("pic"))})
        if posts:
            self.last_status = "ok"
        elif used and st in {"cached_stale", "rate_limited", "auth_expired", "error"}:
            self.last_status = st
        return posts   # 全失败 → [](pending,绝不编造)


class WeiboFetcher(BaseFetcher):
    """Fetch configured KOLs from the monitored-account API and exact-match UID."""

    platform = "weibo"

    def fetch(self, leader):
        api_cfg = self.cfg.get("api") or {}
        media_types = api_cfg.get("media_types", [4])
        posts, status, used = _try_kuaisearch(
            self.cfg,
            str(leader.get("account_handle") or ""),
            media_types=media_types,
        )
        self.last_status = status if used else "system_error"
        if not used:
            raise RuntimeError("Weibo KOL fetcher requires mode=api")
        return posts


class XFetcher(BaseFetcher):
    platform = "twitter"

    def __init__(self, cfg=None):
        super().__init__(cfg)
        self.instances = (cfg or {}).get("nitter_instances") or []
        self.max_attempts = int((cfg or {}).get("x_max_attempts", 2))

    def fetch(self, leader):
        # 用户指定:① 先 Nitter RSS(多实例,有限次)② 全失败则 playwright 直连 → auth_expired
        self.last_status = "ok"
        handle = leader["account_handle"]
        tried = 0
        for tpl in self.instances:
            if tried >= max(self.max_attempts, len(self.instances)):
                break
            url = tpl.format(handle=handle)
            try:
                raw = _get(url)
                posts = self._parse_rss(raw, leader)
                if posts:
                    return posts
            except Exception:
                tried += 1
                continue
        # ② playwright 直连(无 storage_state → 撞登录墙 → auth_expired);时间盒,有限尝试
        try:
            from x_playwright import fetch_timeline
            ssf = self.cfg.get("storage_state_file")
            ss_path = str(SECRETS / Path(ssf).name) if ssf else None
            posts, st = fetch_timeline(handle, ss_path, max_posts=15)
            if posts:
                return posts
            self.last_status = "auth_expired" if st in ("auth_expired", "error") else "empty"
            return []
        except Exception:
            self.last_status = "auth_expired"
            return []

    def _parse_rss(self, raw, leader):
        out = []
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            return out
        for it in root.findall(".//item"):
            link = (it.findtext("link") or "").strip()
            desc = it.findtext("description") or ""
            title = it.findtext("title") or ""
            pid = link.rstrip("/").split("/")[-1].split("#")[0] or link
            # 用 x.com 规范链接(durable;nitter 实例可能失效),pid=status id
            canon = (f"https://x.com/{leader['account_handle']}/status/{pid}"
                     if pid.isdigit() else link)
            if link:
                out.append({"post_id": pid, "post_url": canon,
                            "posted_at": _ts(it.findtext("pubDate")),
                            "content_text": _strip(desc) or _strip(title),
                            "content_html": desc, "has_media": "<img" in desc})
        return out


def _ts(v):
    if v is None:
        return None
    # epoch 毫秒/秒(雪球 created_at 为 epoch ms)→ 东八区 ISO
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.strip().isdigit()):
        try:
            n = float(v)
            if n > 1e12:
                n /= 1000.0
            return datetime.fromtimestamp(n, tz=timezone(timedelta(hours=8))).isoformat(timespec="seconds")
        except Exception:
            pass
    s = str(v)
    try:
        return parsedate_to_datetime(s).isoformat(timespec="seconds")
    except Exception:
        return s[:25]


def make_fetcher(platform: str, platform_cfg: dict):
    if platform == "xueqiu":
        return XueqiuFetcher(platform_cfg)
    if platform == "weibo":
        return WeiboFetcher(platform_cfg)
    if platform == "twitter":
        return XFetcher(platform_cfg)
    return None
