"""get_observed_attack_techniques: OAT events for an endpoint and risk level."""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import Context, FastMCP
from pydantic import Field

from _dates import utc_range
from context import get_app_context
from filters import quote_filter_value, validate_endpoint_name
from tools._hints import read_only

from .models import RiskLevel


def register(mcp: FastMCP) -> None:

    @mcp.tool(**read_only("endpoints"))
    async def get_observed_attack_techniques(
        ctx: Context,
        endpoint_name: str,
        risk_level: RiskLevel,
        days: Annotated[int, Field(ge=1, le=365)] = 30,
    ) -> dict[str, Any]:
        """
        Return Observed Attack Techniques (OAT) events for an endpoint and risk level.

        Returns the raw Vision One payload on purpose (full detection detail). To
        slim it down, define a projection model (see tools/README.md).

        Args:
            endpoint_name: Endpoint name (e.g. 'EC2-AMAZ').
            risk_level: One of info, low, medium, high, critical.
            days: Lookback window in days (1-365, default 30).
        """
        app = get_app_context(ctx)
        endpoint_name = validate_endpoint_name(endpoint_name)
        start, end = utc_range(days)
        return await app.vision_one.get(
            "/v3.0/oat/detections",
            params={"detectedStartDateTime": start, "detectedEndDateTime": end},
            extra_headers={
                "TMV1-Filter": (
                    f"(riskLevel eq {quote_filter_value(risk_level)}) and "
                    f"(endpointName eq {quote_filter_value(endpoint_name)})"
                )
            },
        )
