#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""历史 yfinance 专用估值回填工具；本脚本只使用 yfinance。

只填 PE(TTM/Forward)/PB/PS + 市值(SOP #8:不填复合倍数 EV/EBITDA/PEG/ROE/ROA)。
- 覆盖 11 行业(1/6/7/8/9/10/12/13/15/16/17)所有有 ticker 的 company。
- ticker→yfinance:.SH→.SS(上海),余原样。市值按 currency 换算为「亿+本币单位」。
- valuation_as_of=今日;source=yfinance(三方数据 tier3,fetch_method=api_yfinance)。
- 取不到的字段留空(None),不编造;失败公司记入报告。
用法:python backfill_valuation_yf.py [--limit N] [--sleep 0.6]
"""
from __future__ import annotations
import sys, time, argparse
from datetime import date
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
import db_writer
import yfinance as yf

INDS = (1, 6, 7, 8, 9, 10, 12, 13, 15, 16, 17)
TODAY = date.today().isoformat()
CUR_UNIT = {"CNY": "亿元", "USD": "亿美元", "HKD": "亿港元", "KRW": "亿韩元", "JPY": "亿日元", "TWD": "亿新台币"}


def yf_ticker(t: str):
    t = (t or "").strip()
    if not t:
        return None
    return t[:-3] + ".SS" if t.endswith(".SH") else t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0.6)
    args = ap.parse_args()
    conn = db_writer.get_db()

    # 估值 source(幂等:按 title 复用)
    row = conn.execute("SELECT id FROM source WHERE title=? AND fetch_method='api_yfinance'",
                       (f"yfinance 估值快照",)).fetchone()
    if row:
        vsrc = row["id"]
    else:
        vsrc = conn.execute(
            """INSERT INTO source(title, source_type, publisher, publish_date, quality_tier,
                is_forward_looking, value_layer, fetch_method, source_credibility, language,
                is_primary_source, source_subtype, url)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("yfinance 估值快照", "三方数据", "Yahoo Finance (yfinance)", TODAY, 3, 0,
             "公司专项", "api_yfinance", "unverified", "en", 0, "financial_database",
             "https://finance.yahoo.com/")).lastrowid
        conn.commit()
    print(f"估值 source #{vsrc} | as_of={TODAY}")

    rows = conn.execute(f"""
        SELECT DISTINCT c.id, c.name, c.ticker
        FROM company c JOIN company_industry ci ON ci.company_id=c.id
        WHERE ci.industry_id IN ({','.join('?'*len(INDS))})
          AND c.ticker IS NOT NULL AND TRIM(c.ticker)<>''
        ORDER BY c.id""", INDS).fetchall()
    if args.limit:
        rows = rows[:args.limit]
    print(f"待回填(有 ticker)公司:{len(rows)}\n")

    ok = fail = 0
    failed = []
    for r in rows:
        ytk = yf_ticker(r["ticker"])
        try:
            info = yf.Ticker(ytk).info or {}
            pe = info.get("trailingPE"); pef = info.get("forwardPE")
            pb = info.get("priceToBook"); ps = info.get("priceToSalesTrailing12Months")
            mc = info.get("marketCap"); cur = (info.get("currency") or "").upper()
            # 至少要拿到一个核心估值字段才算成功,否则记失败(不写空快照)
            if pe is None and pb is None and ps is None and mc is None:
                fail += 1; failed.append((r["name"], ytk, "无估值字段")); continue
            mc_val = round(mc / 1e8, 2) if mc else None       # → 亿(本币)
            mc_unit = CUR_UNIT.get(cur, "亿(" + cur + ")") if mc else None
            conn.execute("""UPDATE company SET pe_ttm=?, pe_forward=?, pb=?, ps_ttm=?,
                            market_cap_value=?, market_cap_unit=?, valuation_as_of=?, valuation_source_id=?
                            WHERE id=?""",
                         (pe, pef, pb, ps, mc_val, mc_unit, TODAY, vsrc, r["id"]))
            ok += 1
            print(f"  {r['name']:<14}{ytk:<12} PE={pe} PB={pb} PS={ps} 市值={mc_val}{mc_unit or ''}")
        except Exception as e:
            fail += 1; failed.append((r["name"], ytk, f"{type(e).__name__}:{str(e)[:50]}"))
        if args.sleep:
            time.sleep(args.sleep)
    conn.commit()

    print(f"\n=== 回填完成:成功 {ok} / 失败 {fail} (留空待回填,不编造)===")
    if failed:
        print("失败清单(留空,可重试):")
        for nm, tk, why in failed[:60]:
            print(f"  - {nm} ({tk}): {why}")
    # 按行业汇总已填
    print("\n=== 各行业已填估值公司数 ===")
    for iid in INDS:
        n = conn.execute("""SELECT COUNT(DISTINCT c.id) FROM company c JOIN company_industry ci ON ci.company_id=c.id
                            WHERE ci.industry_id=? AND c.pe_ttm IS NOT NULL""", (iid,)).fetchone()[0]
        nm = conn.execute("SELECT name FROM industry WHERE id=?", (iid,)).fetchone()["name"]
        print(f"  #{iid} {nm}: {n}")
    conn.close()


if __name__ == "__main__":
    main()
