"""A very small connection pool for Vertica access."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from queue import Empty, Queue

import vertica_python

from .config import settings


logger = logging.getLogger("mcp_vertica.pool")

_POOL = Queue(maxsize=settings.pool_size)


def _new_conn():
    return vertica_python.connect(
        host=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.password,
        database=settings.database,
        connection_timeout=5,
        autocommit=True,
    )


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
    raise last_exc


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
