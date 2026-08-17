#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""新闻入库(信源链路重构 v3)— 多源抓取 → 两段漏斗 → 仅 kept 入 news_item。

active 源(config active!=false):
  rss        → RSSNewsFetcher(SemiAnalysis)
  cls_api    → cls_fetcher.fetch_cls(财联社电报)
  gnews_site → google_news_rss + site: 限定(Reuters)
每个候选走 ai_funnel.process_news(seen→A高召回→B1判→双闸→B2生成);被丢只记 dynamic_seen。
突发检测(纯算法)在 kept 入库后跑。auth_expired(含 cls sign 失效)写 cache/dynamic_alerts/。

用法:
  python news_ingest.py                 # 全部 active 源
  python news_ingest.py --source-id N   # 只抓某 news_source(scheduler 用)
  python news_ingest.py --max 30        # 每源候选上限(默认 40)
"""
from __future__ import annotations
import sys, io, argparse
from pathlib import Path
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # 就地,避免多模块重复包装导致 buffer 被 GC 关闭
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from tools.runtime_paths import resolve_runtime_layout
RUNTIME_LAYOUT = resolve_runtime_layout(ROOT)
DB = RUNTIME_LAYOUT.data_root / "research.db"
CONFIG = ROOT / "tools" / "dynamic" / "config.yaml"
ALERTDIR = RUNTIME_LAYOUT.cache_root / "dynamic_alerts"
sys.path.insert(0, str(ROOT / "tools" / "dynamic"))
sys.path.insert(0, str(ROOT / "tools" / "dynamic" / "fetchers"))
sys.path.insert(0, str(ROOT / "tools" / "dynamic" / "news_publishers"))
import yaml
from news_fetcher import make_news_fetcher
import cls_fetcher
import ai_funnel
from relevance_classifier import RelevanceClassifier
from tools.dynamic.database import connect_dynamic

CFG = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
CLUSTERS = CFG["breaking"]["clusters"]
NOW = datetime.now()
NOW_ISO = NOW.isoformat(timespec="seconds")


def detect_cluster(text: str):
    t = (text or "").lower()
    for key, kws in CLUSTERS.items():
        for kw in kws:
            if kw.lower() in t:
                return key
    return None


def publisher_source_map(cur):
    m = {}
    for sid, pub in cur.execute("SELECT id, publisher FROM source WHERE source_subtype='news_feed'"):
        m[pub] = sid
    return m


def fetch_candidates(pconf: dict, max_items: int):
    """按 fetch_method 抓候选;返回 (candidates, status)。status: ok|auth_expired|no_rss|err。"""
    fm = pconf.get("fetch_method")
    name = pconf["name"]
    try:
        if fm == "cls_api":
            items, st = cls_fetcher.fetch_cls(max_items)
            for it in items:
                it.setdefault("summary", it.get("content_text"))
            return items, st
        if fm == "gnews_site":
            from google_news_rss import fetch as gnews_fetch
            host = pconf["home"].split("//", 1)[-1].split("/", 1)[0].replace("www.", "")
            q = f"site:{host} (AI OR semiconductor OR Nvidia OR HBM OR chip OR datacenter OR GPU)"
            raw = gnews_fetch(q)[:max_items]
            cands = [{"title": r["title"], "url": r["url"], "content_text": r["title"],
                      "summary": r["title"], "source_publisher": name,
                      "publish_date": r.get("publish_date")} for r in raw]
            return cands, ("ok" if cands else "empty")
        # 默认 rss
        f = make_news_fetcher(pconf)
        if f is None:
            return [], "no_rss"
        cands = f.fetch(pconf)[:max_items]
        return cands, ("ok" if cands else "empty")
    except Exception as e:
        return [], f"err:{type(e).__name__}:{str(e)[:80]}"


def run_breaking(con):
    cur = con.cursor()
    win = CFG["breaking"]["window_hours"]; mins = CFG["breaking"]["min_sources"]
    cutoff = (NOW - timedelta(hours=win)).isoformat(timespec="seconds")
    rows = cur.execute("""
        SELECT n.id, n.keyword_cluster, n.source_id, s.source_credibility, s.quality_tier
        FROM news_item n LEFT JOIN source s ON s.id=n.source_id
        WHERE n.keyword_cluster IS NOT NULL AND n.publish_date IS NOT NULL AND n.publish_date >= ?
    """, (cutoff[:10],)).fetchall()
    by_cluster = {}
    for nid, cl, sid, cred, tier in rows:
        g = by_cluster.setdefault(cl, {"ids": [], "wl_sources": set(), "min_tier": 9})
        g["ids"].append(nid)
        if cred == "whitelisted":
            g["wl_sources"].add(sid)
            if tier:
                g["min_tier"] = min(g["min_tier"], tier)
    n_break = 0
    for cl, g in by_cluster.items():
        if len(g["wl_sources"]) >= mins:
            imp = g["min_tier"] if g["min_tier"] in (1, 2, 3) else 3
            for nid in g["ids"]:
                cur.execute("UPDATE news_item SET is_breaking=1, importance=? WHERE id=?", (imp, nid))
                n_break += 1
    con.commit()
    return n_break


def alert(lines):
    ALERTDIR.mkdir(parents=True, exist_ok=True)
    (ALERTDIR / f"{NOW.date().isoformat()}.md").open("a", encoding="utf-8").write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-id", type=int)
    ap.add_argument("--max", type=int, default=40)
    args = ap.parse_args()
    con = connect_dynamic(DB, operation_scope="dynamic_news_ingest")
    cur = con.cursor()
    smap = publisher_source_map(cur)

    # 只跑 active!=false 的 publisher
    pubs = [p for p in CFG["news_publishers"] if p.get("active", True)]
    if args.source_id:
        pub_name = next((p for p, s in smap.items() if s == args.source_id), None)
        pubs = [p for p in pubs if p["name"] == pub_name]

    clf = RelevanceClassifier(con)
    closed = ai_funnel.ClosedSet(con)

    results = []; alerts = []
    for p in pubs:
        sid = smap.get(p["name"])
        if not sid:
            results.append((p["name"], 0, 0, "no_source_row")); continue
        cands, st = fetch_candidates(p, args.max)
        if st == "auth_expired":
            alerts.append(f"- {p['name']}(fetch_method={p.get('fetch_method')}):auth_expired(疑 sign 失效/反爬,需排查)")
        verdicts = {}
        for c in cands:
            # 突发 cluster 在入库前算(funnel 内不算;入库后由 run_breaking 复算 kept)
            v = ai_funnel.process_news(con, clf, closed, c, source_id=sid,
                                       source_lang=p.get("language", "en"), now_iso=NOW_ISO)
            verdicts[v] = verdicts.get(v, 0) + 1
            con.commit()
        # kept 入库后补 keyword_cluster(突发用)
        for c in cands:
            cl = detect_cluster((c.get("title") or "") + " " + (c.get("content_text") or ""))
            if cl:
                cur.execute("UPDATE news_item SET keyword_cluster=? WHERE url=? AND keyword_cluster IS NULL",
                            (cl, c.get("url")))
        con.commit()
        kept = verdicts.get("kept", 0)
        results.append((p["name"], len(cands), kept, st + " | " + str(verdicts)))

    nb = run_breaking(con)

    print(f"{'publisher':<14}{'cand':>5}{'kept':>5}  detail")
    for name, got, kept, detail in results:
        print(f"  {name:<12}{got:>5}{kept:>5}  {detail}")
    print(f"\n突发置位:{nb}")
    print("funnel COUNT:", ai_funnel.COUNT)
    import llm_client
    print("DeepSeek usage:", llm_client.USAGE)
    tot = cur.execute("SELECT COUNT(*) FROM news_item").fetchone()[0]
    print(f"news_item 总数:{tot}")

    if alerts:
        alert([f"## 新闻 auth_expired — {NOW_ISO}"] + alerts)
        print(f"alerts → {ALERTDIR.relative_to(ROOT)}/{NOW.date().isoformat()}.md")
    con.close()


if __name__ == "__main__":
    main()
