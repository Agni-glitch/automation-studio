"""AI Agent node: send a prompt (plus upstream data) to an LLM, optionally get validated JSON back."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..errors import NodeExecutionError, NonRetryableError
from ..llm import LLMMessage, LLMRequest, get_provider, schema_errors
from ._http import http_client
from .base import BaseNode, NodeContext
from .registry import register_node


@register_node
class AiAgentNode(BaseNode):
    type = "ai.agent"
    display_name = "AI Agent"
    category = "ai"
    description = (
        "Ask an LLM (Anthropic, OpenAI, Ollama) to analyse data. With output_schema the "
        "reply is validated JSON. Output: {result, text, model, usage}."
    )
    credential_slots = {"default": "{api_key} (optional for local Ollama)"}

    class Parameters(BaseModel):
        model_config = ConfigDict(extra="forbid")
        provider: Literal["anthropic", "openai", "ollama"] = "anthropic"
        model: str = Field(min_length=1)
        system_prompt: str | None = None
        prompt: str = Field(min_length=1)
        input_data: Any = None  # appended to the prompt as a JSON block
        output_schema: dict[str, Any] | None = None  # JSON schema with "type": "object"
        temperature: float | None = Field(default=None, ge=0, le=2)
        max_tokens: int = Field(default=2048, ge=1, le=64_000)
        base_url: str | None = None  # self-hosted / OpenAI-compatible endpoints
        request_timeout: float = Field(default=120, gt=0, le=1800)

        @field_validator("output_schema")
        @classmethod
        def _object_schema(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
            if v is not None and v.get("type") != "object":
                raise ValueError('output_schema must be a JSON schema with "type": "object"')
            return v

    async def execute(self, ctx: NodeContext, params: Parameters) -> dict[str, Any]:
        provider_cls = get_provider(params.provider)
        api_key = None
        if "default" in ctx.node.credentials:
            api_key = (await ctx.get_credential()).get("api_key")
        elif provider_cls.requires_api_key:
            raise NonRetryableError(f"assign a credential with an 'api_key' to use {params.provider}")

        system = params.system_prompt or ""
        if params.output_schema and params.provider != "anthropic":
            # Anthropic enforces the schema through a tool; others benefit from seeing it.
            system += "\n\nRespond only with JSON matching this schema:\n" + json.dumps(params.output_schema)

        request = LLMRequest(
            model=params.model,
            system=system.strip() or None,
            messages=[LLMMessage(role="user", content=_build_prompt(params.prompt, params.input_data))],
            temperature=params.temperature,
            max_tokens=params.max_tokens,
            json_schema=params.output_schema,
        )
        async with http_client(ctx) as client:
            provider = provider_cls(client, api_key, params.base_url, params.request_timeout)
            response = await provider.complete(request)

        ctx.info(
            f"{params.provider}/{response.model}: {response.usage.input_tokens} in, "
            f"{response.usage.output_tokens} out, stop={response.stop_reason}"
        )
        if params.output_schema:
            if errors := schema_errors(response.data, params.output_schema):
                # Retryable: a second sample often fixes it (configure node retry).
                raise NodeExecutionError("model output does not match output_schema: " + "; ".join(errors[:5]))
        return {
            "result": response.data if params.output_schema else response.text,
            "text": response.text,
            "model": response.model,
            "provider": params.provider,
            "usage": response.usage.model_dump(),
        }


def _build_prompt(prompt: str, data: Any) -> str:
    if data is None:
        return prompt
    rendered = data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False)
    return f"{prompt}\n\n<input>\n{rendered}\n</input>"
