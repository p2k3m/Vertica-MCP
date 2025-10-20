"""A very small connection pool for Vertica access."""

from __future__ import annotations

from contextlib import contextmanager
from queue import Empty, Queue

import vertica_python

from .config import settings


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


@contextmanager
def get_conn():
    try:
        conn = _POOL.get_nowait()
    except Empty:
        conn = _new_conn()
    try:
        yield conn
    finally:
        try:
            _POOL.put_nowait(conn)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
