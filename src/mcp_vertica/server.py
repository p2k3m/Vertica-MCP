from __future__ import annotations

import logging
import os
import platform
import time
from ipaddress import ip_address
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Dict, Iterable

from fastapi import FastAPI, Query, Request, HTTPException
from pydantic import BaseModel, Field

from . import pool as pool_module
from .config import settings
from .tools import mcp

try:  # pragma: no cover - importlib.metadata always present on modern Python
    from importlib.metadata import PackageNotFoundError, version
except ImportError:  # pragma: no cover
    from importlib_metadata import PackageNotFoundError, version


logger = logging.getLogger("mcp_vertica.server")

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


def _resolve_listen_host() -> str:
    for key in ("LISTEN_HOST", "MCP_LISTEN_HOST", "BIND_HOST", "MCP_BIND_HOST"):
        value = os.environ.get(key)
        if value and value.strip():
            return value.strip()

    legacy_host = os.environ.get("HOST")
    if legacy_host and legacy_host.strip():
        candidate = legacy_host.strip()
        if _is_socket_address(candidate):
            return candidate
        logger.warning(
            "Ignoring HOST environment variable value %r; set LISTEN_HOST to override the bind address.",
            legacy_host,
        )

    return "0.0.0.0"


def _resolve_listen_port() -> int:
    for key in ("LISTEN_PORT", "MCP_LISTEN_PORT", "BIND_PORT", "MCP_BIND_PORT", "PORT"):
        value = os.environ.get(key)
        port = _coerce_port(value, key)
        if port is not None:
            return port

    return 8000


def _is_socket_address(value: str) -> bool:
    if not value:
        return False

    candidate = value.strip()
    if not candidate:
        return False

    if candidate.lower() == "localhost":
        return True

    with suppress(ValueError):
        ip_address(candidate)
        return True

    return False


def _coerce_port(raw: str | None, key: str) -> int | None:
    if raw is None:
        return None

    candidate = raw.strip()
    if not candidate:
        return None

    try:
        port = int(candidate)
    except ValueError:
        logger.warning(
            "Ignoring non-integer %s value %r when determining listen port.",
            key,
            raw,
        )
        return None

    if not (0 < port < 65536):
        logger.warning(
            "%s value %r is outside the valid TCP port range; ignoring.",
            key,
            raw,
        )
        return None

    return port


def _run_server() -> None:
    """Run the MCP API using uvicorn."""

    import uvicorn  # Imported lazily so unit tests without uvicorn still pass

    host = _resolve_listen_host()
    port = _resolve_listen_port()

    uvicorn.run("mcp_vertica.server:app", host=host, port=port, log_level="info")


def main() -> None:
    """CLI entrypoint for running the FastAPI server."""

    _run_server()


if __name__ == "__main__":  # pragma: no cover - runtime behaviour
    main()


class QueryRequest(BaseModel):
    query: str = Field(..., description="SQL SELECT statement to execute")


def _health_response(*, ping_vertica: bool) -> Dict[str, Any]:
    if ping_vertica:
        checks = {"database": _database_check()}
    else:
        checks = {
            "database": {
                "ok": True,
                "skipped": True,
                "message": "Set ping-vertica=true to run a live Vertica query",
            }
        }

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


@app.get("/", include_in_schema=False)
async def root() -> Dict[str, Any]:
    """Basic landing endpoint for quick smoke tests."""

    return {
        "service": "vertica-mcp",
        "health": "/healthz",
        "documentation": "https://github.com/Expensify/Vertica-MCP",
    }


@app.get("/healthz")
async def healthz(ping_vertica: bool = Query(False, alias="ping-vertica")):
    return _health_response(ping_vertica=ping_vertica)


@app.get("/status", include_in_schema=False)
async def status():
    """Kubernetes-style liveness endpoint.

    The health checks run in "skip" mode to avoid touching Vertica so liveness
    probes remain lightweight.
    """

    return _health_response(ping_vertica=False)


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
    if token and request.url.path not in ("/", "/healthz", "/status", "/api/info", "/sse"):
        if request.headers.get("authorization") != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="Unauthorized")
    return await call_next(request)


app.mount("/api", mcp.streamable_http_app())
app.mount("/sse", mcp.sse_app())


@app.on_event("startup")
async def _startup_validation() -> None:
    logger.info(
        "Starting Vertica MCP targeting %s:%s/%s as %s",
        settings.host,
        settings.port,
        settings.database,
        settings.user,
    )

    result = _database_check()
    if not result.get("ok"):
        logger.warning(
            "Initial Vertica connectivity check failed: %s -- continuing in degraded mode",
            result.get("error", "unknown"),
        )
        return

    logger.info(
        "Initial Vertica connectivity check succeeded in %sms",
        result.get("latency_ms", "?"),
    )
