#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""星瀚专题发现探测(一次性):枚举账号下活跃专题 + 平台/关键词分布。

契约无「专题列表」端点 → 两路发现:
  (A) 试探若干未公开的 list 候选端点(POST,记 http 状态 + 体);
  (B) 主路:subject/infos id=""(全局池)按时间窗翻页,逐条收集 subjectId / keyWord
      / relatedSubjects / webName / 平台层,聚合出「活跃专题 → (条数, 关键词样本, 平台分布)」。

只读探测,不写库。token 读 secrets,绝不入库/入日志。按条计费 → 页数封顶。
用法: python discover_subjects.py [hours] [max_pages]
"""
from __future__ import annotations
import sys, json, time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict
from urllib.request import Request
from urllib.error import HTTPError, URLError

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "dynamic" / "fetchers"))
import senti3
from kuaisearch_client import load_token, BASE, _OPENER, _strip, _ts_ms, TIMEOUT
from xinghan_client import build_body, normalize

TZ = timezone(timedelta(hours=8))
OUT = HERE.parent.parent / "cache" / "xinghan_discovery.md"


def try_list_endpoints(token):
    """试探未公开的「专题列表」候选端点。返回 [(endpoint, status, brief)]。"""
    cands = ["subject/list", "subject/subjectList", "subject/getList", "subject/tree",
             "subject/category", "subjectList", "subject/page", "subject/all",
             "subject", "subject/queryList", "subject/menu"]
    now_ms = int(time.time() * 1000)
    body = {"id": "", "subjectType": 1, "timestamp": now_ms, "pageSize": 50, "limitNum": 50,
            "offset": 0, "language": 2}
    out = []
    for ep in cands:
        data = json.dumps(body).encode("utf-8")
        req = Request(f"{BASE}/{ep}", data=data, method="POST",
                      headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
        try:
            with _OPENER.open(req, timeout=TIMEOUT) as r:
                raw = r.read().decode("utf-8", "replace")
                out.append((ep, r.status, raw[:600]))
        except HTTPError as e:
            try:
                eb = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                eb = ""
            out.append((ep, e.code, eb))
        except (URLError, Exception) as e:
            out.append((ep, "ERR", str(e)[:200]))
        time.sleep(0.5)
    return out


def probe_pool(token, hours, max_pages):
    """全局池 id="" 翻页;聚合 subjectId/keyWord/平台。返回 (records, agg)。"""
    rl = senti3.RateLimiter("infos", 60)
    now = datetime.now(TZ)
    begin_ms = senti3.to_ms(now - timedelta(hours=hours))
    end_ms = senti3.to_ms(now)
    now_ms = int(time.time() * 1000)
    recs = []
    seen = set()
    offset = 0
    status = "ok"
    for page in range(max_pages):
        rl.acquire()
        body = build_body(subject_id="", begin_ms=begin_ms, end_ms=end_ms, now_ms=now_ms,
                          order_by=1, time_type="1", limit=180, offset=offset)
        data = json.dumps(body).encode("utf-8")
        req = Request(f"{BASE}/subject/infos", data=data, method="POST",
                      headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
        try:
            with _OPENER.open(req, timeout=TIMEOUT) as r:
                j = json.loads(r.read().decode("utf-8", "replace"))
        except HTTPError as e:
            status = f"HTTP{e.code}"; break
        except (URLError, Exception) as e:
            status = f"ERR:{str(e)[:80]}"; break
        page_recs = (j.get("data") or {}).get("records") or []
        for rr in page_recs:
            k = rr.get("infoId") or rr.get("id")
            if k and k not in seen:
                seen.add(k); recs.append(rr)
        if len(page_recs) < 180:
            break
        offset += 180
    # 聚合
    by_sub = defaultdict(lambda: {"count": 0, "kw": Counter(), "web": Counter(), "layer": Counter(),
                                  "rel": Counter()})
    layer_all = Counter()
    for rr in recs:
        sub = str(rr.get("subjectId") or "?")
        d = by_sub[sub]
        d["count"] += 1
        if rr.get("keyWord"):
            d["kw"][str(rr["keyWord"])[:30]] += 1
        d["web"][(rr.get("webName") or "?")[:24]] += 1
        rel = rr.get("relatedSubjects")
        if rel:
            d["rel"][str(rel)[:40]] += 1
        lay, plat = senti3.classify_platform(rr.get("webName"), rr.get("domain"),
                                             rr.get("mediaType"), rr.get("channel"))
        tag = f"{lay}/{plat}" if lay else f"OTHER(mt={rr.get('mediaType')})"
        d["layer"][tag] += 1
        layer_all[tag] += 1
    return recs, by_sub, layer_all, status


def main():
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    max_pages = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    token = load_token()
    if not token:
        print("NO TOKEN"); return
    L = [f"# 星瀚专题发现探测  {datetime.now(TZ).isoformat(timespec='seconds')}",
         f"窗口=近{hours}h  翻页上限={max_pages}页(×180条)", ""]

    L.append("## A. 未公开 list 端点试探")
    for ep, st, brief in try_list_endpoints(token):
        L.append(f"- `{ep}` → **{st}**  {brief[:160].replace(chr(10),' ')}")
    L.append("")

    recs, by_sub, layer_all, status = probe_pool(token, hours, max_pages)
    L.append(f"## B. 全局池 id=\"\" 探测  status={status}  拉取记录={len(recs)}")
    L.append(f"全局层/平台分布: {dict(layer_all)}")
    L.append("")
    L.append(f"### 活跃专题(subjectId)共 {len(by_sub)} 个")
    for sub, d in sorted(by_sub.items(), key=lambda x: -x[1]["count"]):
        L.append(f"\n#### subjectId=`{sub}`  条数={d['count']}")
        L.append(f"- 平台层: {dict(d['layer'])}")
        L.append(f"- 关键词 keyWord Top: {dict(d['kw'].most_common(15))}")
        L.append(f"- webName Top: {dict(d['web'].most_common(10))}")
        if d["rel"]:
            L.append(f"- relatedSubjects: {dict(d['rel'].most_common(5))}")
    OUT.write_text("\n".join(L), encoding="utf-8")
    print(f"written {OUT}")
    print(f"status={status} records={len(recs)} subjects={len(by_sub)} layers={dict(layer_all)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
