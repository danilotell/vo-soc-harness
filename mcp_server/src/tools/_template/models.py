"""
Input/output models for the template tool — DELETE this file if your tool has
no models (it returns a plain dict / str).

  * Constrained inputs: use ``typing.Literal`` to restrict argument values at
    the protocol boundary, e.g. ``Status = Literal["open", "closed"]``.

  * Output projection (RECOMMENDED for verbose API responses): declare ONLY the
    fields you want and validate the raw payload against the model. Pydantic v2
    ignores unknown fields by default, so the model acts as a field whitelist —
    keeping the response small and predictable for the LLM. See
    ``tools/README.md`` → "Shaping output".

When you genuinely need the WHOLE upstream response (rich forensic detail,
free-form structures), skip the model and return ``dict[str, Any]`` from the
tool — that is a deliberate, documented opt-out, not a smell.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExampleOutput(BaseModel):
    """A projection of an upstream API object — only the declared fields survive.

    ``extra="ignore"`` is the Pydantic default; stating it documents intent.
    Use ``alias=`` to map the API's camelCase to snake_case attributes.
    """

    id: str
    display_name: str | None = Field(default=None, alias="displayName")

    model_config = {"populate_by_name": True, "extra": "ignore"}
