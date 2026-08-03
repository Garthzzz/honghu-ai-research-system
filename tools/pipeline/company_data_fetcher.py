#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
company_data_fetcher.py — 公司估值/财务/动向/份额 获取层(Phase3 任务 4)

协议见 CLAUDE_COMPANY_PROFILE.md Section B2 / H1。

设计要点:
- 本兼容脚本能直接调的仍是 Yahoo Finance/yfinance 与 Tushare；当前正式公司刷新已在
  `refresh_company_financial_metrics.py` 接入 Wind 内网 HTTP 主源和 Tushare 补缺。
- 本脚本**不能**直接调的:web_search / web_fetch —— 那是 CC(agent)的工具,不是
  Python 库。因此 API 失败时,fetcher 返回 **need_web_fetch sentinel**(含白名单候选
  URL),由 CC 在 Stage 2 用自己的 web_fetch 工具补齐。这是诚实的架构边界,不假装
  脚本能抓网页。

- 所有 fetch 结果都带 `source_meta`(fetch_method/domain/credibility/fetch_timestamp),
  入库时 source 表字段可直接填全(B5)。

Stage 1(架构)只搭类骨架 + 接口 + API 可用性探测(probe_apis,无网络调用)。
  实际抓三行业数据是 Stage 2。smoke test 只跑 probe_apis()。
"""
from __future__ import annotations

import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 可选依赖:探测可用性,不在 import 期硬失败(demo 可能未装/离线)
try:
    import yfinance as _yf  # type: ignore
    _HAS_YF = True
except Exception:
    _yf = None
    _HAS_YF = False

try:
    from tushare_provider import (
        fetch_daily_basic_latest,
        is_a_share_ticker,
        ts_code_from_ticker,
        tushare_available,
    )
    _HAS_TUSHARE = tushare_available()
except Exception:
    fetch_daily_basic_latest = None
    is_a_share_ticker = lambda ticker: False
    ts_code_from_ticker = lambda ticker: None
    _HAS_TUSHARE = False


# 估值类 fallback 候选域名(全在 B3 白名单)
VALUATION_FALLBACK_URLS = {
    "us":    ["https://finance.yahoo.com/quote/{ticker}", "https://www.macrotrends.net/stocks/charts/{ticker}", "https://stockanalysis.com/stocks/{ticker}/"],
    "kospi": ["https://finance.yahoo.com/quote/{ticker}"],
    "tse":   ["https://finance.yahoo.com/quote/{ticker}"],
    "hk":    ["https://finance.yahoo.com/quote/{ticker}", "https://stockanalysis.com/quote/hkg/{ticker}/"],
    "a_share": ["https://finance.yahoo.com/quote/{ticker}", "https://quote.eastmoney.com/{ticker}.html"],
}
PRIVATE_VAL_FALLBACK_URLS = ["https://www.crunchbase.com/organization/{slug}"]


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _yf_ticker(company: Dict[str, Any]) -> Optional[str]:
    """把 db ticker 映射成 yfinance 可识别 ticker。"""
    t = (company.get("ticker") or "").strip()
    if not t:
        return None
    # .SZ/.SH -> yfinance 用 .SS(上海)/.SZ(深圳)
    if t.endswith(".SH"):
        return t[:-3] + ".SS"
    return t  # .SZ/.HK/.KS/.T/.US/裸美股 yfinance 基本可识别


def _source_meta(fetch_method: str, domain: str, credibility: str,
                 is_primary: int = 0, language: str = "en") -> Dict[str, Any]:
    return {
        "fetch_method": fetch_method,
        "domain": domain,
        "source_credibility": credibility,
        "is_primary_source": is_primary,
        "language": language,
        "fetch_timestamp": _now_iso(),
    }


def _need_web_fetch(reason: str, candidate_urls: List[str],
                    used_for: str) -> Dict[str, Any]:
    """API 失败 / 未上市 时返回的 sentinel,交给 CC 用 web_fetch 补。"""
    return {
        "ok": False,
        "need_web_fetch": True,
        "reason": reason,
        "candidate_urls": candidate_urls,
        "used_for": used_for,
    }


class CompanyDataFetcher:
    """公司数据获取层。上市优先 API,失败/未上市返回 need_web_fetch sentinel。"""

    def __init__(self, live: bool = False):
        # live=False(默认):Stage 1 不发网络请求,fetch_* 直接返回 need_web_fetch
        #                    或 probe-only,确保 smoke test 离线安全。
        # live=True :Stage 2 真正调 API。
        self.live = live

    # ── API 可用性探测(无网络调用)──────────────────
    @staticmethod
    def probe_apis() -> Dict[str, bool]:
        return {"tushare": _HAS_TUSHARE, "yfinance": _HAS_YF}

    # ── 估值 ──────────────────────────────────────────
    def fetch_valuation(self, company: Dict[str, Any]) -> Dict[str, Any]:
        ls = (company.get("listing_status") or "").strip()
        ticker = company.get("ticker")
        name = company.get("name", "")
        listed = ls in ("a_share", "hk", "us", "kospi", "tse", "other_listed")

        if not listed:
            slug = name.lower().replace(" ", "-").replace("/", "-")
            return _need_web_fetch(
                "未上市公司:估值只能 web_fetch 一级市场(标 unverified/未审计)",
                [u.format(slug=slug) for u in PRIVATE_VAL_FALLBACK_URLS],
                "private_valuation",
            )

        if not self.live:
            urls = [u.format(ticker=ticker or "") for u in VALUATION_FALLBACK_URLS.get(ls, [])]
            return _need_web_fetch("Stage1 dry-run(live=False),不发网络请求", urls, "valuation")

        # ── live=True:真正调 API ──
        ts_code = ts_code_from_ticker(ticker) if is_a_share_ticker(ticker) else None
        if _HAS_TUSHARE and ts_code and fetch_daily_basic_latest is not None:
            try:
                snap = fetch_daily_basic_latest(ts_code) or {}
                pe_ttm = snap.get("pe_ttm")
                pb = snap.get("pb")
                ps = snap.get("ps_ttm") or snap.get("ps")
                total_mv = snap.get("total_mv")
                if any(v is not None for v in (pe_ttm, pb, ps, total_mv)):
                    return {
                        "ok": True,
                        "pe_ttm": pe_ttm,
                        "pe_forward": None,
                        "pb": pb,
                        "ps_ttm": ps,
                        "market_cap_value": (float(total_mv) / 10000 if total_mv else None),
                        "valuation_as_of": str(snap.get("trade_date") or _now_iso()[:10]),
                        "source_meta": _source_meta("api_tushare", "tushare.pro", "whitelisted", language="zh"),
                    }
            except Exception as e:
                print(f"[WARN] Tushare 失败 {ts_code}: {e}", file=sys.stderr)

        yt = _yf_ticker(company)
        if _HAS_YF and yt:
            try:
                info = _yf.Ticker(yt).info or {}
                pe_ttm = info.get("trailingPE")
                pe_fwd = info.get("forwardPE")
                pb = info.get("priceToBook")
                mcap = info.get("marketCap")
                if any(v is not None for v in (pe_ttm, pe_fwd, pb, mcap)):
                    return {
                        "ok": True,
                        "pe_ttm": pe_ttm, "pe_forward": pe_fwd, "pb": pb,
                        "market_cap_value": (mcap / 1e8) if mcap else None,  # 转亿(原始货币)
                        "valuation_as_of": _now_iso()[:10],
                        "source_meta": _source_meta("api_yfinance", "finance.yahoo.com", "whitelisted"),
                    }
            except Exception as e:
                print(f"[WARN] yfinance 失败 {yt}: {e}", file=sys.stderr)
        # API 全失败 → web_fetch fallback
        urls = [u.format(ticker=ticker or "") for u in VALUATION_FALLBACK_URLS.get(ls, [])]
        return _need_web_fetch("API 失败/无数据,fallback web_fetch", urls, "valuation")

    # ── 财务三年 ──────────────────────────────────────
    def fetch_financials_3y(self, company: Dict[str, Any]) -> Dict[str, Any]:
        ls = (company.get("listing_status") or "").strip()
        listed = ls in ("a_share", "hk", "us", "kospi", "tse", "other_listed")
        ticker = company.get("ticker")
        if not listed:
            return _need_web_fetch("未上市:财务 web_fetch + 标'未审计自披露'", [], "financials_3y")
        if not self.live:
            return _need_web_fetch("Stage1 dry-run", [], "financials_3y")
        yt = _yf_ticker(company)
        if _HAS_YF and yt:
            try:
                fin = _yf.Ticker(yt).financials  # DataFrame
                if fin is not None and not getattr(fin, "empty", True):
                    return {"ok": True, "raw": "yfinance.financials",
                            "source_meta": _source_meta("api_yfinance", "finance.yahoo.com", "whitelisted")}
            except Exception as e:
                print(f"[WARN] yfinance financials 失败 {yt}: {e}", file=sys.stderr)
        return _need_web_fetch("API 失败,fallback SEC/巨潮/港交所 web_fetch", [], "financials_3y")

    # ── 近期动向(永远需 web_search)──────────────────
    def fetch_recent_events(self, company: Dict[str, Any],
                            window_days: int = 180, major_window_days: int = 365) -> Dict[str, Any]:
        # 研报不写最近 3 个月的事,永远靠 web_search;脚本无法调,返回 sentinel
        return _need_web_fetch(
            f"近期动向需 web_search(普通 {window_days}d / 重大 {major_window_days}d,区分 is_major)",
            [], "recent_events",
        )

    # ── 市场份额(多源印证)──────────────────────────
    def fetch_market_share(self, company: Dict[str, Any], industry: Dict[str, Any]) -> Dict[str, Any]:
        return _need_web_fetch(
            "global/china share 需 web_search 多源印证(普通≥2源/关键≥3源),三方专业源优先",
            [], "market_share",
        )


# ── CLI 自检(只跑 probe,不发网络)──────────────────
if __name__ == "__main__":
    f = CompanyDataFetcher(live=False)
    probe = CompanyDataFetcher.probe_apis()
    print("API 可用性探测(无网络):", probe)
    # dry-run sentinel 演示
    demo_listed = {"name": "Micron", "ticker": "MU", "listing_status": "us"}
    demo_unlisted = {"name": "OpenAI", "ticker": None, "listing_status": "unlisted"}
    print("listed dry-run:", f.fetch_valuation(demo_listed)["need_web_fetch"])
    print("unlisted dry-run:", f.fetch_valuation(demo_unlisted)["reason"][:30], "...")
    print("company_data_fetcher self-test PASS")
