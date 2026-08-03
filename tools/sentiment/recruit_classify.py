#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""招聘岗位分类(金融视角):从职位标题派生 ① job_function 职能 ② domain 影响领域 ③ location_city 城市。
纯规则(关键词),不臆造:命中则标,不命中留"其它/未分类"。domain 额外并入公司主营行业 tag。
只写 sentiment.db;research.db 只读取公司行业。用法:python recruit_classify.py
"""
from __future__ import annotations
import sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

# 职能(顺序=优先级,先命中先得)
FUNCTIONS = [
    ("研发设计", r"研发|设计|架构|算法|芯片设计|IC|版图|前端|后端|FPGA|DSP|SerDes|仿真|预研|科学家|研究员"),
    ("光/硬件工程", r"光学|光电|硅光|封装|器件|光路|耦合|结构|硬件|电路|PCB|射频|RF|模拟|数字|版图|工艺集成"),
    ("软件/嵌入", r"软件|嵌入式|固件|驱动|系统软件|平台开发|后台|前端开发|全栈|web|测试开发"),
    ("制造工艺", r"工艺|制程|产线|生产|制造|设备工程|良率|MES|SMT|贴片|工程|PE工程|封测|镀膜|光刻|刻蚀|薄膜"),
    ("测试质量", r"测试|质量|品质|QA|QC|可靠性|认证|计量|检验|失效分析|实验"),
    ("供应链采购", r"采购|供应链|物料|计划|仓储|物流|关务|SQE|供应商"),
    ("销售市场", r"销售|市场|商务|售前|售后|FAE|客户经理|渠道|大客户|海外销售|BD|拓展"),
    ("职能管理", r"人力|HR|招聘|财务|会计|审计|法务|行政|IT支持|证券事务|董秘|内控|薪酬|培训|总裁|总监|经理|主管"),
]
# 影响领域(技术/业务方向;一岗可多领域)
DOMAINS = [
    ("光模块", r"光模块|光收发|光通信模块|800G|1\.6T|400G|OSFP|QSFP"),
    ("硅光", r"硅光|silicon photonics|SiPh|光子集成|PIC"),
    ("光芯片", r"光芯片|激光器|EML|DFB|VCSEL|探测器|APD|PD芯片"),
    ("CPO/光引擎", r"CPO|光引擎|共封装|FAU|光纤阵列"),
    ("存储", r"存储|内存|DRAM|NAND|HBM|SSD|闪存|颗粒|主控|eMMC|DDR"),
    ("AI芯片/算力", r"AI芯片|GPU|ASIC|NPU|加速卡|算力|大模型|训练|推理"),
    ("半导体制造", r"晶圆|foundry|光刻|刻蚀|薄膜|封测|先进封装|CMP|外延|MOCVD"),
    ("交换机/网络", r"交换机|数通|InfiniBand|以太网|网络协议|NPU交换"),
    ("PCB/载板", r"PCB|线路板|载板|覆铜板|HDI|封装基板"),
    ("液冷/散热", r"液冷|散热|冷板|浸没|温控|热设计"),
    ("电源/电力", r"电源|供电|UPS|BMS|电力电子|功率"),
    ("汽车电子", r"车载|汽车电子|车规|自动驾驶|智能座舱"),
]
_CITY = re.compile(r"(北京|上海|深圳|广州|杭州|苏州|南京|武汉|成都|西安|无锡|合肥|天津|重庆|东莞|珠海|宁波|厦门|青岛|济南|郑州|长沙|福州|嘉兴|常州|惠州|中山|昆山|石家庄|大连|沈阳|海宁)")


def classify_function(title):
    for name, pat in FUNCTIONS:
        if re.search(pat, title, re.I):
            return name
    return "其它"


def classify_domains(title, company_domains):
    hits = []
    for name, pat in DOMAINS:
        if re.search(pat, title, re.I):
            hits.append(name)
    # 标题没点出领域 → 落到公司主营行业(该公司招人本身影响主业)
    if not hits and company_domains:
        hits = company_domains[:1]
    return ",".join(dict.fromkeys(hits)) if hits else None


def first_city(location):
    if not location:
        return None
    m = _CITY.search(location)
    if m:
        return m.group(1)
    # 海外/英文地点
    if re.search(r"US|GA|CA|Singapore|Malaysia|海外", location or ""):
        return "海外"
    return (location.split(",")[0].split("/")[0].strip() or None)[:10] if location else None


def company_main_domains(rc, company_id):
    """公司主营行业名作为兜底领域(research.db company_industry × industry)。"""
    rows = rc.execute("""SELECT i.name FROM company_industry ci JOIN industry i ON i.id=ci.industry_id
                         WHERE ci.company_id=? ORDER BY ci.revenue_share DESC""", (company_id,)).fetchall()
    return [r[0] for r in rows]


def main():
    con = common.get_senti_db()
    common.assert_senti_only(con)                      # 门C
    rc = common.research_ro_conn()
    now = common.now_iso()
    dom_cache = {}
    rows = con.execute("SELECT id, company_id, title, location FROM recruit_job").fetchall()
    n = 0
    for r in rows:
        cid = r["company_id"]
        if cid not in dom_cache:
            dom_cache[cid] = company_main_domains(rc, cid)
        func = classify_function(r["title"] or "")
        dom = classify_domains(r["title"] or "", dom_cache[cid])
        city = first_city(r["location"])
        con.execute("""UPDATE recruit_job SET job_function=?, domain=?, location_city=?, classified_at=? WHERE id=?""",
                    (func, dom, city, now, r["id"]))
        n += 1
    con.commit()
    rc.close()
    # 报告
    print(f"?? 分类 {n} 岗")
    print("职能分布:")
    for r in con.execute("SELECT job_function, COUNT(*) c FROM recruit_job WHERE status='open' GROUP BY job_function ORDER BY c DESC"):
        print(f"  {r['job_function']}: {r['c']}")
    print("领域分布(Top):")
    for r in con.execute("SELECT domain, COUNT(*) c FROM recruit_job WHERE status='open' AND domain IS NOT NULL GROUP BY domain ORDER BY c DESC LIMIT 12"):
        print(f"  {r['domain']}: {r['c']}")
    con.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
