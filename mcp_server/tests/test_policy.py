"""
Tests for the tool activation policy and its precedence rules (``app.py``).

The invariant these lock down is the security-relevant one: **a missing
credential always wins**. An operator (or a mistake) must never be able to
force-enable a tool whose integration is not configured, no matter what the
allowlist says — which in ``build_server`` is guaranteed only by applying
capability gating AFTER the user policy. That ordering is easy to invert in a
refactor, so it is asserted here rather than left to code review.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app import (
    _apply_capability_gating,
    _apply_destructive_gating,
    _apply_tool_policy,
    _check_tool_names,
    build_server,
)
from capabilities import CAPABILITIES
from config import Settings
from tags import ALL_TAGS


@dataclass
class _Call:
    """One recorded enable/disable call."""

    kind: str  # "enable" | "disable"
    names: set[str] | None = None
    tags: set[str] | None = None
    components: set[str] | None = None


@dataclass
class _FakeMCP:
    """Records the enable/disable calls the policy applies, in order."""

    calls: list[_Call] = field(default_factory=list)

    def enable(self, *, names=None, tags=None, components=None) -> None:
        self.calls.append(_Call("enable", names, tags, components))

    def disable(self, *, names=None, tags=None, components=None) -> None:
        self.calls.append(_Call("disable", names, tags, components))


@dataclass
class _Settings:
    enabled_tools: set[str] = field(default_factory=set)
    disabled_tools: set[str] = field(default_factory=set)
    disabled_tags: set[str] = field(default_factory=set)
    # Capability predicates in CAPABILITIES read these attributes.
    vo_region: str | None = None
    vo_api_key: str | None = None
    vt_api_key: str | None = None
    slack_webhook_url: str | None = None
    # Read by build_server() / _build_auth().
    transport: str = "stdio"
    auth_token: str | None = None
    mask_error_details: bool = True
    # Containment is opt-in; the default here mirrors the real default.
    enable_destructive: bool = False


def test_no_policy_touches_nothing():
    mcp = _FakeMCP()
    _apply_tool_policy(mcp, _Settings())
    assert mcp.calls == []


def test_allowlist_disables_all_then_reenables_listed():
    mcp = _FakeMCP()
    _apply_tool_policy(mcp, _Settings(enabled_tools={"get_alert_list"}))
    assert mcp.calls[0] == _Call("disable", None, None, {"tool"})
    assert mcp.calls[1] == _Call("enable", {"get_alert_list"}, None, None)


def test_denylists_are_applied_after_the_allowlist():
    """A tool named in both lists ends up disabled: the last transform wins."""
    mcp = _FakeMCP()
    settings = _Settings(
        enabled_tools={"isolate_endpoint"},
        disabled_tools={"isolate_endpoint"},
        disabled_tags={"destructive"},
    )
    _apply_tool_policy(mcp, settings)

    kinds = [(c.kind, c.names, c.tags, c.components) for c in mcp.calls]
    assert kinds == [
        ("disable", None, None, {"tool"}),
        ("enable", {"isolate_endpoint"}, None, None),
        ("disable", None, {"destructive"}, None),
        ("disable", {"isolate_endpoint"}, None, None),
    ]


def test_capability_gating_disables_tags_of_unconfigured_integrations():
    mcp = _FakeMCP()
    # Nothing configured => every capability's tags get disabled.
    _apply_capability_gating(mcp, _Settings())
    disabled_tags: set[str] = set()
    for call in mcp.calls:
        assert call.kind == "disable"
        disabled_tags |= call.tags or set()
    expected = set().union(*(cap.tags for cap in CAPABILITIES))
    assert disabled_tags == expected


def test_configured_integration_is_not_gated():
    mcp = _FakeMCP()
    _apply_capability_gating(
        mcp, _Settings(vo_region="https://api.xdr.trendmicro.com", vo_api_key="k")
    )
    gated: set[str] = set()
    for call in mcp.calls:
        gated |= call.tags or set()
    # Vision One is configured, so its tags survive; VT/Slack are still gated.
    assert not gated & {"alerts", "endpoints", "response"}
    assert gated == {"intel", "notify"}


def test_unknown_tool_name_is_rejected_at_startup():
    """A denylist typo must not read as 'switched off' while the tool stays live."""
    known = {"get_alert_list", "isolate_endpoint"}

    with pytest.raises(ValueError, match="MCP_DISABLED_TOOLS names unknown tool"):
        _check_tool_names(_Settings(disabled_tools={"isolate_endpint"}), known)
    with pytest.raises(ValueError, match="MCP_ENABLED_TOOLS names unknown tool"):
        _check_tool_names(_Settings(enabled_tools={"get_alert_lst"}), known)
    # The message names the valid options, so the fix is obvious.
    with pytest.raises(ValueError, match="isolate_endpoint"):
        _check_tool_names(_Settings(disabled_tools={"nope"}), known)

    _check_tool_names(_Settings(disabled_tools={"isolate_endpoint"}), known)  # valid: no raise


def test_unknown_tag_is_rejected_when_settings_load():
    with pytest.raises(ValueError, match="Unknown tag"):
        Settings(MCP_DISABLED_TAGS="destructiv")

    settings = Settings(MCP_DISABLED_TAGS="destructive,write")
    assert settings.disabled_tags == {"destructive", "write"}


def test_blank_flags_fall_back_to_their_defaults():
    """`FLAG=` in a .env is how people leave a value unset; it must not crash."""
    settings = Settings(
        MCP_ENABLE_DESTRUCTIVE="",
        MCP_REQUIRE_APPROVAL="",
        MCP_MASK_ERROR_DETAILS="",
        MCP_ENABLE_HTTP2="",
    )
    assert settings.enable_destructive is False  # secure default preserved
    assert settings.require_approval is True
    assert settings.mask_error_details is True
    assert settings.enable_http2 is True

    # A real value still wins, and a wrong one is still rejected. Enabling
    # containment also requires an operator to attribute the actions to.
    enabled = Settings(MCP_ENABLE_DESTRUCTIVE="true", MCP_OPERATOR_ID="soc.analyst.1")
    assert enabled.enable_destructive is True
    with pytest.raises(ValueError, match="valid boolean"):
        Settings(MCP_ENABLE_DESTRUCTIVE="treu")


def test_capability_tags_stay_inside_the_vocabulary():
    """capabilities.py and the tag vocabulary must not drift apart."""
    for cap in CAPABILITIES:
        assert set(cap.tags) <= ALL_TAGS, f"{cap.name} uses tags outside the vocabulary"


def test_destructive_tools_are_disabled_by_default():
    """A fresh install must not be able to isolate a host or block an IOC."""
    mcp = _FakeMCP()
    _apply_destructive_gating(mcp, _Settings())
    assert mcp.calls == [_Call("disable", None, {"destructive"}, None)]


def test_destructive_tools_require_an_explicit_opt_in():
    mcp = _FakeMCP()
    _apply_destructive_gating(mcp, _Settings(enable_destructive=True))
    assert mcp.calls == []


def test_destructive_opt_out_wins_over_the_allowlist(monkeypatch):
    """An allowlist naming a containment tool must not expose it when it is off."""
    settings = _Settings(enabled_tools={"isolate_endpoint"})
    recorder = _stub_build_server(monkeypatch, settings)

    build_server()

    enable_index = next(i for i, c in enumerate(recorder.calls) if c.kind == "enable")
    gate_index = next(
        i
        for i, c in enumerate(recorder.calls)
        if c.kind == "disable" and "destructive" in (c.tags or set())
    )
    assert gate_index > enable_index, "destructive gating must be applied after the allowlist"


def _stub_build_server(monkeypatch, settings: _Settings) -> _FakeMCP:
    """Run build_server() against a recorder instead of a real FastMCP server."""
    monkeypatch.setattr("app.get_settings", lambda: settings)
    recorder = _FakeMCP()

    class _StubFastMCP:
        def __init__(self, *args, **kwargs) -> None:
            pass

        enable = recorder.enable
        disable = recorder.disable

    monkeypatch.setattr("app.FastMCP", _StubFastMCP)
    # register_all reports which tools exist; build_server validates the policy
    # names against it, so the stub must claim the ones these tests configure.
    monkeypatch.setattr("app.register_all", lambda mcp: {"isolate_endpoint", "get_alert_list"})
    return recorder


def test_missing_credentials_win_over_the_allowlist(monkeypatch):
    """The ordering invariant, asserted end-to-end through build_server().

    An allowlist naming a Vision One tool must NOT resurrect it when VO_API_KEY
    is absent: capability gating has to run last.
    """
    settings = _Settings(enabled_tools={"isolate_endpoint"})
    recorder = _stub_build_server(monkeypatch, settings)

    build_server()

    # The 'response' tag (isolate_endpoint) is disabled by capability gating,
    # and that disable happens AFTER the allowlist re-enabled the tool by name.
    enable_index = next(i for i, c in enumerate(recorder.calls) if c.kind == "enable")
    gate_index = next(
        i
        for i, c in enumerate(recorder.calls)
        if c.kind == "disable" and "response" in (c.tags or set())
    )
    assert gate_index > enable_index, "capability gating must be applied after the allowlist"
