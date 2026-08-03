#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""信源链路重构 P1 — DeepSeek 判定(B1)+ 生成(B2)。

复用 llm_client(DeepSeek);prompt 结构为「公共 system + 原文(独立 user)+ 任务(独立 user)」,
让 B1/B2 共享「system+原文」前缀 → DeepSeek 服务端自动缓存命中(D5),消双倍输入。

- DeepSeekJudge.judge(title, content) -> {is_relevant, importance(1-5), reason}   ← B1,短输出
- DeepSeekSummarizer.generate(title, content, lang, need_translate, industry_names)
      -> {summary_zh, title_zh, content_text_zh, tags{industry:[名], company:[名]}}  ← B2,仅过闸调

?? 反 slop:prompt 强约束「只用原文、数字必来自原文、tag 只从候选选」;失败返回 None,不编造。
后端可换(API key 换别家):接口不变。
"""
from __future__ import annotations
from abc import ABC, abstractmethod

import llm_client

# 公共 system(B1/B2 一致 → 共享缓存前缀)
COMMON_SYS = (
    "你是面向中国买方机构的「AI 算力产业链」新闻处理助手。覆盖板块:光模块/交换机/存储/"
    "大模型/芯片/半导体/云服务器厂商/液冷散热/电力/AI应用。铁律:只依据给定原文,"
    "绝不编造原文没有的事实或数字;摘要里出现的每个数字都必须能在原文找到。"
)

_B1_TASK = (
    "任务:判定上面这条新闻是否属于 AI 算力产业链,并打重要度。\n"
    "输出 JSON:{\"is_relevant\": true/false, \"importance\": 1-5, \"reason\": \"一句中文理由\"}\n"
    "importance 标度(1=最重要):1=重大(龙头业绩超预期/制裁断供/重大并购/产能或价格剧变/重大技术突破);"
    "2=较重要(明确利好利空的行业动态);3=一般行业动态;4=边缘相关;5=泛泛或几乎无关。"
)


class Summarizer(ABC):
    @abstractmethod
    def generate(self, title: str, content: str, lang: str,
                 need_translate: bool, industry_names: list[str]) -> dict | None: ...


class DeepSeekJudge:
    """B1:相关性 + 重要度判定(便宜短输出)。"""

    def judge(self, title: str, content: str) -> dict | None:
        msgs = [
            {"role": "system", "content": COMMON_SYS},
            {"role": "user", "content": f"【新闻】标题:{title}\n正文:{(content or '')[:2500]}"},
            {"role": "user", "content": _B1_TASK},
        ]
        txt = llm_client.chat(msgs, max_tokens=200, json_mode=True)
        out = _parse_json(txt)
        if not out:
            return None
        # 规整
        try:
            imp = int(out.get("importance"))
        except Exception:
            imp = 3
        imp = min(5, max(1, imp))
        return {"is_relevant": bool(out.get("is_relevant")),
                "importance": imp,
                "reason": str(out.get("reason") or "")[:200]}


class DeepSeekSummarizer(Summarizer):
    """B2:摘要 + 条件翻译 + tag 提议(仅对过闸条目调)。"""

    def generate(self, title, content, lang, need_translate, industry_names):
        inds = "、".join(industry_names)
        if need_translate:
            task = (
                "任务:为上面这条新闻生成 JSON:\n"
                "{\"summary_zh\": \"2-3 句中文摘要(只用原文信息,数字必来自原文)\", "
                "\"title_zh\": \"标题中译(NVIDIA/TSMC/HBM/GPU/ASIC 等专有名词保留英文)\", "
                "\"content_text_zh\": \"正文中译(同样保留专有名词;若正文很长取其要点译出)\", "
                f"\"tags\": {{\"industry\": [从这些里选:{inds}], \"company\": [原文明确点名的公司,中文名优先]}}}}"
            )
        else:
            # 中文源:跳翻译,只做中文摘要(D1)
            task = (
                "任务:为上面这条中文新闻生成 JSON(不要翻译,title_zh/content_text_zh 一律留 null):\n"
                "{\"summary_zh\": \"2-3 句中文摘要(只用原文信息,数字必来自原文)\", "
                "\"title_zh\": null, \"content_text_zh\": null, "
                f"\"tags\": {{\"industry\": [从这些里选:{inds}], \"company\": [原文明确点名的公司]}}}}"
            )
        msgs = [
            {"role": "system", "content": COMMON_SYS},
            {"role": "user", "content": f"【新闻】标题:{title}\n正文:{(content or '')[:2500]}"},
            {"role": "user", "content": task},
        ]
        txt = llm_client.chat(msgs, max_tokens=900, json_mode=True)
        out = _parse_json(txt)
        if not out:
            return None
        tags = out.get("tags") or {}
        return {
            "summary_zh": _s(out.get("summary_zh")),
            "title_zh": _s(out.get("title_zh")),
            "content_text_zh": _s(out.get("content_text_zh")),
            "tags": {"industry": tags.get("industry") or [], "company": tags.get("company") or []},
        }


def _s(v):
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def _parse_json(txt):
    import json
    if not txt:
        return None
    try:
        return json.loads(txt)
    except Exception:
        t = txt.strip()
        try:
            return json.loads(t[t.index("{"): t.rindex("}") + 1])
        except Exception:
            return None
