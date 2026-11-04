"""Studio API: the bridge between the GUI and the engine.

Security model (the API can run code, so it must not be callable by random web pages):
* binds to 127.0.0.1 only;
* rejects any Host header other than 127.0.0.1:<port> / localhost:<port> (DNS rebinding);
* every /api request needs the ``X-Studio-Token`` header. The token is embedded in the
  served index.html, which other origins cannot read, and the custom header forces a CORS
  preflight that this server never approves;
* the WebSocket checks Origin + token (browsers don't apply CORS to WebSockets);
* pages can't be framed (clickjacking).
"""

from __future__ import annotations

import asyncio
import hmac
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from engine.errors import WorkflowValidationError
from engine.models import WorkflowDefinition

from . import autostart, paths
from .updates import UpdateError

if TYPE_CHECKING:
    from .service import StudioService

CREDENTIAL_TYPES: dict[str, dict[str, Any]] = {
    "api_key": {"label": "API key (OpenAI, Anthropic, ...)", "fields": ["api_key"]},
    "bearer": {"label": "Bearer token", "fields": ["token"]},
    "basic": {"label": "Username + password", "fields": ["username", "password"]},
    "smtp": {"label": "SMTP email", "fields": ["host", "port", "username", "password", "security", "from_address"]},
    "linkedin": {"label": "LinkedIn", "fields": ["access_token", "author_urn"]},
    "webhook_token": {"label": "Webhook shared secret", "fields": ["token"]},
    "cloudflare_tunnel": {"label": "Cloudflare tunnel token", "fields": ["token"]},
    "generic": {"label": "Custom fields", "fields": []},
}
_SECRET_HINTS = ("key", "token", "password", "secret")
_TOKEN_PLACEHOLDER = "<!--studio-token-->"


class RunRequest(BaseModel):
    workflow: dict[str, Any] | None = None  # run the editor's current (possibly unsaved) graph
    workflow_id: str | None = None  # ...or a saved workflow
    trigger_data: Any = None
    start_node: str | None = None


class CredentialIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: str = "generic"
    data: dict[str, Any]


class UpdateSettings(BaseModel):
    source: str | None = None
    auto_check: bool = True


class TunnelSettings(BaseModel):
    enabled: bool
    mode: str = "quick"
    credential: str | None = None
    hostname: str | None = None


def create_app(svc: StudioService) -> FastAPI:
    app = FastAPI(title="Automation Studio API", docs_url=None, redoc_url=None, openapi_url=None)

    def allowed_hosts() -> set[str]:
        return {f"127.0.0.1:{svc.api_port}", f"localhost:{svc.api_port}"}

    def allowed_origins() -> set[str]:
        return {f"http://{h}" for h in allowed_hosts()} | svc.dev_origins

    def token_ok(value: str | None) -> bool:
        return bool(value) and hmac.compare_digest(value.encode(), svc.token.encode())

    @app.middleware("http")
    async def guard(request: Request, call_next: Any) -> Response:
        if request.headers.get("host", "") not in allowed_hosts():
            return PlainTextResponse("forbidden host", 403)
        if request.url.path.startswith("/api/") and not token_ok(request.headers.get("x-studio-token")):
            return JSONResponse({"detail": "missing or invalid X-Studio-Token"}, 401)
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    api = APIRouter(prefix="/api")

    def parse(definition: dict[str, Any]) -> WorkflowDefinition:
        try:
            return svc.engine.parse(definition)
        except WorkflowValidationError as exc:
            raise HTTPException(422, {"errors": exc.errors}) from None

    def validation_errors(wf: WorkflowDefinition) -> list[str]:
        try:
            svc.engine.validate(wf)
            return []
        except WorkflowValidationError as exc:
            return exc.errors

    # ---- service

    @api.get("/status")
    async def status() -> dict[str, Any]:
        return svc.status()

    @api.post("/shutdown")
    async def shutdown() -> dict[str, Any]:
        """Stop the background service cleanly (used by `main.py stop`)."""
        svc.request_shutdown()
        return {"stopping": True}

    @api.get("/node-types")
    async def node_types() -> list[dict[str, Any]]:
        return svc.engine.registry.catalog()

    @api.get("/credential-types")
    async def credential_types() -> dict[str, Any]:
        return CREDENTIAL_TYPES

    # ---- workflows

    @api.get("/workflows")
    async def list_workflows() -> list[dict[str, Any]]:
        return await asyncio.to_thread(svc.db.list_workflows)

    @api.post("/workflows")
    async def save_workflow(definition: dict[str, Any] = Body(...)) -> dict[str, Any]:
        wf = parse(definition)
        await asyncio.to_thread(svc.db.save_workflow, wf)
        await svc.sync_triggers()  # an active workflow's triggers follow its edits
        return {"workflow": wf.model_dump(mode="json"), "errors": validation_errors(wf)}

    @api.get("/workflows/{workflow_id}")
    async def get_workflow(workflow_id: str) -> dict[str, Any]:
        wf = await asyncio.to_thread(svc.db.get_workflow, workflow_id)
        if wf is None:
            raise HTTPException(404, "workflow not found")
        active = any(w["id"] == workflow_id and w["active"] for w in svc.db.list_workflows())
        return {"workflow": wf.model_dump(mode="json"), "active": active, "errors": validation_errors(wf)}

    @api.delete("/workflows/{workflow_id}")
    async def delete_workflow(workflow_id: str) -> dict[str, Any]:
        deleted = await asyncio.to_thread(svc.db.delete_workflow, workflow_id)
        await svc.sync_triggers()
        return {"deleted": deleted}

    @api.post("/workflows/{workflow_id}/active")
    async def set_active(workflow_id: str, body: dict[str, bool] = Body(...)) -> dict[str, Any]:
        active = bool(body.get("active"))
        wf = await asyncio.to_thread(svc.db.get_workflow, workflow_id)
        if wf is None:
            raise HTTPException(404, "save the workflow before activating it")
        if active and (errors := validation_errors(wf)):
            raise HTTPException(400, {"errors": errors})
        await asyncio.to_thread(svc.db.set_workflow_active, workflow_id, active)
        await svc.sync_triggers()
        triggers = next((w["triggers"] for w in svc.triggers.status() if w["workflow_id"] == workflow_id), [])
        return {"active": active, "triggers": triggers, "error": svc.triggers.errors.get(workflow_id)}

    @api.post("/validate")
    async def validate(definition: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return {"errors": validation_errors(parse(definition))}

    # ---- executions

    @api.post("/workflows/run", status_code=202)
    async def run(req: RunRequest) -> dict[str, Any]:
        if req.workflow is not None:
            wf = parse(req.workflow)
        elif req.workflow_id:
            wf = await asyncio.to_thread(svc.db.get_workflow, req.workflow_id)
            if wf is None:
                raise HTTPException(404, "workflow not found")
        else:
            raise HTTPException(400, "send 'workflow' or 'workflow_id'")
        try:
            handle = svc.run_workflow(wf, req.trigger_data, req.start_node)
        except WorkflowValidationError as exc:
            raise HTTPException(400, {"errors": exc.errors}) from None
        return {"execution_id": handle.execution_id}

    @api.post("/executions/{execution_id}/cancel")
    async def cancel(execution_id: str) -> dict[str, Any]:
        return {"cancelled": svc.engine.cancel(execution_id)}

    @api.get("/executions")
    async def list_executions(workflow_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return await asyncio.to_thread(svc.db.list_executions, workflow_id, min(limit, 500))

    @api.get("/executions/{execution_id}")
    async def get_execution(execution_id: str) -> dict[str, Any]:
        if (recent := svc.recent_results.get(execution_id)) is not None:
            return recent.model_dump(mode="json")
        handle = svc.engine.handle(execution_id)
        if handle is not None and (snap := handle.snapshot()) is not None:
            return snap.model_dump(mode="json")
        result = await asyncio.to_thread(svc.db.get_execution, execution_id)
        if result is None:
            raise HTTPException(404, "execution not found")
        return result.model_dump(mode="json")

    # ---- credentials (values never leave the service)

    @api.get("/credentials")
    async def list_credentials() -> list[dict[str, Any]]:
        return await asyncio.to_thread(svc.db.list_credentials)

    @api.post("/credentials")
    async def set_credential(body: CredentialIn) -> dict[str, Any]:
        await asyncio.to_thread(svc.db.set_credential, body.name, body.data, body.type)
        return {"saved": body.name, "fields": sorted(body.data)}

    @api.delete("/credentials/{name}")
    async def delete_credential(name: str) -> dict[str, Any]:
        return {"deleted": await asyncio.to_thread(svc.db.delete_credential, name)}

    # ---- tunnel & autostart

    @api.get("/tunnel")
    async def tunnel_status() -> dict[str, Any]:
        return {"settings": svc.status()["tunnel_settings"], "status": svc.tunnel.status()}

    @api.put("/tunnel")
    async def tunnel_update(body: TunnelSettings) -> dict[str, Any]:
        if body.mode not in ("quick", "token"):
            raise HTTPException(400, "mode must be 'quick' or 'token'")
        if body.enabled and body.mode == "token" and not (body.credential and body.hostname):
            raise HTTPException(400, "token mode needs a credential and a hostname")
        await asyncio.to_thread(svc.db.set_setting, "tunnel", body.model_dump())
        await svc.apply_tunnel_settings(force=True)
        return {"settings": body.model_dump(), "status": svc.tunnel.status()}

    # ---- updates

    @api.post("/updates/check")
    async def updates_check() -> dict[str, Any]:
        return await svc.updates.check()

    @api.put("/updates/settings")
    async def updates_settings(body: UpdateSettings) -> dict[str, Any]:
        source = (body.source or "").strip() or None
        if source and not (source.startswith("github:") or source.startswith("https://")):
            raise HTTPException(400, "update source must be github:owner/repo or an https:// manifest URL")
        return await svc.set_update_settings(source, body.auto_check)

    @api.post("/updates/install", status_code=202)
    async def updates_install() -> dict[str, Any]:
        ok, reason = svc.updates.install_preconditions()
        if not ok:
            raise HTTPException(400, reason)
        try:
            await svc.install_update()
        except UpdateError as exc:
            raise HTTPException(400, str(exc)) from None
        return {"installing": svc.updates.latest.version if svc.updates.latest else None}

    @api.get("/autostart")
    async def autostart_status() -> dict[str, Any]:
        return autostart.status()

    @api.put("/autostart")
    async def autostart_update(body: dict[str, bool] = Body(...)) -> dict[str, Any]:
        return autostart.enable() if body.get("enabled") else autostart.disable()

    app.include_router(api)

    # ---- live events

    @app.websocket("/ws/logs")
    async def ws_logs(ws: WebSocket, token: str = "", execution_id: str | None = None) -> None:
        if ws.headers.get("host", "") not in allowed_hosts() or ws.headers.get("origin") not in allowed_origins() \
                or not token_ok(token):
            await ws.close(code=4403)
            return
        await ws.accept()
        async with svc.engine.events.stream(execution_id) as queue:
            async def pump() -> None:
                while True:
                    event = await queue.get()
                    await ws.send_text(event.model_dump_json())

            async def drain() -> None:  # notices the client going away even when idle
                while True:
                    await ws.receive_text()

            tasks = [asyncio.create_task(pump()), asyncio.create_task(drain())]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            except WebSocketDisconnect:
                pass
            finally:
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    # ---- frontend (single-page app)

    dist = paths.FRONTEND_DIST

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> Response:
        if path.startswith(("api/", "ws/")):
            raise HTTPException(404)
        index = dist / "index.html"
        if not index.exists():
            return HTMLResponse(
                "<h1>Frontend not built</h1><p>Run <code>npm install && npm run build</code> in "
                "<code>frontend/</code>, or use the dev server (<code>npm run dev</code>).</p>", 503)
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and dist.resolve() in candidate.parents:
            media_type = mimetypes.guess_type(candidate.name)[0]
            return FileResponse(candidate, media_type=media_type,
                                headers={"Cache-Control": "public, max-age=31536000, immutable"}
                                if "/assets/" in candidate.as_posix() else None)
        html = index.read_text(encoding="utf-8").replace(
            _TOKEN_PLACEHOLDER, f'<meta name="studio-token" content="{svc.token}">')
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    return app
