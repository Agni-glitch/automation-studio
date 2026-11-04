"""Desktop shell: make sure the background service runs, then show the GUI in a native window.

The window is only a viewer. Closing it does NOT stop the service, so active workflows
(webhooks, folder watchers, schedules) keep working, like a tray app.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time

import httpx

from backend import paths

TITLE = "Automation Studio"


def running_api_url() -> str | None:
    try:
        info = json.loads(paths.SERVICE_FILE.read_text(encoding="utf-8"))
        token = paths.TOKEN_FILE.read_text(encoding="utf-8").strip()
        resp = httpx.get(f"{info['api_url']}/api/status", headers={"X-Studio-Token": token}, timeout=2)
        return info["api_url"] if resp.status_code == 200 else None
    except (OSError, ValueError, KeyError, httpx.HTTPError):
        return None


def ensure_service(timeout: float = 30) -> str:
    if url := running_api_url():
        return url
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    subprocess.Popen(paths.service_command(), creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.3)
        if url := running_api_url():
            return url
    raise RuntimeError(f"the service did not start; see {paths.LOG_DIR / 'service.log'}")


def focus_existing_window() -> bool:
    """If the app window is already open (e.g. tray "Open" clicked twice), bring it forward."""
    if sys.platform != "win32":
        return False
    import ctypes

    user32 = ctypes.windll.user32
    user32.FindWindowExW.restype = ctypes.c_void_p
    user32.FindWindowExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
    hwnd = None
    # Other windows can share the title (e.g. a File Explorer tab on a folder named
    # "Automation Studio"), so only accept pywebview's WinForms window.
    while hwnd := user32.FindWindowExW(None, hwnd, None, TITLE):
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(ctypes.c_void_p(hwnd), cls, 256)
        if cls.value.startswith("WindowsForms10."):
            user32.ShowWindow(ctypes.c_void_p(hwnd), 9)  # SW_RESTORE (also un-minimizes)
            user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
            return True
    return False


def main() -> int:
    if focus_existing_window():
        return 0
    try:
        url = ensure_service()
    except RuntimeError as exc:
        _error_box(str(exc))
        return 1
    import webview  # pywebview; uses the Edge WebView2 runtime built into Windows 11

    webview.create_window(TITLE, url, width=1440, height=900, min_size=(960, 600), text_select=True)
    webview.start(private_mode=False)  # keep localStorage (UI preferences) between sessions
    return 0


def _error_box(message: str) -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, TITLE, 0x10)
    else:
        print(message, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
