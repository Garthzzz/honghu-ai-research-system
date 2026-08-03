#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""星瀚三层抓取编排:窗口拉取非微博媒体 → 分层 → 闭集归因 → senti_raw。

一次拉全媒体(经济:窗口内不重叠计费),本地 classify_platform 分层 + AliasIndex 归因。
雪球走 webName/domain 过滤(无独立 mediaType)；新闻=新浪/网易/凤凰/今日头条/微信。
所有窗口显式请求 API 文档列出的非微博媒体类型，避免微博被拉取、落库或计分。
attitude 用星瀚原生(1正2负3中),attitude_src='xinghan_native'。
专题:config.sentiment_layers.industry_subjects(按行业);缺 → global_probe_subject("")兜底。
?? 专题池未覆盖 universe 时归因≈0,如实记 0(待配置),绝不造数。只写 sentiment.db。

用法:
  python senti_fetch_xinghan.py --bucket 2026-06-15T08:00          # 抓某桶窗口
  python senti_fetch_xinghan.py --begin <iso> --end <iso> [--backfilled 1]  # 宽窗补抓
"""
from __future__ import annotations
import sys, argparse, time
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common, senti3, retail_windows_v2
from xinghan_client import PAGE_MAX, XinghanWindowClient


REQUEST_ALL = "all"
NON_WEIBO_MEDIA_TYPES = (1, 2, 5, 6, 7, 9, 11, 13, 19, 99)


def resolve_subjects(lcfg) -> list[str]:
    """返回要拉取的 subject_id 列表。industry_subjects 非空 → 各行业专题;否则全局兜底。"""
    subs = lcfg.get("industry_subjects") or {}
    ids = [str(v) for v in subs.values() if str(v or "").strip()]
    if ids:
        return ids
    return [str(lcfg.get("global_probe_subject", "") or "")]   # ""=全部监测池


def write_raw_xinghan(con, *, n, layer, platform, cid, ticker, backfilled, now):
    b = senti3.bucket_for(senti3.iso_to_dt(n["publish_time"]) if n["publish_time"] else datetime.now(senti3.TZ))
    return senti3.insert_raw(con, bucket_id=b["bucket_id"], company_id=cid, ticker=ticker,
        source_layer=layer, platform=platform, attitude=n["attitude"], attitude_src="xinghan_native",
        dedup_key=n["dedup_key"], post_id=n["post_id"], title=n["title"], url=n["url"],
        author=n["author"], author_uid=n["author_uid"], fans_count=n["fans_count"], auth_type=n["auth_type"],
        web_name=n["web_name"], domain=n["domain"], channel=n["channel"], media_type=n["media_type"],
        hot_value=n["hot_value"], sim_hash=n["sim_hash"], publish_time=n["publish_time"],
        as_of=(n["publish_time"] or now)[:10], fetched_at=now, backfilled=backfilled)


def _segment_iso(value_ms: int) -> str:
    return datetime.fromtimestamp(int(value_ms) / 1000, senti3.TZ).isoformat(timespec="seconds")


def _checkpoint_row(
    con, *, window_id, subject_id, request_variant, segment_start, segment_end,
):
    return con.execute(
        """SELECT * FROM yuqing_fetch_checkpoint
           WHERE window_id=? AND subject_id=? AND request_variant=?
             AND segment_start=? AND segment_end=?""",
        (window_id, subject_id, request_variant, segment_start, segment_end),
    ).fetchone()


def _segment_complete(
    con, *, window_id, subject_id, request_variant, segment_start, segment_end,
) -> bool:
    row = con.execute(
        """SELECT status FROM yuqing_fetch_segment_run
           WHERE window_id=? AND subject_id=? AND request_variant=?
             AND segment_start=? AND segment_end=?""",
        (window_id, subject_id, request_variant, segment_start, segment_end),
    ).fetchone()
    return bool(row and row[0] == "complete")


def _start_or_resume_checkpoint(
    con,
    *,
    window_id,
    subject_id,
    request_variant,
    segment_start,
    segment_end,
    request_begin_ms,
    request_end_ms,
):
    """返回稳定分页快照；首次请求前先提交，崩溃后可重用 timestamp+offset。"""
    row = _checkpoint_row(
        con,
        window_id=window_id,
        subject_id=subject_id,
        request_variant=request_variant,
        segment_start=segment_start,
        segment_end=segment_end,
    )
    if row:
        checkpoint = dict(row)
        if int(checkpoint["request_end_ms"]) != int(request_end_ms):
            raise RuntimeError("xinghan checkpoint request_end drift")
        if int(checkpoint["page_size"]) != PAGE_MAX:
            raise RuntimeError("xinghan checkpoint page_size drift")
        now = common.now_iso()
        resumed_run = con.execute(
            """UPDATE yuqing_fetch_segment_run
               SET status='running',error_code=NULL,finished_at=NULL,updated_at=?
               WHERE window_id=? AND subject_id=? AND request_variant=?
                 AND segment_start=? AND segment_end=?""",
            (now, window_id, subject_id, request_variant, segment_start, segment_end),
        )
        # 旧进程可能在 checkpoint 已提交、segment 行尚未提交的极窄边界退出；
        # 幂等补齐 segment 审计行后再发下一页。
        if resumed_run.rowcount == 0:
            con.execute(
                """INSERT INTO yuqing_fetch_segment_run(
                     window_id,subject_id,request_variant,segment_start,segment_end,status,
                     snapshot_timestamp_ms,pages_committed,records_seen,error_code,
                     started_at,finished_at,updated_at)
                   VALUES(?,?,?,?,?,'running',?,?,?,?,?,NULL,?)""",
                (
                    window_id, subject_id, request_variant, segment_start, segment_end,
                    int(checkpoint["snapshot_timestamp_ms"]),
                    int(checkpoint["pages_committed"]), int(checkpoint["records_seen"]),
                    None, now, now,
                ),
            )
        con.commit()
        return checkpoint

    now = common.now_iso()
    snapshot_ms = int(time.time() * 1000)
    con.execute(
        """INSERT INTO yuqing_fetch_checkpoint(
             window_id,subject_id,request_variant,segment_start,segment_end,
             request_begin_ms,request_end_ms,
             snapshot_timestamp_ms,next_offset,page_size,pages_committed,records_seen,
             created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,0,?,0,0,?,?)""",
        (
            window_id, subject_id, request_variant, segment_start, segment_end,
            int(request_begin_ms), int(request_end_ms), snapshot_ms, PAGE_MAX, now, now,
        ),
    )
    con.execute(
        """INSERT INTO yuqing_fetch_segment_run(
             window_id,subject_id,request_variant,segment_start,segment_end,status,
             snapshot_timestamp_ms,
             pages_committed,records_seen,error_code,started_at,finished_at,updated_at)
           VALUES(?,?,?,?,?,'running',?,0,0,NULL,?,NULL,?)
           ON CONFLICT(window_id,subject_id,request_variant,segment_start,segment_end) DO UPDATE SET
             status='running',snapshot_timestamp_ms=excluded.snapshot_timestamp_ms,
             pages_committed=0,records_seen=0,error_code=NULL,
             started_at=excluded.started_at,finished_at=NULL,updated_at=excluded.updated_at""",
        (
            window_id, subject_id, request_variant, segment_start, segment_end,
            snapshot_ms, now, now,
        ),
    )
    # checkpoint 与 segment running 必须先于首个付费 API 请求持久化。
    con.commit()
    return dict(_checkpoint_row(
        con,
        window_id=window_id,
        subject_id=subject_id,
        request_variant=request_variant,
        segment_start=segment_start,
        segment_end=segment_end,
    ))


def _advance_checkpoint(
    con,
    *,
    window_id,
    subject_id,
    request_variant,
    segment_start,
    segment_end,
    next_offset,
    raw_count,
):
    now = common.now_iso()
    changed = con.execute(
        """UPDATE yuqing_fetch_checkpoint
           SET next_offset=?,pages_committed=pages_committed+1,
               records_seen=records_seen+?,updated_at=?
           WHERE window_id=? AND subject_id=? AND request_variant=?
             AND segment_start=? AND segment_end=?""",
        (
            int(next_offset), int(raw_count), now,
            window_id, subject_id, request_variant, segment_start, segment_end,
        ),
    ).rowcount
    if changed != 1:
        raise RuntimeError("xinghan checkpoint disappeared before page commit")
    checkpoint = _checkpoint_row(
        con,
        window_id=window_id,
        subject_id=subject_id,
        request_variant=request_variant,
        segment_start=segment_start,
        segment_end=segment_end,
    )
    con.execute(
        """UPDATE yuqing_fetch_segment_run
           SET status='running',pages_committed=?,records_seen=?,error_code=NULL,
               finished_at=NULL,updated_at=?
           WHERE window_id=? AND subject_id=? AND request_variant=?
             AND segment_start=? AND segment_end=?""",
        (
            int(checkpoint["pages_committed"]), int(checkpoint["records_seen"]), now,
            window_id, subject_id, request_variant, segment_start, segment_end,
        ),
    )


def _complete_segment(
    con,
    *,
    window_id,
    subject_id,
    request_variant,
    segment_start,
    segment_end,
    terminal_raw_count,
):
    checkpoint = _checkpoint_row(
        con,
        window_id=window_id,
        subject_id=subject_id,
        request_variant=request_variant,
        segment_start=segment_start,
        segment_end=segment_end,
    )
    if not checkpoint:
        raise RuntimeError("xinghan checkpoint missing at segment completion")
    now = common.now_iso()
    pages = int(checkpoint["pages_committed"]) + 1
    records = int(checkpoint["records_seen"]) + int(terminal_raw_count)
    con.execute(
        """UPDATE yuqing_fetch_segment_run
           SET status='complete',snapshot_timestamp_ms=?,pages_committed=?,records_seen=?,
               error_code=NULL,finished_at=?,updated_at=?
           WHERE window_id=? AND subject_id=? AND request_variant=?
             AND segment_start=? AND segment_end=?""",
        (
            int(checkpoint["snapshot_timestamp_ms"]), pages, records, now, now,
            window_id, subject_id, request_variant, segment_start, segment_end,
        ),
    )
    con.execute(
        """DELETE FROM yuqing_fetch_checkpoint
           WHERE window_id=? AND subject_id=? AND request_variant=?
             AND segment_start=? AND segment_end=?""",
        (window_id, subject_id, request_variant, segment_start, segment_end),
    )


def _interrupt_segment(
    con,
    *,
    window_id,
    subject_id,
    request_variant,
    segment_start,
    segment_end,
    status,
):
    checkpoint = _checkpoint_row(
        con,
        window_id=window_id,
        subject_id=subject_id,
        request_variant=request_variant,
        segment_start=segment_start,
        segment_end=segment_end,
    )
    now = common.now_iso()
    pages = int(checkpoint["pages_committed"]) if checkpoint else 0
    records = int(checkpoint["records_seen"]) if checkpoint else 0
    run_status = "partial" if pages or records else "failed"
    con.execute(
        """UPDATE yuqing_fetch_segment_run
           SET status=?,pages_committed=?,records_seen=?,error_code=?,finished_at=?,updated_at=?
           WHERE window_id=? AND subject_id=? AND request_variant=?
             AND segment_start=? AND segment_end=?""",
        (
            run_status, pages, records, str(status), now, now,
            window_id, subject_id, request_variant, segment_start, segment_end,
        ),
    )


def _store_page_records(
    con,
    *,
    records,
    expected_window_id,
    alias_idx,
    backfilled,
    fetched_at,
    source_status,
    layer_dist,
):
    n_attr_rows = 0
    for n in records:
        layer, platform = senti3.classify_platform(
            n["web_name"], n["domain"], n["media_type"], n["channel"]
        )
        stored_window = retail_windows_v2.store_yuqing_feed_record(
            con,
            n,
            platform=platform or "unclassified",
            expected_window_id=expected_window_id,
            fetched_at=fetched_at,
            source_status=source_status,
        )
        if stored_window is None:
            layer_dist["excluded(non-session/out-of-window)"] += 1
            continue
        layer_dist["yuqing_feed_raw"] += 1
        if not layer:
            layer_dist["dropped(非三层源)"] += 1
            continue
        layer_dist[f"{layer}/{platform}"] += 1
        hits = alias_idx.attribute((n["title"] or "") + " " + (n["text"] or ""))
        if not hits:
            layer_dist["unattributed(非闭集)"] += 1
            continue
        for cid, ticker in hits:
            n_attr_rows += write_raw_xinghan(
                con,
                n=n,
                layer=layer,
                platform=platform,
                cid=cid,
                ticker=ticker,
                backfilled=backfilled,
                now=fetched_at,
            )
    return n_attr_rows


def _request_specs(subjects):
    """Build one explicitly non-Weibo API request per configured subject."""
    unique_subjects = list(dict.fromkeys(str(subject or "") for subject in subjects)) or [""]
    specs = [
        {
            "subject_id": subject_id,
            "request_variant": REQUEST_ALL,
            "media_types": NON_WEIBO_MEDIA_TYPES,
        }
        for subject_id in unique_subjects
    ]
    return specs


def _request_log_key(*, subject_id, request_variant):
    return f"variant={request_variant.upper()},sub={subject_id or 'ALL'}"


def fetch_range(
    con,
    *,
    begin_ms,
    end_ms,
    backfilled,
    alias_idx,
    lcfg,
    label="",
    expected_window_id=None,
    allow_legacy_resume=True,
):
    retail_windows_v2.ensure_schema(con)
    rl = lcfg.get("rate_limit", {})
    cli = XinghanWindowClient(interval_sec=rl.get("infos_interval_sec", 65),
                              max_pages=rl.get("max_pages_per_window", 30),
                              rate_limit_retries=rl.get("rate_limit_retries", 3),
                              rate_limit_backoff_sec=rl.get("rate_limit_backoff_sec", 60))
    now = common.now_iso()
    subjects = resolve_subjects(lcfg)
    requests = _request_specs(subjects)
    stat = Counter()
    layer_dist = Counter()
    n_attr_rows = 0
    failures = 0
    segment_start = _segment_iso(begin_ms)
    segment_end = _segment_iso(end_ms)
    chunk_limit = max(1, int(rl.get("max_continuation_chunks_per_segment", 8)))
    legacy_overlap = max(0, int(rl.get("resume_overlap_seconds", 180)))
    for request in requests:
        subject_id = request["subject_id"]
        request_variant = request["request_variant"]
        media_types = request["media_types"]
        request_key = _request_log_key(
            subject_id=subject_id, request_variant=request_variant,
        )
        if expected_window_id and _segment_complete(
            con,
            window_id=expected_window_id,
            subject_id=subject_id,
            request_variant=request_variant,
            segment_start=segment_start,
            segment_end=segment_end,
        ):
            stat[f"{request_key}:segment_cached_complete"] += 1
            continue

        checkpoint = None
        request_begin_ms = int(begin_ms)
        request_end_ms = int(end_ms)
        if expected_window_id:
            checkpoint = _checkpoint_row(
                con,
                window_id=expected_window_id,
                subject_id=subject_id,
                request_variant=request_variant,
                segment_start=segment_start,
                segment_end=segment_end,
            )
            # 只为升级前已经落过数据、却没有精确 checkpoint 的历史 partial 窗口
            # 使用发布时间水位。新任务会在首个 API 请求前创建 checkpoint，之后永远
            # 复用同一 timestamp + offset，不再用时间猜测正常续传位置。
            if (
                checkpoint is None
                and request_variant == REQUEST_ALL
                and allow_legacy_resume
                and len(subjects) == 1
            ):
                canonical_begin = datetime.fromtimestamp(int(begin_ms) / 1000, senti3.TZ)
                canonical_end = datetime.fromtimestamp(int(end_ms) / 1000, senti3.TZ)
                legacy_begin = continuation_begin(
                    con,
                    window_id=expected_window_id,
                    begin=canonical_begin,
                    end=canonical_end,
                    overlap_seconds=legacy_overlap,
                )
                request_begin_ms = senti3.to_ms(legacy_begin)
                if request_begin_ms > int(begin_ms):
                    print(
                        f"[xinghan {label}] legacy continuation {segment_start} -> "
                        f"{legacy_begin.isoformat(timespec='seconds')}"
                    )
            checkpoint = _start_or_resume_checkpoint(
                con,
                window_id=expected_window_id,
                subject_id=subject_id,
                request_variant=request_variant,
                segment_start=segment_start,
                segment_end=segment_end,
                request_begin_ms=request_begin_ms,
                request_end_ms=request_end_ms,
            )
            request_begin_ms = int(checkpoint["request_begin_ms"])
            request_end_ms = int(checkpoint["request_end_ms"])
            snapshot_ms = int(checkpoint["snapshot_timestamp_ms"])
            next_offset = int(checkpoint["next_offset"])
        else:
            # 旧 --begin/--bucket 模式没有 canonical window FK；仍逐页提交，但其
            # 跨进程恢复能力保持 legacy。正式三时点任务始终走上面的持久 checkpoint。
            snapshot_ms = int(time.time() * 1000)
            next_offset = 0

        segment_done = False
        for chunk_index in range(1, chunk_limit + 1):
            for page in cli.iter_window_pages(
                subject_id=subject_id,
                begin_ms=request_begin_ms,
                end_ms=request_end_ms,
                media_types=media_types,
                snapshot_timestamp_ms=snapshot_ms,
                start_offset=next_offset,
            ):
                con.execute("SAVEPOINT xinghan_page_commit")
                page_savepoint_active = True
                try:
                    page_attr_rows = _store_page_records(
                        con,
                        records=page.records,
                        expected_window_id=expected_window_id,
                        alias_idx=alias_idx,
                        backfilled=backfilled,
                        fetched_at=now,
                        source_status="ok",
                        layer_dist=layer_dist,
                    )
                    if expected_window_id:
                        if page.terminal:
                            _complete_segment(
                                con,
                                window_id=expected_window_id,
                                subject_id=subject_id,
                                request_variant=request_variant,
                                segment_start=segment_start,
                                segment_end=segment_end,
                                terminal_raw_count=page.raw_count,
                            )
                        else:
                            _advance_checkpoint(
                                con,
                                window_id=expected_window_id,
                                subject_id=subject_id,
                                request_variant=request_variant,
                                segment_start=segment_start,
                                segment_end=segment_end,
                                next_offset=page.next_offset,
                                raw_count=page.raw_count,
                            )
                    # 原始记录、归因行和 checkpoint/完成标记共用页级 savepoint；
                    # 成功页立即提交，异常页显式回滚且保留请求前已持久化的旧 offset。
                    con.execute("RELEASE SAVEPOINT xinghan_page_commit")
                    page_savepoint_active = False
                    con.commit()
                except Exception:
                    if page_savepoint_active:
                        con.execute("ROLLBACK TO SAVEPOINT xinghan_page_commit")
                        con.execute("RELEASE SAVEPOINT xinghan_page_commit")
                    else:
                        con.rollback()
                    raise
                n_attr_rows += page_attr_rows
                next_offset = page.next_offset
                stat[f"{request_key}:pages_committed"] += 1
                if page.terminal:
                    terminal_status = cli.last_status
                    stat[f"{request_key}:{terminal_status}"] += 1
                    segment_done = True
                    break
            if segment_done:
                break

            chunk_status = cli.last_status
            stat[f"{request_key}:{chunk_status}"] += 1
            if chunk_status == "truncated" and chunk_index < chunk_limit:
                print(
                    f"[xinghan {label} {request_key}] page checkpoint chunk "
                    f"{chunk_index}/{chunk_limit}; "
                    f"resume offset={next_offset} snapshot={snapshot_ms}"
                )
                continue

            failures += 1
            terminal_error = (
                "continuation_exhausted" if chunk_status == "truncated" else chunk_status
            )
            if terminal_error != chunk_status:
                stat[f"{request_key}:{terminal_error}"] += 1
            if expected_window_id:
                _interrupt_segment(
                    con,
                    window_id=expected_window_id,
                    subject_id=subject_id,
                    request_variant=request_variant,
                    segment_start=segment_start,
                    segment_end=segment_end,
                    status=terminal_error,
                )
                con.commit()
            break
    con.commit()
    incomplete_requests = []
    if expected_window_id:
        incomplete_requests = [
            _request_log_key(
                subject_id=request["subject_id"],
                request_variant=request["request_variant"],
            )
            for request in requests
            if not _segment_complete(
                con,
                window_id=expected_window_id,
                subject_id=request["subject_id"],
                request_variant=request["request_variant"],
                segment_start=segment_start,
                segment_end=segment_end,
            )
        ]
        if incomplete_requests:
            stat["required_requests_incomplete"] = len(incomplete_requests)
    print(
        f"[xinghan {label}] calls={cli.calls} billed={cli.billed} "
        f"rate_limit_hits={cli.rate_limit_hits} status={dict(stat)}"
    )
    print(f"  层/平台分布:{dict(layer_dist)}")
    print(f"  ??归因入库 senti_raw 行:{n_attr_rows}(闭集 104 股)")
    return {"ok": failures == 0 and not incomplete_requests, "failures": failures,
            "calls": cli.calls, "billed": cli.billed, "attr_rows": n_attr_rows,
            "layer_dist": dict(layer_dist), "status": dict(stat),
            "incomplete_requests": incomplete_requests}


def continuation_begin(
    con,
    *,
    window_id: str | None,
    begin: datetime,
    end: datetime,
    overlap_seconds: int = 180,
) -> datetime:
    """升级前 partial 窗口的一次性兼容水位；正常恢复不走这里。

    旧代码没有保存 API timestamp/offset，只能以最大已入库发布时间向前重叠建立
    第一个新 checkpoint。checkpoint 一旦存在，所有重启均复用同一快照和精确 offset；
    不再以发布时间作为续传游标。
    """
    if not window_id:
        return begin
    row = con.execute(
        """SELECT MAX(publish_time) FROM yuqing_feed_raw
           WHERE window_id=? AND publish_time>=? AND publish_time<?""",
        (
            window_id,
            begin.isoformat(timespec="seconds"),
            end.isoformat(timespec="seconds"),
        ),
    ).fetchone()
    latest = row[0] if row else None
    if not latest:
        return begin
    try:
        latest_dt = senti3.iso_to_dt(latest)
    except (TypeError, ValueError):
        return begin
    resumed = max(begin, latest_dt - timedelta(seconds=max(0, int(overlap_seconds))))
    return resumed if resumed < end else begin


def weekday_segments(begin, end):
    """把任意半开区间拆成工作日片段，V2 绝不向 API 请求周末区间。"""
    if begin.tzinfo is None or end.tzinfo is None:
        raise ValueError("fetch range requires timezone-aware datetimes")
    begin = begin.astimezone(senti3.TZ)
    end = end.astimezone(senti3.TZ)
    if end <= begin:
        raise ValueError("fetch range end must be later than begin")
    segments = []
    day = begin.date()
    while day <= end.date():
        day_start = datetime.combine(day, datetime.min.time(), tzinfo=senti3.TZ)
        day_end = day_start + timedelta(days=1)
        start = max(begin, day_start)
        stop = min(end, day_end)
        if day.weekday() < 5 and start < stop:
            segments.append((start, stop))
        day += timedelta(days=1)
    return segments


def parse_window_id(value):
    try:
        session_text, slot = value.split(":", 1)
        session_date = datetime.strptime(session_text, "%Y-%m-%d").date()
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"非法 window id: {value!r}") from exc
    return senti3.market_window(session_date, slot)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", help="桶 id(如 2026-06-15T08:00),抓该桶窗口")
    ap.add_argument("--begin", help="窗口起 ISO")
    ap.add_argument("--end", help="窗口止 ISO")
    ap.add_argument("--backfilled", type=int, default=0)
    ap.add_argument("--window-id", help="V2 窗口 YYYY-MM-DD:preopen|morning|afternoon")
    ap.add_argument("--force", action="store_true", help="显式丢弃本窗口星瀚断点并从片段起点重抓")
    args = ap.parse_args()
    con = common.get_senti_db()
    common.assert_senti_only(con)                      # 门C
    alias_idx = senti3.AliasIndex(con)
    lcfg = senti3.load_layer_config()

    if args.window_id:
        if args.bucket or args.begin or args.end:
            ap.error("--window-id 不能与 --bucket/--begin/--end 混用")
        window = parse_window_id(args.window_id)
        segments = list(window.segments)
        label = window.window_id
        expected_window_id = window.window_id
    elif args.bucket:
        bdt = senti3.iso_to_dt(args.bucket + "+08:00") if "+" not in args.bucket else senti3.iso_to_dt(args.bucket)
        b = senti3.bucket_for(bdt)
        begin = senti3.iso_to_dt(b["bucket_start"]); end = senti3.iso_to_dt(b["bucket_end"])
        label = args.bucket
        segments = weekday_segments(begin, end)
        expected_window_id = None
    elif args.begin and args.end:
        begin = senti3.iso_to_dt(args.begin if "+" in args.begin else args.begin + "+08:00")
        end = senti3.iso_to_dt(args.end if "+" in args.end else args.end + "+08:00")
        label = f"{args.begin}~{args.end}"
        segments = weekday_segments(begin, end)
        expected_window_id = None
    else:
        # 默认:当前桶
        b = senti3.bucket_for(datetime.now(senti3.TZ))
        begin = senti3.iso_to_dt(b["bucket_start"]); end = senti3.iso_to_dt(b["bucket_end"])
        label = b["bucket_id"]
        segments = weekday_segments(begin, end)
        expected_window_id = None

    retail_windows_v2.ensure_schema(con)
    if args.force and expected_window_id:
        con.execute("DELETE FROM yuqing_fetch_checkpoint WHERE window_id=?", (expected_window_id,))
        con.execute("DELETE FROM yuqing_fetch_segment_run WHERE window_id=?", (expected_window_id,))
        con.commit()
    if not segments:
        print(f"[xinghan {label}] 无工作日片段，跳过 API 请求")
    exit_code = 0
    for index, (begin, end) in enumerate(segments, start=1):
        result = fetch_range(
            con,
            begin_ms=senti3.to_ms(begin),
            end_ms=senti3.to_ms(end),
            backfilled=args.backfilled,
            alias_idx=alias_idx,
            lcfg=lcfg,
            label=f"{label}#{index}/{len(segments)}",
            expected_window_id=expected_window_id,
            allow_legacy_resume=not args.force,
        )
        if not result["ok"]:
            exit_code = 2
    con.close()
    return exit_code


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
