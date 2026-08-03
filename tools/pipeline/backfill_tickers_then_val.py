#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""第二轮:为无 ticker 的【可识别单一上市公司】补 ticker,然后 yfinance 取估值。

只补**确定的单一上市公司**(curated 映射,人工核对);**跳过**:
  - 聚合伪公司(名字含 + / / 顿号多家、"北美云厂商""九大CSP"等)
  - 未上市(xAI/华为/字节/SpaceX/Anthropic/OpenAI/长江存储/长鑫/智谱…)
不在映射表里的一律不动(留空待回填),绝不猜 ticker。
用法:python backfill_tickers_then_val.py [--sleep 0.6]
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

TODAY = date.today().isoformat()
CUR_UNIT = {"CNY": "亿元", "USD": "亿美元", "HKD": "亿港元", "KRW": "亿韩元", "JPY": "亿日元", "TWD": "亿新台币"}

# 公司名(db 中精确名)→ (ticker, listing_status)。仅确定的单一上市公司。
TMAP = {
    # 美股
    "英伟达": ("NVDA", "us"), "博通": ("AVGO", "us"), "思科": ("CSCO", "us"),
    "美满": ("MRVL", "us"), "Marvell": ("MRVL", "us"), "AMD": ("AMD", "us"),
    "英特尔": ("INTC", "us"), "康宁": ("GLW", "us"), "Ciena": ("CIEN", "us"),
    "诺基亚": ("NOK", "us"), "Semtech": ("SMTC", "us"), "微软": ("MSFT", "us"),
    "亚马逊": ("AMZN", "us"), "谷歌": ("GOOGL", "us"), "Meta": ("META", "us"),
    "世纪互联": ("VNET", "us"), "美光": ("MU", "us"), "西部数据": ("WDC", "us"),
    "希捷": ("STX", "us"), "高通": ("QCOM", "us"), "特斯拉": ("TSLA", "us"),
    "Lumentum": ("LITE", "us"), "Coherent": ("COHR", "us"), "应用材料": ("AMAT", "us"),
    "泛林": ("LRCX", "us"), "科天": ("KLAC", "us"), "Bloom Energy": ("BE", "us"),
    "GE Vernova": ("GEV", "us"), "Amkor": ("AMKR", "us"), "甲骨文": ("ORCL", "us"),
    # 台股
    "台积电": ("TSM", "us"), "联发科": ("2454.TW", "other_listed"),
    "日月光": ("3711.TW", "other_listed"), "鸿海": ("2317.TW", "other_listed"),
    "欣兴电子": ("3037.TW", "other_listed"), "世芯电子": ("3443.TW", "other_listed"),
    "广达": ("2382.TW", "other_listed"), "纬创": ("3231.TW", "other_listed"),
    "奇鋐": ("3017.TW", "other_listed"), "双鸿": ("3324.TW", "other_listed"),
    "台达电": ("2308.TW", "other_listed"),
    # 韩股/日股/欧股
    "韩美半导体": ("042700.KS", "kospi"), "ASML": ("ASML", "us"),
    "东京电子": ("8035.T", "tse"), "爱德万": ("6857.T", "tse"), "BESI": ("BESI.AS", "other_listed"),
    "ASMPT": ("0522.HK", "hk"),
    # A股(db 缺 ticker 的)
    "亨通光电": ("600487.SH", "a_share"), "烽火通信": ("600498.SH", "a_share"),
    "赛微电子": ("300456.SZ", "a_share"), "工业富联": ("601138.SH", "a_share"),
    "中天科技": ("600522.SH", "a_share"), "长飞光纤": ("601869.SH", "a_share"),
    "深南电路": ("002916.SZ", "a_share"), "兴森科技": ("002436.SZ", "a_share"),
    "国际复材": ("301526.SZ", "a_share"), "中国巨石": ("600176.SH", "a_share"),
    "天岳先进": ("688234.SH", "a_share"), "三安光电": ("600703.SH", "a_share"),
    "晶盛机电": ("300316.SZ", "a_share"), "盛合晶微": (None, None),  # 未上市占位,不动
}


def yf_ticker(t):
    t = (t or "").strip()
    return (t[:-3] + ".SS") if t.endswith(".SH") else t


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--sleep", type=float, default=0.6)
    args = ap.parse_args()
    conn = db_writer.get_db()
    vrow = conn.execute("SELECT id FROM source WHERE title='yfinance 估值快照' AND fetch_method='api_yfinance'").fetchone()
    vsrc = vrow["id"] if vrow else None
    if not vsrc:
        print("缺 yfinance 估值 source,请先跑 backfill_valuation_yf.py"); return

    ok = fail = skipped_unlisted = noname = 0
    for name, (tk, ls) in TMAP.items():
        if not tk:
            skipped_unlisted += 1; continue
        crow = conn.execute("SELECT id, ticker FROM company WHERE name=?", (name,)).fetchone()
        if not crow:
            noname += 1; continue
        # 补 ticker(若 db 已有 ticker 则不覆盖,只在缺时补)
        if not (crow["ticker"] or "").strip():
            conn.execute("UPDATE company SET ticker=?, listing_status=COALESCE(listing_status,?) WHERE id=?",
                         (tk, ls, crow["id"]))
        try:
            info = yf.Ticker(yf_ticker(tk)).info or {}
            pe = info.get("trailingPE"); pef = info.get("forwardPE")
            pb = info.get("priceToBook"); ps = info.get("priceToSalesTrailing12Months")
            mc = info.get("marketCap"); cur = (info.get("currency") or "").upper()
            if pe is None and pb is None and ps is None and mc is None:
                fail += 1; print(f"  ?? {name} ({tk}) 无估值字段"); continue
            mcv = round(mc/1e8, 2) if mc else None
            mcu = CUR_UNIT.get(cur, "亿("+cur+")") if mc else None
            conn.execute("""UPDATE company SET pe_ttm=?, pe_forward=?, pb=?, ps_ttm=?,
                            market_cap_value=?, market_cap_unit=?, valuation_as_of=?, valuation_source_id=?
                            WHERE id=?""",
                         (pe, pef, pb, ps, mcv, mcu, TODAY, vsrc, crow["id"]))
            ok += 1
            print(f"  ?? {name:<12}{tk:<11} PE={pe} PB={pb} PS={ps} 市值={mcv}{mcu or ''}")
        except Exception as e:
            fail += 1; print(f"  ?? {name} ({tk}): {type(e).__name__}:{str(e)[:50]}")
        if args.sleep:
            time.sleep(args.sleep)
    conn.commit()
    print(f"\n第二轮:成功 {ok} / 失败 {fail} / 跳过未上市占位 {skipped_unlisted} / db无此名 {noname}")
    conn.close()


if __name__ == "__main__":
    main()
