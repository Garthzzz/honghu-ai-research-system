#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""回填 company_profile 的 净利率/毛利率/经营现金流(全行业 ticker'd 公司)。
A股 → Tushare(fina_indicator/cashflow)。
港股/海外(.T/.TWO/.DE/US)→ yfinance(grossMargins/profitMargins/operatingCashflow)。
规则:operating_cash_flow/net_margin 填空;gross_margin 全行业填空,**仅 18/19 覆盖更新**(纠正研报口径误差)。
亏损 → 负值如实写(margins 可负;不造假)。每值落可溯源 dp。"""
import sys, math, argparse
from datetime import date
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "tools/pipeline")
import db_writer
import yfinance as yf
from tushare_provider import fetch_cashflow_latest, fetch_fina_indicator_latest, ts_code_from_ticker

conn = db_writer.get_db(); TODAY = date.today().isoformat(); RPT = "20251231"
row = conn.execute("SELECT id FROM source WHERE fetch_method='api_tushare'").fetchone()
if row:
    TUSHARE = row["id"]
else:
    TUSHARE = conn.execute("""INSERT INTO source(title,source_type,publisher,publish_date,quality_tier,
        is_forward_looking,value_layer,fetch_method,source_credibility,language,is_primary_source,source_subtype,url)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("Tushare Pro 数据快照", "三方数据", "Tushare Pro", TODAY, 2, 0, "公司专项",
         "api_tushare", "whitelisted", "zh", 0, "financial_database", "https://tushare.pro/")).lastrowid
    conn.commit()
YF = conn.execute("SELECT id FROM source WHERE fetch_method='api_yfinance'").fetchone()["id"]
print(f"Tushare src #{TUSHARE} / yfinance src #{YF}")
OVERWRITE_GM_INDS = {18, 19}   # 仅这两行业覆盖更新 gross_margin(其余只填空)
SFX_UNIT = {".SH":"亿元",".SZ":"亿元",".BJ":"亿元",".HK":"亿港元",".T":"亿日元",".TWO":"亿新台币",".DE":"亿欧元"}

def fnum(v, allow_neg=True):
    try:
        f=float(v)
        if math.isinf(f) or math.isnan(f): return None
        return f if allow_neg else (f if f>0 else None)
    except (TypeError,ValueError): return None

def fetch(ticker):
    """→ (gm%, nm%, ocf_亿, ocf_unit, src_id, method)"""
    sfx = "."+ticker.split(".")[-1] if "." in ticker else "US"
    if sfx in (".SH",".SZ",".BJ"):   # A股 → Tushare
        unit = "亿元"
        try:
            ts_code = ts_code_from_ticker(ticker)
            fi = fetch_fina_indicator_latest(ts_code) if ts_code else None
            cf = fetch_cashflow_latest(ts_code) if ts_code else None
            gm=fnum((fi or {}).get("grossprofit_margin")); nm=fnum((fi or {}).get("netprofit_margin"))
            ocf=fnum((cf or {}).get("n_cashflow_act"))
            return gm, nm, (round(ocf/1e8,2) if ocf is not None else None), unit, TUSHARE, "tushare"
        except Exception as e:
            print(f"  [tushare err] {ticker}: {str(e)[:50]}"); return (None,None,None,unit,TUSHARE,"tushare")
    else:   # 海外 → yfinance
        unit = SFX_UNIT.get(sfx, "亿美元")
        try:
            info=yf.Ticker(ticker).info
            gm=info.get("grossMargins"); nm=info.get("profitMargins"); ocf=info.get("operatingCashflow")
            gm=round(gm*100,2) if isinstance(gm,(int,float)) and gm==gm else None
            nm=round(nm*100,2) if isinstance(nm,(int,float)) and nm==nm else None
            ocf=round(ocf/1e8,2) if isinstance(ocf,(int,float)) and ocf==ocf else None
            return gm, nm, ocf, unit, YF, "yfinance"
        except Exception as e:
            print(f"  [yf err] {ticker}: {str(e)[:50]}"); return (None,None,None,unit,YF,"yfinance")

# 所有有 ticker 的 company_profile 行
rows = conn.execute("""SELECT cp.id pid, cp.company_id, cp.industry_id, cp.gross_margin, cp.net_margin,
    cp.operating_cash_flow, c.name, c.ticker FROM company_profile cp JOIN company c ON c.id=cp.company_id
    WHERE c.ticker IS NOT NULL ORDER BY cp.company_id""").fetchall()
cache={}; stats={"gm":0,"nm":0,"ocf":0,"gm_fix":0}; dp_done=set()
for r in rows:
    tk=r["ticker"]
    if tk not in cache: cache[tk]=fetch(tk)
    gm,nm,ocf,unit,sid,method=cache[tk]
    pid=r["pid"]; ind=r["industry_id"]; cid=r["company_id"]
    # gross_margin:全行业填空;18/19 覆盖
    new_gm=None
    if gm is not None:
        if r["gross_margin"] is None: new_gm=gm; stats["gm"]+=1
        elif ind in OVERWRITE_GM_INDS and abs((r["gross_margin"] or 0)-gm)>3:
            new_gm=gm; stats["gm_fix"]+=1; print(f"  [GM 纠正] {r['name']}#{ind}: {r['gross_margin']:.1f}→{gm:.1f}")
    sets=[]; vals=[]
    if new_gm is not None: sets.append("gross_margin=?"); vals.append(new_gm)
    if r["net_margin"] is None and nm is not None: sets.append("net_margin=?"); vals.append(nm); stats["nm"]+=1
    if r["operating_cash_flow"] is None and ocf is not None:
        sets.append("operating_cash_flow=?"); vals.append(ocf); sets.append("ocf_unit=?"); vals.append(unit); stats["ocf"]+=1
    if sets:
        sets.append("financials_as_of=?"); vals.append("2025"); sets.append("last_verified_at=?"); vals.append(TODAY)
        conn.execute(f"UPDATE company_profile SET {','.join(sets)} WHERE id=?", vals+[pid])
    # 可溯源 dp(每 industry×company×metric 一条)
    exc=f"{method} {tk} @2025年报: 毛利率={gm} 净利率={nm} 经营现金流={ocf}{unit}"
    for metric,val,u in [("毛利率",gm,"%"),("净利率",nm,"%"),("经营活动现金流量净额",ocf,unit)]:
        key=(ind,cid,metric)
        if val is not None and key not in dp_done:
            dp_done.add(key)
            try:
                db_writer.write_data_point(conn,industry_id=ind,metric=metric,period="2025",unit=u,source_id=sid,
                    source_excerpt=exc[:200],extraction_method="web_fetch",value_num=val,as_of_date=TODAY,
                    company_id=cid,note=f"{method} 财务回填(2025年报)",auto_consensus=False)
            except Exception as e: print(f"  [dp err] {metric} {r['name']}: {str(e)[:40]}")
conn.commit()
print(f"\n回填:gross_margin 填空 {stats['gm']} / 18-19覆盖纠正 {stats['gm_fix']};net_margin {stats['nm']};经营现金流 {stats['ocf']};dp {len(dp_done)} 条")
conn.close()
