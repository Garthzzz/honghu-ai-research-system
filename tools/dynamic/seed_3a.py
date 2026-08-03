#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stage 3-A 数据播种 — ?? 顺序:source 先于 opinion_leader(附修订;FK 依赖)

读 config.yaml,依次:
  ① 4 leader source(自媒体/tier3/unverified;Gavin/Dylan note='verified_kol')
     + ~9 publisher source(三方数据/财经媒体,tier2/whitelisted)
  ② opinion_leader 行(回填 source_id)
  ③ fetch_schedule:每 leader 1 行(voice_leader,峰时频率)+ 每 publisher 1 行(news_source,180min)
     + 1 行 event_calendar(1440min)
幂等:source 按 source_url 去重;opinion_leader UNIQUE(platform,handle);fetch_schedule UNIQUE(target_type,target_id)。
re-run 安全。绝不编造:URL/handle 全来自 config(user 提供 / Claude 推荐 Dylan)。
"""
from __future__ import annotations
import sqlite3, sys, io, json
from pathlib import Path
from datetime import datetime

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent.parent
DB = ROOT / "data" / "research.db"
CONFIG = ROOT / "tools" / "dynamic" / "config.yaml"
NOW = datetime.now().isoformat(timespec="seconds")
PLATFORM_CN = {"xueqiu": "雪球", "weibo": "微博", "twitter": "X", "wechat_official": "公众号"}

import yaml


def domain_of(url):
    try:
        return url.split("//", 1)[1].split("/", 1)[0]
    except Exception:
        return ""


def get_or_create_source(cur, *, title, stype, publisher, url, subtype, credibility, tier,
                         language, fetch_method, note=None):
    row = cur.execute("SELECT id FROM source WHERE source_url=?", (url,)).fetchone()
    if row:
        if fetch_method == "yuqing_api_author":
            # 微博 KOL 统一为舆情 API 作者级来源；不再保留散户库桥接标记。
            cur.execute(
                """UPDATE source SET
                     fetch_method=?,source_subtype=?,
                     note=CASE WHEN ? IS NULL THEN note ELSE COALESCE(NULLIF(note,''),?) END
                   WHERE id=?""",
                (fetch_method, subtype, note, note, row[0]),
            )
        elif note:
            cur.execute(
                "UPDATE source SET note=COALESCE(NULLIF(note,''),?) WHERE id=?",
                (note, row[0]),
            )
        return row[0], False
    cur.execute("""INSERT INTO source(title, source_type, publisher, publish_date, quality_tier,
                     is_forward_looking, value_layer, source_url, url, note, source_subtype,
                     fetch_timestamp, fetch_method, domain, language, is_primary_source,
                     source_credibility, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (title[:200], stype, publisher, None, tier, 0, "信息流", url, url, note, subtype,
                 NOW, fetch_method, domain_of(url), language, 0, credibility, NOW))
    return cur.lastrowid, True


def upsert_schedule(cur, target_type, target_id, label, freq):
    ex = cur.execute("SELECT id FROM fetch_schedule WHERE target_type=? AND IFNULL(target_id,-1)=IFNULL(?,-1)",
                     (target_type, target_id)).fetchone()
    if ex:
        return False
    cur.execute("""INSERT INTO fetch_schedule(target_type, target_id, target_label, frequency_minutes,
                     next_run_at, status, is_active) VALUES(?,?,?,?,?, 'active', 1)""",
                (target_type, target_id, label, freq, NOW))   # next_run_at=now → 首 tick 即可跑
    return True


def migrate_all_weibo_source_provenance(cur):
    """Mark every Weibo opinion-leader source as targeted yuqing API provenance."""
    cur.execute(
        """UPDATE source
              SET fetch_method='yuqing_api_author',source_subtype='voice_weibo'
            WHERE id IN (
                  SELECT source_id FROM opinion_leader
                   WHERE platform='weibo' AND source_id IS NOT NULL
            )
              AND (COALESCE(fetch_method,'')<>'yuqing_api_author'
                   OR COALESCE(source_subtype,'')<>'voice_weibo')"""
    )
    return max(int(cur.rowcount or 0), 0)


def main():
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    con = sqlite3.connect(str(DB)); cur = con.cursor()
    con.execute("PRAGMA foreign_keys=ON")
    voice_frequency = int((cfg["schedule"].get("voice_window") or {}).get("frequency_minutes", 60))
    n_src = 0; n_leader = 0; n_sched = 0

    # ── ① + ② leaders:先 source 后 leader ──
    for L in cfg["opinion_leaders"]:
        plat_cn = PLATFORM_CN.get(L["platform"], L["platform"])
        note = "verified_kol" if L.get("verified_kol") else None
        sid, created = get_or_create_source(
            cur, title=f"{L['name']} · {plat_cn}", stype="自媒体", publisher=plat_cn,
            url=L["url"], subtype=f"voice_{L['platform']}", credibility="unverified",
            tier=3, language=("en" if L["region"] == "us" else "zh"),
            fetch_method=(
                "yuqing_api_author" if L["platform"] == "weibo"
                else f"scrape_{L['platform']}"
            ), note=note)
        n_src += int(created)
        # opinion_leader(回填 source_id)
        ex = cur.execute("SELECT id FROM opinion_leader WHERE platform=? AND account_handle=?",
                         (L["platform"], str(L["handle"]))).fetchone()
        freq = voice_frequency
        if ex:
            lid = ex[0]
            cur.execute(
                """UPDATE opinion_leader SET name=?,profile_url=?,region=?,bio=?,source_id=?,
                          fetch_frequency_minutes=? WHERE id=?""",
                (L["name"], L["url"], L["region"], L.get("bio"), sid, freq, lid),
            )
        else:
            cur.execute("""INSERT INTO opinion_leader(name, platform, profile_url, account_handle,
                             region, bio, source_id, fetch_frequency_minutes)
                           VALUES(?,?,?,?,?,?,?,?)""",
                        (L["name"], L["platform"], L["url"], str(L["handle"]), L["region"],
                         L.get("bio"), sid, freq))
            lid = cur.lastrowid; n_leader += 1
        # ③ schedule(voice_leader)
        n_sched += int(upsert_schedule(cur, "voice_leader", lid, L["name"], freq))
        cur.execute(
            """UPDATE fetch_schedule SET target_label=?,frequency_minutes=?
                 WHERE target_type='voice_leader' AND target_id=?""",
            (L["name"], freq, lid),
        )

    n_weibo_migrated = migrate_all_weibo_source_provenance(cur)
    # 包括仍保留在数据库、但已不在当前 config 名单中的兼容 leader；统一频率，
    # 不擅自改变其 active/paused 状态。
    cur.execute("UPDATE opinion_leader SET fetch_frequency_minutes=?", (voice_frequency,))
    cur.execute(
        "UPDATE fetch_schedule SET frequency_minutes=? WHERE target_type='voice_leader'",
        (voice_frequency,),
    )

    # ── ① publishers + ③ news_source schedule(?? 只处理 active!=false)──
    for P in cfg["news_publishers"]:
        if not P.get("active", True):
            continue   # 软停用源:不建 source / 不排程(历史 source 行保留不动)
        lang = P.get("language") or ("zh" if P["name"] in ("36kr", "wallstreetcn") else "en")
        sid, created = get_or_create_source(
            cur, title=P["name"], stype=P["type"], publisher=P["name"], url=P["home"],
            subtype="news_feed", credibility=P["credibility"],
            tier=(2 if P["credibility"] == "whitelisted" else 3),
            language=lang, fetch_method=P.get("fetch_method", "news_feed"))
        n_src += int(created)
        n_sched += int(upsert_schedule(cur, "news_source", sid, P["name"], cfg["schedule"]["news_min"]))

    # ── ③ event_calendar(单行,target_id=0 占位)──
    n_sched += int(upsert_schedule(cur, "event_calendar", 0, "earnings+conf",
                                   cfg["schedule"]["event_calendar_min"]))

    con.commit()
    print(
        f"新建 source:{n_src} | 新建 leader:{n_leader} | "
        f"新建 schedule:{n_sched} | 微博历史 provenance 迁移:{n_weibo_migrated}"
    )
    print("\n=== opinion_leader(回填 source_id 校验)===")
    for r in cur.execute("""SELECT ol.id, ol.name, ol.platform, ol.region, ol.source_id,
                              s.source_type, s.quality_tier, s.source_credibility, s.note
                            FROM opinion_leader ol LEFT JOIN source s ON s.id=ol.source_id ORDER BY ol.id"""):
        print(f"  #{r[0]} {r[1]:<12} {r[2]:<8} {r[3]:<3} src#{r[4]} {r[5]}/tier{r[6]}/{r[7]} note={r[8]}")
    print("\n=== fetch_schedule ===")
    for r in cur.execute("SELECT target_type, COUNT(*), MIN(frequency_minutes), MAX(frequency_minutes) FROM fetch_schedule GROUP BY target_type"):
        print(f"  {r[0]:<16} {r[1]} 行  freq {r[2]}-{r[3]}min")
    con.close()
    print("\nSEED 3A DONE")


if __name__ == "__main__":
    main()
