#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""信源链路重构 P1 — DeepSeek client(OpenAI 兼容,纯 requests,零额外依赖)。

key loader 顺序(D 第4项):
  ① deepseek.api_key_file(secrets/deepseek_api_key.txt,相对项目根)
  ② deepseek.api_key_env(环境变量 DEEPSEEK_API_KEY)
  ③ 都没有 → disabled,enabled()=False,调用返回 None(不编造)

context caching(D5):DeepSeek 服务端自动对重复前缀做缓存命中(无需特殊参数)。
  → B1/B2 prompt 把「正文」放在靠前、稳定的位置,B2 即可命中 B1 的缓存,消双倍输入。
  usage 里 prompt_cache_hit_tokens / prompt_cache_miss_tokens 可量净用量。

?? 反 slop:任何失败(无 key / 超时 / 非 200 / JSON 坏)→ 返回 None,绝不伪造内容。
"""
from __future__ import annotations
import json, time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = ROOT / "tools" / "dynamic" / "config.yaml"
import yaml
_CFG = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
_DS = _CFG.get("deepseek", {}) or {}

# 累计 token 用量(进程内;供 RUN_LOG 统计)
USAGE = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
         "cache_hit_tokens": 0, "cache_miss_tokens": 0, "fail": 0}


def _load_key() -> str | None:
    # ① file(鲁棒解析:绝对 / 相对项目根 / 相对 tools/dynamic / 仅文件名落 secrets)
    f = _DS.get("api_key_file")
    if f:
        cands = []
        if Path(f).is_absolute():
            cands.append(Path(f))
        else:
            cands += [ROOT / f, ROOT / "tools" / "dynamic" / f,
                      ROOT / "tools" / "dynamic" / "secrets" / Path(f).name]
        for p in cands:
            if p.exists():
                k = p.read_text(encoding="utf-8").strip()
                if k:
                    return k
    # ② env
    import os
    env = _DS.get("api_key_env")
    if env and os.environ.get(env):
        return os.environ[env].strip()
    return None


_KEY = _load_key()


def enabled() -> bool:
    return bool(_DS.get("enabled") and _KEY)


def status() -> str:
    if not _DS.get("enabled"):
        return "disabled(config.deepseek.enabled=false)"
    if not _KEY:
        return "disabled(no key:file/env 均空)"
    return f"enabled(model={_DS.get('model')}, key=…{_KEY[-3:]})"


def chat(messages: list[dict], *, max_tokens: int | None = None,
         temperature: float = 0.2, json_mode: bool = False) -> str | None:
    """单次 chat completion。成功返回 assistant 文本;任何失败返回 None(不编造)。"""
    if not enabled():
        return None
    url = _DS["base_url"].rstrip("/") + "/chat/completions"
    body = {
        "model": _DS.get("model", "deepseek-chat"),
        "messages": messages,
        "max_tokens": max_tokens or _DS.get("max_tokens", 800),
        "temperature": temperature,
        "stream": False,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {_KEY}", "Content-Type": "application/json"}
    timeout = _DS.get("timeout_sec", 40)
    retries = _DS.get("max_retries", 2)
    for attempt in range(retries + 1):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=timeout)
            if r.status_code != 200:
                if r.status_code in (429, 500, 502, 503) and attempt < retries:
                    time.sleep(2 * (attempt + 1)); continue
                USAGE["fail"] += 1
                return None
            d = r.json()
            u = d.get("usage", {}) or {}
            USAGE["calls"] += 1
            USAGE["prompt_tokens"] += u.get("prompt_tokens", 0)
            USAGE["completion_tokens"] += u.get("completion_tokens", 0)
            USAGE["cache_hit_tokens"] += u.get("prompt_cache_hit_tokens", 0)
            USAGE["cache_miss_tokens"] += u.get("prompt_cache_miss_tokens", 0)
            return (d["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            if attempt < retries:
                time.sleep(2 * (attempt + 1)); continue
            USAGE["fail"] += 1
            return None
    return None


def chat_json(system: str, user: str, *, max_tokens: int | None = None) -> dict | None:
    """要求 JSON 输出的便捷封装。解析失败 → None。"""
    txt = chat([{"role": "system", "content": system},
                {"role": "user", "content": user}],
               max_tokens=max_tokens, json_mode=True)
    if not txt:
        return None
    try:
        return json.loads(txt)
    except Exception:
        # 容错:剥 ```json fence
        t = txt.strip()
        if t.startswith("```"):
            t = t.split("```", 2)[1] if "```" in t[3:] else t
            t = t[4:] if t.lower().startswith("json") else t
        try:
            s = t[t.index("{"): t.rindex("}") + 1]
            return json.loads(s)
        except Exception:
            return None


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print("DeepSeek status:", status())
    if enabled():
        out = chat_json("你只输出 JSON。", '返回 {"ok": true, "msg": "pong"}')
        print("ping json:", out)
        print("usage:", USAGE)
