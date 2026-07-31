"""Tests for HTTP bearer-token auth gating (app._build_auth)."""

from __future__ import annotations

from dataclasses import dataclass

from app import _build_auth


@dataclass
class _Settings:
    transport: str
    auth_token: str | None


def test_http_with_token_enables_auth():
    verifier = _build_auth(_Settings(transport="http", auth_token="secret-token"))
    assert verifier is not None


def test_http_without_token_stays_open():
    assert _build_auth(_Settings(transport="http", auth_token=None)) is None


def test_stdio_is_never_gated():
    # stdio is local-only; a token must not force auth on it.
    assert _build_auth(_Settings(transport="stdio", auth_token="secret-token")) is None
