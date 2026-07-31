"""Constrained input type for the add_to_block_list tool."""

from __future__ import annotations

from typing import Literal

IocType = Literal["ip", "domain", "fileSha1", "fileSha256", "senderMailAddress", "url"]
