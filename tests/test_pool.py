from __future__ import annotations

from queue import Queue

import pytest

from mcp_vertica import pool


class DummyConnection:
    def close(self) -> None:  # pragma: no cover - nothing to close in tests
        pass


def _reset_pool(monkeypatch) -> None:
    monkeypatch.setattr(pool, "_POOL", Queue(maxsize=1))


def test_get_conn_retries_and_logs(monkeypatch, caplog):
    _reset_pool(monkeypatch)
    monkeypatch.setattr(pool.settings, "connection_attempts", 2)
    monkeypatch.setattr(pool.settings, "connection_retry_backoff_s", 0.0)
    monkeypatch.setattr(pool.settings, "db_debug_logging", True)

    attempts = {"count": 0}

    def flaky_connect(**_kwargs):
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise RuntimeError("temporary outage")
        return DummyConnection()

    monkeypatch.setattr(pool.vertica_python, "connect", flaky_connect)

    caplog.set_level("DEBUG")
    with pool.get_conn() as conn:
        assert isinstance(conn, DummyConnection)

    assert attempts["count"] == 2
    assert any(
        "Failed to establish Vertica connection" in message
        for message in caplog.messages
    )
    assert any(
        "Established Vertica connection" in message for message in caplog.messages
    )


def test_get_conn_raises_after_retry_exhaustion(monkeypatch, caplog):
    _reset_pool(monkeypatch)
    monkeypatch.setattr(pool.settings, "connection_attempts", 2)
    monkeypatch.setattr(pool.settings, "connection_retry_backoff_s", 0.0)
    monkeypatch.setattr(pool.settings, "db_debug_logging", False)

    def failing_connect(**_kwargs):
        raise RuntimeError("unreachable")

    monkeypatch.setattr(pool.vertica_python, "connect", failing_connect)

    caplog.set_level("WARNING")
    with pytest.raises(RuntimeError):
        with pool.get_conn():
            pass

    assert attempts_logged(caplog)


def attempts_logged(caplog) -> bool:
    return any(
        "Failed to establish Vertica connection" in record.message
        for record in caplog.records
    )
