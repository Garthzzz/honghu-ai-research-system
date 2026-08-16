#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""智慧星光 ``subject/infos`` 账号级跨进程限流。

零数据库依赖；Xinghan 窗口抓取与 KOL 快搜必须共享同一个 state/lock。阻塞型调用
用于窗口分页，非阻塞型调用用于事件/KOL 任务：后者在窗口补抓占用令牌时立即退让，
避免两个独立 scheduler 进程同时命中供应商 429。
"""
from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[3]
from tools.runtime_paths import resolve_runtime_layout
DEFAULT_CACHE_DIR = resolve_runtime_layout(ROOT).cache_root / "yuqing"
DEFAULT_INTERVAL_SECONDS = 65.0


@dataclass(frozen=True)
class RateLimitDecision:
    acquired: bool
    reason: str
    retry_after_seconds: float
    marked_at: float | None = None


class SharedSubjectInfosLimiter:
    """一个账号级原子令牌，兼容旧 ``rl_infos``/``last_call`` 水位文件。"""

    def __init__(
        self,
        *,
        cache_dir: Path | str = DEFAULT_CACHE_DIR,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.interval_seconds = max(0.0, float(interval_seconds))
        self.clock = clock
        self.sleeper = sleeper
        # 保留既有文件名，升级时当前/旧进程也能互相看到最近调用水位。
        self.state_paths = (
            self.cache_dir / "rl_infos.txt",
            self.cache_dir / "last_call.txt",
        )
        self.lock_path = self.cache_dir / "subject_infos.lock"

    @staticmethod
    def _lock_handle(handle, *, acquire: bool) -> None:
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt

            mode = msvcrt.LK_NBLCK if acquire else msvcrt.LK_UNLCK
            msvcrt.locking(handle.fileno(), mode, 1)
        else:
            import fcntl

            mode = (fcntl.LOCK_EX | fcntl.LOCK_NB) if acquire else fcntl.LOCK_UN
            fcntl.flock(handle.fileno(), mode)

    @contextmanager
    def _lock(self, *, blocking: bool, timeout_seconds: float | None = None):
        handle = self.lock_path.open("a+b")
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        deadline = None if timeout_seconds is None else self.clock() + max(0.0, timeout_seconds)
        acquired = False
        try:
            while not acquired:
                try:
                    self._lock_handle(handle, acquire=True)
                    acquired = True
                except (OSError, BlockingIOError):
                    if not blocking:
                        break
                    if deadline is not None and self.clock() >= deadline:
                        raise TimeoutError(f"subject/infos limiter lock timeout: {self.lock_path}")
                    self.sleeper(0.05)
            yield acquired
        finally:
            if acquired:
                self._lock_handle(handle, acquire=False)
            handle.close()

    def _latest_unlocked(self) -> float:
        latest = 0.0
        for path in self.state_paths:
            try:
                latest = max(latest, float(path.read_text(encoding="utf-8").strip()))
            except (OSError, TypeError, ValueError):
                continue
        return latest

    def _write_unlocked(self, timestamp: float) -> None:
        value = str(float(timestamp))
        for index, path in enumerate(self.state_paths):
            temp = path.with_name(f".{path.name}.{os.getpid()}.{index}.tmp")
            temp.write_text(value, encoding="utf-8")
            temp.replace(path)

    def _cooldown(self, *, now: float, latest: float) -> float:
        # 系统时间回拨/坏水位最多等待一个完整间隔，不允许异常 future 值锁死任务。
        if latest <= 0:
            return 0.0
        return max(0.0, min(self.interval_seconds, self.interval_seconds - (now - latest)))

    def acquire(self, *, timeout_seconds: float | None = None) -> RateLimitDecision:
        """阻塞取得下一调用令牌；等待期间持有互斥，让非阻塞 KOL 请求立即退让。"""
        with self._lock(blocking=True, timeout_seconds=timeout_seconds) as acquired:
            if not acquired:  # blocking=True 正常不会走到这里
                raise TimeoutError("subject/infos limiter unavailable")
            now = self.clock()
            wait_seconds = self._cooldown(now=now, latest=self._latest_unlocked())
            if wait_seconds > 0:
                self.sleeper(wait_seconds)
            marked_at = self.clock()
            self._write_unlocked(marked_at)
            return RateLimitDecision(True, "acquired", 0.0, marked_at)

    def try_acquire(self) -> RateLimitDecision:
        """不等待；锁忙或仍在冷却期时不消耗令牌。"""
        with self._lock(blocking=False) as acquired:
            if not acquired:
                return RateLimitDecision(False, "busy", self.interval_seconds)
            now = self.clock()
            wait_seconds = self._cooldown(now=now, latest=self._latest_unlocked())
            if wait_seconds > 0:
                return RateLimitDecision(False, "cooldown", wait_seconds)
            self._write_unlocked(now)
            return RateLimitDecision(True, "acquired", 0.0, now)
