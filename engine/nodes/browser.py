"""Browser automation node (Playwright).

Defaults to the Microsoft Edge that ships with Windows (``browser: msedge``), so nothing
extra needs downloading. ``chrome`` uses an installed Google Chrome; ``chromium`` /
``firefox`` / ``webkit`` need ``playwright install <name>`` once.

Set ``profile_dir`` to keep cookies/logins between runs (log in once with headless=false).
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..errors import NodeExecutionError, NonRetryableError
from .base import BaseNode, NodeContext
from .registry import register_node

StepAction = Literal[
    "goto", "click", "fill", "type", "press", "select", "check", "uncheck", "hover",
    "wait_for", "wait", "extract_text", "extract_all_text", "extract_attribute", "extract_html",
    "screenshot", "evaluate",
]

_REQUIRED: dict[str, tuple[str, ...]] = {
    "goto": ("url",),
    "click": ("selector",), "check": ("selector",), "uncheck": ("selector",), "hover": ("selector",),
    "fill": ("selector", "value"), "type": ("selector", "value"), "select": ("selector", "value"),
    "press": ("value",),
    "wait_for": ("selector",), "wait": ("seconds",),
    "extract_text": ("selector", "name"), "extract_all_text": ("selector", "name"),
    "extract_html": ("selector", "name"), "extract_attribute": ("selector", "value", "name"),
    "screenshot": (), "evaluate": ("value",),
}


class BrowserStep(BaseModel):
    """One action. ``value`` is the text to fill/type, the key to press, the option to
    select, the attribute to read, or the JavaScript to evaluate."""

    model_config = ConfigDict(extra="forbid")
    action: StepAction
    selector: str | None = None  # CSS, text=..., role=..., xpath=... (Playwright selectors)
    url: str | None = None
    value: str | None = None
    name: str | None = None  # output key for extract_* / evaluate / screenshot
    seconds: float | None = Field(default=None, ge=0, le=600)
    timeout_ms: int = Field(default=15_000, ge=0, le=600_000)
    full_page: bool = False

    @model_validator(mode="after")
    def _required(self) -> BrowserStep:
        missing = [f for f in _REQUIRED[self.action] if getattr(self, f) in (None, "")]
        if missing:
            raise ValueError(f"step '{self.action}' requires {', '.join(missing)}")
        return self


@register_node
class BrowserNode(BaseNode):
    type = "action.browser"
    display_name = "Browser Automation"
    category = "action"
    description = (
        "Drive a real browser through a list of steps (goto, click, fill, extract_text, "
        "screenshot...). Output: {url, title, data, screenshots}."
    )

    class Parameters(BaseModel):
        model_config = ConfigDict(extra="forbid")
        browser: Literal["msedge", "chrome", "chromium", "firefox", "webkit"] = "msedge"
        headless: bool = True
        profile_dir: str | None = None
        steps: list[BrowserStep] = Field(min_length=1)
        viewport_width: int = Field(default=1280, ge=200, le=7680)
        viewport_height: int = Field(default=800, ge=200, le=4320)
        screenshot_dir: str | None = None

    async def execute(self, ctx: NodeContext, params: Parameters) -> dict[str, Any]:
        try:
            from playwright.async_api import Error as PlaywrightError
            from playwright.async_api import TimeoutError as PlaywrightTimeout
            from playwright.async_api import async_playwright
        except ImportError:
            raise NonRetryableError("browser automation needs Playwright: pip install playwright") from None

        shots_dir = Path(params.screenshot_dir or Path(tempfile.gettempdir()) / "automation-screenshots")
        data: dict[str, Any] = {}
        screenshots: list[str] = []
        viewport = {"width": params.viewport_width, "height": params.viewport_height}
        channel = params.browser if params.browser in ("msedge", "chrome") else None

        async with async_playwright() as pw:
            engine = {"firefox": pw.firefox, "webkit": pw.webkit}.get(params.browser, pw.chromium)
            browser = None
            try:
                if params.profile_dir:
                    context = await engine.launch_persistent_context(
                        params.profile_dir, headless=params.headless, channel=channel, viewport=viewport)
                    page = context.pages[0] if context.pages else await context.new_page()
                else:
                    browser = await engine.launch(headless=params.headless, channel=channel)
                    context = await browser.new_context(viewport=viewport)
                    page = await context.new_page()
            except PlaywrightError as exc:
                hint = f" (try: playwright install {params.browser})" if "Executable doesn't exist" in str(exc) else ""
                raise NonRetryableError(f"cannot start {params.browser}{hint}: {str(exc).splitlines()[0]}") from None

            try:
                for index, step in enumerate(params.steps, start=1):
                    ctx.debug(f"step {index}: {step.action} {step.selector or step.url or ''}".rstrip())
                    try:
                        await _run_step(page, step, data, screenshots, shots_dir)
                    except PlaywrightTimeout:
                        raise NodeExecutionError(
                            f"step {index} ({step.action} {step.selector or step.url}) timed out "
                            f"after {step.timeout_ms} ms") from None
                    except PlaywrightError as exc:
                        raise NodeExecutionError(f"step {index} ({step.action}) failed: {str(exc).splitlines()[0]}") from None
                result = {"url": page.url, "title": await page.title(), "data": data, "screenshots": screenshots}
            finally:
                await context.close()
                if browser is not None:
                    await browser.close()

        ctx.info(f"completed {len(params.steps)} browser step(s) on {result['url']}")
        return result


async def _run_step(page: Any, step: BrowserStep, data: dict[str, Any], shots: list[str], shots_dir: Path) -> None:
    t = step.timeout_ms
    match step.action:
        case "goto":
            await page.goto(step.url, timeout=t, wait_until="domcontentloaded")
        case "click":
            await page.click(step.selector, timeout=t)
        case "fill":
            await page.fill(step.selector, step.value, timeout=t)
        case "type":
            await page.locator(step.selector).press_sequentially(step.value, delay=30, timeout=t)
        case "press":
            if step.selector:
                await page.press(step.selector, step.value, timeout=t)
            else:
                await page.keyboard.press(step.value)
        case "select":
            await page.select_option(step.selector, step.value, timeout=t)
        case "check":
            await page.check(step.selector, timeout=t)
        case "uncheck":
            await page.uncheck(step.selector, timeout=t)
        case "hover":
            await page.hover(step.selector, timeout=t)
        case "wait_for":
            await page.wait_for_selector(step.selector, timeout=t)
        case "wait":
            await asyncio.sleep(step.seconds or 0)
        case "extract_text":
            data[step.name] = (await page.locator(step.selector).first.inner_text(timeout=t)).strip()
        case "extract_all_text":
            data[step.name] = [s.strip() for s in await page.locator(step.selector).all_inner_texts()]
        case "extract_html":
            data[step.name] = await page.locator(step.selector).first.inner_html(timeout=t)
        case "extract_attribute":
            data[step.name] = await page.locator(step.selector).first.get_attribute(step.value, timeout=t)
        case "screenshot":
            shots_dir.mkdir(parents=True, exist_ok=True)
            path = shots_dir / f"{step.name or 'page'}-{time.strftime('%Y%m%d-%H%M%S')}-{len(shots)}.png"
            if step.selector:
                await page.locator(step.selector).first.screenshot(path=str(path), timeout=t)
            else:
                await page.screenshot(path=str(path), full_page=step.full_page, timeout=t)
            shots.append(str(path))
            if step.name:
                data[step.name] = str(path)
        case "evaluate":
            value = await page.evaluate(step.value)
            if step.name:
                data[step.name] = value
