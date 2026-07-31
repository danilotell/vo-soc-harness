"""modify_alert_status: update the status of a Workbench alert."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from audit import audited
from context import get_app_context
from filters import validate_alert_id
from tools._hints import write

from .models import AlertStatus


def register(mcp: FastMCP) -> None:

    @mcp.tool(**write("alerts", idempotent=True))
    async def modify_alert_status(ctx: Context, alert_id: str, status: AlertStatus) -> Any:
        """
        Update the status of a Workbench alert.

        Args:
            alert_id: Workbench alert ID (e.g. 'WB-00000-00000000-00000').
            status: New status — "In Progress" or "Closed".
        """
        app = get_app_context(ctx)
        alert_id = validate_alert_id(alert_id)
        async with audited("modify_alert_status", target=alert_id, details={"status": status}):
            result = await app.vision_one.patch(
                f"/v3.0/workbench/alerts/{alert_id}", {"status": status}
            )
        return result
