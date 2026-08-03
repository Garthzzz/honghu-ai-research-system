#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""招聘代理每周任务:重抓全部公司官网招聘页(新增/下架比对)→ 分类职能/领域/城市。
Windows 计划任务 IndustryDemo_RecruitWeekly(周一 11:00)调用此脚本。只写 sentiment.db。"""
from __future__ import annotations
import sys, subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PY = sys.executable
TZ = timezone(timedelta(hours=8))


def run(script):
    print(f"\n=== {script} ===")
    p = subprocess.run([PY, str(HERE / script)], cwd=str(ROOT),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5400)
    print((p.stdout or "")[-1500:])
    if p.returncode != 0:
        print("ERR:", (p.stderr or "")[-400:])
    return p.returncode == 0


def main():
    # A delayed Task Scheduler launch must remain silent on weekends: do not
    # print, spawn children, call the network, or open the database.
    if datetime.now(TZ).weekday() >= 5:
        return 0
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    run("recruit_scrape.py")        # 重抓 → recruit_job open/closed 比对 + recruit_change_log 历史
    run("recruit_classify.py")      # 职能/领域/城市 分类(新增岗位也分类)
    print("\n?? 招聘周更完成")


if __name__ == "__main__":
    raise SystemExit(main())
