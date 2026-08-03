#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
P4.2 翻译层(可复用 ABC)

Translator(ABC).translate(text, target='zh') -> str
CCSessionTranslator:本期 CC session 翻译(译文经 translate_cc.py 注入,prompt 控制字面翻译)
APITranslator:API key 到位后切(claude-haiku/sonnet),接口一致

?? 反 slop:译文必带原文(UI 双语);只字面翻译不加信息;专有名词保留英文
  (NVIDIA/TSMC/HBM/Anthropic/SK hynix/Samsung/Meta/Google/CoWoS/GPU/ASIC/DRAM/NAND/ASML/
   Qwen/Claude/GPT-5/H100/GB200/Cloudflare/xAI/SpaceX/AWS/Marvell/Trainium/Bedrock 等);
  完不成的留空 + translated_by=NULL。
"""
from __future__ import annotations
from abc import ABC, abstractmethod

# 专有名词白名单(翻译时保留英文,不译)
KEEP_EN = ["NVIDIA", "TSMC", "HBM", "HBM4", "HBM3E", "Anthropic", "OpenAI", "SK hynix", "Samsung",
           "Meta", "Google", "CoWoS", "GPU", "ASIC", "NPU", "TPU", "DRAM", "NAND", "SSD", "ASML",
           "Qwen", "Claude", "GPT-5", "H100", "GB200", "Cloudflare", "xAI", "SpaceX", "AWS",
           "Marvell", "Trainium", "Bedrock", "Broadcom", "Intel", "Micron", "Arista", "DDR4", "DDR5"]


class Translator(ABC):
    @abstractmethod
    def translate(self, text: str, target_lang: str = "zh") -> str:
        ...


class CCSessionTranslator(Translator):
    """本期实现:译文由 CC session 预生成(translate_cc.py 的 dict 注入),此处仅查表。
    未命中 → 返回 None(留空,等下次 / API 版)。"""
    def __init__(self, table: dict | None = None):
        self.table = table or {}

    def translate(self, text: str, target_lang: str = "zh") -> str | None:
        return self.table.get(text)


class APITranslator(Translator):
    """API key 到位后:claude messages 字面翻译,prompt 注入 KEEP_EN。接口一致,UI/调度零改。"""
    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        self.model = model

    def translate(self, text: str, target_lang: str = "zh") -> str | None:
        import os
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None
        try:
            import anthropic
            client = anthropic.Anthropic()
            kp = "、".join(KEEP_EN)
            prompt = (f"把下面英文**字面**翻译成中文,不增删信息,以下专有名词保留英文({kp}):\n\n{text}")
            r = client.messages.create(model=self.model, max_tokens=600,
                                       messages=[{"role": "user", "content": prompt}])
            return "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip()
        except Exception:
            return None
