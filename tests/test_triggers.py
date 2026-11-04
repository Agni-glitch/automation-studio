import asyncio
import os
import time
from datetime import datetime

import httpx
import pytest

from engine import InMemoryCredentialProvider, WorkflowEngine, WorkflowValidationError
from engine.triggers.base import TriggerError
from engine.triggers.cron import CronExpression
from engine.triggers.manager import TriggerManager


async def wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


def wf(trigger: dict, *rest: dict, wid: str = "w") -> dict:
    nodes = [{"id": "trig", **trigger}, *rest]
    conns = [{"source": "trig", "target": n["id"]} for n in rest]
    return {"id": wid, "name": wid, "nodes": nodes, "connections": conns}


# ------------------------------------------------------------------ cron


@pytest.mark.parametrize("expr, after, expected", [
    ("*/15 * * * *", "2026-11-04 10:07", "2026-11-04 10:15"),
    ("0 9 * * MON-FRI", "2026-11-06 09:00", "2026-11-09 09:00"),  # Fri 09:00 -> Mon
    ("30 23 31 * *", "2026-11-01 00:00", "2026-12-31 23:30"),  # November has no 31st
    ("0 0 29 2 *", "2026-03-01 00:00", "2028-02-29 00:00"),  # leap day
    ("0 12 1 * 0", "2026-11-02 00:00", "2026-11-08 12:00"),  # dom OR dow: next Sunday
    ("@daily", "2026-11-04 10:00", "2026-11-05 00:00"),
    ("5-10/5 8 * jan,NOV *", "2026-11-04 08:06", "2026-11-04 08:10"),
])
def test_cron_next(expr, after, expected):
    fmt = "%Y-%m-%d %H:%M"
    assert CronExpression(expr).next_after(datetime.strptime(after, fmt)) == datetime.strptime(expected, fmt)


@pytest.mark.parametrize("expr", ["* * * *", "60 * * * *", "*/0 * * * *", "1-x * * * *", "0 0 31 2 *"])
def test_cron_invalid(expr):
    with pytest.raises(ValueError):
        CronExpression(expr).next_after(datetime(2026, 1, 1))


def test_schedule_validation_in_workflow():
    with pytest.raises(WorkflowValidationError, match="never fires"):
        WorkflowEngine().validate(wf({"type": "trigger.schedule", "parameters": {"cron": "0 0 30 2 *"}}))


# ------------------------------------------------------------------ webhook


def test_webhook_wait_mode_with_token():
    async def scenario():
        results = []
        engine = WorkflowEngine(credentials=InMemoryCredentialProvider({"hook": {"token": "s3cret-token"}}))
        manager = TriggerManager(engine, port=0, on_result=results.append)
        definition = wf(
            {"type": "trigger.webhook", "credentials": {"default": "hook"},
             "parameters": {"path": "/jobs/new/", "auth": "header", "response_mode": "wait"}},
            {"id": "reply", "type": "logic.set",
             "parameters": {"values": {"got": "{{ input.body.title }}", "src": "{{ input.query.src }}"}}},
        )
        [desc] = await manager.activate(definition)
        base = f"http://127.0.0.1:{manager.webhook_port}"
        async with httpx.AsyncClient() as client:
            denied = await client.post(f"{base}/webhook/jobs/new", json={})
            ok = await client.post(f"{base}/webhook/jobs/new?src=test", json={"title": "Dev"},
                                   headers={"X-Webhook-Token": "s3cret-token"})
            wrong_method = await client.get(f"{base}/webhook/jobs/new")
            health = await client.get(f"{base}/health")
        await manager.stop()
        return desc, denied, ok, wrong_method, health, results

    desc, denied, ok, wrong_method, health, results = asyncio.run(scenario())
    assert "token required" in desc
    assert denied.status_code == 401
    assert ok.status_code == 200 and ok.json()["data"] == {"got": "Dev", "src": "test"}
    assert wrong_method.status_code == 404
    assert health.json()["webhooks"] == ["POST /webhook/jobs/new"]
    [result] = results  # the rejected call never started an execution
    assert "x-webhook-token" not in result.trigger_data["headers"]


def test_webhook_immediate_mode_and_path_conflict():
    async def scenario():
        results = []
        manager = TriggerManager(WorkflowEngine(), port=0, on_result=results.append)
        hook = {"type": "trigger.webhook", "parameters": {"path": "ping"}}
        await manager.activate(wf(hook, wid="a"))
        with pytest.raises(TriggerError, match="already used"):
            await manager.activate(wf(hook, wid="b"))
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"http://127.0.0.1:{manager.webhook_port}/webhook/ping", content="hello",
                                     headers={"content-type": "text/plain"})
        await wait_until(lambda: results)
        await manager.stop()
        return resp, results

    resp, results = asyncio.run(scenario())
    assert resp.status_code == 202 and resp.json()["status"] == "started"
    assert results[0].trigger_data["body"] == "hello"


# ------------------------------------------------------------------ folder watcher


def test_file_trigger_settles_filters_and_stops(tmp_path):
    async def scenario():
        results = []
        manager = TriggerManager(WorkflowEngine(), on_result=results.append)
        await manager.activate(wf({"type": "trigger.file", "parameters": {
            "directory": str(tmp_path), "patterns": ["*.txt"], "settle_seconds": 0.15}}))
        await asyncio.sleep(0.2)

        with open(tmp_path / "a.txt", "w") as f:  # written in chunks: must fire once, at the end
            for _ in range(3):
                f.write("x" * 1000)
                f.flush()
                await asyncio.sleep(0.05)
        (tmp_path / "skip.log").write_text("no")
        (tmp_path / "~$lock.txt").write_text("office temp file")
        (tmp_path / "b.txt.part").write_text("downloading")
        os.replace(tmp_path / "b.txt.part", tmp_path / "b.txt")  # finish-by-rename

        await wait_until(lambda: len(results) >= 2)
        await asyncio.sleep(0.6)  # make sure nothing else fires
        names = sorted(r.trigger_data["name"] for r in results)

        await manager.deactivate("w")
        (tmp_path / "late.txt").write_text("after deactivate")
        await asyncio.sleep(0.5)
        await manager.stop()
        return names, results

    names, results = asyncio.run(scenario())
    assert names == ["a.txt", "b.txt"]
    a = next(r for r in results if r.trigger_data["name"] == "a.txt")
    assert a.trigger_data["event"] == "created" and a.trigger_data["size"] == 3000


def test_file_trigger_missing_folder():
    async def scenario():
        manager = TriggerManager(WorkflowEngine())
        with pytest.raises(TriggerError, match="does not exist"):
            await manager.activate(wf({"type": "trigger.file", "parameters": {"directory": "Z:/nope/nowhere"}}))

    asyncio.run(scenario())


# ------------------------------------------------------------------ schedule + sync


def test_interval_schedule_and_skip_if_running():
    async def scenario(wait_seconds: float):
        results = []
        manager = TriggerManager(WorkflowEngine(), on_result=results.append)
        await manager.activate(wf(
            {"type": "trigger.schedule", "parameters": {"mode": "interval", "every_seconds": 0.1, "run_on_start": True}},
            {"id": "work", "type": "logic.wait", "parameters": {"seconds": wait_seconds}},
        ))
        await asyncio.sleep(0.75)
        await manager.stop()
        return results

    fast = asyncio.run(scenario(0))
    slow = asyncio.run(scenario(0.3))  # each run outlasts the interval -> ticks are skipped
    assert len(fast) >= 5
    assert 2 <= len(slow) <= 3
    assert "scheduled_for" in fast[0].trigger_data


def test_sync_activates_changes_and_removes():
    async def scenario():
        manager = TriggerManager(WorkflowEngine(), port=0)
        hook = wf({"type": "trigger.webhook", "parameters": {"path": "one"}}, wid="x")
        await manager.sync([(manager.engine.parse(hook), "v1")])
        first = manager.status()
        hook["nodes"][0]["parameters"]["path"] = "two"
        await manager.sync([(manager.engine.parse(hook), "v2")])
        second = manager.status()
        bad = wf({"type": "trigger.file", "parameters": {"directory": "Z:/missing"}}, wid="bad")
        await manager.sync([(manager.engine.parse(hook), "v2"), (manager.engine.parse(bad), "v1")])
        errors = dict(manager.errors)
        await manager.sync([])
        final = manager.status()
        await manager.stop()
        return first, second, errors, final

    first, second, errors, final = asyncio.run(scenario())
    assert first[0]["triggers"][0].endswith("/webhook/one")
    assert second[0]["triggers"][0].endswith("/webhook/two")
    assert "does not exist" in errors["bad"]
    assert final == []
