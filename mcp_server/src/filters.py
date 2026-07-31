"""
Input validation and safe construction of Vision One ``TMV1-Filter`` clauses.

User/agent-supplied values flow into URL paths and into the ``TMV1-Filter``
header. Both are injection surfaces, so values are validated against strict
patterns and string literals are quoted with embedded quotes escaped.
"""

from __future__ import annotations

import re

from fastmcp.exceptions import ToolError

# Endpoint/host names: letters, digits and a few separators.
_ENDPOINT_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._\-]{0,253}[A-Za-z0-9])?$")
# Workbench alert IDs, e.g. WB-14-20190709-00021.
_ALERT_ID_RE = re.compile(r"^WB-[A-Za-z0-9\-]{1,64}$")


def quote_filter_value(value: str) -> str:
    """Quote a string for a TMV1-Filter clause, escaping single quotes."""
    return "'" + value.replace("'", "''") + "'"


def validate_endpoint_name(endpoint_name: str) -> str:
    name = (endpoint_name or "").strip()
    if not _ENDPOINT_RE.match(name):
        raise ToolError(
            "Invalid endpoint name. Use letters, digits, '.', '_' or '-' (max 255 chars)."
        )
    return name


def validate_alert_id(alert_id: str) -> str:
    value = (alert_id or "").strip()
    if not _ALERT_ID_RE.match(value):
        raise ToolError("Invalid alert ID. Expected a Workbench ID like 'WB-00000-00000000-00000'.")
    return value


def validate_ioc(ioc: str) -> str:
    value = (ioc or "").strip()
    if not value or len(value) > 2048 or any(c in value for c in "\r\n\t"):
        raise ToolError("Invalid IOC value.")
    return value
