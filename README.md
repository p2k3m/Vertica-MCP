# Vertica-MCP

## Development quick start

Install the project dependencies (for example with `pip install -e .[dev]`) and
run the automated test suite before opening a pull request:

```bash
pytest
```

The service now requires a `.env` file at the project root. The repository ships
with a development-safe default that matches the Terraform configuration; add
your own secrets before deploying anywhere outside of local testing. Startup
fails fast with a clear error message if the file is missing so deployments
never fall back to placeholder credentials. Docker and the provisioned systemd
unit both mount the same `.env` file into `/app/.env`, so a missing file will
abort container startup with guidance on how to fix the issue.

### Pointing the MCP at your Vertica database

The `.env` file and Terraform variables both default to the loopback address so
the service never reaches out to an unexpected database host. Before deploying
to AWS, update `DB_HOST` (and, if necessary, the related `DB_*` settings) to
match the publicly reachable Vertica instance you want the MCP to use. When
invoking the Terraform wrapper you can also override the connection details via
environment variables such as `TF_VAR_db_host` or command-line flags like
`--db-host`.

When targeting remote clusters the MCP now understands a richer set of
connection controls:

* `DB_BACKUP_NODES` accepts a comma-separated list of `host[:port]` entries so
  the driver can automatically fail over to a secondary region when the primary
  host is unavailable.
* `DB_TLSMODE` toggles Vertica TLS negotiation (`disable`, `allow`, `prefer`,
  `require`, `verify-ca`, or `verify-full`).
* `DB_TLS_CAFILE`, `DB_TLS_CERTFILE`, and `DB_TLS_KEYFILE` allow the MCP to load
  custom certificate authorities or client credentials.
* `DB_USE_SSL` forces a legacy boolean `ssl` flag when you need to match older
  Vertica deployments.

Sample `.env` templates that demonstrate these options live under
`examples/env/`. Copy the file that matches your deployment scenario (public
TLS, legacy NoSSL, or multi-region) to the project root and replace the
placeholder values before launching the MCP.

To expose the MCP over HTTP when running locally, start the FastMCP runtime in
HTTP mode and bind it to a public interface. The packaged defaults mirror the
production deployment by listening on `0.0.0.0:8000` unless overridden with the
`LISTEN_HOST`/`LISTEN_PORT` environment variables:

```bash
uvx mcp server --transport streamable-http mcp_vertica.tools:mcp
```

For a one-command launch that matches the EC2 configuration you can now run:

```bash
python vertica-mcp
```

Or use the npm wrapper when Node is your entry point:

```bash
npm start
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

### EC2 network access checklist

Even when the MCP service is healthy, inbound traffic to an EC2 instance is
blocked unless the AWS networking layers permit the request. When opening the
application to the internet:

1. **Security group rules** – AWS security groups deny all inbound traffic
   except port `22` by default. Add an inbound rule that allows TCP traffic on
   the MCP port (for example `8000`) from `0.0.0.0/0`, or from a more
   restrictive CIDR that matches your audience.
2. **Network ACLs** – Ensure the subnet's network ACL allows the same inbound
   port and the ephemeral port range (1024–65535) for return traffic so clients
   can receive responses.
3. **Health verification** – After applying the rules, re-run the service
   health check endpoint (for example `/healthz`) from an external network to
   confirm connectivity.

### Local port exposure tips

The repository ships Docker- and natively-driven development workflows. Make
sure the MCP process is reachable from your host when testing locally:

* **Docker runs** – Map the container port to the host with
  `-p 8000:8000` (or the port you configured) so requests outside the Docker
  network can reach the MCP service. The bundled `docker-compose.yml` does this
  automatically and shares the `.env` file with the container. If you change the
  exposed port, update the `PUBLIC_HTTP_PORT` environment variable so the
  runtime can verify your container port mapping before startup.
* **Native runs** – Launch the MCP with the HTTP transport
  (`uvx mcp server --transport streamable-http ...`) and verify the runtime
  dependencies are installed (`pip install -e .[dev]`, Node, etc.). Bind the
  server to `0.0.0.0` or `127.0.0.1` to match how you plan to access it. When
  selecting a non-default port, set `PUBLIC_HTTP_PORT` to the value you expose
  so the preflight check can confirm the MCP is reachable externally.

#### Manual HTTP transport startup checklist

When you need to manually start the packaged MCP runtime outside the helper
scripts, follow this workflow so EC2-hosted or LAN clients can connect:

1. **Start the local HTTP server** – Bind explicitly to all interfaces so the
   service is reachable over a public IP:

   ```bash
   vertica-mcp --transport http --port 8000 --bind-host 0.0.0.0
   ```

   If you rely on the npm distribution, install and run it with:

   ```bash
   npm install -g @hechtcarmel/vertica-mcp
   vertica-mcp --transport http --port 8000 --bind-host 0.0.0.0 --env-file .env
   ```

   For the Python/uv build in this repository:

   ```bash
   uv sync
   source .venv/bin/activate
   vertica-mcp --transport http --port 8000 --bind-host 0.0.0.0
   ```

2. **Permit inbound traffic** – Add an AWS security group rule (or the
   equivalent firewall entry) that allows TCP traffic on port `8000` from the
   desired CIDR, for example `0.0.0.0/0` when testing from the open internet.

3. **Validate connectivity** – After updating the firewall, rerun the MCP
   server or bounce the host networking stack, then hit `/healthz` from an
   external network to confirm the port is reachable.

### Troubleshooting Vertica connectivity

Database credentials are validated during startup, but networking issues or
transient outages can still cause connection attempts to fail. The connection
pool now retries failed Vertica handshakes up to `DB_CONNECTION_RETRIES` times
(`3` by default) with a linear back-off governed by
`DB_CONNECTION_RETRY_BACKOFF_S` (defaults to `0.5` seconds). When you need
detailed stack traces—for example while debugging credentials or security group
rules—set `DB_DEBUG=1` (or any truthy value such as `true`/`yes`). The pool logs
each failed attempt and whether the connection was ultimately established,
making it easier to correlate failures with upstream network events.

### Pipeline best practices

Following a consistent release checklist keeps the Vertica MCP pipelines fast
and predictable.

1. **Start every branch with a clean environment.** Run `uv sync`, `npm ci`, or
   the equivalent helper to align your local environment with the versions
   enforced in CI before you begin work. When Terraform is involved, run
   `./terraform.sh plan` with the same `AWS_REGION` the pipeline will use so you
   can validate credentials early.
2. **Run fast feedback loops locally.** Execute the unit tests (`uv run
   pytest`) and linting (`uv run ruff check`) before opening a pull request to
   catch obvious failures without waiting for GitHub Actions. When your change
   impacts the MCP entrypoint, add a smoke test for `vertica-mcp --transport
   http --bind-host 127.0.0.1` to confirm the CLI still boots.
3. **Keep secrets out of the repo.** The CI/CD pipelines expect credentials to
   arrive via GitHub Actions secrets or the `.env` files listed in the deployment
   docs. Never commit raw passwords, Vertica DSNs, or Terraform state; rely on
   the existing secret backends and let the workflow wire them in at runtime.
4. **Prefer small, reviewable changes.** Group related Terraform, Python, and
   JavaScript updates into cohesive commits, and avoid force-pushing once a
   review has started. The workflow cache is keyed by commit hash, so rewriting
   history leads to unnecessary rebuilds and longer feedback cycles.
5. **Use workflow dispatch for infrastructure changes.** When modifying the
   Terraform modules, trigger the staging deployment manually with the GitHub
   Actions "Run workflow" button. Confirm the preview plan looks correct before
   applying in production.

### Recovering from failed pipeline runs

GitHub Actions surfaces full Terraform logs when a deployment workflow fails.
To recover:

1. Inspect the failing job to confirm whether the error was environmental (for
   example, AWS throttling) or configuration-driven.
2. If the failure was transient, re-run the workflow from the GitHub UI. The MCP
   wrapper will retry connection attempts using the new Vertica back-off and
   resume from the most recent successful Terraform state.
3. For persistent failures, reproduce locally with
   `AWS_REGION=us-east-1 ./terraform.sh plan` (and `--recreate apply` when a
   clean rebuild is required). Address the issue, push the fix, and then re-run
   the GitHub workflow to confirm recovery.

### Switching Vertica connections at runtime

The MCP can retarget its Vertica connection without a restart. Provide a JSON
object containing the standard connection fields—`host`, `port`, `user`,
`password`, and `database`—either when launching the CLI or via the HTTP API.

* **CLI:** pass the payload with `--database-payload`. Inline JSON works, or
  prefix a file path with `@` (for example `--database-payload @runtime.json`
  or `--database-payload @-` to read from `stdin`). The credentials are applied
  before the server starts and the connection pool is cleared automatically.
* **HTTP API:** send the same payload to `POST /configure/database` to switch
  the live service while it is running. The response omits the password but
  confirms which connection is active.

Example API call:

```bash
curl -X POST "http://localhost:8000/configure/database" \
  -H "Content-Type: application/json" \
  -d '{
        "host": "analytics.vertica.example.com",
        "port": 5433,
        "user": "runtime_user",
        "password": "runtime_secret",
        "database": "analytics"
      }'
```

### Claude Desktop integration

Each `terraform.sh apply` run writes `build/mcp-a2a.json` and
`build/claude-desktop-config.json`. The latter is ready to drop into Claude
Desktop's `claude_desktop_config.json` file: merge the `mcpServers` block with
your existing configuration (or copy it wholesale on a fresh install) so the
desktop client can reach the public MCP endpoint immediately. The generated
config prefers the HTTPS CloudFront address when available and includes the
correct authorization header when an HTTP bearer token is configured.

## Deployment endpoints

This section is automatically managed by the deployment workflow. Do not edit
manually.

<!-- BEGIN MCP ENDPOINTS -->

**Direct EC2 (HTTP on port 8000)**  
* Base URL: [`http://3.109.150.92:8000/`](http://3.109.150.92:8000/)
* Health check: [`http://3.109.150.92:8000/healthz`](http://3.109.150.92:8000/healthz)
* Server-Sent Events: [`http://3.109.150.92:8000/sse`](http://3.109.150.92:8000/sse)
* Public IP: `3.109.150.92`
* Public DNS: `ec2-3-109-150-92.ap-south-1.compute.amazonaws.com`

**CloudFront (HTTPS)**  
* Not enabled for this deployment.

_Last updated: 2025-10-22 16:33:15Z_

<!-- END MCP ENDPOINTS -->
