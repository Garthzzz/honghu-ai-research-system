#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从 senti_post(帖级,唯一真相)重算某公司的 小时/日 聚合(发帖量 + T3 方向分)。
senti_ingest 抓帖后调,senti_direction 打标后再调(方向分更新)。只写 sentiment.db。"""
from __future__ import annotations

_DIR_SRC = "deepseek_self(非平台原生)"


def _agg_rows(con, cid, group_col):
    return con.execute(f"""
        SELECT {group_col} AS gk, MAX(ticker) AS ticker, MAX(source_url) AS src,
               COUNT(*) AS pc, SUM(read_count) AS rs,
               SUM(CASE WHEN label_score > 0 THEN 1 ELSE 0 END) AS bull,
               SUM(CASE WHEN label_score < 0 THEN 1 ELSE 0 END) AS bear,
               SUM(CASE WHEN label_score = 0 AND sentiment_label IS NOT NULL THEN 1 ELSE 0 END) AS neu
        FROM senti_post WHERE company_id=? GROUP BY {group_col}""", (cid,)).fetchall()


def recompute_company(con, cid, now):
    # 小时
    for r in _agg_rows(con, cid, "ts_hour"):
        tot = (r["bull"] or 0) + (r["bear"] or 0) + (r["neu"] or 0)
        direction = ((r["bull"] or 0) - (r["bear"] or 0)) / tot if tot else None
        con.execute("""INSERT INTO senti_discussion_hourly
            (company_id,ticker,ts_hour,post_count_hour,read_sum_hour,bull_count,bear_count,neutral_count,
             sentiment_direction,direction_src,source_url,as_of,fetched_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(company_id,ts_hour) DO UPDATE SET
              post_count_hour=excluded.post_count_hour, read_sum_hour=excluded.read_sum_hour,
              bull_count=excluded.bull_count, bear_count=excluded.bear_count, neutral_count=excluded.neutral_count,
              sentiment_direction=excluded.sentiment_direction, direction_src=excluded.direction_src,
              fetched_at=excluded.fetched_at""",
            (cid, r["ticker"], r["gk"], r["pc"], r["rs"], r["bull"], r["bear"], r["neu"],
             direction, (_DIR_SRC if tot else None), r["src"], r["gk"][:10], now))
    # 日(rollup;只 upsert 有帖的日,不动历史无帖日)
    for r in _agg_rows(con, cid, "trade_date"):
        tot = (r["bull"] or 0) + (r["bear"] or 0) + (r["neu"] or 0)
        direction = ((r["bull"] or 0) - (r["bear"] or 0)) / tot if tot else None
        con.execute("""INSERT INTO senti_discussion_daily
            (company_id,ticker,trade_date,post_count,read_count,platform,bull_count,bear_count,neutral_count,
             sentiment_direction,direction_src,source_url,as_of,fetched_at)
            VALUES(?,?,?,?,?,'eastmoney',?,?,?,?,?,?,?,?)
            ON CONFLICT(company_id,trade_date,platform) DO UPDATE SET
              post_count=excluded.post_count, read_count=excluded.read_count,
              bull_count=excluded.bull_count, bear_count=excluded.bear_count, neutral_count=excluded.neutral_count,
              sentiment_direction=excluded.sentiment_direction, direction_src=excluded.direction_src,
              fetched_at=excluded.fetched_at""",
            (cid, r["ticker"], r["gk"], r["pc"], r["rs"], r["bull"], r["bear"], r["neu"],
             direction, (_DIR_SRC if tot else None), r["src"], r["gk"], now))
