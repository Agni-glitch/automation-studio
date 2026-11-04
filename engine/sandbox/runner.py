"""Run user Python code in a separate, resource-limited process.

What this protects against: crashes, infinite loops (timeout), memory blowups and
child-process spawning (Windows Job Object), leaking the engine's environment variables
and secrets (stripped env), and littering (fresh temp working directory).

What it does NOT protect against: deliberately malicious code. The script runs as your
Windows user with network and file-system access. Only run scripts you trust.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import NodeExecutionError, NodeTimeoutError

BOOTSTRAP = Path(__file__).with_name("_bootstrap.py")
MARK = "__WF_RESULT__"
IS_WINDOWS = sys.platform == "win32"


@dataclass
class ScriptResult:
    ok: bool
    result: Any = None
    logs: list[str] = field(default_factory=list)
    error: dict[str, str] | None = None
    duration_ms: float = 0.0


def default_python() -> str:
    """The real interpreter, not the venv launcher (which would spawn a second, unconfined process).

    In the packaged app ``sys.executable`` is AutomationStudio.exe, so scripts run on the
    embeddable CPython bundled next to it (``python/python.exe``).
    """
    if getattr(sys, "frozen", False):
        bundled = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "python" / "python.exe"
        if bundled.exists():
            return str(bundled)
        raise NodeExecutionError(f"bundled Python not found at {bundled}; reinstall the app")
    base = getattr(sys, "_base_executable", None)
    if base and Path(base).exists():
        return base
    return sys.executable


def _site_paths() -> list[str]:
    return [p for p in sys.path if p and "site-packages" in p]


def _minimal_env() -> dict[str, str]:
    keep = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "PATHEXT", "COMSPEC", "PATH", "LANG")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


# ------------------------------------------------------------------ Windows Job Object

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _BASIC_LIMITS(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _EXTENDED_LIMITS(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BASIC_LIMITS),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]

    _JobObjectExtendedLimitInformation = 9
    _LIMIT_ACTIVE_PROCESS = 0x0008
    _LIMIT_PROCESS_MEMORY = 0x0100
    _LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x0400
    _LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _PROCESS_SET_QUOTA, _PROCESS_TERMINATE = 0x0100, 0x0001

    def confine_process(pid: int, memory_limit_mb: int | None = None, single_process: bool = False) -> int:
        """Put a process in a job object that is killed when the returned handle closes
        (including when this Python process dies). Optionally cap memory / forbid children."""
        job = _k32.CreateJobObjectW(None, None)
        if not job:
            raise OSError(ctypes.get_last_error(), "CreateJobObject failed")
        info = _EXTENDED_LIMITS()
        flags = _LIMIT_DIE_ON_UNHANDLED_EXCEPTION | _LIMIT_KILL_ON_JOB_CLOSE
        if single_process:
            flags |= _LIMIT_ACTIVE_PROCESS
            info.BasicLimitInformation.ActiveProcessLimit = 1
        if memory_limit_mb:
            flags |= _LIMIT_PROCESS_MEMORY
            info.ProcessMemoryLimit = memory_limit_mb * 1024 * 1024
        info.BasicLimitInformation.LimitFlags = flags
        process = None
        try:
            if not _k32.SetInformationJobObject(
                job, _JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
            ):
                raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
            process = _k32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
            if not process or not _k32.AssignProcessToJobObject(job, process):
                raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
        except BaseException:
            _k32.CloseHandle(job)
            raise
        finally:
            if process:
                _k32.CloseHandle(process)
        return job

    def release_job(job: int) -> None:
        _k32.CloseHandle(job)  # KILL_ON_JOB_CLOSE terminates anything still running


# ------------------------------------------------------------------ runner


async def run_python(
    code: str,
    *,
    input: Any = None,
    inputs: dict[str, Any] | None = None,
    arguments: dict[str, Any] | None = None,
    timeout: float = 30,
    memory_limit_mb: int = 512,
    python_executable: str | None = None,
) -> ScriptResult:
    job_payload = json.dumps({
        "code": code,
        "input": input,
        "inputs": inputs or {},
        "arguments": arguments or {},
        "sys_path": _site_paths(),
    }).encode("utf-8")

    workdir = tempfile.mkdtemp(prefix="wf-script-")
    started = time.perf_counter()
    job = None
    proc = await asyncio.create_subprocess_exec(
        python_executable or default_python(), "-I", "-X", "utf8", str(BOOTSTRAP),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=workdir,
        env=_minimal_env(),
        creationflags=0x08000000 if IS_WINDOWS else 0,  # CREATE_NO_WINDOW
    )
    try:
        if IS_WINDOWS:
            # The bootstrap blocks on stdin, so no user code runs before confinement.
            job = confine_process(proc.pid, memory_limit_mb, single_process=True)
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(job_payload), timeout)
        except TimeoutError:
            raise NodeTimeoutError(f"script exceeded its {timeout}s time limit") from None
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        if job is not None:
            release_job(job)
        shutil.rmtree(workdir, ignore_errors=True)

    duration = (time.perf_counter() - started) * 1000
    out_text = stdout.decode("utf-8", errors="replace")
    marked = [line for line in out_text.splitlines() if line.startswith(MARK)]
    if not marked:
        err_tail = stderr.decode("utf-8", errors="replace").strip()[-1000:]
        hint = " (possibly killed for exceeding the memory limit)" if proc.returncode not in (0, None) else ""
        raise NodeExecutionError(f"script process exited with code {proc.returncode}{hint}: {err_tail}")
    data = json.loads(marked[-1][len(MARK):])
    return ScriptResult(
        ok=data["ok"],
        result=data.get("result"),
        logs=data.get("logs", []),
        error=data.get("error"),
        duration_ms=duration,
    )
