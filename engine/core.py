"""Workflow orchestrator.

Execution model
---------------
* A workflow is a DAG of nodes joined by connections ``source[.source_output] -> target``.
* Scheduling is dynamic, not level-by-level: a node starts the moment *all* of its
  predecessors have finished, so independent branches run in parallel (bounded by
  ``settings.max_concurrency``).
* A node runs only if at least one incoming connection is *active*, meaning its source
  fired the output port that connection is attached to. Otherwise the node is SKIPPED and
  the skip propagates. This is how ``If`` branches and error outputs work.
* Root nodes receive ``trigger_data`` as their input. When ``start_node`` is given (the
  trigger that fired), all other roots are skipped.
* Failures: retried per ``RetryPolicy``; then handled per ``on_error`` (stop / continue /
  error_output). With ``fail_fast`` an unhandled failure cancels everything still running.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from collections import deque
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from pydantic import ValidationError

from .errors import (
    CredentialNotFoundError,
    NodeExecutionError,
    NodeTimeoutError,
    NonRetryableError,
    WorkflowValidationError,
)
from .events import EventBus, EventType, ExecutionEvent
from .expressions import contains_expression, render_parameters
from .models import (
    DEFAULT_OUTPUT,
    ERROR_OUTPUT,
    Connection,
    ExecutionResult,
    ExecutionStatus,
    LogEntry,
    NodeDefinition,
    NodeError,
    NodeRunRecord,
    NodeStatus,
    OnError,
    WorkflowDefinition,
    new_id,
    to_jsonable,
    utcnow,
)
from .nodes import BaseNode, NodeContext, NodeRegistry, NodeResult, default_registry

logger = logging.getLogger(__name__)

_LOG_LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}
_MIN_SECRET_LEN = 4


# --------------------------------------------------------------------------- credentials


@runtime_checkable
class CredentialProvider(Protocol):
    """Implemented by ``database.db`` (encrypted SQLite). Returns decrypted credential data."""

    async def get_credential(self, name: str) -> dict[str, Any]: ...


class InMemoryCredentialProvider:
    """For tests and scripts. Never use for real secrets."""

    def __init__(self, credentials: Mapping[str, dict[str, Any]] | None = None) -> None:
        self._credentials = {k: dict(v) for k, v in (credentials or {}).items()}

    def set(self, name: str, data: dict[str, Any]) -> None:
        self._credentials[name] = dict(data)

    async def get_credential(self, name: str) -> dict[str, Any]:
        try:
            return dict(self._credentials[name])
        except KeyError:
            raise CredentialNotFoundError(f"credential '{name}' does not exist") from None


# --------------------------------------------------------------------------- graph


def _format_validation_error(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}" for err in exc.errors()
    )


class WorkflowGraph:
    """Adjacency view of a workflow, with cycle detection and a topological order."""

    def __init__(self, workflow: WorkflowDefinition) -> None:
        self.workflow = workflow
        self.nodes: dict[str, NodeDefinition] = {n.id: n for n in workflow.nodes}
        self.incoming: dict[str, list[Connection]] = {nid: [] for nid in self.nodes}
        self.predecessors: dict[str, dict[str, None]] = {nid: {} for nid in self.nodes}
        self.successors: dict[str, dict[str, None]] = {nid: {} for nid in self.nodes}

        seen: set[tuple[str, str, str]] = set()
        for conn in workflow.connections:
            key = (conn.source, conn.target, conn.source_output)
            if key in seen:
                continue
            seen.add(key)
            self.incoming[conn.target].append(conn)
            self.predecessors[conn.target][conn.source] = None  # dicts as ordered sets
            self.successors[conn.source][conn.target] = None

        self.order = self._topological_order()
        self.roots = [nid for nid in self.order if not self.predecessors[nid]]
        self.ancestors: dict[str, set[str]] = {}
        for nid in self.order:
            acc: set[str] = set()
            for pred in self.predecessors[nid]:
                acc.add(pred)
                acc |= self.ancestors[pred]
            self.ancestors[nid] = acc

    def _topological_order(self) -> list[str]:
        indegree = {nid: len(preds) for nid, preds in self.predecessors.items()}
        queue = deque(nid for nid in self.nodes if indegree[nid] == 0)
        order: list[str] = []
        while queue:
            nid = queue.popleft()
            order.append(nid)
            for succ in self.successors[nid]:
                indegree[succ] -= 1
                if indegree[succ] == 0:
                    queue.append(succ)
        if len(order) != len(self.nodes):
            cyclic = [nid for nid in self.nodes if indegree[nid] > 0]
            raise WorkflowValidationError([f"workflow contains a cycle involving nodes: {cyclic}"])
        return order


# --------------------------------------------------------------------------- engine


class ExecutionHandle:
    """A running execution. ``await handle.result()`` or ``handle.cancel()``."""

    def __init__(
        self, execution_id: str, task: asyncio.Task[ExecutionResult], live: ExecutionResult | None = None
    ) -> None:
        self.execution_id = execution_id
        self._task = task
        self._live = live

    def snapshot(self) -> ExecutionResult | None:
        """Copy of the in-progress result (node statuses so far)."""
        return self._live.model_copy(deep=True) if self._live is not None else None

    def cancel(self) -> None:
        self._task.cancel()

    def done(self) -> bool:
        return self._task.done()

    async def result(self) -> ExecutionResult:
        return await asyncio.shield(self._task)


class WorkflowEngine:
    def __init__(
        self,
        registry: NodeRegistry | None = None,
        credentials: CredentialProvider | None = None,
        event_bus: EventBus | None = None,
        services: Mapping[str, Any] | None = None,
    ) -> None:
        self.registry = registry or default_registry
        self.credentials: CredentialProvider = credentials or InMemoryCredentialProvider()
        self.events = event_bus or EventBus()
        self.services = dict(services or {})
        self._active: dict[str, ExecutionHandle] = {}

    # ---- validation

    def parse(self, workflow: WorkflowDefinition | Mapping[str, Any] | str) -> WorkflowDefinition:
        if isinstance(workflow, WorkflowDefinition):
            return workflow
        try:
            if isinstance(workflow, str):
                return WorkflowDefinition.model_validate_json(workflow)
            return WorkflowDefinition.model_validate(workflow)
        except ValidationError as exc:
            raise WorkflowValidationError([_format_validation_error(exc)]) from None

    def validate(self, workflow: WorkflowDefinition | Mapping[str, Any] | str) -> WorkflowGraph:
        """Check structure, node types, credential slots, output ports and static params."""
        wf = self.parse(workflow)
        errors: list[str] = []
        graph: WorkflowGraph | None = None
        try:
            graph = WorkflowGraph(wf)
        except WorkflowValidationError as exc:
            errors.extend(exc.errors)

        for node in wf.nodes:
            if node.type not in self.registry:
                errors.append(f"node '{node.id}': unknown type '{node.type}'")
                continue
            cls = self.registry.get(node.type)
            if unknown := set(node.credentials) - set(cls.credential_slots):
                errors.append(f"node '{node.id}': unknown credential slot(s) {sorted(unknown)}")
            if cls.is_trigger and any(c.target == node.id for c in wf.connections):
                errors.append(f"node '{node.id}': trigger nodes cannot have incoming connections")
            checkable = {k: v for k, v in node.parameters.items() if k not in cls.raw_parameters}
            if not contains_expression(checkable):  # otherwise only checkable at run time
                try:
                    cls.Parameters.model_validate(node.parameters)
                except ValidationError as exc:
                    errors.append(f"node '{node.id}': invalid parameters: {_format_validation_error(exc)}")

        for conn in wf.connections:
            src = wf.node(conn.source)
            if src.type in self.registry:
                valid = set(self.registry.get(src.type).outputs) | {ERROR_OUTPUT}
                if conn.source_output not in valid:
                    errors.append(
                        f"connection {conn.source}->{conn.target}: node '{conn.source}' has no "
                        f"output '{conn.source_output}' (has {sorted(valid)})"
                    )

        if errors:
            raise WorkflowValidationError(errors)
        assert graph is not None
        return graph

    # ---- running

    def start(
        self,
        workflow: WorkflowDefinition | Mapping[str, Any] | str,
        *,
        trigger_data: Any = None,
        start_node: str | None = None,
        execution_id: str | None = None,
    ) -> ExecutionHandle:
        """Validate and launch a workflow in the background. Must be called inside a running loop."""
        graph = self.validate(workflow)
        if start_node is not None and start_node not in graph.roots:
            raise WorkflowValidationError([f"start node '{start_node}' is not a root node"])
        run = _ExecutionRun(self, graph, trigger_data, start_node, execution_id or new_id())
        task = asyncio.create_task(run.execute(), name=f"workflow:{graph.workflow.name}:{run.execution_id}")
        handle = ExecutionHandle(run.execution_id, task, run.result)
        self._active[run.execution_id] = handle
        task.add_done_callback(lambda _t: self._active.pop(run.execution_id, None))
        return handle

    async def run(
        self,
        workflow: WorkflowDefinition | Mapping[str, Any] | str,
        *,
        trigger_data: Any = None,
        start_node: str | None = None,
        execution_id: str | None = None,
    ) -> ExecutionResult:
        """Run a workflow to completion and return its result (never raises for node failures)."""
        handle = self.start(workflow, trigger_data=trigger_data, start_node=start_node, execution_id=execution_id)
        try:
            return await handle.result()
        except asyncio.CancelledError:
            handle.cancel()
            await asyncio.wait([handle._task])
            raise

    def cancel(self, execution_id: str) -> bool:
        handle = self._active.get(execution_id)
        if handle is None:
            return False
        handle.cancel()
        return True

    @property
    def active_executions(self) -> list[str]:
        return list(self._active)

    def handle(self, execution_id: str) -> ExecutionHandle | None:
        return self._active.get(execution_id)


# --------------------------------------------------------------------------- one execution


class _ExecutionRun:
    def __init__(
        self,
        engine: WorkflowEngine,
        graph: WorkflowGraph,
        trigger_data: Any,
        start_node: str | None,
        execution_id: str,
    ) -> None:
        self.engine = engine
        self.graph = graph
        self.wf = graph.workflow
        self.start_node = start_node
        self.execution_id = execution_id
        self.trigger_data = to_jsonable(trigger_data)
        self.result = ExecutionResult(
            execution_id=execution_id,
            workflow_id=self.wf.id,
            workflow_name=self.wf.name,
            trigger_data=self.trigger_data,
            nodes={
                n.id: NodeRunRecord(node_id=n.id, node_type=n.type, node_name=n.label)
                for n in self.wf.nodes
            },
        )
        self.records = self.result.nodes
        self._semaphore = asyncio.Semaphore(self.wf.settings.max_concurrency)
        self._events: asyncio.Queue[ExecutionEvent | None] = asyncio.Queue()
        self._secrets: set[str] = set()
        self._first_failure: str | None = None

    # ---- events / logging / secrets

    def _emit(self, type_: EventType, node_id: str | None = None, **payload: Any) -> None:
        self._events.put_nowait(
            ExecutionEvent(
                type=type_,
                execution_id=self.execution_id,
                workflow_id=self.wf.id,
                node_id=node_id,
                payload=payload,
            )
        )

    async def _dispatch_events(self) -> None:
        while (event := await self._events.get()) is not None:
            await self.engine.events.emit(event)

    def _redact(self, text: str) -> str:
        for secret in sorted(self._secrets, key=len, reverse=True):
            text = text.replace(secret, "***")
        return text

    def _remember_secrets(self, value: Any) -> None:
        if isinstance(value, str) and len(value) >= _MIN_SECRET_LEN:
            self._secrets.add(value)
        elif isinstance(value, Mapping):
            for v in value.values():
                self._remember_secrets(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                self._remember_secrets(v)

    def _log(self, node_id: str, level: str, message: str) -> None:
        message = self._redact(message)
        self.records[node_id].logs.append(LogEntry(level=level, message=message))
        self._emit(EventType.NODE_LOG, node_id, level=level, message=message)
        logger.log(_LOG_LEVELS.get(level, logging.INFO), "[%s/%s] %s", self.wf.name, node_id, message)

    async def _get_credential(self, node: NodeDefinition, slot: str) -> dict[str, Any]:
        name = node.credentials.get(slot)
        if not name:
            raise CredentialNotFoundError(f"node '{node.id}' has no credential assigned to slot '{slot}'")
        data = await self.engine.credentials.get_credential(name)
        self._remember_secrets(data)
        return data

    # ---- top level

    async def execute(self) -> ExecutionResult:
        dispatcher = asyncio.create_task(self._dispatch_events())
        self._emit(EventType.EXECUTION_STARTED, workflow_name=self.wf.name, trigger_data=self.trigger_data)
        status, error = ExecutionStatus.SUCCESS, None
        timeout = self.wf.settings.timeout_seconds
        try:
            async with asyncio.timeout(timeout):
                await self._schedule()
        except TimeoutError:
            status, error = ExecutionStatus.FAILED, f"workflow timed out after {timeout}s"
        except asyncio.CancelledError:
            if (task := asyncio.current_task()) is not None:
                task.uncancel()
            status, error = ExecutionStatus.CANCELLED, "execution was cancelled"
        except Exception as exc:  # a bug in the engine itself, not in a node
            logger.exception("engine failure in execution %s", self.execution_id)
            status, error = ExecutionStatus.FAILED, f"internal engine error: {exc!r}"
        else:
            if self._first_failure:
                status, error = ExecutionStatus.FAILED, self._first_failure

        now = utcnow()
        for record in self.records.values():
            if record.status in (NodeStatus.PENDING, NodeStatus.RUNNING):
                record.status = NodeStatus.CANCELLED
                record.finished_at = record.finished_at or now
        self.result.status, self.result.error, self.result.finished_at = status, error, now
        self._emit(
            EventType.EXECUTION_FINISHED,
            status=status.value,
            error=error,
            duration_ms=(now - self.result.started_at).total_seconds() * 1000,
        )
        self._events.put_nowait(None)
        await dispatcher
        return self.result

    async def _schedule(self) -> None:
        remaining = {nid: len(preds) for nid, preds in self.graph.predecessors.items()}
        resolved: deque[str] = deque(self.graph.roots)  # all predecessors finished
        running: dict[asyncio.Task[None], str] = {}

        def release(node_id: str) -> None:
            for succ in self.graph.successors[node_id]:
                remaining[succ] -= 1
                if remaining[succ] == 0:
                    resolved.append(succ)

        try:
            while True:
                while resolved:
                    nid = resolved.popleft()
                    if (reason := self._skip_reason(nid)) is not None:
                        self._mark_skipped(nid, reason)
                        release(nid)
                    else:
                        running[asyncio.create_task(self._run_node(nid), name=f"node:{nid}")] = nid
                if not running:
                    return
                done, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    nid = running.pop(task)
                    task.result()  # re-raise engine bugs; node errors are captured in the record
                    record = self.records[nid]
                    if record.status is NodeStatus.FAILED and not record.error_handled:
                        if self._first_failure is None:
                            msg = record.error.message if record.error else "unknown error"
                            self._first_failure = f"node '{record.node_name}' failed: {msg}"
                        if self.wf.settings.fail_fast:
                            return
                    release(nid)
        finally:
            for task in running:
                task.cancel()
            if running:
                await asyncio.gather(*running, return_exceptions=True)

    # ---- per node

    def _skip_reason(self, node_id: str) -> str | None:
        if not self.graph.predecessors[node_id]:
            if self.start_node is not None and node_id != self.start_node:
                return "not the trigger that started this execution"
            return None
        for conn in self.graph.incoming[node_id]:
            if conn.source_output in self.records[conn.source].active_outputs:
                return None
        return "no active input (upstream branch not taken, skipped, or failed)"

    def _mark_skipped(self, node_id: str, reason: str) -> None:
        record = self.records[node_id]
        record.status, record.message, record.finished_at = NodeStatus.SKIPPED, reason, utcnow()
        self._emit(EventType.NODE_SKIPPED, node_id, reason=reason)

    def _collect_inputs(self, node_id: str) -> tuple[Any, dict[str, Any]]:
        if not self.graph.predecessors[node_id]:
            return self.trigger_data, {}
        inputs: dict[str, Any] = {}
        for conn in self.graph.incoming[node_id]:
            src = self.records[conn.source]
            if conn.source_output in src.active_outputs and conn.source not in inputs:
                inputs[conn.source] = src.output
        primary = next(iter(inputs.values())) if len(inputs) == 1 else inputs
        return primary, inputs

    def _scope(self, node: NodeDefinition, primary: Any, inputs: dict[str, Any]) -> dict[str, Any]:
        upstream = {
            nid: self.records[nid].output
            for nid in self.graph.ancestors[node.id]
            if self.records[nid].active_outputs
        }
        return {
            "input": primary,
            "inputs": inputs,
            "nodes": upstream,
            "trigger": self.trigger_data,
            "vars": self.wf.variables,
            "execution": {"id": self.execution_id, "workflow_id": self.wf.id, "workflow_name": self.wf.name},
            "node": {"id": node.id, "name": node.label},
        }

    async def _run_node(self, node_id: str) -> None:
        node = self.graph.nodes[node_id]
        record = self.records[node_id]
        primary, inputs = self._collect_inputs(node_id)

        if node.disabled:
            record.status, record.output = NodeStatus.SKIPPED, primary
            record.active_outputs = [DEFAULT_OUTPUT]
            record.message, record.finished_at = "disabled: input passed through", utcnow()
            self._emit(EventType.NODE_SKIPPED, node_id, reason=record.message)
            return

        try:
            async with self._semaphore:
                record.status, record.started_at = NodeStatus.RUNNING, utcnow()
                self._emit(EventType.NODE_STARTED, node_id, node_type=node.type)
                try:
                    outcome = await self._invoke(node, record, primary, inputs)
                except Exception as exc:
                    self._handle_failure(node, record, exc, primary)
                else:
                    record.status, record.output = NodeStatus.SUCCESS, outcome.data
                    record.active_outputs = list(outcome.outputs)
                    record.finished_at = utcnow()
                    self._emit(
                        EventType.NODE_SUCCEEDED,
                        node_id,
                        outputs=record.active_outputs,
                        output=record.output,
                        attempts=record.attempts,
                        duration_ms=record.duration_ms,
                    )
        except asyncio.CancelledError:
            record.status, record.finished_at = NodeStatus.CANCELLED, utcnow()
            self._emit(EventType.NODE_CANCELLED, node_id)
            raise

    async def _invoke(
        self, node: NodeDefinition, record: NodeRunRecord, primary: Any, inputs: dict[str, Any]
    ) -> NodeResult:
        cls: type[BaseNode] = self.engine.registry.get(node.type)
        rendered = render_parameters(node.parameters, self._scope(node, primary, inputs), cls.raw_parameters)
        try:
            params = cls.Parameters.model_validate(rendered)
        except ValidationError as exc:
            raise NonRetryableError(f"invalid parameters: {_format_validation_error(exc)}") from None

        ctx = NodeContext(
            node=node,
            execution_id=self.execution_id,
            workflow_id=self.wf.id,
            input=primary,
            inputs=inputs,
            trigger_data=self.trigger_data,
            variables=self.wf.variables,
            services=self.engine.services,
            credential_getter=lambda slot: self._get_credential(node, slot),
            log_fn=lambda level, msg: self._log(node.id, level, msg),
        )
        policy = node.retry
        for attempt in range(1, policy.max_attempts + 1):
            record.attempts = ctx.attempt = attempt
            try:
                coro = cls(node).execute(ctx, params)
                raw = await asyncio.wait_for(coro, node.timeout_seconds) if node.timeout_seconds else await coro
                outcome = NodeResult.coerce(raw)
                if bad := set(outcome.outputs) - set(cls.outputs):
                    raise NonRetryableError(f"node returned undeclared output(s) {sorted(bad)}")
                return outcome
            except NonRetryableError:
                raise
            except TimeoutError:
                exc: Exception = NodeTimeoutError(f"timed out after {node.timeout_seconds}s")
            except Exception as e:
                exc = e
            if attempt >= policy.max_attempts:
                raise exc
            delay = policy.delay_for(attempt)
            self._emit(
                EventType.NODE_RETRY,
                node.id,
                attempt=attempt,
                next_attempt_in_s=delay,
                error=self._redact(str(exc) or type(exc).__name__),
            )
            await asyncio.sleep(delay)
        raise NodeExecutionError("retry loop exited unexpectedly")  # unreachable

    def _handle_failure(self, node: NodeDefinition, record: NodeRunRecord, exc: Exception, primary: Any) -> None:
        message = self._redact(str(exc) or type(exc).__name__)
        record.error = NodeError(
            type=type(exc).__name__,
            message=message,
            traceback=self._redact("".join(traceback.format_exception(exc))),
        )
        record.status, record.finished_at = NodeStatus.FAILED, utcnow()
        if node.on_error is not OnError.STOP:
            record.error_handled = True
            record.output = {"error": {"type": record.error.type, "message": message}, "input": primary}
            record.active_outputs = [DEFAULT_OUTPUT if node.on_error is OnError.CONTINUE else ERROR_OUTPUT]
        self._emit(
            EventType.NODE_FAILED,
            node.id,
            error=message,
            error_type=record.error.type,
            attempts=record.attempts,
            handled=record.error_handled,
        )
