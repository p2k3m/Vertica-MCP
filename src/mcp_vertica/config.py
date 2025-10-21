"""Centralised configuration for the Vertica MCP service.

All runtime tuning is sourced from environment variables so the service can be
deployed safely across environments.  Every consumer of configuration should go
through this module to avoid duplicated parsing logic.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Iterable

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
)
from pydantic.fields import PrivateAttr

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


def _env_float_or_default(
    key: str,
    default: float,
    *,
    warn_missing: bool = True,
    warn_invalid: bool = True,
) -> float:
    value = _env(key)
    if value is None:
        if warn_missing:
            _log_default(key, str(default), "missing")
        return default

    try:
        return float(value)
    except ValueError:
        if warn_invalid:
            _log_default(key, str(default), f"invalid float value {value!r}")
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    value = _env(key)
    if value is None:
        return default

    candidate = value.strip().lower()
    if candidate in {"1", "true", "yes", "on"}:
        return True
    if candidate in {"0", "false", "no", "off"}:
        return False

    _log_default(key, str(default), f"invalid boolean value {value!r}")
    return default


def _split_csv(value: str | None, fallback: Iterable[str]) -> list[str]:
    if not value:
        return list(fallback)
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_backup_nodes(raw: str | None) -> list[tuple[str, int]]:
    """Return backup Vertica hosts parsed from ``DB_BACKUP_NODES``."""

    if not raw:
        return []

    nodes: list[tuple[str, int]] = []
    for entry in raw.split(","):
        candidate = entry.strip()
        if not candidate:
            continue

        if ":" in candidate:
            host_part, port_part = candidate.rsplit(":", 1)
            host = host_part.strip()
            port_text = port_part.strip()
            if not host:
                raise ValueError(
                    "DB_BACKUP_NODES entries must include a hostname before the colon"
                )
            if not port_text:
                raise ValueError(
                    "DB_BACKUP_NODES entries must include a port number after the colon"
                )
            try:
                port = int(port_text)
            except ValueError as exc:  # pragma: no cover - defensive parsing
                raise ValueError(
                    "DB_BACKUP_NODES port values must be integers"
                ) from exc
        else:
            host = candidate
            port = DEFAULT_DB_PORT

        if not host:
            raise ValueError("DB_BACKUP_NODES entries must not be empty")

        if not 1 <= port <= 65535:
            raise ValueError("DB_BACKUP_NODES ports must be between 1 and 65535")

        nodes.append((host, port))

    return nodes


class DatabaseOverrides(BaseModel):
    """Runtime database configuration supplied via the API."""

    model_config = ConfigDict(extra="forbid")

    host: str
    port: int = Field(ge=1, le=65535)
    user: str
    password: str
    database: str

    @field_validator("host", "user", "password", "database", mode="before")
    @classmethod
    def _coerce_non_empty(cls, value: Any, info: ValidationInfo) -> str:
        if value is None:
            raise ValueError(f"{info.field_name.replace('_', ' ')} must not be empty")

        candidate = str(value).strip()
        if not candidate:
            raise ValueError(f"{info.field_name.replace('_', ' ')} must not be empty")
        return candidate


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_default=True)

    _database_source: str = PrivateAttr(default="environment")

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

    connection_attempts: int = Field(
        default_factory=lambda: _env_int_or_default(
            "DB_CONNECTION_RETRIES", 3, warn_missing=False
        ),
        ge=1,
    )
    connection_retry_backoff_s: float = Field(
        default_factory=lambda: _env_float_or_default(
            "DB_CONNECTION_RETRY_BACKOFF_S", 0.5, warn_missing=False
        ),
        ge=0,
    )

    http_token: str | None = Field(default_factory=lambda: _env("HTTP_TOKEN"))
    cors_origins: str | None = Field(default_factory=lambda: _env("CORS_ORIGINS"))

    allowed_schemas: list[str] = Field(
        default_factory=lambda: _split_csv(_env("ALLOWED_SCHEMAS"), ["public"])
    )

    db_debug_logging: bool = Field(
        default_factory=lambda: _env_bool("DB_DEBUG", default=False)
    )

    backup_nodes: list[tuple[str, int]] = Field(
        default_factory=lambda: _parse_backup_nodes(_env("DB_BACKUP_NODES"))
    )

    tls_mode: str | None = Field(
        default_factory=lambda: _env("DB_TLSMODE")
    )
    use_ssl: bool | None = Field(
        default_factory=lambda: _env("DB_USE_SSL")
    )
    tls_cafile: str | None = Field(default_factory=lambda: _env("DB_TLS_CAFILE"))
    tls_certfile: str | None = Field(
        default_factory=lambda: _env("DB_TLS_CERTFILE")
    )
    tls_keyfile: str | None = Field(default_factory=lambda: _env("DB_TLS_KEYFILE"))

    def model_post_init(self, __context: Any) -> None:  # pragma: no cover - simple assignment
        self._database_source = "environment"

    @field_validator("allowed_schemas")
    @classmethod
    def _validate_schemas(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("At least one allowed schema must be configured")
        return value

    @field_validator("tls_mode", mode="before")
    @classmethod
    def _validate_tls_mode(cls, value: Any) -> str | None:
        if value is None:
            return None

        candidate = str(value).strip().lower()
        if not candidate:
            return None

        allowed = {
            "disable",
            "allow",
            "prefer",
            "require",
            "verify-ca",
            "verify-full",
        }
        if candidate not in allowed:
            raise ValueError(
                "DB_TLSMODE must be one of disable, allow, prefer, require, verify-ca, verify-full"
            )
        return candidate

    @field_validator("use_ssl", mode="before")
    @classmethod
    def _validate_use_ssl(cls, value: Any) -> bool | None:
        if value is None or isinstance(value, bool):
            return value

        candidate = str(value).strip().lower()
        if not candidate:
            return None

        if candidate in {"1", "true", "yes", "on"}:
            return True
        if candidate in {"0", "false", "no", "off"}:
            return False

        raise ValueError("DB_USE_SSL must be a boolean value")

    @field_validator("tls_cafile", "tls_certfile", "tls_keyfile", mode="before")
    @classmethod
    def _validate_optional_path(cls, value: Any) -> str | None:
        if value is None:
            return None

        candidate = str(value).strip()
        if not candidate:
            return None
        return candidate

    @field_validator("backup_nodes", mode="before")
    @classmethod
    def _validate_backup_nodes(cls, value: Any) -> list[tuple[str, int]]:
        if value is None:
            return []

        if isinstance(value, list):
            normalised: list[tuple[str, int]] = []
            for item in value:
                if isinstance(item, tuple) and len(item) == 2:
                    host, port = item
                elif isinstance(item, dict):
                    host = item.get("host")
                    port = item.get("port")
                else:
                    raise ValueError(
                        "DB_BACKUP_NODES must be a comma-separated list of host[:port] entries"
                    )

                if host is None or str(host).strip() == "":
                    raise ValueError(
                        "DB_BACKUP_NODES entries must include a hostname before the colon"
                    )
                try:
                    port_int = int(port)
                except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
                    raise ValueError("DB_BACKUP_NODES port values must be integers") from exc

                if not 1 <= port_int <= 65535:
                    raise ValueError(
                        "DB_BACKUP_NODES ports must be between 1 and 65535"
                    )

                normalised.append((str(host).strip(), port_int))
            return normalised

        if isinstance(value, str):
            return _parse_backup_nodes(value)

        raise ValueError(
            "DB_BACKUP_NODES must be provided as a comma-separated string"
        )

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

    @property
    def database_source(self) -> str:
        return self._database_source

    def apply_database_overrides(self, overrides: DatabaseOverrides) -> None:
        """Apply runtime database configuration provided via the HTTP API."""

        data = overrides.model_dump()
        updated = self.model_copy(update=data)

        for key in ("host", "port", "user", "password", "database"):
            object.__setattr__(self, key, getattr(updated, key))

        self._database_source = "runtime"

    def reload_from_environment(self) -> None:
        """Refresh configuration from environment variables."""

        refreshed = type(self)()

        for key, value in refreshed.model_dump().items():
            object.__setattr__(self, key, value)

        self._database_source = refreshed.database_source

    def vertica_connection_options(self) -> dict[str, Any]:
        """Return keyword arguments for :func:`vertica_python.connect`."""

        options: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
            "connection_timeout": 5,
            "autocommit": True,
        }

        if self.backup_nodes:
            options["backup_server_node"] = [
                (host, port) for host, port in self.backup_nodes
            ]

        if self.tls_mode:
            options["tlsmode"] = self.tls_mode

        if self.tls_cafile:
            options["tls_cafile"] = self.tls_cafile

        if self.tls_certfile:
            options["tls_certfile"] = self.tls_certfile

        if self.tls_keyfile:
            options["tls_keyfile"] = self.tls_keyfile

        if self.use_ssl is not None:
            options["ssl"] = self.use_ssl

        return options


try:
    settings = Settings()
except ValidationError as exc:  # pragma: no cover - startup configuration must succeed
    logging.basicConfig(level=logging.ERROR)
    LOGGER.error("Critical configuration validation failed: %s", exc)
    raise
