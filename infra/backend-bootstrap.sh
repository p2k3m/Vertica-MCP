#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${AWS_REGION:-}" ]]; then
  echo "AWS_REGION must be set" >&2
  exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BACKEND_FILE="${SCRIPT_DIR}/backend.tf"

# Build a deterministic bucket name using the repository identifier when available.
REPO_SLUG=${GITHUB_REPOSITORY:-$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")}
REPO_SLUG=${REPO_SLUG//\//-}
STATE_BUCKET="tfstate-${REPO_SLUG}-${AWS_REGION}"
LOCK_TABLE="tf-locks"

ensure_bucket() {
  if aws s3api head-bucket --bucket "${STATE_BUCKET}" 2>/dev/null; then
    return
  fi

  if [[ "${AWS_REGION}" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "${STATE_BUCKET}" 1>/dev/null
  else
    aws s3api create-bucket --bucket "${STATE_BUCKET}" \
      --create-bucket-configuration LocationConstraint="${AWS_REGION}" 1>/dev/null
  fi
}

ensure_bucket_versioning() {
  local status
  status=$(aws s3api get-bucket-versioning --bucket "${STATE_BUCKET}" --query 'Status' --output text 2>/dev/null || true)
  if [[ "${status}" != "Enabled" ]]; then
    aws s3api put-bucket-versioning \
      --bucket "${STATE_BUCKET}" \
      --versioning-configuration Status=Enabled 1>/dev/null
  fi
}

ensure_bucket_encryption() {
  if ! aws s3api get-bucket-encryption --bucket "${STATE_BUCKET}" 1>/dev/null 2>&1; then
    aws s3api put-bucket-encryption \
      --bucket "${STATE_BUCKET}" \
      --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' 1>/dev/null
  fi
}

ensure_lock_table() {
  if aws dynamodb describe-table --table-name "${LOCK_TABLE}" 1>/dev/null 2>&1; then
    return
  fi

  aws dynamodb create-table \
    --table-name "${LOCK_TABLE}" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST 1>/dev/null
  aws dynamodb wait table-exists --table-name "${LOCK_TABLE}"
}

write_backend_file() {
  cat >"${BACKEND_FILE}" <<EOF_BACKEND
terraform {
  backend "s3" {
    bucket         = "${STATE_BUCKET}"
    key            = "state/terraform.tfstate"
    region         = "${AWS_REGION}"
    dynamodb_table = "${LOCK_TABLE}"
    encrypt        = true
  }
}
EOF_BACKEND
}

ensure_bucket
ensure_bucket_versioning
ensure_bucket_encryption
ensure_lock_table
write_backend_file

echo "Terraform backend configuration written to ${BACKEND_FILE}" >&2
