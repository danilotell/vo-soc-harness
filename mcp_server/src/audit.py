"""
Structured audit logging for every state-changing action.

Anything that mutates state somewhere else — a containment action, but also an
alert status change, a note or a Slack notification — must leave a trace
independent of the upstream API, for forensics and compliance ("who closed this
alert, when, and did anything fail?"). Each call emits a single JSON line on the
dedicated ``vo_mcp.audit`` logger, so operators can route/ship it separately.

Use the ``audited`` context manager for tools: it records the attempt and then
the outcome, so a crash mid-call cannot leave an action untraced.
"""

from __future__ import annotations

import getpass
import json
import logging
import platform
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

audit_logger = logging.getLogger("vo_mcp.audit")


@lru_cache(maxsize=1)
def _actor() -> dict[str, str]:
    """Who to attribute an action to. Resolved once; constant for the process.

    ``operator`` is declared in the configuration, so it identifies the person on
    whose behalf the server runs. ``host`` and ``os_user`` are read from the
    machine and are what makes the record corroborable: configuration alone
    cannot make an action look like it came from somewhere else.

    Never raises. An audit record with less attribution is worth having; a tool
    call that fails because attribution could not be resolved is not.
    """
    actor: dict[str, str] = {}
    try:
        from config import get_settings

        operator = get_settings().operator_id
        if operator:
            actor["operator"] = operator
    except Exception:  # noqa: BLE001 - see docstring
        pass
    try:
        actor["host"] = platform.node()
        actor["os_user"] = getpass.getuser()
    except Exception:  # noqa: BLE001 - see docstring
        pass
    return actor


def log_action(
    action: str,
    *,
    target: str,
    status: str,
    details: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Emit one structured audit record.

    Args:
        action: The tool/action name (e.g. 'isolate_endpoint').
        target: What the action acts on (endpoint name, IOC, ...).
        status: Lifecycle of the action — 'attempt' | 'success' | 'error' |
            'dry_run' — or of its approval gate (see ``approval.py``):
            'approved' | 'approval_denied' | 'approval_unavailable' |
            'approval_delegated'.
        details: Extra context (e.g. the audit description, ioc_type).
        error: Failure message when status == 'error'.
    """
    record: dict[str, Any] = {
        "event": "audit",
        "action": action,
        "target": target,
        "status": status,
        **_actor(),
    }
    if details:
        record["details"] = details
    if error:
        record["error"] = error
    audit_logger.info(json.dumps(record, ensure_ascii=False, sort_keys=True))


@asynccontextmanager
async def audited(
    action: str, *, target: str, details: dict[str, Any] | None = None
) -> AsyncIterator[None]:
    """Wrap a state-changing call so its attempt AND outcome are both recorded.

    Emits 'attempt' on entry, then 'success' or 'error' on exit. The exception is
    re-raised untouched: auditing observes the call, it never swallows failures.

        async with audited("isolate_endpoint", target=host, details=details):
            result = await app.vision_one.post(...)
        return result
    """
    log_action(action, target=target, status="attempt", details=details)
    try:
        yield
    except Exception as exc:
        log_action(action, target=target, status="error", details=details, error=str(exc))
        raise
    log_action(action, target=target, status="success", details=details)
