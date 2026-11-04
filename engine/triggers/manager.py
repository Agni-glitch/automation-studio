"""TriggerManager: keeps active workflows listening and launches executions when they fire.

    manager = TriggerManager(engine, on_result=db.save_execution)
    await manager.activate(workflow)      # starts its webhook / folder / schedule listeners
    ...
    await manager.stop()
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from ..core import ExecutionHandle, WorkflowEngine, WorkflowGraph
from ..errors import WorkflowValidationError
from ..expressions import render_parameters
from ..models import ExecutionResult, WorkflowDefinition
from .base import TriggerError, TriggerListener
from .file_watch import FileWatchListener
from .schedule import ScheduleListener
from .webhook import WebhookListener, WebhookServer

logger = logging.getLogger(__name__)

LISTENERS: dict[str, type[TriggerListener]] = {
    "trigger.webhook": WebhookListener,
    "trigger.file": FileWatchListener,
    "trigger.schedule": ScheduleListener,
}

ResultCallback = Callable[[ExecutionResult], Awaitable[None] | None]


@dataclass
class _Active:
    workflow: WorkflowDefinition
    graph: WorkflowGraph
    listeners: list[TriggerListener]
    marker: Any = None  # caller-defined change marker (e.g. updated_at) used by sync()
    running: set[ExecutionHandle] = field(default_factory=set)


class TriggerManager:
    def __init__(
        self,
        engine: WorkflowEngine,
        *,
        host: str = "127.0.0.1",
        port: int = 5678,
        on_result: ResultCallback | None = None,
        max_body_bytes: int = 10 * 1024 * 1024,
    ) -> None:
        self.engine = engine
        self.on_result = on_result
        self.max_body_bytes = max_body_bytes
        self._webhooks = WebhookServer(host, port, max_body_bytes)
        self._active: dict[str, _Active] = {}
        self._result_tasks: set[asyncio.Task[None]] = set()
        self.errors: dict[str, str] = {}  # workflow id -> last activation error
        self._failed_marker: dict[str, Any] = {}

    # ---- lifecycle

    async def webhook_server(self) -> WebhookServer:
        await self._webhooks.start()
        return self._webhooks

    @property
    def webhook_port(self) -> int:
        return self._webhooks.port

    def webhook_routes(self) -> list[dict[str, str]]:
        return self._webhooks.routes()

    async def activate(self, workflow: WorkflowDefinition | dict | str, *, marker: Any = None) -> list[str]:
        """(Re)start all listening triggers of a workflow. Returns their descriptions."""
        wf = self.engine.parse(workflow)
        graph = self.engine.validate(wf)
        await self.deactivate(wf.id)

        listeners: list[TriggerListener] = []
        try:
            for node_id in graph.roots:
                node = graph.nodes[node_id]
                listener_cls = LISTENERS.get(node.type)
                if node.disabled or listener_cls is None:
                    continue
                node_cls = self.engine.registry.get(node.type)
                # Trigger settings may use {{ vars.x }} (e.g. a folder path); nothing else exists yet.
                rendered = render_parameters(node.parameters, {"vars": wf.variables})
                params = node_cls.Parameters.model_validate(rendered)
                listener = listener_cls(self, wf, node, params)
                await listener.start()
                listeners.append(listener)
        except BaseException:
            for listener in listeners:
                await listener.stop()
            raise

        self._active[wf.id] = _Active(wf, graph, listeners, marker)
        self.errors.pop(wf.id, None)
        self._failed_marker.pop(wf.id, None)
        descriptions = [listener.describe() for listener in listeners]
        if descriptions:
            for d in descriptions:
                logger.info("activated '%s': %s", wf.name, d)
        else:
            logger.warning("workflow '%s' has no listening triggers (webhook/file/schedule)", wf.name)
        return descriptions

    async def deactivate(self, workflow_id: str) -> bool:
        entry = self._active.pop(workflow_id, None)
        if entry is None:
            return False
        for listener in entry.listeners:
            try:
                await listener.stop()
            except Exception:
                logger.exception("failed to stop trigger %s", listener.node.id)
        logger.info("deactivated '%s'", entry.workflow.name)
        return True

    async def sync(self, workflows: Iterable[tuple[WorkflowDefinition, Any]]) -> None:
        """Make the active set match ``(workflow, marker)`` pairs; re-activate when the marker changes."""
        desired = {wf.id: (wf, marker) for wf, marker in workflows}
        for wf_id in list(self._active):
            if wf_id not in desired:
                await self.deactivate(wf_id)
        for wf_id, (wf, marker) in desired.items():
            current = self._active.get(wf_id)
            if current is not None and current.marker == marker:
                continue
            if current is None and wf_id in self.errors and self._failed_marker.get(wf_id) == marker:
                continue  # already failed for this version; don't retry/log every poll
            try:
                await self.activate(wf, marker=marker)
            except (TriggerError, WorkflowValidationError, ValueError, OSError) as exc:
                self.errors[wf_id] = str(exc)
                self._failed_marker[wf_id] = marker
                logger.error("cannot activate '%s': %s", wf.name, exc)

    async def stop(self, grace_seconds: float = 10) -> None:
        for wf_id in list(self._active):
            await self.deactivate(wf_id)
        await self._webhooks.stop()
        if self._result_tasks:
            _, pending = await asyncio.wait(self._result_tasks, timeout=grace_seconds)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    # ---- firing

    def fire(self, workflow_id: str, node_id: str, data: Any) -> ExecutionHandle:
        entry = self._active.get(workflow_id)
        if entry is None:
            raise TriggerError(f"workflow {workflow_id} is not active")
        handle = self.engine.start(entry.workflow, trigger_data=data, start_node=node_id)
        entry.running.add(handle)
        logger.info("'%s' triggered by %s -> execution %s", entry.workflow.name, node_id, handle.execution_id)
        task = asyncio.create_task(self._finish(entry, handle))
        self._result_tasks.add(task)
        task.add_done_callback(self._result_tasks.discard)
        return handle

    async def _finish(self, entry: _Active, handle: ExecutionHandle) -> None:
        try:
            result = await handle.result()
        except asyncio.CancelledError:
            handle.cancel()
            raise
        finally:
            entry.running.discard(handle)
        logger.info("execution %s finished: %s%s", result.execution_id, result.status.value,
                    f" ({result.error})" if result.error else "")
        if self.on_result is not None:
            try:
                outcome = self.on_result(result)
                if inspect.isawaitable(outcome):
                    await outcome
            except Exception:
                logger.exception("on_result callback failed for execution %s", result.execution_id)

    # ---- introspection

    def graph(self, workflow_id: str) -> WorkflowGraph:
        return self._active[workflow_id].graph

    def status(self) -> list[dict[str, Any]]:
        return [
            {
                "workflow_id": wf_id,
                "name": entry.workflow.name,
                "triggers": [listener.describe() for listener in entry.listeners],
                "running_executions": len(entry.running),
            }
            for wf_id, entry in self._active.items()
        ]
