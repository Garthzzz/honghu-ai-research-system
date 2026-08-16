#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
E1 AI 标注 — 可复用 AbstractTagger(铁律 9/22)

AbstractTagger.tag(text) -> {tags_company:[int], tags_industry:[int], summary, cite}
本期实例:CCKeywordTagger —— grounded 名称/别名 + config 关键词匹配:
  - company:匹配 db company.name(子串);**只产 db 现有 id,结构上不可能幻觉新实体**
  - industry:匹配 config.industry_tag_keywords(中英双语)
  - summary:用条目自带 RSS summary(verbatim),不改写
  说明:本轮 token 受限,用确定性 grounded 匹配(零幻觉、可扩展、零硬编码进代码——
        公司清单来自 db,行业关键词来自 config);语义级标注待 APIAbstractTagger(接口一致)。
后端可换(CC / API / manual),接口不变。

用法:python ai_tagger.py --news        # 标 news_item(ai_tagged_by IS NULL)
"""
from __future__ import annotations
import sys, io, json, argparse
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import date

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / "research.db"
CONFIG = ROOT / "tools" / "dynamic" / "config.yaml"
import yaml
from tools.dynamic.database import connect_dynamic
CFG = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
TAGGER_ID = f"cc_session_{date.today().isoformat()}"


class AbstractTagger(ABC):
    @abstractmethod
    def tag(self, text: str) -> dict:
        ...


class CCKeywordTagger(AbstractTagger):
    def __init__(self, con):
        # 公司清单从 db 拉(零硬编码);name 长度≥2 才用于子串匹配(防过短误匹配)
        self.companies = [(cid, nm) for cid, nm in con.execute("SELECT id, name FROM company")
                          if nm and len(nm.strip()) >= 2]
        self.ind_kw = {int(k): v for k, v in (CFG.get("industry_tag_keywords") or {}).items()}

    def tag(self, text: str) -> dict:
        t = text or ""
        tl = t.lower()
        cos = sorted({cid for cid, nm in self.companies if nm in t})
        inds = sorted({iid for iid, kws in self.ind_kw.items()
                       for kw in kws if kw.lower() in tl})
        return {"tags_company": cos, "tags_industry": inds, "cite": []}


def tag_news(limit=None):
    con = connect_dynamic(DB, operation_scope="dynamic_ai_tagger")
    tagger = CCKeywordTagger(con)
    rows = con.execute(
        "SELECT id, title, content_text, summary FROM news_item WHERE ai_tagged_by IS NULL"
        + (f" LIMIT {int(limit)}" if limit else "")).fetchall()
    n = both = ind_only = none = 0
    for r in rows:
        text = f"{r['title']} {r['content_text'] or ''}"
        res = tagger.tag(text)
        summary = (r["summary"] or r["title"] or "")[:160]
        con.execute(
            """UPDATE news_item SET ai_tags_company=?, ai_tags_industry=?, summary=COALESCE(summary,?),
               ai_tagged_by=? WHERE id=?""",
            (json.dumps(res["tags_company"]), json.dumps(res["tags_industry"]), summary, TAGGER_ID, r["id"]))
        n += 1
        if res["tags_company"] and res["tags_industry"]:
            both += 1
        elif res["tags_industry"]:
            ind_only += 1
        elif not res["tags_company"] and not res["tags_industry"]:
            none += 1
    con.commit()
    print(f"标注 news_item:{n} 条(company+industry {both} / 仅industry {ind_only} / 无tag {none})")
    # 质量抽样(5 条)
    print("\n抽样(company id → 名称交叉验证):")
    for r in con.execute("""SELECT id, title, ai_tags_company, ai_tags_industry FROM news_item
                            WHERE ai_tags_company <> '[]' ORDER BY id DESC LIMIT 5"""):
        cos = json.loads(r["ai_tags_company"]); inds = json.loads(r["ai_tags_industry"])
        conames = [con.execute("SELECT name FROM company WHERE id=?", (c,)).fetchone()[0] for c in cos]
        innames = [con.execute("SELECT name FROM industry WHERE id=?", (i,)).fetchone()[0] for i in inds]
        print(f"  #{r['id']} {(r['title'] or '')[:42]} → 公司{conames} 行业{innames}")
    con.close()


def _post_type(text: str) -> str:
    """保守启发式(vocab §16):默认 观点(分析师推文多为观点);不自动判'闲聊'(避免误隐藏)。
    转发→以 'RT ' 起;数据→含 ≥2 个数字/百分比。"""
    t = (text or "").strip()
    if t.startswith("RT ") or t.startswith("//@") or "转发微博" in t:
        return "转发"
    import re as _re
    if len(_re.findall(r"\d+[%\.]?\d*", t)) >= 3:
        return "数据"
    return "观点"


def tag_voices(limit=None):
    con = connect_dynamic(DB, operation_scope="dynamic_ai_tagger")
    tagger = CCKeywordTagger(con)
    rows = con.execute("SELECT id, content_text FROM voice_post WHERE ai_tagged_by IS NULL"
                       + (f" LIMIT {int(limit)}" if limit else "")).fetchall()
    n = 0; by_pt = {}
    for r in rows:
        text = r["content_text"] or ""
        res = tagger.tag(text)
        pt = _post_type(text)
        by_pt[pt] = by_pt.get(pt, 0) + 1
        con.execute("""UPDATE voice_post SET ai_tags_company=?, ai_tags_industry=?, post_type=?,
                       ai_tagged_by=? WHERE id=?""",
                    (json.dumps(res["tags_company"]), json.dumps(res["tags_industry"]), pt, TAGGER_ID, r["id"]))
        n += 1
    con.commit()
    print(f"标注 voice_post:{n} 条;post_type 分布:{by_pt}")
    print("抽样:")
    for r in con.execute("""SELECT id, content_text, ai_tags_company, ai_tags_industry, post_type
                            FROM voice_post ORDER BY id LIMIT 5"""):
        cos = [con.execute("SELECT name FROM company WHERE id=?", (x,)).fetchone()[0] for x in json.loads(r["ai_tags_company"] or "[]")]
        print(f"  #{r['id']} [{r['post_type']}] {(r['content_text'] or '')[:50]} → 公司{cos}")
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--news", action="store_true")
    ap.add_argument("--voices", action="store_true")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    if args.news:
        tag_news(args.limit)
    if args.voices:
        tag_voices(args.limit)
