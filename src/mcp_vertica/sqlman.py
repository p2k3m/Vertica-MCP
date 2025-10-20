"""Utilities for executing parametrised SQL files safely."""

from __future__ import annotations

import datetime as dt
import re
import signal
from dataclasses import asdict, dataclass
from pathlib import Path
from time import time
from typing import Any, Iterable

from .config import settings
from .pool import get_conn


SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
def _utcnow() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class Provenance:
    sql_or_view: str
    params: dict[str, Any]
    as_of_ts: str
    row_count: int
    duration_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Timeout:
    def __init__(self, seconds: int) -> None:
        self.seconds = seconds

    def __enter__(self) -> None:
        signal.signal(
            signal.SIGALRM,
            lambda *_: (_ for _ in ()).throw(TimeoutError("query timeout")),
        )
        signal.alarm(self.seconds)

    def __exit__(self, *_exc) -> None:
        signal.alarm(0)


_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")
_SCHEMA_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\.")


def ensure_schema_allowed(schema: str) -> str:
    if not _IDENT.match(schema or ""):
        raise ValueError(f"Invalid identifier: {schema!r}")
    if schema.lower() not in settings.allowed_schema_set():
        raise PermissionError(f"Schema not allowed: {schema}")
    return schema


def _find_schemas(sql_text: str) -> Iterable[str]:
    return {match.group(1) for match in _SCHEMA_RE.finditer(sql_text)}


def _enforce_schema_allowlist(sql_text: str) -> None:
    disallowed = [
        schema
        for schema in _find_schemas(sql_text)
        if schema.lower() not in settings.allowed_schema_set()
    ]
    if disallowed:
        raise PermissionError(f"Schemas not allowed: {sorted(disallowed)}")


def run_sql(sql_name: str, params: dict[str, Any], limit: int | None = None):
    path = SQL_DIR / sql_name
    if not path.exists():
        raise FileNotFoundError(f"SQL template not found: {path.name}")

    sql = path.read_text(encoding="utf-8")
    _enforce_schema_allowlist(sql)

    params = dict(params)
    for key in list(params):
        if key.endswith("schema"):
            params[key] = ensure_schema_allowed(params[key])

    cap = min(limit or settings.max_rows, settings.max_rows)
    if ":limit" in sql:
        params.setdefault("limit", cap)
    else:
        sql = f"SELECT * FROM ( {sql} ) AS t LIMIT :limit"
        params["limit"] = cap

    with get_conn() as conn, Timeout(settings.query_timeout_s):
        cursor = conn.cursor()
        start = time()
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        elapsed = (time() - start) * 1000

    provenance = Provenance(
        sql_or_view=path.name,
        params=params,
        as_of_ts=_utcnow(),
        row_count=len(rows),
        duration_ms=elapsed,
    )
    return rows, provenance


def ranked_multi(queries: list[tuple[str, dict[str, Any]]], k: int = 50):
    scores: dict[str, float] = {}
    provenances: list[Provenance] = []

    for name, params in queries:
        rows, provenance = run_sql(name, params, limit=k)
        provenances.append(provenance)
        for row in rows:
            if not row:
                continue
            key = row[0]
            score = float(row[1]) if len(row) > 1 else 0.0
            scores[key] = max(scores.get(key, score), score)

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:k]
    return ranked, provenances
