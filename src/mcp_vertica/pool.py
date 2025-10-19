from queue import Queue, Empty
from contextlib import contextmanager
import vertica_python
from .config import settings


_POOL = Queue(maxsize=8)


def _new_conn():
return vertica_python.connect(
host=settings.host,
port=settings.port,
user=settings.user,
password=settings.password,
database=settings.database,
connection_timeout=5,
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
try: conn.close()
except Exception: pass
