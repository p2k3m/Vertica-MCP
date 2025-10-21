"""Utilities for converting MCP Terraform metadata into Claude Desktop config."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


DEFAULT_SERVER_NAME = "vertica-mcp"


class ClaudeConfigError(Exception):
    """Raised when the Terraform metadata cannot be converted."""


@dataclass
class EndpointSelection:
    base_url: str
    sse_url: str | None
    health_url: str | None


def _normalise(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return str(value)


def _select_endpoints(metadata: Mapping[str, Any]) -> EndpointSelection:
    endpoints = metadata.get("endpoints")
    if not isinstance(endpoints, Mapping):
        endpoints = {}

    https_url = _normalise(endpoints.get("https"))
    https_sse = _normalise(endpoints.get("https_sse"))
    https_health = _normalise(endpoints.get("https_healthz"))

    http_url = _normalise(endpoints.get("http"))
    http_sse = _normalise(endpoints.get("sse"))
    http_health = _normalise(endpoints.get("healthz"))

    if https_url:
        return EndpointSelection(
            base_url=https_url,
            sse_url=https_sse,
            health_url=https_health,
        )
    if http_url:
        return EndpointSelection(
            base_url=http_url,
            sse_url=http_sse,
            health_url=http_health,
        )

    raise ClaudeConfigError("MCP metadata does not include an HTTP endpoint")


def build_transport(metadata: Mapping[str, Any]) -> dict[str, Any]:
    selection = _select_endpoints(metadata)

    transport: dict[str, Any] = {
        "type": "http",
        "url": selection.base_url,
    }
    if selection.sse_url:
        transport["sseUrl"] = selection.sse_url
    if selection.health_url:
        transport["healthUrl"] = selection.health_url

    auth = metadata.get("auth")
    if isinstance(auth, Mapping):
        header = _normalise(auth.get("header"))
        value = _normalise(auth.get("value"))
        token = _normalise(auth.get("token"))

        headers: dict[str, str] = {}
        if header and value:
            headers[header] = value
        if headers:
            transport["headers"] = headers
        if token:
            transport["token"] = token

    return transport


def build_claude_config(
    metadata: Mapping[str, Any], *, server_name: str = DEFAULT_SERVER_NAME
) -> dict[str, Any]:
    if not server_name or not server_name.strip():
        raise ClaudeConfigError("Server name must be a non-empty string")

    transport = build_transport(metadata)
    config = {
        "mcpServers": {
            server_name: {
                "transport": transport,
            }
        }
    }

    database = metadata.get("database")
    if isinstance(database, Mapping):
        extras: dict[str, Any] = {}
        for key in ("host", "port", "name", "user", "password"):
            value = database.get(key)
            if value is not None and value != "":
                extras[key] = value
        if extras:
            config["mcpServers"][server_name]["metadata"] = {"database": extras}

    return config


def write_claude_config(
    metadata: Mapping[str, Any],
    output_path: Path,
    *,
    server_name: str = DEFAULT_SERVER_NAME,
) -> Path:
    config = build_claude_config(metadata, server_name=server_name)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    return output_path


def load_metadata(path: Path) -> Mapping[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
        raise ClaudeConfigError(f"Failed to parse MCP metadata: {exc}") from exc

    if not isinstance(raw, Mapping):
        raise ClaudeConfigError("MCP metadata must be a JSON object")
    return raw


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--a2a",
        type=Path,
        default=Path("build/mcp-a2a.json"),
        help="Path to the Terraform-generated MCP metadata JSON",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("build/claude-desktop-config.json"),
        help="Where to write the Claude Desktop configuration",
    )
    parser.add_argument(
        "--server-name",
        default=DEFAULT_SERVER_NAME,
        help="Name to use for the Claude MCP server entry",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metadata = load_metadata(args.a2a)
    try:
        write_claude_config(metadata, args.output, server_name=args.server_name)
    except ClaudeConfigError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
