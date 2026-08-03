#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""信源链路重构 P1 — 两段漏斗编排(seen → A 高召回 → B1 判 → 双闸 → B2 生成)。

新闻:process_news() 完整漏斗 + 仅 kept 入 news_item;被丢只记 dynamic_seen。
KOL :process_voice() 对已入库 voice_post 做 relevance + 摘要/翻译/tag 富化(不丢行,置 is_ai_relevant)。

抗 slop:
  - D4 tag 闭集:company=db 公司名(子串 grounded ∪ B2 提议∩db);industry=industries_final(grounded ∪ B2∩闭集)
  - R2 数字粗筛:摘要数字不在原文 → 降级 ai_summary=NULL(仅 tag),不硬丢
  - D1 条件翻译:非中文源才产 title_zh/content_text_zh;中文源留 NULL,summary_zh 仍做
  - importance_raw 原始 1-5 全记 dynamic_seen(校准底料);min_importance 走 config
"""
from __future__ import annotations
import json, re, sqlite3
from pathlib import Path

import yaml
import llm_client
from summarizer import DeepSeekJudge, DeepSeekSummarizer
from relevance_classifier import RelevanceClassifier

ROOT = Path(__file__).resolve().parent.parent.parent
_CFG = yaml.safe_load((ROOT / "tools" / "dynamic" / "config.yaml").read_text(encoding="utf-8"))
_GATE = _CFG.get("topic_gate", {}) or {}
MIN_IMP = int(_GATE.get("min_importance", 3))
_INDUSTRIES = _CFG.get("industries_final", [])

# funnel 计数(供 RUN_LOG)
COUNT = {"seen_skip": 0, "dropped_prefilter": 0, "dropped_irrelevant": 0,
         "dropped_importance": 0, "kept": 0, "b1_none": 0, "b2_none": 0,
         "number_downgrade": 0, "voice_relevant": 0, "voice_irrelevant": 0}


class ClosedSet:
    """D4 闭集:company 全表 ∪ industries_final。"""
    def __init__(self, con):
        self.company_by_name = {nm.strip(): cid for cid, nm in con.execute("SELECT id, name FROM company")
                                if nm and len(nm.strip()) >= 2}
        self.industry_by_name = {b["name"]: b.get("db_id") for b in _INDUSTRIES if b.get("db_id")}


# ───────────────────────── seen 账本 ─────────────────────────
def seen_has(con, kind, dedup_key) -> bool:
    return con.execute("SELECT 1 FROM dynamic_seen WHERE kind=? AND dedup_key=?",
                       (kind, dedup_key)).fetchone() is not None


def seen_record(con, kind, dedup_key, *, url=None, post_id=None, verdict, is_relevant=None,
                importance_raw=None, reason=None, seen_at):
    con.execute(
        """INSERT OR IGNORE INTO dynamic_seen
           (kind, dedup_key, url, post_id, verdict, is_relevant, importance_raw, relevance_reason, seen_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (kind, dedup_key, url, post_id, verdict,
         (None if is_relevant is None else int(is_relevant)),
         importance_raw, (reason or "")[:300], seen_at))


# ───────────────────────── R2 数字粗筛 ─────────────────────────
_NUM = re.compile(r"\d[\d,\.]*")


def number_guard(summary: str | None, original: str | None) -> tuple[str | None, bool]:
    """摘要每个数字的数字核必须出现在原文数字流;否则降级(返回 None, True)。
       返回 (summary_or_None, downgraded?)。这是『挡粗暴幻觉的栏杆』,非忠实性保证。"""
    if not summary:
        return summary, False
    orig_digits = re.sub(r"[^\d]", "", original or "")
    for tok in _NUM.findall(summary):
        core = re.sub(r"[^\d]", "", tok)
        if not core:
            continue
        if core not in orig_digits and tok not in (original or ""):
            return None, True
    return summary, False


# ───────────────────────── tag 闭集解析 ─────────────────────────
def resolve_tags(clf: RelevanceClassifier, closed: ClosedSet, text: str, b2_tags: dict):
    """grounded(classifier)∪ B2 提议∩闭集 → (company_ids, industry_ids)。"""
    res = clf.classify(text)
    comp = set(res.get("tags_company") or [])                 # grounded 公司 id
    ind_names = set(res.get("tags_industry") or [])           # grounded 板块名
    for nm in (b2_tags or {}).get("company", []):
        nm = str(nm).strip()
        if nm in closed.company_by_name:                      # B2 提议 ∩ db 公司
            comp.add(closed.company_by_name[nm])
    for nm in (b2_tags or {}).get("industry", []):
        nm = str(nm).strip()
        if nm in closed.industry_by_name:                     # B2 提议 ∩ industries_final
            ind_names.add(nm)
    ind_ids = sorted({closed.industry_by_name[n] for n in ind_names if closed.industry_by_name.get(n)})
    return sorted(comp), ind_ids


# ───────────────────────── 新闻漏斗 ─────────────────────────
_judge = DeepSeekJudge()
_summ = DeepSeekSummarizer()
_IND_NAMES = [b["name"] for b in _INDUSTRIES]


def process_news(con, clf, closed, cand: dict, *, source_id, source_lang, now_iso) -> str:
    """单条新闻走漏斗;kept 入 news_item。返回 verdict。"""
    url = cand.get("url"); title = cand.get("title") or ""
    content = cand.get("content_text") or cand.get("summary") or ""
    if not url or not title:
        return "skip_empty"
    if seen_has(con, "news", url):
        COUNT["seen_skip"] += 1
        return "seen"

    text = f"{title} {content}"
    # 漏斗 A:高召回——只杀字面无任何 AI 信号的
    a = clf.classify(text)
    if a["status"] == "irrelevant":
        COUNT["dropped_prefilter"] += 1
        seen_record(con, "news", url, url=url, verdict="dropped_prefilter",
                    reason="A 预过滤:" + a["reason"], seen_at=now_iso)
        return "dropped_prefilter"

    # 漏斗 B1:DeepSeek 判定
    b1 = _judge.judge(title, content)
    if b1 is None:
        COUNT["b1_none"] += 1
        seen_record(con, "news", url, url=url, verdict="dropped_prefilter",
                    reason="B1 调用失败(留空不编造)", seen_at=now_iso)
        return "b1_none"
    imp = b1["importance"]
    if not b1["is_relevant"]:
        COUNT["dropped_irrelevant"] += 1
        seen_record(con, "news", url, url=url, verdict="dropped_irrelevant", is_relevant=0,
                    importance_raw=imp, reason="B1:" + b1["reason"], seen_at=now_iso)
        return "dropped_irrelevant"
    if imp > MIN_IMP:
        COUNT["dropped_importance"] += 1
        seen_record(con, "news", url, url=url, verdict="dropped_importance", is_relevant=1,
                    importance_raw=imp, reason=f"B1 importance={imp}>{MIN_IMP}", seen_at=now_iso)
        return "dropped_importance"

    # 漏斗 B2:生成(条件翻译)
    need_translate = (source_lang or "en") != "zh"
    b2 = _summ.generate(title, content, source_lang, need_translate, _IND_NAMES) or {}
    summary_zh = b2.get("summary_zh")
    summary_zh, downgraded = number_guard(summary_zh, content)
    if downgraded:
        COUNT["number_downgrade"] += 1
    comp_ids, ind_ids = resolve_tags(clf, closed, text, b2.get("tags") or {})

    # 入 news_item(kept)
    con.execute(
        """INSERT OR IGNORE INTO news_item
           (title, url, content_text, summary, source_publisher, source_id, publish_date,
            importance, is_ai_relevant, relevance_reason, ai_tags_company, ai_tags_industry,
            ai_tagged_by, ai_summary, ai_summary_source_ids, ai_summary_generated_at,
            title_zh, content_text_zh, translated_at, translated_by, fetch_timestamp)
           VALUES(?,?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (title[:500], url, content, cand.get("summary"), cand.get("source_publisher"),
         source_id, cand.get("publish_date"), imp, "B1:" + b1["reason"],
         json.dumps(comp_ids), json.dumps(ind_ids), "deepseek_funnel",
         summary_zh, json.dumps([source_id] if source_id else []), now_iso,
         b2.get("title_zh"), b2.get("content_text_zh"),
         (now_iso if need_translate else None), ("deepseek" if need_translate else None),
         now_iso))
    COUNT["kept"] += 1
    seen_record(con, "news", url, url=url, verdict="kept", is_relevant=1, importance_raw=imp,
                reason="kept:" + b1["reason"], seen_at=now_iso)
    return "kept"


# ───────────────────────── KOL 富化 ─────────────────────────
def process_voice(con, clf, closed, vrow, *, source_lang, now_iso, apply_filter=True) -> str:
    """对已入库 voice_post 行做 relevance + 摘要/翻译/tag 富化(不丢行)。返回 verdict。

    apply_filter=True :高噪声账号(如马斯克)走完整漏斗,A 预过滤/B1 不相关 → is_ai_relevant=0。
    apply_filter=False:其余意见领袖只富化(tag/翻译/摘要),跳过相关性闸,一律 is_ai_relevant=1
                        —— 仍可能 b1 提供 importance 文案,但绝不因相关性被丢。
    空内容无论何种模式都置 0(不是过滤,是无可展示文本)。
    """
    vid = vrow["id"]; content = vrow["content_text"] or ""
    if not content.strip():
        con.execute("UPDATE voice_post SET is_ai_relevant=0, ai_tagged_by='deepseek_funnel', relevance_reason=? WHERE id=?",
                    ("空内容", vid))
        return "empty"
    b1 = None
    if apply_filter:
        a = clf.classify(content)
        if a["status"] == "irrelevant":
            COUNT["voice_irrelevant"] += 1
            con.execute("UPDATE voice_post SET is_ai_relevant=0, ai_tagged_by='deepseek_funnel', relevance_reason=? WHERE id=?",
                        ("A 预过滤:" + a["reason"], vid))
            return "irrelevant"
        b1 = _judge.judge("(KOL 帖)", content)
        if b1 and not b1["is_relevant"]:
            COUNT["voice_irrelevant"] += 1
            con.execute("UPDATE voice_post SET is_ai_relevant=0, ai_tagged_by='deepseek_funnel', relevance_reason=? WHERE id=?",
                        ("B1:" + b1["reason"], vid))
            return "irrelevant"
    # 相关(或免过滤账号)→ B2 富化
    need_translate = (source_lang or "en") != "zh"
    b2 = _summ.generate("(KOL 帖)", content, source_lang, need_translate, _IND_NAMES) or {}
    summary_zh, _ = number_guard(b2.get("summary_zh"), content)
    comp_ids, ind_ids = resolve_tags(clf, closed, content, b2.get("tags") or {})
    con.execute(
        """UPDATE voice_post SET is_ai_relevant=1, relevance_reason=?,
             ai_tags_company=?, ai_tags_industry=?, ai_tagged_by=?,
             ai_summary=?, ai_summary_zh=?, ai_summary_generated_at=?,
             content_text_zh=?, translated_at=?, translated_by=? WHERE id=?""",
        (("B1:" + b1["reason"]) if b1 else "免过滤账号:全量保留",
         json.dumps(comp_ids), json.dumps(ind_ids), "deepseek_funnel",
         summary_zh, summary_zh, now_iso,
         (b2.get("content_text_zh") if need_translate else None),
         (now_iso if need_translate else None), ("deepseek" if need_translate else None), vid))
    COUNT["voice_relevant"] += 1
    return "relevant"
