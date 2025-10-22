"""Vertica MCP package initialisation."""

from .env import ensure_dotenv
from .logging_utils import configure_logging

configure_logging()
ensure_dotenv()

__all__ = ["ensure_dotenv", "configure_logging"]