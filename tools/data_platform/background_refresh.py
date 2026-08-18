from __future__ import annotations

"""One daemon queue for disposable PostgreSQL read-projection refreshes."""

import queue
import threading
from collections.abc import Callable


_QUEUE: queue.Queue[Callable[[], None]] = queue.Queue()
_START_LOCK = threading.Lock()
_STARTED = False


def _worker() -> None:
    while True:
        callback = _QUEUE.get()
        try:
            callback()
        finally:
            _QUEUE.task_done()


def submit_background_refresh(callback: Callable[[], None]) -> None:
    """Serialize maintenance so refresh bursts cannot starve Viewer requests."""

    global _STARTED
    with _START_LOCK:
        if not _STARTED:
            threading.Thread(
                target=_worker,
                name="honghu-read-projection-refresh",
                daemon=True,
            ).start()
            _STARTED = True
    _QUEUE.put(callback)

