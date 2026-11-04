import asyncio
import json
import sys

import httpx
import pytest
from websockets.asyncio.client import connect

from backend import autostart, paths
from backend.service import StudioService
from database import Database, StaticKeyStore

TOKEN = "t" * 40

HELLO = {
    "id": "hello", "name": "Hello",
    "nodes": [
        {"id": "hook", "type": "trigger.webhook", "parameters": {"path": "hi", "response_mode": "wait"}},
        {"id": "greet", "type": "logic.set", "parameters": {"values": {"msg": "hi {{ input.body.name ?? \"you\" }}"}}},
    ],
    "connections": [{"source": "hook", "target": "greet"}],
}


def with_service(tmp_path, scenario, dist=None, monkeypatch=None):
    async def go():
        if dist is not None:
            monkeypatch.setattr(paths, "FRONTEND_DIST", dist)
        db = Database(tmp_path / "s.db", key_store=StaticKeyStore())
        svc = StudioService(db, api_port=0, webhook_port=0, token=TOKEN, bin_dir=tmp_path / "bin",
                            service_file=None, poll_seconds=0.2)
        await svc.start()
        base = svc.api_url
        try:
            async with httpx.AsyncClient(base_url=base, headers={"X-Studio-Token": TOKEN}, timeout=10) as client:
                return await scenario(svc, client)
        finally:
            await svc.stop()
            db.close()

    return asyncio.run(go())


def test_api_security(tmp_path):
    async def scenario(svc, client):
        no_token = await httpx.AsyncClient().get(f"{svc.api_url}/api/status")
        bad_host = await client.get("/api/status", headers={"Host": "evil.example:80"})
        ok = await client.get("/api/status")
        return no_token.status_code, bad_host.status_code, ok

    no_token, bad_host, ok = with_service(tmp_path, scenario)
    assert no_token == 401 and bad_host == 403
    assert ok.status_code == 200 and ok.headers["x-frame-options"] == "DENY"


def test_workflow_crud_run_and_live_events(tmp_path):
    async def scenario(svc, client):
        saved = (await client.post("/api/workflows", json=HELLO)).json()
        broken = dict(HELLO, id="broken", nodes=[{"id": "x", "type": "nope"}], connections=[])
        broken_saved = (await client.post("/api/workflows", json=broken)).json()
        listing = (await client.get("/api/workflows")).json()

        origin = f"http://127.0.0.1:{svc.api_port}"
        uri = f"ws://127.0.0.1:{svc.api_port}/ws/logs?token={TOKEN}"
        events = []
        async with connect(uri, origin=origin) as ws:
            run = (await client.post("/api/workflows/run",
                                     json={"workflow": HELLO, "trigger_data": {"body": {"name": "Ada"}}})).json()
            while True:
                event = json.loads(await asyncio.wait_for(ws.recv(), 5))
                if event["execution_id"] == run["execution_id"]:
                    events.append(event["type"])
                    if event["type"] == "execution.finished":
                        break
        await asyncio.sleep(0.2)  # persisted after finishing
        result = (await client.get(f"/api/executions/{run['execution_id']}")).json()
        history = (await client.get("/api/executions", params={"workflow_id": "hello"})).json()
        return saved, broken_saved, listing, events, result, history

    saved, broken_saved, listing, events, result, history = with_service(tmp_path, scenario)
    assert saved["errors"] == [] and "unknown type 'nope'" in broken_saved["errors"][0]
    assert {w["id"] for w in listing} == {"hello", "broken"}
    assert events[0] == "execution.started" and "node.succeeded" in events
    assert result["nodes"]["greet"]["output"] == {"msg": "hi Ada"}
    assert history[0]["status"] == "success"


def test_websocket_rejects_foreign_origin_and_bad_token(tmp_path):
    async def scenario(svc, client):
        outcomes = []
        for origin, token in (("https://evil.example", TOKEN), (f"http://127.0.0.1:{svc.api_port}", "wrong")):
            try:
                async with connect(f"ws://127.0.0.1:{svc.api_port}/ws/logs?token={token}", origin=origin) as ws:
                    await asyncio.wait_for(ws.recv(), 2)
                    outcomes.append("open")
            except Exception as exc:
                outcomes.append(type(exc).__name__)
        return outcomes

    assert "open" not in with_service(tmp_path, scenario)


def test_activate_webhook_and_public_guard(tmp_path):
    async def scenario(svc, client):
        await client.post("/api/workflows", json=HELLO)
        activated = (await client.post("/api/workflows/hello/active", json={"active": True})).json()
        hook = f"http://127.0.0.1:{svc.triggers.webhook_port}/webhook/hi"
        async with httpx.AsyncClient() as raw:
            local = await raw.post(hook, json={"name": "Bo"})
            via_tunnel = await raw.post(hook, json={}, headers={"cf-connecting-ip": "203.0.113.9"})
            public = json.loads(json.dumps(HELLO))
            public["nodes"][0]["parameters"]["allow_public"] = True
            await client.post("/api/workflows", json=public)  # saving an active workflow re-syncs it
            via_tunnel_public = await raw.post(hook, json={}, headers={"cf-connecting-ip": "203.0.113.9"})
        status = (await client.get("/api/status")).json()
        deactivated = (await client.post("/api/workflows/hello/active", json={"active": False})).json()
        return activated, local, via_tunnel, via_tunnel_public, status, deactivated

    activated, local, via_tunnel, via_tunnel_public, status, deactivated = with_service(tmp_path, scenario)
    assert activated["active"] and "webhook POST" in activated["triggers"][0]
    assert local.json()["data"] == {"msg": "hi Bo"}
    assert via_tunnel.status_code == 403
    assert via_tunnel_public.status_code == 200
    assert status["webhooks"][0]["public"] == "yes"
    assert deactivated["active"] is False


def test_credentials_api_never_returns_values(tmp_path):
    async def scenario(svc, client):
        await client.post("/api/credentials", json={"name": "openai", "type": "api_key",
                                                     "data": {"api_key": "sk-top-secret-1"}})
        listing = await client.get("/api/credentials")
        types = (await client.get("/api/credential-types")).json()
        return listing, types

    listing, types = with_service(tmp_path, scenario)
    assert "sk-top-secret-1" not in listing.text
    assert listing.json()[0]["fields"] == ["api_key"] and "smtp" in types


def test_spa_serving_injects_token(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<head><!--studio-token--></head><div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log(1)")

    async def scenario(svc, client):
        bare = httpx.AsyncClient(base_url=svc.api_url)
        return (await bare.get("/")).text, await bare.get("/assets/app.js"), (await bare.get("/workflow/123")).text

    index, asset, deep_link = with_service(tmp_path, scenario, dist=dist, monkeypatch=monkeypatch)
    assert f'content="{TOKEN}"' in index and f'content="{TOKEN}"' in deep_link
    assert asset.status_code == 200 and "javascript" in asset.headers["content-type"]


def test_shutdown_endpoint_stops_run_loop(tmp_path):
    async def go():
        db = Database(tmp_path / "s.db", key_store=StaticKeyStore())
        svc = StudioService(db, api_port=0, webhook_port=0, token=TOKEN, bin_dir=tmp_path / "bin",
                            service_file=None, poll_seconds=30)
        loop_task = asyncio.create_task(svc.run_forever())
        while svc._api is None:
            await asyncio.sleep(0.05)
        async with httpx.AsyncClient(base_url=svc.api_url, headers={"X-Studio-Token": TOKEN}) as client:
            assert (await client.post("/api/shutdown")).json() == {"stopping": True}
        await asyncio.wait_for(loop_task, 10)  # returns promptly despite the 30 s poll interval
        db.close()

    asyncio.run(go())


@pytest.mark.skipif(sys.platform != "win32", reason="Windows registry")
def test_autostart_registry_roundtrip():
    name = "AutomationStudioTest"
    try:
        on = autostart.enable(name)
        assert on["enabled"] and on["up_to_date"] and "serve --background" in on["command"]
    finally:
        off = autostart.disable(name)
    assert off["enabled"] is False
