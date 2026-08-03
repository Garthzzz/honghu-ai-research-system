#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""T2/M1 指标:小时 + 日 指标(既定口径)+ 情绪K线OHLC。只写 sentiment.db。
- senti_indicator_hourly:小时 ma3/ma20/上穿/分位/显著/就绪 + 方向分(盘中盯买卖点)。
- senti_indicator_daily:日级同上(rollup)。
- senti_kline_hourly:每股每小时 OHLC —— metric='direction'(该小时内逐帖累积方向分 开/高/低/收)+ 'post_count'。
"""
from __future__ import annotations
import sys
from collections import defaultdict
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

PCT_WINDOW = 60
READY_MIN = 20            # ma20 就绪门槛(桶数)


def ma(vals, n):
    return sum(vals[-n:]) / n if len(vals) >= n else None


def _indicators(con, cid, table, src_table, count_col, key_col, now, daily_sig):
    rows = con.execute(f"SELECT {key_col} AS k, {count_col} AS pc, sentiment_direction AS dir "
                       f"FROM {src_table} WHERE company_id=? AND {count_col} IS NOT NULL ORDER BY {key_col}", (cid,)).fetchall()
    vals = []; n = 0
    for i, r in enumerate(rows):
        pc = r["pc"]; vals.append(pc)
        ma3, ma20 = ma(vals, 3), ma(vals, 20)
        cross_up = 0
        if ma3 is not None and ma20 is not None and i >= 1:
            prev = vals[:-1]; pma3, pma20 = ma(prev, 3), ma(prev, 20)
            if pma3 is not None and pma20 is not None and pma3 <= pma20 and ma3 > ma20:
                cross_up = 1
        win = vals[-PCT_WINDOW:]
        pct = sum(1 for x in win if x <= pc) / len(win) if win else None
        pct99 = 1 if (pct is not None and pct >= 0.99 and len(vals) >= 10) else 0
        significant = 1 if pc > daily_sig else 0
        ready = 1 if len(vals) >= READY_MIN else 0
        if table == "senti_indicator_hourly":
            con.execute("""INSERT INTO senti_indicator_hourly
                (company_id,ts_hour,post_count_hour,ma3,ma20,cross_up,pct_rank,significant,ready,sentiment_direction,computed_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(company_id,ts_hour) DO UPDATE SET post_count_hour=excluded.post_count_hour,
                  ma3=excluded.ma3,ma20=excluded.ma20,cross_up=excluded.cross_up,pct_rank=excluded.pct_rank,
                  significant=excluded.significant,ready=excluded.ready,sentiment_direction=excluded.sentiment_direction,
                  computed_at=excluded.computed_at""",
                (cid, r["k"], pc, ma3, ma20, cross_up, pct, significant, ready, r["dir"], now))
        else:
            con.execute("""INSERT INTO senti_indicator_daily
                (company_id,trade_date,post_count,ma3,ma20,cross_up,pct_rank,pct99_alert,
                 stagnation_cut_signal,significant,ready,sentiment_direction,computed_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(company_id,trade_date) DO UPDATE SET post_count=excluded.post_count,ma3=excluded.ma3,
                  ma20=excluded.ma20,cross_up=excluded.cross_up,pct_rank=excluded.pct_rank,pct99_alert=excluded.pct99_alert,
                  significant=excluded.significant,ready=excluded.ready,sentiment_direction=excluded.sentiment_direction,
                  computed_at=excluded.computed_at""",
                (cid, r["k"], pc, ma3, ma20, cross_up, pct, pct99, None, significant, ready, r["dir"], now))
        n += 1
    return n


def _kline(con, cid, now):
    # direction 蜡烛:每小时内逐帖累积方向分 OHLC
    posts = con.execute("""SELECT ts_hour, label_score FROM senti_post
                           WHERE company_id=? AND label_score IS NOT NULL ORDER BY posted_at""", (cid,)).fetchall()
    byhour = defaultdict(list)
    for p in posts:
        byhour[p["ts_hour"]].append(p["label_score"])
    for hour, scores in byhour.items():
        run = []; s = 0.0
        for i, sc in enumerate(scores):
            s += sc; run.append(s / (i + 1))
        con.execute("""INSERT INTO senti_kline_hourly(company_id,ts_hour,metric,o,h,l,c,vol,computed_at)
            VALUES(?,?,'direction',?,?,?,?,?,?)
            ON CONFLICT(company_id,ts_hour,metric) DO UPDATE SET o=excluded.o,h=excluded.h,l=excluded.l,c=excluded.c,
              vol=excluded.vol,computed_at=excluded.computed_at""",
            (cid, hour, run[0], max(run), min(run), run[-1], len(scores), now))
    # post_count 蜡烛(每小时发帖量,degenerate OHLC=量)
    for r in con.execute("SELECT ts_hour, post_count_hour FROM senti_discussion_hourly WHERE company_id=?", (cid,)).fetchall():
        v = r["post_count_hour"]
        con.execute("""INSERT INTO senti_kline_hourly(company_id,ts_hour,metric,o,h,l,c,vol,computed_at)
            VALUES(?,?,'post_count',?,?,?,?,?,?)
            ON CONFLICT(company_id,ts_hour,metric) DO UPDATE SET o=excluded.o,h=excluded.h,l=excluded.l,c=excluded.c,
              vol=excluded.vol,computed_at=excluded.computed_at""",
            (cid, r["ts_hour"], v, v, v, v, v, now))


def _stagnation(con, now):
    """T8 解锁:滞涨减仓 = 讨论量高分位(pct_rank≥0.95)且 价格5交易日滞涨(收益≤0)。
    需 stock_kline 日价;无价则保持 NULL(不造)。"""
    n = 0
    MIN_OBS = 10                                       # 讨论分位需足够历史才有意义,否则冷启动 degenerate → 不触发(攒数据中)
    for cid in [r[0] for r in con.execute("SELECT DISTINCT company_id FROM stock_kline WHERE freq='d'")]:
        kl = con.execute("SELECT ts, c FROM stock_kline WHERE company_id=? AND freq='d' ORDER BY ts", (cid,)).fetchall()
        closes = [(r["ts"], r["c"]) for r in kl]
        idx = {d: i for i, (d, _) in enumerate(closes)}
        obs = con.execute("SELECT COUNT(*) FROM senti_indicator_daily WHERE company_id=?", (cid,)).fetchone()[0]
        for r in con.execute("SELECT trade_date, pct_rank FROM senti_indicator_daily WHERE company_id=?", (cid,)).fetchall():
            d = r["trade_date"]; pr = r["pct_rank"]
            stag = None
            if obs >= MIN_OBS and d in idx and idx[d] >= 5 and pr is not None:
                i = idx[d]
                ret = (closes[i][1] / closes[i - 5][1] - 1) if closes[i - 5][1] else None
                if ret is not None:
                    stag = 1 if (pr >= 0.95 and ret <= 0.0) else 0
            con.execute("UPDATE senti_indicator_daily SET stagnation_cut_signal=? WHERE company_id=? AND trade_date=?",
                        (stag, cid, d))
            if stag is not None:
                n += 1
    return n


def main():
    con = common.get_senti_db()
    common.assert_senti_only(con)
    cids = [r[0] for r in con.execute("SELECT DISTINCT company_id FROM senti_post")]
    if not cids:
        cids = [r[0] for r in con.execute("SELECT DISTINCT company_id FROM senti_discussion_daily")]
    now = common.now_iso()
    nh = nd = 0
    for cid in cids:
        nh += _indicators(con, cid, "senti_indicator_hourly", "senti_discussion_hourly", "post_count_hour", "ts_hour", now, 3)
        nd += _indicators(con, cid, "senti_indicator_daily", "senti_discussion_daily", "post_count", "trade_date", now, 10)
        _kline(con, cid, now)
        con.commit()
    ns = _stagnation(con, now); con.commit()
    kl = con.execute("SELECT COUNT(*) FROM senti_kline_hourly").fetchone()[0]
    kd = con.execute("SELECT COUNT(*) FROM senti_kline_hourly WHERE metric='direction'").fetchone()[0]
    nsig = con.execute("SELECT COUNT(*) FROM senti_indicator_daily WHERE stagnation_cut_signal=1").fetchone()[0]
    print(f"=== 指标:小时 {nh} 行 / 日 {nd} 行 | K线 {kl}(方向蜡烛 {kd})===")
    print(f"滞涨减仓信号(T8解锁):已算 {ns} 行 / 触发 {nsig}(讨论99分位+价格5日滞涨)")
    con.close()


if __name__ == "__main__":
    main()
