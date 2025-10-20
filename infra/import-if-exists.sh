#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "${SCRIPT_DIR}"

DOC_NAME="vertica-mcp-run"
ASSOCIATION_NAME="vertica-mcp-singleton"
A2A_PARAM_NAME=${A2A_SSM_PARAMETER_NAME:-/vertica/mcp/a2a}

has_state_entry() {
  local address="$1"
  terraform state list | grep -Fxq "${address}" || true
}

import_document_if_missing() {
  if aws ssm describe-document --name "${DOC_NAME}" >/dev/null 2>&1; then
    if ! has_state_entry "aws_ssm_document.mcp_run"; then
      echo "Importing existing SSM document ${DOC_NAME} into state" >&2
      terraform import aws_ssm_document.mcp_run "${DOC_NAME}" >/dev/null
    fi
  fi
}

import_association_if_missing() {
  local association_id
  association_id=$(aws ssm list-associations \
    --association-filter-list key=AssociationName,value="${ASSOCIATION_NAME}" \
    --query 'Associations[0].AssociationId' \
    --output text 2>/dev/null || true)

  if [[ -n "${association_id}" && "${association_id}" != "None" ]]; then
    if ! has_state_entry "aws_ssm_association.mcp_assoc"; then
      echo "Importing existing SSM association ${association_id} into state" >&2
      terraform import aws_ssm_association.mcp_assoc "${association_id}" >/dev/null
    fi
  fi
}

import_parameter_if_missing() {
  if [[ -z "${A2A_PARAM_NAME}" ]]; then
    return
  fi

  if aws ssm get-parameter --name "${A2A_PARAM_NAME}" --with-decryption >/dev/null 2>&1; then
    if ! has_state_entry "aws_ssm_parameter.mcp_a2a"; then
      echo "Importing existing SSM parameter ${A2A_PARAM_NAME} into state" >&2
      terraform import aws_ssm_parameter.mcp_a2a "${A2A_PARAM_NAME}" >/dev/null
    fi
  fi
}

import_ecr_repository_if_missing() {
  local repo_name="vertica-mcp"

  if aws ecr describe-repositories --repository-names "${repo_name}" >/dev/null 2>&1; then
    if ! has_state_entry "aws_ecr_repository.vertica_mcp"; then
      echo "Importing existing ECR repository ${repo_name} into state" >&2
      terraform import aws_ecr_repository.vertica_mcp "${repo_name}" >/dev/null
    fi
  fi
}

import_document_if_missing
import_association_if_missing
import_parameter_if_missing
import_ecr_repository_if_missing
