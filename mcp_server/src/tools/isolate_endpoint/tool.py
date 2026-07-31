"""isolate_endpoint: isolate an endpoint from the network (DESTRUCTIVE)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from approval import require_human_approval
from audit import audited, log_action
from context import get_app_context
from filters import validate_endpoint_name
from tools._hints import destructive


def register(mcp: FastMCP) -> None:

    @mcp.tool(**destructive("response"))
    async def isolate_endpoint(
        ctx: Context, endpoint_name: str, description: str, dry_run: bool = False
    ) -> Any:
        """
        Isolate an endpoint from the network. DESTRUCTIVE — requires human approval.

        A human is asked to approve before anything happens; the action is
        refused if approval cannot be obtained. Use dry_run to preview safely.

        Args:
            endpoint_name: Endpoint name (e.g. 'EC2-AMAZ').
            description: Reason for isolation (used for audit purposes).
            dry_run: If true, validate and report what WOULD happen without
                isolating anything. Use it to preview the action safely.
        """
        app = get_app_context(ctx)
        endpoint_name = validate_endpoint_name(endpoint_name)
        if not description or not description.strip():
            raise ToolError("A description is required for audit purposes.")

        details = {"description": description}
        if dry_run:
            log_action("isolate_endpoint", target=endpoint_name, status="dry_run", details=details)
            return {"dry_run": True, "would_isolate": endpoint_name, "description": description}

        # Raises unless a human explicitly approves — nothing below runs otherwise.
        await require_human_approval(
            ctx, action="isolate_endpoint", target=endpoint_name, reason=description
        )

        async with audited("isolate_endpoint", target=endpoint_name, details=details):
            result = await app.vision_one.post(
                "/v3.0/response/endpoints/isolate",
                [{"endpointName": endpoint_name, "description": description}],
            )
        return result
