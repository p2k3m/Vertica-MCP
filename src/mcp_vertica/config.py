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


LOGGER = logging.getLogger(__name__)


def _env(key: str, default: str | None = None) -> str | None:
    """Read environment variables with an ``MCP_`` prefix fallback."""

    return os.getenv(key, os.getenv(f"MCP_{key}", default))


def _require_env(key: str) -> str:
    value = _env(key)
    if value is None or value.strip() == "":
        raise ValueError(f"Missing required environment variable: {key}")
    return value


def _split_csv(value: str | None, fallback: Iterable[str]) -> list[str]:
    if not value:
        return list(fallback)
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    host: str = Field(default_factory=lambda: _require_env("DB_HOST"))
    port: int = Field(default_factory=lambda: int(_require_env("DB_PORT")))
    user: str = Field(default_factory=lambda: _require_env("DB_USER"))
    password: str = Field(default_factory=lambda: _require_env("DB_PASSWORD"))
    database: str = Field(default_factory=lambda: _require_env("DB_NAME"))

    max_rows: int = Field(default_factory=lambda: int(_env("MAX_ROWS", "1000")))
    query_timeout_s: int = Field(
        default_factory=lambda: int(_env("QUERY_TIMEOUT_S", "15"))
    )
    pool_size: int = Field(default_factory=lambda: int(_env("POOL_SIZE", "8")))

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


try:
    settings = Settings()
except ValidationError as exc:  # pragma: no cover - startup configuration must succeed
    logging.basicConfig(level=logging.ERROR)
    LOGGER.error("Critical configuration validation failed: %s", exc)
    raise
