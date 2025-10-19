#!/usr/bin/env bash
set -euo pipefail
exists(){ terraform state list | grep -q "$1"; }
DOC="vertica-mcp-run"
if aws ssm describe-document --name "$DOC" >/dev/null 2>&1; then
if ! exists aws_ssm_document.mcp_run; then terraform import aws_ssm_document.mcp_run "$DOC" || true; fi
fi
ASSOC_ID=$(aws ssm list-associations --association-filter-list key=Name,value="$DOC" --query 'Associations[0].AssociationId' --output text 2>/dev/null || true)
if [ "$ASSOC_ID" != "None" ] && [ -n "$ASSOC_ID" ]; then
if ! exists aws_ssm_association.mcp_assoc; then terraform import aws_ssm_association.mcp_assoc "$ASSOC_ID" || true; fi
fi
