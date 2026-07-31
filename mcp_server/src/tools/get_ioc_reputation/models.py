"""Constrained input type for the get_ioc_reputation tool."""

from __future__ import annotations

from typing import Literal

VirusTotalPath = Literal["ip_addresses", "domains", "urls", "files"]
