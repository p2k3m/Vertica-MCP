"""Vertica MCP package initialisation."""

from .env import ensure_dotenv

ensure_dotenv()

__all__ = ["ensure_dotenv"]