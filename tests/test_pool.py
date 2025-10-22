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
    monkeypatch.setattr(pool, "_RETRY_STATE", pool._default_retry_state())


def test_get_conn_retries_and_logs(monkeypatch, caplog):
    _reset_pool(monkeypatch)
    monkeypatch.setattr(pool.settings, "connection_attempts", 2)
    monkeypatch.setattr(pool.settings, "connection_retry_backoff_s", 0.5)
    monkeypatch.setattr(pool.settings, "db_debug_logging", True)

    attempts = {"count": 0}

    def flaky_connect(**_kwargs):
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise RuntimeError("temporary outage")
        return DummyConnection()

    monkeypatch.setattr(pool.vertica_python, "connect", flaky_connect)

    sleeps: list[float] = []

    def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(pool.time, "sleep", fake_sleep)

    caplog.set_level("DEBUG")
    with pool.get_conn() as conn:
        assert isinstance(conn, DummyConnection)

    assert attempts["count"] == 2
    assert sleeps == [0.5]
    assert any(
        "Failed to establish Vertica connection" in message
        for message in caplog.messages
    )
    assert any(
        "Established Vertica connection" in message for message in caplog.messages
    )

    state = pool.connection_retry_state()
    assert state["in_progress"] is False
    assert state["attempts"] == 2
    assert state["max_attempts"] == 2
    assert state["last_failure"] == "temporary outage"
    assert state["last_exception"] == "RuntimeError"
    assert state["next_retry_in_s"] is None
    assert state["recovered_at"] is not None


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


def test_exponential_backoff_progression(monkeypatch, caplog):
    _reset_pool(monkeypatch)
    monkeypatch.setattr(pool.settings, "connection_attempts", 3)
    monkeypatch.setattr(pool.settings, "connection_retry_backoff_s", 0.25)
    monkeypatch.setattr(pool.settings, "db_debug_logging", False)

    def failing_connect(**_kwargs):
        raise RuntimeError("down")

    sleeps: list[float] = []

    def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(pool.vertica_python, "connect", failing_connect)
    monkeypatch.setattr(pool.time, "sleep", fake_sleep)

    caplog.set_level("WARNING")
    with pytest.raises(RuntimeError):
        with pool.get_conn():
            pass

    assert sleeps == [0.25, 0.5]
    state = pool.connection_retry_state()
    assert state["attempts"] == 3
    assert state["max_attempts"] == 3
    assert state["in_progress"] is False
    assert state["exhausted"] is True
    assert state["last_failure"] == "down"
    assert state["last_exception"] == "RuntimeError"
    assert state["last_failure_at"] is not None
    assert state["next_retry_in_s"] is None
    assert state["recovered_at"] is None


def test_connection_failure_logs_redacted_credentials(monkeypatch, caplog):
    _reset_pool(monkeypatch)
    monkeypatch.setattr(pool.settings, "connection_attempts", 1)
    monkeypatch.setattr(pool.settings, "connection_retry_backoff_s", 0.0)
    monkeypatch.setattr(pool.settings, "db_debug_logging", False)

    def failing_connect(**_kwargs):
        raise RuntimeError("password=super-secret Authorization=Bearer 12345 token=abc")

    monkeypatch.setattr(pool.vertica_python, "connect", failing_connect)

    caplog.set_level("WARNING")
    with pytest.raises(RuntimeError):
        with pool.get_conn():
            pass

    combined = " ".join(record.message for record in caplog.records)
    assert "super-secret" not in combined
    assert "12345" not in combined
    assert "token=abc" not in combined
    assert combined.count("<redacted>") >= 2


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
