#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""补海外公司 capex/研发费用率/OCF(yfinance 财报 .cashflow/.income_stmt,比 .info 全)。真实数据,取不到留空。"""
import sys, math
from datetime import date
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "tools/pipeline")
import db_writer
import yfinance as yf
conn = db_writer.get_db(); TODAY = date.today().isoformat()
YF = conn.execute("SELECT id FROM source WHERE fetch_method='api_yfinance'").fetchone()["id"]
SFX_UNIT = {".T":"亿日元",".TWO":"亿新台币",".DE":"亿欧元"}
FOREIGN = [(6857.0,"6857.T"),(0,"TER"),(0,"COHU"),(0,"4063.T"),(0,"3436.T"),(0,"6488.TWO"),(0,"WAF.DE")]
# 用 ticker 找 company_id
def cid_of(tk):
    r=conn.execute("SELECT id FROM company WHERE ticker=?",(tk,)).fetchone(); return r["id"] if r else None
def fnum(v):
    try: f=float(v); return None if (math.isinf(f) or math.isnan(f)) else f
    except (TypeError,ValueError): return None
def row_latest(df,*names):
    if df is None or df.empty: return None
    for nm in names:
        if nm in df.index:
            for col in df.columns[:3]:
                v=fnum(df.loc[nm,col])
                if v is not None: return v
    return None

st={"capex":0,"rd":0,"ocf":0}
for _,tk in FOREIGN:
    cid=cid_of(tk)
    if not cid: print(f"  {tk} 无 company"); continue
    sfx="."+tk.split(".")[-1] if "." in tk else "US"; unit=SFX_UNIT.get(sfx,"亿美元")
    try:
        t=yf.Ticker(tk); cf=t.cashflow; ins=t.income_stmt
        capex=row_latest(cf,"Capital Expenditure","Capital Expenditures")
        ocf=row_latest(cf,"Operating Cash Flow","Total Cash From Operating Activities")
        rd=row_latest(ins,"Research And Development","Research Development")
        rev=row_latest(ins,"Total Revenue","Operating Revenue")
        capx=round(abs(capex)/1e8,2) if capex is not None else None
        ocf_yi=round(ocf/1e8,2) if ocf is not None else None
        rdr=round(rd/rev*100,2) if (rd and rev) else None
        print(f"  {tk}: capex={capx}{unit} 研发率={rdr}% OCF={ocf_yi}{unit}")
        for ind in [r["industry_id"] for r in conn.execute("SELECT industry_id FROM company_profile WHERE company_id=?",(cid,))]:
            sets=[]; vals=[]
            cur=conn.execute("SELECT capex_value,rd_expense_ratio,operating_cash_flow FROM company_profile WHERE company_id=? AND industry_id=?",(cid,ind)).fetchone()
            if cur["capex_value"] is None and capx is not None: sets+=["capex_value=?","capex_unit=?"]; vals+=[capx,unit]; st["capex"]+=1
            if cur["rd_expense_ratio"] is None and rdr is not None: sets+=["rd_expense_ratio=?"]; vals+=[rdr]; st["rd"]+=1
            if cur["operating_cash_flow"] is None and ocf_yi is not None: sets+=["operating_cash_flow=?","ocf_unit=?"]; vals+=[ocf_yi,unit]; st["ocf"]+=1
            if sets:
                sets+=["last_verified_at=?"]; vals+=[TODAY]
                conn.execute(f"UPDATE company_profile SET {','.join(sets)} WHERE company_id=? AND industry_id=?",vals+[cid,ind])
            for metric,val,u in [("资本性支出",capx,unit),("研发费用率",rdr,"%"),("经营活动现金流量净额",ocf_yi,unit)]:
                if val is not None and not conn.execute("SELECT 1 FROM industry_data_point WHERE industry_id=? AND company_id=? AND metric=?",(ind,cid,metric)).fetchone():
                    try: db_writer.write_data_point(conn,industry_id=ind,metric=metric,period="2025",unit=u,source_id=YF,
                        source_excerpt=f"yfinance {tk} 财报: capex={capx}{unit} 研发率={rdr}% OCF={ocf_yi}{unit}"[:200],
                        extraction_method="web_fetch",value_num=val,as_of_date=TODAY,company_id=cid,note="yfinance 财报回填",auto_consensus=False)
                    except Exception: pass
    except Exception as e: print(f"  {tk} ERR {str(e)[:50]}")
conn.commit(); print(f"\n补:capex {st['capex']};研发率 {st['rd']};OCF {st['ocf']}")
conn.close()
