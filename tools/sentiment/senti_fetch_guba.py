#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""散户层 — 东财股吧抓取 → senti_raw(source_layer=retail, platform=guba)。

两种喂数:
  (a) crawl:Playwright 实抓各公司股吧(复用 eastmoney_guba),用于当前桶 + 近期补抓。
  (b) import:把既有 senti_post(已抓 13k+ 帖,部分已 DeepSeek 打标)迁入 senti_raw,
      复用历史 + 已有标签,免重爬(6/12 起历史一次到位)。

attitude 尺度对齐星瀚:看涨→1(正) 看跌→2(负) 中性→3(中);未打标 → NULL(待 senti_score)。
attitude_src='deepseek_self'(自算非原生,tier≤2)。只写 sentiment.db。
"""
from __future__ import annotations
import json
import sys, argparse
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common, senti3
from eastmoney_guba import GubaBrowser, fetch_guba_posts

GUBA_WEB, GUBA_DOMAIN = "东方财富股吧", "guba.eastmoney.com"
# senti_post.label_score → attitude(1正2负3中)
def _score_to_att(label, score):
    if label is None:
        return None
    if score is None:
        return 3
    return 1 if score > 0 else (2 if score < 0 else 3)


def _att_from_label(label):
    return {"看涨": 1, "看跌": 2, "中性": 3}.get(label)


def write_raw(con, *, bucket_id, company_id, ticker, attitude, post_id, title, url,
              publish_time, backfilled, now, reason=None, read_count=None, reply_count=None,
              reply_weight=3):
    """写 senti_raw(股吧)。存 read/reply + 每帖 heat_value(read+reply*w);
    ??重抓时同 post_id 已存在(INSERT OR IGNORE 不更新)→ 显式 UPDATE 刷新 read/reply/heat(补近端热度)。"""
    hv = senti3.heat_value("guba", None, read_count, reply_count, reply_weight)
    n = senti3.insert_raw(con, bucket_id=bucket_id, company_id=company_id, ticker=ticker,
        source_layer="retail", platform="guba", attitude=attitude, attitude_src="deepseek_self",
        dedup_key=str(post_id), post_id=str(post_id), title=title, url=url,
        web_name=GUBA_WEB, domain=GUBA_DOMAIN, publish_time=publish_time, reason=reason,
        read_count=read_count, reply_count=reply_count, heat_value=hv,
        as_of=(publish_time or now)[:10], fetched_at=now, backfilled=backfilled)
    if n == 0 and (read_count is not None or reply_count is not None):
        # 已存在(重抓):刷新热度,补近端 read/reply(原 import 帖此前可能无热度)
        con.execute("""UPDATE senti_raw SET read_count=?, reply_count=?, heat_value=?
                       WHERE company_id=? AND source_layer='retail' AND dedup_key=?""",
                    (read_count, reply_count, hv, company_id, str(post_id)))
    return n


def import_from_senti_post(con, now):
    """既有 senti_post → senti_raw(retail/guba)。按 posted_at 分桶,复用已有标签。"""
    rows = con.execute("""SELECT company_id, ticker, post_id, post_url, posted_at, ts_hour,
                                 title, sentiment_label, label_score, read_count, reply_count
                          FROM senti_post WHERE title IS NOT NULL AND TRIM(title)<>''""").fetchall()
    n_in = 0
    for r in rows:
        pa = r["posted_at"] or r["ts_hour"]
        dt = senti3.iso_to_dt(pa) if pa else None
        if not dt:
            continue
        b = senti3.bucket_for(dt)
        att = _att_from_label(r["sentiment_label"])
        n_in += write_raw(con, bucket_id=b["bucket_id"], company_id=r["company_id"], ticker=r["ticker"],
                          attitude=att, post_id=r["post_id"], title=r["title"], url=r["post_url"],
                          publish_time=dt.isoformat(timespec="minutes"), backfilled=1, now=now,
                          read_count=r["read_count"], reply_count=r["reply_count"])
    con.commit()
    return len(rows), n_in


def _local_dt(value):
    dt = senti3.iso_to_dt(value) if value else None
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=senti3.TZ)
    return dt.astimezone(senti3.TZ) if dt is not None else None


def _inside_window(dt, window):
    return window is None or any(start <= dt < end for start, end in window.segments)


def crawl_company(con, company_id, ticker, pages, now, backfilled=0, window=None,
                  fetcher=fetch_guba_posts):
    code = (ticker or "").split(".")[0]
    if not code.isdigit():
        return 0, 0, 0, 0, 0, "invalid_ticker"
    posts, bad, error = fetcher(
        code, pages=pages, with_status=True,
        window_start=(window.window_start if window is not None else None),
    )
    n_in = matched = excluded = 0
    for p in posts:
        dt = _local_dt(p.get("posted_at"))
        if not dt:
            continue
        # V2 新流程连中间原始行也不接收周末；指定 window 时再做精确半开边界过滤。
        if dt.weekday() >= 5 or not _inside_window(dt, window):
            excluded += 1
            continue
        matched += 1
        b = senti3.bucket_for(dt)
        n_in += write_raw(con, bucket_id=b["bucket_id"], company_id=company_id, ticker=ticker,
                          attitude=None, post_id=p["post_id"], title=p["title"], url=p.get("post_url"),
                          publish_time=dt.isoformat(timespec="minutes"), backfilled=backfilled, now=now,
                          read_count=p.get("read"), reply_count=p.get("reply"))
    con.commit()
    return len(posts), matched, excluded, n_in, bad, error


def parse_window_id(value):
    try:
        session_text, slot = value.split(":", 1)
        session_date = datetime.strptime(session_text, "%Y-%m-%d").date()
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"非法 window id: {value!r}") from exc
    return senti3.market_window(session_date, slot)


def load_universe(con):
    """动态 A 股全集：research canonical + 已验证且未 redirect 的 senti_company。"""
    rc = common.research_ro_conn()
    rows = rc.execute("""SELECT id, name, ticker FROM company
                         WHERE (ticker LIKE '%.SZ' OR ticker LIKE '%.SH'
                            OR ticker LIKE '%.SS' OR ticker LIKE '%.BJ')
                           AND LOWER(COALESCE(listing_status,'')) NOT IN
                               ('delisted','unlisted','private','private_subsidiary','pre_ipo','inactive','ceased')
                         ORDER BY id""").fetchall()
    rc.close()
    universe = {int(r["id"]): (int(r["id"]), r["name"], str(r["ticker"]).upper()) for r in rows}
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    redirected = set()
    if "company_id_redirect" in tables:
        redirected = {int(r[0]) for r in con.execute("SELECT old_company_id FROM company_id_redirect")}
    if "senti_company" in tables:
        for row in con.execute(
            "SELECT id,name,ticker FROM senti_company WHERE ticker IS NOT NULL AND TRIM(ticker)<>''"
        ):
            company_id = int(row["id"])
            ticker = str(row["ticker"] or "").strip().upper()
            if company_id in redirected or not ticker[:6].isdigit() or ticker[-3:] not in {".SZ", ".SH", ".BJ"}:
                continue
            universe[company_id] = (company_id, row["name"], ticker)
    return [universe[key] for key in sorted(universe)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--import-existing", action="store_true", help="从 senti_post 迁入历史")
    ap.add_argument("--crawl", action="store_true", help="Playwright 实抓股吧")
    default_pages = int(
        (senti3.load_layer_config().get("guba", {}) or {}).get("pages_per_stock", 128)
    )
    ap.add_argument("--pages", type=int, default=default_pages)
    ap.add_argument("--limit", type=int, default=0, help="只爬前 N 家(测试用,0=全部)")
    ap.add_argument("--backfilled", type=int, default=0)
    ap.add_argument("--window-id", help="V2 窗口 YYYY-MM-DD:preopen|morning|afternoon")
    args = ap.parse_args()
    con = common.get_senti_db()
    common.assert_senti_only(con)                      # 门C
    now = common.now_iso()

    if args.import_existing:
        nrows, nin = import_from_senti_post(con, now)
        print(f"[import] senti_post {nrows} 帖 → senti_raw 新增 {nin}")

    window = parse_window_id(args.window_id) if args.window_id else None
    if args.window_id:
        args.crawl = True

    exit_code = 0
    if args.crawl:
        uni = load_universe(con)
        if args.limit:
            uni = uni[:args.limit]
        tot_posts = tot_matched = tot_excluded = tot_in = ok = failures = 0
        failed_items = []
        try:
            with GubaBrowser() as browser:
                for cid, name, ticker in uni:
                    try:
                        np, nm, ne, ni, bad, error = crawl_company(
                            con, cid, ticker, args.pages, now, args.backfilled,
                            window=window, fetcher=browser.fetch,
                        )
                        tot_posts += np; tot_matched += nm; tot_excluded += ne; tot_in += ni
                        if error:
                            failures += 1
                            failed_items.append({"company_id": cid, "ticker": ticker, "error": error,
                                                 "posts_seen": np, "window_posts": nm})
                            print(f"  [{ticker}] {name}: PARTIAL {error} | 帖 {np} 窗口内 {nm} 新增 {ni}")
                        else:
                            ok += 1
                            print(f"  [{ticker}] {name}: 帖 {np} 窗口内 {nm} 新增 {ni} 时间坏值 {bad}")
                    except Exception as e:
                        failures += 1
                        failed_items.append({"company_id": cid, "ticker": ticker,
                                             "error": f"{type(e).__name__}:{str(e)[:120]}",
                                             "posts_seen": 0, "window_posts": 0})
                        print(f"  [{ticker}] {name}: ERR {type(e).__name__} {str(e)[:60]}")
        except Exception as e:
            failures += max(len(uni) - ok - failures, 1)
            print(f"  [guba browser] ERR {type(e).__name__} {str(e)[:120]}")
        result = {
            "ok": failures == 0,
            "companies": len(uni),
            "fetch_ok": ok,
            "failures": failures,
            "posts_seen": tot_posts,
            "window_posts": tot_matched,
            "excluded": tot_excluded,
            "inserted": tot_in,
            "failed_items": failed_items,
            "window_id": window.window_id if window else None,
        }
        print(f"[crawl] {ok}/{len(uni)} 请求成功 | 总帖 {tot_posts} 窗口内 {tot_matched} 新增 {tot_in}")
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        exit_code = 2 if failures else 0

    n_raw = con.execute("SELECT COUNT(*) FROM senti_raw WHERE platform='guba'").fetchone()[0]
    print(f"=== senti_raw guba 总计 {n_raw} 行 ===")
    con.close()
    return exit_code


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
