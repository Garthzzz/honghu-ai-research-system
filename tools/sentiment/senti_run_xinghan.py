#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""星瀚情绪重构 离线处理总编排(dump 完成后跑;不调 API,不计费)。

顺序:① 入库 senti_ingest_xinghan(dump → senti_raw)
      ② 个股散户/新闻/发帖量兼容聚合 senti_aggregate_3layer
全部只写 sentiment.db。重跑幂等(INSERT OR IGNORE / UPSERT)。
"""
from __future__ import annotations
import sys, runpy
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def run(mod):
    print(f"\n{'='*60}\n▶ {mod}\n{'='*60}")
    runpy.run_path(str(HERE / f"{mod}.py"), run_name="__main__")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for m in ("senti_ingest_xinghan", "senti_aggregate_3layer"):
        run(m)
    print("\n?? 全部完成")
