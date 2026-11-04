"""Local Ollama server (``/api/chat``). Structured output via the ``format`` schema field."""

from __future__ import annotations

from .base import LLMProvider, LLMRequest, LLMResponse, LLMUsage, parse_json_text


class OllamaProvider(LLMProvider):
    name = "ollama"
    default_base_url = "http://localhost:11434"
    requires_api_key = False

    async def complete(self, request: LLMRequest) -> LLMResponse:
        messages = [{"role": "system", "content": request.system}] if request.system else []
        messages += [m.model_dump() for m in request.messages]
        options: dict = {"num_predict": request.max_tokens}
        if request.temperature is not None:
            options["temperature"] = request.temperature
        body: dict = {"model": request.model, "messages": messages, "stream": False, "options": options}
        if request.json_schema:
            body["format"] = request.json_schema

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = await self._post("/api/chat", body, headers)
        text = (payload.get("message") or {}).get("content") or ""
        return LLMResponse(
            text=text,
            data=parse_json_text(text) if request.json_schema else None,
            model=payload.get("model", request.model),
            stop_reason=payload.get("done_reason"),
            usage=LLMUsage(input_tokens=payload.get("prompt_eval_count"), output_tokens=payload.get("eval_count")),
        )
