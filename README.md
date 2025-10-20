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

## Deployment endpoints

This section is automatically managed by the deployment workflow. Do not edit
manually.

<!-- BEGIN MCP ENDPOINTS -->

**Direct EC2 (HTTP on port 8000)**  
* Base URL: [`http://13.200.202.171:8000/`](http://13.200.202.171:8000/)
* Health check: [`http://13.200.202.171:8000/healthz`](http://13.200.202.171:8000/healthz)
* Server-Sent Events: [`http://13.200.202.171:8000/sse`](http://13.200.202.171:8000/sse)
* Public IP: `13.200.202.171`
* Public DNS: `ec2-13-200-202-171.ap-south-1.compute.amazonaws.com`

**CloudFront (HTTPS)**  
* Not enabled for this deployment.

_Last updated: 2025-10-20 14:12:50Z_

<!-- END MCP ENDPOINTS -->
