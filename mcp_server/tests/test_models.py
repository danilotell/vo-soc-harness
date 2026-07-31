"""Offline unit tests for the per-tool output models."""

from __future__ import annotations

from tools.add_alert_note.tool import sign
from tools.get_alert_list.models import AlertSummary
from tools.get_risk_index.models import RiskIndex


def test_note_is_signed_with_the_operator():
    """Every note must name who answers for it, and the agent cannot opt out."""
    signed = sign("Tier 1: inicio de gestion", "soc.analyst.1")
    assert signed.endswith("-- via Custom Vision One MCP, operator: soc.analyst.1")
    assert signed.startswith("Tier 1: inicio de gestion")


def test_signing_is_idempotent():
    """An agent that reuses a previous note's text must not stack signatures."""
    once = sign("nota", "soc.analyst.1")
    assert sign(once, "soc.analyst.1") == once


def test_unsigned_when_no_operator_is_declared():
    """A read-only deployment needs no operator, so there is nothing to sign with."""
    assert sign("nota", None) == "nota"
    assert sign("nota", "") == "nota"


def test_alert_summary_from_api_maps_aliases():
    summary = AlertSummary.from_api(
        {
            "id": "WB-1",
            "model": "Suspicious activity",
            "createdDateTime": "2020-01-01T00:00:00Z",
            "workbenchLink": "https://example/wb/1",
        }
    )
    dumped = summary.model_dump(by_alias=True)
    assert dumped["id"] == "WB-1"
    assert dumped["createdDateTime"] == "2020-01-01T00:00:00Z"
    assert dumped["workbenchLink"] == "https://example/wb/1"


def test_alert_summary_missing_id_falls_back_to_empty():
    # API omitting 'id' must not raise — robustness over strictness here.
    assert AlertSummary.from_api({}).id == ""


def test_risk_index_accepts_api_alias():
    risk = RiskIndex(riskIndex=42.0)
    assert risk.risk_index == 42.0
    assert risk.model_dump(by_alias=True)["riskIndex"] == 42.0
