from __future__ import annotations

import os
import platform
import time
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Dict, Iterable

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel, Field

from . import pool as pool_module
from .config import settings
from .tools import mcp

try:  # pragma: no cover - importlib.metadata always present on modern Python
    from importlib.metadata import PackageNotFoundError, version
except ImportError:  # pragma: no cover
    from importlib_metadata import PackageNotFoundError, version


app = FastAPI()


def _service_version() -> str:
    """Best effort determination of the deployed package version."""

    try:
        return version("mcp-vertica")
    except PackageNotFoundError:
        return "unknown"


def _pool_details() -> Dict[str, Any]:
    details: Dict[str, Any] = {"configured_size": settings.pool_size}
    queue = getattr(pool_module, "_POOL", None)
    if queue is not None:
        with suppress(Exception):
            details["available"] = queue.qsize()
        with suppress(Exception):
            details["max_size"] = queue.maxsize
    return details


def _database_check() -> Dict[str, Any]:
    pool_info = _pool_details()
    target = {
        "host": settings.host,
        "port": settings.port,
        "database": settings.database,
        "user": settings.user,
    }

    start = time.perf_counter()
    cursor = None
    try:
        with pool_module.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:  # pragma: no cover - exercised in unit tests
        latency = round((time.perf_counter() - start) * 1000, 3)
        if cursor is not None:
            with suppress(Exception):
                cursor.close()
        return {
            "ok": False,
            "latency_ms": latency,
            "pool": pool_info,
            "target": target,
            "error": str(exc),
            "exception": exc.__class__.__name__,
        }
    else:
        latency = round((time.perf_counter() - start) * 1000, 3)
        return {
            "ok": True,
            "latency_ms": latency,
            "pool": pool_info,
            "target": target,
        }
    finally:
        if cursor is not None:
            with suppress(Exception):
                cursor.close()


def _runtime_diagnostics() -> Dict[str, Any]:
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "pid": os.getpid(),
        "service_version": _service_version(),
    }


def _config_diagnostics() -> Dict[str, Any]:
    return {
        "database": {
            "host": settings.host,
            "port": settings.port,
            "database": settings.database,
            "user": settings.user,
        },
        "pool": {
            "size": settings.pool_size,
        },
        "query": {
            "timeout_s": settings.query_timeout_s,
            "max_rows": settings.max_rows,
        },
        "schemas": settings.allowed_schemas,
        "auth": {
            "http_token_configured": bool(settings.http_token),
        },
        "cors": settings.cors_origins,
    }


def _normalise_rows(rows: Iterable[Any]) -> list[Any]:
    normalised: list[Any] = []
    for row in rows:
        if isinstance(row, (list, tuple)):
            normalised.append(list(row))
        else:
            normalised.append(row)
    return normalised


def _query_execution(query: str) -> Dict[str, Any]:
    trimmed = (query or "").strip()
    if not trimmed:
        return {"ok": False, "error": "Query must not be empty"}
    if not trimmed.upper().startswith("SELECT "):
        return {"ok": False, "error": "Only SELECT statements are allowed"}

    start = time.perf_counter()
    cursor = None
    try:
        with pool_module.get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(trimmed)
            rows = cursor.fetchall()
    except Exception as exc:  # pragma: no cover - exercised in unit tests
        latency = round((time.perf_counter() - start) * 1000, 3)
        if cursor is not None:
            with suppress(Exception):
                cursor.close()
        return {
            "ok": False,
            "latency_ms": latency,
            "error": str(exc),
            "exception": exc.__class__.__name__,
        }
    else:
        latency = round((time.perf_counter() - start) * 1000, 3)
        return {
            "ok": True,
            "latency_ms": latency,
            "rows": _normalise_rows(rows),
            "row_count": len(rows),
        }
    finally:
        if cursor is not None:
            with suppress(Exception):
                cursor.close()


class QueryRequest(BaseModel):
    query: str = Field(..., description="SQL SELECT statement to execute")


@app.get("/healthz")
async def healthz():
    checks = {"database": _database_check()}
    ok = all(check.get("ok") for check in checks.values())
    diagnostics = {
        "runtime": _runtime_diagnostics(),
        "config": _config_diagnostics(),
    }
    return {
        "ok": ok,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "diagnostics": diagnostics,
    }


@app.get("/diagnostics")
async def diagnostics():
    return {
        "runtime": _runtime_diagnostics(),
        "config": _config_diagnostics(),
    }


@app.post("/query")
async def execute_query_endpoint(payload: QueryRequest):
    return _query_execution(payload.query)


@app.middleware("http")
async def bearer(request: Request, call_next):
    token = settings.http_token
    if token and request.url.path not in ("/healthz", "/api/info", "/sse"):
        if request.headers.get("authorization") != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="Unauthorized")
    return await call_next(request)


app.mount("/api", mcp.streamable_http_app())
app.mount("/sse", mcp.sse_app())
