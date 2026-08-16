#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""散户情绪 V2 三时点编排器。

每个交易日只执行 preopen(10:00)、morning(14:00)、afternoon(17:00) 三个窗口。
窗口边界由 :mod:`senti3` 的纯函数统一定义；preopen 使用两个不连续片段，因此
周末不会被请求或入库。所有子任务状态真实写入 ledger，任一必需步骤失败时窗口
只能是 partial/failed，绝不伪装 complete/usable。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
from tools.runtime_paths import resolve_runtime_layout
RUNTIME_LAYOUT = resolve_runtime_layout(ROOT)
sys.path.insert(0, str(HERE))

import common
import retail_windows_v2
import retention_policy
import senti3

DEFAULT_GUBA_PAGES = int(
    (senti3.load_layer_config().get("guba", {}) or {}).get("pages_per_stock", 128)
)
TICK_LOCK_PATH = RUNTIME_LAYOUT.cache_root / "retail_window_tick.lock"
TICK_LOCK_TIMEOUT_SECONDS = 8 * 60 * 60
XINGHAN_CHILD_TIMEOUT_SECONDS = 6 * 60 * 60
XINGHAN_ORPHAN_STALE_SECONDS = 10 * 60
DEFAULT_AUTO_BACKFILL_START = date(2026, 7, 15)
DEFAULT_AUTO_BACKFILL_MAX_DAYS = retention_policy.INCOMPLETE_FINALIZATION_DAYS
DEFAULT_AUTO_BACKFILL_MAX_WINDOWS = 3
SENTIMENT_REQUIRED_SOURCES = ("guba", "xinghan", "score")
FETCH_SUCCESS_STATES = frozenset({"complete", "empty"})
EMPTY_RECHECK_SOURCE_PREFIX = "__empty_recheck__:"
EMPTY_RECHECK_REQUIRED_ATTEMPTS = 2


def auto_backfill_policy() -> tuple[date, int, int]:
    """读取 V2 自动补跑边界；非法配置直接失败，避免误扫历史兼容窗口。"""
    schedule = (senti3.load_layer_config().get("schedule", {}) or {})
    raw_start = str(
        schedule.get("auto_backfill_start", DEFAULT_AUTO_BACKFILL_START.isoformat())
    ).strip()
    try:
        start = date.fromisoformat(raw_start)
        max_days = int(schedule.get("backfill_max_days", DEFAULT_AUTO_BACKFILL_MAX_DAYS))
        max_windows = int(
            schedule.get("backfill_max_windows_per_tick", DEFAULT_AUTO_BACKFILL_MAX_WINDOWS)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid sentiment_layers.schedule auto-backfill policy") from exc
    if max_days < 0 or max_windows < 0:
        raise ValueError("auto-backfill limits must be non-negative")
    return start, max_days, max_windows


@contextmanager
def exclusive_tick_lock(
    path: Path = TICK_LOCK_PATH,
    *,
    timeout_seconds: float = TICK_LOCK_TIMEOUT_SECONDS,
    poll_seconds: float = 1.0,
):
    """Serialize all three Task Scheduler entries across slot names/processes.

    Task Scheduler's ``MultipleInstances`` only applies to one task name, while
    this workflow intentionally has three names.  Waiting on one project-level
    byte lock queues a later slot instead of racing two crawlers/SQLite writers.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    handle.seek(0, 2)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    deadline = time.monotonic() + max(timeout_seconds, 0)
    acquired = False
    try:
        while not acquired:
            handle.seek(0)
            try:
                if sys.platform == "win32":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"retail tick lock timeout: {path}")
                time.sleep(max(poll_seconds, 0.01))
        yield
    finally:
        if acquired:
            handle.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


@dataclass(frozen=True)
class ChildCommand:
    source: str
    script: str
    args: tuple[str, ...]
    timeout: int


@dataclass(frozen=True)
class ChildResult:
    source: str
    returncode: int
    stdout_tail: str
    stderr_tail: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def build_commands(
    window: senti3.MarketWindow,
    *,
    guba_pages: int = DEFAULT_GUBA_PAGES,
    score_max: int = 0,
    force: bool = False,
) -> tuple[ChildCommand, ...]:
    """纯函数：给定窗口生成固定、可审计的外部步骤。"""
    if window.slot == "preopen":
        kline_args = ("--mode", "full", "--days", "90", "--m60", "160")
    elif window.slot == "morning":
        kline_args = ("--mode", "intraday", "--days", "10", "--m60", "40")
    else:
        kline_args = ("--mode", "close", "--days", "10", "--m60", "40")
    return (
        ChildCommand(
            "guba",
            "senti_fetch_guba.py",
            ("--window-id", window.window_id, "--pages", str(guba_pages)),
            10800,
        ),
        ChildCommand(
            "xinghan",
            "senti_fetch_xinghan.py",
            ("--window-id", window.window_id) + (("--force",) if force else ()),
            XINGHAN_CHILD_TIMEOUT_SECONDS,
        ),
        ChildCommand(
            "score",
            "senti_score.py",
            (
                "--window-id",
                window.window_id,
                "--require-complete",
                "--max",
                str(score_max),
            ),
            7200,
        ),
        ChildCommand(
            "kline",
            "stock_kline_fetch.py",
            kline_args,
            3600,
        ),
    )


def run_child(command: ChildCommand) -> ChildResult:
    from tools.data_platform.run_domain_operation import derived_operation_environment
    window_id = "unknown-window"
    if "--window-id" in command.args:
        window_id = command.args[command.args.index("--window-id") + 1]
    try:
        bootstrap = os.environ.get("HONGHU_RELEASE_BOOTSTRAP", "").strip()
        site_packages = os.environ.get("HONGHU_LOCKED_SITE_PACKAGES", "").strip()
        if not bootstrap or not site_packages:
            raise RuntimeError("exact-release child bootstrap contract is unavailable")
        module = f"tools.sentiment.{Path(command.script).stem}"
        proc = subprocess.run(
            [
                sys.executable, "-I", "-B", "-S", bootstrap,
                "--site-packages", site_packages,
                "--module", "tools.operations.task_child",
                "--task-module", module,
                "--", *command.args,
            ],
            cwd=str(ROOT),
            env=derived_operation_environment(f"retail:{window_id}:{command.source}"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=command.timeout,
        )
        return ChildResult(
            command.source,
            proc.returncode,
            "\n".join((proc.stdout or "").splitlines()[-8:])[-2000:],
            "\n".join((proc.stderr or "").splitlines()[-8:])[-2000:],
        )
    except subprocess.TimeoutExpired as exc:
        return ChildResult(
            command.source,
            124,
            str(exc.stdout or "")[-2000:],
            str(exc.stderr or "")[-2000:],
            timed_out=True,
        )
    except Exception as exc:
        return ChildResult(command.source, 125, "", f"{type(exc).__name__}:{exc}")


def _source_status(
    con,
    window_id: str,
    source: str,
    status: str,
    result=None,
    *,
    records_seen: int = 0,
    inserted: int = 0,
) -> None:
    now = common.now_iso()
    error = None
    if result is not None and not result.ok:
        error = (result.stderr_tail or result.stdout_tail or f"rc={result.returncode}")[-500:]

    # Upgrade a pre-feature, successful zero-row guba run to one persisted empty
    # observation before its status is overwritten by ``running``.  A second
    # successful zero-row run can then close it as a legitimate empty window.
    if source == "guba" and status == "running":
        previous = con.execute(
            "SELECT status FROM retail_window_source_run WHERE window_id=? AND source=?",
            (window_id, source),
        ).fetchone()
        if (
            previous
            and str(previous["status"] if hasattr(previous, "keys") else previous[0])
            in FETCH_SUCCESS_STATES
            and _source_row_count(con, window_id, source) == 0
            and _empty_recheck_attempts(con, window_id, source) == 0
        ):
            _set_empty_recheck_attempts(con, window_id, source, 1, timestamp=now)

    con.execute(
        """INSERT INTO retail_window_source_run(
             window_id,source,status,records_seen,inserted,error_code,started_at,finished_at)
           VALUES(?,?,?,?,?,?,?,?)
           ON CONFLICT(window_id,source) DO UPDATE SET
             status=excluded.status,error_code=excluded.error_code,
             records_seen=excluded.records_seen,inserted=excluded.inserted,
             started_at=COALESCE(retail_window_source_run.started_at,excluded.started_at),
             finished_at=excluded.finished_at""",
        (
            window_id,
            source,
            status,
            records_seen,
            inserted,
            error,
            now,
            now if status != "running" else None,
        ),
    )
    if source == "guba" and status == "empty":
        attempts = min(
            _empty_recheck_attempts(con, window_id, source) + 1,
            EMPTY_RECHECK_REQUIRED_ATTEMPTS,
        )
        _set_empty_recheck_attempts(con, window_id, source, attempts, timestamp=now)
    elif (
        source == "guba"
        and status == "complete"
        and _source_row_count(con, window_id, source) > 0
    ):
        # Once real rows arrive, an earlier empty observation is stale rather
        # than evidence that should suppress future gap detection.
        con.execute(
            "DELETE FROM retail_window_source_run WHERE window_id=? AND source=?",
            (window_id, _empty_recheck_source(source)),
        )


def _source_row_count(con, window_id: str, source: str) -> int:
    if source == "xinghan":
        return int(
            con.execute(
                "SELECT COUNT(*) FROM yuqing_feed_raw WHERE window_id=? AND platform<>'weibo'",
                (window_id,),
            ).fetchone()[0]
        )
    if source == "guba":
        return int(
            con.execute(
                """SELECT COUNT(*) FROM senti_raw_window rw
                   JOIN senti_raw r ON r.id=rw.raw_id
                   WHERE rw.window_id=? AND r.source_layer='retail' AND r.platform='guba'""",
                (window_id,),
            ).fetchone()[0]
        )
    if source == "score":
        return int(
            con.execute(
                """SELECT COUNT(*) FROM senti_raw_window rw
                   JOIN senti_raw r ON r.id=rw.raw_id
                   WHERE rw.window_id=? AND r.source_layer='retail'
                     AND r.platform<>'weibo' AND r.attitude IN (1,2,3)""",
                (window_id,),
            ).fetchone()[0]
        )
    return 0


def _empty_recheck_source(source: str) -> str:
    return f"{EMPTY_RECHECK_SOURCE_PREFIX}{source}"


def _empty_recheck_attempts(con, window_id: str, source: str = "guba") -> int:
    row = con.execute(
        "SELECT records_seen FROM retail_window_source_run WHERE window_id=? AND source=?",
        (window_id, _empty_recheck_source(source)),
    ).fetchone()
    return int(row[0]) if row else 0


def _empty_recheck_verified(con, window_id: str, source: str = "guba") -> bool:
    row = con.execute(
        """SELECT status,records_seen FROM retail_window_source_run
           WHERE window_id=? AND source=?""",
        (window_id, _empty_recheck_source(source)),
    ).fetchone()
    if not row:
        return False
    status = str(row["status"] if hasattr(row, "keys") else row[0])
    attempts = int(row["records_seen"] if hasattr(row, "keys") else row[1])
    return status == "complete" and attempts >= EMPTY_RECHECK_REQUIRED_ATTEMPTS


def _set_empty_recheck_attempts(
    con,
    window_id: str,
    source: str,
    attempts: int,
    *,
    timestamp: str,
) -> None:
    attempts = max(0, min(int(attempts), EMPTY_RECHECK_REQUIRED_ATTEMPTS))
    verified = attempts >= EMPTY_RECHECK_REQUIRED_ATTEMPTS
    con.execute(
        """INSERT INTO retail_window_source_run(
             window_id,source,status,records_seen,inserted,error_code,started_at,finished_at)
           VALUES(?,?,?,?,?,?,?,?)
           ON CONFLICT(window_id,source) DO UPDATE SET
             status=excluded.status,
             records_seen=excluded.records_seen,
             inserted=0,
             error_code=excluded.error_code,
             started_at=COALESCE(retail_window_source_run.started_at,excluded.started_at),
             finished_at=excluded.finished_at""",
        (
            window_id,
            _empty_recheck_source(source),
            "complete" if verified else "partial",
            attempts,
            0,
            (
                f"legitimate_empty_confirmed:{attempts}/{EMPTY_RECHECK_REQUIRED_ATTEMPTS}"
                if verified
                else f"empty_recheck_pending:{attempts}/{EMPTY_RECHECK_REQUIRED_ATTEMPTS}"
            ),
            timestamp,
            timestamp,
        ),
    )


def _source_rows(con, window_id: str) -> dict[str, dict]:
    rows = con.execute(
        """SELECT source,status,records_seen,inserted,error_code,started_at,finished_at
           FROM retail_window_source_run WHERE window_id=? ORDER BY source""",
        (window_id,),
    ).fetchall()
    return {str(row["source"]): dict(row) for row in rows}


def _score_remaining(con, window_id: str) -> int:
    _selected, stat = retail_windows_v2.fair_score_candidate_ids(
        con, window_id, max_total=0
    )
    return int(stat["candidates"])


def _xinghan_segment_requests_complete(con, window_id: str) -> bool:
    """Check formal all-media request audits before allowing a source-level skip.

    ``retail_window_source_run`` predates request variants.  If no segment or
    checkpoint audit exists, retain compatibility with genuinely legacy windows;
    once formal audit state exists, every configured all-media request for every
    declared segment must be complete.  Generic Weibo probes are retired.
    """
    segment_rows = con.execute(
        """SELECT subject_id,request_variant,segment_start,segment_end,status
           FROM yuqing_fetch_segment_run WHERE window_id=?""",
        (window_id,),
    ).fetchall()
    checkpoint_count = int(
        con.execute(
            "SELECT COUNT(*) FROM yuqing_fetch_checkpoint WHERE window_id=?",
            (window_id,),
        ).fetchone()[0]
    )
    if not segment_rows and checkpoint_count == 0:
        return True

    ledger = con.execute(
        "SELECT segments_json FROM retail_window_ledger WHERE window_id=?",
        (window_id,),
    ).fetchone()
    if not ledger:
        return False
    try:
        raw_segments = json.loads(ledger["segments_json"] if hasattr(ledger, "keys") else ledger[0])
        segments = [
            (
                senti3.iso_to_dt(start).isoformat(timespec="seconds"),
                senti3.iso_to_dt(end).isoformat(timespec="seconds"),
            )
            for start, end in raw_segments
        ]
    except (TypeError, ValueError, json.JSONDecodeError):
        return False

    lcfg = senti3.load_layer_config()
    subject_config = lcfg.get("industry_subjects") or {}
    subject_ids = list(dict.fromkeys(
        str(value) for value in subject_config.values() if str(value or "").strip()
    ))
    if not subject_ids:
        subject_ids = [str(lcfg.get("global_probe_subject", "") or "")]
    request_keys = [(subject_id, "all") for subject_id in subject_ids]
    required = {
        (subject_id, variant, segment_start, segment_end)
        for subject_id, variant in request_keys
        for segment_start, segment_end in segments
    }
    completed = {
        (
            str(row["subject_id"]),
            str(row["request_variant"]),
            str(row["segment_start"]),
            str(row["segment_end"]),
        )
        for row in segment_rows
        if str(row["status"]) == "complete"
    }
    return required.issubset(completed)


def fresh_orphaned_xinghan_windows(
    con,
    *,
    now: datetime | None = None,
    stale_seconds: float = XINGHAN_ORPHAN_STALE_SECONDS,
) -> list[str]:
    """找出父 tick 已消失、但分页 checkpoint 仍在真实推进的 Xinghan 子进程。

    Windows Task Scheduler 可以终止父进程而留下 ``subprocess.run`` 创建的
    Python 子进程。项目级 tick 锁会随父进程释放；若此时直接执行 stale recovery，
    第二个 tick 会与孤儿子进程交错读写同一个 snapshot/offset。来源仍为 running、
    必需请求尚未闭合且最近 10 分钟有 segment/checkpoint 心跳时，必须先等待。
    """
    current = now or datetime.now(senti3.TZ)
    out: list[str] = []
    rows = con.execute(
        """SELECT window_id FROM retail_window_source_run
           WHERE source='xinghan' AND status='running' ORDER BY window_id"""
    ).fetchall()
    for row in rows:
        window_id = str(row["window_id"] if hasattr(row, "keys") else row[0])
        if _xinghan_segment_requests_complete(con, window_id):
            continue
        heartbeat = con.execute(
            """SELECT MAX(updated_at) FROM (
                 SELECT updated_at FROM yuqing_fetch_segment_run WHERE window_id=?
                 UNION ALL
                 SELECT updated_at FROM yuqing_fetch_checkpoint WHERE window_id=?
               )""",
            (window_id, window_id),
        ).fetchone()[0]
        if not heartbeat:
            continue
        try:
            age = (current - senti3.iso_to_dt(str(heartbeat))).total_seconds()
        except (TypeError, ValueError):
            continue
        if -5 <= age <= max(float(stale_seconds), 0):
            out.append(window_id)
    return out


def wait_for_fresh_orphaned_xinghan(
    con,
    *,
    timeout_seconds: float = XINGHAN_CHILD_TIMEOUT_SECONDS,
    poll_seconds: float = 5.0,
) -> dict | None:
    """在 stale recovery 前等待仍有心跳的孤儿 Xinghan 子进程完成。"""
    started = time.monotonic()
    observed: set[str] = set()
    while True:
        fresh = fresh_orphaned_xinghan_windows(con)
        if not fresh:
            if not observed:
                return None
            return {
                "windows": sorted(observed),
                "waited_seconds": round(time.monotonic() - started, 1),
            }
        observed.update(fresh)
        if time.monotonic() - started >= max(timeout_seconds, 0):
            raise TimeoutError(
                "fresh orphaned Xinghan child did not settle: " + ",".join(sorted(fresh))
            )
        con.rollback()
        time.sleep(max(poll_seconds, 0.1))


def _source_is_satisfied(con, window_id: str, source: str) -> bool:
    """按持久化审计和当前数据判断来源是否可安全跳过。"""
    row = _source_rows(con, window_id).get(source)
    if not row:
        return False
    status = str(row["status"])
    if source == "guba":
        if status not in FETCH_SUCCESS_STATES:
            return False
        return (
            _source_row_count(con, window_id, source) > 0
            or _empty_recheck_verified(con, window_id, source)
        )
    if source == "xinghan":
        return status in FETCH_SUCCESS_STATES and _xinghan_segment_requests_complete(
            con, window_id
        )
    if source == "score":
        # 已写 complete 仍不能覆盖后来新映射进窗口的未评分样本。
        return status == "complete" and _score_remaining(con, window_id) == 0
    return status == "complete"


def _window_needs_empty_recheck(con, window_id: str) -> bool:
    """Return whether a due V2 window is empty in a way that needs one more probe.

    ``complete`` is not sufficient evidence for a zero-row window: older runs
    could classify an interrupted/blocked fetch as an empty success.  The core
    guba fetch must either contain rows or have two persisted successful empty
    observations.  Two observations are terminal, so truly empty windows do not
    re-enter every future tick.
    """
    ledger = con.execute(
        "SELECT status,raw_count FROM retail_window_ledger WHERE window_id=?",
        (window_id,),
    ).fetchone()
    if not ledger:
        return False
    verified_empty = _empty_recheck_verified(con, window_id, "guba")
    guba = _source_rows(con, window_id).get("guba")
    if guba and str(guba["status"]) == "empty" and not verified_empty:
        return True
    if str(ledger["status"]) != "complete":
        return False
    company_count = int(
        con.execute(
            "SELECT COUNT(*) FROM senti_retail_window WHERE window_id=?",
            (window_id,),
        ).fetchone()[0]
    )
    raw_count = int(ledger["raw_count"])
    if (raw_count == 0) != (company_count == 0):
        # Aggregation/audit drift is repairable without necessarily refetching;
        # execute_window will bypass its idempotent return and reconcile it.
        return True
    return raw_count == 0 and company_count == 0 and not verified_empty


def due_auto_backfill_windows(
    con,
    *,
    now: datetime,
    exclude_window_ids: set[str] | None = None,
    start_date: date | None = None,
    max_days: int | None = None,
    limit: int | None = None,
) -> list[senti3.MarketWindow]:
    """枚举已到期且未完成的 live V2 窗口，不碰切换前历史映射行。"""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    policy_start, policy_days, policy_limit = auto_backfill_policy()
    start = start_date or policy_start
    days = policy_days if max_days is None else int(max_days)
    cap = policy_limit if limit is None else int(limit)
    if days < 0 or cap < 0:
        raise ValueError("auto-backfill limits must be non-negative")
    if cap == 0:
        return []

    local = now.astimezone(senti3.TZ)
    # A window is no longer eligible for source recovery once it leaves the
    # approved raw working set.  Keeping a wider scheduler lookback would
    # recreate records after retention had sealed and purged the window.
    recovery_days = min(days, retention_policy.INCOMPLETE_FINALIZATION_DAYS)
    floor = max(start, local.date() - timedelta(days=recovery_days))
    excluded = exclude_window_ids or set()
    candidates: list[senti3.MarketWindow] = []
    cursor = floor
    while cursor <= local.date():
        if senti3.is_market_session_day(cursor):
            for slot in senti3.MARKET_WINDOW_SLOTS:
                window = senti3.market_window(cursor, slot)
                if window.scheduled_for <= local and window.window_id not in excluded:
                    candidates.append(window)
        cursor += timedelta(days=1)
    if not candidates:
        return []

    window_ids = [window.window_id for window in candidates]
    placeholders = ",".join("?" for _ in window_ids)
    statuses = {
        str(row["window_id"]): (
            str(row["status"]), str(row["retention_state"] or "live")
        )
        for row in con.execute(
            f"""SELECT window_id,status,retention_state
                FROM retail_window_ledger
                WHERE window_id IN ({placeholders})""",
            window_ids,
        )
    }
    due = [
        window
        for window in candidates
        if statuses.get(window.window_id, ("pending", "live"))[1] == "live"
        and (
            statuses.get(window.window_id, ("pending", "live"))[0] != "complete"
            or _window_needs_empty_recheck(con, window.window_id)
            or not _source_is_satisfied(con, window.window_id, "xinghan")
        )
    ]
    due.sort(key=lambda item: (item.scheduled_for, item.window_id))
    return due[:cap]


def reconcile_window(con, window_id: str) -> dict:
    """从 live source audit + 未评分样本集中推导唯一窗口状态，再重算聚合。"""
    retail_windows_v2.ensure_schema(con)
    source_rows = _source_rows(con, window_id)
    score_remaining = _score_remaining(con, window_id)

    # source 声称 complete 但数据层还有样本缺口时，先修正 source audit，避免
    # source_status_json 与窗口状态互相矛盾。
    score_row = source_rows.get("score")
    if score_row and score_row["status"] == "complete" and score_remaining:
        now = common.now_iso()
        con.execute(
            """UPDATE retail_window_source_run
               SET status='partial',error_code=?,finished_at=?
               WHERE window_id=? AND source='score'""",
            (f"unscored_sample_remaining:{score_remaining}", now, window_id),
        )
        source_rows = _source_rows(con, window_id)

    states = {source: str(row["status"]) for source, row in source_rows.items()}
    required_ok = all(
        _source_is_satisfied(con, window_id, source)
        for source in SENTIMENT_REQUIRED_SOURCES
    )
    actual_raw = int(
        con.execute(
            """SELECT COUNT(*) FROM senti_raw_window rw
               JOIN senti_raw r ON r.id=rw.raw_id
               WHERE rw.window_id=? AND r.source_layer='retail'""",
            (window_id,),
        ).fetchone()[0]
    )
    any_success = any(
        states.get(source) in FETCH_SUCCESS_STATES or states.get(source) == "complete"
        for source in SENTIMENT_REQUIRED_SOURCES
    )
    final_status = "complete" if required_ok else ("partial" if actual_raw or any_success else "failed")

    errors = []
    if not required_ok:
        for source in SENTIMENT_REQUIRED_SOURCES:
            row = source_rows.get(source)
            status = str(row["status"]) if row else "missing"
            source_ok = _source_is_satisfied(con, window_id, source)
            if source_ok:
                continue
            detail = str((row or {}).get("error_code") or "").replace("\r", " ").replace("\n", " ")
            if source == "guba" and status in FETCH_SUCCESS_STATES:
                detail = (
                    f"empty_recheck_pending:"
                    f"{_empty_recheck_attempts(con, window_id, source)}/"
                    f"{EMPTY_RECHECK_REQUIRED_ATTEMPTS}"
                )
            if source == "score" and score_remaining:
                detail = f"unscored_sample_remaining:{score_remaining}"
            errors.append(f"{source}:{status}" + (f":{detail[:400]}" if detail else ""))
    retail_windows_v2.mark_window_status(
        con,
        window_id,
        final_status,
        source_status=states,
        error=" | ".join(errors)[-2000:] if errors else None,
    )
    companies = retail_windows_v2.aggregate_window(con, window_id)
    ledger = con.execute(
        "SELECT status,raw_count,scored_count FROM retail_window_ledger WHERE window_id=?",
        (window_id,),
    ).fetchone()
    return {
        "window_id": window_id,
        "status": str(ledger["status"]),
        "raw_count": int(ledger["raw_count"]),
        "scored_count": int(ledger["scored_count"]),
        "companies": int(companies),
        "sources": states,
        "score_remaining": score_remaining,
        "kline_ok": states.get("kline") == "complete",
    }


def recover_stale_windows(con) -> list[dict]:
    """Close orphaned ``running`` attempts while the global tick lock is held.

    A forced Task Scheduler/process termination cannot execute Python cleanup.
    Because callers hold :func:`exclusive_tick_lock`, any remaining ``running``
    row belongs to a dead earlier process and can be safely finalized as a
    transparent partial/failed attempt before the queued slot starts.
    """
    retail_windows_v2.ensure_schema(con)
    stale = con.execute(
        "SELECT window_id FROM retail_window_ledger WHERE status='running' ORDER BY window_id"
    ).fetchall()
    recovered = []
    now = common.now_iso()
    for row in stale:
        window_id = row["window_id"] if hasattr(row, "keys") else row[0]
        con.execute(
            """UPDATE retail_window_source_run
               SET status='failed',
                   error_code=COALESCE(error_code,'stale_running_recovered_after_process_exit'),
                   finished_at=COALESCE(finished_at,?)
               WHERE window_id=? AND status='running'""",
            (now, window_id),
        )
        # 与 source/ledger 同步关闭失去心跳的分页审计；checkpoint 保留精确
        # snapshot/offset 供后续续跑，但 segment 不能永远伪装为 running。
        con.execute(
            """UPDATE yuqing_fetch_segment_run
               SET status='partial',
                   error_code=COALESCE(error_code,'stale_running_recovered_after_process_exit'),
                   finished_at=COALESCE(finished_at,?),
                   updated_at=?
               WHERE window_id=? AND status='running'""",
            (now, now, window_id),
        )
        source_rows = con.execute(
            "SELECT source,status FROM retail_window_source_run WHERE window_id=?",
            (window_id,),
        ).fetchall()
        source_states = {
            (item["source"] if hasattr(item, "keys") else item[0]):
            (item["status"] if hasattr(item, "keys") else item[1])
            for item in source_rows
        }
        raw_count = con.execute(
            """SELECT COUNT(*) FROM senti_raw_window rw
               JOIN senti_raw r ON r.id=rw.raw_id
               WHERE rw.window_id=? AND r.source_layer='retail'""",
            (window_id,),
        ).fetchone()[0]
        status = "partial" if raw_count else "failed"
        retail_windows_v2.mark_window_status(
            con,
            window_id,
            status,
            source_status=source_states,
            error="stale running attempt recovered after prior process exit",
            timestamp=now,
        )
        try:
            companies = retail_windows_v2.aggregate_window(con, window_id, computed_at=now)
        except Exception as exc:
            companies = 0
            status = "failed"
            retail_windows_v2.mark_window_status(
                con,
                window_id,
                "failed",
                source_status=source_states,
                error=f"stale recovery aggregate:{type(exc).__name__}:{exc}",
                timestamp=now,
            )
        recovered.append(
            {"window_id": window_id, "status": status, "raw_count": int(raw_count), "companies": companies}
        )
    con.commit()
    return recovered


def resolve_window(
    *,
    now: datetime,
    slot: str,
    session_date: date | None = None,
) -> senti3.MarketWindow | None:
    """纯解析：周末返回 None；auto 选择当前已到期的最近时点。"""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local = now.astimezone(senti3.TZ)
    day = session_date or local.date()
    if not senti3.is_market_session_day(day):
        return None
    chosen = senti3.scheduled_slot_for_time(local) if slot == "auto" else slot
    if chosen is None:
        return None
    window = senti3.market_window(day, chosen)
    if window.scheduled_for > local and session_date is None:
        return None
    return window


def _open_window_connection(window_id: str, phase: str):
    """Open one bounded parent mutation phase for a retail window.

    The PostgreSQL-authoritative projection holds its interprocess writer lock
    for the lifetime of a connection.  Source children need that same lock, so
    the parent closes each phase before spawning a child.  Stable phase names
    also keep the adapter's per-connection transaction counter from reusing an
    idempotency key after reconnecting.
    """
    from tools.data_platform.run_domain_operation import derived_operation_id

    operation_id = (
        derived_operation_id(f"window:{window_id}:parent:{phase}")
        if os.environ.get("HONGHU_OPERATION_ID", "").strip()
        else None
    )
    con = common.get_senti_db(
        operation_scope="retail_window",
        operation_id=operation_id,
    )
    common.assert_senti_only(con)
    return con


def execute_window(
    window: senti3.MarketWindow,
    *,
    guba_pages: int,
    score_max: int,
    force: bool = False,
) -> tuple[int, dict]:
    con = _open_window_connection(window.window_id, "initialize")
    retail_windows_v2.ensure_schema(con)
    retail_windows_v2.ensure_window(con, window)
    commands = build_commands(
        window, guba_pages=guba_pages, score_max=score_max, force=force
    )
    existing = con.execute(
        """SELECT status,retention_state FROM retail_window_ledger
           WHERE window_id=?""",
        (window.window_id,),
    ).fetchone()
    if existing and str(existing["retention_state"] or "live") != "live":
        state = str(existing["retention_state"])
        con.close()
        return 2, {
            "ok": False,
            "window_id": window.window_id,
            "status": str(existing["status"]),
            "retention_state": state,
            "error": "retention_finalized_window_cannot_resume",
        }
    if (
        existing
        and existing["status"] == "complete"
        and not force
        and not _window_needs_empty_recheck(con, window.window_id)
        and all(_source_is_satisfied(con, window.window_id, item.source) for item in commands)
    ):
        states = {
            source: str(row["status"])
            for source, row in _source_rows(con, window.window_id).items()
        }
        result = {
            "ok": True,
            "window_id": window.window_id,
            "status": "complete",
            "sources": states,
            "kline_ok": True,
            "skipped": "idempotent",
        }
        con.close()
        return 0, result

    retail_windows_v2.mark_window_status(con, window.window_id, "running")
    con.commit()
    con.close()
    executed_sources: list[str] = []
    skipped_sources: list[str] = []
    for command in commands:
        con = _open_window_connection(
            window.window_id, f"source:{command.source}:start"
        )
        skip_source = False
        try:
            # 修复窗口只补失败/缺失来源；score 每次动态核对候选集，因此 guba
            # 重试新增的帖子会在同一轮随后被评分，不会被旧 complete 状态遮住。
            if not force and _source_is_satisfied(
                con, window.window_id, command.source
            ):
                skipped_sources.append(command.source)
                skip_source = True
            else:
                before_count = _source_row_count(
                    con, window.window_id, command.source
                )
                current_source = _source_rows(con, window.window_id).get(
                    command.source
                )
                if not current_source or str(current_source["status"]) != "running":
                    _source_status(
                        con, window.window_id, command.source, "running"
                    )
                    con.commit()
        finally:
            # Release the PostgreSQL projection writer lock before the child
            # opens its own bounded connection.  The outer tick lock remains
            # held, so another Retail runner still cannot enter.
            con.close()
        if skip_source:
            continue
        child = run_child(command)
        executed_sources.append(command.source)

        # Mapping and source-status publication are separate stable mutation
        # phases.  Otherwise an uncertain map commit followed by a retry with
        # no remaining map delta could shift the per-connection transaction
        # index and collide with the prior source-status operation identity.
        if command.source in {"guba", "xinghan"}:
            con = _open_window_connection(
                window.window_id, f"source:{command.source}:map"
            )
            try:
                retail_windows_v2.map_retail_raw_rows(
                    con,
                    since=window.window_start.isoformat(timespec="minutes"),
                    until=window.window_end.isoformat(timespec="minutes"),
                )
                con.commit()
            finally:
                con.close()

        con = _open_window_connection(
            window.window_id, f"source:{command.source}:finish"
        )
        try:
            after_count = _source_row_count(con, window.window_id, command.source)
            source_state = "failed" if not child.ok else (
                "empty"
                if command.source in {"guba", "xinghan"} and after_count == 0
                else "complete"
            )
            _source_status(
                con,
                window.window_id,
                command.source,
                source_state,
                child,
                records_seen=after_count,
                inserted=max(after_count - before_count, 0),
            )
            con.commit()
        finally:
            con.close()

    con = _open_window_connection(window.window_id, "reconcile")
    try:
        reconciled = reconcile_window(con, window.window_id)
        con.commit()
    except Exception as exc:
        con.rollback()
        status_by_source = {
            source: str(row["status"])
            for source, row in _source_rows(con, window.window_id).items()
        }
        retail_windows_v2.mark_window_status(
            con,
            window.window_id,
            "failed",
            source_status=status_by_source,
            error=f"aggregate:{type(exc).__name__}:{exc}",
        )
        con.commit()
        con.close()
        return 2, {
            "ok": False,
            "window_id": window.window_id,
            "status": "failed",
            "error": f"aggregate:{type(exc).__name__}:{exc}",
        }

    result = {**reconciled,
        "session_date": window.session_date.isoformat(),
        "slot": window.slot,
        "executed_sources": executed_sources,
        "skipped_sources": skipped_sources,
    }
    # ledger/usable 只由三个情绪来源决定；K 线继续是同 tick 的辅助门禁，失败
    # 返回非零并保留 source audit，但不能把完整情绪窗口重新降为未完成。
    result["ok"] = result["status"] == "complete" and result["kline_ok"]
    con.close()
    return (0 if result["ok"] else 2), result


def main(argv: list[str] | None = None) -> int:
    # All automated information collection is silent on weekends. Return before
    # logging, locking, SQLite access, or starting child processes so a Task
    # Scheduler catch-up cannot perform Friday work on Saturday or Sunday.
    if datetime.now(senti3.TZ).weekday() >= 5:
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slot", choices=("auto", *senti3.MARKET_WINDOW_SLOTS), default="auto")
    parser.add_argument("--session-date", type=date.fromisoformat)
    parser.add_argument("--guba-pages", type=int, default=DEFAULT_GUBA_PAGES)
    parser.add_argument("--score-max", type=int, default=0, help="0=完整公平评分，不截断")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-auto-backfill", action="store_true", help="仅执行指定窗口，不扫描历史缺口")
    parser.add_argument(
        "--backfill-max-windows",
        type=int,
        help="覆盖配置的本 tick 自动补跑上限；0=本次不补跑",
    )
    args = parser.parse_args(argv)
    controlled_session = os.environ.get("HONGHU_CONTROLLED_SESSION_DATE", "").strip()
    if controlled_session:
        if os.environ.get("HONGHU_TASK_CONTROLLED_TRIAL") != "1":
            raise RuntimeError("controlled session date is not authorized")
        parsed_controlled_session = date.fromisoformat(controlled_session)
        if args.session_date is not None and args.session_date != parsed_controlled_session:
            raise RuntimeError("controlled session date conflicts with command arguments")
        args.session_date = parsed_controlled_session
    try:
        with exclusive_tick_lock():
            from tools.data_platform.run_domain_operation import derived_operation_id

            recovery_con = common.get_senti_db(
                operation_scope="retail_recovery",
                operation_id=(
                    derived_operation_id("controller:recovery")
                    if os.environ.get("HONGHU_OPERATION_ID", "").strip()
                    else None
                ),
            )
            common.assert_senti_only(recovery_con)
            orphan_wait = wait_for_fresh_orphaned_xinghan(recovery_con)
            if orphan_wait:
                print(json.dumps({"waited_for_orphaned_xinghan": orphan_wait},
                                 ensure_ascii=False, sort_keys=True))
            recovered = recover_stale_windows(recovery_con)
            recovery_con.close()
            if recovered:
                print(json.dumps({"recovered_stale_windows": recovered}, ensure_ascii=False, sort_keys=True))
            window = resolve_window(
                now=datetime.now(senti3.TZ),
                slot=args.slot,
                session_date=args.session_date,
            )
            if window is None:
                print(json.dumps({"ok": True, "status": "skipped_non_session_or_not_due"}, ensure_ascii=False))
                return 0
            code, result = execute_window(
                window,
                guba_pages=args.guba_pages,
                score_max=args.score_max,
                force=args.force,
            )
            backfill_results = []
            overall_code = code
            newer_due = resolve_window(now=datetime.now(senti3.TZ), slot="auto")
            yield_to_newer_window = bool(
                newer_due
                and newer_due.window_id != window.window_id
                and newer_due.scheduled_for > window.scheduled_for
            )
            deferred_for_newer_window = (
                newer_due.window_id if yield_to_newer_window else None
            )
            if not args.no_auto_backfill and not yield_to_newer_window:
                scan_con = common.get_senti_db(
                    operation_scope="retail_backfill_scan",
                    operation_id=(
                        derived_operation_id("controller:backfill-scan")
                        if os.environ.get("HONGHU_OPERATION_ID", "").strip()
                        else None
                    ),
                )
                common.assert_senti_only(scan_con)
                backfill_windows = due_auto_backfill_windows(
                    scan_con,
                    now=datetime.now(senti3.TZ),
                    exclude_window_ids={window.window_id},
                    limit=args.backfill_max_windows,
                )
                scan_con.close()
                for backfill_window in backfill_windows:
                    # 单个旧窗口可能因供应商 65 秒分页限流运行一至两小时。
                    # 每项开始前重新检查；一旦 14:00/17:00 新窗口到期，立即
                    # 停止继续补历史，让另一个已排队的计划任务取得全局锁。
                    latest_due = resolve_window(
                        now=datetime.now(senti3.TZ), slot="auto"
                    )
                    if (
                        latest_due
                        and latest_due.window_id != window.window_id
                        and latest_due.scheduled_for > window.scheduled_for
                    ):
                        deferred_for_newer_window = latest_due.window_id
                        break
                    backfill_code, backfill_result = execute_window(
                        backfill_window,
                        guba_pages=args.guba_pages,
                        score_max=args.score_max,
                        force=False,
                    )
                    backfill_results.append(backfill_result)
                    if overall_code == 0 and backfill_code != 0:
                        overall_code = backfill_code
            result["auto_backfill"] = {
                "attempted": len(backfill_results),
                "windows": backfill_results,
                "deferred_for_newer_window": deferred_for_newer_window,
            }
            result["ok"] = bool(result.get("ok")) and all(
                bool(item.get("ok")) for item in backfill_results
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return overall_code
    except TimeoutError as exc:
        print(json.dumps({"ok": False, "status": "deferred_lock_timeout", "error": str(exc)}, ensure_ascii=False))
        return 75
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "status": "failed_unhandled",
            "error": f"{type(exc).__name__}:{exc}",
        }, ensure_ascii=False, sort_keys=True))
        return 70


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
