"""Maps node type strings (as used in workflow JSON) to node classes."""

from __future__ import annotations

from typing import Any, TypeVar

from ..errors import UnknownNodeTypeError
from .base import BaseNode

N = TypeVar("N", bound=type[BaseNode])


class NodeRegistry:
    def __init__(self) -> None:
        self._types: dict[str, type[BaseNode]] = {}

    def register(self, cls: N | None = None, *, override: bool = False) -> Any:
        """Usable as ``@registry.register`` or ``@registry.register(override=True)``."""

        def decorator(node_cls: N) -> N:
            node_type = getattr(node_cls, "type", None)
            if not node_type:
                raise TypeError(f"{node_cls.__name__} must define a 'type' class attribute")
            for attr in ("display_name", "category"):
                if not getattr(node_cls, attr, None):
                    raise TypeError(f"{node_cls.__name__} must define '{attr}'")
            if node_type in self._types and not override:
                raise ValueError(f"node type '{node_type}' is already registered")
            self._types[node_type] = node_cls
            return node_cls

        return decorator(cls) if cls is not None else decorator

    def get(self, node_type: str) -> type[BaseNode]:
        try:
            return self._types[node_type]
        except KeyError:
            raise UnknownNodeTypeError(f"unknown node type '{node_type}'") from None

    def __contains__(self, node_type: object) -> bool:
        return node_type in self._types

    def types(self) -> list[str]:
        return sorted(self._types)

    def catalog(self) -> list[dict[str, Any]]:
        return [self._types[t].describe() for t in self.types()]

    def copy(self) -> NodeRegistry:
        clone = NodeRegistry()
        clone._types = dict(self._types)
        return clone


default_registry = NodeRegistry()
register_node = default_registry.register
