"""Anthropic Messages API. Structured output uses a forced tool call."""

from __future__ import annotations

import json

from ..errors import NodeExecutionError
from .base import LLMProvider, LLMRequest, LLMResponse, LLMUsage

_RESULT_TOOL = "submit_result"


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    default_base_url = "https://api.anthropic.com"

    async def complete(self, request: LLMRequest) -> LLMResponse:
        body: dict = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "messages": [m.model_dump() for m in request.messages],
        }
        if request.system:
            body["system"] = request.system
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.json_schema:
            body["tools"] = [{
                "name": _RESULT_TOOL,
                "description": "Submit the final structured result.",
                "input_schema": request.json_schema,
            }]
            body["tool_choice"] = {"type": "tool", "name": _RESULT_TOOL}

        payload = await self._post(
            "/v1/messages",
            body,
            {"x-api-key": self.api_key or "", "anthropic-version": "2023-06-01"},
        )
        blocks = payload.get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        data = None
        if request.json_schema:
            tool = next((b for b in blocks if b.get("type") == "tool_use"), None)
            if tool is None:
                raise NodeExecutionError("anthropic: model did not return the structured result")
            data = tool.get("input")
            text = text or json.dumps(data, ensure_ascii=False)
        usage = payload.get("usage", {})
        return LLMResponse(
            text=text,
            data=data,
            model=payload.get("model", request.model),
            stop_reason=payload.get("stop_reason"),
            usage=LLMUsage(input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens")),
        )
