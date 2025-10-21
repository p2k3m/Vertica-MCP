"""Unit tests for the project-wide .env loader."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import mcp_vertica.env as env_module


@pytest.fixture()
def reload_env_module(monkeypatch: pytest.MonkeyPatch):
    """Reload the env module so each test starts from a clean slate."""

    reloaded = importlib.reload(env_module)
    monkeypatch.setattr(reloaded, "_DOTENV_LOADED", False, raising=False)
    return reloaded


def test_ensure_dotenv_errors_when_missing(reload_env_module, monkeypatch: pytest.MonkeyPatch):
    module = reload_env_module

    original_exists = Path.exists

    def fake_exists(self: Path) -> bool:
        if self.name == ".env":
            return False
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists, raising=False)

    with pytest.raises(FileNotFoundError) as exc:
        module.ensure_dotenv()

    assert "Required environment file missing" in str(exc.value)


def test_ensure_dotenv_errors_when_load_fails(reload_env_module, monkeypatch: pytest.MonkeyPatch):
    module = reload_env_module

    monkeypatch.setattr(Path, "exists", lambda self: True, raising=False)
    monkeypatch.setattr(module, "load_dotenv", lambda path: False, raising=False)

    with pytest.raises(RuntimeError) as exc:
        module.ensure_dotenv()

    assert "Failed to load environment variables" in str(exc.value)
