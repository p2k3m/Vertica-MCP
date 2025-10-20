#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "${SCRIPT_DIR}"

DOC_NAME="vertica-mcp-run"
ASSOCIATION_NAME="vertica-mcp-singleton"

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

import_document_if_missing
import_association_if_missing
