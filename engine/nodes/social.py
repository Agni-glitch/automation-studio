"""Social Post node. LinkedIn via the Posts API; dry_run (default) only previews."""

from __future__ import annotations

from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from ..errors import NodeExecutionError, NonRetryableError
from ._http import http_client
from .base import BaseNode, NodeContext
from .registry import register_node

LINKEDIN_POSTS_URL = "https://api.linkedin.com/rest/posts"


@register_node
class SocialPostNode(BaseNode):
    type = "action.social_post"
    display_name = "Social Post"
    category = "action"
    description = "Publish a text post (LinkedIn). Defaults to dry run."
    credential_slots = {
        "default": "LinkedIn: {access_token (w_member_social scope), author_urn e.g. urn:li:person:abc123}",
    }

    class Parameters(BaseModel):
        model_config = ConfigDict(extra="forbid")
        platform: Literal["linkedin"] = "linkedin"
        text: str = Field(min_length=1, max_length=3000)
        visibility: Literal["PUBLIC", "CONNECTIONS"] = "PUBLIC"
        dry_run: bool = True
        # LinkedIn versions expire roughly a year after release. Update this when calls return 426.
        api_version: str = Field(default="202510", pattern=r"^\d{6}$")

    async def execute(self, ctx: NodeContext, params: Parameters) -> dict[str, Any]:
        if params.dry_run:
            ctx.info(f"dry run: {params.platform} post ({len(params.text)} chars) not published")
            return {"posted": False, "dry_run": True, "platform": params.platform, "text": params.text}

        cred = await ctx.get_credential()
        token, author = cred.get("access_token"), cred.get("author_urn")
        if not token or not author:
            raise NonRetryableError("LinkedIn credential needs 'access_token' and 'author_urn'")

        body = {
            "author": author,
            "commentary": params.text,
            "visibility": params.visibility,
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "LinkedIn-Version": params.api_version,
            "X-Restli-Protocol-Version": "2.0.0",
        }
        async with http_client(ctx) as client:
            try:
                resp = await client.post(LINKEDIN_POSTS_URL, json=body, headers=headers, timeout=30)
            except httpx.TransportError as exc:
                raise NodeExecutionError(f"LinkedIn unreachable: {exc!r}") from exc
        if resp.status_code >= 400:
            err = NodeExecutionError if resp.status_code == 429 or resp.status_code >= 500 else NonRetryableError
            raise err(f"LinkedIn API error {resp.status_code}: {resp.text[:300]}")
        post_id = resp.headers.get("x-restli-id")
        ctx.info(f"published LinkedIn post {post_id}")
        return {"posted": True, "dry_run": False, "platform": "linkedin", "post_id": post_id}
