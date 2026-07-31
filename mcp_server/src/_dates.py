"""Date helpers shared across tools."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

_FMT = "%Y-%m-%dT%H:%M:%SZ"


def utc_range(days: int) -> tuple[str, str]:
    """Return (start, end) ISO-8601 strings covering the last ``days`` days."""
    now = datetime.now(UTC)
    return (now - timedelta(days=days)).strftime(_FMT), now.strftime(_FMT)
