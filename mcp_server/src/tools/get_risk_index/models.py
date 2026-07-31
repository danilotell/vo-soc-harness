"""Output model for the get_risk_index tool."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RiskIndex(BaseModel):
    risk_index: float = Field(..., alias="riskIndex")

    model_config = {"populate_by_name": True}
