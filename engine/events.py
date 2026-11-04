"""Execution events: the real-time feed for logs, the GUI and persistence.

The engine emits events into a per-execution queue that delivers them, in order, to
every listener subscribed on the ``EventBus``. Listeners may be sync or async; a failing
listener is logged and never breaks a workflow run.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .models import utcnow

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    EXECUTION_STARTED = "execution.started"
    EXECUTION_FINISHED = "execution.finished"
    NODE_STARTED = "node.started"
    NODE_SUCCEEDED = "node.succeeded"
    NODE_FAILED = "node.failed"
    NODE_SKIPPED = "node.skipped"
    NODE_CANCELLED = "node.cancelled"
    NODE_RETRY = "node.retry"
    NODE_LOG = "node.log"


class ExecutionEvent(BaseModel):
    type: EventType
    execution_id: str
    workflow_id: str
    node_id: str | None = None
    timestamp: datetime = Field(default_factory=utcnow)
    payload: dict[str, Any] = Field(default_factory=dict)


Listener = Callable[[ExecutionEvent], Awaitable[None] | None]


class EventBus:
    def __init__(self) -> None:
        self._listeners: list[Listener] = []

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        """Register a listener; returns a function that unsubscribes it."""
        self._listeners.append(listener)

        def unsubscribe() -> None:
            with contextlib.suppress(ValueError):
                self._listeners.remove(listener)

        return unsubscribe

    async def emit(self, event: ExecutionEvent) -> None:
        for listener in list(self._listeners):
            try:
                result = listener(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("Event listener %r failed on %s", listener, event.type)

    @contextlib.asynccontextmanager
    async def stream(
        self, execution_id: str | None = None, maxsize: int = 10_000
    ) -> AsyncIterator[asyncio.Queue[ExecutionEvent]]:
        """Yield a queue receiving events (optionally for one execution), e.g. for a websocket."""
        queue: asyncio.Queue[ExecutionEvent] = asyncio.Queue(maxsize=maxsize)

        def push(event: ExecutionEvent) -> None:
            if execution_id is not None and event.execution_id != execution_id:
                return
            if queue.full():  # slow consumer: drop the oldest event rather than block the engine
                queue.get_nowait()
            queue.put_nowait(event)

        unsubscribe = self.subscribe(push)
        try:
            yield queue
        finally:
            unsubscribe()
