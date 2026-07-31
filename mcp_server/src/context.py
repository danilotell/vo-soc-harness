"""Shared application context passed through the FastMCP lifespan."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from fastmcp import Context

from config import Settings
from http_client import VisionOneClient


@dataclass
class AppContext:
    """Resources initialized once and shared across all tool invocations."""

    settings: Settings
    http: httpx.AsyncClient
    vision_one: VisionOneClient


def get_app_context(ctx: Context) -> AppContext:
    """Extract the typed AppContext from a FastMCP Context."""
    return ctx.request_context.lifespan_context  # type: ignore[union-attr]
