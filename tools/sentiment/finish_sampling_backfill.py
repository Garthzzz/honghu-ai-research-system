#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""独立续跑补打分(脱离 Claude Code 会话,可断点续跑)。
- 数据库即断点:senti_score 只打 sampled=1 且 attitude 空的帖,逐批 commit,天然幂等可续。
- 让位机制:每 2 分钟看打分是否在推进;若**别的打分器在跑(推进中)就等**,避免重复打/双倍计费;
  只在停滞(其它打分器死/睡)时接手。睡眠→整进程挂起,唤醒→接着跑。
- 全部打完 → 重算三层 + 写完成标记 cache/sampling_backfill_DONE.flag。
只写 sentiment.db。
"""
from __future__ import annotations
import sys, time, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
DB = ROOT / "data" / "sentiment.db"
PY = sys.executable


def _q(sql):
    import sqlite3
    c = sqlite3.connect(str(DB), timeout=30)
    try:
        return c.execute(sql).fetchone()[0]
    finally:
        c.close()


def rem():
    return _q("SELECT COUNT(*) FROM senti_raw WHERE sampled=1 AND attitude IS NULL")


def scored():
    return _q("SELECT COUNT(*) FROM senti_raw WHERE attitude IS NOT NULL")


def run(args, timeout):
    try:
        subprocess.run([PY, str(ROOT / "tools" / "sentiment" / args[0])] + args[1:],
                       cwd=str(ROOT), timeout=timeout, capture_output=True)
    except Exception:
        pass


def main():
    log = (ROOT / "cache" / "finish_backfill.log").open("a", encoding="utf-8")
    def L(m):
        from datetime import datetime
        log.write(f"[{datetime.now().isoformat(timespec='seconds')}] {m}\n"); log.flush()
    L(f"start: 待打 {rem()}")
    idle_rounds = 0
    while rem() > 30 and idle_rounds < 200:               # 安全上限
        a = scored(); time.sleep(120); b = scored()
        if b - a >= 50:                                   # 别的打分器在推进 → 让位
            L(f"其它打分器推进中(+{b-a}/2min),让位等待。待打 {rem()}")
            idle_rounds = 0
            continue
        L(f"停滞(+{b-a}/2min),接手打分。待打 {rem()}")    # 停滞 → 接手
        run(["senti_score.py", "--since", "2026-06-01", "--max", "3000", "--batch", "20"], 3600)
        idle_rounds += 1
    L(f"打分收敛,待打 {rem()} → 重算三层")
    run(["senti_aggregate_3layer.py"], 600)
    (ROOT / "cache" / "sampling_backfill_DONE.flag").write_text(
        f"done remaining={rem()} scored={scored()}", encoding="utf-8")
    L("DONE")
    log.close()


if __name__ == "__main__":
    main()
