"""get_ioc_reputation: VirusTotal reputation for an Indicator of Compromise."""

from __future__ import annotations

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from context import get_app_context
from filters import validate_ioc
from http_client import fetch_virustotal
from tools._hints import read_only

from .models import VirusTotalPath


def register(mcp: FastMCP) -> None:

    @mcp.tool(**read_only("intel"))
    async def get_ioc_reputation(ctx: Context, ioc: str, ioc_path: VirusTotalPath) -> str:
        """
        Query VirusTotal for the reputation of an Indicator of Compromise.

        Args:
            ioc: The indicator value (IP, domain, URL, or file hash).
            ioc_path: VirusTotal resource path — one of: ip_addresses, domains, urls, files.
        """
        app = get_app_context(ctx)
        if not app.settings.vt_api_key:
            raise ToolError("VirusTotal is not configured (missing VT_API_KEY).")
        ioc = validate_ioc(ioc)
        return await fetch_virustotal(
            app.http,
            base_url=app.settings.vt_base_url,
            api_key=app.settings.vt_api_key,
            ioc_path=ioc_path,
            ioc=ioc,
            max_retries=app.settings.max_retries,
            backoff_base=app.settings.backoff_base,
            backoff_max=app.settings.backoff_max,
        )
