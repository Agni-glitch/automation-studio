"""Shared HTTP client access for nodes.

If the engine was given ``services={"http_client": httpx.AsyncClient(...)}``, nodes reuse
it (connection pooling; tests and offline demos inject a mock transport here).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from .base import NodeContext


@asynccontextmanager
async def http_client(ctx: NodeContext) -> AsyncIterator[httpx.AsyncClient]:
    shared = ctx.services.get("http_client")
    if shared is not None:
        yield shared
        return
    async with httpx.AsyncClient() as client:
        yield client
