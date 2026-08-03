#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
E2 事件 AI 前瞻(本期 = CC session 生成版,沿用 2c-G 散文范式)

?? 反 slop:
  - 散文内嵌 ^src:N,数字均来自 db 已有 idp(存储/大模型 consensus dp,2c-G 已验证存在)
  - 校验:解析 ^src → source 全存在(dangling → halt 不写);无买卖建议词
  - 写入 event.ai_preview_narrative + ai_preview_source_ids + ai_preview_generated_at
  - 仅对高价值 upcoming 事件(L1 财报 + 近期大会)生成;其余留 pending 占位
接口:CC 版硬编码;APIEventPreviewer(token 到位)接口一致(扫 idp/news → prompt → 校验入库)。
"""
from __future__ import annotations
import sqlite3, sys, io, re, json
from pathlib import Path
from datetime import datetime

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

DB = Path(__file__).resolve().parent.parent.parent / "data" / "research.db"
NOW = datetime.now().isoformat(timespec="seconds")
SRC_RE = re.compile(r"\^src:(\d+)")
FORBIDDEN = ["买入", "卖出", "目标价", "看多", "看空", "增持", "减持", "推荐买", "强烈推荐", "buy rating", "price target"]

# CC session 生成(grounded in db idp;每个数字带 ^src:N);key=event_id
PREVIEWS = {
    16: (  # 美光 2026Q2 财报(存储 L1)
        "未来一个月美光 2026Q2 财报(预估披露 2026-06-24)是存储板块关键观测点。市场关注 AI 驱动的存储上行周期"
        "在其业绩的兑现度:DRAM 现货价一致预期 2026Q1 同比上涨约 90%(主流口径,高者达 100%)^src:86 ^src:69,"
        "由 HBM 挤占传统 DRAM 产能与 AI 服务器需求共同推动——AI 服务器单机存储用量约为普通服务器 5 倍^src:77。"
        "美光为 DRAM CR3(全球约 90–97%)^src:69 ^src:53 成员,其 HBM4 已于 FY26Q1 量产供货^src:248,关注点在 HBM "
        "出货占比、DRAM ASP 与后续指引;整体存储 2026 TAM 一致预期约 2148 亿美元^src:46。需留意存储强周期属性与"
        "供给端扩产节奏对持续性的影响。"),
    14: (  # 三星 2026Q3 财报(存储 L1)
        "三星 2026Q3 财报(预估披露 2026-07-29)看点在 DRAM 领头之争与 HBM4 进展。4Q25 三星已重夺 DRAM 第一(与 "
        "SK海力士咬合约 32%)、1Q26 整体利润亦反超^src:247;HBM4 时代三星抢先量产并通过 NVIDIA 双档认证^src:251。"
        "市场关注其 HBM4 放量节奏、DRAM/NAND 价格(2026Q1 现货同比约 90%)^src:86 ^src:69 对盈利的拉动,以及 AI "
        "服务器需求(单机存储用量约 5 倍)^src:77 的延续性。三星作为存储全品类龙头,其指引对全行业供给与价格预期"
        "具指标意义。"),
    15: (  # SK海力士 2026Q3 财报(存储 L1)
        "SK海力士 2026Q3 财报(预估披露 2026-07-29)核心看点是 HBM 主导地位的延续。SK海力士在 HBM 仍居领先,且拿下 "
        "NVIDIA Vera Rubin HBM4 约 70% 订单^src:251;市场关注其 HBM4 量产爬坡、DRAM 价格(2026Q1 现货同比约 90%)"
        "^src:86 ^src:69 与营收/利润率指引。AI 服务器存储用量约普通服务器 5 倍^src:77 支撑结构性需求。关注点亦包括 "
        "HBM 占 DRAM 产能比例及其对传统 DRAM 供给的挤占。"),
    4: (   # WWDC 2026(大模型)
        "苹果 WWDC 2026(2026-06-08)是大模型板块的端侧 AI 观测窗口。市场关注苹果在设备端大模型、助手升级与开发者 "
        "AI 框架的进展。宏观背景:全球 AI 市场 2026 TAM 一致预期中值约 1.05 万亿美元(支出/收入/累计口径差异较大)"
        "^src:131,行业 CAGR 一致预期约 58–84%^src:127,相关厂商营收同比仍高增^src:125。端侧 AI 的推进可能影响"
        "推理需求结构与端云协同;需留意口径差异与商业化兑现节奏,信息以官方主题演讲为准。"),
}


def main():
    con = sqlite3.connect(str(DB)); cur = con.cursor()
    real = {r[0] for r in cur.execute("SELECT id FROM source")}
    written = 0
    for eid, text in PREVIEWS.items():
        ev = cur.execute("SELECT id, title FROM event WHERE id=?", (eid,)).fetchone()
        if not ev:
            print(f"  ?? event #{eid} 不存在,跳过"); continue
        refs = sorted(set(int(x) for x in SRC_RE.findall(text)))
        dangling = [r for r in refs if r not in real]
        if not refs:
            print(f"  ?? #{eid}: 无 ^src,拒绝"); continue
        if dangling:
            print(f"  ?? #{eid}: dangling {dangling},halt 不写"); continue
        bad = [w for w in FORBIDDEN if w in text]
        if bad:
            print(f"  ?? #{eid}: 含买卖建议词 {bad},halt 不写"); continue
        cur.execute("""UPDATE event SET ai_preview_narrative=?, ai_preview_source_ids=?,
                       ai_preview_generated_at=?, ai_preview_overridden_by_human=0 WHERE id=?""",
                    (text, json.dumps(refs), NOW, eid))
        written += 1
        print(f"  ?? #{eid} {ev[1]}: {len(text)} 字,{len(refs)} 源 {refs},无买卖建议词")
    con.commit(); con.close()
    print(f"\n写入事件前瞻:{written}。EVENT PREVIEW (CC) DONE")


if __name__ == "__main__":
    main()
