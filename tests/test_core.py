import asyncio
import time
from typing import Any

import pytest
from pydantic import BaseModel

from engine import (
    BaseNode,
    EventType,
    ExecutionStatus,
    InMemoryCredentialProvider,
    NodeContext,
    NodeExecutionError,
    NodeStatus,
    WorkflowEngine,
    WorkflowValidationError,
    default_registry,
)

# ---------------------------------------------------------------- test-only nodes

registry = default_registry.copy()
_flaky_calls: dict[str, int] = {}


@registry.register
class FlakyNode(BaseNode):
    type = "test.flaky"
    display_name = "Flaky"
    category = "logic"

    class Parameters(BaseModel):
        key: str
        fail_times: int = 0

    async def execute(self, ctx: NodeContext, params: Parameters) -> Any:
        _flaky_calls[params.key] = _flaky_calls.get(params.key, 0) + 1
        if _flaky_calls[params.key] <= params.fail_times:
            raise NodeExecutionError(f"boom #{_flaky_calls[params.key]}")
        return {"calls": _flaky_calls[params.key]}


@registry.register
class SecretEchoNode(BaseNode):
    type = "test.secret"
    display_name = "Secret"
    category = "action"
    credential_slots = {"default": "test api key"}

    async def execute(self, ctx: NodeContext, params: Any) -> Any:
        cred = await ctx.get_credential()
        ctx.info(f"using key {cred['api_key']}")
        return {"ok": True}


def engine(**kw: Any) -> WorkflowEngine:
    return WorkflowEngine(registry=registry, **kw)


def wf(nodes: list[dict], connections: list[tuple] = (), **settings: Any) -> dict:
    conns = [
        {"source": c[0], "target": c[1], **({"source_output": c[2]} if len(c) > 2 else {})}
        for c in connections
    ]
    return {"name": "test", "nodes": nodes, "connections": conns, "settings": settings}


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- tests


def test_linear_flow_with_expressions():
    definition = wf(
        [
            {"id": "start", "type": "trigger.manual"},
            {"id": "shape", "type": "logic.set", "parameters": {"values": {
                "greeting": "Hi {{ input.name }}!",
                "raw": "{{ trigger.tags }}",
                "first_tag": "{{ nodes.start.tags[0] }}",
                "who": "{{ vars.owner }}",
            }}},
        ],
        [("start", "shape")],
    )
    definition["variables"] = {"owner": "me"}
    result = run(engine().run(definition, trigger_data={"name": "Ada", "tags": ["x", "y"]}))
    assert result.status is ExecutionStatus.SUCCESS
    assert result.output_of("shape") == {"greeting": "Hi Ada!", "raw": ["x", "y"], "first_tag": "x", "who": "me"}


def test_parallel_branches_run_concurrently():
    definition = wf(
        [
            {"id": "start", "type": "trigger.manual"},
            {"id": "a", "type": "logic.wait", "parameters": {"seconds": 0.3}},
            {"id": "b", "type": "logic.wait", "parameters": {"seconds": 0.3}},
            {"id": "join", "type": "logic.set", "parameters": {"values": {"n": 1}}},
        ],
        [("start", "a"), ("start", "b"), ("a", "join"), ("b", "join")],
    )
    t0 = time.perf_counter()
    result = run(engine().run(definition))
    assert result.status is ExecutionStatus.SUCCESS
    assert time.perf_counter() - t0 < 0.55


def test_if_branch_skips_other_side():
    definition = wf(
        [
            {"id": "start", "type": "trigger.manual"},
            {"id": "check", "type": "logic.if", "parameters": {"left": "{{ input.score }}", "operator": "greater_than", "right": 70}},
            {"id": "yes", "type": "logic.set", "parameters": {"values": {"r": "strong"}}},
            {"id": "no", "type": "logic.set", "parameters": {"values": {"r": "weak"}}},
            {"id": "after_no", "type": "logic.set"},
        ],
        [("start", "check"), ("check", "yes", "true"), ("check", "no", "false"), ("no", "after_no")],
    )
    result = run(engine().run(definition, trigger_data={"score": "82"}))
    assert result.status is ExecutionStatus.SUCCESS
    assert result.nodes["yes"].status is NodeStatus.SUCCESS
    assert result.nodes["no"].status is NodeStatus.SKIPPED
    assert result.nodes["after_no"].status is NodeStatus.SKIPPED


def test_validation_errors():
    with pytest.raises(WorkflowValidationError, match="cycle"):
        engine().validate(wf(
            [{"id": "a", "type": "logic.set"}, {"id": "b", "type": "logic.set"}],
            [("a", "b"), ("b", "a")],
        ))
    with pytest.raises(WorkflowValidationError) as info:
        engine().validate(wf(
            [{"id": "a", "type": "nope"}, {"id": "w", "type": "logic.wait", "parameters": {"seconds": -1}},
             {"id": "i", "type": "logic.if"}, {"id": "x", "type": "logic.set"}],
            [("i", "x", "maybe")],
        ))
    text = str(info.value)
    assert "unknown type 'nope'" in text and "seconds" in text and "no output 'maybe'" in text


def test_retry_then_succeed():
    definition = wf([{"id": "f", "type": "test.flaky", "parameters": {"key": "retry1", "fail_times": 2},
                      "retry": {"max_attempts": 3, "backoff_seconds": 0.01}}])
    events: list = []
    eng = engine()
    eng.events.subscribe(events.append)
    result = run(eng.run(definition))
    assert result.status is ExecutionStatus.SUCCESS
    assert result.nodes["f"].attempts == 3
    assert sum(e.type is EventType.NODE_RETRY for e in events) == 2
    assert events[0].type is EventType.EXECUTION_STARTED and events[-1].type is EventType.EXECUTION_FINISHED


def test_fail_fast_cancels_running_branch():
    definition = wf(
        [
            {"id": "start", "type": "trigger.manual"},
            {"id": "bad", "type": "test.flaky", "parameters": {"key": "ff", "fail_times": 99}},
            {"id": "slow", "type": "logic.wait", "parameters": {"seconds": 5}},
            {"id": "after_bad", "type": "logic.set"},
        ],
        [("start", "bad"), ("start", "slow"), ("bad", "after_bad")],
    )
    t0 = time.perf_counter()
    result = run(engine().run(definition))
    assert time.perf_counter() - t0 < 2
    assert result.status is ExecutionStatus.FAILED
    assert "boom" in result.error
    assert result.nodes["slow"].status is NodeStatus.CANCELLED
    assert result.nodes["after_bad"].status is NodeStatus.CANCELLED


def test_error_output_and_continue():
    definition = wf(
        [
            {"id": "bad", "type": "test.flaky", "parameters": {"key": "eo", "fail_times": 99}, "on_error": "error_output"},
            {"id": "ok_path", "type": "logic.set"},
            {"id": "err_path", "type": "logic.set", "parameters": {"values": {"why": "{{ input.error.message }}"}}},
            {"id": "bad2", "type": "test.flaky", "parameters": {"key": "co", "fail_times": 99}, "on_error": "continue"},
            {"id": "next", "type": "logic.set", "parameters": {"include_input": True}},
        ],
        [("bad", "ok_path"), ("bad", "err_path", "error"), ("bad2", "next")],
    )
    result = run(engine().run(definition))
    assert result.status is ExecutionStatus.SUCCESS
    assert result.nodes["ok_path"].status is NodeStatus.SKIPPED
    assert result.output_of("err_path") == {"why": "boom #1"}
    assert result.output_of("next")["error"]["message"] == "boom #1"


def test_disabled_node_passes_input_through():
    definition = wf(
        [
            {"id": "start", "type": "trigger.manual"},
            {"id": "off", "type": "logic.set", "disabled": True, "parameters": {"values": {"x": 1}}},
            {"id": "end", "type": "logic.set", "parameters": {"values": {"v": "{{ input.v }}"}}},
        ],
        [("start", "off"), ("off", "end")],
    )
    result = run(engine().run(definition, trigger_data={"v": 7}))
    assert result.output_of("end") == {"v": 7}


def test_workflow_timeout_and_node_timeout():
    slow = wf([{"id": "w", "type": "logic.wait", "parameters": {"seconds": 5}}], timeout_seconds=0.2)
    result = run(engine().run(slow))
    assert result.status is ExecutionStatus.FAILED and "timed out" in result.error

    node_to = wf([{"id": "w", "type": "logic.wait", "parameters": {"seconds": 5}, "timeout_seconds": 0.1}])
    result = run(engine().run(node_to))
    assert result.nodes["w"].error.type == "NodeTimeoutError"


def test_cancel_execution():
    async def scenario():
        eng = engine()
        handle = eng.start(wf([{"id": "w", "type": "logic.wait", "parameters": {"seconds": 5}}]))
        await asyncio.sleep(0.1)
        assert eng.cancel(handle.execution_id)
        return await handle.result()

    result = run(scenario())
    assert result.status is ExecutionStatus.CANCELLED
    assert result.nodes["w"].status is NodeStatus.CANCELLED


def test_credentials_are_redacted_from_logs():
    creds = InMemoryCredentialProvider({"my-key": {"api_key": "sk-super-secret-123"}})
    definition = wf([{"id": "s", "type": "test.secret", "credentials": {"default": "my-key"}}])
    result = run(engine(credentials=creds).run(definition))
    assert result.status is ExecutionStatus.SUCCESS
    assert result.nodes["s"].logs[0].message == "using key ***"

    missing = wf([{"id": "s", "type": "test.secret"}])
    result = run(engine(credentials=creds).run(missing))
    assert result.nodes["s"].error.type == "CredentialNotFoundError"


def test_start_node_skips_other_triggers():
    definition = wf(
        [
            {"id": "t1", "type": "trigger.manual"},
            {"id": "t2", "type": "trigger.manual"},
            {"id": "end", "type": "logic.set", "parameters": {"values": {"from": "{{ input.src }}"}}},
        ],
        [("t1", "end"), ("t2", "end")],
    )
    result = run(engine().run(definition, start_node="t2", trigger_data={"src": "t2"}))
    assert result.nodes["t1"].status is NodeStatus.SKIPPED
    assert result.output_of("end") == {"from": "t2"}


def test_expression_fallbacks():
    definition = wf(
        [
            {"id": "start", "type": "trigger.manual"},
            {"id": "s", "type": "logic.set", "parameters": {"values": {
                "a": "{{ input.missing ?? \"dflt\" }}",
                "b": "{{ input.nothing ?? input.n }}",
                "c": "{{ input.none ?? 5 }}",  # null also falls through
                "d": "Hi {{ input.who ?? \"there\" }}",
                "e": "{{ input.x.y.z ?? null }}",
            }}},
        ],
        [("start", "s")],
    )
    result = run(engine().run(definition, trigger_data={"n": 3, "none": None}))
    assert result.output_of("s") == {"a": "dflt", "b": 3, "c": 5, "d": "Hi there", "e": None}


def test_missing_expression_path_fails_without_retry():
    definition = wf([{"id": "s", "type": "logic.set", "parameters": {"values": {"x": "{{ nodes.ghost.y }}"}},
                      "retry": {"max_attempts": 3, "backoff_seconds": 0}}])
    result = run(engine().run(definition))
    assert result.status is ExecutionStatus.FAILED
    assert result.nodes["s"].attempts == 0
    assert "cannot resolve 'nodes.ghost'" in result.nodes["s"].error.message
