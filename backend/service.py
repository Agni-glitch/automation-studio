"""The background service: Studio API + trigger listeners + tunnel, in one process.

Started by ``python main.py serve`` (or at login, see ``autostart``). The GUI is just a
client of this service: closing the window leaves webhooks, folder watchers and schedules
running.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from database import Database
from engine import ExecutionHandle, WorkflowEngine
from engine.models import ExecutionResult, WorkflowDefinition
from engine.triggers.manager import TriggerManager
from engine.triggers.webhook import start_uvicorn, stop_uvicorn

from . import __version__, autostart, paths
from .tunnel import TunnelManager
from .updates import UpdateManager

if TYPE_CHECKING:
    from .tray import TrayController

logger = logging.getLogger(__name__)

TUNNEL_DEFAULTS = {"enabled": False, "mode": "quick", "credential": None, "hostname": None}


class AlreadyRunningError(RuntimeError):
    pass


class InstanceLock:
    """Exclusive lock file; released automatically if the process dies."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh: Any = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+")
        try:
            if sys.platform == "win32":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            raise AlreadyRunningError("the Automation Studio service is already running") from None
        self._fh = fh

    def release(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


def load_or_create_token(path: Path = paths.TOKEN_FILE) -> str:
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if len(token) >= 32:
            return token
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    path.write_text(token, encoding="utf-8")
    return token


class StudioService:
    def __init__(
        self,
        db: Database,
        *,
        api_host: str = "127.0.0.1",
        api_port: int = paths.DEFAULT_API_PORT,
        webhook_host: str = "127.0.0.1",
        webhook_port: int = paths.DEFAULT_WEBHOOK_PORT,
        token: str | None = None,
        dev_origins: tuple[str, ...] = (),
        poll_seconds: float = 3.0,
        bin_dir: Path = paths.BIN_DIR,
        service_file: Path | None = paths.SERVICE_FILE,
        tray: bool = False,
        updates: UpdateManager | None = None,
    ) -> None:
        from .server import create_app  # local import: server imports this module for typing

        self.db = db
        self.engine = WorkflowEngine(credentials=db)
        self.triggers = TriggerManager(self.engine, host=webhook_host, port=webhook_port,
                                       on_result=self._persist_triggered)
        self.updates = updates or UpdateManager(__version__)
        self.updates.source = self.update_settings()["source"]
        self._want_tray = tray
        self.tray: TrayController | None = None
        self.tunnel = TunnelManager(
            bin_dir,
            target_url=lambda: f"http://127.0.0.1:{self.triggers.webhook_port}",
            get_credential=db.get_credential,
        )
        self.token = token or load_or_create_token()
        self.api_host, self.api_port = api_host, api_port
        self.dev_origins = set(dev_origins)
        self.poll_seconds = poll_seconds
        self.service_file = service_file
        self.started_at = datetime.now().astimezone()
        self.app = create_app(self)
        self._sync_lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._shutdown = False
        self._tunnel_applied: dict[str, Any] | None = None
        self._persist_tasks: set[asyncio.Task[None]] = set()
        self.recent_results: OrderedDict[str, ExecutionResult] = OrderedDict()
        self._api: tuple[Any, asyncio.Task[None]] | None = None

    # ---- executions

    async def _persist(self, result: ExecutionResult) -> None:
        # Remember first: the GUI asks for the result as soon as it sees "execution.finished",
        # which can be before the database write completes.
        self.recent_results[result.execution_id] = result
        while len(self.recent_results) > 50:
            self.recent_results.popitem(last=False)
        await asyncio.to_thread(self.db.save_execution, result)

    async def _persist_triggered(self, result: ExecutionResult) -> None:
        """Background (trigger-started) runs: nobody is watching, so failures notify via the tray."""
        await self._persist(result)
        if result.status.value == "failed" and self.tray is not None:
            self.tray.notify_failure(result.workflow_name, result.error)

    def run_workflow(self, workflow: WorkflowDefinition, trigger_data: Any = None,
                     start_node: str | None = None) -> ExecutionHandle:
        handle = self.engine.start(workflow, trigger_data=trigger_data, start_node=start_node)

        async def persist() -> None:
            await self._persist(await handle.result())

        task = asyncio.create_task(persist())
        self._persist_tasks.add(task)
        task.add_done_callback(self._persist_tasks.discard)
        return handle

    # ---- triggers / tunnel reconciliation

    async def sync_triggers(self) -> None:
        async with self._sync_lock:
            active = await asyncio.to_thread(self.db.active_workflows)
            await self.triggers.sync(active)

    def tunnel_settings(self) -> dict[str, Any]:
        return {**TUNNEL_DEFAULTS, **(self.db.get_setting("tunnel") or {})}

    async def set_tunnel_enabled(self, enabled: bool) -> None:
        await asyncio.to_thread(self.db.set_setting, "tunnel", {**self.tunnel_settings(), "enabled": enabled})
        await self.apply_tunnel_settings(force=True)

    def update_settings(self) -> dict[str, Any]:
        defaults = {"source": paths.build_info().get("update_source"), "auto_check": True}
        return {**defaults, **(self.db.get_setting("updates") or {})}

    async def set_update_settings(self, source: str | None, auto_check: bool) -> dict[str, Any]:
        await asyncio.to_thread(self.db.set_setting, "updates", {"source": source or None, "auto_check": auto_check})
        self.updates.source = source or None
        self.updates.latest, self.updates.checked_at, self.updates.error = None, None, None
        return self.updates.status()

    async def install_update(self) -> None:
        installer = await self.updates.download_and_verify()
        self.updates.launch_installer(installer)
        # The installer stops us via `studio.exe stop`; shut down anyway in case it can't reach us.
        asyncio.get_running_loop().call_later(5, self.request_shutdown)

    async def apply_tunnel_settings(self, force: bool = False) -> None:
        wanted = self.tunnel_settings()
        if wanted == self._tunnel_applied and not force:
            return
        self._tunnel_applied = wanted
        if wanted["enabled"]:
            await self.tunnel.start(wanted["mode"], wanted.get("credential"), wanted.get("hostname"))
        else:
            await self.tunnel.stop()

    def wake(self) -> None:
        """Ask the main loop to reconcile now instead of at the next poll."""
        self._wake.set()

    def request_shutdown(self) -> None:
        self._shutdown = True
        self._wake.set()

    # ---- lifecycle

    async def start(self) -> None:
        await self.triggers.webhook_server()
        server, task, self.api_port = await start_uvicorn(self.app, self.api_host, self.api_port, "studio-api")
        self._api = (server, task)
        await self.sync_triggers()
        await self.apply_tunnel_settings()
        if self.service_file is not None:
            self.service_file.write_text(json.dumps({
                "pid": os.getpid(),
                "api_url": self.api_url,
                "webhook_url": f"http://127.0.0.1:{self.triggers.webhook_port}",
                "started_at": self.started_at.isoformat(),
            }), encoding="utf-8")
        logger.info("Studio API on %s, webhooks on port %s", self.api_url, self.triggers.webhook_port)
        if self._want_tray:
            try:
                from .tray import TrayController

                self.tray = TrayController(self, asyncio.get_running_loop())
                self.tray.start()
            except Exception:  # no tray is not fatal (e.g. no desktop session)
                logger.exception("cannot show tray icon")
                self.tray = None

    async def run_forever(self) -> None:
        await self.start()
        update_task: asyncio.Task[Any] | None = None
        try:
            while not self._shutdown:
                try:
                    await asyncio.wait_for(self._wake.wait(), self.poll_seconds)
                except TimeoutError:
                    pass
                self._wake.clear()
                if self._shutdown:
                    break
                try:
                    await self.sync_triggers()  # picks up CLI imports/edits too
                    await self.apply_tunnel_settings()
                    if (self.update_settings()["auto_check"] and self.updates.due()
                            and (update_task is None or update_task.done())):
                        update_task = asyncio.create_task(self.updates.check())
                    if self.tray is not None:
                        self.tray.refresh()
                except Exception:
                    logger.exception("reconcile failed")
        finally:
            if update_task is not None:
                update_task.cancel()
            await self.stop()

    async def stop(self) -> None:
        if self.tray is not None:
            self.tray.stop()
            self.tray = None
        await self.tunnel.stop()
        await self.triggers.stop()
        if self._persist_tasks:
            await asyncio.wait(self._persist_tasks, timeout=10)
        if self._api is not None:
            await stop_uvicorn(*self._api)
            self._api = None
        if self.service_file is not None:
            self.service_file.unlink(missing_ok=True)

    # ---- status

    @property
    def api_url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    def status(self) -> dict[str, Any]:
        tunnel = self.tunnel.status()
        return {
            "version": __version__,
            "frozen": paths.FROZEN,
            "pid": os.getpid(),
            "started_at": self.started_at.isoformat(),
            "api_url": self.api_url,
            "webhook_url": f"http://127.0.0.1:{self.triggers.webhook_port}/webhook/",
            "public_webhook_url": tunnel["webhook_base"],
            "active_workflows": self.triggers.status(),
            "trigger_errors": dict(self.triggers.errors),
            "webhooks": self.triggers.webhook_routes(),
            "running_executions": self.engine.active_executions,
            "tunnel": tunnel,
            "tunnel_settings": self.tunnel_settings(),
            "autostart": autostart.status(),
            "updates": {**self.updates.status(), "auto_check": self.update_settings()["auto_check"]},
            "tray": self.tray is not None,
        }
