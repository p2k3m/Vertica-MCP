"""Project-wide environment loading helpers.

This module centralises the logic that ensures operators always provide the
required ``.env`` file when launching the Vertica MCP runtime.  The
configuration layer depends heavily on environment variables, so we eagerly load
them from the repository root before any other modules evaluate their settings.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from textwrap import dedent

from dotenv import load_dotenv

__all__ = ["ensure_dotenv"]

logger = logging.getLogger("mcp_vertica.env")

_DOTENV_LOADED = False


def _candidate_paths() -> list[Path]:
    """Return possible locations for the MCP ``.env`` file."""

    overrides: list[str] = []
    for key in ("VERTICA_MCP_ENV_FILE", "MCP_ENV_FILE"):
        override = os.environ.get(key, "").strip()
        if override:
            overrides.append(override)

    candidates = [Path(path).expanduser() for path in overrides]

    project_root = Path(__file__).resolve().parent.parent.parent
    candidates.append(project_root / ".env")

    return candidates


def ensure_dotenv() -> None:
    """Load the project ``.env`` file exactly once.

    A missing ``.env`` should abort startup with a clear error so deployments do
    not accidentally rely on placeholder defaults.  The loader is idempotent to
    allow repeated imports across modules without re-reading the file.
    """

    global _DOTENV_LOADED

    if _DOTENV_LOADED:
        return

    candidates = _candidate_paths()

    existing_path = next((path for path in candidates if path.exists()), None)

    if existing_path is None:
        search_list = "\n".join(f"  - {path}" for path in candidates)
        resolution = dedent(
            """
            Create the file with your Vertica connection settings or mount it into
            the runtime container. When using Docker or the provisioned systemd
            service, ensure the same file is available inside the container (for
            example via ``-v /etc/mcp.env:/app/.env:ro``) or set the
            ``VERTICA_MCP_ENV_FILE`` environment variable to the correct path.
            """
        ).strip()
        message = (
            "Required environment file missing; checked the following locations:\n"
            f"{search_list}\nResolution: {resolution}"
        )
        logger.critical(message)
        raise FileNotFoundError(message)

    dotenv_path = existing_path

    loaded = load_dotenv(dotenv_path)
    if not loaded:
        message = (
            f"Failed to load environment variables from {dotenv_path}. "
            "Ensure the file is readable and formatted as KEY=VALUE pairs."
        )
        logger.critical(message)
        raise RuntimeError(message)

    _DOTENV_LOADED = True
    logger.debug("Loaded environment variables from %s", dotenv_path)
