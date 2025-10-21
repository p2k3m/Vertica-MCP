from __future__ import annotations

import sys
import types

import pytest

from mcp_vertica import server


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

    server._run_server()

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9001
    assert captured["log_level"] == "info"


def test_run_server_falls_back_to_port_env(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    captured = _fake_uvicorn(monkeypatch)
    monkeypatch.setenv("LISTEN_PORT", "not-a-number")
    monkeypatch.setenv("PORT", "9002")

    with caplog.at_level("WARNING"):
        server._run_server()

    assert captured["port"] == 9002
    assert "non-integer LISTEN_PORT value" in caplog.text
