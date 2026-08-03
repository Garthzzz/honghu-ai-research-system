#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stage 2c-F 任务 C6:估值/盈利预测数据 fetch(yfinance,实时 API,绝不编造)

- 仅对已上市且有 ticker 的公司抓数;未上市(OpenAI/Anthropic/长鑫/长江等)跳过,留空。
- 新增字段:roe / roa / ev_ebitda / ps_ttm / peg / 盈利预测(eps/营收 +1y/+2y)+ forecast_as_of_date。
- 同时刷新已有 pe_ttm / pe_forward / pb / market_cap_value / valuation_as_of。
- cell ^src:每家公司复用其已存在的「公司 · Yahoo Finance (yfinance)」source 行
  (source.fetch_method='api_yfinance'),写入 company.valuation_source_id / forecast_source_id。
- 抓不到的字段保持 NULL,不凑近似(反 slop)。
- dividend_yield 因 yfinance 版本口径不一(易量级错),本轮不写,留 NULL。

用法:python tools/pipeline/stage2c_f_fetch_valuation.py [--limit N] [--only id,id]
"""
from __future__ import annotations
import sqlite3, sys, io, argparse, json
from pathlib import Path
from datetime import date

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

DB = Path(__file__).resolve().parent.parent.parent / "data" / "research.db"
TODAY = date.today().isoformat()

import yfinance as yf


def yf_ticker(ticker: str) -> str:
    t = (ticker or "").strip()
    if not t:
        return ""
    if t.endswith(".SH"):
        return t[:-3] + ".SS"
    if t.endswith(".HK"):                       # 09888.HK -> 9888.HK ; 00100.HK -> 0100.HK
        num = t[:-3].lstrip("0")
        num = num.rjust(4, "0")
        return num + ".HK"
    return t


def pct(v):
    """fraction -> percent, rounded 2dp; None-safe; reject絶対値>50 (already-pct or junk)."""
    if v is None:
        return None
    try:
        f = float(v)
    except Exception:
        return None
    # yfinance returns ROE/ROA/margins as fraction (0.74). Guard magnitude.
    if abs(f) > 10:        # 已是百分数或异常,不二次×100
        return round(f, 2)
    return round(f * 100, 2)


def num(v, ndp=2):
    if v is None:
        return None
    try:
        return round(float(v), ndp)
    except Exception:
        return None


def build_yf_source_map(cur):
    """company_id -> 该公司 yfinance source id(用已存在的 source 行,标题以公司名开头)。"""
    comps = cur.execute("SELECT id, name FROM company").fetchall()
    srcs = cur.execute(
        "SELECT id, title FROM source WHERE fetch_method='api_yfinance' ORDER BY id"
    ).fetchall()
    m = {}
    for cid, cname in comps:
        if not cname:
            continue
        for sid, stitle in srcs:
            if stitle and stitle.startswith(cname + " ·"):
                m[cid] = sid
                break
    return m


def fetch_one(ytk: str):
    """返回 dict 或 None。"""
    try:
        tk = yf.Ticker(ytk)
        info = tk.info or {}
    except Exception as e:
        print(f"   [WARN] info 失败 {ytk}: {e}", file=sys.stderr)
        return None
    if not info or info.get("trailingPE") is None and info.get("marketCap") is None and info.get("priceToBook") is None:
        # 基本无数据
        return {"_empty": True, "info_keys": len(info)}
    out = {
        "pe_ttm":   num(info.get("trailingPE")),
        "pe_forward": num(info.get("forwardPE")),
        "pb":       num(info.get("priceToBook")),
        "market_cap_value": (num(info.get("marketCap") / 1e8, 2) if info.get("marketCap") else None),
        "roe":      pct(info.get("returnOnEquity")),
        "roa":      pct(info.get("returnOnAssets")),
        "ev_ebitda": num(info.get("enterpriseToEbitda")),
        "ps_ttm":   num(info.get("priceToSalesTrailing12Months")),
        "peg":      num(info.get("trailingPegRatio") if info.get("trailingPegRatio") is not None else info.get("pegRatio")),
        "currency": info.get("financialCurrency") or info.get("currency"),
    }
    # 盈利预测(+1y / +2y),newer yfinance: earnings_estimate / revenue_estimate DataFrame
    try:
        ee = getattr(tk, "earnings_estimate", None)
        if ee is not None and not ee.empty:
            if "+1y" in ee.index and "avg" in ee.columns:
                out["forecast_eps_year1"] = num(ee.loc["+1y", "avg"])
            if "+2y" in ee.index and "avg" in ee.columns:
                out["forecast_eps_year2"] = num(ee.loc["+2y", "avg"])
    except Exception:
        pass
    try:
        re_ = getattr(tk, "revenue_estimate", None)
        if re_ is not None and not re_.empty:
            if "+1y" in re_.index and "avg" in re_.columns and re_.loc["+1y", "avg"]:
                out["forecast_revenue_year1"] = num(float(re_.loc["+1y", "avg"]) / 1e8)  # -> 亿
            if "+2y" in re_.index and "avg" in re_.columns and re_.loc["+2y", "avg"]:
                out["forecast_revenue_year2"] = num(float(re_.loc["+2y", "avg"]) / 1e8)
    except Exception:
        pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", type=str, default="")
    args = ap.parse_args()

    con = sqlite3.connect(str(DB)); cur = con.cursor()
    src_map = build_yf_source_map(cur)

    only = {int(x) for x in args.only.split(",") if x.strip()} if args.only else None
    rows = cur.execute("""
        SELECT DISTINCT c.id, c.name, c.ticker, c.listing_status
        FROM company c JOIN company_profile cp ON cp.company_id=c.id
        WHERE c.ticker IS NOT NULL AND TRIM(c.ticker)<>''
          AND c.listing_status IN ('a_share','hk','us','kospi','tse','other_listed')
        ORDER BY c.id
    """).fetchall()
    if only:
        rows = [r for r in rows if r[0] in only]
    if args.limit:
        rows = rows[: args.limit]

    print(f"目标公司(上市+有ticker+有画像):{len(rows)}")
    upd_fields = ["pe_ttm","pe_forward","pb","market_cap_value","roe","roa",
                  "ev_ebitda","ps_ttm","peg","forecast_eps_year1","forecast_eps_year2",
                  "forecast_revenue_year1","forecast_revenue_year2"]
    ok = 0; empty = 0; fail = 0
    summary = []
    for cid, name, ticker, ls in rows:
        ytk = yf_ticker(ticker)
        d = fetch_one(ytk)
        if d is None:
            fail += 1; summary.append((name, ticker, "FAIL")); continue
        if d.get("_empty"):
            empty += 1; summary.append((name, ticker, f"EMPTY(keys={d.get('info_keys')})")); continue
        sets = []
        params = []
        for f in upd_fields:
            if d.get(f) is not None:
                sets.append(f"{f}=?"); params.append(d[f])
        # 时点 + cell ^src 来源
        sets.append("valuation_as_of=?"); params.append(TODAY)
        vsid = src_map.get(cid)
        if vsid:
            sets.append("valuation_source_id=?"); params.append(vsid)
        if any(d.get(k) is not None for k in ("forecast_eps_year1","forecast_revenue_year1")):
            sets.append("forecast_as_of_date=?"); params.append(TODAY)
            if vsid:
                sets.append("forecast_source_id=?"); params.append(vsid)
        if d.get("forecast_revenue_year1") is not None:
            sets.append("forecast_revenue_unit=?"); params.append(f"亿{d.get('currency') or ''}")
        params.append(cid)
        cur.execute(f"UPDATE company SET {', '.join(sets)} WHERE id=?", params)
        ok += 1
        got = [f for f in ("roe","roa","ev_ebitda","ps_ttm","forecast_eps_year1","forecast_revenue_year1") if d.get(f) is not None]
        summary.append((name, ticker, "OK pe=%s pb=%s roe=%s roa=%s +%s" % (
            d.get("pe_ttm"), d.get("pb"), d.get("roe"), d.get("roa"), ",".join(got) or "无预测")))
    con.commit()
    print(f"\n成功 {ok} / 空数据 {empty} / 失败 {fail}")
    for nm, tk, st in summary:
        print("  %-14s %-10s %s" % ((nm or "")[:14], tk, st))
    con.close()
    print("\nFETCH DONE")


if __name__ == "__main__":
    main()
