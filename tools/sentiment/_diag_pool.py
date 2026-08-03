#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""诊断:全局池为何 0 条。多 param 组合各拉 limit=10(省计费),报 code/msg/records/平台。
每组合间隔 60s(限流)。只读不写库。"""
from __future__ import annotations
import sys, json, time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import Counter
from urllib.request import Request
from urllib.error import HTTPError, URLError

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "dynamic" / "fetchers"))
import senti3
from kuaisearch_client import load_token, BASE, _OPENER, TIMEOUT

TZ = timezone(timedelta(hours=8))


def body(*, subject_type, time_type, hours, info_source="", filter_type="1", is_repeat="0",
         media_types=(), limit=10):
    now = datetime.now(TZ); now_ms = int(time.time() * 1000)
    return {
        "id": "", "subjectType": subject_type,
        "beginTime": senti3.to_ms(now - timedelta(hours=hours)), "endTime": senti3.to_ms(now),
        "timestamp": now_ms, "timeType": str(time_type),
        "infoSource": info_source, "attitude": [], "sourceRange": "",
        "newSqSourceRange": [], "newSourceRange": "", "newsMediaSourceRange": [],
        "mediaType": list(media_types), "shortVideoType": [], "tvChannel": [], "tvColumn": [],
        "isOcr": "", "filterType": filter_type, "matchRange": "", "firstRegion": "100", "wordRange": "50",
        "uniqueRegion": True, "weiboTimeFilter": False, "ignoreWeiboLocationWord": False,
        "ignoreWeiboRemindWord": False, "ignoreWeiboTopicWord": False,
        "weiboType": [], "weiboAttestType": [], "weiboState": "",
        "isRepeat": is_repeat, "browseRange": "", "isImportance": False, "noPicture": False, "orderBy": 1,
        "isHideSummary": False, "customCondition": [], "subjectModule": 1, "refreshType": 1,
        "pageSize": limit, "sites": [], "industryTags": [], "distinguishType": [],
        "videoDurationType": [], "regionalMatchType": [], "regionalMatch": [], "subjectArray": [],
        "sqSourceRange": [], "fansCountRange": "", "isFullscreen": False, "warningType": 1,
        "monitorType": 0, "language": 2, "offset": 0, "limitNum": limit, "activeNav": 1, "backTrack": False,
    }


def call(token, b, rl):
    rl.acquire()
    data = json.dumps(b).encode("utf-8")
    req = Request(f"{BASE}/subject/infos", data=data, method="POST",
                  headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    try:
        with _OPENER.open(req, timeout=TIMEOUT) as r:
            j = json.loads(r.read().decode("utf-8", "replace"))
    except HTTPError as e:
        try: eb = e.read().decode("utf-8", "replace")[:200]
        except Exception: eb = ""
        return {"http": e.code, "err": eb}
    except (URLError, Exception) as e:
        return {"http": "ERR", "err": str(e)[:150]}
    recs = (j.get("data") or {}).get("records") or []
    subs = Counter(str(r.get("subjectId"))[:12] for r in recs)
    webs = Counter((r.get("webName") or "?")[:18] for r in recs)
    samp = []
    for r in recs[:3]:
        samp.append({"sub": str(r.get("subjectId"))[:10], "kw": r.get("keyWord"),
                     "web": r.get("webName"), "pub": r.get("publishTime"),
                     "title": (r.get("title") or "")[:30]})
    return {"http": 200, "code": j.get("code"), "msg": j.get("msg") or j.get("message"),
            "n": len(recs), "subs": dict(subs), "webs": dict(webs.most_common(6)), "samp": samp}


def main():
    token = load_token()
    rl = senti3.RateLimiter("infos", 60)
    combos = [
        ("T1=专题/采集/720h", dict(subject_type=1, time_type=2, hours=720)),
        ("T2=分类/采集/720h", dict(subject_type=2, time_type=2, hours=720)),
        ("T3=专题/发布/2160h", dict(subject_type=1, time_type=1, hours=2160)),
        ("T4=专题/采集/72h/境内", dict(subject_type=1, time_type=2, hours=72, info_source="0")),
        ("T5=专题/采集/720h/不去重/全过滤", dict(subject_type=1, time_type=2, hours=720, is_repeat="1", filter_type="")),
    ]
    for name, kw in combos:
        r = call(token, body(**kw), rl)
        print(f"\n=== {name} ===")
        print(json.dumps(r, ensure_ascii=False)[:900])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
