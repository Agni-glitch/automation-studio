"""Pydantic models: workflow definitions (input) and execution records (output).

A workflow is stored and exchanged as JSON matching ``WorkflowDefinition``. Everything
the engine produces while running (``ExecutionResult``) is JSON-serializable so it can
be persisted to SQLite and streamed to the GUI unchanged.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

DEFAULT_OUTPUT = "main"
ERROR_OUTPUT = "error"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


_ANY_ADAPTER: TypeAdapter[Any] = TypeAdapter(Any)


def to_jsonable(value: Any) -> Any:
    """Convert node output (pydantic models, datetimes, sets, ...) into plain JSON data."""
    return _ANY_ADAPTER.dump_python(value, mode="json", fallback=repr)


# --------------------------------------------------------------------------- definition


class OnError(str, Enum):
    STOP = "stop"  # node fails -> workflow fails (default)
    CONTINUE = "continue"  # emit {"error": ...} on the "main" output and carry on
    ERROR_OUTPUT = "error_output"  # emit {"error": ...} on the "error" output only


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=1, ge=1, le=10)
    backoff_seconds: float = Field(default=1.0, ge=0)
    backoff_multiplier: float = Field(default=2.0, ge=1)

    def delay_for(self, failed_attempts: int) -> float:
        return self.backoff_seconds * self.backoff_multiplier ** (failed_attempts - 1)


class NodeDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    type: str
    name: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    # credential slot (declared by the node class) -> stored credential name
    credentials: dict[str, str] = Field(default_factory=dict)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    timeout_seconds: float | None = Field(default=300, gt=0)
    on_error: OnError = OnError.STOP
    disabled: bool = False
    # GUI-only metadata, ignored by the engine
    position: tuple[float, float] | None = None
    notes: str | None = None

    @property
    def label(self) -> str:
        return self.name or self.id


class Connection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    source_output: str = DEFAULT_OUTPUT


class WorkflowSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_concurrency: int = Field(default=4, ge=1, le=64)
    timeout_seconds: float | None = Field(default=None, gt=0)
    # True: first unhandled node failure cancels everything still running.
    # False: independent branches keep running; the execution is still marked failed.
    fail_fast: bool = True


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_id)
    name: str
    description: str = ""
    version: int = 1
    nodes: list[NodeDefinition]
    connections: list[Connection] = Field(default_factory=list)
    variables: dict[str, Any] = Field(default_factory=dict)
    settings: WorkflowSettings = Field(default_factory=WorkflowSettings)

    @model_validator(mode="after")
    def _check_references(self) -> WorkflowDefinition:
        seen: set[str] = set()
        dupes: set[str] = set()
        for node in self.nodes:
            (dupes if node.id in seen else seen).add(node.id)
        if dupes:
            raise ValueError(f"duplicate node ids: {sorted(dupes)}")
        for conn in self.connections:
            for end in (conn.source, conn.target):
                if end not in seen:
                    raise ValueError(f"connection references unknown node '{end}'")
            if conn.source == conn.target:
                raise ValueError(f"node '{conn.source}' is connected to itself")
        return self

    def node(self, node_id: str) -> NodeDefinition:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise KeyError(node_id)


# --------------------------------------------------------------------------- execution


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class ExecutionStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class LogEntry(BaseModel):
    timestamp: datetime = Field(default_factory=utcnow)
    level: str = "info"
    message: str


class NodeError(BaseModel):
    type: str
    message: str
    traceback: str | None = None


class NodeRunRecord(BaseModel):
    node_id: str
    node_type: str
    node_name: str
    status: NodeStatus = NodeStatus.PENDING
    attempts: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    output: Any = None
    # Output ports that fired. Downstream nodes run only if connected to an active port.
    active_outputs: list[str] = Field(default_factory=list)
    error: NodeError | None = None
    error_handled: bool = False
    message: str | None = None
    logs: list[LogEntry] = Field(default_factory=list)

    @property
    def duration_ms(self) -> float | None:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds() * 1000
        return None


class ExecutionResult(BaseModel):
    execution_id: str
    workflow_id: str
    workflow_name: str
    status: ExecutionStatus = ExecutionStatus.RUNNING
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    trigger_data: Any = None
    error: str | None = None
    nodes: dict[str, NodeRunRecord] = Field(default_factory=dict)

    def output_of(self, node_id: str) -> Any:
        return self.nodes[node_id].output
