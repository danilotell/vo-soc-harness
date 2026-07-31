"""Tests for tool autodiscovery: completeness, declarations, fault isolation."""

from __future__ import annotations

import importlib

from tags import ACCESS_TAGS, ALL_TAGS, INTEGRATION_TAGS
from tools import register_all

EXPECTED_TOOLS = {
    "get_risk_index",
    "get_alert_list",
    "get_alert_details",
    "modify_alert_status",
    "add_alert_note",
    "get_observed_attack_techniques",
    "get_endpoint_details",
    "isolate_endpoint",
    "add_to_block_list",
    "get_ioc_reputation",
    "send_slack_summary",
    "get_server_capabilities",
}


class _FakeMCP:
    """Captures what every tool declares: its name, annotations and tags."""

    def __init__(self):
        self.tools: list[str] = []
        self.declared: dict[str, dict] = {}

    def tool(self, *_args, **kwargs):
        def decorator(fn):
            self.tools.append(fn.__name__)
            self.declared[fn.__name__] = kwargs
            return fn

        return decorator


def test_registers_every_tool_and_skips_template():
    mcp = _FakeMCP()
    registered = register_all(mcp)
    assert set(mcp.tools) == EXPECTED_TOOLS
    assert "my_new_tool" not in mcp.tools  # _template must be skipped
    assert len(mcp.tools) == len(set(mcp.tools))  # no duplicates
    # The returned names are what validates MCP_ENABLED_TOOLS / MCP_DISABLED_TOOLS,
    # so a tool package must be named after the tool it declares.
    assert registered == EXPECTED_TOOLS


def test_every_tool_declares_a_known_integration_and_access_level():
    mcp = _FakeMCP()
    register_all(mcp)

    for name, declaration in mcp.declared.items():
        tags = declaration["tags"]
        assert tags <= ALL_TAGS, f"{name} uses tags outside the vocabulary: {tags - ALL_TAGS}"
        assert len(tags & INTEGRATION_TAGS) == 1, f"{name} needs exactly one integration tag"
        assert tags & ACCESS_TAGS, f"{name} declares no access level"


def test_annotations_and_tags_cannot_disagree():
    """The client-facing hint and the tag this server gates on must say the same.

    A containment tool that advertises `destructiveHint` but forgets the
    `destructive` tag would look dangerous to the client while escaping
    MCP_ENABLE_DESTRUCTIVE — so the two are asserted to match for every tool.
    """
    mcp = _FakeMCP()
    register_all(mcp)

    for name, declaration in mcp.declared.items():
        annotations, tags = declaration["annotations"], declaration["tags"]
        is_destructive = annotations.get("destructiveHint", False)
        is_read_only = annotations.get("readOnlyHint", False)

        assert is_destructive == ("destructive" in tags), f"{name}: hint vs tag mismatch"
        assert is_read_only == ("read" in tags), f"{name}: readOnlyHint vs 'read' tag mismatch"
        # A read cannot mutate, and anything that can must be tagged as writing.
        assert is_read_only != ("write" in tags), f"{name}: read/write declaration conflict"


def test_one_failing_tool_does_not_crash_the_rest(monkeypatch):
    real_import = importlib.import_module

    def flaky_import(name, *args, **kwargs):
        if name.endswith(".isolate_endpoint"):

            class _Boom:
                @staticmethod
                def register(_mcp):
                    raise RuntimeError("simulated bad tool")

            return _Boom
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", flaky_import)

    mcp = _FakeMCP()
    register_all(mcp)  # must NOT raise

    assert "isolate_endpoint" not in mcp.tools  # the broken tool was skipped
    assert "get_alert_list" in mcp.tools  # the rest still registered
