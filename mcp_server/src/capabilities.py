"""
Single source of truth for integration capabilities.

A capability ties an external integration to the env vars it needs and the
tool tags it gates. Both the startup gating (``app.py``) and the diagnostic
``get_server_capabilities`` tool read from this list.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from config import Settings


@dataclass(frozen=True)
class Capability:
    name: str
    env_vars: tuple[str, ...]
    tags: frozenset[str]
    is_configured: Callable[[Settings], bool]


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        name="Vision One (alerts, endpoints, response)",
        env_vars=("VO_REGION", "VO_API_KEY"),
        tags=frozenset({"alerts", "endpoints", "response"}),
        is_configured=lambda s: bool(s.vo_region and s.vo_api_key),
    ),
    Capability(
        name="VirusTotal (threat intel)",
        env_vars=("VT_API_KEY",),
        tags=frozenset({"intel"}),
        is_configured=lambda s: bool(s.vt_api_key),
    ),
    Capability(
        name="Slack (notifications)",
        env_vars=("SLACK_WEBHOOK_URL",),
        tags=frozenset({"notify"}),
        is_configured=lambda s: bool(s.slack_webhook_url),
    ),
)
