"""Long-running trigger listeners. ``TriggerManager`` is imported lazily because the node
definitions import ``engine.triggers.cron`` before the engine core is loaded."""

from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    if name in ("TriggerManager", "LISTENERS"):
        from . import manager

        return getattr(manager, name)
    if name in ("TriggerError", "TriggerListener"):
        from . import base

        return getattr(base, name)
    raise AttributeError(name)
