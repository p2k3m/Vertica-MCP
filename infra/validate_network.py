"""Validate MCP network accessibility requirements.

This script is executed from the CI pipeline to ensure that the
infrastructure created by Terraform exposes the MCP service on the
expected port and that the associated network ACL allows return
traffic.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Iterable, List, Optional


class ValidationError(Exception):
    """Raised when one or more validation checks fail."""


@dataclass
class SecurityGroupCheckResult:
    group_id: str
    inbound_allows: bool
    outbound_allows: bool


@dataclass
class NaclCheckResult:
    nacl_id: str
    inbound_allows: bool
    outbound_allows_start: bool
    outbound_allows_end: bool


def format_range(start: int, end: int) -> str:
    return str(start) if start == end else f"{start}-{end}"


def summarize_security_groups(
    results: Iterable[SecurityGroupCheckResult],
    port: int,
    return_start: int,
    return_end: int,
    cidr: str,
) -> str:
    lines = [
        "Security group evaluation:",
    ]
    port_range = format_range(return_start, return_end)
    for result in results:
        inbound = "allows" if result.inbound_allows else "blocks"
        outbound = "allows" if result.outbound_allows else "blocks"
        lines.append(
            f"  - {result.group_id} {inbound} inbound TCP {port} from {cidr}"
        )
        lines.append(
            f"    and {outbound} outbound TCP {port_range} to {cidr}."
        )
    return "\n".join(lines)


def summarize_nacls(
    results: Iterable[NaclCheckResult],
    port: int,
    return_start: int,
    return_end: int,
    cidr: str,
) -> str:
    lines = [
        "Network ACL evaluation:",
    ]
    port_range = format_range(return_start, return_end)
    for result in results:
        inbound = "allows" if result.inbound_allows else "blocks"
        outbound_start = "allows" if result.outbound_allows_start else "blocks"
        outbound_end = "allows" if result.outbound_allows_end else "blocks"
        outbound_summary = "allows" if result.outbound_allows_start and result.outbound_allows_end else "blocks"
        lines.append(
            f"  - {result.nacl_id} {inbound} inbound TCP {port} from {cidr}"
        )
        lines.append(
            f"    outbound start/end checks: {outbound_start} {return_start}, {outbound_end} {return_end} (overall {outbound_summary} {port_range})."
        )
    return "\n".join(lines)


def describe_network_flow(
    port: int,
    return_start: int,
    return_end: int,
    cidr: str,
    security_groups: Iterable[SecurityGroupCheckResult],
    nacls: Iterable[NaclCheckResult],
) -> str:
    sg_ids = ", ".join(result.group_id for result in security_groups) or "none"
    nacl_ids = ", ".join(result.nacl_id for result in nacls) or "none"
    port_range = format_range(return_start, return_end)
    return "\n".join(
        [
            "Deployment network flow:",
            f"  • Client traffic targets TCP {port} on the EC2 host.",
            f"  • Security group(s) [{sg_ids}] gate this traffic before it reaches the subnet.",
            f"  • Subnet network ACL(s) [{nacl_ids}] must also allow the request and subsequent return traffic {port_range}.",
            f"  • The systemd service maps host port {port} to the Docker container, so permitted packets are delivered directly to the MCP server.",
            f"  • Responses travel back through the Docker port, the security group egress rules, and the subnet ACL rules to {cidr}.",
        ]
    )


def run_aws_command(args: List[str]) -> dict:
    """Run an AWS CLI command and parse its JSON output."""

    cmd = ["aws", *args, "--output", "json"]
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:  # pragma: no cover - surface in CI
        stderr = exc.stderr.strip()
        print(f"AWS CLI command failed: {' '.join(cmd)}", file=sys.stderr)
        if stderr:
            print(stderr, file=sys.stderr)
        raise

    stdout = result.stdout.strip()
    if not stdout:
        return {}
    return json.loads(stdout)


def extract_instance(instance_id: str) -> dict:
    data = run_aws_command([
        "ec2",
        "describe-instances",
        "--instance-ids",
        instance_id,
    ])

    reservations = data.get("Reservations", [])
    for reservation in reservations:
        for instance in reservation.get("Instances", []):
            if instance.get("InstanceId") == instance_id:
                return instance
    raise ValidationError(f"Instance {instance_id} not found in describe-instances response")


def security_group_allows_port(permissions: Iterable[dict], port: int, cidr: str) -> bool:
    for permission in permissions:
        protocol = permission.get("IpProtocol")
        ip_ranges = permission.get("IpRanges", [])
        if not any(r.get("CidrIp") == cidr for r in ip_ranges):
            continue

        if protocol == "-1":
            return True
        if protocol != "tcp":
            continue

        from_port = permission.get("FromPort")
        to_port = permission.get("ToPort")
        if from_port is None or to_port is None:
            continue
        if from_port <= port <= to_port:
            return True
    return False


def security_group_allows_range(permissions: Iterable[dict], start_port: int, end_port: int, cidr: str) -> bool:
    for permission in permissions:
        protocol = permission.get("IpProtocol")
        ip_ranges = permission.get("IpRanges", [])
        if not any(r.get("CidrIp") == cidr for r in ip_ranges):
            continue

        if protocol == "-1":
            return True
        if protocol != "tcp":
            continue

        from_port = permission.get("FromPort")
        to_port = permission.get("ToPort")
        if from_port is None or to_port is None:
            continue
        if from_port <= start_port and to_port >= end_port:
            return True
    return False


def evaluate_security_groups(group_ids: List[str], port: int, return_start: int, return_end: int, cidr: str) -> List[SecurityGroupCheckResult]:
    if not group_ids:
        raise ValidationError("Instance has no associated security groups")

    data = run_aws_command([
        "ec2",
        "describe-security-groups",
        "--group-ids",
        *group_ids,
    ])

    results: List[SecurityGroupCheckResult] = []
    for sg in data.get("SecurityGroups", []):
        group_id = sg.get("GroupId", "unknown")
        inbound_ok = security_group_allows_port(sg.get("IpPermissions", []), port, cidr)
        outbound_ok = security_group_allows_range(sg.get("IpPermissionsEgress", []), return_start, return_end, cidr)
        results.append(SecurityGroupCheckResult(group_id, inbound_ok, outbound_ok))
    return results


def nacl_entry_matches(entry: dict, port: int, cidr: str) -> bool:
    if entry.get("CidrBlock") != cidr:
        return False

    protocol = entry.get("Protocol")
    if protocol not in ("-1", "6"):
        return False

    port_range = entry.get("PortRange")
    if port_range is None:
        return True

    start = port_range.get("From")
    end = port_range.get("To")
    if start is None or end is None:
        return False
    return start <= port <= end


def nacl_allows_port(entries: Iterable[dict], port: int, cidr: str, egress: bool) -> bool:
    relevant = sorted(
        (entry for entry in entries if entry.get("Egress") is bool(egress)),
        key=lambda entry: entry.get("RuleNumber", 0),
    )
    for entry in relevant:
        if not nacl_entry_matches(entry, port, cidr):
            continue
        return entry.get("RuleAction", "").lower() == "allow"
    return False


def evaluate_nacls(subnet_id: str, port: int, return_start: int, return_end: int, cidr: str) -> List[NaclCheckResult]:
    data = run_aws_command([
        "ec2",
        "describe-network-acls",
        "--filters",
        f"Name=association.subnet-id,Values={subnet_id}",
    ])

    nacls = data.get("NetworkAcls", [])
    if not nacls:
        raise ValidationError(f"No network ACLs associated with subnet {subnet_id}")

    results: List[NaclCheckResult] = []
    for nacl in nacls:
        entries = nacl.get("Entries", [])
        inbound_ok = nacl_allows_port(entries, port, cidr, egress=False)
        outbound_start_ok = nacl_allows_port(entries, return_start, cidr, egress=True)
        outbound_end_ok = nacl_allows_port(entries, return_end, cidr, egress=True)
        results.append(
            NaclCheckResult(
                nacl_id=nacl.get("NetworkAclId", "unknown"),
                inbound_allows=inbound_ok,
                outbound_allows_start=outbound_start_ok,
                outbound_allows_end=outbound_end_ok,
            )
        )
    return results


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate MCP network access policies")
    parser.add_argument("--instance-id", required=True, help="ID of the MCP EC2 instance")
    parser.add_argument("--port", type=int, default=8000, help="Application listening port to validate")
    parser.add_argument(
        "--return-port-start",
        type=int,
        default=1024,
        help="Beginning of the return traffic port range",
    )
    parser.add_argument(
        "--return-port-end",
        type=int,
        default=65535,
        help="End of the return traffic port range",
    )
    parser.add_argument(
        "--cidr",
        default="0.0.0.0/0",
        help="CIDR block that must be allowed",
    )

    args = parser.parse_args(argv)

    if args.return_port_start > args.return_port_end:
        raise ValidationError("Return port start must be less than or equal to return port end")

    instance = extract_instance(args.instance_id)
    group_ids = [sg.get("GroupId") for sg in instance.get("SecurityGroups", []) if sg.get("GroupId")]
    subnet_id = instance.get("SubnetId")
    if not subnet_id:
        raise ValidationError(f"Instance {args.instance_id} does not have an associated subnet")

    sg_results = evaluate_security_groups(group_ids, args.port, args.return_port_start, args.return_port_end, args.cidr)
    nacl_results = evaluate_nacls(subnet_id, args.port, args.return_port_start, args.return_port_end, args.cidr)

    errors: List[str] = []

    print(summarize_security_groups(sg_results, args.port, args.return_port_start, args.return_port_end, args.cidr))
    print()
    print(summarize_nacls(nacl_results, args.port, args.return_port_start, args.return_port_end, args.cidr))
    print()
    print(describe_network_flow(args.port, args.return_port_start, args.return_port_end, args.cidr, sg_results, nacl_results))
    print()

    if not any(result.inbound_allows for result in sg_results):
        ids = ", ".join(result.group_id for result in sg_results)
        errors.append(
            f"Security groups [{ids}] do not allow inbound TCP {args.port} from {args.cidr}."
        )

    if not any(result.outbound_allows for result in sg_results):
        ids = ", ".join(result.group_id for result in sg_results)
        errors.append(
            f"Security groups [{ids}] do not allow outbound TCP {args.return_port_start}-{args.return_port_end} to {args.cidr}."
        )

    if not any(result.inbound_allows for result in nacl_results):
        ids = ", ".join(result.nacl_id for result in nacl_results)
        errors.append(
            f"Network ACLs [{ids}] do not allow inbound TCP {args.port} from {args.cidr}."
        )

    if not any(result.outbound_allows_start and result.outbound_allows_end for result in nacl_results):
        ids = ", ".join(result.nacl_id for result in nacl_results)
        errors.append(
            f"Network ACLs [{ids}] do not allow outbound return traffic (ports {args.return_port_start}-{args.return_port_end}) to {args.cidr}."
        )

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(
        "Security groups and network ACLs allow inbound port "
        f"{args.port} and outbound return traffic {args.return_port_start}-{args.return_port_end} to {args.cidr}."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
