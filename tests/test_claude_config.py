import importlib.util
import json
from pathlib import Path
import sys

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "infra" / "claude_config.py"
SPEC = importlib.util.spec_from_file_location("claude_config", MODULE_PATH)
assert SPEC and SPEC.loader  # pragma: no cover - guard for missing module
claude_config = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = claude_config
SPEC.loader.exec_module(claude_config)


SAMPLE_METADATA = {
    "endpoints": {
        "http": "http://example.com/",
        "sse": "http://example.com/sse",
        "healthz": "http://example.com/healthz",
        "https": "https://example.com/",
        "https_sse": "https://example.com/sse",
        "https_healthz": "https://example.com/healthz",
    },
    "auth": {
        "header": "Authorization",
        "value": "Bearer token",
        "token": "token",
    },
    "database": {
        "host": "vertica.example.com",
        "port": 5433,
        "name": "VMart",
        "user": "dbadmin",
        "password": "secret",
    },
}


def test_build_claude_config_prefers_https():
    config = claude_config.build_claude_config(SAMPLE_METADATA, server_name="vertica")

    transport = config["mcpServers"]["vertica"]["transport"]
    assert transport["url"] == "https://example.com/"
    assert transport["sseUrl"] == "https://example.com/sse"
    assert transport["healthUrl"] == "https://example.com/healthz"
    assert transport["headers"] == {"Authorization": "Bearer token"}
    assert transport["token"] == "token"

    metadata = config["mcpServers"]["vertica"]["metadata"]
    assert metadata["database"]["host"] == "vertica.example.com"


def test_build_transport_falls_back_to_http():
    meta = {
        "endpoints": {
            "http": "http://only-http/",
            "sse": "http://only-http/sse",
        }
    }

    transport = claude_config.build_transport(meta)
    assert transport["url"] == "http://only-http/"
    assert transport["sseUrl"] == "http://only-http/sse"


def test_missing_endpoint_raises():
    with pytest.raises(claude_config.ClaudeConfigError):
        claude_config.build_transport({})


def test_write_claude_config(tmp_path: Path):
    output = tmp_path / "claude.json"
    written = claude_config.write_claude_config(SAMPLE_METADATA, output)

    assert written == output
    data = json.loads(output.read_text())
    assert "vertica-mcp" in data["mcpServers"]


def test_cli_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    a2a_path = tmp_path / "mcp-a2a.json"
    output_path = tmp_path / "claude-config.json"
    a2a_path.write_text(json.dumps(SAMPLE_METADATA))

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "claude_config.py",
            "--a2a",
            str(a2a_path),
            "--output",
            str(output_path),
            "--server-name",
            "custom",
        ],
    )

    claude_config.main()

    data = json.loads(output_path.read_text())
    assert "custom" in data["mcpServers"]

