"""A very small connection pool for Vertica access."""

from __future__ import annotations

import errno
import logging
import socket
import time
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from queue import Empty, Queue
from typing import Any, Dict

import vertica_python

from .config import settings


logger = logging.getLogger("mcp_vertica.pool")

_POOL = Queue(maxsize=settings.pool_size)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def _exponential_backoff_delay(base: float, attempt: int) -> float:
    if base <= 0:
        return 0.0
    exponent = max(0, attempt - 1)
    return float(base) * (2 ** exponent)


def _default_retry_state() -> Dict[str, Any]:
    return {
        "in_progress": False,
        "attempts": 0,
        "max_attempts": max(1, settings.connection_attempts),
        "strategy": "exponential",
        "base_backoff_s": max(0.0, settings.connection_retry_backoff_s),
        "last_failure": None,
        "last_exception": None,
        "last_failure_at": None,
        "next_retry_in_s": None,
        "next_retry_at": None,
        "recovered_at": None,
        "exhausted": False,
    }


_RETRY_STATE: Dict[str, Any] = _default_retry_state()


def _update_retry_context(*, attempts: int, base_backoff: float) -> None:
    _RETRY_STATE.update(
        max_attempts=attempts,
        base_backoff_s=max(0.0, base_backoff),
        strategy="exponential",
    )


def _record_retry_failure(
    *,
    exc: Exception,
    attempt: int,
    max_attempts: int,
    base_backoff: float,
) -> float:
    now = _utcnow()
    delay = _exponential_backoff_delay(base_backoff, attempt)
    if attempt >= max_attempts:
        delay = 0.0

    in_progress = attempt < max_attempts
    _RETRY_STATE.update(
        in_progress=in_progress,
        attempts=attempt,
        last_failure=str(exc),
        last_exception=exc.__class__.__name__,
        last_failure_at=_isoformat(now),
        exhausted=not in_progress,
    )

    if in_progress:
        next_retry_at = now + timedelta(seconds=delay)
        _RETRY_STATE.update(
            next_retry_in_s=round(delay, 3),
            next_retry_at=_isoformat(next_retry_at),
        )
    else:
        _RETRY_STATE.update(next_retry_in_s=None, next_retry_at=None)

    return delay


def _record_retry_success(attempt: int) -> None:
    now = _utcnow()
    _RETRY_STATE.update(
        in_progress=False,
        attempts=attempt,
        next_retry_in_s=None,
        next_retry_at=None,
        exhausted=False,
        recovered_at=_isoformat(now),
    )


def connection_retry_state() -> Dict[str, Any]:
    return dict(_RETRY_STATE)


class VerticaConnectionSetupError(RuntimeError):
    """Raised when Vertica connection initialisation fails with a known cause."""


_AUTH_FAILURE_MARKERS = (
    "authentication failed",
    "password",
    "invalid credentials",
    "fatal 28000",
)


def _classify_connection_exception(exc: Exception) -> Exception:
    """Return a rich error for well understood connection failures."""

    if isinstance(exc, socket.gaierror):
        message = exc.strerror or str(exc)
        return VerticaConnectionSetupError(
            (
                "Unable to resolve Vertica host '%s'. "
                "Update the DB_HOST setting and ensure DNS is reachable (%s)."
            )
            % (settings.host, message)
        )

    if isinstance(exc, OSError):
        if exc.errno == errno.ENETUNREACH:
            return VerticaConnectionSetupError(
                (
                    "Network unreachable when contacting Vertica at %s:%s. "
                    "Verify network or VPN connectivity before retrying."
                )
                % (settings.host, settings.port)
            )
        if exc.errno == errno.ECONNREFUSED:
            return VerticaConnectionSetupError(
                (
                    "Connection to Vertica at %s:%s was refused. "
                    "Confirm the service is listening on the configured DB_PORT."
                )
                % (settings.host, settings.port)
            )

    if isinstance(exc, vertica_python.errors.ConnectionError):
        message = str(exc).lower()
        if any(marker in message for marker in _AUTH_FAILURE_MARKERS):
            return VerticaConnectionSetupError(
                (
                    "Authentication failed for Vertica user '%s'. "
                    "Double-check DB_USER and DB_PASSWORD."
                )
                % (settings.user,)
            )

    return exc


def _new_conn():
    return vertica_python.connect(**settings.vertica_connection_options())


def _connect_with_retry():
    attempts = max(1, settings.connection_attempts)
    backoff = settings.connection_retry_backoff_s
    last_exc: Exception | None = None

    _update_retry_context(attempts=attempts, base_backoff=backoff)

    for attempt in range(1, attempts + 1):
        try:
            conn = _new_conn()
        except Exception as exc:  # pragma: no cover - exercised via unit tests
            last_exc = exc
            if settings.db_debug_logging:
                logger.exception(
                    "Failed to establish Vertica connection (attempt %s/%s)",
                    attempt,
                    attempts,
                )
            else:
                logger.warning(
                    "Failed to establish Vertica connection (attempt %s/%s): %s",
                    attempt,
                    attempts,
                    exc,
                )

            delay = _record_retry_failure(
                exc=exc, attempt=attempt, max_attempts=attempts, base_backoff=backoff
            )

            if attempt == attempts:
                break

            if delay:
                logger.info(
                    "Retrying Vertica connection in %.2fs (attempt %s/%s)",
                    delay,
                    attempt + 1,
                    attempts,
                )
                time.sleep(delay)
            else:
                logger.info(
                    "Retrying Vertica connection immediately (attempt %s/%s)",
                    attempt + 1,
                    attempts,
                )
        else:
            if settings.db_debug_logging:
                logger.debug(
                    "Established Vertica connection on attempt %s", attempt
                )
            _record_retry_success(attempt)
            return conn

    assert last_exc is not None
    classified = _classify_connection_exception(last_exc)
    if classified is last_exc:
        raise last_exc
    raise classified from last_exc


@contextmanager
def get_conn():
    try:
        conn = _POOL.get_nowait()
    except Empty:
        conn = _connect_with_retry()
    try:
        yield conn
    finally:
        try:
            _POOL.put_nowait(conn)
        except Exception as exc:  # pragma: no cover - defensive cleanup
            if settings.db_debug_logging:
                logger.exception(
                    "Discarding Vertica connection; pool rejection raised an exception"
                )
            else:
                logger.warning(
                    "Discarding Vertica connection after pool rejection: %s", exc
                )
            try:
                conn.close()
            except Exception as close_exc:  # pragma: no cover - best effort cleanup
                if settings.db_debug_logging:
                    logger.exception(
                        "Failed to close Vertica connection after pool rejection"
                    )
                else:
                    logger.warning(
                        "Failed to close Vertica connection after pool rejection: %s",
                        close_exc,
                    )


def reset_pool() -> None:
    """Flush existing connections and rebuild the pool."""

    global _POOL

    drained = []
    queue = _POOL
    if queue is not None:
        while True:
            try:
                conn = queue.get_nowait()
            except Empty:
                break
            else:
                drained.append(conn)

    for conn in drained:
        try:
            conn.close()
        except Exception as exc:  # pragma: no cover - best effort cleanup
            if settings.db_debug_logging:
                logger.exception(
                    "Failed to close Vertica connection during pool reset"
                )
            else:
                logger.warning(
                    "Failed to close Vertica connection during pool reset: %s",
                    exc,
                )

    _POOL = Queue(maxsize=settings.pool_size)
