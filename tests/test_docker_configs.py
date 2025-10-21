from __future__ import annotations

import pathlib


def test_docker_compose_exposes_public_port() -> None:
    compose_path = pathlib.Path(__file__).resolve().parents[1] / "docker-compose.yml"
    contents = compose_path.read_text(encoding="utf-8")

    assert "ports:" in contents
    assert "8000:8000" in contents
