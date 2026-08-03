#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""第二轮:财务+估值数值回填,**全部可溯源入库(dp 原子)**。
本文件是历史 Tushare/yfinance 定向回填实现，不代表当前数据源策略。当前正式公司
刷新为 A 股 Wind 内网 HTTP 主源、Tushare 逐字段补缺，其他市场 yfinance，并走
``refresh_company_financial_metrics.py`` 的 fetch/apply manifest。
每个数值三处落地:① company 估值列 ② company_profile 财务 ③ **industry_data_point dp 原子**
  (metric/period/unit/source_id/source_excerpt/extraction_method='web_fetch' + last_verified_at,
   可在 viewer source modal 溯源到具体查询与取值)。
用法:python backfill_financials_traceable.py [--sleep 0.5] [--limit N]
"""
from __future__ import annotations
import sys, time, json, argparse, math
from datetime import date
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
import db_writer
import yfinance as yf
from tushare_provider import (
    fetch_daily_basic_latest,
    fetch_fina_indicator_latest,
    fetch_income_rows,
    ts_code_from_ticker,
)

INDS = (1, 6, 7, 8, 9, 10, 12, 13, 15, 16, 17)
TODAY = date.today().isoformat()
CUR_UNIT = {"CNY": "亿元", "USD": "亿美元", "HKD": "亿港元", "KRW": "亿韩元", "JPY": "亿日元", "TWD": "亿新台币"}
# ticker 后缀 → 货币(用于市值/营收单位)
SFX_CUR = {".SZ": "CNY", ".SH": "CNY", ".BJ": "CNY", ".HK": "HKD", ".TW": "TWD", ".KS": "KRW", ".T": "JPY"}


def fnum(v):
    try:
        f = float(v)
        return None if (math.isinf(f) or math.isnan(f)) else f
    except (TypeError, ValueError):
        return None


def yf_tk(t):
    return (t[:-3] + ".SS") if t.endswith(".SH") else t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sleep", type=float, default=0.5)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    conn = db_writer.get_db()

    # ── 注册/复用 source ──
    def get_src(title, fetch_method, tier, cred, url):
        r = conn.execute("SELECT id FROM source WHERE title=? AND fetch_method=?", (title, fetch_method)).fetchone()
        if r:
            return r["id"]
        return conn.execute("""INSERT INTO source(title,source_type,publisher,publish_date,quality_tier,
            is_forward_looking,value_layer,fetch_method,source_credibility,language,is_primary_source,source_subtype,url)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (title, "三方数据", "Tushare Pro" if "Tushare" in title else "Yahoo Finance", TODAY, tier, 0,
             "公司专项", fetch_method, cred, "zh" if "Tushare" in title else "en", 0, "financial_database", url)).lastrowid
    ts_src = get_src("Tushare Pro 数据快照", "api_tushare", 2, "whitelisted", "https://tushare.pro/")
    yf_src = get_src("yfinance 估值快照", "api_yfinance", 3, "unverified", "https://finance.yahoo.com/")
    conn.commit()
    print(f"source:Tushare #{ts_src}(tier2) yfinance #{yf_src}(tier3) | as_of={TODAY}\n")

    # 公司列表(有 ticker)+ 主行业(min industry_id,dp 原子归属)
    rows = conn.execute(f"""
        SELECT c.id, c.name, c.ticker, MIN(ci.industry_id) AS pind
        FROM company c JOIN company_industry ci ON ci.company_id=c.id
        WHERE ci.industry_id IN ({','.join('?'*len(INDS))}) AND c.ticker IS NOT NULL AND TRIM(c.ticker)<>''
        GROUP BY c.id ORDER BY c.id""", INDS).fetchall()
    if args.limit:
        rows = rows[:args.limit]
    print(f"待回填公司:{len(rows)}\n")

    stat = {"tushare_ok": 0, "yf_ok": 0, "fail": 0, "dp": 0}
    crosscheck = []

    def write_dp(ind, cid, metric, val, unit, src, excerpt, period):
        """写一条可溯源 dp 原子 + 置 last_verified_at。"""
        if val is None:
            return
        try:
            did = db_writer.write_data_point(
                conn, industry_id=ind, metric=metric, period=period, unit=unit,
                source_id=src, source_excerpt=excerpt[:200], extraction_method="web_fetch",
                value_num=float(val), as_of_date=TODAY,
                sentiment="不适用", company_id=cid, note="API 取数,可溯源", auto_consensus=False)
            conn.execute("UPDATE industry_data_point SET last_verified_at=? WHERE id=?", (TODAY, did))
            stat["dp"] += 1
        except Exception as e:
            print(f"    [dp skip] {metric}: {e}", file=sys.stderr)

    def upd_profile(cid, gm, nm, rev_val, rev_unit, ni_val, src):
        """更新该公司所有 company_profile 行的财务字段(财务与行业无关)。"""
        rev_series = json.dumps([{"period": "TTM", "value": rev_val, "unit": rev_unit, "source_ids": [src]}], ensure_ascii=False) if rev_val is not None else None
        ni_series = json.dumps([{"period": "TTM", "value": ni_val, "unit": rev_unit, "source_ids": [src]}], ensure_ascii=False) if ni_val is not None else None
        conn.execute("""UPDATE company_profile SET gross_margin=COALESCE(?,gross_margin),
            net_margin=COALESCE(?,net_margin), revenue_series=COALESCE(?,revenue_series),
            net_income_series=COALESCE(?,net_income_series), financials_as_of=?, last_verified_at=? WHERE company_id=?""",
            (gm, nm, rev_series, ni_series, WIND_DATE, TODAY, cid))

    for r in rows:
        tk = r["ticker"].strip(); cid = r["id"]; ind = r["pind"]
        sfx = next((s for s in SFX_CUR if tk.endswith(s)), None)
        cur = SFX_CUR.get(sfx, "USD")
        use_tushare = sfx in (".SZ", ".SH", ".BJ")
        try:
            if use_tushare:
                ts_code = ts_code_from_ticker(tk)
                if not ts_code:
                    raise RuntimeError("无法转换 Tushare ts_code")
                db = fetch_daily_basic_latest(ts_code) or {}
                fi = fetch_fina_indicator_latest(ts_code) or {}
                inc_rows = fetch_income_rows(ts_code)
                inc = inc_rows[0] if inc_rows else {}
                pe = fnum(db.get("pe_ttm")); pb = fnum(db.get("pb")); ps = fnum(db.get("ps_ttm") or db.get("ps"))
                total_mv = fnum(db.get("total_mv")); mc = total_mv * 10000 if total_mv is not None else None
                rev = fnum(inc.get("revenue") or inc.get("total_revenue"))
                ni = fnum(inc.get("n_income_attr_p") or inc.get("n_income"))
                gm = fnum(fi.get("grossprofit_margin")); nmg = fnum(fi.get("netprofit_margin"))
                src = ts_src; smark = "Tushare"
            else:
                info = yf.Ticker(yf_tk(tk)).info or {}
                pe = fnum(info.get("trailingPE")); pb = fnum(info.get("priceToBook")); ps = fnum(info.get("priceToSalesTrailing12Months"))
                mc = fnum(info.get("marketCap")); rev = fnum(info.get("totalRevenue")); ni = fnum(info.get("netIncomeToCommon"))
                gmf = fnum(info.get("grossMargins")); nmf = fnum(info.get("profitMargins"))
                gm = gmf*100 if gmf is not None else None; nmg = nmf*100 if nmf is not None else None
                cur = (info.get("currency") or cur).upper()
                src = yf_src; smark = "yf"
            # 清洗:ADR/无意义
            if pe is not None and pe <= 0: pe = None
            if pb is not None and pb > 100: pb = None
            mc_yi = round(mc/1e8, 2) if mc else None
            rev_yi = round(rev/1e8, 2) if rev else None
            ni_yi = round(ni/1e8, 2) if ni else None
            unit_cur = CUR_UNIT.get(cur, "亿(" + cur + ")")
            if pe is None and pb is None and ps is None and mc is None and rev is None:
                stat["fail"] += 1; print(f"  {r['name']} ({tk}) 无数据");
                if args.sleep: time.sleep(args.sleep)
                continue
            # ① company 估值列
            conn.execute("""UPDATE company SET pe_ttm=?, pb=?, ps_ttm=?, market_cap_value=?, market_cap_unit=?,
                valuation_as_of=?, valuation_source_id=? WHERE id=?""",
                (pe, pb, ps, mc_yi, unit_cur if mc_yi else None, TODAY, src, cid))
            # ② company_profile 财务
            upd_profile(cid, gm, nmg, rev_yi, unit_cur, ni_yi, src)
            # ③ dp 原子(可溯源)
            ex = f"{smark} {tk} @{TODAY}"
            write_dp(ind, cid, "市盈率PE_TTM", pe, "倍", src, f"{ex} pe_ttm={pe}", TODAY)
            write_dp(ind, cid, "市净率PB", pb, "倍", src, f"{ex} pb={pb}", TODAY)
            write_dp(ind, cid, "市销率PS_TTM", ps, "倍", src, f"{ex} ps_ttm={ps}", TODAY)
            write_dp(ind, cid, "总市值", mc_yi, unit_cur, src, f"{ex} mkt_cap={mc_yi}{unit_cur}", TODAY)
            write_dp(ind, cid, "营业收入_TTM", rev_yi, unit_cur, src, f"{ex} or_ttm={rev_yi}{unit_cur}", "TTM_2026-06")
            write_dp(ind, cid, "净利润_TTM", ni_yi, unit_cur, src, f"{ex} netprofit_ttm={ni_yi}{unit_cur}", "TTM_2026-06")
            write_dp(ind, cid, "销售毛利率_TTM", gm, "%", src, f"{ex} grossmargin={gm}%", "TTM_2026-06")
            write_dp(ind, cid, "销售净利率_TTM", nmg, "%", src, f"{ex} netmargin={nmg}%", "TTM_2026-06")
            stat["tushare_ok" if use_tushare else "yf_ok"] += 1
            print(f"  [{smark}] {r['name']:<12}{tk:<11} PE={pe} PB={pb} 营收={rev_yi}{unit_cur} 毛利率={gm} 净利率={nmg}")
        except Exception as e:
            stat["fail"] += 1; print(f"  {r['name']} ({tk}): {type(e).__name__}:{str(e)[:50]}")
        if args.sleep:
            time.sleep(args.sleep)
    conn.commit()
    print(f"\n=== 完成:Tushare {stat['tushare_ok']} | yfinance {stat['yf_ok']} | 失败 {stat['fail']} | dp原子 {stat['dp']} ===")
    conn.close()


if __name__ == "__main__":
    main()
