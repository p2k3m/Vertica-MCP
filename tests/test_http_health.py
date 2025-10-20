from __future__ import annotations

import asyncio
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response

from mcp_vertica import server


client = TestClient(server.app)


def test_health_endpoint():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_protected_routes_require_bearer_token(monkeypatch):
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

    health = client.get("/healthz")
    assert health.status_code == 200

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
