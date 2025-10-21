"""Project-wide environment loading helpers.

This module centralises the logic that ensures operators always provide the
required ``.env`` file when launching the Vertica MCP runtime.  The
configuration layer depends heavily on environment variables, so we eagerly load
them from the repository root before any other modules evaluate their settings.
"""

from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv

__all__ = ["ensure_dotenv"]

logger = logging.getLogger("mcp_vertica.env")

_DOTENV_LOADED = False


def ensure_dotenv() -> None:
    """Load the project ``.env`` file exactly once.

    A missing ``.env`` should abort startup with a clear error so deployments do
    not accidentally rely on placeholder defaults.  The loader is idempotent to
    allow repeated imports across modules without re-reading the file.
    """

    global _DOTENV_LOADED

    if _DOTENV_LOADED:
        return

    project_root = Path(__file__).resolve().parent.parent.parent
    dotenv_path = project_root / ".env"

    if not dotenv_path.exists():  # pragma: no cover - defensive guard
        message = (
            "Required environment file missing at "
            f"{dotenv_path}. Create the file with your Vertica connection "
            "settings before starting the server."
        )
        logger.critical(message)
        raise FileNotFoundError(message)

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
