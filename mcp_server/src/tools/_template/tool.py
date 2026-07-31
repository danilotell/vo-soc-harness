"""<tool_name>: one-line description of what this tool does.

The only contract autodiscovery requires is a module-level ``register(mcp)``
that defines exactly one @mcp.tool. Everything below is a fill-in-the-blanks
starting point — adjust the access level, args and body to your tool.
"""

from __future__ import annotations

from fastmcp import Context, FastMCP

from context import get_app_context
from tools._hints import read_only  # or write / destructive / meta_read

# Validation:
#   * shared check used by several tools -> import from filters:
#         from filters import validate_endpoint_name
#   * check unique to THIS tool -> define it in validators.py (relative import):
#         from .validators import validate_ticket_id
# from .models import MyOutput  # uncomment if you declare models in models.py


def register(mcp: FastMCP) -> None:

    # One call sets both the client-facing annotations and the tags this server
    # gates on. Pick the access level, then the integration it belongs to:
    #   read_only / write / destructive with
    #     "alerts" | "endpoints" | "response"  -> needs Vision One credentials
    #     "intel"                              -> needs a VirusTotal key
    #     "notify"                             -> needs a Slack webhook
    #   meta_read()                            -> touches no external system
    @mcp.tool(**read_only("alerts"))
    async def my_new_tool(ctx: Context, example_arg: str) -> dict:
        """
        One-line summary shown to the LLM (keep the first line short).

        Args:
            example_arg: describe each argument — the LLM reads this.
        """
        app = get_app_context(ctx)
        # Validate any free-text input BEFORE using it (it flows into URLs /
        # filter headers / request bodies):
        #   example_arg = validate_ticket_id(example_arg)
        # Reach upstream services via the shared clients:
        #   data = await app.vision_one.get("/v3.0/...")
        #   await app.http.post(url, json=...)
        #
        # Choose your output policy:
        #   * Projected (recommended for verbose responses) — model = whitelist:
        #         return ExampleOutput.model_validate(data)
        #     ...for a list:
        #         return [ExampleOutput.model_validate(x) for x in data["items"]]
        #   * Full response (when the caller truly needs everything):
        #         return data            # raw dict[str, Any], intentional
        return {"example_arg": example_arg}
