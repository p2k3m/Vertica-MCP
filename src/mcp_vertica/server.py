from __future__ import annotations

import argparse
import logging
import os
import platform
import sys
import time
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Sequence

from fastapi import FastAPI, Query, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import pool as pool_module
from .config import settings
from .runtime import (
    allow_loopback_listen,
    external_ip_info,
    is_bindable_listen_host,
    resolve_listen_host,
    resolve_listen_port,
    require_public_port_alignment,
)
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

    if settings.using_placeholder_credentials():
        return {
            "ok": False,
            "pool": pool_info,
            "target": target,
            "error": "Vertica credentials are using repository placeholder values.",
            "placeholder_credentials": True,
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


def _runtime_status() -> Dict[str, Any]:
    listen_host = resolve_listen_host(log=logger)
    listen_port = resolve_listen_port(log=logger)
    loopback_allowed = allow_loopback_listen()

    return {
        "listen": {
            "host": listen_host,
            "port": listen_port,
            "loopback_allowed": loopback_allowed,
        },
        "external_ip": external_ip_info(),
    }


def _config_diagnostics() -> Dict[str, Any]:
    return {
        "database": {
            "host": settings.host,
            "port": settings.port,
            "database": settings.database,
            "user": settings.user,
            "placeholder_credentials": settings.using_placeholder_credentials(),
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


def _resolve_host_override(host: str | None) -> str:
    allow_loopback = allow_loopback_listen()
    resolved = resolve_listen_host(log=logger)

    if host is None:
        return resolved

    candidate = host.strip()
    if not candidate:
        logger.warning("Ignoring empty CLI --host override; using %s", resolved)
        return resolved

    if is_bindable_listen_host(candidate, allow_loopback=allow_loopback):
        return candidate

    logger.warning("Ignoring CLI --host override %r; not a bindable interface.", host)
    if candidate in {"127.0.0.1", "localhost"} and not allow_loopback:
        logger.warning(
            "Set ALLOW_LOOPBACK_LISTEN=1 to bind Vertica MCP to loopback interfaces explicitly.",
        )

    return resolved


def _resolve_port_override(port: int | None) -> int:
    resolved = resolve_listen_port(log=logger)

    if port is None:
        return resolved

    if not (0 < port < 65536):
        raise SystemExit(f"Port {port!r} is outside the valid TCP port range (1-65535).")

    return port


def _run_server(*, host: str | None = None, port: int | None = None) -> None:
    """Run the MCP API using uvicorn."""

    import uvicorn  # Imported lazily so unit tests without uvicorn still pass

    resolved_host = _resolve_host_override(host)
    resolved_port = _resolve_port_override(port)

    require_public_port_alignment(resolved_port, log=logger)

    uvicorn.run(
        "mcp_vertica.server:app",
        host=resolved_host,
        port=resolved_port,
        log_level="info",
    )


def _parse_cli_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Vertica MCP HTTP server")
    parser.add_argument(
        "--host",
        help=(
            "Bind address for the HTTP transport. Defaults to environment driven "
            "resolution (0.0.0.0 when unset)."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        help=(
            "Port for the HTTP transport. Defaults to environment driven "
            "resolution (8000 when unset)."
        ),
    )
    parser.add_argument(
        "--transport",
        choices=["http"],
        default="http",
        help="Transport protocol to expose. Only HTTP is currently supported.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entrypoint for running the FastAPI server."""

    args = _parse_cli_args(argv)

    if args.transport != "http":  # pragma: no cover - defensive future proofing
        raise SystemExit(
            f"Unsupported transport {args.transport!r}; only 'http' is available."
        )

    _run_server(host=args.host, port=args.port)


if __name__ == "__main__":  # pragma: no cover - runtime behaviour
    main(sys.argv[1:])


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
    status = {"runtime": _runtime_status()}
    return {
        "ok": ok,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "diagnostics": diagnostics,
        "status": status,
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
    payload = _health_response(ping_vertica=ping_vertica)
    status = 200 if payload.get("ok") else 503
    return JSONResponse(payload, status_code=status)


@app.get("/status", include_in_schema=False)
async def status():
    """Kubernetes-style liveness endpoint.

    The health checks run in "skip" mode to avoid touching Vertica so liveness
    probes remain lightweight.
    """

    payload = _health_response(ping_vertica=False)
    return JSONResponse(payload, status_code=200)


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

    if settings.using_placeholder_credentials():
        logger.error(
            "Vertica credentials are still set to repository placeholder values; update your .env before deployment."
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
