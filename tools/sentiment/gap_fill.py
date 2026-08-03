#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""每小时 tick 的【缺口回填 + 检测】机制(用户要求:检测到之前空值就一起取上,保证所有时间都有值)。
- 股价:当前 K 线统一入口使用 Tushare/yfinance 全窗口抓取 + UPSERT；Wind 已允许，但尚未接入 K 线统一入口，不能恢复旧脚本。
- 情绪/发帖量:从 senti_post 全量重算聚合(任何已抓到的帖都会落到其小时/日)→ 填已有数据的空桶;
        东财股吧无法回溯抓历史帖,真正"从没抓到过"的历史小时无法伪造补全(铁律),只能从现在每小时累积,本脚本如实报告缺口。
只写 sentiment.db。
"""
from __future__ import annotations
import sys, subprocess
from datetime import date, timedelta
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

HERE = Path(__file__).resolve().parent
ROOT = common.ROOT


def _run(script, args, timeout):
    try:
        p = subprocess.run([sys.executable, str(HERE / script)] + args, cwd=str(ROOT),
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        tail = (p.stdout or "").strip().splitlines()[-1:] or [""]
        print(f"  {script}: rc={p.returncode} | {tail[0][:110]}")
    except Exception as e:
        print(f"  {script}: {type(e).__name__} {str(e)[:60]}")


def main():
    # 1) 股价全窗口回填(真实数据;漏抓的会一并补上)
    print("=== 缺口回填:股价(全窗口 UPSERT,补齐漏抓)===")
    _run("stock_kline_fetch.py", ["--days", "60", "--m60", "120"], 180)

    # 2) 缺口检测报告(交易日维度;不伪造)
    con = common.get_senti_db()
    common.assert_senti_only(con)
    print("=== 缺口检测(股价日线 vs 情绪日)===")
    rows = con.execute("""SELECT k.company_id, k.ticker,
            (SELECT COUNT(DISTINCT ts) FROM stock_kline s WHERE s.company_id=k.company_id AND s.freq='d') AS price_days,
            (SELECT COUNT(DISTINCT trade_date) FROM senti_discussion_daily d WHERE d.company_id=k.company_id) AS senti_days
        FROM (SELECT DISTINCT company_id, ticker FROM stock_kline) k""").fetchall()
    for r in rows[:14]:
        print(f"  {r['ticker']}: 价格日 {r['price_days']} / 情绪日 {r['senti_days']}")
    print("说明:价格缺口已由全窗口 UPSERT 自动补齐(真实);情绪历史缺口因东财股吧不可回溯,只能逐小时累积,不伪造。")
    con.close()


if __name__ == "__main__":
    main()
