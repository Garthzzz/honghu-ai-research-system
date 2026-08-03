#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""抽样口径重做 — schema 迁移 + 热度回填(只写 sentiment.db)。幂等:可重复跑。

改动:
  1) senti_raw 加 read_count / reply_count(股吧热度源)+ heat_value(每帖热度)+ sampled(抽样标记 1/0/NULL)。
  2) senti_retail/news_bucket & _daily 加 net_sentiment_plain(不加权基准)+ layer_total / scored_count /
     coverage / usable(覆盖率);news 桶/日补 net_sentiment_weighted(热度加权,无来源权重)。
  3) 从 senti_post 按 post_id 回填 read/reply 到 senti_raw 的 guba 行(senti_post 全量有 read/reply)。
  4) 按 senti3.heat_value 公式给全部 senti_raw 行算 heat_value(星瀚=hot_value;股吧=read+reply*w)。

用法:python migrate_sampling.py
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common, senti3


def _cols(con, table):
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def _add_col(con, table, col, decl):
    """幂等加列。"""
    if col not in _cols(con, table):
        con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        return 1
    return 0


def migrate_schema(con):
    n = 0
    # 1) senti_raw 抽样/热度列
    n += _add_col(con, "senti_raw", "read_count", "INTEGER")
    n += _add_col(con, "senti_raw", "reply_count", "INTEGER")
    n += _add_col(con, "senti_raw", "heat_value", "INTEGER")     # 每帖热度(派生,可重算)
    n += _add_col(con, "senti_raw", "sampled", "INTEGER")        # 1=入样本 0=抽样排除 NULL=待定
    # 2) 桶/日表覆盖率 + 两版净情绪
    for t in ("senti_retail_bucket", "senti_retail_daily", "senti_news_bucket", "senti_news_daily"):
        n += _add_col(con, t, "net_sentiment_plain", "REAL")     # (pos-neg)/(pos+neg+neu) 不加权基准
        n += _add_col(con, t, "layer_total", "INTEGER")          # 该桶该层总帖数(含未打分)
        n += _add_col(con, t, "scored_count", "INTEGER")         # 已打分数
        n += _add_col(con, t, "coverage", "REAL")                # scored/layer_total
        n += _add_col(con, t, "usable", "INTEGER")               # 1=情绪分可用 0=覆盖不足/不显著
    # news 层补 weighted(热度加权,无来源权重)
    n += _add_col(con, "senti_news_bucket", "net_sentiment_weighted", "REAL")
    n += _add_col(con, "senti_news_daily", "net_sentiment_weighted", "REAL")
    # 3) 抽样/热度索引(大表加速)
    con.execute("CREATE INDEX IF NOT EXISTS ix_raw_sample ON senti_raw(company_id, source_layer, platform, bucket_id)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_raw_heat ON senti_raw(bucket_id, platform, heat_value)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_raw_postid ON senti_raw(post_id)")
    # senti_post.post_id 无单列索引(唯一键是 (company_id,post_id) 复合)→ 回填相关子查询全扫描慢;补单列索引
    con.execute("CREATE INDEX IF NOT EXISTS ix_spost_postid ON senti_post(post_id)")
    # 4) 抽样/覆盖率审计 view(每层:桶数 / 可用桶 / 低覆盖桶 / 平均覆盖率)
    con.execute("DROP VIEW IF EXISTS v_sample_coverage_audit")
    con.execute("""CREATE VIEW v_sample_coverage_audit AS
        SELECT 'retail' AS layer,
               COUNT(*) AS n_buckets,
               SUM(CASE WHEN usable=1 THEN 1 ELSE 0 END) AS n_usable,
               SUM(CASE WHEN coverage IS NOT NULL AND coverage<0.5 THEN 1 ELSE 0 END) AS n_low_cov,
               SUM(CASE WHEN bucket_id<'2026-06-01' AND usable=0 THEN 1 ELSE 0 END) AS n_pre0601_unusable,
               ROUND(AVG(coverage),3) AS avg_coverage
        FROM senti_retail_bucket
        UNION ALL
        SELECT 'news', COUNT(*), SUM(CASE WHEN usable=1 THEN 1 ELSE 0 END),
               SUM(CASE WHEN coverage IS NOT NULL AND coverage<0.5 THEN 1 ELSE 0 END),
               SUM(CASE WHEN bucket_id<'2026-06-01' AND usable=0 THEN 1 ELSE 0 END),
               ROUND(AVG(coverage),3)
        FROM senti_news_bucket""")
    con.commit()
    return n


def backfill_read_reply(con):
    """从 senti_post 按 post_id 回填 read/reply 到 senti_raw 的 guba 行(senti_post 全量有 read/reply)。
    ??只填 read_count IS NULL 的行:绝不覆盖重抓刚存入的更新鲜热度(重抓 write_raw 已写;此处只补历史 import 帖)。"""
    cur = con.execute("""
        UPDATE senti_raw AS sr
        SET read_count = (SELECT p.read_count FROM senti_post p WHERE p.post_id = sr.post_id
                          AND p.read_count IS NOT NULL ORDER BY p.id LIMIT 1),
            reply_count = (SELECT p.reply_count FROM senti_post p WHERE p.post_id = sr.post_id
                           AND p.reply_count IS NOT NULL ORDER BY p.id LIMIT 1)
        WHERE sr.platform = 'guba' AND sr.read_count IS NULL
          AND EXISTS (SELECT 1 FROM senti_post p WHERE p.post_id = sr.post_id AND p.read_count IS NOT NULL)
    """)
    con.commit()
    return cur.rowcount


def recompute_heat_value(con):
    """全量重算 heat_value(星瀚=hot_value;股吧=read+reply*w)。幂等。"""
    w = int(senti3.load_sampling_config()["reply_heat_weight"])
    # 股吧:read + reply*w
    con.execute("""UPDATE senti_raw
        SET heat_value = COALESCE(read_count,0) + COALESCE(reply_count,0) * ?
        WHERE platform = 'guba'""", (w,))
    # 星瀚(非股吧):hot_value
    con.execute("""UPDATE senti_raw
        SET heat_value = COALESCE(hot_value,0)
        WHERE platform <> 'guba'""")
    con.commit()
    return con.execute("SELECT COUNT(*) FROM senti_raw WHERE heat_value IS NOT NULL").fetchone()[0]


def main():
    con = common.get_senti_db()
    common.assert_senti_only(con)                      # 门C 隔离
    n_cols = migrate_schema(con)
    n_bf = backfill_read_reply(con)
    n_hv = recompute_heat_value(con)
    # 报告
    r = con.execute("""SELECT
        SUM(CASE WHEN platform='guba' THEN 1 ELSE 0 END) guba,
        SUM(CASE WHEN platform='guba' AND read_count IS NOT NULL THEN 1 ELSE 0 END) guba_hasread,
        SUM(CASE WHEN heat_value>0 THEN 1 ELSE 0 END) hv_pos
        FROM senti_raw""").fetchone()
    print(f"?? 迁移完成:新增列 {n_cols} 个;回填 read/reply {n_bf} 行;heat_value 覆盖 {n_hv} 行")
    print(f"   guba 行 {r['guba']} | 有 read_count {r['guba_hasread']} | heat_value>0 {r['hv_pos']}")
    con.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
