#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
B1 财报事件抓取(yfinance 主 + Tushare A股 fallback) — 写 event(event_type='财报')

反 slop / 金融严谨:
  - ticker 必须 db 中存在(不猜测);只入未来日期(≥今天);抓不到 → 落 STAGE3B_EARNINGS_PENDING.md
  - 未来财报日均为 **预估披露日**(estimated)→ description 明示;货币/期间标注
  - importance 默认 2,config.earnings_importance_override 标龙头为 1
  - UPSERT 按 (company_id, quarter)(event_store.upsert_earnings)
  - source_id 指向该公司 yfinance source(可溯源);拿不到 source 仍入(source_id NULL)但 note 标
零硬编码实体:公司清单 + ticker 全从 db 拉;override 从 config。
"""
from __future__ import annotations
import sqlite3, sys, io, json
from pathlib import Path
from datetime import datetime, date

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DB = ROOT / "data" / "research.db"
CONFIG = ROOT / "tools" / "dynamic" / "config.yaml"
PENDING = ROOT / "cache" / "STAGE3B_EARNINGS_PENDING.md"
sys.path.insert(0, str(ROOT / "tools" / "dynamic"))
import event_store
import yaml
import yfinance as yf
sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
from tushare_provider import fetch_disclosure_date_latest, ts_code_from_ticker
CFG = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
OVERRIDE = CFG.get("earnings_importance_override", {})
TODAY = date.today()


def yf_ticker(ticker: str) -> str:
    t = (ticker or "").strip()
    if not t:
        return ""
    if t.endswith(".SH"):
        return t[:-3] + ".SS"
    if t.endswith(".HK"):
        return t[:-3].lstrip("0").rjust(4, "0") + ".HK"
    return t


def quarter_of(d: date) -> str:
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def source_map(cur):
    m = {}
    comps = cur.execute("SELECT id, name FROM company").fetchall()
    srcs = cur.execute("SELECT id, title FROM source WHERE fetch_method='api_yfinance'").fetchall()
    for cid, cname in comps:
        for sid, stitle in srcs:
            if cname and stitle and stitle.startswith(cname + " ·"):
                m[cid] = sid; break
    return m


def next_earnings_yf(ytk: str):
    """返回 (date, 'estimated'|'confirmed') 或 None。未来日期视为 estimated。"""
    try:
        tk = yf.Ticker(ytk)
        df = tk.get_earnings_dates(limit=16)
        if df is not None and not df.empty:
            future = [d for d in df.index if d.date() >= TODAY]
            if future:
                nearest = min(future)
                return nearest.date(), "estimated"
    except Exception:
        pass
    # fallback .calendar
    try:
        cal = yf.Ticker(ytk).calendar
        ed = None
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if isinstance(ed, (list, tuple)) and ed:
                ed = ed[0]
        if ed is not None:
            d = ed if isinstance(ed, date) else getattr(ed, "date", lambda: None)()
            if d and d >= TODAY:
                return d, "estimated"
    except Exception:
        pass
    return None


def next_earnings_tushare(ticker: str):
    """A股 fallback:Tushare disclosure_date 预约披露日。"""
    ts_code = ts_code_from_ticker(ticker)
    if not ts_code:
        return None
    try:
        row = fetch_disclosure_date_latest(ts_code)
        raw = str((row or {}).get("pre_date") or "")
        if len(raw) == 8 and raw.isdigit():
            d = datetime.strptime(raw, "%Y%m%d").date()
            if d >= TODAY:
                return d, "estimated"
    except Exception:
        pass
    return None


def main():
    con = sqlite3.connect(str(DB)); cur = con.cursor()
    smap = source_map(cur)
    rows = cur.execute("""
        SELECT DISTINCT c.id, c.name, c.ticker, c.market, c.listing_status
        FROM company c JOIN company_profile cp ON cp.company_id=c.id
        ORDER BY c.id""").fetchall()
    print(f"company_profile 公司:{len(rows)}")
    n_yf = n_ts = n_skip_noticker = 0
    pending = []
    results = []
    for cid, name, ticker, market, ls in rows:
        if not ticker or not str(ticker).strip():
            n_skip_noticker += 1
            pending.append((name, "(无 ticker:未上市/未公开)", ls))
            continue
        ytk = yf_ticker(ticker)
        got = next_earnings_yf(ytk)
        via = "yfinance"
        if not got and ls == "a_share":
            got = next_earnings_tushare(ticker); via = "tushare"
        if not got:
            pending.append((name, ticker, f"yfinance/Tushare 均无未来财报日({ls})"))
            continue
        d, conf = got
        q = quarter_of(d)
        imp = OVERRIDE.get(name, 2)
        desc = (f"{name}({ticker})财报{'预估' if conf=='estimated' else ''}披露日 {d.isoformat()}"
                f";期间约 {q}(按披露日历推算,**预估**,具体财季/币种以公司公告为准);来源 {via}")
        r = event_store.upsert_earnings(con, company_id=cid, company_name=name, quarter=q,
                                        scheduled_date=d.isoformat(), importance=imp,
                                        description=desc, source_id=smap.get(cid), status="upcoming")
        results.append((name, ticker, d.isoformat(), q, imp, via, r))
        if via == "yfinance":
            n_yf += 1
        else:
            n_ts += 1
    con.commit()

    print(f"\n成功:yfinance {n_yf} / Tushare {n_ts} | 无 ticker 跳过 {n_skip_noticker} | pending {len(pending)}")
    for name, tk, d, q, imp, via, r in results:
        print(f"  {name:<14} {tk:<10} {d} {q} L{imp} [{via}] {r}")

    # pending 落盘
    lines = [f"# Stage 3-B 财报事件 PENDING — {datetime.now().isoformat(timespec='seconds')}", "",
             f"成功入库 {n_yf+n_ts} 家(yfinance {n_yf} / Tushare {n_ts});以下 {len(pending)} 家未拿到未来财报日,留空不编造:", ""]
    for name, tk, why in pending:
        lines.append(f"- {name}({tk}):{why}")
    lines += ["", "> 未上市公司(OpenAI/Anthropic/长鑫/长存/xAI 等)无公开财报日历,属正常;",
              "> A股若 Tushare 无披露日或 token 不可用,可手动补 POST /api/event(data_source=manual)。"]
    PENDING.write_text("\n".join(lines), encoding="utf-8")
    print(f"\npending → {PENDING.relative_to(ROOT)}")
    con.close()
    return {"yfinance": n_yf, "tushare": n_ts, "pending": len(pending), "no_ticker": n_skip_noticker}


if __name__ == "__main__":
    main()
