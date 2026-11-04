"""Start the background service at Windows login (HKCU Run key: per-user, no admin needed)."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

from .paths import service_command

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "AutomationStudio"


def _command_line(value_name: str = VALUE_NAME) -> str:
    return subprocess.list2cmdline(service_command())


def status(value_name: str = VALUE_NAME) -> dict[str, Any]:
    expected = _command_line(value_name)
    if sys.platform != "win32":
        return {"supported": False, "enabled": False, "command": None, "expected": expected}
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            current, _ = winreg.QueryValueEx(key, value_name)
    except FileNotFoundError:
        current = None
    return {
        "supported": True,
        "enabled": current is not None,
        # false if the app/venv moved since enabling. Quotes are ignored so a value written by
        # the installer (always quoted) matches one written here (quoted only when needed).
        "up_to_date": current is not None and current.replace('"', "") == expected.replace('"', ""),
        "command": current,
        "expected": expected,
    }


def enable(value_name: str = VALUE_NAME) -> dict[str, Any]:
    if sys.platform != "win32":
        raise RuntimeError("autostart is only supported on Windows")
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, _command_line(value_name))
    return status(value_name)


def disable(value_name: str = VALUE_NAME) -> dict[str, Any]:
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, value_name)
        except FileNotFoundError:
            pass
    return status(value_name)
