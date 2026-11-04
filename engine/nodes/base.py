"""Base class every node type derives from, plus the runtime context handed to nodes."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from ..models import DEFAULT_OUTPUT, NodeDefinition, to_jsonable

NodeCategory = Literal["trigger", "ai", "code", "action", "logic"]
LogLevel = Literal["debug", "info", "warning", "error"]


class EmptyParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(slots=True)
class NodeResult:
    """Return this from ``execute`` to choose which output port(s) fire.

    Returning any other value is shorthand for ``NodeResult(data=value)`` on "main".
    """

    data: Any = None
    outputs: Sequence[str] = field(default=(DEFAULT_OUTPUT,))

    @classmethod
    def coerce(cls, value: Any) -> NodeResult:
        if isinstance(value, NodeResult):
            return cls(to_jsonable(value.data), tuple(value.outputs))
        return cls(to_jsonable(value))


class NodeContext:
    """Everything a node may touch at runtime. Built by the engine, one per node run."""

    def __init__(
        self,
        *,
        node: NodeDefinition,
        execution_id: str,
        workflow_id: str,
        input: Any,
        inputs: dict[str, Any],
        trigger_data: Any,
        variables: dict[str, Any],
        services: dict[str, Any],
        credential_getter: Callable[[str], Awaitable[dict[str, Any]]],
        log_fn: Callable[[LogLevel, str], None],
    ) -> None:
        self.node = node
        self.execution_id = execution_id
        self.workflow_id = workflow_id
        self.input = input  # single upstream output, trigger data for roots, dict if merging
        self.inputs = inputs  # upstream node id -> output, for active connections only
        self.trigger_data = trigger_data
        self.variables = variables
        self.services = services  # shared clients (http, llm providers...) injected into the engine
        self.attempt = 1
        self._credential_getter = credential_getter
        self._log_fn = log_fn

    async def get_credential(self, slot: str = "default") -> dict[str, Any]:
        """Decrypted credential assigned to ``slot``. Its values are redacted from logs."""
        return await self._credential_getter(slot)

    def log(self, message: Any, level: LogLevel = "info") -> None:
        self._log_fn(level, str(message))

    def debug(self, message: Any) -> None:
        self.log(message, "debug")

    def info(self, message: Any) -> None:
        self.log(message, "info")

    def warning(self, message: Any) -> None:
        self.log(message, "warning")

    def error(self, message: Any) -> None:
        self.log(message, "error")

    async def run_blocking(self, func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        """Run sync/blocking code (PyAutoGUI, smtplib, file IO) without stalling the event loop.

        Blocking calls made directly inside ``execute`` freeze every parallel branch and
        defeat node timeouts, so always route them through here.
        """
        return await asyncio.to_thread(func, *args, **kwargs)


class BaseNode(ABC):
    """Subclass, set the class attributes, implement ``execute``, decorate with ``@register_node``."""

    type: ClassVar[str]  # unique id, e.g. "action.http_request"
    display_name: ClassVar[str]
    category: ClassVar[NodeCategory]
    description: ClassVar[str] = ""
    version: ClassVar[int] = 1
    is_trigger: ClassVar[bool] = False

    Parameters: ClassVar[type[BaseModel]] = EmptyParameters
    # slot name -> human description of the expected credential, e.g. {"default": "OpenAI API key"}
    credential_slots: ClassVar[dict[str, str]] = {}
    outputs: ClassVar[tuple[str, ...]] = (DEFAULT_OUTPUT,)
    # parameters excluded from {{ }} rendering (e.g. source code)
    raw_parameters: ClassVar[frozenset[str]] = frozenset()

    def __init__(self, definition: NodeDefinition) -> None:
        self.definition = definition

    @abstractmethod
    async def execute(self, ctx: NodeContext, params: Any) -> Any:
        """Do the work. ``params`` is an instance of ``self.Parameters`` with expressions resolved.

        Raise ``NodeExecutionError`` (retryable) or ``NonRetryableError`` on failure.
        """

    @classmethod
    def describe(cls) -> dict[str, Any]:
        """Metadata the GUI uses to render the node palette and parameter forms."""
        return {
            "type": cls.type,
            "display_name": cls.display_name,
            "category": cls.category,
            "description": cls.description,
            "version": cls.version,
            "is_trigger": cls.is_trigger,
            "outputs": list(cls.outputs),
            "credential_slots": dict(cls.credential_slots),
            "parameters_schema": cls.Parameters.model_json_schema(),
        }
