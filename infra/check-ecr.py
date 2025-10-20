#!/usr/bin/env python3
import json
import subprocess
import sys
from typing import Any, Dict


def main() -> None:
    try:
        query = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON input: {exc}") from exc

    repository_name = query.get("name")
    if not repository_name:
        raise SystemExit("missing required 'name' in query")

    region = query.get("region")

    args = ["aws", "ecr", "describe-repositories", "--repository-names", repository_name]
    if region:
        args.extend(["--region", region])

    try:
        output = subprocess.check_output(args, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as exc:
        message = exc.output.decode("utf-8", errors="ignore")
        if "RepositoryNotFoundException" in message:
            json.dump(_to_string_map({"exists": False}), sys.stdout)
            return
        sys.stderr.write(message)
        raise

    description = json.loads(output.decode("utf-8"))
    repositories = description.get("repositories") or []
    if not repositories:
        json.dump(_to_string_map({"exists": False}), sys.stdout)
        return

    repository = repositories[0]
    json.dump(
        _to_string_map(
            {
                "exists": True,
                "repository_url": repository.get("repositoryUri"),
                "registry_id": repository.get("registryId"),
            }
        ),
        sys.stdout,
    )


def _to_string_map(values: Dict[str, Any]) -> Dict[str, str]:
    """Return a copy of *values* with all entries coerced to strings.

    Terraform's external data source requires that every value in the
    response be a string. This helper converts Python values (including
    booleans) to the expected string representation before serialising the
    response as JSON.
    """

    result: Dict[str, str] = {}
    for key, value in values.items():
        if value is True:
            result[key] = "true"
        elif value is False:
            result[key] = "false"
        elif value is None:
            result[key] = ""
        else:
            result[key] = str(value)
    return result


if __name__ == "__main__":
    main()
