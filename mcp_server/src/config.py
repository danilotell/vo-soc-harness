"""
Configuration for the Custom Vision One MCP server.

Settings are loaded from environment variables (and an optional ``.env`` file
living next to this module) and validated up-front with pydantic-settings, so a
misconfigured server fails fast at startup instead of mid-request.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from tags import ALL_TAGS

_ENV_FILE = Path(__file__).parent / ".env"

# Clone root: src/ -> mcp_server/ -> repo. Relative paths in .env are anchored
# here rather than to the process CWD, which is `mcp_server/` because the server
# is launched as `uv run --directory mcp_server ...`.
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Validated runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Credentials & upstream endpoints -------------------------------
    # All optional: a missing credential disables only the tools that need it,
    # the server still starts. An empty string is treated as "not configured".
    # `repr=False` on every secret: a Settings repr shows up in tracebacks and error
    # reports, and would leak a live credential.
    vo_region: str | None = Field(default=None, description="Vision One regional API base URL.")
    vo_api_key: str | None = Field(
        default=None, repr=False, description="Vision One API key (bearer token)."
    )
    vt_api_key: str | None = Field(default=None, repr=False, description="VirusTotal API key.")
    slack_webhook_url: str | None = Field(
        default=None, repr=False, description="Slack incoming webhook URL."
    )
    vt_base_url: str = Field(default="https://www.virustotal.com/api/v3")

    # --- Transport ------------------------------------------------------
    transport: Literal["stdio", "http"] = Field(default="stdio", validation_alias="MCP_TRANSPORT")
    http_host: str = Field(default="127.0.0.1", validation_alias="MCP_HTTP_HOST")
    http_port: int = Field(default=8000, validation_alias="MCP_HTTP_PORT", ge=1, le=65535)
    # Bearer token required on the HTTP transport. Empty => HTTP is unauthenticated
    # (a startup warning is logged). Ignored for stdio, which is local-only.
    auth_token: str | None = Field(default=None, repr=False, validation_alias="MCP_AUTH_TOKEN")

    # --- Observability --------------------------------------------------
    log_level: str = Field(default="INFO", validation_alias="MCP_LOG_LEVEL")
    # If set, audit records for destructive actions are written (JSON lines, with
    # rotation) to this file ONLY, kept out of the app log stream. If unset they
    # propagate to stderr with the rest of the logs.
    audit_log_file: str | None = Field(default=None, validation_alias="MCP_AUDIT_LOG_FILE")
    mask_error_details: bool = Field(default=True, validation_alias="MCP_MASK_ERROR_DETAILS")
    # Who is operating this server, stamped on every audit record. Required once
    # containment is enabled: an audit trail that cannot say who authorised an
    # isolation does not answer the question it exists to answer. Self-declared,
    # so the records also carry the host and OS user, which configuration alone
    # cannot forge (see audit.py).
    operator_id: str | None = Field(default=None, validation_alias="MCP_OPERATOR_ID")

    # --- Human-in-the-loop ----------------------------------------------
    # Destructive tools are NOT exposed unless this is explicitly turned on, so a
    # fresh install cannot contain anything by accident. Independent of the
    # MCP_DISABLED_* denylists on purpose: enabling containment must be a
    # deliberate act, not a side effect of editing an unrelated CSV.
    enable_destructive: bool = Field(default=False, validation_alias="MCP_ENABLE_DESTRUCTIVE")

    # Whether the SERVER must obtain the approval itself (via MCP elicitation).
    # true (default): refuse the action if the client cannot ask a human.
    # false: accept the client's own approval gate when the client cannot be
    #   asked — every such call is audited as `approval_delegated`. Clients that
    #   DO support elicitation are still asked by the server either way.
    require_approval: bool = Field(default=True, validation_alias="MCP_REQUIRE_APPROVAL")

    # --- HTTP client tuning ---------------------------------------------
    connect_timeout: float = Field(default=10.0, ge=0.1)
    request_timeout: float = Field(default=30.0, ge=0.1)
    max_connections: int = Field(default=50, ge=1)
    max_keepalive_connections: int = Field(default=20, ge=1)
    enable_http2: bool = Field(default=True, validation_alias="MCP_ENABLE_HTTP2")
    max_retries: int = Field(default=3, ge=0, le=10)
    backoff_base: float = Field(default=0.5, ge=0.0)
    backoff_max: float = Field(default=8.0, ge=0.0)

    # --- Pagination safety ----------------------------------------------
    max_pages: int = Field(default=50, ge=1, le=1000)

    # --- Tool activation policy -----------------------------------------
    # Comma-separated. ``enabled_tools`` is an allowlist (if set, ONLY those
    # tools are active). ``disabled_tools`` / ``disabled_tags`` are denylists
    # applied afterwards, so they always win over the allowlist.
    enabled_tools_raw: str = Field(default="", validation_alias="MCP_ENABLED_TOOLS")
    disabled_tools_raw: str = Field(default="", validation_alias="MCP_DISABLED_TOOLS")
    disabled_tags_raw: str = Field(default="", validation_alias="MCP_DISABLED_TAGS")

    @staticmethod
    def _csv_to_set(value: str) -> set[str]:
        return {item.strip() for item in value.split(",") if item.strip()}

    @property
    def enabled_tools(self) -> set[str]:
        return self._csv_to_set(self.enabled_tools_raw)

    @property
    def disabled_tools(self) -> set[str]:
        return self._csv_to_set(self.disabled_tools_raw)

    @property
    def disabled_tags(self) -> set[str]:
        return self._csv_to_set(self.disabled_tags_raw)

    @field_validator(
        "vo_api_key",
        "vt_api_key",
        "slack_webhook_url",
        "auth_token",
        "audit_log_file",
        "operator_id",
        mode="before",
    )
    @classmethod
    def _empty_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return str(value).strip() or None

    @field_validator("audit_log_file", mode="after")
    @classmethod
    def _anchor_audit_path(cls, value: str | None) -> str | None:
        """Resolve a relative audit path against the clone root, not the CWD.

        ``MCP_AUDIT_LOG_FILE=audit/vo-audit.log`` therefore resolves to
        ``<clone>/audit/vo-audit.log`` independently of the launching directory,
        which is where the setup scripts create it. Absolute paths pass through
        unchanged.
        """
        if value is None:
            return None
        path = Path(value)
        return str(path if path.is_absolute() else _REPO_ROOT / path)

    @field_validator("vo_region", mode="before")
    @classmethod
    def _optional_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = str(value).strip()
        if not value:
            return None
        if not value.startswith(("http://", "https://")):
            raise ValueError(f"Expected an http(s) URL, got: {value!r}")
        return value.rstrip("/")

    @field_validator("vt_base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith(("http://", "https://")):
            raise ValueError(f"Expected an http(s) URL, got: {value!r}")
        return value.rstrip("/")

    @field_validator(
        "enable_destructive",
        "require_approval",
        "mask_error_details",
        "enable_http2",
        mode="before",
    )
    @classmethod
    def _blank_flag_means_default(cls, value: object, info: ValidationInfo) -> object:
        """Treat an empty ``FLAG=`` in a .env as "use the default", not as an error."""
        if isinstance(value, str) and not value.strip():
            assert info.field_name is not None
            return cls.model_fields[info.field_name].default
        return value

    @model_validator(mode="after")
    def _containment_requires_an_operator(self) -> Settings:
        """Refuse to enable containment without a declared operator.

        Every containment action is recorded, but a record that cannot name who
        authorised it does not answer the question the audit trail exists to
        answer. Enforced at startup, like the rest of the configuration, so the
        gap cannot be discovered during an incident.
        """
        if self.enable_destructive and not self.operator_id:
            raise ValueError(
                "MCP_ENABLE_DESTRUCTIVE=true requires MCP_OPERATOR_ID: response actions "
                "must be attributable to a person in the audit trail."
            )
        return self

    @field_validator("disabled_tags_raw")
    @classmethod
    def _known_tags_only(cls, value: str) -> str:
        """Reject unknown tags instead of letting them match nothing.

        A denylist typo is the dangerous kind of mistake: without this,
        ``MCP_DISABLED_TAGS=destructiv`` looks like it locked the server down
        while leaving every containment tool exposed.
        """
        unknown = cls._csv_to_set(value) - ALL_TAGS
        if unknown:
            raise ValueError(
                f"Unknown tag(s): {', '.join(sorted(unknown))}. "
                f"Valid tags: {', '.join(sorted(ALL_TAGS))}."
            )
        return value

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"Invalid log level: {value!r}")
        return level


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the validated settings singleton (cached for the process)."""
    return Settings()
