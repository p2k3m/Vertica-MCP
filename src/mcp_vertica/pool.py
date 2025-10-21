"""A very small connection pool for Vertica access."""

from __future__ import annotations

import errno
import logging
import socket
import time
from contextlib import contextmanager
from queue import Empty, Queue

import vertica_python

from .config import settings


logger = logging.getLogger("mcp_vertica.pool")

_POOL = Queue(maxsize=settings.pool_size)


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

            if attempt == attempts:
                break

            delay = max(0.0, backoff) * attempt
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
