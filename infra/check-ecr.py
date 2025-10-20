#!/usr/bin/env python3
import json
import subprocess
import sys


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
            json.dump({"exists": False}, sys.stdout)
            return
        sys.stderr.write(message)
        raise

    description = json.loads(output.decode("utf-8"))
    repositories = description.get("repositories") or []
    if not repositories:
        json.dump({"exists": False}, sys.stdout)
        return

    repository = repositories[0]
    json.dump(
        {
            "exists": True,
            "repository_url": repository.get("repositoryUri"),
            "registry_id": repository.get("registryId"),
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
