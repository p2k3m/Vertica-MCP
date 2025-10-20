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
trigger a deployment.

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

If you need a full re-deploy in one shot, pass `--recreate` (or use the
`recreate` sub-command) to run a destroy followed by an apply while re-using the
same remote state configuration:

```bash
AWS_REGION=us-east-1 ./terraform.sh --recreate apply -- -auto-approve
```
