from __future__ import annotations

"""Bind a production task process tree to one kill-on-close Windows Job.

The outer task runner enrolls itself before authority checks or producer work.
Every subprocess subsequently created by the runner inherits Job membership.
If Task Scheduler terminates the runner, Windows closes the owning handle and
terminates all surviving descendants as one unit.
"""

import os


_SELF_JOB_HANDLE: int | None = None
_PARENT_JOB_MARKER = "HONGHU_TASK_KILL_ON_CLOSE_JOB"


def ensure_self_killing_job() -> bool:
    """Own or inherit the reviewed kill-on-close task Job.

    The outer task runner creates the Job and deliberately keeps its only
    handle.  Descendants inherit membership, but not that handle.  They also
    inherit the private marker and verify their membership with
    ``IsProcessInJob`` instead of attempting to create a nested Job.  Thus a
    Task Scheduler stop of the outer runner closes the owning handle and
    reaps the complete process tree immediately.
    """

    global _SELF_JOB_HANDLE
    if os.name != "nt":
        return False
    if _SELF_JOB_HANDLE is not None:
        return True

    import ctypes
    from ctypes import wintypes

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.IsProcessInJob.argtypes = (
        wintypes.HANDLE,
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.BOOL),
    )
    kernel32.IsProcessInJob.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    if os.environ.get(_PARENT_JOB_MARKER) == "1":
        in_job = wintypes.BOOL()
        if not kernel32.IsProcessInJob(
            kernel32.GetCurrentProcess(), None, ctypes.byref(in_job)
        ):
            raise OSError(ctypes.get_last_error(), "IsProcessInJob failed")
        if not in_job.value:
            raise RuntimeError(
                "task Job marker is present but the process is outside the parent Job"
            )
        return True

    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
    try:
        information = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        information.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            handle, 9, ctypes.byref(information), ctypes.sizeof(information)
        ):
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
        if not kernel32.AssignProcessToJobObject(handle, kernel32.GetCurrentProcess()):
            raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
    except Exception:
        kernel32.CloseHandle(handle)
        raise
    # Deliberately retain the only non-inheritable handle for the lifetime of
    # this root process.  Normal exit or forced termination then closes it.
    _SELF_JOB_HANDLE = int(handle)
    os.environ[_PARENT_JOB_MARKER] = "1"
    return True
