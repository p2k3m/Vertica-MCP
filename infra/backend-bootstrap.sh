#!/usr/bin/env bash
set -euo pipefail
: "${AWS_REGION:?Missing AWS_REGION}" || exit 1
BUCKET="tfstate-${GITHUB_REPOSITORY//\//-}-${AWS_REGION}"
TABLE="tf-locks"

# Ensure the S3 bucket exists before enabling versioning. us-east-1 requires a
# special create-bucket invocation with no LocationConstraint; other regions
# need the configuration flag. If the bucket already exists, we simply reuse it.
if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  if [ "$AWS_REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET"
  else
    aws s3api create-bucket --bucket "$BUCKET" \
      --create-bucket-configuration LocationConstraint=${AWS_REGION}
  fi
fi

aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
aws dynamodb create-table --table-name "$TABLE" \
--attribute-definitions AttributeName=LockID,AttributeType=S \
--key-schema AttributeName=LockID,KeyType=HASH \
--billing-mode PAY_PER_REQUEST 2>/dev/null || true
cat > backend.tf <<EOF
terraform { backend "s3" { region = "${AWS_REGION}" bucket = "${BUCKET}" key = "state/terraform.tfstate" dynamodb_table = "${TABLE}" encrypt = true } }
EOF
