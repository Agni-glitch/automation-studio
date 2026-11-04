"""Webhook trigger: one local HTTP server, routes ``/webhook/<path>`` to active workflows.

Binds to 127.0.0.1 by default, so only programs on this PC can call it. To receive
webhooks from the internet, put a tunnel (Cloudflare Tunnel, ngrok, Tailscale Funnel) in
front and set ``auth: header`` with a token credential.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import socket
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..models import NodeStatus
from .base import TriggerError, TriggerListener

if TYPE_CHECKING:
    from .manager import TriggerManager

logger = logging.getLogger(__name__)
_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
_DROP_HEADERS = {"authorization", "cookie", "proxy-authorization"}


class _QuietServer(uvicorn.Server):
    """uvicorn without its own signal handling: Ctrl+C belongs to the host application."""

    @contextlib.contextmanager
    def capture_signals(self):  # uvicorn >= 0.29
        yield

    def install_signal_handlers(self) -> None:  # older uvicorn
        pass


async def start_uvicorn(app: Any, host: str, port: int, name: str) -> tuple[uvicorn.Server, asyncio.Task[None], int]:
    """Start an ASGI app in the current event loop. Bind errors raise ``TriggerError``
    (instead of uvicorn's sys.exit). Returns (server, task, actual_port)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
    except OSError as exc:
        sock.close()
        raise TriggerError(f"cannot listen on {host}:{port}: {exc.strerror or exc}") from None
    actual_port = sock.getsockname()[1]
    # log_config=None: the host app owns logging. uvicorn's default config probes
    # sys.stdout.isatty(), which crashes under pythonw / a windowed .exe (stdout is None).
    config = uvicorn.Config(app, log_level="warning", access_log=False, lifespan="off",
                            ws="websockets-sansio", log_config=None)
    server = _QuietServer(config)
    task = asyncio.create_task(server.serve(sockets=[sock]), name=name)
    while not server.started:
        if task.done():
            task.result()
            raise TriggerError(f"{name} stopped during startup")
        await asyncio.sleep(0.02)
    return server, task, actual_port


async def stop_uvicorn(server: uvicorn.Server, task: asyncio.Task[None], timeout: float = 5) -> None:
    server.should_exit = True
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout)
    except TimeoutError:
        task.cancel()


def is_tunneled(request: Request) -> bool:
    """True for requests relayed by Cloudflare Tunnel (i.e. coming from the internet)."""
    return "cf-connecting-ip" in request.headers or "cf-ray" in request.headers


class WebhookServer:
    def __init__(self, host: str, port: int, max_body_bytes: int) -> None:
        self.host, self.port, self.max_body_bytes = host, port, max_body_bytes
        self._routes: dict[tuple[str, str], WebhookListener] = {}
        self._server: _QuietServer | None = None
        self._task: asyncio.Task[None] | None = None
        self.app = FastAPI(title="Automation webhooks", docs_url=None, redoc_url=None, openapi_url=None)
        self.app.add_api_route("/health", self._health, methods=["GET"])
        self.app.add_api_route("/webhook/{path:path}", self._dispatch, methods=_METHODS)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def url(self, path: str) -> str:
        return f"http://{self.host}:{self.port}/webhook/{path}"

    def register(self, method: str, path: str, listener: WebhookListener) -> None:
        key = (method, path)
        owner = self._routes.get(key)
        if owner is not None and owner is not listener:
            raise TriggerError(
                f"{method} /webhook/{path} is already used by workflow '{owner.workflow.name}'"
            )
        self._routes[key] = listener

    def unregister(self, method: str, path: str, listener: WebhookListener) -> None:
        if self._routes.get((method, path)) is listener:
            del self._routes[(method, path)]

    async def start(self) -> None:
        if self.running:
            return
        # port 0 resolves to the actual free port
        self._server, self._task, self.port = await start_uvicorn(self.app, self.host, self.port, "webhook-server")
        logger.info("webhook server listening on http://%s:%s", self.host, self.port)

    async def stop(self) -> None:
        if self._server is None or self._task is None:
            return
        await stop_uvicorn(self._server, self._task)
        self._server = self._task = None

    def routes(self) -> list[dict[str, str]]:
        return [{"method": m, "path": p, "workflow_id": l.workflow.id, "workflow_name": l.workflow.name,
                 "public": "yes" if l.params.allow_public else ("token" if l._token else "no")}
                for (m, p), l in sorted(self._routes.items())]

    async def _health(self) -> dict[str, Any]:
        return {"ok": True, "webhooks": [f"{m} /webhook/{p}" for m, p in sorted(self._routes)]}

    async def _dispatch(self, request: Request, path: str) -> JSONResponse:
        listener = self._routes.get((request.method, path.strip("/")))
        if listener is None:
            return JSONResponse({"error": f"no active webhook for {request.method} /webhook/{path}"}, 404)
        return await listener.handle(request)


class WebhookListener(TriggerListener):
    _server: WebhookServer | None = None
    _token: str | None = None

    async def start(self) -> None:
        if self.params.auth == "header":
            name = self.node.credentials.get("default")
            if not name:
                raise TriggerError(f"webhook '{self.node.id}' uses header auth but has no credential assigned")
            cred = await self.manager.engine.credentials.get_credential(name)
            if not cred.get("token"):
                raise TriggerError(f"credential '{name}' needs a 'token' field")
            self._token = str(cred["token"])
        if self.params.response_node and self.params.response_node not in {n.id for n in self.workflow.nodes}:
            raise TriggerError(f"response_node '{self.params.response_node}' does not exist")
        self._server = await self.manager.webhook_server()
        self._server.register(self.params.method, self.params.path, self)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.unregister(self.params.method, self.params.path, self)
            self._server = None

    def describe(self) -> str:
        url = self._server.url(self.params.path) if self._server else f"/webhook/{self.params.path}"
        return f"webhook {self.params.method} {url}" + (" (token required)" if self._token else "")

    async def handle(self, request: Request) -> JSONResponse:
        p = self.params
        if self._token is None and not p.allow_public and is_tunneled(request):
            return JSONResponse(
                {"error": "this webhook only accepts local calls; enable token auth or allow_public"}, 403)
        if self._token is not None:
            supplied = request.headers.get(p.auth_header, "")
            if not hmac.compare_digest(supplied.encode(), self._token.encode()):
                return JSONResponse({"error": "invalid or missing token"}, 401)

        limit = self.manager.max_body_bytes
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            return JSONResponse({"error": "body too large"}, 413)
        raw = await request.body()
        if len(raw) > limit:
            return JSONResponse({"error": "body too large"}, 413)
        try:
            body = _parse_body(raw, request.headers.get("content-type", ""))
        except ValueError as exc:
            return JSONResponse({"error": f"invalid body: {exc}"}, 400)

        hidden = _DROP_HEADERS | {p.auth_header.lower()}
        handle = self.fire({
            "method": request.method,
            "path": p.path,
            "query": dict(request.query_params),
            "headers": {k: v for k, v in request.headers.items() if k.lower() not in hidden},
            "body": body,
            "client": request.client.host if request.client else None,
        })
        if p.response_mode == "immediate":
            return JSONResponse({"execution_id": handle.execution_id, "status": "started"}, 202)

        try:
            result = await asyncio.wait_for(handle.result(), p.wait_timeout)
        except TimeoutError:
            return JSONResponse({"execution_id": handle.execution_id, "status": "running",
                                 "error": f"still running after {p.wait_timeout:g}s"}, 202)
        ok = result.status.value == "success"
        return JSONResponse(
            {"execution_id": result.execution_id, "status": result.status.value,
             "data": self._response_data(result) if ok else None, "error": result.error},
            200 if ok else 500,
        )

    def _response_data(self, result: Any) -> Any:
        if self.params.response_node:
            return result.nodes[self.params.response_node].output
        order = self.manager.graph(self.workflow.id).order
        for node_id in reversed(order):  # last node that actually produced output
            record = result.nodes[node_id]
            if record.status is NodeStatus.SUCCESS:
                return record.output
        return None


def _parse_body(raw: bytes, content_type: str) -> Any:
    if not raw:
        return None
    ctype = content_type.split(";")[0].strip().lower()
    if ctype == "application/json" or ctype.endswith("+json"):
        return json.loads(raw)
    if ctype == "application/x-www-form-urlencoded":
        return dict(parse_qsl(raw.decode("utf-8", errors="replace"), keep_blank_values=True))
    return raw.decode("utf-8", errors="replace")
