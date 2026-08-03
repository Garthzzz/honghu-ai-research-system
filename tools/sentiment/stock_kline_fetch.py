#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""动态公司全集 OHLCV 更新，当前实现使用 Tushare 与 Yahoo Finance/yfinance。

Wind 已在全局策略中允许，但尚未接入本 K 线入口；若后续加入，必须保留这里的
公司全集、去重、partial 状态传播和 UPSERT 门禁，不能恢复旧 Wind 脚本。

公司池实时读取 research.db 中所有具有合法 ticker 的公司，并补充 sentiment.db
中少量已经人工核验 ticker、且未被 identity redirect 的本地公司。相同 ticker 只
请求一次，结果再写给对应公司，避免重复外部调用。

默认将任一频率缺失视为 partial 并返回非零；只有显式 ``--allow-partial`` 才允许
调度器忽略部分失败。最后一行始终输出结构化 JSON，供 slot tick 可靠传播状态。
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools" / "pipeline"))

import common
import yfinance as yf
from tushare_provider import call_tushare, fetch_daily_rows, is_a_share_ticker, ts_code_from_ticker


VALID_TICKER = re.compile(r"^[A-Z0-9^][A-Z0-9.^=_-]{0,19}$")
YF_SYMBOL_OVERRIDES = {"3324.TW": "3324.TWO"}
# 598 新光电气（SHINKO 6967.T）已由公司官方确认于 2025-06-06 退市；
# 在旧 research.db 尚未同步 listing_status 时也必须排除。
EXCLUDED_COMPANY_IDS = {598}
EXCLUDED_LISTING_STATUSES = {
    "delisted",
    "unlisted",
    "private",
    "private_subsidiary",
    "pre_ipo",
    "inactive",
    "ceased",
}


@dataclass(frozen=True)
class UniverseCompany:
    company_id: int
    name: str
    ticker: str
    origin: str


def normalize_ticker(value: str | None) -> str | None:
    ticker = str(value or "").strip().upper()
    return ticker if ticker and VALID_TICKER.fullmatch(ticker) else None


def load_universe(
    research_con,
    sentiment_con=None,
    *,
    company_ids: set[int] | None = None,
    tickers: set[str] | None = None,
) -> list[UniverseCompany]:
    """实时构建 K 线公司池；选择器存在时按 id/ticker 的并集筛选。"""
    selected_ids = {int(value) for value in (company_ids or set())}
    selected_tickers = {
        ticker for value in (tickers or set()) if (ticker := normalize_ticker(value))
    }

    def wanted(company_id: int, ticker: str) -> bool:
        if not selected_ids and not selected_tickers:
            return True
        return company_id in selected_ids or ticker in selected_tickers

    out: dict[int, UniverseCompany] = {}
    company_columns = {
        str(row[1]) for row in research_con.execute("PRAGMA table_info(company)")
    }
    status_sql = "listing_status" if "listing_status" in company_columns else "NULL AS listing_status"
    research_rows = research_con.execute(
        f"SELECT id,name,ticker,{status_sql} FROM company ORDER BY id"
    ).fetchall()
    eligible_rows = [
        row
        for row in research_rows
        if int(row["id"]) not in EXCLUDED_COMPANY_IDS
        and str(row["listing_status"] or "").strip().lower() not in EXCLUDED_LISTING_STATUSES
    ]
    research_names = {int(row["id"]): str(row["name"]) for row in eligible_rows}
    for row in eligible_rows:
        ticker = normalize_ticker(row["ticker"])
        if ticker and wanted(int(row["id"]), ticker):
            out[int(row["id"])] = UniverseCompany(
                int(row["id"]), str(row["name"]), ticker, "research"
            )

    if sentiment_con is not None:
        tables = {
            row[0]
            for row in sentiment_con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "senti_company" in tables:
            redirected = set()
            if "company_id_redirect" in tables:
                redirected = {
                    int(row[0])
                    for row in sentiment_con.execute("SELECT old_company_id FROM company_id_redirect")
                }
            for row in sentiment_con.execute(
                "SELECT id,name,ticker FROM senti_company "
                "WHERE ticker IS NOT NULL AND TRIM(ticker)<>'' ORDER BY id"
            ):
                company_id = int(row["id"])
                ticker = normalize_ticker(row["ticker"])
                if company_id in redirected or not ticker or not wanted(company_id, ticker):
                    continue
                out.setdefault(
                    company_id,
                    UniverseCompany(company_id, str(row["name"]), ticker, "sentiment_verified"),
                )
        # Canonical research company 的 ticker 可能尚未同步回 research.db；V2 迁移会
        # 用 Tushare 精确身份在 company_alias 留下已验证 ticker，K 线全集从此补齐。
        if "company_alias" in tables:
            for row in sentiment_con.execute(
                "SELECT company_id,ticker FROM company_alias "
                "WHERE ticker IS NOT NULL AND TRIM(ticker)<>'' ORDER BY company_id,id"
            ):
                company_id = int(row["company_id"])
                ticker = normalize_ticker(row["ticker"])
                if (
                    company_id not in research_names
                    or company_id in out
                    or not ticker
                    or not wanted(company_id, ticker)
                ):
                    continue
                out[company_id] = UniverseCompany(
                    company_id, research_names[company_id], ticker, "verified_alias"
                )
    return sorted(out.values(), key=lambda item: (item.ticker, item.company_id))


def yf_ticker(ticker: str) -> str:
    ticker = ticker.strip().upper()
    if ticker in YF_SYMBOL_OVERRIDES:
        return YF_SYMBOL_OVERRIDES[ticker]
    if ticker.endswith(".SH"):
        return ticker[:-3] + ".SS"
    if ticker.endswith(".HK"):
        code = ticker[:-3]
        if code.isdigit():
            # Tushare/交易所使用五位代码（如 09888.HK），Yahoo 使用四位 9888.HK。
            return f"{int(code):04d}.HK"
    return ticker


def fnum(value):
    try:
        number = float(value)
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def compact_date(days: int) -> tuple[str, str]:
    end = datetime.now().date()
    start = end - timedelta(days=days + 10)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def fetch_daily_tushare(ticker: str, days: int) -> tuple[list[dict], str]:
    ts_code = ts_code_from_ticker(ticker)
    if not ts_code:
        return [], ""
    start, end = compact_date(days)
    rows = fetch_daily_rows(ts_code, start_date=start, end_date=end)
    out = []
    for row in rows[:days]:
        trade_date = str(row.get("trade_date") or "")
        if len(trade_date) != 8:
            continue
        out.append(
            {
                "ts": f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}",
                "o": fnum(row.get("open")),
                "h": fnum(row.get("high")),
                "l": fnum(row.get("low")),
                "c": fnum(row.get("close")),
                "vol": (fnum(row.get("vol")) or 0) * 100 if row.get("vol") is not None else None,
                "amount": (fnum(row.get("amount")) or 0) * 1000 if row.get("amount") is not None else None,
                "source": "tushare",
                "source_url": "https://tushare.pro/document/2?doc_id=27",
            }
        )
    return out, "tushare"


def fetch_realtime_hourly_tushare(tickers: list[str]) -> tuple[dict[str, list[dict]], str | None]:
    """批量兜底 yfinance 不支持的 A 股 60 分钟线。

    Tushare 官方 ``rt_min`` 支持逗号分隔多代码，正好避免 ``stk_mins`` 在当前
    账户上的单代码小时级限频。这里只返回当前交易日已形成的 60 分钟 bar；历史
    数据仍保留原库，不为凑长度伪造。
    """
    canonical = {ts_code_from_ticker(ticker): ticker for ticker in tickers}
    canonical.pop(None, None)
    if not canonical:
        return {}, "empty_a_share_universe"
    try:
        rows = call_tushare(
            "rt_min",
            {"ts_code": ",".join(sorted(canonical)), "freq": "60MIN"},
            "ts_code,time,open,close,high,low,vol,amount",
        )
    except Exception as exc:
        return {}, f"{type(exc).__name__}:{str(exc)[:160]}"
    grouped = {ticker: [] for ticker in canonical.values()}
    for row in rows:
        ticker = canonical.get(str(row.get("ts_code") or "").strip().upper())
        trade_time = str(row.get("time") or "").strip()
        if ticker is None or len(trade_time) < 16:
            continue
        item = {
            "ts": trade_time[:16],
            "o": fnum(row.get("open")), "h": fnum(row.get("high")),
            "l": fnum(row.get("low")), "c": fnum(row.get("close")),
            "vol": fnum(row.get("vol")), "amount": fnum(row.get("amount")),
            "source": "tushare",
            "source_url": "https://tushare.pro/document/2?doc_id=374",
        }
        if None not in (item["o"], item["h"], item["l"], item["c"]):
            grouped[ticker].append(item)
    for values in grouped.values():
        values.sort(key=lambda row: row["ts"])
    return grouped, None


def apply_realtime_hourly_fallback(cache: dict[str, dict]) -> dict:
    missing = sorted(
        ticker for ticker, result in cache.items()
        if result.get("request_hourly") and not result.get("hourly") and is_a_share_ticker(ticker)
    )
    if not missing:
        return {"requested": 0, "filled": 0, "error": None}
    grouped, error = fetch_realtime_hourly_tushare(missing)
    filled = 0
    for ticker in missing:
        rows = grouped.get(ticker) or []
        if rows:
            cache[ticker]["hourly"] = rows
            cache[ticker]["errors"] = [item for item in cache[ticker]["errors"] if item != "60m_missing"]
            filled += 1
        elif error:
            cache[ticker]["warnings"].append(f"tushare_rt_min:{error}")
    return {"requested": len(missing), "filled": filled, "error": error}


def fetch_yfinance(
    ticker: str,
    *,
    period: str,
    interval: str,
    now: datetime | None = None,
) -> tuple[list[dict], str | None]:
    """返回数据与显式错误，并对非空但滞后的日线做一次定向重试。"""
    symbol = yf_ticker(ticker)
    try:
        ticker_client = yf.Ticker(symbol)
        history = ticker_client.history(
            period=period, interval=interval, auto_adjust=False
        )
    except Exception as exc:  # provider 错误必须上抛到结构化状态
        return [], f"{type(exc).__name__}:{str(exc)[:160]}"
    if history is None or getattr(history, "empty", True):
        return [], "empty_result"
    def parse_rows(frame) -> list[dict]:
        out = []
        for index, row in frame.iterrows():
            ts = index.strftime("%Y-%m-%d" if interval == "1d" else "%Y-%m-%d %H:%M")
            item = {
                "ts": ts,
                "o": fnum(row.get("Open")),
                "h": fnum(row.get("High")),
                "l": fnum(row.get("Low")),
                "c": fnum(row.get("Close")),
                "vol": fnum(row.get("Volume")),
                "amount": None,
                "source": "yfinance",
                "source_url": f"https://finance.yahoo.com/quote/{symbol}",
            }
            # 对股票日线，缺少/为零成交量的“平线”不能证明真实成交；Yahoo
            # 会在拆股停牌期生成这种伪 bar。小时线仍允许上游缺 volume。
            if None not in (item["o"], item["h"], item["l"], item["c"]) and (
                interval != "1d" or item["vol"] is not None
            ):
                out.append(item)
        return out

    valid = parse_rows(history)
    if not valid:
        return [], "no_valid_ohlc"
    if interval != "1d":
        return valid, None

    index_tz = getattr(getattr(history, "index", None), "tz", None)
    local_now = now or datetime.now(index_tz)
    if local_now.tzinfo is not None and index_tz is not None:
        local_now = local_now.astimezone(index_tz)
    expected = local_now.date()
    # 通用股票市场保守口径：本地 16:00 前只要求上一工作日，避免把
    # 尚未收盘的当日误判缺失；节假日会触发一次无害重试并留下 warning。
    if local_now.hour < 16:
        expected -= timedelta(days=1)
    while expected.weekday() >= 5:
        expected -= timedelta(days=1)
    latest = date.fromisoformat(max(row["ts"][:10] for row in valid))
    if latest >= expected:
        return valid, None

    retry_start = (expected - timedelta(days=21)).isoformat()
    retry_end = (expected + timedelta(days=1)).isoformat()
    try:
        retry_history = ticker_client.history(
            start=retry_start,
            end=retry_end,
            interval=interval,
            auto_adjust=False,
            repair=True,
        )
        retry_rows = parse_rows(retry_history) if retry_history is not None else []
    except Exception as exc:
        return valid, (
            f"stale_latest:{latest.isoformat()}<expected:{expected.isoformat()};"
            f"retry_{type(exc).__name__}:{str(exc)[:100]}"
        )
    merged = {row["ts"]: row for row in valid}
    merged.update({row["ts"]: row for row in retry_rows})
    valid = [merged[key] for key in sorted(merged)]
    latest = date.fromisoformat(max(row["ts"][:10] for row in valid))
    warning = (
        f"stale_latest_repaired:{expected.isoformat()}"
        if latest >= expected
        else f"stale_latest:{latest.isoformat()}<expected:{expected.isoformat()};retry_exhausted"
    )
    return valid, warning


def fetch_ticker(ticker: str, *, days: int, m60: int, mode: str = "full") -> dict:
    if mode not in {"full", "intraday", "close"}:
        raise ValueError(f"unknown Kline mode: {mode}")
    request_daily = mode != "intraday"
    request_hourly = True
    a_share = is_a_share_ticker(ticker)
    warnings = []
    daily_rows = []
    if request_daily and a_share:
        try:
            daily_rows, _ = fetch_daily_tushare(ticker, days)
            if not daily_rows:
                warnings.append("tushare:empty_result")
        except Exception as exc:
            warnings.append(f"tushare:{type(exc).__name__}:{str(exc)[:160]}")
    if request_daily and not daily_rows:
        daily_period = f"{max(days, 30)}d" if mode == "full" else "10d"
        daily_rows, daily_error = fetch_yfinance(
            ticker, period=daily_period, interval="1d"
        )
        if daily_error:
            warnings.append(f"yfinance_daily:{daily_error}")
    # 盘中定时任务随后会用一次 Tushare ``rt_min`` 批量请求补齐全部 A 股。
    # 这里不能先逐票调用 Yahoo：这会浪费数百次请求并把海外 ticker 的额度耗尽。
    if mode == "intraday" and a_share:
        hourly_rows, hourly_error = [], None
    else:
        hourly_period = "90d" if mode == "full" else "5d"
        hourly_rows, hourly_error = fetch_yfinance(
            ticker, period=hourly_period, interval="60m"
        )
    hourly_rows = hourly_rows[-m60:] if m60 > 0 else hourly_rows
    if hourly_error:
        warnings.append(f"yfinance_60m:{hourly_error}")
    errors = []
    if request_daily and not daily_rows:
        errors.append("daily_missing")
    if request_hourly and not hourly_rows:
        errors.append("60m_missing")
    return {
        "daily": daily_rows,
        "hourly": hourly_rows,
        "warnings": warnings,
        "errors": errors,
        "request_daily": request_daily,
        "request_hourly": request_hourly,
        "mode": mode,
    }


def upsert_rows(con, company_id: int, ticker: str, freq: str, rows: list[dict], now: str) -> int:
    count = 0
    for row in rows:
        if None in (row.get("o"), row.get("h"), row.get("l"), row.get("c")):
            continue
        con.execute(
            """INSERT INTO stock_kline(
                 company_id,ticker,freq,ts,o,h,l,c,vol,amount,source,source_url,as_of,fetched_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(company_id,freq,ts) DO UPDATE SET
                 ticker=excluded.ticker,o=excluded.o,h=excluded.h,l=excluded.l,c=excluded.c,
                 vol=excluded.vol,amount=excluded.amount,source=excluded.source,
                 source_url=excluded.source_url,as_of=excluded.as_of,fetched_at=excluded.fetched_at""",
            (
                company_id,
                ticker,
                freq,
                row["ts"],
                row["o"],
                row["h"],
                row["l"],
                row["c"],
                row.get("vol"),
                row.get("amount"),
                row["source"],
                row.get("source_url"),
                row["ts"][:10],
                now,
            ),
        )
        count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--m60", type=int, default=80)
    parser.add_argument(
        "--mode",
        choices=("full", "intraday", "close"),
        default="full",
        help="full=日线+90d小时回填；intraday=仅5d小时增量；close=10d日线+5d小时增量",
    )
    parser.add_argument("--company-id", type=int, action="append", default=[])
    parser.add_argument("--ticker", action="append", default=[])
    parser.add_argument("--sleep", type=float, default=0.25)
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="部分公司/频率失败仍返回 0；默认返回 2 让调度器感知陈旧风险",
    )
    args = parser.parse_args(argv)

    con = common.get_senti_db()
    common.assert_senti_only(con)
    try:
        con.execute("ALTER TABLE stock_kline ADD COLUMN source TEXT DEFAULT 'yfinance'")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            con.close()
            raise
    research = common.research_ro_conn()
    try:
        universe = load_universe(
            research,
            con,
            company_ids=set(args.company_id),
            tickers=set(args.ticker),
        )
        if not universe:
            result = {"ok": False, "error": "empty_universe", "companies": 0}
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            con.close()
            return 2

        cache = {}
        per_company = []
        now = common.now_iso()
        for ticker in sorted({item.ticker for item in universe}):
            try:
                cache[ticker] = fetch_ticker(
                    ticker, days=args.days, m60=args.m60, mode=args.mode
                )
            except Exception as exc:
                cache[ticker] = {
                    "daily": [],
                    "hourly": [],
                    "warnings": [f"unexpected:{type(exc).__name__}:{str(exc)[:160]}"],
                    "errors": (["daily_missing"] if args.mode != "intraday" else [])
                              + ["60m_missing"],
                    "request_daily": args.mode != "intraday",
                    "request_hourly": True,
                    "mode": args.mode,
                }
            if args.sleep > 0:
                time.sleep(args.sleep)

        realtime_fallback = apply_realtime_hourly_fallback(cache)

        for company in universe:
            fetched = cache[company.ticker]
            daily_count = upsert_rows(
                con, company.company_id, company.ticker, "d", fetched["daily"], now
            )
            hourly_count = upsert_rows(
                con, company.company_id, company.ticker, "60m", fetched["hourly"], now
            )
            daily_ok = bool(daily_count) or not fetched["request_daily"]
            hourly_ok = bool(hourly_count) or not fetched["request_hourly"]
            status = "complete" if daily_ok and hourly_ok else (
                "partial" if daily_count or hourly_count else "failed"
            )
            per_company.append(
                {
                    "company_id": company.company_id,
                    "ticker": company.ticker,
                    "status": status,
                    "daily_rows": daily_count,
                    "m60_rows": hourly_count,
                    "errors": fetched["errors"],
                    "warnings": fetched["warnings"],
                }
            )
        con.commit()
    finally:
        research.close()

    complete = sum(item["status"] == "complete" for item in per_company)
    partial = sum(item["status"] == "partial" for item in per_company)
    failed = sum(item["status"] == "failed" for item in per_company)
    result = {
        "ok": partial == 0 and failed == 0,
        "companies": len(per_company),
        "unique_tickers": len(cache),
        "mode": args.mode,
        "complete": complete,
        "partial": partial,
        "failed": failed,
        "daily_rows": sum(item["daily_rows"] for item in per_company),
        "m60_rows": sum(item["m60_rows"] for item in per_company),
        "realtime_fallback": realtime_fallback,
        "failures": [item for item in per_company if item["status"] != "complete"],
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    con.close()
    return 0 if result["ok"] or args.allow_partial else 2


if __name__ == "__main__":
    raise SystemExit(main())
