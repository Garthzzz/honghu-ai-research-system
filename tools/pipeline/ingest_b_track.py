#!/usr/bin/env python
"""B 轨兼容入口；实现已统一到 ingest_research.py。"""

try:
    from .ingest_research import main
except ImportError:  # 直接执行脚本时保留兼容
    from ingest_research import main


if __name__ == "__main__":
    main(default_track="b")
