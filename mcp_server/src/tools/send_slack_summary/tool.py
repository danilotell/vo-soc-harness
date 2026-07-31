"""send_slack_summary: send an alert-management summary to Slack."""

from __future__ import annotations

import logging

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from audit import audited
from context import get_app_context
from tools._hints import write

logger = logging.getLogger("vo_mcp.notify")


def register(mcp: FastMCP) -> None:

    @mcp.tool(**write("notify"))
    async def send_slack_summary(ctx: Context, workbench_id: str, summary: str) -> str:
        """
        Send an alert-management summary to the configured Slack channel.

        Args:
            workbench_id: The Workbench alert ID that was managed.
            summary: Markdown-formatted summary of the actions taken.
        """
        app = get_app_context(ctx)
        if not app.settings.slack_webhook_url:
            raise ToolError("Slack is not configured (missing SLACK_WEBHOOK_URL).")
        if not summary or not summary.strip():
            raise ToolError("Summary content cannot be empty.")

        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"📊 Alert management summary {workbench_id}",
                    },
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"{summary}"},
                },
            ]
        }
        # Notifying an external channel is a state change outside Vision One, so it
        # belongs in the audit trail too (only the size, never the message body).
        details = {"summary_chars": len(summary)}
        async with audited("send_slack_summary", target=workbench_id, details=details):
            try:
                response = await app.http.post(app.settings.slack_webhook_url, json=payload)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                logger.warning("Slack transport error: %s", exc)
                raise ToolError("Could not reach Slack. Try again later.") from exc

            if response.is_error:
                logger.error(
                    "Slack webhook failed: %d %s", response.status_code, response.text[:500]
                )
                raise ToolError(f"Slack rejected the message (HTTP {response.status_code}).")
        return "Summary successfully sent to Slack."
