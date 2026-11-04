"""The desktop window's JS bridge: Export JSON saves through a native dialog."""

from __future__ import annotations

import sys
import types

import pytest

from desktop.app_window import DesktopBridge


def _fake_webview(monkeypatch: pytest.MonkeyPatch, chosen: object) -> list[dict]:
    calls: list[dict] = []

    class Window:
        def create_file_dialog(self, dialog_type, **kwargs):
            calls.append({"type": dialog_type, **kwargs})
            return chosen

    module = types.SimpleNamespace(windows=[Window()], FileDialog=types.SimpleNamespace(SAVE="save"))
    monkeypatch.setitem(sys.modules, "webview", module)
    return calls


def test_save_json_writes_chosen_file(tmp_path, monkeypatch):
    target = tmp_path / "flow.json"
    calls = _fake_webview(monkeypatch, str(target))
    assert DesktopBridge().save_json("My_flow.json", '{"name": "é"}') == str(target)
    assert target.read_text(encoding="utf-8") == '{"name": "é"}'
    assert calls[0]["type"] == "save" and calls[0]["save_filename"] == "My_flow.json"


def test_save_json_accepts_list_and_adds_extension(tmp_path, monkeypatch):
    _fake_webview(monkeypatch, [str(tmp_path / "flow")])
    assert DesktopBridge().save_json("x.json", "{}") == str(tmp_path / "flow.json")
    assert (tmp_path / "flow.json").read_text(encoding="utf-8") == "{}"


def test_save_json_cancelled(monkeypatch):
    _fake_webview(monkeypatch, None)
    assert DesktopBridge().save_json("x.json", "{}") is None
