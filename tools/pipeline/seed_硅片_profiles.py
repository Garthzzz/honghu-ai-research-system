#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""半导体硅片 #18 公司透视 + 产业链 + 估值 tickers 种子。幂等(先删本行业 profile/share/relation 再插)。"""
import sqlite3, sys, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
c = sqlite3.connect("data/research.db"); c.row_factory = sqlite3.Row
c.execute("PRAGMA foreign_keys=ON")
IND = 18
T = "2026-06-28"

# ── 1. tickers(仅确定的;不确定留空,不臆造)──
TICK = {532:"605358.SH", 544:"688432.SH", 549:"688233.SH", 547:"002129.SZ",
        507:"4063.T", 543:"3436.T", 509:"6488.TWO", 539:"WAF.DE", 545:"688584.SH", 546:"003026.SZ"}
for cid, tk in TICK.items():
    c.execute("UPDATE company SET ticker=COALESCE(ticker,?) WHERE id=?", (tk, cid))

# ── 2. industry_relation(grounded 边)──
c.execute("DELETE FROM industry_relation WHERE upstream_id=? OR downstream_id=?", (IND, IND))
REL = [
    # 硅片 → 下游晶圆制造(算力芯片/存储/先进封装),AI/HBM 驱动需求,历史下游议价强势(2026 涨价转均衡)
    (18, 9, "供应", None, None, "downstream_strong", 625, "半导体硅片是先进逻辑/AI 芯片晶圆制造的衬底基材;AI 先进制程驱动 12 吋大硅片需求高增。历史上硅片对晶圆厂下游议价强势(被卡价),2026 涨价周期转相对均衡。"),
    (18, 7, "供应", None, None, "downstream_strong", 624, "HBM/3D NAND 高堆叠驱动 12 吋硅片需求倍增(HBM 用片数为普通 DRAM 数倍);存储扩产是硅片需求核心拉动。"),
    (18, 16, "供应", None, None, "downstream_strong", 625, "先进封装 CoWoS 硅中介层(interposer)消耗 12 吋硅片;Chiplet/2.5D 封装放量带来增量硅片需求。"),
    # 半导体设备 → 硅片(长晶/切磨抛设备供应给硅片厂),扩产期设备紧俏
    (10, 18, "供应", None, None, "balanced", 625, "硅片厂扩产需采购长晶炉/切片/研磨/抛光/外延设备(半导体设备子环节);大硅片扩产周期长(约 18-24 月)。"),
]
for u, d, rt, cs, ds, bp, sid, note in REL:
    c.execute("""INSERT INTO industry_relation(upstream_id,downstream_id,relation_type,cost_share,demand_share,bargaining_power,source_id,note)
                 VALUES(?,?,?,?,?,?,?,?)""", (u, d, rt, cs, ds, bp, sid, note))

# ── 3. company_profile(公司透视三表)──
c.execute("DELETE FROM company_profile WHERE industry_id=?", (IND,))
def series(items):  # items: [(period,value,yoy,unit,src)] — yoy 始终输出(未知=null,模板要求)
    return json.dumps([{"period":p,"value":v,"unit":u,"source_ids":[s],"yoy":y} for p,v,y,u,s in items], ensure_ascii=False)

PROF = [
 # cid, period, glob_rank, glob_share, glob_as_of, cn_rank, techleader, in_g, in_c, gm, products, summary, srcids, rev_series, ni_series
 (507,"2024",1,27.0,"2024",None,0,1,0,None,"300mm 抛光片/外延片/SOI/化合物衬底(全球综合龙头)","全球半导体硅片龙头,份额约 25-27%(2024-2025)",[635,626],None,None),
 (543,"FY2025",2,24.0,"2024",None,0,1,0,None,"300mm/200mm 抛光片、外延片","全球第二,FY2025 营收 4096 亿日元;日本双雄之一",[635,642],series([("FY2025",4096.0,None,"亿日元",642)]),None),
 (509,"2024",3,17.0,"2024",None,0,1,0,None,"300mm/200mm 硅片、SOI(并购 Siltronic 受阻后独立扩产)","台湾环球晶圆(GlobalWafers),全球第三,2025 营收 606 亿新台币",[635,626],series([("2025",606.0,None,"亿新台币",626)]),None),
 (539,"2024",4,13.0,"2024",None,0,1,0,None,"300mm/200mm 硅片(德国,SOI 强)","德国世创(Siltronic),全球第四",[635],None,None),
 (548,"2024",5,13.0,"2024",None,0,1,0,None,"300mm/200mm 硅片(韩国,SK 集团)","韩国 SK Siltron,全球第五(未上市,SK Inc 子公司)",[635],None,None),
 # 中国表 + 技术派
 (510,"2026Q1",None,3.68,"2025",1,1,0,1,None,"300mm 抛光片/外延片/SOI(国产 12 吋龙头,新傲/Okmetic SOI)","中国 12 吋硅片国产龙头(沪硅产业);2025 营收 37.16 亿、净利 -15.08 亿(扩产折旧拖累)",[637,624,626],series([("2025",37.16,None,"亿元",637),("2026Q1",10.84,None,"亿元",637)]),series([("2025",-15.08,None,"亿元",637),("2026Q1",-4.83,None,"亿元",637)])),
 (532,"2026Q1",None,3.68,"2025",2,1,0,1,15.56,"12 吋硅片/8 吋硅片/功率器件/射频(立昂微)","中国第二,12 吋进入放量期;2026Q1 毛利率回升至 15.56%(2025 全年 9.86%)",[628,638,624],series([("2025",35.91,None,"亿元",628),("2026Q1",9.99,None,"亿元",628)]),series([("2025",-1.42,None,"亿元",628),("2026Q1",0.07,None,"亿元",628)])),
 (547,"2025",None,None,None,3,0,0,1,None,"12 吋大硅片(中环领先半导体材料,TCL中环子公司)","中环领先 2025 硅片业务营收约 57 亿元;母公司 TCL中环财务受光伏拖累(口径分离)",[641,626],series([("2024",23.31,None,"亿元",641)]),None),
 (544,"2026Q1",None,None,None,4,1,0,1,37.0,"刻蚀用单晶硅/利基硅片/区熔硅片(有研硅,跨境并购 DGT)","利基/刻蚀硅龙头,盈利能力强(毛利率约 37%);2025 营收 10.05 亿、净利 2.09 亿",[629,639,626],series([("2023",9.6,None,"亿元",629),("2024",9.96,6.2,"亿元",629),("2025",10.05,5.0,"亿元",629)]),series([("2023",2.54,None,"亿元",629),("2024",2.33,-8.3,"亿元",629),("2025",2.09,-10.3,"亿元",629)])),
 (549,"2026Q1",None,None,None,5,0,0,1,44.75,"刻蚀用单晶硅材料/8 吋轻掺抛光片(神工股份)","刻蚀硅材料龙头,毛利率高(44.75%);2025 营收 4.38 亿、净利 1.02 亿",[640],series([("2025",4.38,None,"亿元",640),("2026Q1",1.12,None,"亿元",640)]),series([("2025",1.02,None,"亿元",640),("2026Q1",0.25,None,"亿元",640)])),
 (538,"2025",None,None,None,6,0,0,1,None,"12 吋硅片(西安奕材/奕斯伟材料,大产能扩张)","国产 12 吋新势力,产能扩张激进(规划数十万片/月);未上市/上市进程待确认",[624],None,None),
 (540,"2025",None,None,None,7,0,0,1,None,"12 吋/8 吋硅片(上海超硅)","国产 12 吋新势力之一;未上市",[624],None,None),
]
for (cid,period,gr,gs,gas,cr,tl,ing,inc,gm,prod,summ,srcids,rev,ni) in PROF:
    c.execute("""INSERT INTO company_profile(company_id,industry_id,period,global_rank,global_share,global_share_as_of,
                 china_rank,is_china_tech_leader,in_global_table,in_china_table,gross_margin,main_products,summary,
                 source_ids,revenue_series,net_income_series,last_updated,last_verified_at)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (cid,IND,period,gr,gs,gas,cr,tl,ing,inc,gm,prod,summ,json.dumps(srcids),rev,ni,T,T))

# ── 4. company_sub_market_share(全球全市场份额,承载份额口径)──
c.execute("DELETE FROM company_sub_market_share WHERE industry_id=?", (IND,))
SHARE = [(507,27.0,1),(543,24.0,2),(509,17.0,3),(539,13.0,4),(548,13.0,5)]
for cid,sh,rk in SHARE:
    c.execute("""INSERT INTO company_sub_market_share(company_id,industry_id,sub_market,geo,share,share_as_of,rank,source_ids,source_excerpt_ref,credibility,display_note)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
              (cid,IND,"全球硅片全市场","global",sh,"2024",rk,json.dumps([635]),
               "智研/媒体转引 Omdia 口径 2024:信越27/SUMCO24/环球晶17/世创13/SK13,CR5≈90%","unverified","?? 三方估算孤证(src635),CR5≈90%"))

c.commit()
print("tickers set:", len(TICK))
print("relations:", c.execute("SELECT COUNT(*) FROM industry_relation WHERE upstream_id=? OR downstream_id=?",(IND,IND)).fetchone()[0])
print("profiles:", c.execute("SELECT COUNT(*) FROM company_profile WHERE industry_id=?",(IND,)).fetchone()[0],
      "| global表:", c.execute("SELECT COUNT(*) FROM company_profile WHERE industry_id=? AND in_global_table=1",(IND,)).fetchone()[0],
      "| china表:", c.execute("SELECT COUNT(*) FROM company_profile WHERE industry_id=? AND in_china_table=1",(IND,)).fetchone()[0],
      "| 技术派:", c.execute("SELECT COUNT(*) FROM company_profile WHERE industry_id=? AND is_china_tech_leader=1",(IND,)).fetchone()[0])
print("sub_market_share:", c.execute("SELECT COUNT(*) FROM company_sub_market_share WHERE industry_id=?",(IND,)).fetchone()[0])
c.close()
