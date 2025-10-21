from __future__ import annotations

import json
import sys
import types

import pytest

from mcp_vertica import runtime, server


def _fake_uvicorn(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    def fake_run(app, **kwargs):  # pragma: no cover - simple capture helper
        captured["app"] = app
        captured.update(kwargs)

    module = types.SimpleNamespace(run=fake_run)
    monkeypatch.setitem(sys.modules, "uvicorn", module)
    return captured


def test_run_server_ignores_hostname_host_env(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    captured = _fake_uvicorn(monkeypatch)
    monkeypatch.setenv("HOST", "ip-172-31-12-34.ap-south-1.compute.internal")

    with caplog.at_level("WARNING"):
        server._run_server()

    assert captured["app"] == "mcp_vertica.server:app"
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 8000
    assert "Ignoring HOST environment variable" in caplog.text


def test_run_server_ignores_localhost_host_env(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    captured = _fake_uvicorn(monkeypatch)
    monkeypatch.setenv("HOST", "localhost")

    with caplog.at_level("WARNING"):
        server._run_server()

    assert captured["host"] == "0.0.0.0"
    assert "Ignoring HOST environment variable" in caplog.text


def test_run_server_ignores_public_ip_host_env(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    captured = _fake_uvicorn(monkeypatch)
    monkeypatch.setenv("HOST", "8.8.8.8")

    with caplog.at_level("WARNING"):
        server._run_server()

    assert captured["host"] == "0.0.0.0"
    assert "Ignoring HOST environment variable" in caplog.text


def test_run_server_ignores_loopback_host_env(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    captured = _fake_uvicorn(monkeypatch)
    monkeypatch.setenv("HOST", "127.0.0.1")

    with caplog.at_level("WARNING"):
        server._run_server()

    assert captured["host"] == "0.0.0.0"
    assert "Ignoring HOST environment variable" in caplog.text


def test_run_server_respects_private_ip_host_env(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _fake_uvicorn(monkeypatch)
    monkeypatch.setenv("HOST", "10.1.2.3")

    server._run_server()

    assert captured["host"] == "10.1.2.3"


def test_run_server_respects_explicit_listen_env(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _fake_uvicorn(monkeypatch)
    monkeypatch.setenv("LISTEN_HOST", "127.0.0.1")
    monkeypatch.setenv("LISTEN_PORT", "9001")
    monkeypatch.setenv("ALLOW_LOOPBACK_LISTEN", "1")
    monkeypatch.setenv("PUBLIC_HTTP_PORT", "9001")

    server._run_server()

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9001
    assert captured["log_level"] == "info"


def test_run_server_rejects_loopback_listen_host_by_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    captured = _fake_uvicorn(monkeypatch)
    monkeypatch.setenv("LISTEN_HOST", "127.0.0.1")

    with caplog.at_level("WARNING"):
        server._run_server()

    assert captured["host"] == "0.0.0.0"
    assert "Ignoring LISTEN_HOST environment variable" in caplog.text


def test_run_server_falls_back_to_port_env(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    captured = _fake_uvicorn(monkeypatch)
    monkeypatch.setenv("LISTEN_PORT", "not-a-number")
    monkeypatch.setenv("PORT", "9002")
    monkeypatch.setenv("PUBLIC_HTTP_PORT", "9002")

    with caplog.at_level("WARNING"):
        server._run_server()

    assert captured["port"] == 9002
    assert "non-integer LISTEN_PORT value" in caplog.text


def test_main_defaults_to_http(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _fake_uvicorn(monkeypatch)

    server.main([])

    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 8000


def test_main_respects_cli_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _fake_uvicorn(monkeypatch)
    monkeypatch.setenv("PUBLIC_HTTP_PORT", "9005")

    server.main(["--host", "10.0.0.5", "--port", "9005"])

    assert captured["host"] == "10.0.0.5"
    assert captured["port"] == 9005


def test_main_applies_database_override_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _fake_uvicorn(monkeypatch)
    calls = {"reset": 0}

    def fake_reset() -> None:  # pragma: no cover - trivial
        calls["reset"] += 1

    monkeypatch.setattr(server.pool_module, "reset_pool", fake_reset)

    payload = {
        "host": "cli.example.com",
        "port": 5444,
        "user": "cli_user",
        "password": "cli_secret",
        "database": "cli_db",
    }

    try:
        server.main(["--database-payload", json.dumps(payload)])
        assert server.settings.host == payload["host"]
        assert server.settings.port == payload["port"]
        assert server.settings.user == payload["user"]
        assert server.settings.password == payload["password"]
        assert server.settings.database == payload["database"]
        assert calls["reset"] == 1
    finally:
        server.settings.reload_from_environment()

    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 8000


def test_main_runs_connection_test_before_launch(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    captured = _fake_uvicorn(monkeypatch)

    def successful_check() -> dict[str, object]:  # pragma: no cover - simple stub
        return {"ok": True, "latency_ms": 12.5}

    monkeypatch.setattr(server, "_database_check", successful_check)

    with caplog.at_level("INFO"):
        server.main(["--connection-test"])

    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 8000
    assert "Vertica connection test succeeded" in caplog.text


def test_main_aborts_when_connection_test_fails(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    captured = _fake_uvicorn(monkeypatch)

    def failing_check() -> dict[str, object]:  # pragma: no cover - simple stub
        return {"ok": False, "error": "boom"}

    monkeypatch.setattr(server, "_database_check", failing_check)

    with caplog.at_level("ERROR"):
        with pytest.raises(SystemExit) as exc:
            server.main(["--connection-test"])

    assert exc.value.code == 1
    assert "Vertica connection test failed" in caplog.text
    assert "app" not in captured


def test_main_loads_database_override_from_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _fake_uvicorn(monkeypatch)
    payload = {
        "host": "file.example.com",
        "port": 5555,
        "user": "file_user",
        "password": "file_secret",
        "database": "file_db",
    }
    payload_path = tmp_path / "override.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")

    try:
        server.main(["--database-payload", f"@{payload_path}"])
        assert server.settings.host == payload["host"]
        assert server.settings.port == payload["port"]
        assert server.settings.user == payload["user"]
        assert server.settings.password == payload["password"]
        assert server.settings.database == payload["database"]
    finally:
        server.settings.reload_from_environment()

    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 8000


def test_main_rejects_invalid_database_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_uvicorn(monkeypatch)

    with pytest.raises(SystemExit):
        server.main(["--database-payload", "{not-json}"])


def test_run_server_errors_when_public_port_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _fake_uvicorn(monkeypatch)
    monkeypatch.setenv("PUBLIC_HTTP_PORT", "8100")

    with pytest.raises(SystemExit) as exc:
        server._run_server()

    assert "public HTTP port" in str(exc.value)
    assert "app" not in captured


def test_resolve_public_http_port_prefers_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_HTTP_PORT", "8100")
    monkeypatch.setenv("LISTEN_PORT", "8200")

    assert runtime.resolve_public_http_port() == 8100


def test_resolve_public_http_port_falls_back_to_listen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PUBLIC_HTTP_PORT", raising=False)
    monkeypatch.setenv("LISTEN_PORT", "8300")

    assert runtime.resolve_public_http_port() == 8300


def test_require_public_port_alignment_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_HTTP_PORT", "8400")

    with pytest.raises(SystemExit):
        runtime.require_public_port_alignment(8000)


def test_require_public_port_alignment_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBLIC_HTTP_PORT", "8500")

    runtime.require_public_port_alignment(8500)


def test_main_rejects_empty_cli_host(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    captured = _fake_uvicorn(monkeypatch)

    with caplog.at_level("WARNING"):
        server.main(["--host", "   "])

    assert captured["host"] == "0.0.0.0"
    assert "Ignoring empty CLI --host override" in caplog.text


def test_main_rejects_localhost_cli_override(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    captured = _fake_uvicorn(monkeypatch)

    with caplog.at_level("WARNING"):
        server.main(["--host", "localhost"])

    assert captured["host"] == "0.0.0.0"
    assert "Ignoring CLI --host override" in caplog.text


def test_main_allows_loopback_override_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _fake_uvicorn(monkeypatch)
    monkeypatch.setenv("ALLOW_LOOPBACK_LISTEN", "1")

    server.main(["--host", "127.0.0.1"])

    assert captured["host"] == "127.0.0.1"


def test_main_rejects_cli_port_out_of_range(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _fake_uvicorn(monkeypatch)

    with pytest.raises(SystemExit):
        server.main(["--port", "70000"])

    assert "app" not in captured


def test_main_rejects_cli_port_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _fake_uvicorn(monkeypatch)

    with pytest.raises(SystemExit):
        server.main(["--port", "0"])

    assert "app" not in captured
