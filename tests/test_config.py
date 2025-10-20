from __future__ import annotations

from mcp_vertica import config


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

    fresh = config.Settings()

    assert fresh.max_rows == 1000
    assert fresh.query_timeout_s == 15
    assert fresh.pool_size == 8


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


def test_required_database_env_uses_defaults(monkeypatch, caplog):
    _clear_db_env(monkeypatch)

    with caplog.at_level("WARNING"):
        fresh = config.Settings()

    assert fresh.host == config.DEFAULT_DB_HOST
    assert fresh.port == config.DEFAULT_DB_PORT
    assert fresh.user == config.DEFAULT_DB_USER
    assert fresh.password == config.DEFAULT_DB_PASSWORD
    assert fresh.database == config.DEFAULT_DB_NAME

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
