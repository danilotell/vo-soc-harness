"""get_alert_list: summarized list of open Workbench alerts."""

from __future__ import annotations

from typing import Annotated

from fastmcp import Context, FastMCP
from pydantic import Field

from _dates import utc_range
from context import get_app_context
from tools._hints import read_only

from .models import AlertSummary


def register(mcp: FastMCP) -> None:

    @mcp.tool(**read_only("alerts"))
    async def get_alert_list(
        ctx: Context,
        days: Annotated[int, Field(ge=1, le=365)] = 1,
        limit: Annotated[int, Field(ge=1, le=500)] = 50,
    ) -> list[AlertSummary]:
        """
        Return a summarized list of open Workbench alerts created in the last N days.

        Args:
            days: Number of past days to query (1-365, default 1 — today's shift).
                Widen it explicitly when you need history.
            limit: Maximum number of alerts to return (1-500, default 50). Newest
                first, so a small limit returns the most recent alerts.
        """
        app = get_app_context(ctx)
        start, end = utc_range(days)
        items = await app.vision_one.paginate(
            "/v3.0/workbench/alerts",
            params={
                "startDateTime": start,
                "endDateTime": end,
                "dateTimeTarget": "createdDateTime",
                "orderBy": "createdDateTime desc",
            },
            extra_headers={"TMV1-Filter": "status eq 'Open'"},
            max_items=limit,
        )
        return [AlertSummary.from_api(item) for item in items]
