"""add_to_block_list: add an IOC to the Vision One block list (DESTRUCTIVE)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from approval import require_human_approval
from audit import audited, log_action
from context import get_app_context
from filters import validate_ioc
from tools._hints import destructive

from .models import IocType


def register(mcp: FastMCP) -> None:

    @mcp.tool(**destructive("response"))
    async def add_to_block_list(
        ctx: Context, ioc: str, ioc_type: IocType, description: str, dry_run: bool = False
    ) -> Any:
        """
        Add an Indicator of Compromise to the Vision One block list. DESTRUCTIVE.

        A human is asked to approve before anything happens; the action is
        refused if approval cannot be obtained. Use dry_run to preview safely.

        Args:
            ioc: The indicator value (IP, domain, hash, URL, or email address).
            ioc_type: One of: ip, domain, fileSha1, fileSha256, senderMailAddress, url.
            description: Human-readable description of the IOC.
            dry_run: If true, validate and report what WOULD happen without
                blocking anything. Use it to preview the action safely.
        """
        app = get_app_context(ctx)
        ioc = validate_ioc(ioc)
        if not description or not description.strip():
            raise ToolError("A description is required for audit purposes.")

        details = {"ioc_type": ioc_type, "description": description}
        if dry_run:
            log_action("add_to_block_list", target=ioc, status="dry_run", details=details)
            return {
                "dry_run": True,
                "would_block": ioc,
                "ioc_type": ioc_type,
                "description": description,
            }

        # Raises unless a human explicitly approves — nothing below runs otherwise.
        await require_human_approval(
            ctx, action="add_to_block_list", target=ioc, reason=description
        )

        async with audited("add_to_block_list", target=ioc, details=details):
            result = await app.vision_one.post(
                "/v3.0/response/suspiciousObjects",
                [{ioc_type: ioc, "description": description}],
            )
        return result
