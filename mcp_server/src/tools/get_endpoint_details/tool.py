"""get_endpoint_details: detailed information about an endpoint."""

from __future__ import annotations

import time
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from context import AppContext, get_app_context
from filters import quote_filter_value, validate_endpoint_name
from tools._hints import read_only

# Endpoint name -> (resolved_at_monotonic, agentGuid). The name->GUID mapping is
# stable, so caching it removes one API round-trip per call within the TTL.
_GUID_CACHE: dict[str, tuple[float, str]] = {}
_GUID_TTL_SECONDS = 300.0


async def _resolve_agent_guid(app: AppContext, endpoint_name: str) -> str:
    """Resolve an endpoint name to its agentGuid (cached for a short TTL)."""
    now = time.monotonic()
    cached = _GUID_CACHE.get(endpoint_name)
    if cached is not None and now - cached[0] < _GUID_TTL_SECONDS:
        return cached[1]

    data = await app.vision_one.get(
        "/v3.0/endpointSecurity/endpoints",
        extra_headers={"TMV1-Filter": f"endpointName eq {quote_filter_value(endpoint_name)}"},
    )
    items = (data or {}).get("items") or []
    if not items or "agentGuid" not in items[0]:
        raise ToolError(f"Endpoint '{endpoint_name}' was not found.")

    agent_guid = items[0]["agentGuid"]
    _GUID_CACHE[endpoint_name] = (now, agent_guid)
    return agent_guid


def register(mcp: FastMCP) -> None:

    @mcp.tool(**read_only("endpoints"))
    async def get_endpoint_details(ctx: Context, endpoint_name: str) -> dict[str, Any]:
        """
        Return detailed information about an endpoint.

        Returns the raw Vision One payload on purpose (full endpoint detail). To
        slim it down, define a projection model (see tools/README.md).

        Args:
            endpoint_name: Endpoint name (e.g. 'EC2-AMAZ').
        """
        app = get_app_context(ctx)
        endpoint_name = validate_endpoint_name(endpoint_name)
        agent_guid = await _resolve_agent_guid(app, endpoint_name)
        return await app.vision_one.get(f"/v3.0/endpointSecurity/endpoints/{agent_guid}")
