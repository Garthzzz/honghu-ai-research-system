#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""离线归因入库:cache/xinghan_dump.json → senti_raw(个股)。

与抓取解耦(dump 已计费一次,归因可反复重跑不再计费)。只写 sentiment.db。
- 平台:senti3.classify_platform(webName/domain/mediaType);回落 platform_hint。
- 个股归因:AliasIndex(标题+正文),闭集 = research.db 104 + senti_company 31 新股。多命中多归。
- 态度:星瀚原生 1正2负3中 → attitude_src='xinghan_native';缺失留 NULL(不编造)。
- 分桶:publish_time → senti3.bucket_for。
"""
from __future__ import annotations
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common, senti3

ROOT = Path(__file__).resolve().parent.parent.parent
DUMP = ROOT / "cache" / "xinghan_dump.json"
def main():
    con = common.get_senti_db()
    common.assert_senti_only(con)
    alias_idx = senti3.AliasIndex(con)
    recs = json.loads(DUMP.read_text(encoding="utf-8"))
    now = common.now_iso()
    from collections import Counter
    plat_dist = Counter(); n_raw = 0; n_drop_plat = 0; n_noattr_stock = 0
    n_records = len(recs)
    for n in recs:
        layer, platform = senti3.classify_platform(n.get("web_name"), n.get("domain"),
                                                   n.get("media_type"), n.get("channel"))
        if not layer:
            # 回落 platform_hint(weibo 探测等)
            ph = n.get("platform_hint")
            if ph in ("xueqiu", "eastmoney", "ths", "weibo"):
                layer, platform = "retail", ph
            else:
                n_drop_plat += 1; continue
        plat_dist[platform] += 1
        pub = n.get("publish_time")
        bdt = senti3.iso_to_dt(pub) if pub else None
        b = senti3.bucket_for(bdt or senti3.iso_to_dt(now))
        bid = b["bucket_id"]
        text = (n.get("title") or "") + " " + (n.get("text") or "")
        as_of = (pub or now)[:10]
        # ── 个股归因 → senti_raw ──
        hits = alias_idx.attribute(text)
        for cid, ticker in hits:
            r = senti3.insert_raw(con, bucket_id=bid, company_id=cid, ticker=ticker or "",
                source_layer=layer, platform=platform, attitude=n.get("attitude"),
                attitude_src="xinghan_native", dedup_key=n["dedup_key"], post_id=n.get("post_id"),
                title=n.get("title"), url=n.get("url"), author=n.get("author"), author_uid=n.get("author_uid"),
                fans_count=n.get("fans_count"), auth_type=n.get("auth_type"), web_name=n.get("web_name"),
                domain=n.get("domain"), channel=n.get("channel"), media_type=n.get("media_type"),
                hot_value=n.get("hot_value"), sim_hash=n.get("sim_hash"), publish_time=pub,
                as_of=as_of, fetched_at=now, backfilled=1)
            n_raw += r
        if not hits:
            n_noattr_stock += 1
    con.commit()
    print(f"=== 星瀚 dump 入库 ===  原始记录 {n_records}")
    print(f"  平台分布: {dict(plat_dist)}")
    print(f"  个股 senti_raw 新增行 {n_raw}(多归因展开);未归因个股记录 {n_noattr_stock}")
    print(f"  丢弃非散户/新闻平台 {n_drop_plat}")
    con.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
