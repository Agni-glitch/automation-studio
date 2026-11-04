"""HTTP Request node: call any REST API, with credential-based auth."""

from __future__ import annotations

import time
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..errors import NodeExecutionError, NonRetryableError
from ._http import http_client
from .base import BaseNode, NodeContext
from .registry import register_node


@register_node
class ApiRequestNode(BaseNode):
    type = "action.http_request"
    display_name = "HTTP Request"
    category = "action"
    description = "Call a REST API. Output: {status, headers, data}."
    credential_slots = {
        "default": "bearer: {token}; api_key_header/api_key_query: {api_key}; basic: {username, password}",
    }

    class Parameters(BaseModel):
        model_config = ConfigDict(extra="forbid")
        method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"] = "GET"
        url: str = Field(pattern=r"^https?://")
        query: dict[str, Any] = Field(default_factory=dict)
        headers: dict[str, str] = Field(default_factory=dict)
        json_body: Any = None
        body: str | None = None
        auth: Literal["none", "bearer", "api_key_header", "api_key_query", "basic"] = "none"
        auth_key_name: str = "X-API-Key"  # header / query parameter name for api_key_* modes
        response_format: Literal["auto", "json", "text"] = "auto"
        timeout: float = Field(default=30, gt=0, le=600)
        fail_on_error_status: bool = True
        follow_redirects: bool = True

        @model_validator(mode="after")
        def _one_body(self) -> ApiRequestNode.Parameters:
            if self.json_body is not None and self.body is not None:
                raise ValueError("set either json_body or body, not both")
            return self

    async def execute(self, ctx: NodeContext, params: Parameters) -> dict[str, Any]:
        headers = dict(params.headers)
        query = {k: _query_value(v) for k, v in params.query.items() if v is not None}
        auth: httpx.BasicAuth | None = None

        if params.auth != "none":
            cred = await ctx.get_credential()
            if params.auth == "bearer":
                headers["Authorization"] = f"Bearer {_field(cred, 'token', 'api_key')}"
            elif params.auth == "api_key_header":
                headers[params.auth_key_name] = _field(cred, "api_key", "token")
            elif params.auth == "api_key_query":
                query[params.auth_key_name] = _field(cred, "api_key", "token")
            else:
                auth = httpx.BasicAuth(_field(cred, "username"), _field(cred, "password"))

        started = time.perf_counter()
        async with http_client(ctx) as client:
            try:
                resp = await client.request(
                    params.method,
                    params.url,
                    params=query,
                    headers=headers,
                    json=params.json_body,
                    content=params.body,
                    auth=auth or httpx.USE_CLIENT_DEFAULT,
                    timeout=params.timeout,
                    follow_redirects=params.follow_redirects,
                )
            except httpx.TransportError as exc:
                raise NodeExecutionError(f"{params.method} {params.url} failed: {exc!r}") from exc

        elapsed_ms = (time.perf_counter() - started) * 1000
        ctx.info(f"{params.method} {resp.request.url} -> {resp.status_code} ({elapsed_ms:.0f} ms)")
        if resp.status_code >= 400 and params.fail_on_error_status:
            retryable = resp.status_code in (408, 425, 429) or resp.status_code >= 500
            err = NodeExecutionError if retryable else NonRetryableError
            raise err(f"HTTP {resp.status_code} from {params.url}: {resp.text[:300]}")

        return {
            "status": resp.status_code,
            "headers": dict(resp.headers),
            "data": _decode(resp, params.response_format),
        }


def _field(cred: dict[str, Any], *names: str) -> str:
    for name in names:
        if cred.get(name):
            return str(cred[name])
    raise NonRetryableError(f"credential is missing field '{names[0]}'")


def _query_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _decode(resp: httpx.Response, fmt: str) -> Any:
    if fmt == "text" or not resp.content:
        return resp.text
    is_json = "json" in resp.headers.get("content-type", "")
    if fmt == "json" or is_json:
        try:
            return resp.json()
        except ValueError:
            if fmt == "json":
                raise NonRetryableError("response is not valid JSON") from None
    return resp.text
