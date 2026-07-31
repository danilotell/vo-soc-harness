"""
Tests for the human-in-the-loop approval gate (``approval.py``).

The point of every test here is the same: there must be **no path** from a model
calling a destructive tool to the action running, unless a human said yes. In
particular, "the client could not ask" must fail closed.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Literal

import pytest
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
)

from approval import APPROVE, REJECT, ApprovalDecision, require_human_approval


@dataclass
class _Settings:
    require_approval: bool = True


class _FakeCtx:
    """Minimal stand-in for a FastMCP Context.

    ``can_elicit`` mirrors the client's declared handshake capability (OpenCode
    declares none). ``result`` is what elicit() returns; ``exc`` makes it raise,
    i.e. a client that declared the capability but cannot honour it.
    """

    def __init__(
        self,
        *,
        settings: _Settings,
        result=None,
        exc: Exception | None = None,
        can_elicit: bool = True,
    ) -> None:
        self._result = result
        self._exc = exc
        self.messages: list[str] = []
        self.request_context = SimpleNamespace(lifespan_context=SimpleNamespace(settings=settings))
        self.session = SimpleNamespace(
            client_params=SimpleNamespace(
                capabilities=SimpleNamespace(elicitation={} if can_elicit else None)
            )
        )

    async def elicit(self, message: str, response_type=None):
        self.messages.append(message)
        if self._exc is not None:
            raise self._exc
        return self._result


@pytest.fixture
def audit_records(caplog):
    """Collect the JSON audit records emitted during a test."""
    caplog.set_level(logging.INFO, logger="vo_mcp.audit")

    def _records() -> list[dict]:
        return [json.loads(r.getMessage()) for r in caplog.records if r.name == "vo_mcp.audit"]

    return _records


def _accepted(decision: Literal["approve", "reject"]):
    """An accepted elicitation carrying the approval form."""
    return AcceptedElicitation(data=ApprovalDecision(decision=decision))


async def _gate(ctx: Any) -> None:
    await require_human_approval(
        ctx, action="isolate_endpoint", target="HOST1", reason="ransomware"
    )


async def test_approval_accepted_proceeds_and_is_audited(audit_records):
    ctx = _FakeCtx(settings=_Settings(), result=_accepted(APPROVE))
    await _gate(ctx)  # must not raise

    statuses = [r["status"] for r in audit_records()]
    assert statuses == ["approved"]
    # The human is told what, on whom, and why.
    assert "isolate_endpoint" in ctx.messages[0]
    assert "HOST1" in ctx.messages[0]
    assert "ransomware" in ctx.messages[0]


async def test_explicit_rejection_refuses(audit_records):
    ctx = _FakeCtx(settings=_Settings(), result=_accepted(REJECT))
    with pytest.raises(ToolError, match="did not approve"):
        await _gate(ctx)
    assert [r["status"] for r in audit_records()] == ["approval_denied"]


@pytest.mark.parametrize("result", [DeclinedElicitation(), CancelledElicitation()])
async def test_declined_or_cancelled_refuses(result, audit_records):
    ctx = _FakeCtx(settings=_Settings(), result=result)
    with pytest.raises(ToolError, match="did not approve"):
        await _gate(ctx)
    assert [r["status"] for r in audit_records()] == ["approval_denied"]


async def test_client_without_elicitation_fails_closed(audit_records):
    """The critical case: unable to ask a human => refuse, never proceed."""
    ctx = _FakeCtx(settings=_Settings(), can_elicit=False)
    with pytest.raises(ToolError, match="cannot ask"):
        await _gate(ctx)
    assert ctx.messages == []  # we do not even try when the client declared nothing
    assert [r["status"] for r in audit_records()] == ["approval_unavailable"]


async def test_capability_declared_but_broken_still_fails_closed(audit_records):
    """Declaring elicitation and then failing must not become an approval either."""
    ctx = _FakeCtx(settings=_Settings(), exc=RuntimeError("transport went away"))
    with pytest.raises(ToolError, match="cannot ask"):
        await _gate(ctx)
    assert [r["status"] for r in audit_records()] == ["approval_unavailable"]


async def test_response_off_schema_refuses(audit_records):
    """A client answering with something other than the approval form is not approval."""
    ctx = _FakeCtx(settings=_Settings(), result=AcceptedElicitation(data="yes please"))
    with pytest.raises(ToolError, match="did not approve"):
        await _gate(ctx)
    assert [r["status"] for r in audit_records()] == ["approval_denied"]


async def test_delegated_mode_skips_elicitation_but_leaves_a_trace(audit_records):
    """OpenCode's situation: server cannot ask, operator accepted the client gate."""
    ctx = _FakeCtx(settings=_Settings(require_approval=False), can_elicit=False)
    await _gate(ctx)  # must not raise: the client is responsible for asking

    assert ctx.messages == []  # the server did not ask
    records = audit_records()
    assert [r["status"] for r in records] == ["approval_delegated"]
    assert records[0]["target"] == "HOST1"


async def test_capable_client_is_asked_even_when_approval_is_delegated(audit_records):
    """The setting only governs clients that CANNOT be asked.

    Delegating must never silence a client that is able to ask a human, otherwise
    one env var would quietly downgrade every deployment.
    """
    ctx = _FakeCtx(
        settings=_Settings(require_approval=False), result=_accepted(APPROVE), can_elicit=True
    )
    await _gate(ctx)

    assert ctx.messages, "a capable client must still be asked"
    assert [r["status"] for r in audit_records()] == ["approved"]


async def test_capable_client_rejection_wins_over_delegation(audit_records):
    ctx = _FakeCtx(
        settings=_Settings(require_approval=False), result=_accepted(REJECT), can_elicit=True
    )
    with pytest.raises(ToolError, match="did not approve"):
        await _gate(ctx)
    assert [r["status"] for r in audit_records()] == ["approval_denied"]
