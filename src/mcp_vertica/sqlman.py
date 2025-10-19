from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import Any
import signal, datetime as dt, re
from .config import settings
from .pool import get_conn


SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


@dataclass
class Provenance:
sql_or_view: str
params: dict
as_of_ts: str
row_count: int


class Timeout:
def __init__(self, seconds: int): self.seconds = seconds
def __enter__(self):
signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("query timeout")))
signal.alarm(self.seconds)
def __exit__(self, *_): signal.alarm(0)


_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")


def _sanitize_ident(name: str) -> str:
if not _IDENT.match(name or ""): raise ValueError(f"Invalid identifier: {name!r}")
return name


# very simple schema allowlist: detect schema prefixes used in SQL text
SCHEMA_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\.")


def _enforce_schema_allowlist(sql_text: str):
schemas = set(m.group(1) for m in SCHEMA_RE.finditer(sql_text))
disallowed = [s for s in schemas if s.lower() not in [x.lower() for x in settings.allowed_schemas]]
if disallowed:
raise PermissionError(f"Schemas not allowed: {disallowed}")


# naive :param substitution is handled by vertica-python named params


def run_sql(sql_name: str, params: dict[str, Any], limit: int | None = None):
p = SQL_DIR / sql_name
if not p.exists():
raise FileNotFoundError(f"SQL template not found: {p.name}")
sql = p.read_text(encoding="utf-8")
_enforce_schema_allowlist(sql)


cap = min(limit or settings.max_rows, settings.max_rows)
if ":limit" in sql:
params = dict(params); params.setdefault("limit", cap)
else:
sql = f"SELECT * FROM ( {sql} ) AS t LIMIT :limit"; params = dict(params, limit=cap)


with get_conn() as conn, Timeout(settings.query_timeout_s):
cur = conn.cursor(); t0=time(); cur.execute(sql, params); rows = cur.fetchall()


prov = Provenance(sql_or_view=p.name, params=params, as_of_ts=dt.datetime.utcnow().isoformat()+"Z", row_count=len(rows))
return rows, prov


# simple ensemble ranker: take max score per key


def ranked_multi(queries: list[tuple[str, dict]], k: int = 50):
agg: dict[str, float] = {}
provs: list[Provenance] = []
for name, params in queries:
rows, prov = run_sql(name, params, limit=k)
provs.append(prov)
for r in rows:
key = r[0]
score = float(r[1]) if len(r) > 1 else 0.0
agg[key] = max(agg.get(key, 0.0), score)
ranked = sorted(agg.items(), key=lambda kv: kv[1], reverse=True)[:k]
return [(k, s) for k, s in ranked], provs
