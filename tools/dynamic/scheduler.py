#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stage 3-A 调度器骨架 — 无状态 tick(Windows 任务计划器每 15min 调 `python scheduler.py tick`)

v2 修订 + R5 已内置:
  修订3:is_running 原子锁(UPDATE WHERE is_running=0)防同 target 并发;
         running_started_at 超 stale_lock_minutes(默认30)→ 僵死自动重置。
  附修订:in_peak 跨午夜 OR 判断(start<end→AND;start>end→OR)。
  R5:next_run_at = 抓取**完成时**的 local_now()+freq(用最新时刻,不是 tick 开始时刻),
      避免抓取耗时 > freq 时下一轮立刻又跑。

微博 voice target 只走舆情 API 的重点账号池并按作者 UID 精确匹配。
voice 子进程的认证/系统错误会进入 ``error``，连续第三次失败才 ``paused``；
共享舆情令牌繁忙返回的延期码只释放锁并等待下一个 tick，不累计失败。

用法:
  python scheduler.py tick      # 跑一轮(到点 target 才动)
  python scheduler.py status    # 看 fetch_schedule 当前状态
"""
from __future__ import annotations
import os, sys, json, subprocess
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from tools.runtime_paths import resolve_runtime_layout
RUNTIME_LAYOUT = resolve_runtime_layout(ROOT)
DB = RUNTIME_LAYOUT.data_root / "research.db"
CONFIG = ROOT / "tools" / "dynamic" / "config.yaml"
LOGDIR = RUNTIME_LAYOUT.cache_root / "dynamic_fetch_log"
import yaml
from tools.dynamic.database import connect_operations
from tools.data_platform.run_domain_operation import (
    derived_operation_id,
    derived_operation_environment,
    install_operation_context,
)
CFG = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
STALE_MIN = CFG["schedule"].get("stale_lock_minutes", 30)
sys.path.insert(0, str(ROOT / "tools" / "dynamic"))
import quiet_hours   # tz-aware 静默闸(D2)


class ScheduledFetchError(RuntimeError):
    """A child failure with an explicit fetch_schedule status hint."""

    def __init__(self, message: str, *, schedule_status: str = "error"):
        super().__init__(message)
        self.schedule_status = schedule_status


class ScheduledFetchDeferred(ScheduledFetchError):
    """The source is healthy but a shared upstream token is temporarily busy."""

    def __init__(self, message: str):
        super().__init__(message, schedule_status="deferred")


# Stable child-process contract exported by voice_ingest.EXIT_DEFERRED.  Keep the
# numeric check local so importing voice_ingest cannot initialize its DB/config
# dependencies inside the scheduler process.
VOICE_INGEST_EXIT_DEFERRED = 22

# A Stage 5 compatibility defect used ``sqlite3.Row.get`` before dispatching
# any producer.  The exact error is safe to recognize once so a controlled
# trial can repair the schedule rows immediately instead of waiting for their
# exponential backoff.  Ordinary production ticks never bypass ``next_run_at``.
COMPAT_ROW_ACCESS_FAILURE = "'sqlite3.Row' object has no attribute 'get'"


def now():
    # fetch_schedule 历史字段是无时区 ISO；统一以北京时间写入，避免部署主机
    # 时区变化后把 09:00--17:00 的意见领袖窗口整体平移。
    return quiet_hours.now_tz().replace(tzinfo=None)


def log(msg):
    LOGDIR.mkdir(parents=True, exist_ok=True)
    line = f"[{now().isoformat(timespec='seconds')}] {msg}"
    (LOGDIR / f"{now().date().isoformat()}.log").open("a", encoding="utf-8").write(line + "\n")
    print(line)


def _hm(s):
    h, m = s.split(":"); return int(h) * 60 + int(m)


def in_peak(region: str, t: datetime) -> bool:
    """跨午夜 OR 判断:start<end → start<=t<end(AND);start>end → t>=start OR t<end(OR)。"""
    rw = CFG["schedule"]["region_windows"].get(region) or CFG["schedule"]["region_windows"]["global"]
    cur = t.hour * 60 + t.minute
    s, e = _hm(rw["peak_start"]), _hm(rw["peak_end"])
    return (s <= cur < e) if s < e else (cur >= s or cur < e)


def voice_window_open(t: datetime | None = None) -> bool:
    """意见领袖统一北京时间窗口；结束时刻这一档允许启动。"""
    policy = (CFG.get("schedule", {}) or {}).get("voice_window", {}) or {}
    current = t or now()
    cur = current.hour * 60 + current.minute
    start = _hm(str(policy.get("start", "09:00")))
    end = _hm(str(policy.get("end", "17:00")))
    return (start <= cur <= end) if start <= end else (cur >= start or cur <= end)


def next_allowed_voice_time(candidate: datetime) -> datetime:
    """把下一次 KOL 检查对齐到 tick，并越过夜间和周末。"""
    policy = (CFG.get("schedule", {}) or {}).get("voice_window", {}) or {}
    start = _hm(str(policy.get("start", "09:00")))
    tick_minutes = max(1, int((CFG.get("runtime", {}) or {}).get("tick_frequency_min", 15)))
    candidate = candidate.replace(second=0, microsecond=0)
    remainder = candidate.minute % tick_minutes
    if remainder:
        candidate += timedelta(minutes=tick_minutes - remainder)
    if candidate.weekday() < 5 and voice_window_open(candidate):
        return candidate
    if candidate.weekday() < 5 and candidate.hour * 60 + candidate.minute < start:
        return candidate.replace(hour=start // 60, minute=start % 60)
    cursor = candidate
    while True:
        cursor = (cursor + timedelta(days=1)).replace(
            hour=start // 60, minute=start % 60, second=0, microsecond=0
        )
        if cursor.weekday() < 5:
            return cursor


def freq_for(con, row) -> int:
    """所有意见领袖统一 60 分钟；其余任务使用各自排程频率。"""
    if row["target_type"] == "voice_leader":
        policy = (CFG.get("schedule", {}) or {}).get("voice_window", {}) or {}
        return max(1, int(policy.get("frequency_minutes", 60)))
    return row["frequency_minutes"]


# ── dispatch:真 fetcher 接入点 ────────────────────────────────────────────────
EVDIR = ROOT / "tools" / "dynamic" / "event_sources"


def _isolated_child(module: str, *arguments: str) -> list[str]:
    bootstrap = os.environ.get("HONGHU_RELEASE_BOOTSTRAP", "").strip()
    site_packages = os.environ.get("HONGHU_LOCKED_SITE_PACKAGES", "").strip()
    if not bootstrap or not site_packages:
        raise RuntimeError("exact-release child bootstrap contract is unavailable")
    return [
        sys.executable, "-I", "-B", "-S", bootstrap,
        "--site-packages", site_packages,
        "--module", "tools.operations.task_child",
        "--task-module", module,
        "--", *arguments,
    ]


def _run_script(path: Path, label: str, *, step: str):
    """subprocess 跑重型 fetcher(隔离 stdout/yfinance);失败抛异常(交 tick 退避)。"""
    relative = path.resolve().relative_to(ROOT).with_suffix("")
    module = ".".join(relative.parts)
    p = subprocess.run(_isolated_child(module), cwd=str(ROOT), capture_output=True,
                       env=derived_operation_environment(step),
                       text=True, encoding="utf-8", errors="replace", timeout=600)
    tail = (p.stdout or "").strip().splitlines()[-1:] or [""]
    log(f"    {label}: rc={p.returncode} | {tail[0][:120]}")
    if p.returncode != 0:
        raise RuntimeError(f"{label} rc={p.returncode}: {(p.stderr or '')[:200]}")


def run_fetch(con, row) -> int:
    """调用对应来源；微博 voice_ingest 只使用舆情 API。"""
    tt, label = row["target_type"], row["target_label"]
    # ``sqlite3.Row`` and the PostgreSQL compatibility row both support keyed
    # indexing, but ``sqlite3.Row`` intentionally has no ``dict.get`` method.
    try:
        schedule_id = row["id"]
    except (KeyError, IndexError):
        schedule_id = f"{tt}:{row['target_id']}"
    if tt == "event_calendar":
        # B7:真跑 大会 loader(快/幂等)+ 财报 fetcher(yfinance)
        _run_script(EVDIR / "conference_loader.py", "conference_loader", step=f"schedule:{schedule_id}:conference")
        _run_script(EVDIR / "earnings_fetcher.py", "earnings_fetcher", step=f"schedule:{schedule_id}:earnings")
    elif tt == "voice_leader":
        # D3:真调 voice_ingest 抓该 leader(subprocess 隔离),失败抛异常 → 退避(P0-1)
        p = subprocess.run(_isolated_child(
                               "tools.dynamic.voice_ingest", "--leader-id", str(row["target_id"])),
                           env=derived_operation_environment(f"schedule:{schedule_id}:voice:{row['target_id']}"),
                           cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        tail = (p.stdout or "").strip().splitlines()[-2:] or [""]
        log(f"    voice_ingest[{label}]: rc={p.returncode} | {' / '.join(t[:70] for t in tail)}")
        if p.returncode == VOICE_INGEST_EXIT_DEFERRED:
            raise ScheduledFetchDeferred(
                f"voice_ingest {label} deferred rc={p.returncode}: "
                f"{(p.stderr or '')[:160]}"
            )
        if p.returncode != 0:
            raise ScheduledFetchError(
                f"voice_ingest {label} rc={p.returncode}: {(p.stderr or '')[:160]}"
            )
    elif tt == "news_source":
        # C4:真调 news_ingest 抓该 source(subprocess 隔离),失败抛异常 → tick 退避(P0-1)
        p = subprocess.run(_isolated_child(
                               "tools.dynamic.news_ingest", "--source-id", str(row["target_id"])),
                           env=derived_operation_environment(f"schedule:{schedule_id}:news:{row['target_id']}"),
                           cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180)
        tail = (p.stdout or "").strip().splitlines()[-2:] or [""]
        log(f"    news_ingest[{label}]: rc={p.returncode} | {' / '.join(t[:80] for t in tail)}")
        if p.returncode != 0:
            raise RuntimeError(f"news_ingest {label} rc={p.returncode}: {(p.stderr or '')[:160]}")
    return 0


def _controlled_compatibility_retry(row) -> bool:
    return (
        os.environ.get("HONGHU_DYNAMIC_COMPATIBILITY_RETRY", "").strip() == "1"
        and row["last_error"] == COMPAT_ROW_ACCESS_FAILURE
    )


def try_lock(con, sid, *, allow_compatibility_retry: bool = False) -> bool:
    lock_time = now()
    lock_iso = lock_time.isoformat(timespec="seconds")
    cur = con.execute(
        """UPDATE fetch_schedule
           SET is_running=1,running_started_at=?,updated_at=?
           WHERE id=? AND is_running=0 AND is_active=1
             AND (
               (status<>'paused' AND (next_run_at IS NULL OR next_run_at<=?))
               OR (?=1 AND last_error=?)
             )""",
        (
            lock_iso,
            lock_iso,
            sid,
            lock_iso,
            int(allow_compatibility_retry),
            COMPAT_ROW_ACCESS_FAILURE,
        ),
    )
    return cur.rowcount == 1


def _operation_connection(step: str):
    """Open one retry-stable schedule mutation stream.

    The PostgreSQL compatibility adapter numbers commits per connection.  A
    single connection spanning an order-dependent target loop would therefore
    give a later target a different publication identity after a partial
    retry.  Each schedule/phase gets its own stable root and exactly one
    commit, while the read snapshot remains separate.
    """

    operation_id = (
        derived_operation_id(step)
        if os.environ.get("HONGHU_OPERATION_ID", "").strip()
        else None
    )
    return connect_operations(
        DB,
        operation_scope="dynamic_scheduler_step",
        operation_id=operation_id,
    )


def tick():
    # 周末完全静默：不建日志、不动排程状态、不累计错误。
    if quiet_hours.is_weekend():
        return
    # 夜间静默：不抓/不处理/不调任何 API(含 DeepSeek)。
    if quiet_hours.in_quiet_hours():
        log(f"QUIET HOURS — skip tick(上海 {quiet_hours.now_tz().strftime('%Y-%m-%d %H:%M')},静默 "
            f"{CFG['quiet_hours']['start']}–{CFG['quiet_hours']['end']})")
        return
    tick_time = now().replace(second=0, microsecond=0)
    tick_minutes = max(1, int((CFG.get("runtime", {}) or {}).get("tick_frequency_min", 15)))
    tick_time = tick_time.replace(minute=tick_time.minute - tick_time.minute % tick_minutes)
    install_operation_context(
        cutover_unit="operations_governance",
        operation_scope="dynamic_scheduler_tick",
        logical_window=tick_time.isoformat(timespec="minutes"),
    )
    read_con = connect_operations(DB, readonly=True)
    rows = read_con.execute("SELECT * FROM fetch_schedule WHERE is_active=1 ORDER BY next_run_at").fetchall()
    ran = deferred_count = failed_count = skipped = stale_reset = 0
    log(f"TICK start — {len(rows)} active targets")
    for row in rows:
        sid = row["id"]
        is_voice = row["target_type"] == "voice_leader"
        if is_voice and not voice_window_open(now()):
            skipped += 1
            continue
        # 僵死锁自动重置(修订3)
        if row["is_running"]:
            started = row["running_started_at"]
            if started and (now() - datetime.fromisoformat(started)) >= timedelta(minutes=STALE_MIN):
                stale_con = _operation_connection(
                    f"schedule:{sid}:stale-reset:{started}"
                )
                try:
                    stale_con.execute(
                        """UPDATE fetch_schedule
                              SET is_running=0,last_error='stale_reset'
                            WHERE id=? AND is_running=1 AND running_started_at=?""",
                        (sid, started),
                    )
                    stale_con.commit()
                finally:
                    stale_con.close()
                stale_reset += 1
                log(f"  stale lock reset: {row['target_label']}")
            else:
                skipped += 1; continue
        compatibility_retry = _controlled_compatibility_retry(row)
        if row["status"] == "paused" and not compatibility_retry:
            skipped += 1; continue
        # 到点判断
        if (
            row["next_run_at"]
            and datetime.fromisoformat(row["next_run_at"]) > now()
            and not compatibility_retry
        ):
            skipped += 1; continue
        # 原子加锁(防并发 tick 抢同一 target)
        due_key = str(row["next_run_at"] or "initial")
        acquire_con = _operation_connection(f"schedule:{sid}:acquire:{due_key}")
        try:
            acquired = try_lock(
                acquire_con,
                sid,
                allow_compatibility_retry=compatibility_retry,
            )
            acquire_con.commit()
        finally:
            acquire_con.close()
        if not acquired:
            skipped += 1; continue
        outcome = "success"; err = None
        try:
            run_fetch(read_con, row)
        except ScheduledFetchDeferred as e:
            outcome = "deferred"; err = str(e)[:200]
        except Exception as e:
            outcome = "error"; err = str(e)[:200]
        # R5:完成时用最新时刻算 next_run_at(不是 tick 开始时刻)
        base_freq = freq_for(read_con, row)
        completed_at = now()
        ts = completed_at.isoformat(timespec="seconds")
        outcome_con = _operation_connection(f"schedule:{sid}:outcome:{due_key}")
        if outcome == "success":
            next_at = completed_at + timedelta(minutes=base_freq)
            if is_voice:
                next_at = next_allowed_voice_time(next_at)
            nxt = next_at.isoformat(timespec="seconds")
            outcome_con.execute("""UPDATE fetch_schedule SET is_running=0, last_run_at=?, next_run_at=?,
                           error_count=0, last_error=NULL, running_started_at=NULL,
                           status='active', updated_at=? WHERE id=?""",
                        (ts, nxt, ts, sid))
            ran += 1
        elif outcome == "deferred":
            # A retail Xinghan paginator can legitimately own the one-per-minute
            # subject/infos token for hours.  This is neither a completed fetch
            # nor a producer failure: preserve last_run_at/status/error_count and
            # the last real error, release the row lock, then retry next tick.
            tick_freq = int((CFG.get("runtime", {}) or {}).get("tick_frequency_min", 15) or 15)
            retry_minutes = max(1, min(base_freq, tick_freq))
            next_at = completed_at + timedelta(minutes=retry_minutes)
            if is_voice:
                next_at = next_allowed_voice_time(next_at)
            nxt = next_at.isoformat(timespec="seconds")
            outcome_con.execute("""UPDATE fetch_schedule SET is_running=0, next_run_at=?,
                           running_started_at=NULL, updated_at=? WHERE id=?""",
                        (nxt, ts, sid))
            deferred_count += 1
            log(f"  DEFER {row['target_label']}: {err} | error_count unchanged="
                f"{row['error_count']} retry={retry_minutes}min next={nxt}")
        else:
            # P0-1:指数退避 backoff_freq = min(base_freq × 2^ec, 360);ec=新 error_count
            #       (验收:首次失败 ec=1 → next_run_at = now + base_freq×2)。封顶 6h。
            ec = row["error_count"] + 1
            backoff_freq = min(base_freq * (2 ** ec), 360)
            next_at = completed_at + timedelta(minutes=backoff_freq)
            if is_voice:
                next_at = next_allowed_voice_time(next_at)
            nxt = next_at.isoformat(timespec="seconds")
            # 任意异常都不能伪装成最近检查成功。ScheduledFetchError 可显式给出
            # ``error``；超时等未包装异常也必须 fail closed 为 ``error``。
            st = "paused" if ec >= 3 else "error"
            failed_count += 1
            outcome_con.execute("""UPDATE fetch_schedule SET is_running=0, last_run_at=?, next_run_at=?,
                           error_count=?, last_error=?, running_started_at=NULL,
                           status=?, updated_at=? WHERE id=?""",
                        (ts, nxt, ec, err, st, ts, sid))
            log(f"  FAIL {row['target_label']}: {err} | ec={ec} base={base_freq}min "
                f"backoff_freq={backoff_freq}min next={nxt}{' → PAUSED' if st=='paused' else ''}")
        try:
            outcome_con.commit()
        finally:
            outcome_con.close()
    log(f"TICK done — ran={ran} deferred={deferred_count} skipped={skipped} "
        f"stale_reset={stale_reset}")
    read_con.close()
    if failed_count:
        return 2
    if deferred_count and not ran:
        return 75
    return 0


def status():
    con = connect_operations(DB, readonly=True)
    # P0附:freq_actual 列 —— voice_leader 显示按时区计算的实际频率 freq_for(row)
    print(f"{'type':<16}{'label':<16}{'freq':>6}{'freq_act':>9}{'ec':>4}{'run':>4}{'status':>9}  next_run_at")
    for r in con.execute("SELECT * FROM fetch_schedule ORDER BY target_type, id"):
        fa = freq_for(con, r)
        print(f"{r['target_type']:<16}{(r['target_label'] or ''):<16}{r['frequency_minutes']:>6}"
              f"{fa:>9}{r['error_count']:>4}{r['is_running']:>4}{r['status']:>9}  {r['next_run_at'] or '-'}")
    con.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "tick"
    if cmd == "status":
        status()
    else:
        raise SystemExit(tick() or 0)
