"""Filesystem locations, valid both from source and from a PyInstaller build."""

from __future__ import annotations

import sys
from pathlib import Path

from database.db import default_data_dir

FROZEN = bool(getattr(sys, "frozen", False))

# Read-only bundled resources (frontend build, etc.)
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
PROJECT_DIR = Path(__file__).resolve().parent.parent  # source checkout (unused when frozen)
FRONTEND_DIST = RESOURCE_DIR / "frontend" / "dist"

DATA_DIR = default_data_dir()  # %LOCALAPPDATA%\AutomationEngine
BIN_DIR = DATA_DIR / "bin"
LOG_DIR = DATA_DIR / "logs"
TOKEN_FILE = DATA_DIR / "api.token"
SERVICE_FILE = DATA_DIR / "service.json"
LOCK_FILE = DATA_DIR / "service.lock"

DEFAULT_API_PORT = 5680
DEFAULT_WEBHOOK_PORT = 5678


BUILD_INFO = RESOURCE_DIR / "build_info.json"  # written by build/package.py


def build_info() -> dict:
    """Build-time defaults (e.g. the update source) baked into the packaged app."""
    import json

    try:
        return json.loads(BUILD_INFO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def installed_copy() -> bool:
    """True when running from the installer's folder (it leaves its uninstaller next to the
    exe); False for the portable zip, which in-app updates must not overwrite."""
    return (Path(sys.executable).parent / "unins000.exe").exists()


def _pythonw() -> str:
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    return str(pythonw if pythonw.exists() else python)


def window_command() -> list[str]:
    """Command line that opens (or focuses) the desktop window."""
    if FROZEN:
        return [str(Path(sys.executable).with_name("AutomationStudio.exe"))]
    return [_pythonw(), str(PROJECT_DIR / "main.py"), "open"]


def service_command() -> list[str]:
    """Command line that starts the background service without a console window."""
    if FROZEN:
        # Always the windowed exe: the console one (studio.exe) would open a terminal at login.
        return [str(Path(sys.executable).with_name("AutomationStudio.exe")), "serve", "--background"]
    return [_pythonw(), str(PROJECT_DIR / "main.py"), "serve", "--background"]
