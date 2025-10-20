# Vertica-MCP

## Infrastructure automation

Use the helper script in `infra/terraform.sh` to ensure Terraform always
leverages the remote state bucket (with DynamoDB state locking) and keeps the
existing SSM artefacts aligned with state before any plan or apply run.

```bash
cd infra
AWS_REGION=us-east-1 ./terraform.sh plan
AWS_REGION=us-east-1 ./terraform.sh apply -- -auto-approve
```

To force a full re-deployment in one go use the `--recreate` flag (or the
`recreate` sub-command), which will `destroy` and then `apply` while sharing the
same remote state and imports.

```bash
AWS_REGION=us-east-1 ./terraform.sh --recreate apply -- -auto-approve
```
