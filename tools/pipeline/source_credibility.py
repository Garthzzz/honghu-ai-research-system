#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
source_credibility.py — 信息源三层名单分类 + 灰名单上报(Phase3 任务 5 / 第五道防线)

协议见 CLAUDE_COMPANY_PROFILE.md Section B3 / D。

- classify_source(domain) -> 'whitelisted' | 'unverified' | 'blacklisted'
    白/黑名单 hardcode 自 B3(domain 子串匹配);白黑之外 = 灰名单 'unverified'。
- report_gray_source(...) -> 写 source_review_queue(去重 by domain)
    + append cache/new_sources_for_review_<ts>.md。

?? 重要(user 澄清 #3):灰名单"不可作为唯一来源"是 **UI/审计页 warning**,
  不在写入层拒绝。本模块只做分类 + 上报,不拒绝任何写入。
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "research.db"
CACHE_DIR = ROOT / "cache"


# ── B3 第一层:白名单(domain 子串)──────────────────
WHITELIST = [
    # 一手监管
    "sec.gov", "hkexnews.hk", "cninfo.com.cn", "sse.com.cn", "szse.cn",
    # 二手权威英文
    "bloomberg.com", "reuters.com", "ft.com", "wsj.com", "nikkei.com", "theinformation.com",
    # 二手权威中文
    "caixin.com", "yicai.com", "stcn.com",
    # 财务数据库；Wind 通过项目内网 HTTP 代理接入，公开来源定位使用 wind.com.cn
    "wind.com.cn", "finance.yahoo.com", "tushare.pro", "macrotrends.net", "stockanalysis.com",
    # 三方专业
    "dramexchange.com", "trendforce.com", "counterpointresearch.com", "lightcounting.com",
    "semianalysis.com", "idc.com", "gartner.com", "yole.fr", "yolegroup.com", "omdia.com",
    "wsts.org", "techinsights.com",
    # AI 专属
    "epoch.ai", "artificialanalysis.ai", "scale.com", "openrouter.ai",
    "radar.cloudflare.com", "cloudflare.com",
    # 国内行业
    "questmobile.com.cn",
]
# ── 2c-E:user 指定 6 大权威源已全部在白名单(TrendForce/LightCounting/IDC/Reuters/Bloomberg/Cloudflare Radar/QuestMobile)
# 灰名单但允许入库(转载,标 unverified):eetasia.com / blocksandfiles.com / techpowerup.com / aicpb.com / The Information 摘要
# 公司 IR 子域名前缀(investors.* / ir.*)单独判断

# ── B3 第二层:黑名单(domain 子串)──────────────────
BLACKLIST = [
    "reddit.com", "stackexchange.com", "stackoverflow.com",
    "zhihu.com", "xueqiu.com", "guba.eastmoney.com", "weibo.com",
    "xiaohongshu.com", "douyin.com", "twitter.com", "x.com",
    "summary.io",
]


def _extract_domain(url_or_domain: str) -> str:
    """从 url 或裸 domain 提取归一化 domain(去 www.,小写)。"""
    s = (url_or_domain or "").strip().lower()
    if not s:
        return ""
    if "://" in s:
        s = urlparse(s).netloc or s
    else:
        # 可能是 'example.com/path' 形式
        s = s.split("/")[0]
    if s.startswith("www."):
        s = s[4:]
    return s


def _is_company_ir(domain: str) -> bool:
    """公司官方 IR 子域名:investors.* / ir.*(B3 白名单一手 IR)。"""
    return domain.startswith("investors.") or domain.startswith("ir.") \
        or ".investors." in domain or domain.startswith("investor.")


def classify_source(url_or_domain: str) -> str:
    """返回 'whitelisted' / 'unverified' / 'blacklisted'。
    黑名单优先(更具体),再白名单,皆不中 = 灰名单 'unverified'。
    """
    domain = _extract_domain(url_or_domain)
    if not domain:
        return "unverified"
    for b in BLACKLIST:
        if b in domain:
            return "blacklisted"
    if _is_company_ir(domain):
        return "whitelisted"
    for w in WHITELIST:
        if w in domain:
            return "whitelisted"
    return "unverified"


def get_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def report_gray_source(
    domain: str,
    sample_url: str = "",
    used_for_field: str = "",
    cc_judgment: str = "",
    suggested_action: str = "keep_gray",
    industry_context: Optional[str] = None,
    company_context: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> bool:
    """灰名单源上报:写 source_review_queue(去重 by domain)+ append cache md。
    返回 True=新上报,False=已存在(去重命中)。
    不拒绝任何写入(D2 是 UI warning,不是写入拒绝)。
    """
    dom = _extract_domain(domain)
    if not dom:
        return False
    if suggested_action not in ("whitelist", "blacklist", "keep_gray"):
        suggested_action = "keep_gray"

    own = conn is None
    if own:
        conn = get_db()
    try:
        cur = conn.execute("SELECT id FROM source_review_queue WHERE domain=?", (dom,))
        if cur.fetchone():
            return False  # 去重:已上报
        conn.execute("""
            INSERT INTO source_review_queue
                (domain, sample_url, used_for_field, cc_judgment, suggested_action,
                 industry_context, company_context)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (dom, sample_url, used_for_field, cc_judgment, suggested_action,
              industry_context, company_context))
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()

    # append cache md(供 user review)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d")
        md = CACHE_DIR / f"new_sources_for_review_{ts}.md"
        new_file = not md.exists()
        with md.open("a", encoding="utf-8") as f:
            if new_file:
                f.write(f"# 灰名单 source 待 user 决策 — {ts}\n\n")
                f.write("| domain | sample_url | used_for | cc_judgment | suggested | context |\n")
                f.write("|---|---|---|---|---|---|\n")
            ctx = " / ".join([x for x in (industry_context, company_context) if x])
            f.write(f"| {dom} | {sample_url} | {used_for_field} | {cc_judgment} | "
                    f"{suggested_action} | {ctx} |\n")
    except Exception as e:
        print(f"[WARN] 写 cache md 失败:{e}", file=sys.stderr)
    return True


# ── CLI 自检 ────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        ("https://www.bloomberg.com/news/x", "whitelisted"),
        ("macrotrends.net/stocks/MU", "whitelisted"),
        ("https://investors.micron.com/", "whitelisted"),
        ("https://www.reddit.com/r/stocks", "blacklisted"),
        ("xueqiu.com/123", "blacklisted"),
        ("https://some-random-blog.cn/post", "unverified"),
    ]
    ok = True
    for url, exp in tests:
        got = classify_source(url)
        flag = "OK" if got == exp else "FAIL"
        if got != exp:
            ok = False
        print(f"  [{flag}] {url} -> {got} (期望 {exp})")
    print("source_credibility self-test", "PASS" if ok else "FAIL")
