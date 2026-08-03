#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stage 3 Phase 1 — P0-2 + P0-4 migration

P0-2:加 trigger trg_fetch_schedule_no_null_target 防 INSERT target_id IS NULL
      (SQLite UNIQUE 视多个 NULL 为 distinct → 会绕过去重;event_calendar 用 target_id=0,不受影响)。
P0-4:9 行 news_source 的 next_run_at 抖动 = now + random(0,30) min(错开抓取,避免同时打 9 个源)。
      voice_leader(4)/event_calendar(1)不抖动。

幂等:trigger IF NOT EXISTS;P0-4 只 UPDATE news_source(re-run 会重新抖动,无害)。
不破坏现有 14 行。
"""
import sqlite3, sys, io, random, statistics
from pathlib import Path
from datetime import datetime, timedelta

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

DB = Path(__file__).resolve().parent.parent.parent / "data" / "research.db"
NOW = datetime.now()

TRIGGER = """
CREATE TRIGGER IF NOT EXISTS trg_fetch_schedule_no_null_target
BEFORE INSERT ON fetch_schedule
WHEN NEW.target_id IS NULL
BEGIN
  SELECT RAISE(ABORT, 'fetch_schedule.target_id 不能为 NULL(P0-2)');
END;
"""

def main():
    con = sqlite3.connect(str(DB)); cur = con.cursor()
    before = cur.execute("SELECT COUNT(*) FROM fetch_schedule").fetchone()[0]

    # P0-2
    cur.executescript(TRIGGER)
    con.commit()

    # P0-4:news_source 抖动
    ids = [r[0] for r in cur.execute("SELECT id FROM fetch_schedule WHERE target_type='news_source' ORDER BY id")]
    for sid in ids:
        jitter = random.randint(0, 30)
        nxt = (NOW + timedelta(minutes=jitter)).isoformat(timespec="seconds")
        cur.execute("UPDATE fetch_schedule SET next_run_at=? WHERE id=?", (nxt, sid))
    con.commit()

    print("=== P0-2 验收:NULL target_id 应被拒 ===")
    try:
        cur.execute("INSERT INTO fetch_schedule(target_type, target_id) VALUES('news_source', NULL)")
        con.commit()
        print("  ?? FAIL:NULL 竟然插入成功(trigger 没生效)")
    except sqlite3.IntegrityError as e:
        print(f"  ?? PASS:NULL 被拒 — {e}")
    except sqlite3.OperationalError as e:
        print(f"  ?? PASS:NULL 被拒(RAISE)— {e}")

    print("\n=== P0-4 验收:news_source next_run_at 抖动分散 ===")
    spans = []
    for r in cur.execute("SELECT target_label, next_run_at FROM fetch_schedule WHERE target_type='news_source' ORDER BY next_run_at"):
        mins = (datetime.fromisoformat(r[1]) - NOW).total_seconds() / 60
        spans.append(mins)
        print(f"  {r[0]:<16} +{mins:.0f}min  {r[1]}")
    sd = statistics.pstdev(spans) if len(spans) > 1 else 0
    print(f"  分布标准差 = {sd:.1f} min  ({'?? PASS >5' if sd > 5 else '?? <5 抖动不足'})")

    after = cur.execute("SELECT COUNT(*) FROM fetch_schedule").fetchone()[0]
    print(f"\n现有 fetch_schedule 行数:{before} → {after}(应不变=14)")
    con.close()
    print("MIGRATION 005 DONE")

if __name__ == "__main__":
    main()
