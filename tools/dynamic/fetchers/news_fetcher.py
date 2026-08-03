#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
C1 新闻抓取 — 可复用 ABC + 工厂(铁律 11/9)

BaseNewsFetcher(ABC):统一接口 fetch(source_config) -> List[NewsCandidate]
RSSNewsFetcher:通用 RSS/Atom 解析(stdlib,无 feedparser 依赖)
make_news_fetcher(source_config):工厂 —— 有 rss → RSSNewsFetcher;无 rss → None(落 pending)

NewsCandidate = {title, url, content_text, summary, source_publisher, publish_date}
?? 不写"专门给某家用"的 fetcher;新增源 = config 加一行 rss(零改代码)。
?? 反 slop:内容 verbatim;publish_date 解析自 RSS pubDate,拿不到 → None(ingest 标 description)。
"""
from __future__ import annotations
import sys, io, ssl, re
from abc import ABC, abstractmethod
from datetime import datetime
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from email.utils import parsedate_to_datetime

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
TIMEOUT = 12
_ctx = ssl.create_default_context(); _ctx.check_hostname = False; _ctx.verify_mode = ssl.CERT_NONE
_TAG = re.compile(r"<[^>]+>")


def _strip_html(s):
    return _TAG.sub("", s or "").strip()


def _parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        return parsedate_to_datetime(s).date().isoformat()      # RFC822 (RSS)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:len(fmt) if "T" not in fmt else 19], fmt).date().isoformat()
        except Exception:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return None


class BaseNewsFetcher(ABC):
    """新闻抓取统一接口。"""
    @abstractmethod
    def fetch(self, source_config: dict) -> list[dict]:
        ...


class RSSNewsFetcher(BaseNewsFetcher):
    def fetch(self, source_config: dict) -> list[dict]:
        rss = source_config.get("rss")
        if not rss:
            return []
        req = Request(rss, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
        with urlopen(req, timeout=TIMEOUT, context=_ctx) as r:
            raw = r.read()
        return self._parse(raw, source_config["name"])

    def _parse(self, raw: bytes, publisher: str) -> list[dict]:
        out = []
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            return out
        # RSS 2.0
        items = root.findall(".//item")
        if items:
            for it in items:
                title = (it.findtext("title") or "").strip()
                link = (it.findtext("link") or "").strip()
                desc = it.findtext("description") or ""
                pub = it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date")
                if title and link:
                    out.append({"title": title, "url": link, "content_text": _strip_html(desc),
                                "summary": _strip_html(desc)[:300], "source_publisher": publisher,
                                "publish_date": _parse_date(pub)})
            return out
        # Atom
        ns = "{http://www.w3.org/2005/Atom}"
        entries = root.findall(f".//{ns}entry")
        for e in entries:
            title = (e.findtext(f"{ns}title") or "").strip()
            link = ""
            for lk in e.findall(f"{ns}link"):
                if lk.get("rel") in (None, "alternate") and lk.get("href"):
                    link = lk.get("href"); break
            summ = e.findtext(f"{ns}summary") or e.findtext(f"{ns}content") or ""
            pub = e.findtext(f"{ns}updated") or e.findtext(f"{ns}published")
            if title and link:
                out.append({"title": title, "url": link, "content_text": _strip_html(summ),
                            "summary": _strip_html(summ)[:300], "source_publisher": publisher,
                            "publish_date": _parse_date(pub)})
        return out


def make_news_fetcher(source_config: dict):
    """工厂:有 rss → RSSNewsFetcher;否则 None(无 RSS,落 pending)。"""
    if source_config.get("rss"):
        return RSSNewsFetcher()
    return None
