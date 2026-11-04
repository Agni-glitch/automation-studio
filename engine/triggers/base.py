"""Base class for trigger listeners (the long-running side of trigger nodes)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from ..errors import EngineError
from ..models import NodeDefinition, WorkflowDefinition

if TYPE_CHECKING:
    from ..core import ExecutionHandle
    from .manager import TriggerManager


class TriggerError(EngineError):
    """A trigger could not be activated (folder missing, port/path conflict, bad credential...)."""


class TriggerListener(ABC):
    def __init__(
        self, manager: TriggerManager, workflow: WorkflowDefinition, node: NodeDefinition, params: Any
    ) -> None:
        self.manager = manager
        self.workflow = workflow
        self.node = node
        self.params = params

    @abstractmethod
    async def start(self) -> None:
        """Begin listening. Raise ``TriggerError`` if that is impossible."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop listening. Must be safe to call more than once."""

    @abstractmethod
    def describe(self) -> str: ...

    def fire(self, data: Any) -> ExecutionHandle:
        return self.manager.fire(self.workflow.id, self.node.id, data)
