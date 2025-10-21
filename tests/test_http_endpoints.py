from __future__ import annotations

from contextlib import contextmanager

from mcp_vertica import server


def test_configure_database_endpoint_updates_settings(monkeypatch, client):
    calls = {"reset": 0}

    def fake_reset():
        calls["reset"] += 1

    monkeypatch.setattr(server.pool_module, "reset_pool", fake_reset)

    payload = {
        "host": "runtime.vertica.example.com",
        "port": 5434,
        "user": "runtime-user",
        "password": "runtime-secret",
        "database": "runtime",
    }

    try:
        response = client.post("/configure/database", json=payload)
        assert response.status_code == 200

        body = response.json()
        assert body["ok"] is True
        database = body["database"]
        assert database["host"] == payload["host"]
        assert database["port"] == payload["port"]
        assert database["database"] == payload["database"]
        assert database["user"] == payload["user"]
        assert database["source"] == "runtime"
        assert database["placeholder_credentials"] is False
        assert "password" not in database

        assert server.settings.host == payload["host"]
        assert server.settings.port == payload["port"]
        assert server.settings.user == payload["user"]
        assert server.settings.password == payload["password"]
        assert server.settings.database == payload["database"]
        assert calls["reset"] == 1
    finally:
        server.settings.reload_from_environment()


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
