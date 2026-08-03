#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一次性回填:意见领袖 relevance 闸改为"仅马斯克"后的历史数据修正。

1) 浮现(surface):非马斯克、此前被相关性闸丢(is_ai_relevant=0)、且有正文的帖 → is_ai_relevant=1。
   空内容帖保持 0(那是无可展示文本,不是被过滤)。
2) 重富化(re-enrich):非马斯克、近 7 天、尚无 industry tag 的帖 → process_voice(apply_filter=False),
   补 tag/翻译/摘要,使"第一次更新"的最近一周干净可读。

马斯克(elonmusk)不动:他保留完整漏斗结果。新闻不受影响。
用法:python backfill_voice_musk_only.py [--max-reenrich 200]
"""
from __future__ import annotations
import sqlite3, sys, argparse
from pathlib import Path
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent.parent
DB = ROOT / "data" / "research.db"
sys.path.insert(0, str(ROOT / "tools" / "dynamic"))
import ai_funnel
from relevance_classifier import RelevanceClassifier

NOW = datetime.now().isoformat(timespec="seconds")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-reenrich", type=int, default=200)
    args = ap.parse_args()
    con = sqlite3.connect(str(DB)); con.row_factory = sqlite3.Row

    # 1) surface 非马斯克 hidden(有正文)
    cur = con.execute("""
        UPDATE voice_post SET is_ai_relevant=1
        WHERE id IN (
          SELECT vp.id FROM voice_post vp JOIN opinion_leader ol ON ol.id=vp.leader_id
          WHERE lower(COALESCE(ol.account_handle,''))!='elonmusk'
            AND vp.is_ai_relevant=0 AND TRIM(COALESCE(vp.content_text,''))<>''
        )""")
    surfaced = cur.rowcount
    con.commit()
    print(f"[surface] 非马斯克帖浮现 is_ai_relevant=1:{surfaced} 条")

    # 2) re-enrich 非马斯克近 7 天未打 industry tag 的帖
    clf = RelevanceClassifier(con)
    closed = ai_funnel.ClosedSet(con)
    rows = con.execute("""
        SELECT vp.*, ol.region, ol.account_handle, ol.name AS leader_name
        FROM voice_post vp JOIN opinion_leader ol ON ol.id=vp.leader_id
        WHERE ol.is_active=1 AND lower(COALESCE(ol.account_handle,''))!='elonmusk'
          AND vp.posted_at >= date('now','-7 days')
          AND (vp.ai_tags_industry IS NULL OR vp.ai_tags_industry IN ('','[]'))
          AND TRIM(COALESCE(vp.content_text,''))<>''
        ORDER BY vp.posted_at DESC LIMIT ?""", (args.max_reenrich,)).fetchall()
    print(f"[re-enrich] 待重富化:{len(rows)} 条(近7天未打tag)")
    done = 0
    for r in rows:
        lang = "zh" if r["region"] == "cn" else "en"
        ai_funnel.process_voice(con, clf, closed, r, source_lang=lang, now_iso=NOW,
                                apply_filter=False)
        con.commit(); done += 1
        if done % 20 == 0:
            print(f"  …{done}/{len(rows)}")
    import llm_client
    print(f"[done] 重富化 {done} 条 | DeepSeek usage: {llm_client.USAGE}")

    # 校验
    vis = con.execute("""SELECT COUNT(*) FROM voice_post vp JOIN opinion_leader ol ON ol.id=vp.leader_id
        WHERE lower(COALESCE(ol.account_handle,''))!='elonmusk' AND vp.is_ai_relevant=1""").fetchone()[0]
    hid = con.execute("""SELECT COUNT(*) FROM voice_post vp JOIN opinion_leader ol ON ol.id=vp.leader_id
        WHERE lower(COALESCE(ol.account_handle,''))='elonmusk' AND vp.is_ai_relevant=0""").fetchone()[0]
    print(f"[verify] 非马斯克可见={vis} | 马斯克仍被过滤={hid}")
    con.close()


if __name__ == "__main__":
    main()
