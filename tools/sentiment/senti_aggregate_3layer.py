#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""三层聚合:senti_raw → senti_retail_{bucket,daily} / senti_news_{bucket,daily} / heat_volume_{bucket,daily}。

三层各自独立算,绝不合表:
  净情绪两版(都落库,只基于已打分帖):
    net_sentiment_plain   =(pos-neg)/(pos+neg+neu)        不加权基准
    net_sentiment_weighted = Σ(w·polarity)/Σ(w)            w=每帖 heat_value(0→最小权重1);
                                                          散户层再叠加来源权重(雪球/股吧高、微博低),新闻层无来源权重。
  覆盖率:layer_total(该桶该层总帖数,含未打分)/ scored_count(已打分)/ coverage / usable。
    usable=0:6/1 前低覆盖存量桶(绝不用低覆盖分冒充)或已打分有效条数≤significance_min(不显著)。
  显著性:valid_count(=scored_count)>significance_min;per_hour_count=valid_count/span_hours(防隔夜12h桶压日间3h桶)。
  热度=条数(含未打标),独立,绝不并入情绪。
只写 sentiment.db。
"""
from __future__ import annotations
import sys
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common, senti3

RETAIL_PLAT = ("xueqiu", "eastmoney", "ths", "guba")
NEWS_PLAT = ("sina_news", "netease_news", "ifeng", "toutiao", "weixin")
SINCE_FLOOR = "2026-06-01"        # 只补 6/1 起;6/1 前低覆盖存量桶标 usable=0

# 每帖热度权重 w=MAX(heat_value,1):0 热度给最小权重 1(只进随机池但仍计权)
_HW = "MAX(COALESCE(heat_value,0),1)"
_SEL_HEAT = f"""
    SUM(CASE WHEN attitude=1 THEN {_HW} ELSE 0 END) hpos,
    SUM(CASE WHEN attitude=2 THEN {_HW} ELSE 0 END) hneg,
    SUM(CASE WHEN attitude=3 THEN {_HW} ELSE 0 END) hneu"""


def _assert_full_raw_history_available(con) -> None:
    """Never rebuild historical facts from a deliberately truncated raw set."""
    table = con.execute(
        """SELECT 1 FROM sqlite_master
           WHERE type='table' AND name='retail_window_ledger'"""
    ).fetchone()
    if not table:
        return
    purged = int(
        con.execute(
            """SELECT COUNT(*) FROM retail_window_ledger
               WHERE raw_purged_at IS NOT NULL
                  OR retention_state IN ('purged','purged_incomplete')"""
        ).fetchone()[0]
    )
    if purged:
        raise RuntimeError(
            "full-history senti_raw aggregation is retired after raw retention; "
            "use permanent window/daily facts"
        )


def span_of(bucket_id):
    dt = senti3.iso_to_dt(bucket_id + "+08:00")
    return senti3.bucket_for(dt)["span_hours"] if dt else 3


def _net(pos, neg, neu):
    tot = pos + neg + neu
    return ((pos - neg) / tot) if tot else None


def _net_w(wp, wn, wnu):
    tot = wp + wn + wnu
    return ((wp - wn) / tot) if tot else None


def _usable(bid_or_date, valid, cov, sig_min, cov_low):
    """usable 判定。bid_or_date 取前 10 位与 SINCE_FLOOR 比(桶 'YYYY-MM-DDT..'/日 'YYYY-MM-DD' 同序)。"""
    if bid_or_date[:10] < SINCE_FLOOR and (cov is None or cov < cov_low):
        return 0                                  # 6/1 前低覆盖存量桶:不可用
    return 1 if valid > sig_min else 0            # 显著才可用(含抽样估计的大桶:coverage 低但 scored>10)


def agg_retail(con, now, weights, sig_min, cov_low, *, commit=True):
    _assert_full_raw_history_available(con)
    rows = con.execute(f"""SELECT company_id, MAX(ticker) ticker, bucket_id, platform,
            SUM(CASE WHEN attitude=1 THEN 1 ELSE 0 END) pos,
            SUM(CASE WHEN attitude=2 THEN 1 ELSE 0 END) neg,
            SUM(CASE WHEN attitude=3 THEN 1 ELSE 0 END) neu,
            {_SEL_HEAT},
            COUNT(*) cnt
          FROM senti_raw WHERE source_layer='retail' AND platform<>'weibo'
          GROUP BY company_id, bucket_id, platform""").fetchall()
    agg = defaultdict(lambda: {"ticker": None, "pos": 0, "neg": 0, "neu": 0, "total": 0,
                               "wp": 0.0, "wn": 0.0, "wnu": 0.0,
                               "n_xueqiu": 0, "n_weibo": 0, "n_guba": 0, "n_ths": 0, "n_eastmoney": 0})
    for r in rows:
        k = (r["company_id"], r["bucket_id"])
        a = agg[k]; a["ticker"] = a["ticker"] or r["ticker"]
        sw = senti3.retail_weight(r["platform"], weights)        # 来源权重(仅散户层)
        a["pos"] += r["pos"]; a["neg"] += r["neg"]; a["neu"] += r["neu"]; a["total"] += r["cnt"]
        a["wp"] += sw * r["hpos"]; a["wn"] += sw * r["hneg"]; a["wnu"] += sw * r["hneu"]
        a[f"n_{r['platform']}"] = a.get(f"n_{r['platform']}", 0) + r["cnt"]
    for (cid, bid), a in agg.items():
        valid = a["pos"] + a["neg"] + a["neu"]; total = a["total"]; span = span_of(bid)
        cov = (valid / total) if total else 0.0
        net_p = _net(a["pos"], a["neg"], a["neu"])
        usable = _usable(bid, valid, cov, sig_min, cov_low)
        con.execute("""INSERT INTO senti_retail_bucket
            (company_id,ticker,bucket_id,bucket_start,span_hours,valid_count,pos,neg,neu,
             net_sentiment,net_sentiment_plain,net_sentiment_weighted,per_hour_count,significant,
             layer_total,scored_count,coverage,usable,n_xueqiu,n_weibo,n_guba,n_ths,n_eastmoney,computed_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(company_id,bucket_id) DO UPDATE SET
              valid_count=excluded.valid_count,pos=excluded.pos,neg=excluded.neg,neu=excluded.neu,
              net_sentiment=excluded.net_sentiment,net_sentiment_plain=excluded.net_sentiment_plain,
              net_sentiment_weighted=excluded.net_sentiment_weighted,
              per_hour_count=excluded.per_hour_count,significant=excluded.significant,
              layer_total=excluded.layer_total,scored_count=excluded.scored_count,
              coverage=excluded.coverage,usable=excluded.usable,
              n_xueqiu=excluded.n_xueqiu,n_weibo=excluded.n_weibo,n_guba=excluded.n_guba,
              n_ths=excluded.n_ths,n_eastmoney=excluded.n_eastmoney,computed_at=excluded.computed_at""",
            (cid, a["ticker"], bid, bid + "+08:00", span, valid, a["pos"], a["neg"], a["neu"],
             net_p, net_p, _net_w(a["wp"], a["wn"], a["wnu"]), valid / span if span else None,
             1 if valid > sig_min else 0, total, valid, cov, usable,
             a["n_xueqiu"], a["n_weibo"], a["n_guba"], a.get("n_ths", 0), a.get("n_eastmoney", 0), now))
    if commit:
        con.commit()
    return len(agg)


def agg_news(con, now, sig_min, cov_low, *, commit=True):
    _assert_full_raw_history_available(con)
    rows = con.execute(f"""SELECT company_id, MAX(ticker) ticker, bucket_id, platform,
            SUM(CASE WHEN attitude=1 THEN 1 ELSE 0 END) pos,
            SUM(CASE WHEN attitude=2 THEN 1 ELSE 0 END) neg,
            SUM(CASE WHEN attitude=3 THEN 1 ELSE 0 END) neu,
            {_SEL_HEAT}, COUNT(*) cnt
          FROM senti_raw WHERE source_layer='news'
          GROUP BY company_id, bucket_id, platform""").fetchall()
    agg = defaultdict(lambda: {"ticker": None, "pos": 0, "neg": 0, "neu": 0, "total": 0,
                               "wp": 0.0, "wn": 0.0, "wnu": 0.0,
                               "n_sina_news": 0, "n_netease_news": 0, "n_ifeng": 0, "n_toutiao": 0, "n_weixin": 0})
    for r in rows:
        k = (r["company_id"], r["bucket_id"])
        a = agg[k]; a["ticker"] = a["ticker"] or r["ticker"]
        a["pos"] += r["pos"]; a["neg"] += r["neg"]; a["neu"] += r["neu"]; a["total"] += r["cnt"]
        a["wp"] += r["hpos"]; a["wn"] += r["hneg"]; a["wnu"] += r["hneu"]      # 新闻层无来源权重
        a[f"n_{r['platform']}"] = a.get(f"n_{r['platform']}", 0) + r["cnt"]
    for (cid, bid), a in agg.items():
        valid = a["pos"] + a["neg"] + a["neu"]; total = a["total"]; span = span_of(bid)
        cov = (valid / total) if total else 0.0
        net_p = _net(a["pos"], a["neg"], a["neu"])
        usable = _usable(bid, valid, cov, sig_min, cov_low)
        con.execute("""INSERT INTO senti_news_bucket
            (company_id,ticker,bucket_id,bucket_start,span_hours,valid_count,pos,neg,neu,
             net_sentiment,net_sentiment_plain,net_sentiment_weighted,per_hour_count,significant,
             layer_total,scored_count,coverage,usable,n_sina,n_netease,n_ifeng,n_toutiao,n_weixin,computed_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(company_id,bucket_id) DO UPDATE SET
              valid_count=excluded.valid_count,pos=excluded.pos,neg=excluded.neg,neu=excluded.neu,
              net_sentiment=excluded.net_sentiment,net_sentiment_plain=excluded.net_sentiment_plain,
              net_sentiment_weighted=excluded.net_sentiment_weighted,
              per_hour_count=excluded.per_hour_count,significant=excluded.significant,
              layer_total=excluded.layer_total,scored_count=excluded.scored_count,
              coverage=excluded.coverage,usable=excluded.usable,
              n_sina=excluded.n_sina,n_netease=excluded.n_netease,
              n_ifeng=excluded.n_ifeng,n_toutiao=excluded.n_toutiao,n_weixin=excluded.n_weixin,computed_at=excluded.computed_at""",
            (cid, a["ticker"], bid, bid + "+08:00", span, valid, a["pos"], a["neg"], a["neu"],
             net_p, net_p, _net_w(a["wp"], a["wn"], a["wnu"]), valid / span if span else None,
             1 if valid > sig_min else 0, total, valid, cov, usable,
             a["n_sina_news"], a["n_netease_news"], a["n_ifeng"], a["n_toutiao"], a["n_weixin"], now))
    if commit:
        con.commit()
    return len(agg)


def agg_heat(con, now, *, commit=True):
    _assert_full_raw_history_available(con)
    rows = con.execute("""SELECT company_id, MAX(ticker) ticker, bucket_id, source_layer, platform,
            COUNT(*) cnt, SUM(COALESCE(hot_value,0)) hot
          FROM senti_raw WHERE platform<>'weibo'
          GROUP BY company_id, bucket_id, source_layer, platform""").fetchall()
    agg = defaultdict(lambda: {"ticker": None, "total": 0, "retail": 0, "news": 0, "hot": 0,
                               "n_xueqiu": 0, "n_weibo": 0, "n_guba": 0, "n_ths": 0, "n_eastmoney": 0,
                               "n_news": 0})
    for r in rows:
        k = (r["company_id"], r["bucket_id"]); a = agg[k]; a["ticker"] = a["ticker"] or r["ticker"]
        a["total"] += r["cnt"]; a["hot"] += r["hot"] or 0
        if r["source_layer"] == "retail":
            a["retail"] += r["cnt"]
            if r["platform"] in ("xueqiu", "guba", "ths", "eastmoney"):
                a[f"n_{r['platform']}"] += r["cnt"]
        else:
            a["news"] += r["cnt"]; a["n_news"] += r["cnt"]
    for (cid, bid), a in agg.items():
        span = span_of(bid)
        con.execute("""INSERT INTO heat_volume_bucket
            (company_id,ticker,bucket_id,bucket_start,span_hours,total_count,per_hour_count,
             retail_count,news_count,n_xueqiu,n_weibo,n_guba,n_ths,n_eastmoney,n_news,sum_hot_value,computed_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(company_id,bucket_id) DO UPDATE SET
              total_count=excluded.total_count,per_hour_count=excluded.per_hour_count,
              retail_count=excluded.retail_count,news_count=excluded.news_count,
              n_xueqiu=excluded.n_xueqiu,n_weibo=excluded.n_weibo,n_guba=excluded.n_guba,
              n_ths=excluded.n_ths,n_eastmoney=excluded.n_eastmoney,
              n_news=excluded.n_news,sum_hot_value=excluded.sum_hot_value,computed_at=excluded.computed_at""",
            (cid, a["ticker"], bid, bid + "+08:00", span, a["total"], a["total"] / span if span else None,
             a["retail"], a["news"], a["n_xueqiu"], a["n_weibo"], a["n_guba"],
             a.get("n_ths", 0), a.get("n_eastmoney", 0), a["n_news"], a["hot"], now))
    if commit:
        con.commit()
    return len(agg)


def _daily_weighted(con, layer, weights):
    """日级热度加权净情绪(从 senti_raw 按 date×platform 重算;散户叠加来源权重,新闻无)。
    返回 {(company_id, date): (wp, wn, wnu)}。"""
    rows = con.execute(f"""SELECT company_id, substr(bucket_id,1,10) d, platform, {_SEL_HEAT}
          FROM senti_raw WHERE source_layer=? AND platform<>'weibo'
          GROUP BY company_id, d, platform""", (layer,)).fetchall()
    out = defaultdict(lambda: [0.0, 0.0, 0.0])
    for r in rows:
        sw = senti3.retail_weight(r["platform"], weights) if layer == "retail" else 1.0
        v = out[(r["company_id"], r["d"])]
        v[0] += sw * r["hpos"]; v[1] += sw * r["hneg"]; v[2] += sw * r["hneu"]
    return out


def rollup_daily(con, now, sig_min, cov_low, weights, *, commit=True):
    """桶 → 日(overnight 桶归其起始日)。plain/coverage 从桶汇总;weighted 从 senti_raw 按日重算。"""
    _assert_full_raw_history_available(con)
    # retail
    rw = _daily_weighted(con, "retail", weights)
    con.execute("DELETE FROM senti_retail_daily")
    for r in con.execute("""SELECT company_id, MAX(ticker) ticker, substr(bucket_id,1,10) d,
            SUM(valid_count) vc, SUM(pos) pos, SUM(neg) neg, SUM(neu) neu, SUM(span_hours) sh,
            SUM(COALESCE(layer_total,0)) lt, SUM(n_xueqiu) nx, SUM(n_weibo) nw, SUM(n_guba) ng,
            SUM(COALESCE(n_ths,0)) nt2, SUM(COALESCE(n_eastmoney,0)) ne
          FROM senti_retail_bucket GROUP BY company_id, substr(bucket_id,1,10)""").fetchall():
        wp, wn, wnu = rw.get((r["company_id"], r["d"]), (0.0, 0.0, 0.0))
        valid = r["vc"] or 0; total = r["lt"] or 0
        cov = (valid / total) if total else 0.0
        net_p = _net(r["pos"], r["neg"], r["neu"])
        con.execute("""INSERT INTO senti_retail_daily
            (company_id,ticker,trade_date,valid_count,pos,neg,neu,net_sentiment,net_sentiment_plain,
             net_sentiment_weighted,per_hour_count,significant,layer_total,scored_count,coverage,usable,
             n_xueqiu,n_weibo,n_guba,n_ths,n_eastmoney,computed_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r["company_id"], r["ticker"], r["d"], valid, r["pos"], r["neg"], r["neu"],
             net_p, net_p, _net_w(wp, wn, wnu), (valid / r["sh"]) if r["sh"] else None,
             1 if valid > sig_min else 0, total, valid, cov, _usable(r["d"], valid, cov, sig_min, cov_low),
             r["nx"], r["nw"], r["ng"], r["nt2"], r["ne"], now))
    # news
    nw_ = _daily_weighted(con, "news", weights)
    con.execute("DELETE FROM senti_news_daily")
    for r in con.execute("""SELECT company_id, MAX(ticker) ticker, substr(bucket_id,1,10) d,
            SUM(valid_count) vc, SUM(pos) pos, SUM(neg) neg, SUM(neu) neu, SUM(span_hours) sh,
            SUM(COALESCE(layer_total,0)) lt,
            SUM(n_sina) ns,SUM(n_netease) nn,SUM(n_ifeng) nf,SUM(n_toutiao) nt,SUM(n_weixin) nwx
          FROM senti_news_bucket GROUP BY company_id, substr(bucket_id,1,10)""").fetchall():
        wp, wn, wnu = nw_.get((r["company_id"], r["d"]), (0.0, 0.0, 0.0))
        valid = r["vc"] or 0; total = r["lt"] or 0
        cov = (valid / total) if total else 0.0
        net_p = _net(r["pos"], r["neg"], r["neu"])
        con.execute("""INSERT INTO senti_news_daily
            (company_id,ticker,trade_date,valid_count,pos,neg,neu,net_sentiment,net_sentiment_plain,
             net_sentiment_weighted,per_hour_count,significant,layer_total,scored_count,coverage,usable,
             n_sina,n_netease,n_ifeng,n_toutiao,n_weixin,computed_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r["company_id"], r["ticker"], r["d"], valid, r["pos"], r["neg"], r["neu"],
             net_p, net_p, _net_w(wp, wn, wnu), (valid / r["sh"]) if r["sh"] else None,
             1 if valid > sig_min else 0, total, valid, cov, _usable(r["d"], valid, cov, sig_min, cov_low),
             r["ns"], r["nn"], r["nf"], r["nt"], r["nwx"], now))
    # heat
    con.execute("DELETE FROM heat_volume_daily")
    for r in con.execute("""SELECT company_id, MAX(ticker) ticker, substr(bucket_id,1,10) d,
            SUM(total_count) tc, SUM(span_hours) sh, SUM(retail_count) rc, SUM(news_count) nc,
            SUM(n_xueqiu) nx,SUM(n_weibo) nw,SUM(n_guba) ng,
            SUM(COALESCE(n_ths,0)) nt2,SUM(COALESCE(n_eastmoney,0)) ne,
            SUM(n_news) nn,SUM(sum_hot_value) hv
          FROM heat_volume_bucket GROUP BY company_id, substr(bucket_id,1,10)""").fetchall():
        con.execute("""INSERT INTO heat_volume_daily
            (company_id,ticker,trade_date,total_count,per_hour_count,retail_count,news_count,
             n_xueqiu,n_weibo,n_guba,n_ths,n_eastmoney,n_news,sum_hot_value,computed_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r["company_id"], r["ticker"], r["d"], r["tc"], (r["tc"] / r["sh"]) if r["sh"] else None,
             r["rc"], r["nc"], r["nx"], r["nw"], r["ng"], r["nt2"], r["ne"], r["nn"], r["hv"], now))
    if commit:
        con.commit()


def main():
    con = common.get_senti_db()
    common.assert_senti_only(con)                      # 门C
    lcfg = senti3.load_layer_config()
    weights = (lcfg.get("retail", {}) or {}).get("weights", senti3.DEFAULT_RETAIL_WEIGHTS)
    sig_min = (lcfg.get("retail", {}) or {}).get("significance_min", senti3.SIGNIFICANCE_MIN)
    cov_low = float(senti3.load_sampling_config()["coverage_low"])
    now = common.now_iso()
    nr = agg_retail(con, now, weights, sig_min, cov_low)
    nn = agg_news(con, now, sig_min, cov_low)
    nh = agg_heat(con, now)
    rollup_daily(con, now, sig_min, cov_low, weights)
    print(f"=== 三层聚合:retail桶 {nr} / news桶 {nn} / heat桶 {nh} ===")
    for r in con.execute("SELECT * FROM v_layer_coverage_audit"):
        print(f"  [{r['layer']}] 公司 {r['n_companies']} 桶行 {r['n_bucket_rows']} "
              f"valid/条 {r['n_valid']} 显著 {r['n_significant']}")
    con.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
