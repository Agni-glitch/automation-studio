"""Provider-neutral LLM interface used by the AI Agent node."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Literal

import httpx
from pydantic import BaseModel, Field

from ..errors import NodeExecutionError, NonRetryableError


class LLMMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class LLMRequest(BaseModel):
    model: str
    messages: list[LLMMessage]
    system: str | None = None
    temperature: float | None = None
    max_tokens: int = 2048
    # When set, the provider is asked for JSON matching this (object) schema.
    json_schema: dict[str, Any] | None = None


class LLMUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMResponse(BaseModel):
    text: str
    data: Any = None  # parsed JSON when json_schema was requested
    model: str
    stop_reason: str | None = None
    usage: LLMUsage = Field(default_factory=LLMUsage)


class LLMProvider(ABC):
    name: ClassVar[str]
    default_base_url: ClassVar[str]
    requires_api_key: ClassVar[bool] = True

    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 120,
    ) -> None:
        if self.requires_api_key and not api_key:
            raise NonRetryableError(f"{self.name} requires an API key credential")
        self.client = client
        self.api_key = api_key
        self.base_url = (base_url or self.default_base_url).rstrip("/")
        self.timeout = timeout

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse: ...

    async def _post(self, path: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        try:
            resp = await self.client.post(f"{self.base_url}{path}", json=body, headers=headers, timeout=self.timeout)
        except httpx.TransportError as exc:
            raise NodeExecutionError(f"{self.name}: cannot reach {self.base_url}: {exc!r}") from exc
        if resp.status_code >= 400:
            detail = resp.text[:500]
            retryable = resp.status_code in (408, 409, 429) or resp.status_code >= 500
            err = NodeExecutionError if retryable else NonRetryableError
            raise err(f"{self.name} API error {resp.status_code}: {detail}")
        try:
            return resp.json()
        except ValueError as exc:
            raise NodeExecutionError(f"{self.name}: response is not JSON") from exc


_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)


def parse_json_text(text: str) -> Any:
    """Parse model output as JSON, tolerating code fences and surrounding prose."""
    candidate = text.strip()
    if m := _FENCE.match(candidate):
        candidate = m.group(1)
    try:
        return json.loads(candidate)
    except ValueError:
        pass
    start, end = candidate.find("{"), candidate.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(candidate[start : end + 1])
        except ValueError:
            pass
    raise NodeExecutionError(f"model did not return valid JSON: {text[:200]!r}")


_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "null": (type(None),),
}


def schema_errors(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Small JSON-schema subset check (type, required, properties, items, enum, min/max)."""
    errors: list[str] = []
    expected = schema.get("type")
    if expected:
        names = expected if isinstance(expected, list) else [expected]
        ok = any(
            isinstance(value, _TYPES.get(n, object)) and not (n in ("integer", "number") and isinstance(value, bool))
            for n in names
        )
        if not ok:
            return [f"{path}: expected {expected}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: {value} > maximum {schema['maximum']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required '{key}'")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                errors.extend(schema_errors(value[key], sub, f"{path}.{key}"))
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(value):
            errors.extend(schema_errors(item, schema["items"], f"{path}[{i}]"))
    return errors
