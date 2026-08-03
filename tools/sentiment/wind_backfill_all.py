#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""已退役：旧 Wind 批量回填入口。

Wind 已允许通过项目内网 HTTP 代理使用，但大批量回填必须走当前受控的
fetch/apply manifest、字段白名单和逐字段 provenance，不能恢复本旧入口。
"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if __name__ == "__main__":
    raise SystemExit(
        "wind_backfill_all.py 已退役；公司财务请使用 "
        "tools/pipeline/refresh_company_financial_metrics.py。"
    )
