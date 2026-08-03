#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""已退役：旧 Wind 单次估值回填入口。

Wind 已允许通过项目内网 HTTP 代理使用，但必须走统一 fetch/apply manifest，不能
恢复这个绕过字段级来源与原子写入门禁的旧脚本。请使用
``tools/pipeline/refresh_company_financial_metrics.py``。
"""
from __future__ import annotations

if __name__ == "__main__":
    raise SystemExit(
        "val_wind_backfill.py 已退役；请使用 refresh_company_financial_metrics.py，"
        "其 A 股策略为 Wind 内网 HTTP 代理主源、Tushare 逐字段补缺。"
    )
