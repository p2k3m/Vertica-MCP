from __future__ import annotations

import asyncio
from contextlib import contextmanager

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response

from mcp_vertica import server


def test_health_endpoint(monkeypatch, client):
    monkeypatch.setattr(
        server,
        "_database_check",
        lambda: {
            "ok": True,
            "latency_ms": 1.23,
            "pool": {"configured_size": server.settings.pool_size},
            "target": {
                "host": server.settings.host,
                "port": server.settings.port,
                "database": server.settings.database,
                "user": server.settings.user,
            },
        },
    )

    response = client.get("/healthz", params={"ping-vertica": "true"})
    assert response.status_code == 200

    payload = response.json()
    assert payload["ok"] is True
    assert "timestamp" in payload
    assert payload["checks"]["database"]["ok"] is True
    config = payload["diagnostics"]["config"]
    assert config["database"]["host"] == server.settings.host
    assert config["auth"]["http_token_configured"] is bool(server.settings.http_token)
    assert config["database"]["placeholder_credentials"] is False


def test_health_endpoint_reports_failures(monkeypatch, client):
    monkeypatch.setattr(
        server,
        "_database_check",
        lambda: {
            "ok": False,
            "pool": {},
            "target": {},
            "error": "no connection",
        },
    )

    response = client.get("/healthz", params={"ping-vertica": "true"})
    assert response.status_code == 503

    payload = response.json()
    assert payload["ok"] is False
    assert payload["checks"]["database"]["error"] == "no connection"


def test_health_endpoint_reports_placeholder_credentials(monkeypatch):
    monkeypatch.setattr(
        server.settings.__class__,
        "using_placeholder_credentials",
        lambda self: True,
    )

    with TestClient(server.app) as placeholder_client:
        response = placeholder_client.get("/healthz", params={"ping-vertica": "true"})

    assert response.status_code == 503

    payload = response.json()
    database = payload["checks"]["database"]
    assert database["ok"] is False
    assert database["placeholder_credentials"] is True
    assert "placeholder" in database["error"].lower()


def test_status_endpoint_is_lightweight(monkeypatch, client):
    """The status endpoint should not attempt to contact Vertica."""

    def fake_database_check():  # pragma: no cover - guard against invocation
        raise AssertionError("status endpoint should not ping Vertica")

    monkeypatch.setattr(server, "_database_check", fake_database_check)

    response = client.get("/status")
    assert response.status_code == 200

    payload = response.json()
    assert payload["ok"] is True
    assert payload["checks"]["database"]["skipped"] is True


def test_database_check_success(monkeypatch):
    events = {"cursor_closed": False}

    class DummyCursor:
        def execute(self, query: str) -> None:  # pragma: no cover - trivial
            events["query"] = query

        def fetchone(self):  # pragma: no cover - trivial
            return (1,)

        def close(self) -> None:  # pragma: no cover - trivial
            events["cursor_closed"] = True

    class DummyConn:
        def cursor(self) -> DummyCursor:  # pragma: no cover - trivial
            return DummyCursor()

    @contextmanager
    def fake_get_conn():
        yield DummyConn()

    class DummyQueue:
        def __init__(self) -> None:  # pragma: no cover - trivial
            self.maxsize = server.settings.pool_size

        def qsize(self) -> int:  # pragma: no cover - trivial
            return 2

    monkeypatch.setattr(server.pool_module, "get_conn", fake_get_conn)
    monkeypatch.setattr(server.pool_module, "_POOL", DummyQueue())

    result = server._database_check()
    assert result["ok"] is True
    assert result["pool"]["configured_size"] == server.settings.pool_size
    assert result["pool"]["available"] == 2
    assert result["pool"]["max_size"] == server.settings.pool_size
    assert result["target"]["database"] == server.settings.database
    assert events["cursor_closed"] is True


def test_database_check_failure(monkeypatch):
    @contextmanager
    def fake_get_conn():
        raise RuntimeError("boom")
        yield

    monkeypatch.setattr(server.pool_module, "get_conn", fake_get_conn)
    monkeypatch.setattr(server.pool_module, "_POOL", None, raising=False)

    result = server._database_check()
    assert result["ok"] is False
    assert result["error"] == "boom"
    assert result["exception"] == "RuntimeError"


def test_protected_routes_require_bearer_token(monkeypatch, client):
    monkeypatch.setattr(server.settings, "http_token", "shhh", raising=False)

    def make_request(path: str, headers: list[tuple[bytes, bytes]] | None = None) -> Request:
        async def receive() -> dict:
            return {"type": "http.request"}

        scope = {
            "type": "http",
            "method": "GET",
            "path": path,
            "root_path": "",
            "scheme": "http",
            "query_string": b"",
            "headers": headers or [],
            "client": ("test", 1234),
            "server": ("testserver", 80),
            "http_version": "1.1",
        }
        return Request(scope, receive)

    async def call_next(_request: Request) -> Response:
        call_next.called = True
        return Response("ok")

    call_next.called = False

    with pytest.raises(HTTPException) as exc:
        asyncio.run(server.bearer(make_request("/api/mcp"), call_next))
    assert exc.value.status_code == 401
    assert not call_next.called

    monkeypatch.setattr(
        server,
        "_database_check",
        lambda: {
            "ok": True,
            "pool": {},
            "target": {},
        },
    )

    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["ok"] is True

    call_next.called = False
    response = asyncio.run(
        server.bearer(
            make_request(
                "/api/mcp", headers=[(b"authorization", b"Bearer shhh")]
            ),
            call_next,
        )
    )
    assert response.status_code == 200
    assert call_next.called


def test_startup_allows_vertica_failures(monkeypatch):
    """Service startup should not abort if Vertica is unreachable."""

    attempts = {"count": 0}

    def failing_database_check():
        attempts["count"] += 1
        return {
            "ok": False,
            "error": "no connection",
        }

    monkeypatch.setattr(server, "_database_check", failing_database_check)

    with TestClient(server.app) as degraded_client:
        # Startup should have attempted the connectivity probe once.
        assert attempts["count"] == 1

        response = degraded_client.get("/healthz")
        assert response.status_code == 200

        payload = response.json()
        # Without ping-vertica the health endpoint remains optimistic.
        assert payload["ok"] is True
        assert payload["checks"]["database"]["skipped"] is True
