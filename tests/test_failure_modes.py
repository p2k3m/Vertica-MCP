"""Failure scenario coverage for Vertica MCP runtime."""
from __future__ import annotations

import importlib
from urllib.error import URLError

import pytest

from mcp_vertica import logging_utils, runtime, server


def test_health_response_failed_db_connection_includes_recent_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failed Vertica connectivity should surface through the health payload."""

    logging_utils.clear_error_history()

    def failing_check() -> dict[str, object]:
        logging_utils.record_service_error(source="database", message="no connection")
        return {
            "ok": False,
            "pool": {},
            "target": {},
            "error": "no connection",
        }

    monkeypatch.setattr(server, "_database_check", failing_check)

    payload = server._health_response(ping_vertica=True)

    assert payload["ok"] is False
    assert payload["checks"]["database"]["error"] == "no connection"
    assert payload["errors"]
    assert payload["errors"][0]["message"] == "no connection"

    logging_utils.clear_error_history()


def test_config_import_errors_without_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing configuration should fail loudly when the .env file is missing."""

    import mcp_vertica.config as config_module
    import mcp_vertica.env as env_module

    def fake_ensure() -> None:
        raise FileNotFoundError("missing test .env")

    monkeypatch.setattr(config_module, "ensure_dotenv", fake_ensure)
    monkeypatch.setattr(env_module, "ensure_dotenv", fake_ensure)

    with pytest.raises(FileNotFoundError):
        importlib.reload(config_module)

    monkeypatch.undo()
    importlib.reload(env_module)
    importlib.reload(config_module)


def test_resolve_port_override_rejects_invalid_port() -> None:
    """CLI overrides outside the TCP range should abort startup."""

    with pytest.raises(SystemExit) as excinfo:
        server._resolve_port_override(70000)

    assert "valid TCP port range" in str(excinfo.value)


def test_database_check_reports_placeholder_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Placeholder credentials must force the database check to fail."""

    monkeypatch.setattr(
        server.settings.__class__,
        "using_placeholder_credentials",
        lambda self: True,
    )

    result = server._database_check()

    assert result["ok"] is False
    assert result["placeholder_credentials"] is True
    assert "placeholder" in result["error"].lower()


def test_external_ip_info_handles_unreachable_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """External IP discovery should tolerate unreachable endpoints."""

    def offline_urlopen(url: str, timeout: float):  # pragma: no cover - helper only
        raise URLError("offline")

    monkeypatch.setattr(runtime, "urlopen", offline_urlopen)

    result = runtime.external_ip_info(timeout=0.01)

    assert result["ok"] is False
    assert result["errors"]
    assert result["errors"][0]["exception"] == "URLError"


def test_health_response_skips_vertica_when_not_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without ping-vertica the health payload should skip expensive checks."""

    logging_utils.clear_error_history()
    logging_utils.record_service_error(source="health", message="scheduled health check missed")

    def unexpected_call() -> dict[str, object]:  # pragma: no cover - guard
        raise AssertionError("database check should not run when ping-vertica is false")

    monkeypatch.setattr(server, "_database_check", unexpected_call)

    payload = server._health_response(ping_vertica=False)

    assert payload["ok"] is True
    assert payload["checks"]["database"]["skipped"] is True
    assert payload["errors"]
    assert payload["errors"][0]["message"] == "scheduled health check missed"

    logging_utils.clear_error_history()
