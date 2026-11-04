import asyncio
import os
import sys
import types
from pathlib import Path

import pytest

from engine import NodeStatus, WorkflowEngine, WorkflowValidationError

EDGE = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"


def run_node(node: dict):
    result = asyncio.run(WorkflowEngine().run({"name": "t", "nodes": [{"id": "n", **node}]}))
    return result.nodes["n"]


# ------------------------------------------------------------------ browser


def test_browser_step_validation():
    with pytest.raises(WorkflowValidationError, match="requires selector, value"):
        WorkflowEngine().validate({"name": "t", "nodes": [
            {"id": "b", "type": "action.browser", "parameters": {"steps": [{"action": "fill"}]}}]})


@pytest.mark.skipif(not EDGE.exists(), reason="Microsoft Edge not installed")
def test_browser_drives_real_edge(tmp_path):
    page = tmp_path / "form.html"
    page.write_text("""<!doctype html><title>Demo form</title>
        <input id="name"><select id="role"><option>dev</option><option>ops</option></select>
        <button onclick="document.getElementById('out').textContent =
            'Hello ' + document.getElementById('name').value + ' (' + document.getElementById('role').value + ')'">Go</button>
        <p id="out"></p><a class="job" href="/1">Job A</a><a class="job" href="/2">Job B</a>""", encoding="utf-8")

    rec = run_node({"type": "action.browser", "timeout_seconds": 60, "parameters": {
        "screenshot_dir": str(tmp_path / "shots"),
        "steps": [
            {"action": "goto", "url": page.as_uri()},
            {"action": "fill", "selector": "#name", "value": "Ada"},
            {"action": "select", "selector": "#role", "value": "ops"},
            {"action": "click", "selector": "text=Go"},
            {"action": "wait_for", "selector": "#out:has-text('Hello')"},
            {"action": "extract_text", "selector": "#out", "name": "greeting"},
            {"action": "extract_all_text", "selector": "a.job", "name": "jobs"},
            {"action": "extract_attribute", "selector": "a.job", "value": "href", "name": "first_href"},
            {"action": "evaluate", "value": "document.title.length", "name": "title_len"},
            {"action": "screenshot", "name": "final"},
        ]}})
    assert rec.status is NodeStatus.SUCCESS, rec.error
    out = rec.output
    assert out["title"] == "Demo form"
    assert out["data"]["greeting"] == "Hello Ada (ops)"
    assert out["data"]["jobs"] == ["Job A", "Job B"] and out["data"]["first_href"] == "/1"
    assert out["data"]["title_len"] == 9
    assert Path(out["screenshots"][0]).stat().st_size > 1000


@pytest.mark.skipif(not EDGE.exists(), reason="Microsoft Edge not installed")
def test_browser_timeout_is_reported_per_step(tmp_path):
    page = tmp_path / "empty.html"
    page.write_text("<p>nothing here</p>")
    rec = run_node({"type": "action.browser", "parameters": {"steps": [
        {"action": "goto", "url": page.as_uri()},
        {"action": "click", "selector": "#missing", "timeout_ms": 300}]}})
    assert rec.status is NodeStatus.FAILED and "step 2 (click #missing) timed out" in rec.error.message


# ------------------------------------------------------------------ desktop (fake pyautogui: never touches the real mouse)


@pytest.fixture
def fake_gui(monkeypatch):
    calls = []

    class FailSafeException(Exception):
        pass

    class Window:
        title, isMinimized = "Untitled - Notepad", True
        def restore(self): calls.append(("restore",))
        def activate(self): calls.append(("activate",))

    gui = types.ModuleType("pyautogui")
    gui.FailSafeException = FailSafeException
    for name in ("hotkey", "press", "write", "click", "moveTo", "scroll"):
        setattr(gui, name, lambda *a, _n=name, **k: calls.append((_n, a, k)))
    gui.screenshot = lambda path: (Path(path).write_bytes(b"png"), calls.append(("screenshot", path)))
    gui.locateCenterOnScreen = lambda image, **k: (100, 200) if "button" in image else None
    gui.getWindowsWithTitle = lambda t: [Window()] if "Notepad" in t else []
    clip = types.ModuleType("pyperclip")
    clip.copy = lambda text: calls.append(("clipboard", text))
    monkeypatch.setitem(sys.modules, "pyautogui", gui)
    monkeypatch.setitem(sys.modules, "pyperclip", clip)
    monkeypatch.setattr(os, "startfile", lambda target: calls.append(("open", target)), raising=False)
    return calls


def test_desktop_steps(fake_gui, tmp_path):
    rec = run_node({"type": "action.desktop", "parameters": {
        "pause_between_actions": 0, "screenshot_dir": str(tmp_path), "steps": [
            {"action": "open", "target": "notepad.exe"},
            {"action": "activate_window", "target": "Notepad", "name": "window"},
            {"action": "paste", "text": "Grüße"},
            {"action": "hotkey", "keys": ["ctrl", "s"]},
            {"action": "click", "image": "save_button.png"},
            {"action": "locate_image", "image": "missing.png", "name": "where"},
            {"action": "screenshot", "name": "after"},
        ]}})
    assert rec.status is NodeStatus.SUCCESS, rec.error
    kinds = [c[0] for c in fake_gui]
    assert kinds == ["open", "restore", "activate", "clipboard", "hotkey", "hotkey", "click", "screenshot"]
    assert fake_gui[6][2]["x"] == 100 and fake_gui[6][2]["y"] == 200
    assert rec.output["data"]["window"] == "Untitled - Notepad" and rec.output["data"]["where"] is None


def test_desktop_validation_and_missing_image(fake_gui):
    with pytest.raises(WorkflowValidationError, match="use 'paste'"):
        WorkflowEngine().validate({"name": "t", "nodes": [{"id": "d", "type": "action.desktop",
                                                           "parameters": {"steps": [{"action": "type", "text": "é"}]}}]})
    rec = run_node({"type": "action.desktop", "parameters": {"steps": [{"action": "click", "image": "nope.png"}]}})
    assert rec.status is NodeStatus.FAILED and "image not found" in rec.error.message
