#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
B5 + B8:事件 AI 前瞻全覆盖(22/22)+ 金融严谨重写(去模糊词)

- grounded:每条 fact 从 db idp(共识/主流,tier≤2)live 拉,带 source publisher + as_of + source_id
- 精确归因(B8):用"据 {publisher}({as_of})"而非"主流口径/高者达/市场预期"
- 禁买卖建议(prompt 内化 + 关键词校验)
- ^src 全部校验存在(dangling → 跳过)
- consensus_overridden_by_human=1 的不覆盖(尊重人工)

覆盖:所有 event(按 company→industry 或 event.related_industry_ids 定 industry);
数据不足的事件 → 偏短 + 标"待数据补充",不编造。
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
VAGUE = ["主流口径", "高者达", "市场预期", "据传", "或将", "有望大涨"]
FORBIDDEN = ["买入", "卖出", "目标价", "看多", "看空", "增持", "减持", "推荐买", "强烈推荐"]
IND_NAME = {1: "光模块", 7: "存储", 8: "大模型"}
IND_WATCH = {1: "800G/1.6T 出货节奏与 ASP、CPO/硅光进展", 7: "DRAM/HBM 价格、HBM4 量产与出货占比",
             8: "营收增速、算力投入与商业化兑现"}


def fact_bank(con, iid, k=3):
    """从 db 拉该行业 grounded facts(共识/主流,tier≤2,带 publisher 归因 + source_id)。"""
    rows = con.execute("""
        SELECT dp.metric, dp.value_num, dp.value_text, dp.unit, dp.as_of_date, dp.period,
               dp.source_id, s.publisher, dp.is_forecast
        FROM industry_data_point dp LEFT JOIN source s ON s.id=dp.source_id
        WHERE dp.industry_id=? AND dp.company_id IS NULL
          AND dp.consensus_status IN ('共识','主流') AND dp.source_id IS NOT NULL
          AND (s.quality_tier IS NULL OR s.quality_tier<=2)
        ORDER BY (dp.consensus_status='共识') DESC, dp.peer_count DESC LIMIT ?""", (iid, k)).fetchall()
    facts = []
    for m, vn, vt, unit, aof, per, sid, pub, isfc in rows:
        v = ("%g" % vn) if vn is not None else (vt or "")
        if not v:
            continue
        when = aof or per or ""
        pub_attr = f"据{pub}" if pub else "据卖方研报"
        tag = "(预测)" if isfc else ""
        facts.append(f"{m} {v}{unit or ''}{tag}（{pub_attr},{when}）^src:{sid}")
    return facts


def industry_of(con, ev):
    cos = json.loads(ev["related_company_ids"] or "[]")
    if cos:
        r = con.execute("SELECT industry_id FROM company_profile WHERE company_id=? LIMIT 1", (cos[0],)).fetchone()
        if r:
            return r[0]
    inds = json.loads(ev["related_industry_ids"] or "[]")
    return inds[0] if inds else None


def main():
    con = sqlite3.connect(str(DB)); con.row_factory = sqlite3.Row
    real = {r[0] for r in con.execute("SELECT id FROM source")}
    banks = {i: fact_bank(con, i) for i in (1, 7, 8)}
    evs = con.execute("SELECT * FROM event WHERE ai_preview_overridden_by_human=0 OR ai_preview_overridden_by_human IS NULL").fetchall()
    written = short = 0
    for ev in evs:
        iid = industry_of(con, ev)
        facts = banks.get(iid, [])
        watch = IND_WATCH.get(iid, "相关板块基本面")
        iname = IND_NAME.get(iid, "相关")
        if facts:
            body = (f"{ev['title']} 看点集中在{iname}板块的{watch}。结合 db 现有研报一致数据:"
                    + ";".join(facts[:3]) + "。以上为公开研报与第三方数据的汇总,具体以官方披露为准。")
            n_short = 0
        else:
            body = (f"{ev['title']} 关注{iname if iid else '相关'}板块基本面;**待数据补充**(db 暂无该行业足够多源一致数据点支撑前瞻)。"
                    "以官方披露为准。")
            n_short = 1
        refs = sorted(set(int(x) for x in SRC_RE.findall(body)))
        if [r for r in refs if r not in real]:
            print(f"  ?? #{ev['id']}: dangling,跳过"); continue
        if [w for w in (VAGUE + FORBIDDEN) if w in body]:
            print(f"  ?? #{ev['id']}: 含模糊/买卖词,跳过"); continue
        con.execute("""UPDATE event SET ai_preview_narrative=?, ai_preview_source_ids=?,
                       ai_preview_generated_at=? WHERE id=?""",
                    (body, json.dumps(refs), NOW, ev["id"]))
        written += 1; short += n_short
    con.commit()
    cov = con.execute("SELECT COUNT(*) FROM event WHERE ai_preview_narrative IS NOT NULL").fetchone()[0]
    tot = con.execute("SELECT COUNT(*) FROM event").fetchone()[0]
    # 校验:全库无 dangling + 无模糊/买卖词
    bad_src = bad_word = 0
    for r in con.execute("SELECT ai_preview_narrative, ai_preview_source_ids FROM event WHERE ai_preview_narrative IS NOT NULL"):
        for s in json.loads(r[1] or "[]"):
            if s not in real:
                bad_src += 1
        if any(w in (r[0] or "") for w in VAGUE + FORBIDDEN):
            bad_word += 1
    print(f"写入/重写前瞻:{written}(偏短待补 {short});覆盖 {cov}/{tot}")
    print(f"全库校验:dangling src={bad_src} | 含模糊/买卖词={bad_word}(均应 0)")
    con.close()


if __name__ == "__main__":
    main()
