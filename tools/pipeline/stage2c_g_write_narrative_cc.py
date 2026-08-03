#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stage 2c-G 任务 4(本轮 = CC session 生成版)

按 user 约定:本轮 AI 综合分析【散文式一致预期】由 CC(当前 session)作为 LLM 直接生成,
不调 Anthropic API、不读 ANTHROPIC_API_KEY。内容硬编码于此(CC 已在 session 内基于
db dp 生成),脚本负责:解析 ^src → 校验 source 真实存在(dangling 即拒绝该行)→
写入 industry_thesis.consensus_narrative + consensus_source_ids + consensus_generated_at。

?? 反 slop:每个数字均来自 db 已有 dp(cache/_smoke 已 dump 核对),引用 ^src:N 的 N
  全部在 source 表存在;不覆盖 consensus_overridden_by_human=1 的人工版本。
后续 ANTHROPIC_API_KEY 到位后,改用 stage2c_g_gen_consensus_narrative.py(API 版)。
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

# CC session 生成的散文(每段 ~250-310 字,3 段;数字均来自 db dp,带 ^src:N)
NARRATIVES = {
    1: (
        "未来 6–24 个月,光模块景气由 AI 数据中心资本开支驱动延续:北美头部云厂商 2026 年 "
        "CapEx 合计一致预期约 5700–6020 亿美元^src:25 ^src:15,直接拉动数通光模块需求,行业出货量 "
        "2024 年已同比增约 45–50%^src:6 ^src:12,机构对 2030 年的全行业五年 CAGR 一致预期约 17–20%"
        "^src:14 ^src:26。主线是速率升级——1.6T 模块 2027 年单价一致预期约 550–599 美元/只^src:32 ^src:27,"
        "量价齐升支撑头部厂商盈利。竞争格局上中国厂商已占全球前十中的 7 席^src:29 ^src:20,头部公司全球份额"
        "维持高位^src:22。产业链价值持续向上游与设备环节集中——上游(光芯片/光器件)成本占比约 50%^src:29,"
        "国产光芯片仍是关键瓶颈。风险方面,CPO/LPO 技术路线切换节奏与云厂商 CapEx 波动是主要不确定性。"
    ),
    7: (
        "未来 6–24 个月,存储进入 AI 驱动的超级上行周期:DRAM 现货价一致预期 2026Q1 同比大幅上涨,"
        "主流口径约 90%、高者达 100%^src:86 ^src:69,涨价由 HBM 挤占传统 DRAM 产能与 AI 服务器需求共同推动"
        "——AI 服务器单机存储用量约为普通服务器的 5 倍^src:77。格局维持极致寡头,DRAM CR3 约 90–97%"
        "^src:69 ^src:52 ^src:53(三星/SK海力士/美光三足鼎立);NAND 市场规模 2024 年约 656 亿美元^src:53 ^src:56,"
        "企业级 SSD 受 AI 拉动,2024–2030 年 CAGR 一致预期约 54%^src:50 ^src:47。整体存储 2026 年 TAM 一致预期"
        "约 2148 亿美元^src:46。国产(长鑫 DRAM、长存 NAND)份额持续提升但仍在追赶先进制程。风险方面,"
        "存储强周期本质未变,供给端扩产节奏与价格高位回落是主要监控点。"
    ),
    8: (
        "未来 6–24 个月,生成式 AI 仍处高速扩张但增速与口径分化明显:全球 AI 市场 2026 年 TAM 一致预期区间较宽,"
        "多源测算自约 6000 亿美元至 1.5 万亿美元不等、中值约 1.05 万亿美元^src:131 ^src:136(支出/收入/累计口径差异需注意);"
        "行业 CAGR 一致预期约 58–84%^src:127,营收同比约 89%^src:125 仍高增。中国市场规模口径更小且分散,"
        "2024 年多源在约 50–294 亿元区间^src:105 ^src:114。竞争上闭源头部(OpenAI/Anthropic/Google)与开源阵营"
        "(DeepSeek/Qwen 等)双轨并行,价格战压低 API 单价、推动 token 调用量爆发;商业化仍以 run-rate(年化、"
        "非确认收入)为主,盈利模式尚未完全验证。风险方面,scaling law 边际收益、算力出口管制与 AI 监管是主要不确定性。"
    ),
}


def main():
    con = sqlite3.connect(str(DB)); cur = con.cursor()
    real = {r[0] for r in cur.execute("SELECT id FROM source")}
    written = 0
    for iid, text in NARRATIVES.items():
        refs = sorted(set(int(x) for x in SRC_RE.findall(text)))
        if not refs:
            print(f"  ?? ind {iid}: 无 ^src,拒绝"); continue
        dangling = [r for r in refs if r not in real]
        if dangling:
            print(f"  ?? ind {iid}: dangling source {dangling},halt 不入库"); continue
        ex = cur.execute("SELECT id, consensus_overridden_by_human FROM industry_thesis WHERE industry_id=?", (iid,)).fetchone()
        if ex and ex[1] == 1:
            print(f"  – ind {iid}: 已人工覆盖,跳过"); continue
        sj = json.dumps(refs)
        if ex:
            cur.execute("""UPDATE industry_thesis SET consensus_narrative=?, consensus_source_ids=?,
                           consensus_generated_at=?, consensus_overridden_by_human=0 WHERE industry_id=?""",
                        (text, sj, NOW, iid))
        else:
            cur.execute("""INSERT INTO industry_thesis(industry_id, consensus_narrative, consensus_source_ids,
                           consensus_generated_at, consensus_overridden_by_human) VALUES(?,?,?,?,0)""",
                        (iid, text, sj, NOW))
        written += 1
        print(f"  ?? ind {iid}: {len(text)} 字,引用 {len(refs)} 源 {refs},全部存在 ??")
    con.commit(); con.close()
    print(f"\n写入 {written} 个行业散文。WRITE NARRATIVE (CC) DONE")


if __name__ == "__main__":
    main()
