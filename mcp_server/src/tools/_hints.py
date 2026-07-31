"""
How a tool declares what it does — annotations and tags in a single call.

An MCP ``annotation`` tells the *client* a tool is dangerous; a ``tag`` is what
this *server* gates on. They describe the same fact, so they are produced
together here instead of being written out twice per tool: if they could drift
apart, a containment tool could advertise itself as destructive to the client
while escaping the server's own gating.

    @mcp.tool(**destructive("response"))
    async def isolate_endpoint(...): ...

    @mcp.tool(**write("alerts", idempotent=True))
    async def modify_alert_status(...): ...

Access levels:

===============  =============================================================
``read_only``    Reads that may reach an external system (queries, lookups).
``write``        Mutations that are not destructive (notes, status, messages).
``destructive``  Containment. Clients must gate these behind human approval.
``meta_read``    Diagnostics that touch no external system.
===============  =============================================================
"""

from __future__ import annotations

from typing import Any

from tags import INTEGRATION_TAGS

_READ_ONLY: dict[str, Any] = {"readOnlyHint": True, "openWorldHint": True}
_WRITE: dict[str, Any] = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}
_DESTRUCTIVE: dict[str, Any] = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "openWorldHint": True,
}
_META_READ: dict[str, Any] = {"readOnlyHint": True, "openWorldHint": False}


def _declare(
    annotations: dict[str, Any],
    integration: str,
    access: set[str],
    **extra: Any,
) -> dict[str, Any]:
    if integration not in INTEGRATION_TAGS:
        raise ValueError(
            f"Unknown integration tag {integration!r}. "
            f"Expected one of: {', '.join(sorted(INTEGRATION_TAGS))}."
        )
    return {"annotations": {**annotations, **extra}, "tags": {integration, *access}}


def read_only(integration: str) -> dict[str, Any]:
    """A read that may reach an external system."""
    return _declare(_READ_ONLY, integration, {"read"})


def write(integration: str, *, idempotent: bool = False) -> dict[str, Any]:
    """A mutation that is not destructive.

    Args:
        integration: Which integration the tool belongs to.
        idempotent: True when repeating the call has no additional effect.
    """
    extra = {"idempotentHint": True} if idempotent else {}
    return _declare(_WRITE, integration, {"write"}, **extra)


def destructive(integration: str) -> dict[str, Any]:
    """A containment action. Also tagged ``write``, so denying writes denies these."""
    return _declare(_DESTRUCTIVE, integration, {"write", "destructive"})


def meta_read() -> dict[str, Any]:
    """A diagnostic read that stays inside this server."""
    return _declare(_META_READ, "meta", {"read"})
