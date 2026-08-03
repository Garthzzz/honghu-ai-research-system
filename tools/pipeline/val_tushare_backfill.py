#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tushare 估值回填(A 股,默认硅片#18 + 测试机#19)。

替代旧 `val_wind_backfill.py`。只写 Tushare 快照，不使用 Wind。
"""
from __future__ import annotations

import argparse
import math
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "pipeline"))

import db_writer
from tushare_provider import fetch_daily_basic_latest, fnum, get_or_create_tushare_source


TODAY = date.today().isoformat()
DEFAULT_INDS = (18, 19)


def clean_num(v, *, positive: bool = True):
    x = fnum(v)
    if x is None:
        return None
    if positive and x <= 0:
        return None
    if math.isinf(x) or math.isnan(x):
        return None
    return x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--industries", default="18,19", help="逗号分隔行业 id，默认 18,19")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    inds = tuple(int(x) for x in args.industries.split(",") if x.strip()) or DEFAULT_INDS

    conn = db_writer.get_db()
    src = get_or_create_tushare_source(conn, title="Tushare A股估值快照")
    conn.commit()

    rows = conn.execute(
        f"""SELECT DISTINCT c.id, c.name, c.ticker, MIN(ci.industry_id) AS industry_id
            FROM company c JOIN company_industry ci ON ci.company_id=c.id
            WHERE ci.industry_id IN ({','.join('?' * len(inds))})
              AND (c.ticker LIKE '%.SH' OR c.ticker LIKE '%.SZ' OR c.ticker LIKE '%.BJ')
            GROUP BY c.id ORDER BY c.id""",
        inds,
    ).fetchall()
    if args.limit:
        rows = rows[: args.limit]

    ok = fail = dp = 0
    for r in rows:
        ticker = r["ticker"]
        try:
            snap = fetch_daily_basic_latest(ticker)
        except Exception as exc:
            fail += 1
            print(f"  Tushare 失败 {r['name']} {ticker}: {type(exc).__name__}:{str(exc)[:80]}")
            continue
        if not snap:
            fail += 1
            print(f"  Tushare 无估值 {r['name']} {ticker}")
            continue
        pe = clean_num(snap.get("pe_ttm"))
        pb = clean_num(snap.get("pb"))
        ps = clean_num(snap.get("ps_ttm") or snap.get("ps"))
        total_mv = clean_num(snap.get("total_mv"))
        market_cap_yi = round(total_mv / 10000, 2) if total_mv is not None else None
        trade_date = str(snap.get("trade_date") or TODAY)
        if pe is None and pb is None and ps is None and market_cap_yi is None:
            fail += 1
            print(f"  Tushare 无核心字段 {r['name']} {ticker}")
            continue
        conn.execute(
            """UPDATE company SET pe_ttm=?, pb=?, ps_ttm=?, market_cap_value=?,
               market_cap_unit='亿元', valuation_as_of=?, valuation_source_id=? WHERE id=?""",
            (pe, pb, ps, market_cap_yi, trade_date, src, r["id"]),
        )
        excerpt = (
            f"Tushare daily_basic {ticker} @{trade_date}: "
            f"pe_ttm={pe}, pb={pb}, ps_ttm={ps}, total_mv={total_mv}万元"
        )
        for metric, value, unit in (
            ("市盈率PE_TTM", pe, "倍"),
            ("市净率PB", pb, "倍"),
            ("市销率PS_TTM", ps, "倍"),
            ("总市值", market_cap_yi, "亿元"),
        ):
            if value is None:
                continue
            db_writer.write_data_point(
                conn,
                industry_id=r["industry_id"],
                metric=metric,
                period=trade_date[:4] + "Q" + str((int(trade_date[4:6]) - 1) // 3 + 1)
                if len(trade_date) >= 6 and trade_date[:6].isdigit()
                else TODAY[:7],
                unit=unit,
                source_id=src,
                source_excerpt=excerpt[:200],
                extraction_method="web_fetch",
                value_num=value,
                as_of_date=trade_date,
                company_id=r["id"],
                note="Tushare A股估值快照",
                auto_consensus=False,
            )
            dp += 1
        ok += 1
        print(f"  Tushare {r['name']} {ticker}: PE={pe} PB={pb} PS={ps} 市值={market_cap_yi}亿元")
    conn.commit()
    conn.close()
    print(f"完成:Tushare 估值成功 {ok} / 失败 {fail} / 数据点 {dp}")


if __name__ == "__main__":
    main()

