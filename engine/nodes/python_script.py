"""Python Script node: run user code in a separate, resource-limited process."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..errors import NonRetryableError
from ..sandbox import run_python
from .base import BaseNode, NodeContext
from .registry import register_node

_HELP = """Available names: input (upstream output), inputs (by node id), args (the
'arguments' parameter), log(...) (same as print). Either define main(input) and return a
value, or assign `result = ...`. The return value must be JSON-serializable."""


@register_node
class PythonScriptNode(BaseNode):
    type = "code.python"
    display_name = "Python Script"
    category = "code"
    description = "Run custom Python in an isolated subprocess. " + _HELP
    raw_parameters = frozenset({"code"})  # never expand {{ }} inside source code

    class Parameters(BaseModel):
        model_config = ConfigDict(extra="forbid")
        code: str = Field(min_length=1)
        arguments: dict[str, Any] = Field(default_factory=dict)
        timeout_seconds: float = Field(default=30, gt=0, le=3600)
        memory_limit_mb: int = Field(default=512, ge=32, le=16_384)

    async def execute(self, ctx: NodeContext, params: Parameters) -> Any:
        outcome = await run_python(
            params.code,
            input=ctx.input,
            inputs=ctx.inputs,
            arguments=params.arguments,
            timeout=params.timeout_seconds,
            memory_limit_mb=params.memory_limit_mb,
            python_executable=ctx.services.get("python_executable"),
        )
        for line in outcome.logs:
            ctx.info(line)
        if not outcome.ok:
            err = outcome.error or {}
            tb = err.get("traceback", "").rstrip()
            raise NonRetryableError(
                f"{err.get('type', 'Error')}: {err.get('message', '')}" + (f"\n{tb}" if tb else "")
            )
        ctx.debug(f"script finished in {outcome.duration_ms:.0f} ms")
        return outcome.result
