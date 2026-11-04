"""OpenAI Chat Completions API. Also works with OpenAI-compatible servers via ``base_url``
(LM Studio, vLLM, OpenRouter, ...)."""

from __future__ import annotations

from .base import LLMProvider, LLMRequest, LLMResponse, LLMUsage, parse_json_text

_OFFICIAL = "https://api.openai.com"


class OpenAIProvider(LLMProvider):
    name = "openai"
    default_base_url = _OFFICIAL

    async def complete(self, request: LLMRequest) -> LLMResponse:
        messages = [{"role": "system", "content": request.system}] if request.system else []
        messages += [m.model_dump() for m in request.messages]
        body: dict = {"model": request.model, "messages": messages}
        # The official API's newer models only accept max_completion_tokens; compatible servers
        # generally only know max_tokens.
        body["max_completion_tokens" if self.base_url == _OFFICIAL else "max_tokens"] = request.max_tokens
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.json_schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": request.json_schema, "strict": False},
            }

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = await self._post("/v1/chat/completions", body, headers)
        choice = (payload.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        usage = payload.get("usage", {})
        return LLMResponse(
            text=text,
            data=parse_json_text(text) if request.json_schema else None,
            model=payload.get("model", request.model),
            stop_reason=choice.get("finish_reason"),
            usage=LLMUsage(input_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens")),
        )
