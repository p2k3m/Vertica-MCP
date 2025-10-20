# Vertica-MCP

## Development quick start

Install the project dependencies (for example with `pip install -e .[dev]`) and
run the automated test suite before opening a pull request:

```bash
pytest
```

## Deployment & destruction

Infrastructure changes are applied via the workflows in `.github/workflows/`.
The `Build & Deploy MCP (apply)` workflow automatically rebuilds and applies the
Terraform stack whenever files that materially affect the MCP service change
(`src/`, `sql/`, `infra/`, `Dockerfile`, `pyproject.toml`, or the workflow
itself). Documentation-only edits—such as changes to this README—will not
trigger a deployment. When the workflow runs because of a merge to `main` it
invokes the Terraform wrapper with `--recreate apply`, guaranteeing that the
previous deployment is destroyed before a fresh stack is created.

For local plans or ad-hoc applies, use the helper script in `infra/terraform.sh`
so the remote state bucket (with DynamoDB locking) and SSM artefacts stay in
sync:

```bash
cd infra
AWS_REGION=us-east-1 ./terraform.sh plan
AWS_REGION=us-east-1 ./terraform.sh apply -- -auto-approve
```

The wrapper enforces a singleton MCP host by default. If you intentionally need
to launch additional MCP instances, pass `--allow-multiple` (or set
`TF_VAR_allow_multiple_mcp_instances=true`) before applying so the singleton
guard can be bypassed explicitly.

To destroy the stack when you are done:

```bash
cd infra
AWS_REGION=us-east-1 ./terraform.sh destroy -- -auto-approve
```

For a guaranteed clean redeploy (whether locally or in automation) use the
`--recreate` flag so the wrapper destroys the existing infrastructure and then
applies the desired state in one run:

```bash
AWS_REGION=us-east-1 ./terraform.sh --recreate apply -- -auto-approve
```

### Systemd service configuration

The EC2 host provisions a `mcp.service` systemd unit that keeps the Dockerized
MCP API online. The unit pulls the latest container image, removes any failed
`mcp` container instance, and then launches the service with
`--restart unless-stopped` so Docker maintains the container lifecycle. Systemd
adds another layer of resilience with `Restart=always` and a five-second
`RestartSec` back-off. Environment variables are sourced from the generated
`/etc/mcp.env` file before the service starts, and `ExecStartPre` health checks
ensure all required database settings are present before the container runs.

## Deployment endpoints

This section is automatically managed by the deployment workflow. Do not edit
manually.

<!-- BEGIN MCP ENDPOINTS -->

**Direct EC2 (HTTP on port 8000)**  
* Not available (deployment not yet provisioned).

**CloudFront (HTTPS)**  
* Not enabled for this deployment.

_Last updated: 2025-10-20 14:54:47Z_

<!-- END MCP ENDPOINTS -->
