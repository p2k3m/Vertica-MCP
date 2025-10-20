"""Tests for the systemd service unit generated in Terraform."""

from __future__ import annotations

import pathlib
import re


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
INFRA_MAIN = REPO_ROOT / "infra" / "main.tf"


def _extract_service_unit() -> str:
    """Return the interpolated systemd unit contents from ``infra/main.tf``."""

    file_text = INFRA_MAIN.read_text(encoding="utf-8")
    match = re.search(
        r"service_unit_contents\s*=\s*<<-?UNIT\n(?P<unit>.*?)\n\s*UNIT",
        file_text,
        re.DOTALL,
    )
    if not match:
        raise AssertionError("service_unit_contents heredoc was not found in infra/main.tf")
    return match.group("unit").strip()


def test_service_unit_enables_container_auto_restart() -> None:
    """The systemd service should automatically restart the MCP container."""

    unit = _extract_service_unit()

    assert "Restart=always" in unit
    assert "RestartSec=5" in unit
    assert "--restart unless-stopped" in unit


def test_service_unit_recovers_from_previous_container_failure() -> None:
    """Systemd should remove any failed container instance before starting a new one."""

    unit = _extract_service_unit()

    exec_start_pre_lines = [
        line.strip()
        for line in unit.splitlines()
        if line.strip().startswith("ExecStartPre=")
    ]

    assert any("docker rm -f mcp" in line for line in exec_start_pre_lines)
    assert any("docker pull" in line for line in exec_start_pre_lines)
