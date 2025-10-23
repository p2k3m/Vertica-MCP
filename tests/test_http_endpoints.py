from __future__ import annotations

from contextlib import contextmanager

from fastapi.testclient import TestClient

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


def test_dbs_endpoint_lists_configured_databases(monkeypatch):
    backup_nodes = [("backup.vertica.example.com", 5434)]
    monkeypatch.setattr(server.settings, "backup_nodes", backup_nodes)

    with _bootstrap_test_client(monkeypatch) as test_client:
        response = test_client.get("/dbs")

    assert response.status_code == 200

    payload = response.json()
    assert payload["current"]["host"] == server.settings.host
    assert payload["current"]["database"] == server.settings.database
    assert payload["current"]["user"] == server.settings.user

    supported = payload["supported"]
    assert any(entry["role"] == "primary" for entry in supported)
    backup_entries = [entry for entry in supported if entry["role"] == "backup"]
    assert backup_entries == [
        {
            "role": "backup",
            "host": backup_nodes[0][0],
            "port": backup_nodes[0][1],
            "database": server.settings.database,
            "user": server.settings.user,
        }
    ]
    for entry in supported:
        assert "password" not in entry

    pool = payload["pool"]
    assert pool["configured_size"] == server.settings.pool_size


def test_root_endpoint_provides_links(client):
    response = client.get("/")
    assert response.status_code == 200

    payload = response.json()
    assert payload["service"] == "vertica-mcp"
    assert payload["health"] == "/healthz"
    assert payload["documentation"].startswith("https://")


def test_info_endpoint_reports_server_details(client):
    response = client.get("/info")
    assert response.status_code == 200

    payload = response.json()
    assert payload["service"] == "vertica-mcp"
    assert payload["version"]

    uptime = payload["uptime"]
    assert "started" in uptime
    assert uptime["seconds"] >= 0

    hosts = payload["connected_hosts"]
    assert isinstance(hosts, list)
    assert hosts, "Expected the active request host to be tracked"
    assert hosts[0]["host"]
    assert hosts[0]["connections"] >= 1


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


def test_bearer_middleware_logs_auth_failures(monkeypatch, caplog):
    monkeypatch.setattr(server.settings, "http_token", "expected")

    with _bootstrap_test_client(monkeypatch) as test_client:
        caplog.set_level("WARNING")
        response = test_client.get("/diagnostics")

    assert response.status_code == 401
    messages = [
        record.message
        for record in caplog.records
        if "Rejected unauthorized request" in record.message
    ]
    assert messages, "Expected unauthorized access log entry"
    assert "expected" not in messages[0]
    assert "(missing bearer token)" in messages[0]


def _bootstrap_test_client(monkeypatch):
    monkeypatch.setattr(
        server,
        "_database_check",
        lambda: {
            "ok": True,
            "latency_ms": 1.0,
            "pool": {"configured_size": server.settings.pool_size},
            "target": {
                "host": server.settings.host,
                "port": server.settings.port,
                "database": server.settings.database,
                "user": server.settings.user,
            },
        },
    )

    monkeypatch.setattr(
        server,
        "external_ip_info",
        lambda timeout=2.0: {"ok": True, "ip": "203.0.113.10", "source": "test"},
    )

    return TestClient(server.app, raise_server_exceptions=False)
