"""Centralised configuration for the Vertica MCP service.

All runtime tuning is sourced from environment variables so the service can be
deployed safely across environments.  Every consumer of configuration should go
through this module to avoid duplicated parsing logic.
"""

from __future__ import annotations

import logging
import os
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .env import ensure_dotenv


LOGGER = logging.getLogger(__name__)


# Load the shared .env file before reading configuration so we never fall back
# to placeholder defaults when the project-wide environment definition is
# missing.  ``ensure_dotenv`` will abort early with a clear error message if the
# file cannot be located or parsed.
ensure_dotenv()


# Defaults mirror the Terraform variables defined in ``infra/variables.tf`` so a
# freshly provisioned environment can still bring the service online even if
# the operator forgets to override the database settings.  The service will run
# in a degraded mode (health checks will fail) until the real Vertica
# connection details are supplied, but the HTTP endpoints remain available for
# diagnostics instead of exiting during import time.
# Use the loopback address as the baked-in default so operators must provide a
# real Vertica endpoint via environment variables or Terraform before the
# service attempts any remote connections. This keeps accidental deployments
# from pointing at someone else's database when configuration is incomplete.
DEFAULT_DB_HOST = "127.0.0.1"
DEFAULT_DB_PORT = 5433
DEFAULT_DB_USER = "mcp_app"
DEFAULT_DB_PASSWORD = "change-me-please"
DEFAULT_DB_NAME = "vertica"


def _env(key: str, default: str | None = None) -> str | None:
    """Read environment variables with an ``MCP_`` prefix fallback.

    Empty strings are treated the same as an unset variable so callers can rely
    on sensible defaults when operators intentionally clear optional
    configuration values.
    """

    value = os.getenv(key)
    if value is None:
        value = os.getenv(f"MCP_{key}")

    if value is None:
        return default

    if value.strip() == "":
        return default

    return value


def _log_default(key: str, default: str, reason: str) -> None:
    LOGGER.warning(
        "%s is not configured (%s); falling back to default %r.",
        key,
        reason,
        default,
    )


def _env_or_default(key: str, default: str, *, warn: bool = True) -> str:
    value = _env(key)
    if value is None:
        if warn:
            _log_default(key, default, "missing")
        return default
    return value


def _env_int_or_default(
    key: str,
    default: int,
    *,
    warn_missing: bool = True,
    warn_invalid: bool = True,
) -> int:
    value = _env(key)
    if value is None:
        if warn_missing:
            _log_default(key, str(default), "missing")
        return default

    try:
        return int(value)
    except ValueError:
        if warn_invalid:
            _log_default(key, str(default), f"invalid integer value {value!r}")
        return default


def _split_csv(value: str | None, fallback: Iterable[str]) -> list[str]:
    if not value:
        return list(fallback)
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    host: str = Field(
        default_factory=lambda: _env_or_default("DB_HOST", DEFAULT_DB_HOST)
    )
    port: int = Field(
        default_factory=lambda: _env_int_or_default("DB_PORT", DEFAULT_DB_PORT)
    )
    user: str = Field(
        default_factory=lambda: _env_or_default("DB_USER", DEFAULT_DB_USER)
    )
    password: str = Field(
        default_factory=lambda: _env_or_default("DB_PASSWORD", DEFAULT_DB_PASSWORD)
    )
    database: str = Field(
        default_factory=lambda: _env_or_default("DB_NAME", DEFAULT_DB_NAME)
    )

    max_rows: int = Field(
        default_factory=lambda: _env_int_or_default("MAX_ROWS", 1000, warn_missing=False)
    )
    query_timeout_s: int = Field(
        default_factory=lambda: _env_int_or_default(
            "QUERY_TIMEOUT_S", 15, warn_missing=False
        )
    )
    pool_size: int = Field(
        default_factory=lambda: _env_int_or_default("POOL_SIZE", 8, warn_missing=False)
    )

    http_token: str | None = Field(default_factory=lambda: _env("HTTP_TOKEN"))
    cors_origins: str | None = Field(default_factory=lambda: _env("CORS_ORIGINS"))

    allowed_schemas: list[str] = Field(
        default_factory=lambda: _split_csv(_env("ALLOWED_SCHEMAS"), ["public"])
    )

    @field_validator("allowed_schemas")
    @classmethod
    def _validate_schemas(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("At least one allowed schema must be configured")
        return value

    @property
    def default_schema(self) -> str:
        return self.allowed_schemas[0]

    def allowed_schema_set(self) -> set[str]:
        return {schema.lower() for schema in self.allowed_schemas}

    def using_placeholder_credentials(self) -> bool:
        """Return ``True`` when the Vertica credentials look like repo defaults."""

        return (
            self.host == DEFAULT_DB_HOST
            and self.user == DEFAULT_DB_USER
            and self.password == DEFAULT_DB_PASSWORD
            and self.database == DEFAULT_DB_NAME
        )


try:
    settings = Settings()
except ValidationError as exc:  # pragma: no cover - startup configuration must succeed
    logging.basicConfig(level=logging.ERROR)
    LOGGER.error("Critical configuration validation failed: %s", exc)
    raise
