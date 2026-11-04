import asyncio
import json
import smtplib
import sys
from typing import Any

import httpx
import pytest

from engine import ExecutionStatus, InMemoryCredentialProvider, NodeStatus, WorkflowEngine, WorkflowValidationError

SCHEMA = {
    "type": "object",
    "required": ["score", "skills"],
    "properties": {"score": {"type": "integer", "minimum": 0, "maximum": 100},
                   "skills": {"type": "array", "items": {"type": "string"}}},
}


def run_single(node: dict, *, handler=None, creds: dict | None = None, trigger: Any = None, **services):
    """Run a workflow consisting of one node; returns (result, record)."""
    async def go():
        if handler is not None:
            services["http_client"] = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        engine = WorkflowEngine(credentials=InMemoryCredentialProvider(creds or {}), services=services)
        result = await engine.run({"name": "t", "nodes": [{"id": "n", **node}]}, trigger_data=trigger)
        if "http_client" in services:
            await services["http_client"].aclose()
        return result

    result = asyncio.run(go())
    return result, result.nodes["n"]


# ------------------------------------------------------------------ HTTP request


def test_http_request_with_bearer_and_query():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers["authorization"]
        seen["url"] = str(req.url)
        return httpx.Response(200, json={"jobs": [1, 2]})

    result, rec = run_single(
        {"type": "action.http_request", "credentials": {"default": "k"},
         "parameters": {"url": "https://api.test/jobs", "query": {"q": "{{ input.q }}", "remote": True},
                        "auth": "bearer"}},
        handler=handler, creds={"k": {"token": "tok-12345"}}, trigger={"q": "python"},
    )
    assert result.status is ExecutionStatus.SUCCESS
    assert rec.output["data"] == {"jobs": [1, 2]} and rec.output["status"] == 200
    assert seen["auth"] == "Bearer tok-12345"
    assert seen["url"] == "https://api.test/jobs?q=python&remote=true"


def test_http_request_retries_5xx_not_4xx():
    calls = {"n": 0}

    def flaky(req):
        calls["n"] += 1
        return httpx.Response(503 if calls["n"] < 3 else 200, text="ok")

    node = {"type": "action.http_request", "parameters": {"url": "https://api.test/x"},
            "retry": {"max_attempts": 3, "backoff_seconds": 0}}
    _, rec = run_single(node, handler=flaky)
    assert rec.status is NodeStatus.SUCCESS and rec.attempts == 3

    calls["n"] = 0

    def not_found(req):
        calls["n"] += 1
        return httpx.Response(404, text="nope")

    _, rec = run_single(node, handler=not_found)
    assert rec.status is NodeStatus.FAILED and calls["n"] == 1 and "404" in rec.error.message


# ------------------------------------------------------------------ AI agent


def _ai_node(provider: str, **params) -> dict:
    return {"type": "ai.agent", "credentials": {"default": "llm"},
            "parameters": {"provider": provider, "model": "m-1", "prompt": "Rate this CV",
                           "input_data": "{{ input }}", "output_schema": SCHEMA, **params}}


def test_ai_agent_anthropic_forced_tool():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        seen["key"] = req.headers["x-api-key"]
        return httpx.Response(200, json={
            "model": "m-1", "stop_reason": "tool_use", "usage": {"input_tokens": 10, "output_tokens": 5},
            "content": [{"type": "tool_use", "id": "t", "name": "submit_result",
                         "input": {"score": 80, "skills": ["python"]}}]})

    _, rec = run_single(_ai_node("anthropic"), handler=handler,
                        creds={"llm": {"api_key": "sk-ant-xyz"}}, trigger={"cv": "Ada, Python dev"})
    assert rec.status is NodeStatus.SUCCESS, rec.error
    assert rec.output["result"] == {"score": 80, "skills": ["python"]}
    assert seen["key"] == "sk-ant-xyz"
    assert seen["body"]["tool_choice"] == {"type": "tool", "name": "submit_result"}
    assert "Ada, Python dev" in seen["body"]["messages"][0]["content"]


def test_ai_agent_openai_and_schema_retry():
    replies = iter(['{"score": "high"}', '```json\n{"score": 70, "skills": []}\n```'])

    def handler(req):
        body = json.loads(req.content)
        assert body["response_format"]["type"] == "json_schema"
        assert "max_completion_tokens" in body
        return httpx.Response(200, json={"model": "m-1", "choices": [
            {"message": {"content": next(replies)}, "finish_reason": "stop"}], "usage": {}})

    node = _ai_node("openai") | {"retry": {"max_attempts": 2, "backoff_seconds": 0}}
    _, rec = run_single(node, handler=handler, creds={"llm": {"api_key": "sk-1234"}})
    assert rec.status is NodeStatus.SUCCESS and rec.attempts == 2
    assert rec.output["result"]["score"] == 70


def test_ai_agent_ollama_needs_no_key():
    def handler(req):
        assert req.url.host == "localhost" and json.loads(req.content)["format"] == SCHEMA
        return httpx.Response(200, json={"model": "llama3", "message": {"content": '{"score": 5, "skills": ["x"]}'}})

    node = _ai_node("ollama")
    node.pop("credentials")
    _, rec = run_single(node, handler=handler)
    assert rec.status is NodeStatus.SUCCESS, rec.error


def test_ai_agent_auth_error_not_retried():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(401, json={"error": "bad key"})

    node = _ai_node("anthropic") | {"retry": {"max_attempts": 3, "backoff_seconds": 0}}
    _, rec = run_single(node, handler=handler, creds={"llm": {"api_key": "bad-key"}})
    assert rec.status is NodeStatus.FAILED and calls["n"] == 1


# ------------------------------------------------------------------ Python script


def _script(code: str, **params) -> dict:
    return {"type": "code.python", "parameters": {"code": code, **params}}


def test_python_script_main_and_logs():
    code = "def main(input):\n    print('got', input['n'])\n    return {'double': input['n'] * 2, 'k': args['k']}\n"
    _, rec = run_single(_script(code, arguments={"k": "v"}), trigger={"n": 21})
    assert rec.status is NodeStatus.SUCCESS, rec.error
    assert rec.output == {"double": 42, "k": "v"}
    assert any(log.message == "got 21" for log in rec.logs)


def test_python_script_result_variable_and_braces_untouched():
    _, rec = run_single(_script("result = '{{ not an expression }}'"))
    assert rec.output == "{{ not an expression }}"


def test_python_script_error_has_user_traceback():
    _, rec = run_single(_script("x = 1\ny = x / 0\n"))
    assert rec.status is NodeStatus.FAILED
    assert "ZeroDivisionError" in rec.error.message and "line 2" in rec.error.message


def test_python_script_timeout():
    _, rec = run_single(_script("while True: pass", timeout_seconds=1))
    assert rec.status is NodeStatus.FAILED and rec.error.type == "NodeTimeoutError"


def test_python_script_env_is_stripped(monkeypatch):
    monkeypatch.setenv("SUPER_SECRET_TOKEN", "leak")
    _, rec = run_single(_script("import os\nresult = os.environ.get('SUPER_SECRET_TOKEN')"))
    assert rec.output is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object limits")
def test_python_script_job_object_limits():
    _, rec = run_single(_script("result = len(bytearray(400 * 1024 * 1024))", memory_limit_mb=64))
    assert rec.status is NodeStatus.FAILED and "MemoryError" in rec.error.message

    code = "import subprocess, sys\nresult = subprocess.run([sys.executable, '-c', 'print(1)']).returncode"
    _, rec = run_single(_script(code))
    assert rec.status is NodeStatus.FAILED  # spawning a child process is blocked


# ------------------------------------------------------------------ Email


def _email(**params) -> dict:
    return {"type": "action.email", "credentials": {"default": "smtp"},
            "parameters": {"to": "a@example.com, b@example.com", "subject": "Hi", "body": "Hello", **params}}


def test_email_dry_run_needs_no_credential():
    _, rec = run_single(_email(dry_run=True))
    assert rec.status is NodeStatus.SUCCESS
    assert rec.output["sent"] is False and rec.output["to"] == ["a@example.com", "b@example.com"]


def test_email_sends_via_smtp(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent["server"] = (host, port)
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def starttls(self, context): sent["tls"] = True
        def login(self, u, p): sent["login"] = (u, p)
        def send_message(self, msg, to_addrs): sent["msg"], sent["rcpt"] = msg, to_addrs

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    creds = {"smtp": {"host": "smtp.gmail.com", "username": "me@gmail.com", "password": "app-pass"}}
    _, rec = run_single(_email(bcc=["hidden@example.com"]), creds=creds)
    assert rec.status is NodeStatus.SUCCESS, rec.error
    assert sent["server"] == ("smtp.gmail.com", 587) and sent["tls"]
    assert sent["rcpt"] == ["a@example.com", "b@example.com", "hidden@example.com"]
    assert "Bcc" not in sent["msg"] and sent["msg"]["From"] == "me@gmail.com"


def test_email_rejects_bad_address():
    # static value: caught when the workflow is validated, before anything runs
    with pytest.raises(WorkflowValidationError, match="invalid email"):
        run_single(_email(to="not-an-email", dry_run=True))
    # expression value: caught at run time, without retrying
    _, rec = run_single(_email(to="{{ input.to }}", dry_run=True), trigger={"to": "nope"})
    assert rec.status is NodeStatus.FAILED and "invalid email" in rec.error.message and rec.attempts == 0


# ------------------------------------------------------------------ Social


def test_social_post_dry_run_and_live():
    _, rec = run_single({"type": "action.social_post", "parameters": {"text": "Hello"}})
    assert rec.output == {"posted": False, "dry_run": True, "platform": "linkedin", "text": "Hello"}

    def handler(req):
        body = json.loads(req.content)
        assert body["author"] == "urn:li:person:1" and req.headers["linkedin-version"] == "202510"
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:99"})

    _, rec = run_single(
        {"type": "action.social_post", "credentials": {"default": "li"},
         "parameters": {"text": "Hello", "dry_run": False}},
        handler=handler, creds={"li": {"access_token": "tok-abc", "author_urn": "urn:li:person:1"}},
    )
    assert rec.output["post_id"] == "urn:li:share:99"
