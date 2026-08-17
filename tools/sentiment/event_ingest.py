#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""巨潮公告抓取与公告情绪补判，只写 ``sentiment.db``。

公告先幂等入库，再在同一轮补判历史和本轮尚未评分的记录。这样即使单日
公告数超过 LLM 配额，后续日任务也会继续收口，不会被去重账本永久跳过。
"""
from __future__ import annotations
import os, sys, json, ssl, time, argparse, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
if sys.stdout is None:
    # Task Scheduler 使用 pythonw.exe，避免每天弹出可见控制台；输出保留到日志。
    from tools.runtime_paths import resolve_runtime_layout
    _log_dir = resolve_runtime_layout(Path(__file__).resolve().parents[2]).cache_root / "sentiment"
    _log_dir.mkdir(parents=True, exist_ok=True)
    _log_handle = (_log_dir / "event_ingest.log").open("a", encoding="utf-8", buffering=1)
    sys.stdout = _log_handle
    sys.stderr = _log_handle
else:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dynamic"))
import common
import quiet_hours
from tools.data_platform.run_domain_operation import (
    derived_operation_id,
    install_operation_context,
)
try:
    import llm_client
except Exception:
    llm_client = None

_ctx = ssl.create_default_context(); _ctx.check_hostname = False; _ctx.verify_mode = ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
TZ = timezone(timedelta(hours=8))
CORE_TICKERS = ["300308.SZ", "300502.SZ", "300394.SZ", "601138.SH", "000977.SZ", "688008.SH",
                "002371.SZ", "002156.SZ", "002463.SZ", "301308.SZ", "688981.SH", "002230.SZ"]


def _operation_connection(step: str):
    """Open one stable mutation stream instead of a process-order stream."""

    operation_id = (
        derived_operation_id(step)
        if os.environ.get("HONGHU_OPERATION_ID", "").strip()
        else None
    )
    connection = common.get_senti_db(
        operation_scope="event_ingest_step",
        operation_id=operation_id,
    )
    common.assert_senti_only(connection)
    return connection


def _post(url, form):
    try:
        req = urllib.request.Request(url, data=form.encode(),
                                     headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded",
                                              "X-Requested-With": "XMLHttpRequest"})
        return json.loads(urllib.request.urlopen(req, timeout=15, context=_ctx).read().decode("utf-8", "replace"))
    except Exception:
        return None


def get_orgid(con, code):
    row = con.execute("SELECT org_id, market, name FROM event_orgid_map WHERE code=?", (code,)).fetchone()
    if row and row[0]:
        return row[0], row[1], row[2]
    j = _post("http://www.cninfo.com.cn/new/information/topSearch/query", f"keyWord={code}&maxNum=10")
    if isinstance(j, list):
        for it in j:
            if str(it.get("code")) == code:
                org = it.get("orgId"); name = it.get("zwjc")
                market = "szse" if code[0] in "03" else "sse"
                con.execute("""INSERT OR REPLACE INTO event_orgid_map(ticker,code,org_id,name,market,updated_at)
                               VALUES(?,?,?,?,?,?)""", (code, code, org, name, market, common.now_iso()))
                con.commit()
                return org, market, name
    return None, None, None


def fetch_announcements(code, org, market, n=8):
    j = _post("http://www.cninfo.com.cn/new/hisAnnouncement/query",
              f"stock={code},{org}&tabName=fulltext&pageSize={n}&pageNum=1&column={market}&category=&isHLtitle=true")
    if not isinstance(j, dict):
        return None
    out = []
    for a in (j.get("announcements") or [])[:n]:
        ts = a.get("announcementTime")
        pub = datetime.fromtimestamp(ts / 1000, TZ).isoformat(timespec="seconds") if ts else None
        url = "http://static.cninfo.com.cn/" + (a.get("adjunctUrl") or "")
        title = (a.get("announcementTitle") or "").replace("　", " ").strip()
        out.append({"title": title, "url": url, "published_at": pub})
    return out


def judge(title):
    """DeepSeek 判 materiality/sentiment/summary。无 key/失败 → (None,None,None) 不造数。"""
    if not (llm_client and llm_client.enabled()):
        return None, None, None
    sysmsg = "你是金融事件分析助手。针对A股公司公告标题,判断其对公司股价的重大性与情绪倾向,并给一句中文摘要。只输出JSON。"
    usr = (f"公告标题:{title}\n输出JSON:{{\"materiality\":\"高|中|低\",\"sentiment\":\"正面|负面|中性\",\"summary\":\"一句话摘要\"}}")
    r = llm_client.chat_json(sysmsg, usr, max_tokens=200)
    if not isinstance(r, dict):
        return None, None, None
    materiality = str(r.get("materiality") or "").strip()
    sentiment = str(r.get("sentiment") or "").strip()
    summary = str(r.get("summary") or "").strip()
    if materiality not in {"高", "中", "低"} or sentiment not in {"正面", "负面", "中性"}:
        return None, None, None
    return materiality, sentiment, summary or None


def score_pending(con, max_items):
    """补判最近尚未完整评分的公告，返回可审计计数。"""
    pending_before = int(con.execute(
        """SELECT COUNT(*) FROM event_item
           WHERE materiality IS NULL OR sentiment IS NULL"""
    ).fetchone()[0])
    result = {
        "pending_before": pending_before,
        "attempted": 0,
        "judged": 0,
        "pending_after": pending_before,
    }
    if max_items <= 0 or pending_before == 0:
        return result
    if not (llm_client and llm_client.enabled()):
        return result

    rows = con.execute(
        """SELECT id,title FROM event_item
           WHERE materiality IS NULL OR sentiment IS NULL
           ORDER BY COALESCE(published_at,fetched_at) DESC,id DESC
           LIMIT ?""",
        (int(max_items),),
    ).fetchall()
    for row in rows:
        result["attempted"] += 1
        materiality, sentiment, summary = judge(row["title"])
        if materiality:
            con.execute(
                """UPDATE event_item
                   SET materiality=?,sentiment=?,summary_ai=?,
                       ai_tagged_by='deepseek',ai_tier=2
                   WHERE id=?""",
                (materiality, sentiment, summary, row["id"]),
            )
            result["judged"] += 1
        # One scoring window is one mutation batch.  Intermediate commits made
        # retry identity depend on how many rows a previous attempt completed.
    con.commit()
    result["pending_after"] = int(con.execute(
        """SELECT COUNT(*) FROM event_item
           WHERE materiality IS NULL OR sentiment IS NULL"""
    ).fetchone()[0])
    return result


def main():
    install_operation_context(
        cutover_unit="sentiment_analytics",
        operation_scope="event_ingest",
        logical_window=datetime.now(TZ).date().isoformat(),
    )
    # 自动或手动误触发都不应在周末访问公告源或 LLM；按用户要求静默返回。
    if quiet_hours.is_weekend():
        return 0
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-llm", type=int, default=200, help="本轮最多补判的公告数；0 表示只抓取不打分")
    ap.add_argument("--per-stock", type=int, default=6)
    ap.add_argument("--all", action="store_true", help="覆盖全部闭集 A 股(非仅 12 只 CORE_TICKERS)")
    ap.add_argument("--verbose", action="store_true", help="输出每只股票的抓取结果；默认只输出真实新增或失败")
    args = ap.parse_args()
    comps, _ = common.load_closed_set()
    rc = common.research_ro_conn()
    now = common.now_iso()
    stat = {"ann": 0, "new": 0, "fetch_failed": 0, "skip_closed": 0}
    print(f"\n=== 公告日任务开始 {now} ===")

    if args.all:
        tickers = [r[0] for r in rc.execute("""SELECT ticker FROM company
            WHERE ticker LIKE '%.SZ' OR ticker LIKE '%.SH' OR ticker LIKE '%.SS' OR ticker LIKE '%.BJ'
            ORDER BY id""")]
    else:
        tickers = CORE_TICKERS
    for tk in tickers:
        code = tk.split(".")[0]
        crow = rc.execute("SELECT id, name FROM company WHERE ticker=?", (tk,)).fetchone()
        if not crow or crow[0] not in comps:
            stat["skip_closed"] += 1; continue
        cid, name = crow[0], crow[1]
        org_connection = _operation_connection(f"company:{code}:org")
        try:
            org, market, _ = get_orgid(org_connection, code)
        finally:
            org_connection.close()
        if not org:
            stat["fetch_failed"] += 1
            print(f"  失败 {name} {tk}: orgId 未取到"); continue
        anns = fetch_announcements(code, org, market, args.per_stock)
        if anns is None:
            stat["fetch_failed"] += 1
            print(f"  失败 {name} {tk}: 巨潮请求未返回有效响应")
            continue
        stat["ann"] += len(anns)
        company_new = 0
        company_connection = _operation_connection(f"company:{code}:announcements")
        try:
            for a in anns:
                if not a["url"] or not a["title"]:
                    continue
                if not common.mark_seen(company_connection, "event", "cninfo", a["url"]):
                    continue                                 # 已见跳过
                cur = company_connection.execute("""INSERT OR IGNORE INTO event_item
                    (entity_type,entity_id,event_type,title,summary_ai,url,published_at,source,
                     sentiment,materiality,ai_tagged_by,ai_tier,source_url,as_of,fetched_at)
                    VALUES('company',?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (cid, "announcement", a["title"], None, a["url"], a["published_at"], "cninfo",
                     None, None, None, 2, a["url"], a["published_at"], now))
                if cur.rowcount == 1:
                    company_new += 1
                    stat["new"] += 1
            company_connection.commit()
        finally:
            company_connection.close()
        if company_new or args.verbose:
            print(f"  {name} {tk}: 返回 {len(anns)} 条，真实新增 {company_new} 条")
        time.sleep(0.6)
    rc.close()
    scoring_connection = _operation_connection("scoring")
    try:
        scoring = score_pending(scoring_connection, args.max_llm)
    finally:
        scoring_connection.close()
    print(
        "\n=== 公告日任务完成: "
        f"返回 {stat['ann']} | 真实新增 {stat['new']} | 抓取失败 {stat['fetch_failed']} | "
        f"待评分 {scoring['pending_before']} -> {scoring['pending_after']} "
        f"(尝试 {scoring['attempted']}，成功 {scoring['judged']}) ==="
    )
    if llm_client:
        print("DeepSeek:", "启用" if llm_client.enabled() else "未启用(materiality/sentiment 留空,不造数)", getattr(llm_client, "USAGE", ""))
    return 2 if stat["fetch_failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
