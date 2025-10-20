from __future__ import annotations

from contextlib import contextmanager

from mcp_vertica import server


def test_diagnostics_endpoint(client):
    response = client.get("/diagnostics")
    assert response.status_code == 200

    payload = response.json()
    assert "runtime" in payload
    assert "config" in payload


def test_root_endpoint_provides_links(client):
    response = client.get("/")
    assert response.status_code == 200

    payload = response.json()
    assert payload["service"] == "vertica-mcp"
    assert payload["health"] == "/healthz"
    assert payload["documentation"].startswith("https://")


def test_query_endpoint_executes_select(monkeypatch, client):
    events = {"executed": None, "cursor_closed": False}

    class DummyCursor:
        def execute(self, query: str) -> None:  # pragma: no cover - trivial
            events["executed"] = query

        def fetchall(self):  # pragma: no cover - trivial
            return [(1,)]

        def close(self) -> None:  # pragma: no cover - trivial
            events["cursor_closed"] = True

    class DummyConn:
        def cursor(self) -> DummyCursor:  # pragma: no cover - trivial
            return DummyCursor()

    @contextmanager
    def fake_get_conn():
        yield DummyConn()

    monkeypatch.setattr(server.pool_module, "get_conn", fake_get_conn)

    response = client.post("/query", json={"query": "SELECT 1"})
    assert response.status_code == 200

    payload = response.json()
    assert payload["ok"] is True
    assert payload["rows"] == [[1]]
    assert payload["row_count"] == 1
    assert events["executed"] == "SELECT 1"
    assert events["cursor_closed"] is True


def test_query_endpoint_rejects_non_select(client):
    response = client.post("/query", json={"query": "UPDATE foo SET bar = 1"})
    assert response.status_code == 200

    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"] == "Only SELECT statements are allowed"


def test_query_endpoint_reports_errors(monkeypatch, client):
    @contextmanager
    def fake_get_conn():
        raise RuntimeError("boom")
        yield

    monkeypatch.setattr(server.pool_module, "get_conn", fake_get_conn)

    response = client.post("/query", json={"query": "SELECT 1"})
    assert response.status_code == 200

    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"] == "boom"
    assert payload["exception"] == "RuntimeError"
