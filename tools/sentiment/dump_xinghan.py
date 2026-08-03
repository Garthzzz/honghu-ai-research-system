#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""星瀚原始记录批量 dump(一次性,与归因/打分解耦,避免重复计费)。

按 config.platform_subjects 的 3 个非微博平台专题,各自宽窗(fetch_since→now)翻页拉尽。
每条保留 keyWord/subjectId/平台 + 归一化字段；不请求微博媒体类型。
增量落盘 cache/xinghan_dump.json(每页写一次,断点可续);进度写 status 文件。
限流 65s/次(略宽于 60s 防 429)。只读不写库。token 读 secrets。
"""
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
INTERVAL = 65
PER_SUBJECT_PAGES = 14
NON_WEIBO_MEDIA_TYPES = [1, 2, 5, 6, 7, 9, 11, 13, 19, 99]


def log(msg):
    line = f"{datetime.now(TZ).isoformat(timespec='seconds')} {msg}"
    with STATUS.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)


def cfg():
    import yaml
    c = yaml.safe_load((ROOT / "tools" / "dynamic" / "config.yaml").read_text(encoding="utf-8"))
    return c.get("sentiment_layers", {})


def enrich(rec, subject_hint, platform_hint):
    n = normalize(rec)
    n["keyWord"] = rec.get("keyWord")
    n["subjectId"] = rec.get("subjectId") or subject_hint
    n["platform_hint"] = platform_hint
    n["attitude_raw"] = rec.get("attitude")
    return n


def page_subject(token, rl, sid, platform_hint, begin_ms, end_ms, max_pages, acc, seen):
    now_ms = int(time.time() * 1000)
    offset = 0
    added = 0
    for page in range(max_pages):
        rl.acquire()
        body = build_body(subject_id=sid, begin_ms=begin_ms, end_ms=end_ms, now_ms=now_ms,
                          order_by=2, time_type="1", limit=180, offset=offset)
        body["mediaType"] = NON_WEIBO_MEDIA_TYPES
        data = json.dumps(body).encode("utf-8")
        req = Request(f"{BASE}/subject/infos", data=data, method="POST",
                      headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
        try:
            with _OPENER.open(req, timeout=TIMEOUT) as r:
                j = json.loads(r.read().decode("utf-8", "replace"))
        except HTTPError as e:
            log(f"  [{platform_hint}] page{page} HTTP{e.code} → stop"); break
        except (URLError, Exception) as e:
            log(f"  [{platform_hint}] page{page} ERR {str(e)[:60]} → stop"); break
        if j.get("code") not in (200, None):
            log(f"  [{platform_hint}] page{page} code={j.get('code')} msg={str(j.get('msg'))[:40]} → stop"); break
        recs = (j.get("data") or {}).get("records") or []
        for rr in recs:
            n = enrich(rr, sid, platform_hint)
            k = (platform_hint, n["dedup_key"])
            if n["dedup_key"] and k not in seen:
                seen.add(k); acc.append(n); added += 1
        DUMP.write_text(json.dumps(acc, ensure_ascii=False), encoding="utf-8")  # 增量落盘
        log(f"  [{platform_hint}] page{page} recs={len(recs)} new_total={len(acc)}")
        if len(recs) < 180:
            break
        offset += 180
    return added


def main():
    token = load_token()
    if not token:
        log("NO TOKEN"); return
    c = cfg()
    begin = senti3.iso_to_dt((c.get("fetch_since") or "2026-06-22T00:00") + "+08:00")
    end = datetime.now(TZ)
    begin_ms, end_ms = senti3.to_ms(begin), senti3.to_ms(end)
    STATUS.write_text("", encoding="utf-8")
    log(f"DUMP start window={begin.isoformat()}~{end.isoformat()}")
    rl = senti3.RateLimiter("infos", INTERVAL)
    acc, seen = [], set()
    for ps in (c.get("platform_subjects") or []):
        log(f"subject {ps['platform']} id={ps['id'][:10]}…")
        page_subject(token, rl, ps["id"], ps["platform"], begin_ms, end_ms, PER_SUBJECT_PAGES, acc, seen)
    DUMP.write_text(json.dumps(acc, ensure_ascii=False), encoding="utf-8")
    from collections import Counter
    plat = Counter(n["platform_hint"] for n in acc)
    log(f"DONE total={len(acc)} by_platform={dict(plat)}")
    log("DUMP_COMPLETE")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
