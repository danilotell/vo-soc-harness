"""get_alert_details: full details for a specific Workbench alert."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from context import get_app_context
from filters import validate_alert_id
from tools._hints import read_only


def register(mcp: FastMCP) -> None:

    @mcp.tool(**read_only("alerts"))
    async def get_alert_details(ctx: Context, alert_id: str) -> dict[str, Any]:
        """
        Return full details for a specific Workbench alert.

        Returns the raw Vision One payload on purpose: alert triage needs the
        complete structure (indicators, impact scope, highlighted objects). To
        slim it down, define a projection model (see tools/README.md).

        Args:
            alert_id: Workbench alert ID (e.g. 'WB-00000-00000000-00000').
        """
        app = get_app_context(ctx)
        alert_id = validate_alert_id(alert_id)
        return await app.vision_one.get(f"/v3.0/workbench/alerts/{alert_id}")
