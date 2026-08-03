#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
C4:Google News RSS 间接获取 Reuters/Bloomberg/AI 产业链新闻(真尝试)

news.google.com/rss/search?q=... 聚合多 publisher;<source> 标真实来源。
- 命中白名单 publisher → 用其 source 行(tier2/whitelisted)
- 其余 → 记 'Google News 聚合' 灰源 source(unverified,UI 标 ??)
- dedup url;入库后跑 relevance + importance
?? 真实尝试,失败如实记 cache/STAGE3C_PENDING.md。
"""
from __future__ import annotations
import sqlite3, sys, io, ssl
from pathlib import Path
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.parse import quote
from xml.etree import ElementTree as ET
from email.utils import parsedate_to_datetime

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DB = ROOT / "data" / "research.db"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
_ctx = ssl.create_default_context(); _ctx.check_hostname = False; _ctx.verify_mode = ssl.CERT_NONE
NOW = datetime.now().isoformat(timespec="seconds")
QUERIES = ["AI semiconductor HBM", "Nvidia GPU AI chip", "optical module 800G AI datacenter",
           "memory DRAM price AI", "AI datacenter capex hyperscaler"]
WHITELIST = {"reuters", "bloomberg", "trendforce", "semianalysis", "idc", "lightcounting"}


def fetch(query):
    url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/xml,*/*"})
    with urlopen(req, timeout=15, context=_ctx) as r:
        raw = r.read()
    root = ET.fromstring(raw)
    out = []
    for it in root.findall(".//item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = it.findtext("pubDate")
        src = it.find("{http://news.google.com/}source") or it.find("source")
        publisher = (src.text.strip() if src is not None and src.text else "Google News")
        try:
            pd = parsedate_to_datetime(pub).date().isoformat() if pub else None
        except Exception:
            pd = None
        if title and link:
            out.append({"title": title, "url": link, "publisher": publisher, "publish_date": pd})
    return out


def ensure_gnews_source(cur):
    r = cur.execute("SELECT id FROM source WHERE title='Google News 聚合' LIMIT 1").fetchone()
    if r:
        return r[0]
    cur.execute("""INSERT INTO source(title, source_type, publisher, quality_tier, value_layer,
                     source_url, url, source_subtype, fetch_method, domain, language,
                     is_primary_source, source_credibility, created_at, fetch_timestamp)
                   VALUES('Google News 聚合','财经媒体','Google News',3,'信息流',
                     'https://news.google.com/','https://news.google.com/','news_feed','google_news_rss',
                     'news.google.com','en',0,'unverified',?,?)""", (NOW, NOW))
    return cur.lastrowid


def main():
    con = sqlite3.connect(str(DB)); cur = con.cursor()
    # 白名单 publisher → source id
    wl = {p.lower(): sid for sid, p in cur.execute("SELECT id, publisher FROM source WHERE source_subtype='news_feed' AND source_credibility='whitelisted'")}
    gnews_sid = ensure_gnews_source(cur)
    got = ins = 0; attempts = []
    for q in QUERIES:
        try:
            items = fetch(q)
            attempts.append((q, len(items), "OK"))
        except Exception as e:
            attempts.append((q, 0, f"ERR {type(e).__name__}: {str(e)[:80]}")); continue
        for it in items:
            got += 1
            pl = it["publisher"].lower()
            sid = next((s for name, s in wl.items() if name in pl), None) or gnews_sid
            r = cur.execute("""INSERT OR IGNORE INTO news_item(title, url, source_publisher, source_id,
                                 publish_date, importance, fetch_timestamp)
                               VALUES(?,?,?,?,?,3,?)""",
                            (it["title"][:500], it["url"], it["publisher"], sid, it["publish_date"], NOW))
            ins += r.rowcount
    con.commit()
    print("Google News RSS 尝试:")
    for q, n, st in attempts:
        print(f"  '{q[:36]}' → {n} 条 {st}")
    print(f"\n抓取 {got} 候选,新入库 {ins} 条(去重后)")
    print("news_item 总数:", cur.execute("SELECT COUNT(*) FROM news_item").fetchone()[0])
    con.close()
    return {"got": got, "ins": ins, "attempts": attempts}


if __name__ == "__main__":
    main()
