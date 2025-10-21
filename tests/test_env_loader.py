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

    monkeypatch.setattr(module, "_candidate_paths", lambda: [Path("/tmp/a"), Path("/tmp/b")])

    with pytest.raises(FileNotFoundError) as exc:
        module.ensure_dotenv()

    message = str(exc.value)
    assert "Required environment file missing" in message
    assert "/tmp/a" in message and "/tmp/b" in message
    assert "Resolution:" in message


def test_ensure_dotenv_errors_when_load_fails(reload_env_module, monkeypatch: pytest.MonkeyPatch):
    module = reload_env_module

    monkeypatch.setattr(Path, "exists", lambda self: True, raising=False)
    monkeypatch.setattr(module, "load_dotenv", lambda path: False, raising=False)

    with pytest.raises(RuntimeError) as exc:
        module.ensure_dotenv()

    assert "Failed to load environment variables" in str(exc.value)


def test_candidate_paths_respect_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VERTICA_MCP_ENV_FILE", "~/secrets/.env.mcp")
    monkeypatch.setenv("MCP_ENV_FILE", "~/ignored.env")

    candidates = env_module._candidate_paths()

    # The override should be expanded and appear before the repository default
    assert Path("~/secrets/.env.mcp").expanduser() == candidates[0]
    assert candidates[-1].name == ".env"
