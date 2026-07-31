"""Offline unit tests for the input validators / filter escaping.

These guard a security boundary (values flow into URL paths and the
``TMV1-Filter`` header), so they must run with no network or credentials.
"""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError

from filters import (
    quote_filter_value,
    validate_alert_id,
    validate_endpoint_name,
    validate_ioc,
)


def test_quote_filter_value_escapes_single_quotes():
    assert quote_filter_value("a'b") == "'a''b'"
    assert quote_filter_value("plain") == "'plain'"


def test_validate_endpoint_name_accepts_valid():
    assert validate_endpoint_name(" EC2-AMAZ.local_1 ") == "EC2-AMAZ.local_1"


@pytest.mark.parametrize("bad", ["", "   ", "-bad", "a/b", "a b", "x" * 300])
def test_validate_endpoint_name_rejects_invalid(bad):
    with pytest.raises(ToolError):
        validate_endpoint_name(bad)


def test_validate_alert_id_accepts_valid():
    assert validate_alert_id("WB-14-20190709-00021") == "WB-14-20190709-00021"


@pytest.mark.parametrize("bad", ["", "ALERT-1", "wb-1", "WB ", "WB-" + "x" * 100])
def test_validate_alert_id_rejects_invalid(bad):
    with pytest.raises(ToolError):
        validate_alert_id(bad)


def test_validate_ioc_accepts_and_strips():
    assert validate_ioc("  8.8.8.8  ") == "8.8.8.8"


@pytest.mark.parametrize("bad", ["", "a\nb", "a\tb", "a\rb", "x" * 3000])
def test_validate_ioc_rejects_invalid(bad):
    with pytest.raises(ToolError):
        validate_ioc(bad)
