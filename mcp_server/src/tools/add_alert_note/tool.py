"""add_alert_note: attach a technical note to a Workbench alert."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from audit import audited
from context import get_app_context
from filters import validate_alert_id
from tools._hints import write


def sign(note: str, operator_id: str | None) -> str:
    """Append the operator signature the note is written under.

    Signed HERE rather than in the note the agent composes, for the same reason the
    operator id is not exposed as a writable value: a signature the model has to
    remember to add is one it can omit, reword, or attribute to someone else. This
    way every note on a Workbench alert names a person who answers for it, and that
    name comes from the server's `.env` — which the agent may neither read nor write.

    Idempotent: a note that already ends with this signature is not signed twice, so
    an agent that copies a previous note's text does not stack footers.
    """
    if not operator_id:
        return note
    signature = f"-- via Custom Vision One MCP, operator: {operator_id}"
    if note.rstrip().endswith(signature):
        return note
    return f"{note.rstrip()}\n\n{signature}"


def register(mcp: FastMCP) -> None:

    @mcp.tool(**write("alerts"))
    async def add_alert_note(ctx: Context, alert_id: str, note: str) -> Any:
        """
        Add a technical note to a Workbench alert.

        The note is signed with the server's operator id (MCP_OPERATOR_ID) before it
        is sent, so every note names who is responsible for it. Do not add your own
        signature line.

        Args:
            alert_id: Workbench alert ID (e.g. 'WB-00000-00000000-00000').
            note: Note content to attach to the alert.
        """
        app = get_app_context(ctx)
        alert_id = validate_alert_id(alert_id)
        if not note or not note.strip():
            raise ToolError("Note content cannot be empty.")
        note = sign(note, app.settings.operator_id)
        # Only the note's size is audited: its text is already stored on the alert
        # in Vision One, and the audit stream should stay small and greppable.
        async with audited("add_alert_note", target=alert_id, details={"note_chars": len(note)}):
            result = await app.vision_one.post(
                f"/v3.0/workbench/alerts/{alert_id}/notes", {"content": note}
            )
        return result
