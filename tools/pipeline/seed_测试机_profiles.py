#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试机 #19 公司透视 + 产业链 + tickers 种子。幂等。"""
import sqlite3, sys, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
c = sqlite3.connect("data/research.db"); c.row_factory = sqlite3.Row
c.execute("PRAGMA foreign_keys=ON")
IND = 19; T = "2026-06-28"

c.execute("UPDATE industry SET core_dynamic=? WHERE id=?", (
 "AI/HBM 驱动测试时长翻倍 + 去美化/去日化国产替代;全球爱德万+泰瑞达双寡头 CR2≈80%(爱德万 SoC 测试份额约 66%);国产长川/华峰测控量价齐升、存储测试第二曲线,SoC/存储测试机国产化率仍低;ATE 机型生命周期长(可卖 20 年)、客户黏性高、吃封测/晶圆厂 capex 导数", IND))

# 1. tickers
TICK = {435:"300604.SZ",436:"688200.SH",50:"688001.SH",439:"301369.SZ",553:"688627.SH",
        550:"6857.T",552:"TER",554:"COHU"}
for cid,tk in TICK.items():
    c.execute("UPDATE company SET ticker=COALESCE(ticker,?) WHERE id=?",(tk,cid))

# 2. industry_relation(测试机=后道测试设备,供给给封测/芯片;AI/HBM 驱动)
c.execute("DELETE FROM industry_relation WHERE upstream_id=? OR downstream_id=?", (IND,IND))
REL=[
 (19,9,"供应",None,None,"balanced",644,"测试机(ATE)对 AI/算力芯片做 CP/FT 测试;AI 大芯片管脚多、测试时长翻倍,带动测试机量价齐升。ATE 机型生命周期长、客户黏性高,但需求是封测/晶圆厂 capex 导数(传导弹性约 0.5-0.6)。"),
 (19,7,"供应",None,None,"balanced",644,"存储测试机对 DRAM/HBM/NAND 做测试;HBM 的 KGSD 已知良堆叠、TSV、动态老化新增测试环节,驱动存储测试机需求(长川/精智达存储第二曲线)。"),
 (19,16,"供应",None,None,"balanced",646,"先进封装/Chiplet 带来 SLT 系统级测试、2.5D/3D 封装测试新增插入点,扩大测试机需求。"),
]
for u,d,rt,cs,ds,bp,sid,note in REL:
    c.execute("""INSERT INTO industry_relation(upstream_id,downstream_id,relation_type,cost_share,demand_share,bargaining_power,source_id,note)
                 VALUES(?,?,?,?,?,?,?,?)""",(u,d,rt,cs,ds,bp,sid,note))

# 3. company_profile
c.execute("DELETE FROM company_profile WHERE industry_id=?", (IND,))
def series(items):  # (period,value,yoy,unit,src) — yoy 始终输出
    return json.dumps([{"period":p,"value":v,"unit":u,"source_ids":[s],"yoy":y} for p,v,y,u,s in items], ensure_ascii=False)

PROF=[
 # cid,period,gr,gs,gas,cr,tl,ing,inc,gm,products,summary,srcids,rev,ni
 (550,"FY2025",1,65.0,"FY2025",None,0,1,0,64.34,"SoC 测试机 V93000/T2000、存储测试机(爱德万 Advantest)","全球 ATE 龙头,SoC 测试份额约 66%、整体约 65%;FY2025 营收 11286 亿日元(+44.7%)、净利 3754 亿日元",[644,650,656,670],series([("FY2024",7797.07,None,"亿日元",655),("FY2025",11286.1,44.7,"亿日元",656)]),series([("FY2025",3753.53,None,"亿日元",656)])),
 (552,"2025",2,28.0,"2025",None,0,1,0,58.2,"SoC 测试机 UltraFLEX/UltraFLEXplus、系统级测试(泰瑞达 Teradyne)","全球 ATE 第二,份额约 28-30%;2025 营收 31.9 亿美元(+13%)、毛利率 58.2%",[645,657,670],series([("2025",31.9,None,"亿美元",657)]),series([("2025",5.54,None,"亿美元",657)])),
 (554,"2024",3,None,None,None,0,1,0,None,"测试接口/分选/系统级测试(科休 Cohu)","全球后道测试设备厂商;2024 营收 4.02 亿美元",[673],series([("2024",4.018,None,"亿美元",673)]),None),
 # 中国表 + 技术派
 (435,"2026Q1",None,None,None,1,1,0,1,35.39,"SoC/模拟/功率测试机 D9000、分选机、存储测试探针(长川科技)","国产 ATE 龙头,平台化(测试机+分选机);2025 营收 52.92 亿(+45%)、净利 13.31 亿(+190%);存储测试第二曲线",[644,651,658,660],series([("2023",18.0,None,"亿元",649),("2024",36.0,100.0,"亿元",651),("2025",52.92,47.0,"亿元",658)]),series([("2025",13.31,190.0,"亿元",658)])),
 (436,"2026Q1",None,None,None,2,1,0,1,73.81,"模拟/数模混合测试机 STS8300/STS8600(华峰测控)","国产模拟测试机龙头,毛利率高(73.81%);2025 营收 13.46 亿、净利 5.38 亿;高端 SoC 主频突破 800MHz",[647,659,660,674],series([("2023",7.0,None,"亿元",649),("2024",9.05,29.3,"亿元",647),("2025",13.46,48.7,"亿元",659)]),series([("2025",5.38,None,"亿元",659)])),
 (553,"2025",None,None,None,3,1,0,1,None,"存储测试机/HBM 测试、显示测试(精智达)","国产存储/HBM 测试新锐;2025 营收 11.28 亿、净利 0.65 亿",[649,661],series([("2023",6.5,None,"亿元",649),("2025",11.28,None,"亿元",661)]),series([("2025",0.65,None,"亿元",661)])),
 (50,"2026Q1",None,None,None,4,0,0,1,None,"平板显示检测/半导体测试(华兴源创)","显示检测起家,拓展半导体测试;2025 营收 22.4 亿、净利 0.80 亿",[662],series([("2025",22.4,None,"亿元",662)]),series([("2025",0.80,None,"亿元",662)])),
 (439,"2025",None,None,None,5,0,0,1,None,"分选机/功率测试机(联动科技)","国产分选机/功率测试;规模较小",[663],None,None),
]
for (cid,period,gr,gs,gas,cr,tl,ing,inc,gm,prod,summ,srcids,rev,ni) in PROF:
    c.execute("""INSERT INTO company_profile(company_id,industry_id,period,global_rank,global_share,global_share_as_of,
                 china_rank,is_china_tech_leader,in_global_table,in_china_table,gross_margin,main_products,summary,
                 source_ids,revenue_series,net_income_series,last_updated,last_verified_at)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (cid,IND,period,gr,gs,gas,cr,tl,ing,inc,gm,prod,summ,json.dumps(srcids),rev,ni,T,T))

# 4. company_sub_market_share(全球 ATE 双寡头)
c.execute("DELETE FROM company_sub_market_share WHERE industry_id=?", (IND,))
SHARE=[(550,65.0,1,"爱德万 SoC 测试份额约 66%、整体约 65%(FY2025)^src644/650"),
       (552,28.0,2,"泰瑞达份额约 28-30%(2024-2025)^src645/670")]
for cid,sh,rk,ref in SHARE:
    c.execute("""INSERT INTO company_sub_market_share(company_id,industry_id,sub_market,geo,share,share_as_of,rank,source_ids,source_excerpt_ref,credibility,display_note)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
              (cid,IND,"全球ATE全市场","global",sh,"2025",rk,json.dumps([644,645,670]),ref,"unverified","?? 双寡头 CR2≈80%;份额口径多源(收入 vs 装机量)有分歧"))

c.commit()
print("tickers:",len(TICK),"| relations:",c.execute("SELECT COUNT(*) FROM industry_relation WHERE upstream_id=? OR downstream_id=?",(IND,IND)).fetchone()[0])
print("profiles:",c.execute("SELECT COUNT(*) FROM company_profile WHERE industry_id=?",(IND,)).fetchone()[0],
      "| global:",c.execute("SELECT COUNT(*) FROM company_profile WHERE industry_id=? AND in_global_table=1",(IND,)).fetchone()[0],
      "| china:",c.execute("SELECT COUNT(*) FROM company_profile WHERE industry_id=? AND in_china_table=1",(IND,)).fetchone()[0],
      "| 技术派:",c.execute("SELECT COUNT(*) FROM company_profile WHERE industry_id=? AND is_china_tech_leader=1",(IND,)).fetchone()[0])
print("sub_market:",c.execute("SELECT COUNT(*) FROM company_sub_market_share WHERE industry_id=?",(IND,)).fetchone()[0])
c.close()
