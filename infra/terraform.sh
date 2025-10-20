#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: terraform.sh [--recreate] <plan|apply|destroy|recreate> [-- <terraform args>]

Ensures the Terraform backend uses S3 with DynamoDB locking, imports
pre-existing SSM artefacts into state, and then executes the requested
Terraform command.

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
cd "${SCRIPT_DIR}"

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
  "${SCRIPT_DIR}/backend-bootstrap.sh" >/dev/null
}

terraform_init() {
  terraform init -input=false >/dev/null
}

import_existing_resources() {
  "${SCRIPT_DIR}/import-if-exists.sh"
}

ensure_ready() {
  bootstrap_backend
  terraform_init
  import_existing_resources
}

run_command() {
  case "$COMMAND" in
    plan)
      ensure_ready
      terraform plan "${EXTRA_ARGS[@]}"
      ;;
    apply)
      ensure_ready
      if [[ "${RECREATE_FLAG}" == "true" ]]; then
        terraform destroy -auto-approve "${EXTRA_ARGS[@]}"
        terraform apply -auto-approve "${EXTRA_ARGS[@]}"
      else
        terraform apply "${EXTRA_ARGS[@]}"
      fi
      ;;
    destroy)
      ensure_ready
      terraform destroy "${EXTRA_ARGS[@]}"
      ;;
    *)
      echo "Unsupported command: ${COMMAND}" >&2
      exit 1
      ;;
  esac
}

run_command
