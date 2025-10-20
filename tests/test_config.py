from __future__ import annotations

from mcp_vertica import config


def _minimal_required_env(monkeypatch):
    monkeypatch.setenv("DB_HOST", "vertica.example.com")
    monkeypatch.setenv("DB_PORT", "5433")
    monkeypatch.setenv("DB_USER", "dbadmin")
    monkeypatch.setenv("DB_PASSWORD", "super-secret")
    monkeypatch.setenv("DB_NAME", "VMart")


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
