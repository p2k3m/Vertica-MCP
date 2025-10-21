from __future__ import annotations

import errno
import socket
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


@pytest.mark.parametrize(
    "raised, expected_message",
    [
        (
            socket.gaierror(socket.EAI_NONAME, "Name or service not known"),
            "Unable to resolve Vertica host",
        ),
        (
            OSError(errno.ENETUNREACH, "Network is unreachable"),
            "Network unreachable",
        ),
        (
            ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused"),
            "was refused",
        ),
        (
            pool.vertica_python.errors.ConnectionError(
                "FATAL 28000: Authentication failed"
            ),
            "Authentication failed",
        ),
    ],
)
def test_classified_connection_errors(monkeypatch, raised, expected_message):
    _reset_pool(monkeypatch)
    monkeypatch.setattr(pool.settings, "connection_attempts", 1)
    monkeypatch.setattr(pool.settings, "db_debug_logging", False)

    def failing_connect(**_kwargs):
        raise raised

    monkeypatch.setattr(pool.vertica_python, "connect", failing_connect)

    with pytest.raises(pool.VerticaConnectionSetupError) as excinfo:
        with pool.get_conn():
            pass

    assert expected_message in str(excinfo.value)


def attempts_logged(caplog) -> bool:
    return any(
        "Failed to establish Vertica connection" in record.message
        for record in caplog.records
    )
