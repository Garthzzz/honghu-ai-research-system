#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""历史市值换算/定向补数工具。

FX 取自 yfinance，脚本自身仍使用 Tushare 做定向补数；当前统一公司刷新已经改为
A 股 Wind 内网 HTTP 主源、Tushare 逐字段补缺，不应把本旧工具当现行数据策略。
"""
import sys, math, json
from datetime import date
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "tools/pipeline")
import db_writer
import yfinance as yf
from tushare_provider import (
    fetch_cashflow_latest,
    fetch_daily_basic_latest,
    fetch_fina_indicator_latest,
    fetch_income_rows,
    get_or_create_tushare_source,
)
conn = db_writer.get_db(); TODAY = date.today().isoformat()
TUSHARE = get_or_create_tushare_source(conn, title="Tushare Pro 数据快照")
conn.commit()

# ── FX(单位货币 → CNY)──
USDCNY=6.8175; JPYCNY=4.211/100; EURCNY=7.7564; HKDCNY=0.86919
try:
    usd=yf.Ticker("USDCNY=X").fast_info.get("last_price") or yf.Ticker("USDCNY=X").info.get("regularMarketPrice")
    if usd: USDCNY=float(usd)
except Exception: pass
try:
    jpy=yf.Ticker("JPYCNY=X").fast_info.get("last_price") or yf.Ticker("JPYCNY=X").info.get("regularMarketPrice")
    if jpy: JPYCNY=float(jpy)
except Exception: pass
try:
    eur=yf.Ticker("EURCNY=X").fast_info.get("last_price") or yf.Ticker("EURCNY=X").info.get("regularMarketPrice")
    if eur: EURCNY=float(eur)
except Exception: pass
try:
    hkd=yf.Ticker("HKDCNY=X").fast_info.get("last_price") or yf.Ticker("HKDCNY=X").info.get("regularMarketPrice")
    if hkd: HKDCNY=float(hkd)
except Exception: pass
try:
    twd=yf.Ticker("TWDCNY=X").info.get("regularMarketPrice") or yf.Ticker("TWDCNY=X").fast_info.get("last_price")
    TWDCNY=float(twd)
except Exception: TWDCNY=USDCNY/32.0   # 兜底,若取不到用 USDTWD≈32 近似(标注)
print(f"FX→CNY: USD={USDCNY} JPY={JPYCNY} EUR={EURCNY} HKD={HKDCNY} TWD={TWDCNY:.4f}")
FX={"亿元":1.0,"亿人民币":1.0,"亿日元":JPYCNY,"亿欧元":EURCNY,"亿港元":HKDCNY,"亿美元":USDCNY,"亿新台币":TWDCNY}

# ── 新增列(幂等)──
cols={r[1] for r in conn.execute("PRAGMA table_info(company)")}
if "market_cap_cny" not in cols: conn.execute("ALTER TABLE company ADD COLUMN market_cap_cny REAL")
if "market_cap_usd" not in cols: conn.execute("ALTER TABLE company ADD COLUMN market_cap_usd REAL")
if "market_cap_cny_as_of" not in cols: conn.execute("ALTER TABLE company ADD COLUMN market_cap_cny_as_of TEXT")

# ── 补 西安奕材 ticker ──
conn.execute("UPDATE company SET ticker='688783.SH' WHERE id=538 AND (ticker IS NULL OR ticker='')")
conn.commit()

# ── 全公司市值换算 ──
n=0; miss=[]
for r in conn.execute("SELECT id,name,market_cap_value,market_cap_unit FROM company WHERE market_cap_value IS NOT NULL").fetchall():
    u=(r["market_cap_unit"] or "亿元").strip()
    f=FX.get(u)
    if f is None: miss.append((r["name"],u)); continue
    cny=round(r["market_cap_value"]*f,1); usd=round(cny/USDCNY,1)
    conn.execute("UPDATE company SET market_cap_cny=?,market_cap_usd=?,market_cap_cny_as_of=? WHERE id=?",(cny,usd,TODAY,r["id"]))
    n+=1
conn.commit()
print(f"市值换算 {n} 家;未知单位 {miss[:5]}")

# ── 西安奕材(688783.SH)财务回填(Tushare)──
def fnum(v):
    try: f=float(v); return None if (math.isinf(f) or math.isnan(f)) else f
    except (TypeError,ValueError): return None
tk="688783.SH"
try:
    fi=fetch_fina_indicator_latest(tk) or {}
    cf=fetch_cashflow_latest(tk) or {}
    inc_rows=fetch_income_rows(tk)
    inc=inc_rows[0] if inc_rows else {}
    val=fetch_daily_basic_latest(tk) or {}
    gm=fnum(fi.get("grossprofit_margin")); nm=fnum(fi.get("netprofit_margin"))
    ocf=fnum(cf.get("n_cashflow_act"))
    rev=fnum(inc.get("revenue") or inc.get("total_revenue"))
    np_=fnum(inc.get("n_income_attr_p") or inc.get("n_income"))
    rd=fnum(inc.get("rd_exp"))
    cap=fnum(cf.get("c_pay_acq_const_fiolta"))
    pe=fnum(val.get("pe_ttm")); pb=fnum(val.get("pb")); ps=fnum(val.get("ps_ttm") or val.get("ps"))
    total_mv=fnum(val.get("total_mv"))
    mc=total_mv*10000 if total_mv is not None else None
    rdr=round(rd/rev*100,2) if (rd and rev) else None; capx=round(cap/1e8,2) if cap else None
    mc_yi=round(mc/1e8,1) if mc else None
    print(f"西安奕材: 毛{gm} 净{nm} OCF{round(ocf/1e8,2) if ocf else None}亿 研发率{rdr} capex{capx} 市值{mc_yi}亿 PE{pe} PB{pb} PS{ps}")
    # 更新 company + profile(id=538,industry 18)
    if mc_yi: conn.execute("UPDATE company SET pe_ttm=?,pb=?,ps_ttm=?,market_cap_value=?,market_cap_unit='亿元',market_cap_cny=?,market_cap_usd=?,valuation_as_of=?,valuation_source_id=? WHERE id=538",
        (None if (pe and pe<=0) else pe,pb,ps,mc_yi,mc_yi,round(mc_yi/USDCNY,1),TODAY,TUSHARE))
    sets={"gross_margin":gm,"net_margin":nm,"operating_cash_flow":round(ocf/1e8,2) if ocf else None,"rd_expense_ratio":rdr,"capex_value":capx,"capex_unit":"亿元","financials_as_of":"2025","last_verified_at":TODAY}
    keys=[k for k,v in sets.items() if v is not None]
    conn.execute(f"UPDATE company_profile SET {','.join(k+'=?' for k in keys)} WHERE company_id=538 AND industry_id=18",[sets[k] for k in keys])
    conn.commit(); print("西安奕材 profile 回填完成")
except Exception as e: print("西安奕材 Tushare ERR",str(e)[:60])
conn.close()
