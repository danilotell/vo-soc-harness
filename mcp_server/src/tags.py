"""
The closed vocabulary of tool tags.

Tags are what a deployment can switch off: by integration (``alerts``, ``intel``,
...) or by access level (``read``, ``write``, ``destructive``). Because they
control what a server is *able* to do, the vocabulary is closed and validated —
an unknown tag is a configuration error, not a rule that silently matches
nothing.
"""

from __future__ import annotations

from typing import Final

#: One per external integration, mapped to credentials in ``capabilities.py``.
#: ``meta`` covers diagnostics that touch no external system.
INTEGRATION_TAGS: Final = frozenset({"alerts", "endpoints", "response", "intel", "notify", "meta"})

#: What a tool does to the world. Every tool carries exactly one.
ACCESS_TAGS: Final = frozenset({"read", "write", "destructive"})

ALL_TAGS: Final = INTEGRATION_TAGS | ACCESS_TAGS
