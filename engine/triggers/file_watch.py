"""Folder watcher trigger (watchdog; uses ReadDirectoryChangesW on Windows).

Copying a large file produces a burst of created/modified events while it is still being
written. Events per path are coalesced, and the trigger fires only once the file's size has
been stable for ``settle_seconds`` and it can be opened for reading.
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import os
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .base import TriggerError, TriggerListener

logger = logging.getLogger(__name__)
_MAX_SETTLE_WAIT = 600.0  # give up on a file that keeps growing for 10 minutes


class _Forwarder(FileSystemEventHandler):
    def __init__(self, loop: asyncio.AbstractEventLoop, callback: Any) -> None:
        self._loop = loop
        self._callback = callback

    def on_any_event(self, event: FileSystemEvent) -> None:  # runs on the watchdog thread
        if event.is_directory or event.event_type not in ("created", "modified", "deleted", "moved"):
            return
        src = os.fsdecode(event.src_path)
        dest = os.fsdecode(getattr(event, "dest_path", "") or "")
        self._loop.call_soon_threadsafe(self._callback, event.event_type, src, dest)


class FileWatchListener(TriggerListener):
    _observer: Any = None

    async def start(self) -> None:
        self.directory = Path(os.path.expandvars(os.path.expanduser(self.params.directory))).resolve()
        if not self.directory.is_dir():
            raise TriggerError(f"folder does not exist: {self.directory}")
        self._pending: dict[str, tuple[str, str, asyncio.Task[None]]] = {}
        self._observer = Observer()
        handler = _Forwarder(asyncio.get_running_loop(), self._on_event)
        self._observer.schedule(handler, str(self.directory), recursive=self.params.recursive)
        self._observer.start()

    async def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            await asyncio.to_thread(self._observer.join, 5)
            self._observer = None
        for _, _, task in getattr(self, "_pending", {}).values():
            task.cancel()
        self._pending = {}

    def describe(self) -> str:
        return (f"watching {self.directory} for {','.join(self.params.events)} "
                f"({' '.join(self.params.patterns)}{', recursive' if self.params.recursive else ''})")

    # ---- event handling (on the event loop)

    def _wanted(self, path: str) -> bool:
        name = os.path.basename(path).lower()
        if any(fnmatch.fnmatch(name, p.lower()) for p in self.params.ignore_patterns):
            return False
        return any(fnmatch.fnmatch(name, p.lower()) for p in self.params.patterns)

    def _on_event(self, kind: str, src: str, dest: str) -> None:
        if kind == "moved":
            # A rename into a watched name (e.g. "report.pdf.part" -> "report.pdf") is how many
            # apps finish writing; treat it as "created" unless "moved" itself is requested.
            if "moved" in self.params.events and self._wanted(dest):
                self._schedule(dest, "moved", src)
            elif "created" in self.params.events and self._wanted(dest) and not self._wanted(src):
                self._schedule(dest, "created", "")
            return
        if kind not in self.params.events and not (kind == "modified" and src in self._pending):
            return
        if not self._wanted(src):
            return
        if kind == "deleted":
            if (pending := self._pending.pop(src, None)) is not None:
                pending[2].cancel()
            self._emit(src, "deleted", "", size=None)
            return
        # A "modified" right after "created" belongs to the same write: keep the original kind.
        original_kind = self._pending[src][0] if src in self._pending else kind
        self._schedule(src, original_kind, "")

    def _schedule(self, path: str, kind: str, src_path: str) -> None:
        if (pending := self._pending.get(path)) is not None:
            pending[2].cancel()
        task = asyncio.create_task(self._settle(path, kind, src_path))
        self._pending[path] = (kind, src_path, task)

    async def _settle(self, path: str, kind: str, src_path: str) -> None:
        settle = self.params.settle_seconds
        waited, last_size = 0.0, -1
        try:
            while waited <= _MAX_SETTLE_WAIT:
                await asyncio.sleep(settle)
                waited += settle
                try:
                    size = os.path.getsize(path)
                    with open(path, "rb"):
                        pass
                except OSError:  # vanished or still exclusively locked by the writer
                    if not os.path.exists(path):
                        return
                    continue
                if size == last_size or settle == 0:
                    self._pending.pop(path, None)
                    self._emit(path, kind, src_path, size=size)
                    return
                last_size = size
            logger.warning("file %s never stopped changing; not triggering", path)
        finally:
            current = self._pending.get(path)
            if current is not None and current[2] is asyncio.current_task():
                self._pending.pop(path, None)

    def _emit(self, path: str, kind: str, src_path: str, size: int | None) -> None:
        p = Path(path)
        logger.info("file trigger %s/%s: %s %s", self.workflow.name, self.node.id, kind, p)
        self.fire({
            "event": kind,
            "path": str(p),
            "name": p.name,
            "stem": p.stem,
            "extension": p.suffix.lower(),
            "directory": str(p.parent),
            "size": size,
            "src_path": src_path or None,
        })
