#!/usr/bin/env bash
set -euo pipefail

DEFAULT_AWS_REGION="us-east-1"
DEFAULT_INSTANCE_TYPE="t3.micro"
DEFAULT_SUBNET_ID=""
DEFAULT_DB_HOST="127.0.0.1"
DEFAULT_DB_PORT="5433"
DEFAULT_DB_USER="mcp_app"
DEFAULT_DB_PASSWORD="change-me-please"
DEFAULT_DB_NAME="vertica"

usage() {
  cat <<'USAGE'
Usage: terraform.sh [--recreate] [--allow-multiple] <plan|apply|destroy|recreate> [-- <terraform args>]

Ensures the Terraform backend uses S3 with DynamoDB locking, imports
pre-existing SSM artefacts into state, and then executes the requested
Terraform command. The script also validates that no local state files
exist so every run is forced to use the remote backend.

Commands:
  plan       Run "terraform plan" after synchronising remote state.
  apply      Run "terraform apply" after synchronising remote state.
  destroy    Run "terraform destroy" after synchronising remote state.
  recreate   Shorthand for "--recreate apply".

Options:
  --recreate   Perform a destroy followed by an apply in one run.
  --allow-multiple
               Disable the singleton guard so multiple MCP hosts can be provisioned.
  --region <name>
               Override the AWS region (defaults to us-east-1).
  --instance-type <type>
               Override the MCP instance type (defaults to t3.micro).
  --subnet-id <subnet>
               Launch the MCP host in a specific subnet (defaults to the default VPC).
  --db-host <host>
               Override the Vertica database host (defaults to 127.0.0.1).
  --db-port <port>
               Override the Vertica database port (defaults to 5433).
  --db-user <user>
               Override the Vertica database user (defaults to mcp_app).
  --db-password <password>
               Override the Vertica database password (defaults to change-me-please).
  --db-name <name>
               Override the Vertica database name (defaults to vertica).
  -h, --help   Show this message and exit.

Additional arguments after "--" are passed directly to Terraform.
Environment:
  AWS_REGION sets the deployment region (defaults to us-east-1). MCP_REGION is
  also honoured.
  MCP_INSTANCE_TYPE, MCP_SUBNET_ID, MCP_DB_HOST, MCP_DB_PORT, MCP_DB_USER,
  MCP_DB_PASSWORD, and MCP_DB_NAME provide environment overrides for the
  corresponding Terraform variables. TF_VAR_* exports remain fully supported
  and take precedence over the built-in defaults.
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
cd "${SCRIPT_DIR}"

log_step() {
  local timestamp
  timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  printf '[terraform][%s] %s\n' "${timestamp}" "$*" >&2
}

A2A_ARTIFACT_PATH=${A2A_ARTIFACT_PATH:-"${REPO_ROOT}/build/mcp-a2a.json"}
CLAUDE_CONFIG_PATH=${CLAUDE_CONFIG_PATH:-"${REPO_ROOT}/build/claude-desktop-config.json"}

if [[ $# -eq 0 ]]; then
  usage
  exit 1
fi

RECREATE_FLAG=false
COMMAND=""
CLI_REGION=""
CLI_INSTANCE_TYPE=""
CLI_SUBNET_ID=""
CLI_DB_HOST=""
CLI_DB_PORT=""
CLI_DB_USER=""
CLI_DB_PASSWORD=""
CLI_DB_NAME=""
CLI_ALLOW_MULTIPLE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --recreate)
      RECREATE_FLAG=true
      shift
      ;;
    --allow-multiple)
      CLI_ALLOW_MULTIPLE="true"
      shift
      ;;
    --region)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --region" >&2
        usage
        exit 1
      fi
      CLI_REGION="$2"
      shift 2
      ;;
    --instance-type)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --instance-type" >&2
        usage
        exit 1
      fi
      CLI_INSTANCE_TYPE="$2"
      shift 2
      ;;
    --subnet-id)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --subnet-id" >&2
        usage
        exit 1
      fi
      CLI_SUBNET_ID="$2"
      shift 2
      ;;
    --db-host)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --db-host" >&2
        usage
        exit 1
      fi
      CLI_DB_HOST="$2"
      shift 2
      ;;
    --db-port)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --db-port" >&2
        usage
        exit 1
      fi
      CLI_DB_PORT="$2"
      shift 2
      ;;
    --db-user)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --db-user" >&2
        usage
        exit 1
      fi
      CLI_DB_USER="$2"
      shift 2
      ;;
    --db-password)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --db-password" >&2
        usage
        exit 1
      fi
      CLI_DB_PASSWORD="$2"
      shift 2
      ;;
    --db-name)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --db-name" >&2
        usage
        exit 1
      fi
      CLI_DB_NAME="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    plan|apply|destroy|recreate)
      COMMAND="$1"
      shift
      break
      ;;
    --)
      echo "Missing command before --" >&2
      usage
      exit 1
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "${COMMAND}" ]]; then
  echo "No command provided" >&2
  usage
  exit 1
fi

resolve_value() {
  local default_value="$1"
  shift
  local resolved="$default_value"
  local candidate
  for candidate in "$@"; do
    if [[ -n "${candidate}" ]]; then
      resolved="${candidate}"
    fi
  done
  printf '%s' "${resolved}"
}

RESOLVED_REGION=$(resolve_value "${DEFAULT_AWS_REGION}" "${TF_VAR_aws_region:-}" "${MCP_REGION:-}" "${AWS_REGION:-}" "${CLI_REGION}")
export AWS_REGION="${RESOLVED_REGION}"
export TF_VAR_aws_region="${RESOLVED_REGION}"

log_step "Command: ${COMMAND}"
log_step "AWS region resolved to ${RESOLVED_REGION}"

RESOLVED_INSTANCE_TYPE=$(resolve_value "${DEFAULT_INSTANCE_TYPE}" "${TF_VAR_mcp_instance_type:-}" "${MCP_INSTANCE_TYPE:-}" "${CLI_INSTANCE_TYPE}")
export TF_VAR_mcp_instance_type="${RESOLVED_INSTANCE_TYPE}"
log_step "EC2 instance type resolved to ${RESOLVED_INSTANCE_TYPE}"

RESOLVED_SUBNET_ID=$(resolve_value "${DEFAULT_SUBNET_ID}" "${TF_VAR_mcp_subnet_id:-}" "${MCP_SUBNET_ID:-}" "${CLI_SUBNET_ID}")
if [[ -z "${RESOLVED_SUBNET_ID}" ]]; then
  unset TF_VAR_mcp_subnet_id
else
  export TF_VAR_mcp_subnet_id="${RESOLVED_SUBNET_ID}"
fi
if [[ -n "${RESOLVED_SUBNET_ID}" ]]; then
  log_step "Deploying into subnet ${RESOLVED_SUBNET_ID}"
else
  log_step "No explicit subnet provided – using default VPC subnet"
fi

RESOLVED_DB_HOST=$(resolve_value "${DEFAULT_DB_HOST}" "${TF_VAR_db_host:-}" "${MCP_DB_HOST:-}" "${CLI_DB_HOST}")
export TF_VAR_db_host="${RESOLVED_DB_HOST}"

RESOLVED_DB_PORT=$(resolve_value "${DEFAULT_DB_PORT}" "${TF_VAR_db_port:-}" "${MCP_DB_PORT:-}" "${CLI_DB_PORT}")
export TF_VAR_db_port="${RESOLVED_DB_PORT}"
log_step "Database target resolved to ${RESOLVED_DB_HOST}:${RESOLVED_DB_PORT}"

RESOLVED_DB_USER=$(resolve_value "${DEFAULT_DB_USER}" "${TF_VAR_db_user:-}" "${MCP_DB_USER:-}" "${CLI_DB_USER}")
export TF_VAR_db_user="${RESOLVED_DB_USER}"

RESOLVED_DB_PASSWORD=$(resolve_value "${DEFAULT_DB_PASSWORD}" "${TF_VAR_db_password:-}" "${MCP_DB_PASSWORD:-}" "${CLI_DB_PASSWORD}")
export TF_VAR_db_password="${RESOLVED_DB_PASSWORD}"

RESOLVED_DB_NAME=$(resolve_value "${DEFAULT_DB_NAME}" "${TF_VAR_db_name:-}" "${MCP_DB_NAME:-}" "${CLI_DB_NAME}")
export TF_VAR_db_name="${RESOLVED_DB_NAME}"

RESOLVED_ALLOW_MULTIPLE=$(resolve_value "false" "${TF_VAR_allow_multiple_mcp_instances:-}" "${CLI_ALLOW_MULTIPLE}")
if [[ -z "${RESOLVED_ALLOW_MULTIPLE}" ]]; then
  unset TF_VAR_allow_multiple_mcp_instances
else
  export TF_VAR_allow_multiple_mcp_instances="${RESOLVED_ALLOW_MULTIPLE}"
fi
if [[ "${RESOLVED_ALLOW_MULTIPLE}" == "true" ]]; then
  log_step "Singleton guard disabled – allowing multiple MCP instances"
else
  log_step "Singleton guard enabled"
fi

EXTRA_ARGS=()
EXPORTED_TF_VARS=()
if [[ $# -gt 0 ]]; then
  if [[ "$1" == "--" ]]; then
    shift
  fi
  EXTRA_ARGS=("$@")
fi

if [[ "${COMMAND}" == "recreate" ]]; then
  RECREATE_FLAG=true
  COMMAND="apply"
fi

if [[ -z "${AWS_REGION:-}" ]]; then
  echo "AWS_REGION must be set to bootstrap the Terraform backend." >&2
  exit 1
fi

bootstrap_backend() {
  log_step "Ensuring remote backend prerequisites"
  "${SCRIPT_DIR}/backend-bootstrap.sh"
}

terraform_init() {
  log_step "Initializing Terraform working directory"
  terraform init -input=false
}

import_existing_resources() {
  log_step "Reconciling existing AWS artefacts into Terraform state"
  "${SCRIPT_DIR}/import-if-exists.sh"
}

ensure_ready() {
  log_step "Preparing Terraform environment"
  ensure_no_local_state
  bootstrap_backend
  terraform_init
  verify_remote_backend
  import_existing_resources
}

ensure_no_local_state() {
  log_step "Checking for disallowed local Terraform state files"
  local disallowed_state_files=(
    "${SCRIPT_DIR}/terraform.tfstate"
    "${SCRIPT_DIR}/terraform.tfstate.backup"
  )

  for state_file in "${disallowed_state_files[@]}"; do
    if [[ -f "${state_file}" ]]; then
      echo "Local Terraform state detected at ${state_file}. Remote state is required for safe multi-user operation." >&2
      echo "Please migrate or remove the local state file before retrying." >&2
      exit 1
    fi
  done
}

verify_remote_backend() {
  log_step "Verifying remote backend metadata"
  local backend_state_file="${SCRIPT_DIR}/.terraform/terraform.tfstate"

  if [[ ! -f "${backend_state_file}" ]]; then
    echo "Terraform backend state metadata not found at ${backend_state_file}." >&2
    echo "Ensure \"terraform init\" completed successfully." >&2
    exit 1
  fi

  python - "${backend_state_file}" <<'PY'
import json
import pathlib
import sys

backend_file = pathlib.Path(sys.argv[1])
try:
    backend_state = json.loads(backend_file.read_text())
except Exception as exc:  # pragma: no cover - defensive guard for malformed files
    print(
        f"Unable to parse Terraform backend metadata from {backend_file}: {exc}",
        file=sys.stderr,
    )
    sys.exit(1)

backend = backend_state.get("backend") or {}
backend_type = backend.get("type")
if backend_type != "s3":
    print(
        "Terraform backend must be configured for the S3 remote backend.",
        file=sys.stderr,
    )
    sys.exit(1)

config = backend.get("config") or {}
if not config.get("bucket"):
    print("Terraform backend is missing the S3 bucket configuration.", file=sys.stderr)
    sys.exit(1)

if not config.get("dynamodb_table"):
    print(
        "Terraform backend must configure a DynamoDB table for state locking.",
        file=sys.stderr,
    )
    sys.exit(1)
PY
}

write_a2a_artifact() {
  local tmp_file
  tmp_file=$(mktemp)

  if ! terraform output -json >"${tmp_file}" 2>/dev/null; then
    rm -f "${tmp_file}"
    return
  fi

  log_step "Exporting MCP automation artefacts"
  python - "${tmp_file}" "${A2A_ARTIFACT_PATH}" "${CLAUDE_CONFIG_PATH}" "${SCRIPT_DIR}" <<'PY'
import json
import pathlib
import sys

outputs_path = pathlib.Path(sys.argv[1])
artifact_path = pathlib.Path(sys.argv[2])
claude_path = pathlib.Path(sys.argv[3])
script_dir = pathlib.Path(sys.argv[4])
sys.path.insert(0, str(script_dir))

try:
    outputs = json.loads(outputs_path.read_text())
except json.JSONDecodeError:
    sys.exit(0)

metadata = outputs.get("mcp_a2a_metadata")
if not isinstance(metadata, dict):
    sys.exit(0)

value = metadata.get("value")
if value in (None, ""):
    sys.exit(0)

artifact_path.parent.mkdir(parents=True, exist_ok=True)
artifact_path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
print(f"Wrote MCP A2A artifact to {artifact_path}", file=sys.stderr)

try:
    from claude_config import ClaudeConfigError, write_claude_config
except Exception:  # pragma: no cover - defensive guard for missing helper
    sys.exit(0)

try:
    write_claude_config(value, claude_path)
except ClaudeConfigError as exc:
    print(f"Skipping Claude Desktop config generation: {exc}", file=sys.stderr)
else:
    print(f"Wrote Claude Desktop config to {claude_path}", file=sys.stderr)
PY

  rm -f "${tmp_file}"
}

update_readme_from_outputs() {
  local tmp_file
  tmp_file=$(mktemp)

  if ! terraform output -json >"${tmp_file}" 2>/dev/null; then
    rm -f "${tmp_file}"
    return
  fi

  log_step "Refreshing README endpoints from Terraform outputs"
  if ! python3 "${SCRIPT_DIR}/update_readme.py" --readme "${REPO_ROOT}/README.md" --outputs-json "${tmp_file}"; then
    echo "Warning: failed to update README endpoints from Terraform outputs." >&2
  fi

  rm -f "${tmp_file}"
}

reset_readme_endpoints() {
  log_step "Resetting README endpoints"
  if ! python3 "${SCRIPT_DIR}/update_readme.py" --readme "${REPO_ROOT}/README.md"; then
    echo "Warning: failed to reset README endpoints." >&2
  fi
}

export_tf_vars_from_extra_args() {
  EXPORTED_TF_VARS=()

  for arg in "${EXTRA_ARGS[@]}"; do
    case "$arg" in
      -var=*)
        local assignment name value env_name
        assignment=${arg#-var=}

        if [[ "$assignment" != *=* ]]; then
          continue
        fi

        name=${assignment%%=*}
        value=${assignment#*=}

        if [[ -z "$name" ]]; then
          continue
        fi

        env_name="TF_VAR_${name}"
        export "${env_name}=${value}"
        EXPORTED_TF_VARS+=("${env_name}")
        log_step "Propagated ${env_name} from CLI override"
        ;;
    esac
  done
}

cleanup_exported_tf_vars() {
  local count=${#EXPORTED_TF_VARS[@]}
  for env_name in "${EXPORTED_TF_VARS[@]}"; do
    unset "${env_name}"
  done
  EXPORTED_TF_VARS=()
  if [[ ${count} -gt 0 ]]; then
    log_step "Cleared ${count} temporary TF_VAR exports"
  fi
}

cleanup_orphaned_resources() {
  log_step "Running orphaned resource cleanup"
  if ! "${SCRIPT_DIR}/cleanup-orphans.sh"; then
    echo "Warning: failed to clean up orphaned resources." >&2
  fi
}

run_command() {
  case "$COMMAND" in
    plan)
      export_tf_vars_from_extra_args
      ensure_ready
      log_step "Validating Terraform configuration"
      terraform validate
      cleanup_exported_tf_vars
      log_step "Running terraform plan"
      terraform plan "${EXTRA_ARGS[@]}"
      ;;
    apply)
      export_tf_vars_from_extra_args
      ensure_ready
      if [[ "${RECREATE_FLAG}" == "true" ]]; then
        log_step "Recreate flag enabled – destroying existing infrastructure first"
        destroy_exit=0
        if ! terraform destroy -auto-approve "${EXTRA_ARGS[@]}"; then
          destroy_exit=$?
        fi
        cleanup_orphaned_resources
        if [[ "${destroy_exit}" -ne 0 ]]; then
          cleanup_exported_tf_vars
          exit "${destroy_exit}"
        fi
        log_step "Recreate destroy completed – applying fresh infrastructure"
        terraform apply -auto-approve "${EXTRA_ARGS[@]}"
      else
        log_step "Running terraform apply"
        terraform apply "${EXTRA_ARGS[@]}"
      fi
      cleanup_exported_tf_vars
      write_a2a_artifact
      update_readme_from_outputs
      ;;
    destroy)
      export_tf_vars_from_extra_args
      ensure_ready
      log_step "Running terraform destroy"
      destroy_exit=0
      if ! terraform destroy "${EXTRA_ARGS[@]}"; then
        destroy_exit=$?
      fi
      cleanup_exported_tf_vars
      cleanup_orphaned_resources
      if [[ "${destroy_exit}" -ne 0 ]]; then
        exit "${destroy_exit}"
      fi
      reset_readme_endpoints
      ;;
    *)
      echo "Unsupported command: ${COMMAND}" >&2
      exit 1
      ;;
  esac
}

run_command
