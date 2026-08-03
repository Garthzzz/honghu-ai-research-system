#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stage 2c-G 任务 4(??重做):AI 综合分析 — 一致预期【散文式】生成

不是数字罗列,是 AI 综合写作。给定 industry_id:
  1. 扫该行业 quality_tier≤2 的 idp dp + company_profile + sub_market_share
  2. 丢给 Claude(Anthropic API)→ 200-400 字散文(走势预判 + 核心原因 + 数据串联,数字带 ^src:N)
  3. 严格校验:必须含 ^src;所有 ^src:N 的 N 必须在 db source 表真实存在(dangling → 跳过不入库);
     数字应能在传入数据里反查。
  4. 写入 industry_thesis.consensus_narrative + consensus_source_ids + consensus_generated_at
     (consensus_overridden_by_human=1 的行不覆盖)。

?? 降级:未设 ANTHROPIC_API_KEY 或缺 anthropic SDK → 不写入(narrative 留空,UI 显示 pending),退出 0。

用法:
  set ANTHROPIC_API_KEY=...   (PowerShell: $env:ANTHROPIC_API_KEY="...")
  python tools/pipeline/stage2c_g_gen_consensus_narrative.py --all-industries
  python tools/pipeline/stage2c_g_gen_consensus_narrative.py --industry 1 [--force]
"""
from __future__ import annotations
import sqlite3, sys, io, os, json, re, argparse
from pathlib import Path
from datetime import datetime

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

DB = Path(__file__).resolve().parent.parent.parent / "data" / "research.db"
NOW = datetime.now().isoformat(timespec="seconds")
MODEL = os.environ.get("STAGE2CG_MODEL", "claude-sonnet-4-6")
SRC_RE = re.compile(r"\^src:(\d+)")
IND_NAME = {1: "光模块", 7: "存储", 8: "大模型"}


def have_api():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False, "ANTHROPIC_API_KEY 未设置"
    try:
        import anthropic  # noqa
        return True, ""
    except Exception:
        return False, "anthropic SDK 未安装(pip install anthropic)"


def gather_data(cur, iid):
    """收集传给 Claude 的 db 数据(只 tier≤2,带 source_id 可溯源)。"""
    dps = cur.execute("""
        SELECT dp.metric, dp.value_num, dp.value_text, dp.unit, dp.as_of_date, dp.period,
               dp.is_forecast, dp.consensus_status, dp.peer_count, dp.source_id, dp.source_excerpt
        FROM industry_data_point dp LEFT JOIN source s ON s.id=dp.source_id
        WHERE dp.industry_id=? AND dp.company_id IS NULL
          AND (s.quality_tier IS NULL OR s.quality_tier<=2)
          AND dp.consensus_status IN ('共识','主流','次主流')
          AND dp.source_id IS NOT NULL
        ORDER BY (dp.consensus_status='共识') DESC, dp.peer_count DESC
        LIMIT 40
    """, (iid,)).fetchall()
    lines = []
    valid_src = set()
    for m, vn, vt, unit, aof, per, isfc, cs, peer, sid, exc in dps:
        v = ("%g" % vn) if vn is not None else (vt or "")
        if not v:
            continue
        valid_src.add(sid)
        tag = "(预测)" if isfc else ""
        lines.append(f"[dp source_id={sid}] {m}={v}{unit or ''}{tag} @{aof or per or ''} "
                     f"({cs},{peer}源)" + (f" 摘录:{(exc or '')[:80]}" if exc else ""))
    # 子市场份额
    for sub, geo, share, aof, rank, sids in cur.execute("""
        SELECT s.sub_market, s.geo, s.share, s.share_as_of, s.rank, s.source_ids
        FROM company_sub_market_share s WHERE s.industry_id=? AND s.share IS NOT NULL
        ORDER BY s.sub_market, (s.rank IS NULL), s.rank
    """, (iid,)):
        try:
            sl = [x for x in (json.loads(sids) if sids else []) if isinstance(x, int)]
        except Exception:
            sl = []
        valid_src.update(sl)
        cn = cur.execute("SELECT c.name FROM company_sub_market_share s JOIN company c ON c.id=s.company_id WHERE s.industry_id=? AND s.sub_market=? AND s.share=? LIMIT 1", (iid, sub, share)).fetchone()
        nm = cn[0] if cn else ""
        lines.append(f"[子市场份额 source_id={sl[0] if sl else '?'}] {sub}({geo}) {nm} {share:g}% rank={rank} @{aof or ''}")
    return "\n".join(lines), valid_src


PROMPT_TMPL = """你是泓湖投资 AI 行研助手。基于以下 db 数据,为「{name}」生成一段未来走势综合分析(约 200-400 字)。

包含三部分(融成一段散文,不要分点列表):
A. 走势预判:未来 6-24 个月该行业的关键趋势(供需/产能/价格/技术等)
B. 核心原因:这个走势的支撑逻辑(用研报数据点串联)
C. 数据支撑:关键数字嵌入叙事中,每个引用的数字后紧跟 ^src:N(N=该 dp 的 source_id)

硬要求:
- 一段散文,不要列表/小标题
- 引用任何数字必须带 ^src:N,N 只能取自下方数据的 source_id,绝不编造
- 不允许出现 db 数据里没有的数字
- 风险点只一句带过(不展开,避免与 risks 字段重叠)
- 客观中性,不带情绪修饰;中文输出

db 数据(只可引用这些 source_id):
{data}
"""


def validate_and_write(cur, iid, narrative, valid_src):
    refs = set(int(x) for x in SRC_RE.findall(narrative))
    if not refs:
        print(f"  ?? ind {iid}: 返回不含任何 ^src,按反 slop 拒绝入库"); return False
    real = {r[0] for r in cur.execute("SELECT id FROM source")}
    dangling = sorted(r for r in refs if r not in real)
    if dangling:
        print(f"  ?? ind {iid}: 含 dangling source {dangling},halt 不入库"); return False
    out_of_scope = sorted(r for r in refs if r not in valid_src)
    if out_of_scope:
        print(f"  ?? ind {iid}: 引用了未传入的 source {out_of_scope}(可能 AI 越界)→ 拒绝入库"); return False
    # 不覆盖人工版本
    ex = cur.execute("SELECT consensus_overridden_by_human FROM industry_thesis WHERE industry_id=?", (iid,)).fetchone()
    if ex and ex[0] == 1:
        print(f"  – ind {iid}: 已人工覆盖,跳过"); return False
    sj = json.dumps(sorted(refs))
    if ex:
        cur.execute("""UPDATE industry_thesis SET consensus_narrative=?, consensus_source_ids=?,
                       consensus_generated_at=?, consensus_overridden_by_human=0 WHERE industry_id=?""",
                    (narrative, sj, NOW, iid))
    else:
        cur.execute("""INSERT INTO industry_thesis(industry_id, consensus_narrative, consensus_source_ids,
                       consensus_generated_at, consensus_overridden_by_human) VALUES(?,?,?,?,0)""",
                    (iid, narrative, sj, NOW))
    print(f"  ?? ind {iid}: 写入散文 {len(narrative)} 字,引用 {len(refs)} 源")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--industry", type=int)
    ap.add_argument("--all-industries", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    ok, msg = have_api()
    if not ok:
        print(f"??  降级:{msg}")
        print("    任务 4 schema 已就绪(industry_thesis.consensus_narrative),narrative 留空 = pending。")
        print("    待 ANTHROPIC_API_KEY 到位后重跑本脚本即可补充。")
        return

    import anthropic
    client = anthropic.Anthropic()
    targets = [1, 7, 8] if args.all_industries else ([args.industry] if args.industry else [])
    con = sqlite3.connect(str(DB)); cur = con.cursor()
    n = 0
    for iid in targets:
        data, valid_src = gather_data(cur, iid)
        if not data.strip():
            print(f"  – ind {iid}: 无 tier≤2 共识 dp,跳过"); continue
        prompt = PROMPT_TMPL.format(name=IND_NAME.get(iid, str(iid)), data=data)
        try:
            resp = client.messages.create(model=MODEL, max_tokens=1200,
                                          messages=[{"role": "user", "content": prompt}])
            narrative = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        except Exception as e:
            print(f"  ?? ind {iid}: API 调用失败 {e}"); continue
        if validate_and_write(cur, iid, narrative, valid_src):
            n += 1
    con.commit(); con.close()
    print(f"\n生成散文 {n} 个行业。GEN NARRATIVE DONE")


if __name__ == "__main__":
    main()
