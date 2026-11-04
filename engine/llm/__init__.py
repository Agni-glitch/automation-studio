"""LLM provider adapters."""

from __future__ import annotations

from ..errors import NonRetryableError
from .anthropic import AnthropicProvider
from .base import LLMMessage, LLMProvider, LLMRequest, LLMResponse, LLMUsage, parse_json_text, schema_errors
from .ollama import OllamaProvider
from .openai import OpenAIProvider

PROVIDERS: dict[str, type[LLMProvider]] = {
    p.name: p for p in (AnthropicProvider, OpenAIProvider, OllamaProvider)
}


def get_provider(name: str) -> type[LLMProvider]:
    try:
        return PROVIDERS[name]
    except KeyError:
        raise NonRetryableError(f"unknown LLM provider '{name}' (have {sorted(PROVIDERS)})") from None


__all__ = [
    "PROVIDERS",
    "AnthropicProvider",
    "LLMMessage",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "LLMUsage",
    "OllamaProvider",
    "OpenAIProvider",
    "get_provider",
    "parse_json_text",
    "schema_errors",
]
