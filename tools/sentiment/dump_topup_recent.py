#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""近端补抓(order DESC):填补 ASC 翻页封顶导致的「今日」缺口。
对指定平台专题按时间倒序拉最近窗口,合并去重进 cache/xinghan_dump.json。限流 65s。"""
from __future__ import annotations
import sys, json, time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.request import Request
from urllib.error import HTTPError, URLError

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "dynamic" / "fetchers"))
import senti3
from kuaisearch_client import load_token, BASE, _OPENER, TIMEOUT
from xinghan_client import build_body, normalize

TZ = timezone(timedelta(hours=8))
ROOT = HERE.parent.parent
DUMP = ROOT / "cache" / "xinghan_dump.json"
STATUS = ROOT / "cache" / "xinghan_dump_status.txt"
# 缺今日的两平台(同花顺已覆盖 6/24)
TARGETS = [("a58a7da97e1243c68ad1c3ec1fa13ab9", "xueqiu"),
           ("ff605f0fac2f46f7aad7d9ed49477a5f", "eastmoney")]
SINCE = "2026-06-23T18:00"     # 近端窗口(倒序,覆盖最新)
PAGES = 6


def log(m):
    line = f"{datetime.now(TZ).isoformat(timespec='seconds')} [topup] {m}"
    STATUS.open("a", encoding="utf-8").write(line + "\n"); print(line)


def main():
    token = load_token()
    acc = json.loads(DUMP.read_text(encoding="utf-8"))
    seen = {(n["platform_hint"], n["dedup_key"]) for n in acc}
    begin_ms = senti3.to_ms(senti3.iso_to_dt(SINCE + "+08:00"))
    end_ms = senti3.to_ms(datetime.now(TZ))
    rl = senti3.RateLimiter("infos", 65)
    added = 0
    for sid, plat in TARGETS:
        now_ms = int(time.time() * 1000); offset = 0
        for page in range(PAGES):
            rl.acquire()
            body = build_body(subject_id=sid, begin_ms=begin_ms, end_ms=end_ms, now_ms=now_ms,
                              order_by=1, time_type="1", limit=180, offset=offset)   # 倒序=最新优先
            req = Request(f"{BASE}/subject/infos", data=json.dumps(body).encode(), method="POST",
                          headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
            try:
                with _OPENER.open(req, timeout=TIMEOUT) as r:
                    j = json.loads(r.read().decode("utf-8", "replace"))
            except (HTTPError, URLError, Exception) as e:
                log(f"{plat} page{page} ERR {str(e)[:50]} stop"); break
            recs = (j.get("data") or {}).get("records") or []
            for rr in recs:
                n = normalize(rr); n["keyWord"] = rr.get("keyWord")
                n["subjectId"] = rr.get("subjectId") or sid; n["platform_hint"] = plat
                n["attitude_raw"] = rr.get("attitude")
                k = (plat, n["dedup_key"])
                if n["dedup_key"] and k not in seen:
                    seen.add(k); acc.append(n); added += 1
            DUMP.write_text(json.dumps(acc, ensure_ascii=False), encoding="utf-8")
            log(f"{plat} page{page} recs={len(recs)} added_total={added}")
            if len(recs) < 180:
                break
            offset += 180
    log(f"TOPUP_DONE added={added} dump_total={len(acc)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
