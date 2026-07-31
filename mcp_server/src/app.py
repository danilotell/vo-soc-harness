"""FastMCP server factory: lifespan, shared resources and tool registration."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

from capabilities import CAPABILITIES
from config import Settings, get_settings
from context import AppContext
from http_client import VisionOneClient
from tools import register_all

logger = logging.getLogger("vo_mcp")


def _http2_available() -> bool:
    try:
        import h2  # noqa: F401
    except ImportError:
        return False
    return True


def _build_async_client(settings: Settings) -> httpx.AsyncClient:
    timeout = httpx.Timeout(settings.request_timeout, connect=settings.connect_timeout)
    limits = httpx.Limits(
        max_connections=settings.max_connections,
        max_keepalive_connections=settings.max_keepalive_connections,
    )
    http2 = settings.enable_http2 and _http2_available()
    if settings.enable_http2 and not http2:
        logger.warning("HTTP/2 requested but 'h2' is not installed; falling back to HTTP/1.1.")
    return httpx.AsyncClient(timeout=timeout, limits=limits, http2=http2)


@asynccontextmanager
async def _lifespan(_server: FastMCP) -> AsyncIterator[AppContext]:
    settings = get_settings()
    logger.info("Starting Vision One MCP (transport=%s)", settings.transport)
    async with _build_async_client(settings) as http:
        vision_one = VisionOneClient(
            base_url=settings.vo_region or "",
            api_key=settings.vo_api_key or "",
            http=http,
            max_retries=settings.max_retries,
            backoff_base=settings.backoff_base,
            backoff_max=settings.backoff_max,
            max_pages=settings.max_pages,
        )
        yield AppContext(settings=settings, http=http, vision_one=vision_one)
    logger.info("Vision One MCP shut down cleanly.")


def _apply_capability_gating(mcp: FastMCP, settings: Settings) -> None:
    """Disable tools whose required credentials are not configured."""
    for cap in CAPABILITIES:
        if not cap.is_configured(settings):
            mcp.disable(tags=set(cap.tags))
            logger.warning(
                "Disabled tools tagged %s because %s is not configured.",
                sorted(cap.tags),
                " + ".join(cap.env_vars),
            )


def _check_tool_names(settings: Settings, known: set[str]) -> None:
    """Reject names that match no tool, instead of ignoring them silently.

    Without this, ``MCP_DISABLED_TOOLS=isolate_endpint`` reads like the tool was
    switched off while it stays fully exposed. Failing at startup keeps the same
    promise the rest of the configuration makes: a misconfigured server does not
    start.
    """
    for variable, names in (
        ("MCP_ENABLED_TOOLS", settings.enabled_tools),
        ("MCP_DISABLED_TOOLS", settings.disabled_tools),
    ):
        unknown = names - known
        if unknown:
            raise ValueError(
                f"{variable} names unknown tool(s): {', '.join(sorted(unknown))}. "
                f"Available tools: {', '.join(sorted(known))}."
            )


def _apply_tool_policy(mcp: FastMCP, settings: Settings) -> None:
    """Enable/disable tools per configuration (allowlist + denylists).

    Precedence (later transforms win in FastMCP):
      1. allowlist (MCP_ENABLED_TOOLS): disable everything, re-enable the listed tools
      2. MCP_DISABLED_TAGS: disable whole categories (e.g. 'destructive', 'write')
      3. MCP_DISABLED_TOOLS: disable specific tools (always wins)
    """
    if settings.enabled_tools:
        mcp.disable(components={"tool"})
        mcp.enable(names=settings.enabled_tools)
        logger.info("Tool allowlist active: %s", sorted(settings.enabled_tools))
    if settings.disabled_tags:
        mcp.disable(tags=settings.disabled_tags)
        logger.info("Disabled tool tags: %s", sorted(settings.disabled_tags))
    if settings.disabled_tools:
        mcp.disable(names=settings.disabled_tools)
        logger.info("Disabled tools: %s", sorted(settings.disabled_tools))


def _apply_destructive_gating(mcp: FastMCP, settings: Settings) -> None:
    """Hide containment tools unless an operator explicitly enabled them.

    Applied after the user policy for the same reason as capability gating — an
    allowlist must not be able to resurrect a tool the operator never turned on.
    """
    if settings.enable_destructive:
        logger.warning(
            "Destructive tools are ENABLED (MCP_ENABLE_DESTRUCTIVE=true). Every call "
            "requires human approval; see approval.py."
        )
        return
    mcp.disable(tags={"destructive"})
    logger.info(
        "Destructive tools are disabled (default). Set MCP_ENABLE_DESTRUCTIVE=true to expose "
        "them; they will still require human approval on every call."
    )


def _build_auth(settings: Settings) -> StaticTokenVerifier | None:
    """Return a bearer-token verifier for HTTP, or None (no auth) otherwise.

    stdio is local-only so it is never gated. On HTTP without MCP_AUTH_TOKEN the
    server stays open but logs a loud warning — destructive tools would be
    reachable unauthenticated, so this should only happen behind a trusted proxy.
    """
    if settings.transport != "http":
        return None
    if not settings.auth_token:
        logger.warning(
            "HTTP transport is running WITHOUT authentication (MCP_AUTH_TOKEN is "
            "unset). Destructive tools are reachable by anyone who can reach the "
            "port. Set MCP_AUTH_TOKEN or deploy behind an authenticating proxy."
        )
        return None
    return StaticTokenVerifier(tokens={settings.auth_token: {"client_id": "soc-mcp"}})


def build_server() -> FastMCP:
    """Construct and configure the FastMCP server with all tools registered."""
    settings = get_settings()
    mcp = FastMCP(
        "Custom Vision One MCP",
        lifespan=_lifespan,
        mask_error_details=settings.mask_error_details,
        auth=_build_auth(settings),
    )
    registered = register_all(mcp)
    _check_tool_names(settings, registered)
    # User policy first; the safety gates last so they always win (a tool cannot be
    # force-enabled when its credential is absent, or when containment is off).
    _apply_tool_policy(mcp, settings)
    _apply_destructive_gating(mcp, settings)
    _apply_capability_gating(mcp, settings)
    return mcp
