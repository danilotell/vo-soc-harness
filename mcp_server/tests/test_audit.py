"""Tests for the audit trail: durable file output and the ``audited`` wrapper."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from audit import audited, log_action
from config import Settings
from custom_vo_mcp import _configure_audit_logging


def test_audit_action_is_written_to_file(tmp_path):
    log_file = tmp_path / "audit.log"
    _configure_audit_logging(str(log_file))
    try:
        log_action(
            "isolate_endpoint",
            target="HOST1",
            status="success",
            details={"description": "contención"},
        )
    finally:
        # Detach the file handler so it doesn't leak into other tests.
        audit_logger = logging.getLogger("vo_mcp.audit")
        for handler in list(audit_logger.handlers):
            handler.close()
            audit_logger.removeHandler(handler)
        audit_logger.propagate = True

    content = log_file.read_text(encoding="utf-8")
    assert '"action": "isolate_endpoint"' in content
    assert '"target": "HOST1"' in content
    assert '"status": "success"' in content


def test_audit_directory_is_created_when_missing(tmp_path):
    """The audit directory is created on demand rather than required to exist.

    ``RotatingFileHandler`` raises ``FileNotFoundError`` on a missing parent, and
    this runs at startup, so without the mkdir the server would not boot.
    """
    log_file = tmp_path / "does" / "not" / "exist" / "audit.log"
    assert not log_file.parent.exists()

    _configure_audit_logging(str(log_file))
    try:
        log_action("isolate_endpoint", target="HOST1", status="success")
    finally:
        audit_logger = logging.getLogger("vo_mcp.audit")
        for handler in list(audit_logger.handlers):
            handler.close()
            audit_logger.removeHandler(handler)
        audit_logger.propagate = True

    assert log_file.exists()


def test_relative_audit_path_is_anchored_to_the_clone_root():
    """A relative path resolves against the clone root, not the CWD.

    The server runs as ``uv run --directory mcp_server``, so its CWD is
    ``mcp_server/``. Unanchored, ``audit/vo-audit.log`` would resolve inside
    ``mcp_server/`` rather than beside the harness state created by the setup.
    """
    from config import _REPO_ROOT

    settings = Settings(MCP_AUDIT_LOG_FILE="audit/vo-audit.log")

    assert settings.audit_log_file is not None
    assert Path(settings.audit_log_file) == _REPO_ROOT / "audit" / "vo-audit.log"


def test_absolute_audit_path_is_left_untouched(tmp_path):
    absolute = tmp_path / "elsewhere" / "audit.log"
    settings = Settings(MCP_AUDIT_LOG_FILE=str(absolute))

    assert settings.audit_log_file == str(absolute)


def test_every_record_carries_the_machine_actor(caplog):
    """host and os_user are what make a record corroborable."""
    with caplog.at_level(logging.INFO, logger="vo_mcp.audit"):
        log_action("isolate_endpoint", target="HOST1", status="approved")

    record = _records(caplog)[0]
    assert record["host"]
    assert record["os_user"]


def test_containment_requires_a_declared_operator():
    """An action nobody can be held to is not an auditable action."""
    with pytest.raises(ValidationError, match="MCP_OPERATOR_ID"):
        Settings(MCP_ENABLE_DESTRUCTIVE=True, MCP_OPERATOR_ID="")

    settings = Settings(MCP_ENABLE_DESTRUCTIVE=True, MCP_OPERATOR_ID="soc.analyst.1")
    assert settings.operator_id == "soc.analyst.1"


def test_read_only_server_needs_no_operator():
    """The requirement is tied to containment, not to running the server.

    ``_env_file=None`` is what keeps this hermetic: no dependency on local
    configuration.
    """
    assert Settings(_env_file=None, MCP_ENABLE_DESTRUCTIVE=False).operator_id is None


def _records(caplog) -> list[dict]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == "vo_mcp.audit"]


async def test_audited_records_attempt_then_success(caplog):
    caplog.set_level(logging.INFO, logger="vo_mcp.audit")

    async with audited("modify_alert_status", target="WB-1", details={"status": "Closed"}):
        pass

    assert [r["status"] for r in _records(caplog)] == ["attempt", "success"]


async def test_audited_records_error_and_reraises(caplog):
    """A failed action must still be traceable, and must not be swallowed."""
    caplog.set_level(logging.INFO, logger="vo_mcp.audit")

    with pytest.raises(RuntimeError, match="upstream exploded"):
        async with audited("add_alert_note", target="WB-1"):
            raise RuntimeError("upstream exploded")

    records = _records(caplog)
    assert [r["status"] for r in records] == ["attempt", "error"]
    assert records[-1]["error"] == "upstream exploded"
