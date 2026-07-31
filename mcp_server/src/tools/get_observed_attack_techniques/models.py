"""Constrained input type for the get_observed_attack_techniques tool."""

from __future__ import annotations

from typing import Literal

RiskLevel = Literal["info", "low", "medium", "high", "critical"]
