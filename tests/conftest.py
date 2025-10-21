import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

# Ensure mandatory runtime configuration is present before application modules load.
_ENV_DEFAULTS = {
    "DB_HOST": "vertica.example.com",
    "DB_PORT": "5433",
    "DB_USER": "dbadmin",
    "DB_PASSWORD": "super-secret",
    "DB_NAME": "VMart",
}
for _key, _value in _ENV_DEFAULTS.items():
    os.environ.setdefault(_key, _value)

from mcp_vertica import server  # noqa: E402  (import after environment defaults)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    """Yield a test client with a successful bootstrap health check."""

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

    with TestClient(server.app) as test_client:
        yield test_client
