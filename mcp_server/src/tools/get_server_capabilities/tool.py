"""get_server_capabilities: report configured integrations and active tools."""

from __future__ import annotations

from fastmcp import Context, FastMCP

from approval import client_supports_elicitation
from capabilities import CAPABILITIES
from config import Settings
from context import get_app_context
from tools._hints import meta_read

from .models import ContainmentStatus, IntegrationStatus, ServerCapabilities


def _containment_status(settings: Settings, can_elicit: bool) -> ContainmentStatus:
    """Describe who will approve destructive actions, before any are attempted."""
    if not settings.enable_destructive:
        return ContainmentStatus(
            destructive_tools_enabled=False,
            approval_channel="unavailable",
            detail=(
                "Containment tools are not exposed (MCP_ENABLE_DESTRUCTIVE is false). Do not "
                "plan response actions: report to the human that containment is disabled."
            ),
        )
    if can_elicit:
        return ContainmentStatus(
            destructive_tools_enabled=True,
            approval_channel="server_elicitation",
            detail="The server will ask the human to approve each destructive action.",
        )
    if settings.require_approval:
        return ContainmentStatus(
            destructive_tools_enabled=True,
            approval_channel="unavailable",
            detail=(
                "This client cannot be asked for approval (no elicitation support) and "
                "MCP_REQUIRE_APPROVAL is true, so every destructive call will be REFUSED."
            ),
        )
    return ContainmentStatus(
        destructive_tools_enabled=True,
        approval_channel="client_gate",
        detail=(
            "This client cannot be asked by the server, so approval is delegated to it. YOU "
            "must obtain explicit human authorization before requesting any response action."
        ),
    )


def register(mcp: FastMCP) -> None:

    @mcp.tool(**meta_read())
    async def get_server_capabilities(ctx: Context) -> ServerCapabilities:
        """
        Report which integrations are configured and which tools are active.

        Use this to discover the server's current capabilities before planning
        actions — inactive integrations list the env var(s) needed to enable them.
        """
        app = get_app_context(ctx)
        settings = app.settings

        integrations: list[IntegrationStatus] = []
        for cap in CAPABILITIES:
            configured = cap.is_configured(settings)
            integrations.append(
                IntegrationStatus(
                    name=cap.name,
                    status="active" if configured else "inactive",
                    required_env=list(cap.env_vars),
                    categories=sorted(cap.tags),
                    reason=None if configured else f"Set {' + '.join(cap.env_vars)} to enable.",
                )
            )

        active_tools = sorted(t.name for t in await ctx.fastmcp.list_tools())
        return ServerCapabilities(
            transport=settings.transport,
            http2=settings.enable_http2,
            operator_id=settings.operator_id,
            integrations=integrations,
            containment=_containment_status(settings, client_supports_elicitation(ctx)),
            active_tools=active_tools,
            active_tool_count=len(active_tools),
        )
