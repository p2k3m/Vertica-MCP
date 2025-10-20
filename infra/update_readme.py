#!/usr/bin/env python3
"""Update the README deployment endpoints section from Terraform outputs."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from typing import Optional

BEGIN_MARKER = "<!-- BEGIN MCP ENDPOINTS -->"
END_MARKER = "<!-- END MCP ENDPOINTS -->"


def format_link(url: Optional[str]) -> str:
    """Return a Markdown link for the URL or ``n/a`` when missing."""
    if not url:
        return "`n/a`"
    cleaned = url.strip()
    return f"[`{cleaned}`]({cleaned})"


def build_section(
    *,
    http_url: Optional[str],
    health_url: Optional[str],
    sse_url: Optional[str],
    public_ip: Optional[str],
    public_dns: Optional[str],
    https_url: Optional[str],
    https_health_url: Optional[str],
    https_sse_url: Optional[str],
    cloudfront_domain: Optional[str],
) -> str:
    """Render the Markdown snippet that lives between the README markers."""

    lines: list[str] = []

    lines.append("**Direct EC2 (HTTP on port 8000)**  ")
    if http_url:
        lines.append(f"* Base URL: {format_link(http_url)}")
        lines.append(f"* Health check: {format_link(health_url)}")
        lines.append(f"* Server-Sent Events: {format_link(sse_url)}")
        lines.append(f"* Public IP: `{public_ip.strip() if public_ip else 'n/a'}`")
        lines.append(f"* Public DNS: `{public_dns.strip() if public_dns else 'n/a'}`")
    else:
        lines.append("* Not available (deployment not yet provisioned).")

    lines.append("")
    lines.append("**CloudFront (HTTPS)**  ")
    if https_url:
        lines.append(f"* Distribution domain: `{cloudfront_domain.strip() if cloudfront_domain else 'n/a'}`")
        lines.append(f"* Base URL: {format_link(https_url)}")
        lines.append(f"* Health check: {format_link(https_health_url)}")
        lines.append(f"* Server-Sent Events: {format_link(https_sse_url)}")
    else:
        lines.append("* Not enabled for this deployment.")

    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    lines.append("")
    lines.append(f"_Last updated: {timestamp}_")

    return "\n".join(lines)


def replace_section(readme_path: Path, new_section: str) -> bool:
    """Replace the README marker block with ``new_section``.

    Returns ``True`` when the file was modified.
    """

    contents = readme_path.read_text(encoding="utf-8")
    try:
        start = contents.index(BEGIN_MARKER) + len(BEGIN_MARKER)
        end = contents.index(END_MARKER, start)
    except ValueError as exc:  # pragma: no cover - guarded by CI
        raise SystemExit("README markers for MCP endpoints were not found") from exc

    before = contents[:start]
    after = contents[end:]

    replacement = f"\n\n{new_section}\n\n"
    updated = before + replacement + after

    if updated == contents:
        return False

    readme_path.write_text(updated, encoding="utf-8")
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readme", default="README.md", type=Path)
    parser.add_argument("--http-url")
    parser.add_argument("--health-url")
    parser.add_argument("--sse-url")
    parser.add_argument("--public-ip")
    parser.add_argument("--public-dns")
    parser.add_argument("--https-url")
    parser.add_argument("--https-health-url")
    parser.add_argument("--https-sse-url")
    parser.add_argument("--cloudfront-domain")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    section = build_section(
        http_url=args.http_url,
        health_url=args.health_url,
        sse_url=args.sse_url,
        public_ip=args.public_ip,
        public_dns=args.public_dns,
        https_url=args.https_url,
        https_health_url=args.https_health_url,
        https_sse_url=args.https_sse_url,
        cloudfront_domain=args.cloudfront_domain,
    )
    updated = replace_section(Path(args.readme), section)
    if not updated:
        print("README already up to date.")


if __name__ == "__main__":
    main()
