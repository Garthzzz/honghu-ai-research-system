from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest
from unittest import mock

from tools.operations.task_child import ALLOWED_TASK_MODULES, main


def test_task_child_has_only_the_seven_task_module_families():
    assert {
        "tools.dynamic.scheduler",
        "tools.sentiment.event_ingest",
        "tools.sentiment.recruit_weekly",
        "tools.sentiment.retail_window_tick",
        "tools.maintenance.sentiment_retention",
        "tools.financial.valuation_market_price_reconcile",
    }.issubset(ALLOWED_TASK_MODULES)


def test_task_child_rejects_an_unreviewed_module():
    with pytest.raises(SystemExit) as exc:
        main(["--task-module", "tools.viewer.app"])
    assert exc.value.code == 2


def test_task_child_enrols_process_tree_before_importing_producer():
    order: list[str] = []
    with mock.patch(
        "tools.operations.task_child.ensure_self_killing_job",
        side_effect=lambda: order.append("job"),
    ), mock.patch(
        "tools.operations.task_child.runpy.run_module",
        side_effect=lambda *_args, **_kwargs: order.append("producer"),
    ):
        assert main(["--task-module", "tools.dynamic.scheduler"]) == 0
    assert order == ["job", "producer"]


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object contract")
def test_killing_enrolled_root_reaps_its_descendant():
    script = r'''
import subprocess, sys, time
from tools.operations.windows_job import ensure_self_killing_job
ensure_self_killing_job()
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
print(child.pid, flush=True)
time.sleep(60)
'''
    root = subprocess.Popen(
        [sys.executable, "-B", "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert root.stdout is not None
    child_pid = int(root.stdout.readline().strip())
    root.kill()
    root.wait(timeout=10)

    import ctypes

    synchronize = 0x00100000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    for _ in range(50):
        handle = kernel32.OpenProcess(synchronize, False, child_pid)
        if not handle:
            break
        try:
            if kernel32.WaitForSingleObject(handle, 0) == 0:
                break
        finally:
            kernel32.CloseHandle(handle)
        time.sleep(0.1)
    else:
        subprocess.run(["taskkill", "/PID", str(child_pid), "/T", "/F"], check=False)
        pytest.fail("enrolled descendant survived root termination")


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object contract")
def test_killing_outer_runner_reaps_child_and_grandchild_without_nested_job():
    child_script = r'''
import subprocess, sys, time
from tools.operations.windows_job import ensure_self_killing_job
ensure_self_killing_job()
grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
print(grandchild.pid, flush=True)
time.sleep(60)
'''
    root_script = r'''
import subprocess, sys, time
from tools.operations.windows_job import ensure_self_killing_job
ensure_self_killing_job()
child = subprocess.Popen(
    [sys.executable, "-B", "-c", sys.argv[1]],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)
print(child.pid, child.stdout.readline().strip(), flush=True)
time.sleep(60)
'''
    root = subprocess.Popen(
        [sys.executable, "-B", "-c", root_script, child_script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert root.stdout is not None
    child_pid, grandchild_pid = map(int, root.stdout.readline().split())
    started = time.monotonic()
    root.kill()
    root.wait(timeout=10)

    import ctypes

    synchronize = 0x00100000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)

    def exited(pid: int) -> bool:
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return True
        try:
            return kernel32.WaitForSingleObject(handle, 0) == 0
        finally:
            kernel32.CloseHandle(handle)

    try:
        deadline = started + 3.0
        while time.monotonic() < deadline:
            if exited(child_pid) and exited(grandchild_pid):
                break
            time.sleep(0.05)
        else:
            pytest.fail("outer Job close did not promptly reap child and grandchild")
    finally:
        for pid in (child_pid, grandchild_pid):
            if not exited(pid):
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"], check=False
                )
