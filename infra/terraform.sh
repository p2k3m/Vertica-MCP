#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: terraform.sh [--recreate] <plan|apply|destroy|recreate> [-- <terraform args>]

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
  -h, --help   Show this message and exit.

Additional arguments after "--" are passed directly to Terraform.
Environment:
  AWS_REGION must be set so the backend bootstrapper knows where to operate.
USAGE
}

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
cd "${SCRIPT_DIR}"

A2A_ARTIFACT_PATH=${A2A_ARTIFACT_PATH:-"${REPO_ROOT}/build/mcp-a2a.json"}

if [[ $# -eq 0 ]]; then
  usage
  exit 1
fi

RECREATE_FLAG=false
COMMAND=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --recreate)
      RECREATE_FLAG=true
      shift
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
  echo "Running backend bootstrapper..." >&2
  "${SCRIPT_DIR}/backend-bootstrap.sh"
}

terraform_init() {
  echo "Initializing Terraform working directory..." >&2
  terraform init -input=false
}

import_existing_resources() {
  "${SCRIPT_DIR}/import-if-exists.sh"
}

ensure_ready() {
  ensure_no_local_state
  bootstrap_backend
  terraform_init
  verify_remote_backend
  import_existing_resources
}

ensure_no_local_state() {
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

  python - "${tmp_file}" "${A2A_ARTIFACT_PATH}" <<'PY'
import json
import pathlib
import sys

outputs_path = pathlib.Path(sys.argv[1])
artifact_path = pathlib.Path(sys.argv[2])

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
PY

  rm -f "${tmp_file}"
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
        ;;
    esac
  done
}

cleanup_exported_tf_vars() {
  for env_name in "${EXPORTED_TF_VARS[@]}"; do
    unset "${env_name}"
  done
  EXPORTED_TF_VARS=()
}

run_command() {
  case "$COMMAND" in
    plan)
      export_tf_vars_from_extra_args
      ensure_ready
      terraform validate
      cleanup_exported_tf_vars
      terraform plan "${EXTRA_ARGS[@]}"
      ;;
    apply)
      export_tf_vars_from_extra_args
      ensure_ready
      if [[ "${RECREATE_FLAG}" == "true" ]]; then
        terraform destroy -auto-approve "${EXTRA_ARGS[@]}"
        terraform apply -auto-approve "${EXTRA_ARGS[@]}"
      else
        terraform apply "${EXTRA_ARGS[@]}"
      fi
      cleanup_exported_tf_vars
      write_a2a_artifact
      ;;
    destroy)
      export_tf_vars_from_extra_args
      ensure_ready
      terraform destroy "${EXTRA_ARGS[@]}"
      cleanup_exported_tf_vars
      ;;
    *)
      echo "Unsupported command: ${COMMAND}" >&2
      exit 1
      ;;
  esac
}

run_command
