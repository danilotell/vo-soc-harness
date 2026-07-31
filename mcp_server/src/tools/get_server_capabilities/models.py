"""Output models for the get_server_capabilities diagnostic tool."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class IntegrationStatus(BaseModel):
    """Status of a single external integration."""

    name: str
    status: Literal["active", "inactive"]
    required_env: list[str]
    categories: list[str]
    reason: str | None = None


class ContainmentStatus(BaseModel):
    """Whether destructive actions are possible right now, and who approves them.

    Reported up front so an orchestrator can plan around it instead of finding
    out when it tries to contain a live threat.
    """

    destructive_tools_enabled: bool
    approval_channel: Literal["server_elicitation", "client_gate", "unavailable"]
    detail: str


class ServerCapabilities(BaseModel):
    """Diagnostic snapshot of what the server can currently do."""

    transport: str
    http2: bool
    operator_id: str | None
    integrations: list[IntegrationStatus]
    containment: ContainmentStatus
    active_tools: list[str]
    active_tool_count: int
