"""Schedule trigger: cron (local time) or fixed interval."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import datetime, timedelta

from ..core import ExecutionHandle
from .base import TriggerListener
from .cron import CronExpression

logger = logging.getLogger(__name__)

# Sleep in short chunks and re-check the wall clock, so laptop sleep/hibernate and DST
# changes can't make a schedule drift or fire hours late.
_MAX_NAP = 30.0


class ScheduleListener(TriggerListener):
    _task: asyncio.Task[None] | None = None
    _current: ExecutionHandle | None = None
    next_fire: datetime | None = None

    async def start(self) -> None:
        self._cron = CronExpression(self.params.cron) if self.params.mode == "cron" else None
        self._task = asyncio.create_task(self._loop(), name=f"schedule:{self.workflow.id}:{self.node.id}")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def describe(self) -> str:
        if self._cron is not None:
            nxt = self._cron.next_after(datetime.now())
            return f"schedule cron '{self.params.cron}' (next {nxt:%Y-%m-%d %H:%M})"
        return f"schedule every {self.params.every_seconds:g}s"

    async def _loop(self) -> None:
        if self.params.run_on_start:
            self._fire(datetime.now())
        if self._cron is not None:
            while True:
                self.next_fire = self._cron.next_after(datetime.now())
                await _sleep_until_wall(self.next_fire)
                self._fire(self.next_fire)
        else:
            interval = float(self.params.every_seconds)
            due = time.monotonic() + interval
            while True:
                self.next_fire = datetime.now() + timedelta(seconds=max(0.0, due - time.monotonic()))
                await asyncio.sleep(max(0.0, due - time.monotonic()))
                self._fire(datetime.now())
                due = max(due + interval, time.monotonic())  # don't burst after a long stall

    def _fire(self, scheduled_for: datetime) -> None:
        if self.params.skip_if_running and self._current is not None and not self._current.done():
            logger.info("schedule %s/%s: previous run still active, skipping", self.workflow.name, self.node.id)
            return
        self._current = self.fire({
            "scheduled_for": scheduled_for.isoformat(timespec="seconds"),
            "fired_at": datetime.now().isoformat(timespec="seconds"),
        })


async def _sleep_until_wall(target: datetime) -> None:
    while (remaining := (target - datetime.now()).total_seconds()) > 0:
        await asyncio.sleep(min(remaining, _MAX_NAP))
