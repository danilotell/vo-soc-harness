"""
Custom Vision One MCP Server.

Thin entry point: configures logging, builds the server (see ``app.py``) and
runs it over the transport selected by ``MCP_TRANSPORT`` (stdio | http).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from app import build_server
from config import get_settings


def _configure_logging(level: str) -> None:
    # IMPORTANT: stdio transport speaks JSON-RPC over stdout, so logs MUST go to
    # stderr to avoid corrupting the protocol stream.
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _configure_audit_logging(path: str | None) -> None:
    """Route the audit trail to a durable, rotated file, separate from app logs.

    When no path is configured, audit records simply propagate to stderr with
    everything else (fine for local/dev; set MCP_AUDIT_LOG_FILE in production).

    The parent directory is created here: ``RotatingFileHandler`` does not create
    it, and a missing parent raises ``FileNotFoundError`` at startup, before the
    server accepts any request.
    """
    if not path:
        return
    from logging.handlers import RotatingFileHandler

    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(log_path, maxBytes=10_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    audit_logger = logging.getLogger("vo_mcp.audit")
    audit_logger.addHandler(handler)
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False  # keep the audit trail out of the noisy app stream


def main() -> None:
    settings = get_settings()
    _configure_logging(settings.log_level)
    _configure_audit_logging(settings.audit_log_file)
    mcp = build_server()

    if settings.transport == "http":
        mcp.run(transport="http", host=settings.http_host, port=settings.http_port)
    else:
        mcp.run()  # stdio (default)


if __name__ == "__main__":
    main()
