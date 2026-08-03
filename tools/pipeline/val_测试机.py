#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试机 #19 估值回填(yfinance)。亏损 PE=None 不造假。可溯源 dp。"""
import sqlite3, sys, math
from datetime import date
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "tools/pipeline")
import db_writer
import yfinance as yf
conn = db_writer.get_db(); IND = 19; TODAY = date.today().isoformat()
r = conn.execute("SELECT id FROM source WHERE fetch_method='api_yfinance'").fetchone()
YF = r["id"] if r else conn.execute("""INSERT INTO source(title,source_type,publisher,publish_date,quality_tier,value_layer,fetch_method,source_credibility,language,source_subtype) VALUES(?,?,?,?,?,?,?,?,?,?)""",("yfinance 估值/财务 API","三方数据","Yahoo Finance",TODAY,3,"最新数据","api_yfinance","unverified","en","api")).lastrowid
print("yfinance source #", YF)

CUR = {".SS":("亿元","CNY"),".SZ":("亿元","CNY"),".T":("亿日元","JPY"),".TWO":("亿新台币","TWD"),".DE":("亿欧元","EUR")}
COS = [(435,"300604.SZ"),(436,"688200.SS"),(50,"688001.SS"),(439,"301369.SZ"),(553,"688627.SS"),
       (550,"6857.T"),(552,"TER"),(554,"COHU")]
def fnum(v):
    try:
        f=float(v); return None if (math.isinf(f) or math.isnan(f) or f<=0) else f
    except (TypeError,ValueError): return None
ok=0; fail=[]
for cid,tk in COS:
    sfx = "."+tk.split(".")[-1] if "." in tk else "US"
    unit,cur = CUR.get(sfx,("亿美元","USD"))
    try:
        info=yf.Ticker(tk).info
        pe=fnum(info.get("trailingPE")); pb=fnum(info.get("priceToBook")); ps=fnum(info.get("priceToSalesTrailing12Months"))
        mc=info.get("marketCap"); mc_yi=round(mc/1e8,1) if mc else None
        if pe is None and pb is None and ps is None and mc_yi is None:
            fail.append(tk); continue
        conn.execute("UPDATE company SET pe_ttm=?,pb=?,ps_ttm=?,market_cap_value=?,market_cap_unit=?,valuation_as_of=?,valuation_source_id=? WHERE id=?",
                     (pe,pb,ps,mc_yi,unit,TODAY,YF,cid))
        exc=f"yfinance {tk} @{TODAY}: PE={pe} PB={pb} PS={ps} 市值={mc_yi}{unit}"
        for metric,val,u in [("PE_TTM",pe,"倍"),("PB",pb,"倍"),("PS_TTM",ps,"倍"),("总市值",mc_yi,unit)]:
            if val is not None:
                db_writer.write_data_point(conn,industry_id=IND,metric=metric,period="2026Q2",unit=u,source_id=YF,
                    source_excerpt=exc[:200],extraction_method="web_fetch",value_num=val,as_of_date=TODAY,
                    company_id=cid,note="yfinance 估值快照",auto_consensus=False)
        ok+=1; print(f"  {tk}: PE={pe} PB={pb} PS={ps} mc={mc_yi}{unit}")
    except Exception as e:
        fail.append(tk); print(f"  {tk} ERR {str(e)[:60]}")
conn.commit(); print(f"估值入库 {ok}/{len(COS)};失败/无数据: {fail}"); conn.close()
