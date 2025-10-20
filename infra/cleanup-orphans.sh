#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "${SCRIPT_DIR}"

DOC_PREFIX="vertica-mcp-run"
ASSOCIATION_NAME="vertica-mcp-singleton"
A2A_PARAM_NAME="${A2A_SSM_PARAMETER_NAME:-${TF_VAR_a2a_ssm_parameter_name:-/vertica/mcp/a2a}}"
SINGLETON_PARAM_NAME="/vertica/mcp/singleton-lock"
ECR_REPOSITORY="vertica-mcp"

AWS_CLI_REGION_ARGS=()
if [[ -n "${AWS_REGION:-}" ]]; then
  AWS_CLI_REGION_ARGS+=("--region" "${AWS_REGION}")
elif [[ -n "${MCP_REGION:-}" ]]; then
  AWS_CLI_REGION_ARGS+=("--region" "${MCP_REGION}")
fi

log() {
  echo "[cleanup] $*" >&2
}

warn() {
  echo "[cleanup] Warning: $*" >&2
}

delete_ssm_association() {
  local association_id
  if ! association_id=$(aws ssm list-associations \
    --association-filter-list key=AssociationName,value="${ASSOCIATION_NAME}" \
    --query 'Associations[0].AssociationId' \
    --output text "${AWS_CLI_REGION_ARGS[@]}" 2>/dev/null || true); then
    warn "Failed to query SSM associations"
    return
  fi

  if [[ -z "${association_id}" || "${association_id}" == "None" ]]; then
    return
  fi

  log "Deleting orphaned SSM association ${association_id}"
  if ! aws ssm delete-association --association-id "${association_id}" "${AWS_CLI_REGION_ARGS[@]}" >/dev/null 2>&1; then
    warn "Unable to delete SSM association ${association_id}"
  fi
}

delete_ssm_documents() {
  local documents_raw
  if ! documents_raw=$(aws ssm list-documents \
    --filters Key=Owner,Values=Self \
    --query "DocumentIdentifiers[?starts_with(Name, '${DOC_PREFIX}')].Name" \
    --output text "${AWS_CLI_REGION_ARGS[@]}" 2>/dev/null || true); then
    warn "Failed to query SSM documents"
    return
  fi

  if [[ -z "${documents_raw}" || "${documents_raw}" == "None" ]]; then
    return
  fi

  local doc
  for doc in ${documents_raw}; do
    log "Deleting orphaned SSM document ${doc}"
    if ! aws ssm delete-document --name "${doc}" --force "${AWS_CLI_REGION_ARGS[@]}" >/dev/null 2>&1; then
      warn "Unable to delete SSM document ${doc}"
    fi
  done
}

delete_parameter() {
  local name="$1"
  if [[ -z "${name}" ]]; then
    return
  fi

  if ! aws ssm get-parameter --name "${name}" --with-decryption "${AWS_CLI_REGION_ARGS[@]}" >/dev/null 2>&1; then
    return
  fi

  log "Deleting orphaned SSM parameter ${name}"
  if ! aws ssm delete-parameter --name "${name}" "${AWS_CLI_REGION_ARGS[@]}" >/dev/null 2>&1; then
    warn "Unable to delete SSM parameter ${name}"
  fi
}

delete_ecr_repository() {
  if ! aws ecr describe-repositories --repository-names "${ECR_REPOSITORY}" "${AWS_CLI_REGION_ARGS[@]}" >/dev/null 2>&1; then
    return
  fi

  log "Deleting orphaned ECR repository ${ECR_REPOSITORY}"
  if ! aws ecr delete-repository --repository-name "${ECR_REPOSITORY}" --force "${AWS_CLI_REGION_ARGS[@]}" >/dev/null 2>&1; then
    warn "Unable to delete ECR repository ${ECR_REPOSITORY}"
  fi
}

main() {
  delete_ssm_association
  delete_ssm_documents

  delete_parameter "${A2A_PARAM_NAME}"

  delete_parameter "${SINGLETON_PARAM_NAME}"

  delete_ecr_repository
}

main "$@"
