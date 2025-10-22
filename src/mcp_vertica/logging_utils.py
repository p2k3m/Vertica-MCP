"""Utility helpers for Vertica MCP logging and error reporting."""

from __future__ import annotations

import logging
import os
import sys
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, Mapping

_LOGGER = logging.getLogger("mcp_vertica.logging")

_ERROR_HISTORY_LIMIT = 50
try:
    _ERROR_HISTORY_LIMIT = max(
        1, int(os.getenv("MCP_ERROR_HISTORY_LIMIT", str(_ERROR_HISTORY_LIMIT)))
    )
except ValueError:
    _ERROR_HISTORY_LIMIT = 50

_ERROR_HISTORY: Deque[Dict[str, Any]] = deque(maxlen=_ERROR_HISTORY_LIMIT)

_CONFIGURED = False


def _debug_level_from_env(raw: str | None) -> tuple[int, int]:
    """Return the logging level and parsed DEBUG value."""

    if raw is None:
        return logging.WARNING, 0

    candidate = raw.strip()
    if not candidate:
        return logging.WARNING, 0

    try:
        debug_value = int(candidate)
    except ValueError:
        _LOGGER.warning("Invalid DEBUG value %r; defaulting to WARNING level", raw)
        return logging.WARNING, 0

    debug_value = max(0, min(debug_value, 3))
    if debug_value == 0:
        return logging.WARNING, debug_value
    if debug_value == 1:
        return logging.INFO, debug_value
    # DEBUG levels 2 and 3 both map to full DEBUG output; the distinction is
    # available for future expansion (for example, enabling SQL tracing).
    return logging.DEBUG, debug_value


def configure_logging(*, force: bool = False) -> None:
    """Initialise application logging according to the DEBUG environment variable."""

    global _CONFIGURED

    if _CONFIGURED and not force:
        return

    debug_env = os.getenv("DEBUG")
    level, parsed_debug = _debug_level_from_env(debug_env)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )

    # Align commonly used third party loggers with the configured level so they
    # remain visible during debugging sessions.
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(logger_name).setLevel(level)

    _LOGGER.info("Configured logging level %s (DEBUG=%s)", logging.getLevelName(level), parsed_debug)

    _CONFIGURED = True


def record_service_error(
    *,
    source: str,
    message: str,
    exception: Exception | None = None,
    context: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Record a service error for surfacing via health endpoints and CI logs."""

    entry: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "message": message,
    }

    if exception is not None:
        entry["exception"] = exception.__class__.__name__
        entry["error"] = str(exception)

    if context:
        entry["context"] = dict(context)

    _ERROR_HISTORY.append(entry)

    if os.getenv("GITHUB_ACTIONS") == "true":
        annotation = message
        if exception is not None:
            annotation = f"{message} ({exception.__class__.__name__}: {exception})"
        print(f"::error title={source}::{annotation}", file=sys.stdout, flush=True)

    return entry


def recent_errors(limit: int | None = None) -> list[Dict[str, Any]]:
    """Return a list of the most recent recorded errors."""

    if limit is not None:
        if limit <= 0:
            return []
        return list(_ERROR_HISTORY)[-limit:]
    return list(_ERROR_HISTORY)


def clear_error_history() -> None:
    """Remove all recorded error entries."""

    _ERROR_HISTORY.clear()
