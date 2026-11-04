"""Desktop automation node (PyAutoGUI): keyboard, mouse, windows, screenshots.

Needs ``pip install pyautogui`` (plus ``opencv-python`` for image ``confidence``).
Runs only in an interactive, unlocked Windows session. Move the mouse into a screen
corner to abort immediately (PyAutoGUI fail-safe). Only one desktop node runs at a time,
because two would fight over the same mouse and keyboard.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..errors import NodeExecutionError, NonRetryableError
from .base import BaseNode, NodeContext
from .registry import register_node

_DESKTOP_LOCK = threading.Lock()

DesktopAction = Literal[
    "open", "wait", "hotkey", "press", "type", "paste",
    "click", "double_click", "right_click", "move", "scroll",
    "screenshot", "activate_window", "locate_image",
]

_REQUIRED: dict[str, tuple[str, ...]] = {
    "open": ("target",), "wait": ("seconds",), "hotkey": ("keys",), "press": ("key",),
    "type": ("text",), "paste": ("text",), "move": ("x", "y"), "scroll": ("amount",),
    "activate_window": ("target",), "locate_image": ("image", "name"),
    "click": (), "double_click": (), "right_click": (), "screenshot": (),
}


class DesktopStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: DesktopAction
    target: str | None = None  # open: file/folder/URL/app; activate_window: title substring
    keys: list[str] = Field(default_factory=list)  # hotkey, e.g. ["ctrl", "s"]
    key: str | None = None  # press, e.g. "enter"
    text: str | None = None  # type (ASCII only) / paste (any text, via clipboard)
    x: int | None = None
    y: int | None = None
    image: str | None = None  # click on / locate this screenshot fragment
    confidence: float | None = Field(default=None, gt=0, le=1)
    amount: int | None = None  # scroll clicks (+up / -down)
    presses: int = Field(default=1, ge=1, le=100)
    interval: float = Field(default=0.02, ge=0, le=5)
    seconds: float | None = Field(default=None, ge=0, le=600)
    name: str | None = None  # output key

    @model_validator(mode="after")
    def _required(self) -> DesktopStep:
        missing = [f for f in _REQUIRED[self.action] if getattr(self, f) in (None, "", [])]
        if missing:
            raise ValueError(f"step '{self.action}' requires {', '.join(missing)}")
        if self.action == "type" and self.text and not self.text.isascii():
            raise ValueError("'type' only supports ASCII text; use 'paste' for other characters")
        return self


@register_node
class DesktopNode(BaseNode):
    type = "action.desktop"
    display_name = "Desktop Automation"
    category = "action"
    description = (
        "Control the Windows desktop: open apps, focus windows, type, hotkeys, click "
        "(coordinates or image), screenshots. Output: {data, screenshots}."
    )

    class Parameters(BaseModel):
        model_config = ConfigDict(extra="forbid")
        steps: list[DesktopStep] = Field(min_length=1)
        pause_between_actions: float = Field(default=0.2, ge=0, le=5)
        screenshot_dir: str | None = None

    async def execute(self, ctx: NodeContext, params: Parameters) -> dict[str, Any]:
        try:
            import pyautogui
        except ImportError:
            raise NonRetryableError("desktop automation needs PyAutoGUI: pip install pyautogui") from None

        logs: list[str] = []  # collected on the worker thread, logged afterwards
        try:
            result = await ctx.run_blocking(_run_steps, pyautogui, params, logs)
        finally:
            for line in logs:
                ctx.debug(line)
        ctx.info(f"completed {len(params.steps)} desktop step(s)")
        return result


def _run_steps(gui: Any, params: DesktopNode.Parameters, logs: list[str]) -> dict[str, Any]:
    if not _DESKTOP_LOCK.acquire(timeout=300):
        raise NodeExecutionError("another desktop automation has been running for 5 minutes")
    try:
        gui.FAILSAFE = True
        gui.PAUSE = params.pause_between_actions
        shots_dir = Path(params.screenshot_dir or Path(tempfile.gettempdir()) / "automation-screenshots")
        data: dict[str, Any] = {}
        shots: list[str] = []
        for index, step in enumerate(params.steps, start=1):
            logs.append(f"step {index}: {step.action}")
            try:
                _run_step(gui, step, data, shots, shots_dir)
            except gui.FailSafeException:
                raise NonRetryableError("aborted: mouse moved to a screen corner (fail-safe)") from None
        return {"data": data, "screenshots": shots}
    finally:
        _DESKTOP_LOCK.release()


def _locate(gui: Any, step: DesktopStep) -> tuple[int, int] | None:
    kwargs = {"confidence": step.confidence} if step.confidence else {}
    try:
        point = gui.locateCenterOnScreen(step.image, **kwargs)
    except Exception as exc:  # newer pyscreeze raises ImageNotFoundException instead of returning None
        if type(exc).__name__ == "ImageNotFoundException":
            return None
        raise
    return (int(point[0]), int(point[1])) if point is not None else None


def _run_step(gui: Any, step: DesktopStep, data: dict[str, Any], shots: list[str], shots_dir: Path) -> None:
    match step.action:
        case "open":
            os.startfile(step.target)  # type: ignore[attr-defined]  # Windows: default app for file/URL
        case "wait":
            time.sleep(step.seconds or 0)
        case "hotkey":
            gui.hotkey(*step.keys)
        case "press":
            gui.press(step.key, presses=step.presses, interval=step.interval)
        case "type":
            gui.write(step.text, interval=step.interval)
        case "paste":
            import pyperclip  # installed with pyautogui

            pyperclip.copy(step.text)
            gui.hotkey("ctrl", "v")
        case "click" | "double_click" | "right_click":
            x, y = step.x, step.y
            if step.image:
                found = _locate(gui, step)
                if found is None:
                    raise NodeExecutionError(f"image not found on screen: {step.image}")
                x, y = found
            clicks = 2 if step.action == "double_click" else step.presses
            button = "right" if step.action == "right_click" else "left"
            gui.click(x=x, y=y, clicks=clicks, interval=step.interval, button=button)
        case "move":
            gui.moveTo(step.x, step.y, duration=0.2)
        case "scroll":
            gui.scroll(step.amount, x=step.x, y=step.y)
        case "screenshot":
            shots_dir.mkdir(parents=True, exist_ok=True)
            path = shots_dir / f"{step.name or 'desktop'}-{time.strftime('%Y%m%d-%H%M%S')}-{len(shots)}.png"
            gui.screenshot(str(path))
            shots.append(str(path))
            if step.name:
                data[step.name] = str(path)
        case "activate_window":
            windows = [w for w in gui.getWindowsWithTitle(step.target) if w.title]
            if not windows:
                raise NodeExecutionError(f"no window with title containing {step.target!r}")
            window = windows[0]
            if window.isMinimized:
                window.restore()
            window.activate()
            if step.name:
                data[step.name] = window.title
        case "locate_image":
            found = _locate(gui, step)
            data[step.name] = {"x": found[0], "y": found[1]} if found else None
