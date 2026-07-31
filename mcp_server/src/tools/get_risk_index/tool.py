"""get_risk_index: organization security risk index from Vision One ASRM."""

from __future__ import annotations

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from context import get_app_context
from tools._hints import read_only

from .models import RiskIndex


def register(mcp: FastMCP) -> None:

    @mcp.tool(**read_only("alerts"))
    async def get_risk_index(ctx: Context) -> RiskIndex:
        """Return the organization's current security risk index from Vision One ASRM."""
        app = get_app_context(ctx)
        data = await app.vision_one.get("/v3.0/asrm/securityPosture")
        if not data or "riskIndex" not in data:
            raise ToolError("Vision One returned no risk index.")
        return RiskIndex(riskIndex=data["riskIndex"])
