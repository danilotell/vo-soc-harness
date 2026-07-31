"""Output model for the get_alert_list tool."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AlertSummary(BaseModel):
    """Summarized Workbench alert as returned by ``get_alert_list``."""

    id: str
    model: str | None = None
    description: str | None = None
    status: str | None = None
    score: float | None = None
    severity: str | None = None
    created_date_time: str | None = Field(default=None, alias="createdDateTime")
    workbench_link: str | None = Field(default=None, alias="workbenchLink")

    model_config = {"populate_by_name": True}

    @classmethod
    def from_api(cls, item: dict) -> AlertSummary:
        return cls(
            id=item.get("id", ""),
            model=item.get("model"),
            description=item.get("description"),
            status=item.get("status"),
            score=item.get("score"),
            severity=item.get("severity"),
            createdDateTime=item.get("createdDateTime"),
            workbenchLink=item.get("workbenchLink"),
        )
