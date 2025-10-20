from __future__ import annotations

import importlib.util
import textwrap
from pathlib import Path

import pytest


def _load_update_readme() -> object:
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "infra" / "update_readme.py"
    spec = importlib.util.spec_from_file_location("update_readme", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load update_readme module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


update_readme = _load_update_readme()


@pytest.fixture()
def temp_readme(tmp_path: Path) -> Path:
    readme = tmp_path / "README.md"
    readme.write_text(
        textwrap.dedent(
            """
            # Sample

            <!-- BEGIN MCP ENDPOINTS -->

            placeholder

            <!-- END MCP ENDPOINTS -->
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return readme


def test_build_section_marks_http_as_unavailable_when_missing() -> None:
    section = update_readme.build_section(
        http_url=None,
        health_url=None,
        sse_url=None,
        public_ip=None,
        public_dns=None,
        https_url=None,
        https_health_url=None,
        https_sse_url=None,
        cloudfront_domain=None,
    )

    assert "Not available" in section
    assert "Direct EC2" in section


def test_replace_section_inserts_generated_block(temp_readme: Path) -> None:
    section = update_readme.build_section(
        http_url=None,
        health_url=None,
        sse_url=None,
        public_ip=None,
        public_dns=None,
        https_url=None,
        https_health_url=None,
        https_sse_url=None,
        cloudfront_domain=None,
    )

    changed = update_readme.replace_section(temp_readme, section)

    assert changed is True
    updated = temp_readme.read_text(encoding="utf-8")
    assert "Not available" in updated
