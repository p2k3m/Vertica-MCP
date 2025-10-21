# Environment configuration samples

The files in this directory provide ready-to-use `.env` templates for common
remote Vertica deployment patterns. Copy the sample that matches your
infrastructure to the project root (or merge the settings into your existing
`.env`) and then replace the placeholder hosts, credentials, and certificate
paths with real values.

* `public-ssl.env` – Connects to a publicly reachable Vertica service with
  strict TLS validation enabled.
* `public-nossl.env` – Targets a legacy instance that does not support TLS.
  Only use this profile on trusted private networks.
* `multi-region-ssl.env` – Demonstrates how to provide multiple regional
  endpoints via `DB_BACKUP_NODES` so the MCP can automatically fail over when
  the primary host is unavailable.

Each template intentionally includes comments describing when and why to use the
featured settings so operators can adapt the configuration safely.
