"""System-tray icon for the background service.

Shows that the service is running (with a status dot), and gives quick access to the app,
the public tunnel, start-at-sign-in, logs, updates and Quit. Failed background runs pop a
notification. pystray runs its own message loop on a thread; menu actions that touch the
service are handed to the asyncio loop with ``run_coroutine_threadsafe``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Any

from . import APP_NAME, autostart, paths
from .icon import draw

if TYPE_CHECKING:
    from .service import StudioService

logger = logging.getLogger(__name__)
_GREEN, _AMBER, _RED = (62, 207, 142), (245, 184, 74), (255, 93, 108)
_NOTIFY_GAP = 20.0  # seconds between failure notifications (avoid floods from a broken schedule)


def open_window() -> None:
    """Open (or focus) the desktop window in its own process."""
    flags = subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0
    subprocess.Popen(paths.window_command(), creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def copy_to_clipboard(text: str) -> None:
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    data = (text + "\0").encode("utf-16-le")
    if not user32.OpenClipboard(None):
        return
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        ctypes.memmove(kernel32.GlobalLock(handle), data, len(data))
        kernel32.GlobalUnlock(handle)
        user32.SetClipboardData(13, handle)  # CF_UNICODETEXT; the clipboard now owns the memory
    finally:
        user32.CloseClipboard()


class TrayController:
    def __init__(self, service: StudioService, loop: asyncio.AbstractEventLoop) -> None:
        self.svc = service
        self.loop = loop
        self.icon: Any = None
        self._badge: tuple[int, int, int] | None = None
        self._last_notify = 0.0

    # ---- lifecycle

    def start(self) -> None:
        import pystray
        from pystray import Menu, MenuItem as Item

        def run(coro_factory: Any) -> Any:
            return lambda icon, item: asyncio.run_coroutine_threadsafe(coro_factory(), self.loop)

        tunnel_on = lambda item: bool(self.svc.tunnel_settings().get("enabled"))  # noqa: E731
        update = lambda: self.svc.updates.latest  # noqa: E731

        menu = Menu(
            Item(f"Open {APP_NAME}", lambda icon, item: open_window(), default=True),
            Menu.SEPARATOR,
            Item(lambda item: self._summary(), None, enabled=False),
            Item(lambda item: f"Public: {self.svc.tunnel.status()['webhook_base']}", None, enabled=False,
                 visible=lambda item: bool(self.svc.tunnel.public_url)),
            Item("Copy public webhook URL", lambda icon, item: copy_to_clipboard(self.svc.tunnel.status()["webhook_base"] or ""),
                 visible=lambda item: bool(self.svc.tunnel.public_url)),
            Item("Public webhooks (tunnel)", run(lambda: self.svc.set_tunnel_enabled(not tunnel_on(None))),
                 checked=tunnel_on),
            Item("Start at sign-in", lambda icon, item: self._toggle_autostart(),
                 checked=lambda item: autostart.status()["enabled"]),
            Menu.SEPARATOR,
            Item(lambda item: f"Install update {update().version}" if update() else "Install update",
                 lambda icon, item: open_window(), visible=lambda item: self.svc.updates.available),
            Item("Check for updates", run(self.svc.updates.check), visible=lambda item: bool(self.svc.updates.source)),
            Item("Open logs folder", lambda icon, item: os.startfile(paths.LOG_DIR)),  # type: ignore[attr-defined]
            Menu.SEPARATOR,
            Item("Quit (stop background workflows)", lambda icon, item: self.loop.call_soon_threadsafe(self.svc.request_shutdown)),
        )
        self.icon = pystray.Icon("AutomationStudio", draw(64, badge=_GREEN), APP_NAME, menu)
        self.icon.run_detached()
        logger.info("tray icon started")

    def stop(self) -> None:
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                logger.exception("tray stop failed")
            self.icon = None

    # ---- updates from the service loop

    def refresh(self) -> None:
        if self.icon is None:
            return
        errors = bool(self.svc.triggers.errors)
        tunnel = self.svc.tunnel.state
        badge = _RED if errors or tunnel == "error" else _AMBER if self.svc.updates.available else _GREEN
        if badge != self._badge:
            self._badge = badge
            self.icon.icon = draw(64, badge=badge)
        self.icon.title = f"{APP_NAME} - {self._summary()}"[:127]  # Windows tooltip limit
        self.icon.update_menu()

    def notify_failure(self, workflow: str, error: str | None) -> None:
        if self.icon is None or time.monotonic() - self._last_notify < _NOTIFY_GAP:
            return
        self._last_notify = time.monotonic()
        try:
            self.icon.notify((error or "failed")[:200], f"Workflow failed: {workflow}"[:63])
        except Exception:
            logger.exception("tray notification failed")

    # ---- helpers

    def _summary(self) -> str:
        n = len(self.svc.triggers.status())
        running = len(self.svc.engine.active_executions)
        parts = [f"{n} active workflow{'s' if n != 1 else ''}"]
        if running:
            parts.append(f"{running} running")
        if self.svc.triggers.errors:
            parts.append(f"{len(self.svc.triggers.errors)} trigger error(s)")
        return ", ".join(parts)

    def _toggle_autostart(self) -> None:
        (autostart.disable if autostart.status()["enabled"] else autostart.enable)()
