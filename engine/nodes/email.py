"""Email node (SMTP). Works with Gmail/Outlook via SMTP + an app password."""

from __future__ import annotations

import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..errors import NodeExecutionError, NonRetryableError
from .base import BaseNode, NodeContext
from .registry import register_node

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _address_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    items = [p.strip() for p in value.split(",")] if isinstance(value, str) else [str(v).strip() for v in value]
    items = [i for i in items if i]
    for item in items:
        if not _EMAIL.match(item):
            raise ValueError(f"invalid email address {item!r}")
    return items


@register_node
class EmailActionNode(BaseNode):
    type = "action.email"
    display_name = "Send Email"
    category = "action"
    description = "Send an email over SMTP. dry_run builds the message without sending."
    credential_slots = {
        "default": "{host, port, username, password, security: starttls|ssl|none, from_address}",
    }

    class Parameters(BaseModel):
        model_config = ConfigDict(extra="forbid")
        to: list[str]
        cc: list[str] = Field(default_factory=list)
        bcc: list[str] = Field(default_factory=list)
        subject: str
        body: str
        html: bool = False
        from_address: str | None = None
        reply_to: str | None = None
        dry_run: bool = False

        @field_validator("to", "cc", "bcc", mode="before")
        @classmethod
        def _parse_addresses(cls, v: Any) -> list[str]:
            return _address_list(v)

        @field_validator("to")
        @classmethod
        def _has_recipient(cls, v: list[str]) -> list[str]:
            if not v:
                raise ValueError("at least one recipient is required")
            return v

    async def execute(self, ctx: NodeContext, params: Parameters) -> dict[str, Any]:
        cred: dict[str, Any] = {}
        if not params.dry_run:
            cred = await ctx.get_credential()
            for key in ("host", "username", "password"):
                if not cred.get(key):
                    raise NonRetryableError(f"SMTP credential is missing '{key}'")

        sender = params.from_address or cred.get("from_address") or cred.get("username") or "dry-run@localhost"
        msg = _build_message(params, sender)
        summary = {
            "message_id": msg["Message-ID"],
            "from": sender,
            "to": params.to,
            "cc": params.cc,
            "subject": params.subject,
        }
        if params.dry_run:
            ctx.info(f"dry run: email to {', '.join(params.to)} not sent")
            return {"sent": False, "dry_run": True, **summary, "body": params.body}

        await ctx.run_blocking(_send, msg, cred, params.to + params.cc + params.bcc)
        ctx.info(f"sent email to {', '.join(params.to)}")
        return {"sent": True, "dry_run": False, **summary}


def _build_message(params: EmailActionNode.Parameters, sender: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(params.to)
    if params.cc:
        msg["Cc"] = ", ".join(params.cc)
    if params.reply_to:
        msg["Reply-To"] = params.reply_to
    msg["Subject"] = params.subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1])
    if params.html:
        msg.set_content(re.sub(r"<[^>]+>", "", params.body))
        msg.add_alternative(params.body, subtype="html")
    else:
        msg.set_content(params.body)
    return msg  # Bcc intentionally not a header


def _send(msg: EmailMessage, cred: dict[str, Any], recipients: list[str]) -> None:
    host = cred["host"]
    security = cred.get("security", "starttls")
    port = int(cred.get("port") or (465 if security == "ssl" else 587))
    context = ssl.create_default_context()
    try:
        if security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=30, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
        with server:
            if security == "starttls":
                server.starttls(context=context)
            server.login(cred["username"], cred["password"])
            server.send_message(msg, to_addrs=recipients)
    except (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused) as exc:
        raise NonRetryableError(f"SMTP rejected the message: {exc}") from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise NodeExecutionError(f"SMTP error talking to {host}:{port}: {exc!r}") from exc
