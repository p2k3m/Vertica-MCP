"""Runtime helpers shared by the Vertica MCP server and tool transport."""

from __future__ import annotations

import json
import logging
import os
from contextlib import suppress
from ipaddress import ip_address
from typing import Any, Dict, List
from urllib.error import URLError
from urllib.request import urlopen

__all__ = [
    "allow_loopback_listen",
    "external_ip_info",
    "is_bindable_listen_host",
    "resolve_listen_host",
    "resolve_listen_port",
]

logger = logging.getLogger("mcp_vertica.runtime")

_BIND_HOST_KEYS = ("LISTEN_HOST", "MCP_LISTEN_HOST", "BIND_HOST", "MCP_BIND_HOST")
_BIND_PORT_KEYS = ("LISTEN_PORT", "MCP_LISTEN_PORT", "BIND_PORT", "MCP_BIND_PORT", "PORT")


def allow_loopback_listen() -> bool:
    """Return ``True`` when loopback interfaces are allowed."""

    return os.environ.get("ALLOW_LOOPBACK_LISTEN", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def external_ip_info(*, timeout: float = 2.0) -> Dict[str, Any]:
    """Best-effort discovery of the MCP runtime's external IP address."""

    configured = os.environ.get("EXTERNAL_IP", "").strip()
    if configured:
        return {
            "ok": True,
            "ip": configured,
            "source": "environment",
        }

    providers: List[tuple[str, str | None]] = [
        ("https://api.ipify.org?format=json", "ip"),
        ("https://ifconfig.co/json", "ip"),
    ]

    errors: List[Dict[str, Any]] = []
    for url, key in providers:
        try:
            with urlopen(url, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except (TimeoutError, URLError, OSError) as exc:
            errors.append(
                {
                    "source": url,
                    "error": str(exc),
                    "exception": exc.__class__.__name__,
                }
            )
            continue

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(
                {
                    "source": url,
                    "error": f"Failed to decode response: {exc}",
                    "exception": exc.__class__.__name__,
                }
            )
            continue

        candidate = payload.get(key) if key else None
        if candidate:
            return {
                "ok": True,
                "ip": str(candidate).strip(),
                "source": url,
            }

        errors.append(
            {
                "source": url,
                "error": f"Response missing expected key {key!r}",
            }
        )

    return {"ok": False, "errors": errors}


def resolve_listen_host(*, log: logging.Logger | None = None) -> str:
    """Determine the HTTP bind address for the MCP service."""

    log = log or logger

    allow_loopback = allow_loopback_listen()

    for key in _BIND_HOST_KEYS:
        value = os.environ.get(key)
        if not value:
            continue

        candidate = value.strip()
        if not candidate:
            continue

        if is_bindable_listen_host(candidate, allow_loopback=allow_loopback):
            return candidate

        log.warning(
            "Ignoring %s environment variable value %r; not a bindable interface.",
            key,
            value,
        )
        if candidate in {"127.0.0.1", "localhost"} and not allow_loopback:
            log.warning(
                "Set ALLOW_LOOPBACK_LISTEN=1 to bind Vertica MCP to loopback interfaces explicitly.",
            )

    legacy_host = os.environ.get("HOST")
    if legacy_host and legacy_host.strip():
        candidate = legacy_host.strip()
        if is_bindable_listen_host(candidate):
            return candidate
        log.warning(
            "Ignoring HOST environment variable value %r; set LISTEN_HOST to override the bind address.",
            legacy_host,
        )

    return "0.0.0.0"


def resolve_listen_port(*, log: logging.Logger | None = None) -> int:
    """Determine the TCP port for the MCP service."""

    log = log or logger

    for key in _BIND_PORT_KEYS:
        value = os.environ.get(key)
        port = _coerce_port(value, key, log=log)
        if port is not None:
            return port

    return 8000


def is_bindable_listen_host(value: str, *, allow_loopback: bool | None = None) -> bool:
    if not value:
        return False

    candidate = value.strip()
    if not candidate:
        return False

    if allow_loopback is None:
        allow_loopback = allow_loopback_listen()

    with suppress(ValueError):
        ip = ip_address(candidate)
        if ip.is_unspecified:
            return True
        if ip.is_loopback:
            return allow_loopback
        if ip.is_private:
            return True
        return False

    return False


def _coerce_port(raw: str | None, key: str, *, log: logging.Logger) -> int | None:
    if raw is None:
        return None

    candidate = raw.strip()
    if not candidate:
        return None

    try:
        port = int(candidate)
    except ValueError:
        log.warning(
            "Ignoring non-integer %s value %r when determining listen port.",
            key,
            raw,
        )
        return None

    if not (0 < port < 65536):
        log.warning(
            "%s value %r is outside the valid TCP port range; ignoring.",
            key,
            raw,
        )
        return None

    return port
