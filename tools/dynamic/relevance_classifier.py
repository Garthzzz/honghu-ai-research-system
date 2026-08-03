#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
A3 反向 tag 过滤器 v2(板块级 10 tag;STAGE3G_TAG_FINAL v2)

- industry tag = config.industries_final 的 10 个板块名(大模型/AI应用/芯片/半导体/存储/光模块/
  交换机/云服务器厂商/液冷散热/电力);命中 alias → 打该板块**名**(新板块 db 暂无 id,存名)。
- company tag = db company.name(独立维度,company_id)。
- AI 相关性 = 命中 ai_supply_chain_keywords 任一。
- ?? Agent 上下文判断:裸 "agent" 仅在有 AI 上下文(ai/智能/大模型/llm/智能体...)时命中,
  避免 travel agent / sales agent 误命中。
- 不相关 → is_ai_relevant=0 + 理由(非空)。subtopic 层取消。
本期 grounded 匹配(零幻觉,只产 config 板块名 / db company id);语义级 API 版接口一致。

用法:python relevance_classifier.py --classify news|voice|event|all
"""
from __future__ import annotations
import sqlite3, sys, io, json, argparse
from abc import ABC, abstractmethod
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # 就地;作为 lib 被 import 时不重建 wrapper(避免 buffer 被 GC 关闭)
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent.parent
DB = ROOT / "data" / "research.db"
CONFIG = ROOT / "tools" / "dynamic" / "config.yaml"
import yaml
CFG = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
AI_CONTEXT = ["ai", "人工智能", "智能体", "大模型", "llm", "agi", "生成式", "机器学习", "算力"]
GENERIC = {"agent"}   # 需 AI 上下文才算命中的通用词


class BaseClassifier(ABC):
    @abstractmethod
    def classify(self, text: str) -> dict: ...


class RelevanceClassifier(BaseClassifier):
    def __init__(self, con):
        self.companies = [(cid, nm) for cid, nm in con.execute("SELECT id, name FROM company")
                          if nm and len(nm.strip()) >= 2]
        # 板块池(config industries_final):name + aliases(lower);P1 后 db_id 全有 → 存 id
        self.boards = [(b["name"], [a.lower() for a in b["aliases"]]) for b in CFG.get("industries_final", [])]
        self.name2id = {b["name"]: b.get("db_id") for b in CFG.get("industries_final", [])}
        self.ai_kw = [k.lower() for k in CFG.get("ai_supply_chain_keywords", [])]

    def _alias_hit(self, alias, tl, has_ai_ctx):
        if alias in GENERIC:               # 裸 "agent" 需 AI 上下文
            return (alias in tl) and has_ai_ctx
        return alias in tl

    def classify(self, text: str) -> dict:
        t = text or ""; tl = t.lower()
        has_ai_ctx = any(k in tl for k in AI_CONTEXT)
        cos = sorted({cid for cid, nm in self.companies if nm in t})
        inds = []
        for name, aliases in self.boards:
            if any(self._alias_hit(a, tl, has_ai_ctx) for a in aliases):
                inds.append(name)
        ai_hits = [k for k in self.ai_kw if (k not in GENERIC and k in tl) or (k in GENERIC and k in tl and has_ai_ctx)]
        if cos or inds or ai_hits:
            reason = "命中板块:" + ("/".join(inds) if inds else "无") + \
                     (f" 公司{len(cos)}" if cos else "") + (f" AI词{len(ai_hits)}" if ai_hits and not inds else "")
            return {"status": "relevant", "tags_industry": inds, "tags_company": cos, "reason": reason}
        return {"status": "irrelevant", "tags_industry": [], "tags_company": [],
                "reason": "未命中任何 AI 板块/公司/相关词(非 AI 产业链内容)"}


def run(target):
    con = sqlite3.connect(str(DB)); con.row_factory = sqlite3.Row
    clf = RelevanceClassifier(con)
    specs = {"news": ("news_item", "COALESCE(title,'')||' '||COALESCE(content_text,'')"),
             "voice": ("voice_post", "COALESCE(content_text,'')"),
             "event": ("event", "COALESCE(title,'')||' '||COALESCE(description,'')")}
    targets = ["news", "voice", "event"] if target == "all" else [target]
    for tg in targets:
        tbl, expr = specs[tg]
        rows = con.execute(f"SELECT id, {expr} AS txt FROM {tbl}").fetchall()
        rel = 0; app_hits = 0
        for r in rows:
            res = clf.classify(r["txt"])
            ai = 1 if res["status"] == "relevant" else 0
            # P1 后存 db id(板块名 → industries_final.db_id);全 10 板块均有 id
            ind_ids = sorted({clf.name2id[n] for n in res["tags_industry"] if clf.name2id.get(n)})
            inds_json = json.dumps(ind_ids)
            cos_json = json.dumps(res["tags_company"])
            if tbl == "event":
                con.execute("UPDATE event SET is_ai_relevant=? WHERE id=?", (ai, r["id"]))
            else:
                con.execute(f"UPDATE {tbl} SET is_ai_relevant=?, relevance_reason=?, ai_tags_industry=?, ai_tags_company=? WHERE id=?",
                            (ai, res["reason"], inds_json, cos_json, r["id"]))
            rel += ai
            if "AI应用" in res["tags_industry"]:
                app_hits += 1
        con.commit()
        extra = f" | AI应用 命中 {app_hits}" if tg == "news" else ""
        print(f"{tg:<6} 共{len(rows)} relevant {rel}({100*rel//max(len(rows),1)}%){extra}")
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--classify", default="all")
    run(ap.parse_args().classify)
