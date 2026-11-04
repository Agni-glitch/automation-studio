"""Trigger nodes.

At execution time a trigger node simply emits the payload that started the run (or its
``sample_data`` when you run the workflow by hand). The *listening* side lives in
``engine/triggers/`` and is driven by ``TriggerManager`` (``python main.py serve``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..triggers.cron import CronExpression
from .base import BaseNode, NodeContext
from .registry import register_node


class TriggerParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_data: Any = None  # used when the workflow is run manually


class TriggerNode(BaseNode):
    category = "trigger"
    is_trigger = True
    Parameters = TriggerParameters

    async def execute(self, ctx: NodeContext, params: Any) -> Any:
        if ctx.trigger_data is not None:
            return ctx.trigger_data
        sample = getattr(params, "sample_data", None)
        return sample if sample is not None else {}


@register_node
class ManualTriggerNode(TriggerNode):
    type = "trigger.manual"
    display_name = "Manual Trigger"
    description = "Starts the workflow when you click Run. Uses sample data if none is supplied."


@register_node
class WebhookTriggerNode(TriggerNode):
    type = "trigger.webhook"
    display_name = "Webhook"
    description = (
        "Starts the workflow on an HTTP request to http://127.0.0.1:<port>/webhook/<path>. "
        "Output: {method, path, query, headers, body, client}."
    )
    credential_slots = {"default": "{token}: callers must send it in the auth header"}

    class Parameters(TriggerParameters):
        path: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_\-/.]+$")
        method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "POST"
        auth: Literal["none", "header"] = "none"
        auth_header: str = "X-Webhook-Token"
        # immediate: reply 202 {execution_id} at once. wait: reply with the workflow's output.
        response_mode: Literal["immediate", "wait"] = "immediate"
        response_node: str | None = None  # node whose output is returned in wait mode
        wait_timeout: float = Field(default=30, gt=0, le=600)
        # Calls arriving through the public tunnel are refused unless token auth is on or this is true.
        allow_public: bool = False

        @field_validator("path")
        @classmethod
        def _normalize(cls, v: str) -> str:
            return v.strip("/")


_TEMP_PATTERNS = ["~$*", "*.tmp", "*.crdownload", "*.part", "*.partial", ".~lock*", "desktop.ini", "Thumbs.db"]


@register_node
class FileTriggerNode(TriggerNode):
    type = "trigger.file"
    display_name = "Folder Watcher"
    description = (
        "Starts the workflow when files appear/change in a folder. Waits until a file stops "
        "growing before firing. Output: {event, path, name, stem, extension, directory, size, src_path}."
    )

    class Parameters(TriggerParameters):
        directory: str = Field(min_length=1)
        patterns: list[str] = Field(default_factory=lambda: ["*"])
        events: list[Literal["created", "modified", "deleted", "moved"]] = Field(default_factory=lambda: ["created"])
        recursive: bool = False
        settle_seconds: float = Field(default=1.0, ge=0, le=60)
        ignore_patterns: list[str] = Field(default_factory=lambda: list(_TEMP_PATTERNS))

        @field_validator("events")
        @classmethod
        def _non_empty(cls, v: list[str]) -> list[str]:
            if not v:
                raise ValueError("select at least one event")
            return v


@register_node
class ScheduleTriggerNode(TriggerNode):
    type = "trigger.schedule"
    display_name = "Schedule"
    description = (
        "Starts the workflow on a cron schedule (local time) or a fixed interval. "
        "Runs missed while the app was closed are not caught up. Output: {scheduled_for, fired_at}."
    )

    class Parameters(TriggerParameters):
        mode: Literal["cron", "interval"] = "cron"
        cron: str | None = None  # e.g. "0 9 * * MON-FRI"
        every_seconds: float | None = Field(default=None, ge=0.1)
        run_on_start: bool = False
        skip_if_running: bool = True

        @model_validator(mode="after")
        def _check_mode(self) -> ScheduleTriggerNode.Parameters:
            if self.mode == "cron":
                if not self.cron:
                    raise ValueError("cron mode requires 'cron'")
                CronExpression(self.cron).next_after(datetime.now())  # also rejects never-firing dates
            elif self.every_seconds is None:
                raise ValueError("interval mode requires 'every_seconds'")
            return self
