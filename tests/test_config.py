from __future__ import annotations

import importlib

import pytest

from mcp_vertica import config
import mcp_vertica.env as env_module


def _minimal_required_env(monkeypatch):
    monkeypatch.setenv("DB_HOST", "vertica.example.com")
    monkeypatch.setenv("DB_PORT", "5433")
    monkeypatch.setenv("DB_USER", "dbadmin")
    monkeypatch.setenv("DB_PASSWORD", "super-secret")
    monkeypatch.setenv("DB_NAME", "VMart")


def _clear_db_env(monkeypatch):
    for key in ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(f"MCP_{key}", raising=False)


def test_optional_integers_ignore_blank_values(monkeypatch):
    _minimal_required_env(monkeypatch)
    monkeypatch.setenv("MAX_ROWS", " ")
    monkeypatch.setenv("QUERY_TIMEOUT_S", "")
    monkeypatch.setenv("POOL_SIZE", "\n")
    monkeypatch.setenv("DB_CONNECTION_RETRIES", " ")
    monkeypatch.setenv("DB_CONNECTION_RETRY_BACKOFF_S", "")

    fresh = config.Settings()

    assert fresh.max_rows == 1000
    assert fresh.query_timeout_s == 15
    assert fresh.pool_size == 8
    assert fresh.connection_attempts == 3
    assert fresh.connection_retry_backoff_s == 0.5


def test_optional_strings_treat_blank_as_missing(monkeypatch):
    _minimal_required_env(monkeypatch)
    monkeypatch.setenv("HTTP_TOKEN", "")
    monkeypatch.setenv("CORS_ORIGINS", "   ")

    fresh = config.Settings()

    assert fresh.http_token is None
    assert fresh.cors_origins is None


def test_env_helper_prefers_prefixed_values(monkeypatch):
    monkeypatch.delenv("EXAMPLE", raising=False)
    monkeypatch.delenv("MCP_EXAMPLE", raising=False)

    monkeypatch.setenv("MCP_EXAMPLE", "from-prefix")
    monkeypatch.setenv("EXAMPLE", "from-direct")

    assert config._env("EXAMPLE") == "from-direct"
    assert config._env("MISSING", "fallback") == "fallback"
    assert config._env("EXAMPLE", default=None) == "from-direct"


def test_required_database_env_defaults_flag_placeholders(monkeypatch, caplog):
    _clear_db_env(monkeypatch)

    with caplog.at_level("WARNING"):
        fresh = config.Settings()

    assert fresh.host == config.DEFAULT_DB_HOST
    assert fresh.port == config.DEFAULT_DB_PORT
    assert fresh.user == config.DEFAULT_DB_USER
    assert fresh.password == config.DEFAULT_DB_PASSWORD
    assert fresh.database == config.DEFAULT_DB_NAME
    assert fresh.using_placeholder_credentials() is True

    # At least one of the missing variables should have emitted a warning so
    # operators are nudged to provide the correct credentials.
    assert any("falling back to default" in message for message in caplog.messages)


def test_invalid_port_falls_back_to_default(monkeypatch, caplog):
    _minimal_required_env(monkeypatch)
    monkeypatch.setenv("DB_PORT", "not-a-number")

    with caplog.at_level("WARNING"):
        fresh = config.Settings()

    assert fresh.port == config.DEFAULT_DB_PORT
    assert any("invalid integer value" in message for message in caplog.messages)


def test_debug_flags_and_retries(monkeypatch):
    _minimal_required_env(monkeypatch)
    monkeypatch.setenv("DB_CONNECTION_RETRIES", "5")
    monkeypatch.setenv("DB_CONNECTION_RETRY_BACKOFF_S", "1.25")
    monkeypatch.setenv("DB_DEBUG", "true")

    fresh = config.Settings()

    assert fresh.connection_attempts == 5
    assert fresh.connection_retry_backoff_s == 1.25
    assert fresh.db_debug_logging is True


def test_invalid_retry_values_raise(monkeypatch):
    _minimal_required_env(monkeypatch)
    monkeypatch.setenv("DB_CONNECTION_RETRIES", "0")

    with pytest.raises(config.ValidationError):
        config.Settings()

    monkeypatch.setenv("DB_CONNECTION_RETRIES", "2")
    monkeypatch.setenv("DB_CONNECTION_RETRY_BACKOFF_S", "-1")

    with pytest.raises(config.ValidationError):
        config.Settings()


def test_config_import_requires_dotenv(monkeypatch):
    original = env_module.ensure_dotenv

    def missing_dotenv():
        raise FileNotFoundError("missing .env")

    monkeypatch.setattr(env_module, "ensure_dotenv", missing_dotenv)

    with pytest.raises(FileNotFoundError):
        importlib.reload(config)

    # Restore the original loader so later tests re-import configuration safely.
    monkeypatch.setattr(env_module, "ensure_dotenv", original)
    importlib.reload(config)


def test_database_overrides_update_settings(monkeypatch):
    _minimal_required_env(monkeypatch)
    fresh = config.Settings()

    overrides = config.DatabaseOverrides(
        host="runtime.vertica.example.com",
        port=5434,
        user="runtime-user",
        password="runtime-secret",
        database="RuntimeMart",
    )

    assert fresh.database_source == "environment"

    fresh.apply_database_overrides(overrides)

    assert fresh.host == overrides.host
    assert fresh.port == overrides.port
    assert fresh.user == overrides.user
    assert fresh.password == overrides.password
    assert fresh.database == overrides.database
    assert fresh.database_source == "runtime"
    assert fresh.using_placeholder_credentials() is False


def test_reload_from_environment_restores_source(monkeypatch):
    _minimal_required_env(monkeypatch)
    fresh = config.Settings()

    overrides = config.DatabaseOverrides(
        host="runtime.example.com",
        port=6000,
        user="runtime",
        password="override",
        database="runtime",
    )
    fresh.apply_database_overrides(overrides)
    assert fresh.database_source == "runtime"

    fresh.reload_from_environment()

    assert fresh.host == "vertica.example.com"
    assert fresh.port == 5433
    assert fresh.user == "dbadmin"
    assert fresh.password == "super-secret"
    assert fresh.database == "VMart"
    assert fresh.database_source == "environment"
