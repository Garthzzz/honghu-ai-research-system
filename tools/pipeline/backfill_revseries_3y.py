#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""3 年财务序列回填(营收+净利,最少 3 年;上市不足 3 年取全部已披露年报)。可溯源入库。
  - A股 → Tushare income。
  - 港股/美/台/韩/日股 → yfinance income_stmt(Total Revenue/Net Income 多年)。
落地:① company_profile.revenue_series/net_income_series(JSON ≥3 期)② dp 原子(每年每指标,可溯源)。
用法:python backfill_revseries_3y.py [--sleep 0.4] [--limit N]
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
from tushare_provider import fetch_income_rows, ts_code_from_ticker

INDS = (1, 6, 7, 8, 9, 10, 12, 13, 15, 16, 17)
TODAY = date.today().isoformat()
YEARS = ["2022", "2023", "2024", "2025"]   # 抓 4 年:多抓 2022 作 2023 的 YoY 基数;展示前 3 年(2023-2025)各带 YoY
DISPLAY_FROM = "2023"               # 展示序列从此年起(2022 仅作基数,不进展示序列)
SFX_CUR = {".SZ": "CNY", ".SH": "CNY", ".BJ": "CNY", ".HK": "HKD", ".TW": "TWD", ".KS": "KRW", ".T": "JPY"}
CUR_UNIT = {"CNY": "亿元", "USD": "亿美元", "HKD": "亿港元", "KRW": "亿韩元", "JPY": "亿日元", "TWD": "亿新台币"}


def fnum(v):
    try:
        f = float(v); return None if (math.isinf(f) or math.isnan(f)) else f
    except (TypeError, ValueError):
        return None


def yf_tk(t):
    return (t[:-3] + ".SS") if t.endswith(".SH") else t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sleep", type=float, default=0.4); ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    conn = db_writer.get_db()
    ts_src = conn.execute("SELECT id FROM source WHERE fetch_method='api_tushare'").fetchone()
    yf_src = conn.execute("SELECT id FROM source WHERE fetch_method='api_yfinance'").fetchone()
    if ts_src:
        ts_src = ts_src["id"]
    else:
        ts_src = conn.execute("""INSERT INTO source(title,source_type,publisher,publish_date,quality_tier,
            is_forward_looking,value_layer,fetch_method,source_credibility,language,is_primary_source,source_subtype,url)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("Tushare Pro 数据快照", "三方数据", "Tushare Pro", TODAY, 2, 0, "公司专项",
             "api_tushare", "whitelisted", "zh", 0, "financial_database", "https://tushare.pro/")).lastrowid
        conn.commit()
    yf_src = yf_src["id"] if yf_src else None
    print(f"source Tushare #{ts_src} / yfinance #{yf_src}\n")

    rows = conn.execute(f"""SELECT c.id,c.name,c.ticker,MIN(ci.industry_id) pind
        FROM company c JOIN company_industry ci ON ci.company_id=c.id
        WHERE ci.industry_id IN ({','.join('?'*len(INDS))}) AND c.ticker IS NOT NULL AND TRIM(c.ticker)<>''
        GROUP BY c.id ORDER BY c.id""", INDS).fetchall()
    if args.limit:
        rows = rows[:args.limit]
    print(f"公司:{len(rows)}\n")
    stat = {"ok": 0, "partial": 0, "fail": 0, "dp": 0}

    def wr_dp(ind, cid, metric, val, unit, src, ex, period):
        if val is None:
            return
        try:
            did = db_writer.write_data_point(conn, industry_id=ind, metric=metric, period=period, unit=unit,
                source_id=src, source_excerpt=ex[:200], extraction_method="web_fetch",
                value_num=float(val), as_of_date=period, sentiment="不适用", company_id=cid,
                note="API 年报序列,可溯源", auto_consensus=False)
            conn.execute("UPDATE industry_data_point SET last_verified_at=? WHERE id=?", (TODAY, did))
            stat["dp"] += 1
        except Exception as e:
            print(f"    [dp skip] {metric} {period}: {e}", file=sys.stderr)

    for r in rows:
        tk = r["ticker"].strip(); cid = r["id"]; ind = r["pind"]
        sfx = next((s for s in SFX_CUR if tk.endswith(s)), None)
        cur = SFX_CUR.get(sfx, "USD"); unit = CUR_UNIT.get(cur, "亿(" + cur + ")")
        use_tushare = sfx in (".SZ", ".SH", ".BJ")
        rev_ser, ni_ser = [], []
        try:
            if use_tushare:
                ts_code = ts_code_from_ticker(tk)
                src = ts_src; smark = "Tushare"
                income_rows = fetch_income_rows(ts_code, years=YEARS) if ts_code else []
                by_year = {}
                for row in income_rows:
                    yr = str(row.get("end_date") or "")[:4]
                    if yr and yr not in by_year:
                        by_year[yr] = row
                for yr in YEARS:
                    d = by_year.get(yr)
                    if not d:
                        continue
                    rev = fnum(d.get("revenue") or d.get("total_revenue"))
                    ni = fnum(d.get("n_income_attr_p") or d.get("n_income"))
                    rev_yi = round(rev/1e8, 2) if rev is not None else None
                    ni_yi = round(ni/1e8, 2) if ni is not None else None
                    if rev_yi is not None:
                        rev_ser.append({"period": yr, "value": rev_yi, "unit": unit, "source_ids": [src]})
                        wr_dp(ind, cid, "营业收入_年报", rev_yi, unit, src, f"Tushare income {tk} FY{yr} revenue={rev_yi}{unit}", yr)
                    if ni_yi is not None:
                        ni_ser.append({"period": yr, "value": ni_yi, "unit": unit, "source_ids": [src]})
                        wr_dp(ind, cid, "净利润_年报", ni_yi, unit, src, f"Tushare income {tk} FY{yr} net_profit={ni_yi}{unit}", yr)
                    if args.sleep:
                        time.sleep(args.sleep)
            else:
                src = yf_src; smark = "yf"
                fin = yf.Ticker(yf_tk(tk)).income_stmt
                if fin is not None and not fin.empty:
                    cols = list(fin.columns)[:4]   # 最近 4 个财年(多取 1 年作最早展示年的 YoY 基数)
                    for c in cols:
                        yr = str(c)[:4]
                        rev = fnum(fin.loc["Total Revenue", c]) if "Total Revenue" in fin.index else None
                        ni = fnum(fin.loc["Net Income", c]) if "Net Income" in fin.index else None
                        rev_yi = round(rev/1e8, 2) if rev is not None else None
                        ni_yi = round(ni/1e8, 2) if ni is not None else None
                        if rev_yi is not None:
                            rev_ser.append({"period": yr, "value": rev_yi, "unit": unit, "source_ids": [src]})
                            wr_dp(ind, cid, "营业收入_年报", rev_yi, unit, src, f"yfinance income_stmt {tk} FY{yr} TotalRevenue={rev_yi}{unit}", yr)
                        if ni_yi is not None:
                            ni_ser.append({"period": yr, "value": ni_yi, "unit": unit, "source_ids": [src]})
                            wr_dp(ind, cid, "净利润_年报", ni_yi, unit, src, f"yfinance income_stmt {tk} FY{yr} NetIncome={ni_yi}{unit}", yr)
            if not rev_ser:
                stat["fail"] += 1; print(f"  {r['name']} ({tk}) 无年报序列")
            else:
                def finalize(ser):
                    """按年排序 → 算 YoY(本期 vs 上期,直接公式)→ 切到展示起始年(基数年仅算 YoY 不展示)。"""
                    ser.sort(key=lambda x: x["period"])
                    by = {x["period"]: x["value"] for x in ser}
                    out = []
                    for x in ser:
                        if x["period"] < DISPLAY_FROM:
                            continue  # 基数年(2022)不进展示序列
                        py = str(int(x["period"]) - 1)
                        prev = by.get(py)
                        x["yoy"] = round((x["value"] - prev) / prev * 100, 1) if (prev not in (None, 0)) else None
                        out.append(x)
                    return out
                rev_disp = finalize(rev_ser); ni_disp = finalize(ni_ser)
                conn.execute("""UPDATE company_profile SET revenue_series=?, net_income_series=?,
                    financials_as_of=?, last_verified_at=? WHERE company_id=?""",
                    (json.dumps(rev_disp, ensure_ascii=False), json.dumps(ni_disp, ensure_ascii=False), TODAY, TODAY, cid))
                tag = "≥3年" if len(rev_disp) >= 3 else f"{len(rev_disp)}年(年报可得不足3年)"
                if len(rev_disp) >= 3: stat["ok"] += 1
                else: stat["partial"] += 1
                disp = [(s["period"], s["value"], (str(s["yoy"]) + "%") if s.get("yoy") is not None else "—") for s in rev_disp]
                print(f"  [{smark}] {r['name']:<12}{tk:<11} 营收(YoY) {disp} {tag}")
        except Exception as e:
            stat["fail"] += 1; print(f"  {r['name']} ({tk}): {type(e).__name__}:{str(e)[:50]}")
        if args.sleep:
            time.sleep(args.sleep)
    conn.commit()
    print(f"\n=== 完成:≥3年 {stat['ok']} | 不足3年(上市新) {stat['partial']} | 失败 {stat['fail']} | dp原子 {stat['dp']} ===")
    conn.close()


if __name__ == "__main__":
    main()
