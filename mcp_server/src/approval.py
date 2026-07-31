"""
Human-in-the-loop approval gate for destructive actions.

``destructiveHint`` is *advisory*: it tells a client that a tool is dangerous,
but nothing obliges the client to act on it. This module adds a gate the
**server** owns, so containment cannot run just because a model decided to call
a tool:

  * ``MCP_REQUIRE_APPROVAL=true`` (default) — the server asks the human through
    the MCP elicitation flow and proceeds only on an explicit approval. If the
    client does not support elicitation, or the human declines/cancels, the
    action is REFUSED. There is no path where "we could not ask" turns into
    "we went ahead" (fail closed).
  * ``MCP_REQUIRE_APPROVAL=false`` — approval is delegated to the client (e.g.
    OpenCode's ``permission: ask``). The server logs a warning and writes an
    ``approval_delegated`` audit record on every call, so the weaker posture is
    visible in the audit trail instead of being implicit.

Every outcome (approved, denied, unavailable, delegated) is audited, so the
trail shows not only what ran but what was refused and why.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import AcceptedElicitation
from pydantic import BaseModel

from audit import log_action
from context import get_app_context

logger = logging.getLogger("vo_mcp.approval")

APPROVE = "approve"
REJECT = "reject"


class ApprovalDecision(BaseModel):
    """The form a human fills in to approve or abort a destructive action."""

    decision: Literal["approve", "reject"]


def client_supports_elicitation(ctx: Context) -> bool:
    """Whether the connected client declared the elicitation capability.

    Read from the MCP handshake, so we know up front whether a human can be
    reached instead of finding out by failing mid-containment. Unknown counts as
    NOT supported: we would rather refuse than assume someone is watching.
    """
    try:
        capabilities = ctx.session.client_params.capabilities  # type: ignore[union-attr]
    except Exception:  # pragma: no cover - defensive: transport without a handshake
        return False
    return getattr(capabilities, "elicitation", None) is not None


async def require_human_approval(ctx: Context, *, action: str, target: str, reason: str) -> None:
    """Require explicit human approval for ``action`` on ``target``.

    Returns normally only when a human approved (or approval was explicitly
    delegated to a client that cannot be asked). Raises ``ToolError`` otherwise.

    Args:
        action: Tool name, e.g. 'isolate_endpoint'.
        target: What the action acts on (endpoint name, IOC, ...).
        reason: The caller-supplied justification, shown to the human.
    """
    settings = get_app_context(ctx).settings
    details = {"reason": reason}

    # A client that can be asked is ALWAYS asked, whatever the setting says: the
    # setting only decides what happens when we cannot reach a human ourselves.
    if not client_supports_elicitation(ctx):
        if settings.require_approval:
            logger.error(
                "Refusing %s on %s: this client cannot be asked for approval "
                "(no elicitation capability) and MCP_REQUIRE_APPROVAL is true.",
                action,
                target,
            )
            log_action(
                action,
                target=target,
                status="approval_unavailable",
                details=details,
                error="client does not support elicitation",
            )
            raise ToolError(
                f"Refused: {action} needs human approval and this client cannot ask for it. "
                "Use a client that supports MCP elicitation, or set MCP_REQUIRE_APPROVAL=false "
                "only if the client enforces approval itself."
            )
        logger.warning(
            "Client cannot be asked for approval and MCP_REQUIRE_APPROVAL is false: %s on %s is "
            "delegated to the client, which MUST gate it interactively.",
            action,
            target,
        )
        log_action(action, target=target, status="approval_delegated", details=details)
        return

    message = (
        f"APPROVAL REQUIRED — {action} on '{target}'.\n"
        f"Reason given: {reason}\n"
        f"This is a destructive containment action. Choose '{APPROVE}' to execute it, "
        f"'{REJECT}' to abort."
    )

    try:
        # A BaseModel response_type is supported at runtime (and covered by tests);
        # mypy only resolves elicit()'s first @overload, the response_type=None one.
        result = await ctx.elicit(message, ApprovalDecision)  # type: ignore[arg-type]
    except Exception as exc:
        # Client cannot ask a human -> we must not act. Fail closed.
        logger.error("Could not obtain human approval for %s on %s: %s", action, target, exc)
        log_action(action, target=target, status="approval_unavailable", error=str(exc))
        raise ToolError(
            f"Refused: {action} needs human approval and this client cannot ask for it. "
            "Use a client that supports MCP elicitation, or set MCP_REQUIRE_APPROVAL=false "
            "only if the client enforces approval itself."
        ) from exc

    # getattr, not attribute access: a client that returns something other than the
    # requested schema is not an approval either, and must not raise its way past us.
    decision = getattr(getattr(result, "data", None), "decision", None)
    if not isinstance(result, AcceptedElicitation) or decision != APPROVE:
        outcome = getattr(result, "action", "unknown")
        logger.warning("Human did not approve %s on %s (%s).", action, target, outcome)
        log_action(
            action,
            target=target,
            status="approval_denied",
            details={**details, "elicitation": str(outcome)},
        )
        raise ToolError(f"Refused: a human did not approve {action} on '{target}'.")

    log_action(action, target=target, status="approved", details=details)
