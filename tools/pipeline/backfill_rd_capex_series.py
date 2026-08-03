#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""回填 company_profile 剩余空值:研发费用率/capex/营收序列/净利序列(全行业 ticker'd)。
A股 → Tushare(income/fina_indicator/cashflow)。
港股/海外 → yfinance。真实 API 数据,取不到留空不造假。每值落可溯源 dp。"""
import sys, math, json
from datetime import date
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "tools/pipeline")
import db_writer
import yfinance as yf
from tushare_provider import fetch_cashflow_latest, fetch_fina_indicator_latest, fetch_income_rows, ts_code_from_ticker

conn = db_writer.get_db(); TODAY = date.today().isoformat()
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
YEARS = ["2023","2024","2025"]
SFX_UNIT = {".SH":"亿元",".SZ":"亿元",".BJ":"亿元",".HK":"亿港元",".T":"亿日元",".TWO":"亿新台币",".DE":"亿欧元"}

def fnum(v):
    try:
        f=float(v); return None if (math.isinf(f) or math.isnan(f)) else f
    except (TypeError,ValueError): return None

def tushare_years(tk):
    """返回 {year: (revenue, net_income, rd_exp)}，单位按 Tushare 原始元口径处理。"""
    out = {}
    ts_code = ts_code_from_ticker(tk)
    if not ts_code:
        return out
    try:
        for r in fetch_income_rows(ts_code, years=YEARS):
            yr = str(r.get("end_date") or "")[:4]
            if yr and yr not in out:
                out[yr] = (
                    fnum(r.get("revenue") or r.get("total_revenue")),
                    fnum(r.get("n_income_attr_p") or r.get("n_income")),
                    fnum(r.get("rd_exp")),
                )
    except Exception as e:
        print(f"   [tushare income {tk}] {str(e)[:40]}")
    return out

def series(items, unit, source_id):  # items [(period,val_元)]
    out=[]; prev=None
    for p,v in items:
        if v is None: continue
        yi=round(v/1e8,2); yoy=round((v-prev)/abs(prev)*100,1) if (prev not in (None,0)) else None
        out.append({"period":p,"value":yi,"unit":unit,"source_ids":[source_id],"yoy":yoy}); prev=v
    return out

rows = conn.execute("""SELECT cp.id pid,cp.company_id,cp.industry_id,cp.rd_expense_ratio,cp.capex_value,
    cp.revenue_series,cp.net_income_series,c.name,c.ticker FROM company_profile cp JOIN company c ON c.id=cp.company_id
    WHERE c.ticker IS NOT NULL ORDER BY cp.company_id""").fetchall()
cache={}; st={"rd":0,"capex":0,"rev":0,"ni":0}; dp=set()
for r in rows:
    tk=r["ticker"]; sfx="."+tk.split(".")[-1] if "." in tk else "US"; unit=SFX_UNIT.get(sfx,"亿美元")
    if tk not in cache:
        if sfx in (".SH",".SZ",".BJ"):
            yd=tushare_years(tk)
            rev25,np25,rd25=yd.get("2025",(None,None,None))
            try:
                fi = fetch_fina_indicator_latest(ts_code_from_ticker(tk))
                cf = fetch_cashflow_latest(ts_code_from_ticker(tk))
            except Exception:
                fi = cf = None
            rdr=fnum((fi or {}).get("rd_exp_to_operting_revenue"))
            if rdr is None:
                rdr=round(rd25/rev25*100,2) if (rd25 and rev25) else None
            cap=fnum((cf or {}).get("c_pay_acq_const_fiolta"))
            capx=round(cap/1e8,2) if cap is not None else None
            revs=series([(y,yd.get(y,(None,None,None))[0]) for y in YEARS],unit,TUSHARE)
            nis=series([(y,yd.get(y,(None,None,None))[1]) for y in YEARS],unit,TUSHARE)
            cache[tk]=(rdr,capx,unit,revs,nis,TUSHARE,"tushare")
        else:
            rdr=capx=None; revs=[]; nis=[]
            try:
                t=yf.Ticker(tk); info=t.info
                cap=info.get("capitalExpenditures"); capx=round(abs(cap)/1e8,2) if isinstance(cap,(int,float)) and cap==cap else None
                # R&D ratio + 序列 from financials
                fin=t.income_stmt
                if fin is not None and not fin.empty:
                    cols=list(fin.columns)[:3]
                    def row(name):
                        return fin.loc[name] if name in fin.index else None
                    rev_r=row("Total Revenue"); ni_r=row("Net Income"); rd_r=row("Research And Development")
                    if rev_r is not None and rd_r is not None:
                        try: rdr=round(float(rd_r[cols[0]])/float(rev_r[cols[0]])*100,2)
                        except Exception: rdr=None
                    def yf_series(rr):
                        out=[]; prev=None
                        for cc in reversed(cols):
                            v=fnum(rr[cc]) if rr is not None else None
                            if v is None: continue
                            yi=round(v/1e8,2); yoy=round((v-prev)/abs(prev)*100,1) if prev not in (None,0) else None
                            out.append({"period":str(cc.year),"value":yi,"unit":unit,"source_ids":[YF],"yoy":yoy}); prev=v
                        return out
                    revs=yf_series(rev_r); nis=yf_series(ni_r)
            except Exception as e: print(f"   [yf {tk}] {str(e)[:40]}")
            cache[tk]=(rdr,capx,unit,revs,nis,YF,"yfinance")
    rdr,capx,u,revs,nis,sid,method=cache[tk]
    pid=r["pid"]; ind=r["industry_id"]; cid=r["company_id"]
    sets=[]; vals=[]
    if r["rd_expense_ratio"] is None and rdr is not None: sets+=["rd_expense_ratio=?"]; vals+=[rdr]; st["rd"]+=1
    if r["capex_value"] is None and capx is not None: sets+=["capex_value=?","capex_unit=?"]; vals+=[capx,u]; st["capex"]+=1
    if (not r["revenue_series"] or r["revenue_series"] in ("[]","")) and revs: sets+=["revenue_series=?"]; vals+=[json.dumps(revs,ensure_ascii=False)]; st["rev"]+=1
    if (not r["net_income_series"] or r["net_income_series"] in ("[]","")) and nis: sets+=["net_income_series=?"]; vals+=[json.dumps(nis,ensure_ascii=False)]; st["ni"]+=1
    if sets:
        sets+=["last_verified_at=?"]; vals+=[TODAY]
        conn.execute(f"UPDATE company_profile SET {','.join(sets)} WHERE id=?", vals+[pid])
    exc=f"{method} {tk} @2025年报: 研发费用率={rdr}% capex={capx}{u}"
    for metric,val,uu in [("研发费用率",rdr,"%"),("资本性支出",capx,u)]:
        k=(ind,cid,metric)
        if val is not None and k not in dp:
            dp.add(k)
            try: db_writer.write_data_point(conn,industry_id=ind,metric=metric,period="2025",unit=uu,source_id=sid,
                source_excerpt=exc[:200],extraction_method="web_fetch",value_num=val,as_of_date=TODAY,company_id=cid,
                note=f"{method} 财务回填(2025年报)",auto_consensus=False)
            except Exception as e: print(f"   [dp] {metric} {r['name']} {str(e)[:30]}")
conn.commit()
print(f"\n回填:研发费用率 {st['rd']};capex {st['capex']};营收序列 {st['rev']};净利序列 {st['ni']};dp {len(dp)} 条")
conn.close()
