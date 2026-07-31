"""
Tool-specific input validation — DELETE this file if your tool doesn't need it.

Use this ONLY for validation unique to this tool. If two or more tools need the
same check, promote it to the shared ``filters`` module instead (see
``tools/README.md`` → "Validation: shared vs tool-specific").

Validators must raise ``fastmcp.exceptions.ToolError`` on bad input — that
message is surfaced safely to the caller — and return the cleaned value.
"""

from __future__ import annotations

import re

from fastmcp.exceptions import ToolError

# Example: a ticket id like "INC-12345". Replace with your tool's own rule.
_TICKET_RE = re.compile(r"^INC-[0-9]{1,10}$")


def validate_ticket_id(ticket_id: str) -> str:
    value = (ticket_id or "").strip()
    if not _TICKET_RE.match(value):
        raise ToolError("Invalid ticket id. Expected a value like 'INC-12345'.")
    return value
