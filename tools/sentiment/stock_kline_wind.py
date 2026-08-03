#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""已退役：旧 Wind K 线入口。

Wind 已解除全局禁止，但旧脚本不具备当前公司全集、状态传播和写库门禁。K 线仍
使用 ``stock_kline_fetch.py``；如接入 Wind K 线，应在该统一入口增加受控 provider，
不能恢复本文件的历史实现。
"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if __name__ == "__main__":
    raise SystemExit(
        "stock_kline_wind.py 已退役；请使用 stock_kline_fetch.py。"
    )
