"""Flow-control and data-shaping nodes: Set, If, Wait."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..errors import NonRetryableError
from .base import BaseNode, NodeContext, NodeResult
from .registry import register_node


@register_node
class SetNode(BaseNode):
    type = "logic.set"
    display_name = "Set Fields"
    category = "logic"
    description = "Build an object from fixed values and {{ expressions }}."

    class Parameters(BaseModel):
        model_config = ConfigDict(extra="forbid")
        values: dict[str, Any] = Field(default_factory=dict)
        include_input: bool = False

    async def execute(self, ctx: NodeContext, params: Parameters) -> Any:
        result: dict[str, Any] = {}
        if params.include_input and isinstance(ctx.input, dict):
            result.update(ctx.input)
        result.update(params.values)
        return result


Operator = Literal[
    "equals", "not_equals",
    "greater_than", "greater_or_equal", "less_than", "less_or_equal",
    "contains", "not_contains", "starts_with", "ends_with", "matches_regex",
    "is_empty", "is_not_empty", "is_true", "is_false",
]


def _as_number(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    return value


def evaluate_condition(op: str, left: Any, right: Any) -> bool:
    if op in ("greater_than", "greater_or_equal", "less_than", "less_or_equal"):
        a, b = _as_number(left), _as_number(right)
        try:
            return {
                "greater_than": a > b,
                "greater_or_equal": a >= b,
                "less_than": a < b,
                "less_or_equal": a <= b,
            }[op]
        except TypeError:
            raise NonRetryableError(f"cannot compare {left!r} and {right!r} with '{op}'") from None
    if op == "equals":
        return left == right or _as_number(left) == _as_number(right)
    if op == "not_equals":
        return not evaluate_condition("equals", left, right)
    if op in ("contains", "not_contains"):
        found = right in left if isinstance(left, (list, dict)) else str(right) in str(left)
        return found if op == "contains" else not found
    if op == "starts_with":
        return str(left).startswith(str(right))
    if op == "ends_with":
        return str(left).endswith(str(right))
    if op == "matches_regex":
        try:
            return re.search(str(right), str(left)) is not None
        except re.error as exc:
            raise NonRetryableError(f"invalid regex {right!r}: {exc}") from None
    if op in ("is_empty", "is_not_empty"):
        empty = left is None or left == "" or (hasattr(left, "__len__") and len(left) == 0)
        return empty if op == "is_empty" else not empty
    if op == "is_true":
        return left is True or str(left).lower() in ("true", "1", "yes")
    if op == "is_false":
        return not evaluate_condition("is_true", left, right)
    raise NonRetryableError(f"unknown operator '{op}'")


@register_node
class IfNode(BaseNode):
    type = "logic.if"
    display_name = "If"
    category = "logic"
    description = "Route the input to the 'true' or 'false' output."
    outputs = ("true", "false")

    class Parameters(BaseModel):
        model_config = ConfigDict(extra="forbid")
        left: Any = None
        operator: Operator = "equals"
        right: Any = None

    async def execute(self, ctx: NodeContext, params: Parameters) -> NodeResult:
        passed = evaluate_condition(params.operator, params.left, params.right)
        ctx.debug(f"{params.left!r} {params.operator} {params.right!r} -> {passed}")
        return NodeResult(data=ctx.input, outputs=["true" if passed else "false"])


@register_node
class WaitNode(BaseNode):
    type = "logic.wait"
    display_name = "Wait"
    category = "logic"
    description = "Pause, then pass the input through unchanged."

    class Parameters(BaseModel):
        model_config = ConfigDict(extra="forbid")
        seconds: float = Field(default=1.0, ge=0, le=86_400)

    async def execute(self, ctx: NodeContext, params: Parameters) -> Any:
        await asyncio.sleep(params.seconds)
        return ctx.input
