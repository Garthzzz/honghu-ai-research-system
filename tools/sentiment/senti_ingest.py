#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""M1/T2:核心池东财股吧【帖级】抓取 → senti_post → 重算 小时/日 聚合(只写 sentiment.db)。
?? 门日期:时间戳经 parse_time 校验门;非法直接跳过(bad_time 计数),绝不入库垃圾。
指标①方向分由 senti_direction(T3)后补,本步 direction 列先 NULL。
用法:python senti_ingest.py [--limit N] [--pages 3]
"""
from __future__ import annotations
import sys, json, ssl, time, argparse, urllib.request
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
from eastmoney_guba import fetch_guba_posts
from senti_aggregate import recompute_company

_ctx = ssl.create_default_context(); _ctx.check_hostname = False; _ctx.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
CORE_TICKERS = ["300308.SZ", "300502.SZ", "300394.SZ", "601138.SH", "000977.SZ", "688008.SH",
                "002371.SZ", "002156.SZ", "002463.SZ", "301308.SZ", "688981.SH", "002230.SZ"]


def popularity_map():
    try:
        body = json.dumps({"appId": "appId01", "globalId": "786e4c21", "marketType": "", "pageNo": 1, "pageSize": 100})
        req = urllib.request.Request("https://emappdata.eastmoney.com/stockrank/getAllCurrentList",
                                     data=body.encode(), headers={"User-Agent": UA, "Content-Type": "application/json"})
        d = json.loads(urllib.request.urlopen(req, timeout=12, context=_ctx).read())
        return {it.get("sc"): it.get("rk") for it in d.get("data", [])}
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=len(CORE_TICKERS))
    ap.add_argument("--pages", type=int, default=3)
    args = ap.parse_args()
    con = common.get_senti_db()
    common.assert_senti_only(con)                       # 门C
    try:
        con.execute("ALTER TABLE senti_post ADD COLUMN time_caliber TEXT")    # T10 口径列(幂等)
    except Exception:
        pass
    comps, _ = common.load_closed_set()

    rc = common.research_ro_conn()
    pool = []
    for tk in CORE_TICKERS[:args.limit]:
        row = rc.execute("SELECT id, name FROM company WHERE ticker=?", (tk,)).fetchone()
        if row and row[0] in comps:
            pool.append((row[0], row[1], tk))
        else:
            print(f"  [skip] {tk} 不在 research.db 闭集")
    rc.close()
    print(f"核心池: {len(pool)} 只\n")
    pop = popularity_map()
    now = common.now_iso()
    stat = {"ok": 0, "empty": 0, "posts_new": 0, "bad_time": 0}

    for cid, name, tk in pool:
        code = tk.split(".")[0]; market = "0" if tk.endswith(".SZ") else "1"
        posts, bad = fetch_guba_posts(code, pages=args.pages)
        stat["bad_time"] += bad
        if not posts:
            stat["empty"] += 1
            print(f"  ?? {name:<10}{tk} 股吧空/被挡(覆盖弱,不造数;时间废 {bad})")
            continue
        src = f"https://guba.eastmoney.com/list,{code}.html"
        ins = 0
        for p in posts:
            r = con.execute("""INSERT OR IGNORE INTO senti_post
                (company_id,ticker,post_id,post_url,ts_hour,trade_date,posted_at,title,read_count,reply_count,
                 time_caliber,source_url,as_of,fetched_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cid, tk, p["post_id"], p["post_url"], p["ts_hour"], p["trade_date"], p["posted_at"],
                 p["title"], p["read"], p["reply"], p.get("time_caliber"), src, p["trade_date"], now))
            ins += r.rowcount
        stat["posts_new"] += ins
        recompute_company(con, cid, now)
        # 人气榜(日级辅助)→ 最新日
        rank = pop.get(("SZ" if market == "0" else "SH") + code)
        if rank:
            con.execute("""UPDATE senti_discussion_daily SET popularity_rank=?
                           WHERE company_id=? AND trade_date=(SELECT MAX(trade_date) FROM senti_discussion_daily WHERE company_id=?)""",
                        (rank, cid, cid))
        con.commit()
        stat["ok"] += 1
        latest = max(p["ts_hour"] for p in posts)
        print(f"  ?? {name:<10}{tk} 新帖{ins} 最新{latest} 人气#{rank} 废时间{bad}")
        time.sleep(1.0)

    # ?? 门日期终检:任何非法 trade_date/ts_hour 入库 → 报警
    badpost = con.execute("SELECT COUNT(*) FROM senti_post WHERE trade_date NOT GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]'").fetchone()[0]
    print(f"\n=== M1/T2:成功 {stat['ok']} / 空 {stat['empty']} / 新帖 {stat['posts_new']} / 时间校验废 {stat['bad_time']} ===")
    print(f"门日期检查:senti_post 非法日期 {badpost}(应0)")
    if badpost:
        print("!!! 门日期触发:有非法日期入库,校验门未生效 → 停查", file=sys.stderr)
    con.close()


if __name__ == "__main__":
    main()
