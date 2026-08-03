#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""信源链路重构 — tz-aware 静默闸(D2)。

config.runtime.timezone + config.quiet_hours.{start,end};[start, end) 全静默。
中国无 DST → 优先 ZoneInfo,缺 tzdata 时回退固定 +8(对 Asia/Shanghai 精确)。

用法:
  from quiet_hours import in_quiet_hours, now_tz
  if in_quiet_hours():  # tick 顶部
      return
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
_CFG = yaml.safe_load((ROOT / "tools" / "dynamic" / "config.yaml").read_text(encoding="utf-8"))
_TZNAME = (_CFG.get("runtime", {}) or {}).get("timezone", "Asia/Shanghai")
_QH = _CFG.get("quiet_hours", {}) or {}


def _tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(_TZNAME)
    except Exception:
        # 回退:Asia/Shanghai / 中国标准时间 = 固定 UTC+8(无 DST)
        return timezone(timedelta(hours=8))


def now_tz() -> datetime:
    return datetime.now(_tz())


def _hm(s: str) -> int:
    h, m = s.split(":"); return int(h) * 60 + int(m)


def in_quiet_hours(t: datetime | None = None) -> bool:
    """t(tz-aware,缺省取 now_tz)是否落在 [start, end) 静默窗;跨午夜用 OR。"""
    if not _QH:
        return False
    t = t or now_tz()
    cur = t.hour * 60 + t.minute
    s, e = _hm(_QH["start"]), _hm(_QH["end"])
    return (s <= cur < e) if s < e else (cur >= s or cur < e)


def is_weekend(t: datetime | None = None) -> bool:
    """上海时区周六、周日；自动抓取入口应直接静默返回。"""
    local = (t or now_tz()).astimezone(_tz())
    return local.weekday() >= 5


def in_automation_silence(t: datetime | None = None) -> bool:
    """夜间或周末均不得调用外部抓取/LLM。"""
    local = (t or now_tz()).astimezone(_tz())
    return is_weekend(local) or in_quiet_hours(local)


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    n = now_tz()
    print(f"tz={_TZNAME} now={n.isoformat(timespec='seconds')} "
          f"quiet={_QH.get('start')}-{_QH.get('end')} weekend={is_weekend(n)} "
          f"→ in_silence={in_automation_silence(n)}")
