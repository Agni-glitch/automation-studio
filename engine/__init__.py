"""Local workflow automation engine."""

from .core import (
    CredentialProvider,
    ExecutionHandle,
    InMemoryCredentialProvider,
    WorkflowEngine,
    WorkflowGraph,
)
from .errors import (
    CredentialNotFoundError,
    EngineError,
    ExpressionError,
    NodeExecutionError,
    NodeTimeoutError,
    NonRetryableError,
    WorkflowValidationError,
)
from .events import EventBus, EventType, ExecutionEvent
from .models import (
    Connection,
    ExecutionResult,
    ExecutionStatus,
    NodeDefinition,
    NodeStatus,
    OnError,
    RetryPolicy,
    WorkflowDefinition,
    WorkflowSettings,
)
from .nodes import BaseNode, NodeContext, NodeRegistry, NodeResult, default_registry, register_node

__all__ = [name for name in dir() if not name.startswith("_")]
