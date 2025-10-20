terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.60"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  container_repository = "${var.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
  container_image_name = "${local.container_repository}/vertica-mcp"
  container_image_tag  = trimspace(var.image_tag) == "" ? "latest" : trimspace(var.image_tag)
  container_image      = "${local.container_image_name}:${local.container_image_tag}"
  service_unit_contents = <<-UNIT
    [Unit]
    Description=Vertica MCP service
    After=docker.service
    Requires=docker.service

    [Service]
    Type=simple
    Environment=DB_HOST=${var.db_host}
    Environment=DB_PORT=${var.db_port}
    Environment=DB_USER=${var.db_user}
    Environment=DB_PASSWORD=${var.db_password}
    Environment=DB_NAME=${var.db_name}
    Environment=MCP_HTTP_TOKEN=${var.http_token}
    Restart=always
    RestartSec=5
    ExecStartPre=/usr/bin/aws ecr get-login-password --region ${var.aws_region} | /usr/bin/docker login --username AWS --password-stdin ${local.container_repository}
    ExecStartPre=/usr/bin/docker pull ${local.container_image}
    ExecStartPre=/usr/bin/docker rm -f mcp || true
    ExecStart=/usr/bin/docker run --name mcp -p 8000:8000 --restart unless-stopped -e DB_HOST -e DB_PORT -e DB_USER -e DB_PASSWORD -e DB_NAME -e MCP_HTTP_TOKEN ${local.container_image}
    ExecStop=/usr/bin/docker stop mcp

    [Install]
    WantedBy=multi-user.target
  UNIT
  service_unit_command = join("\n", [
    "cat <<UNIT >/etc/systemd/system/mcp.service",
    trimspace(local.service_unit_contents),
    "UNIT",
  ])
}

locals {
  use_cloudfront_input = try(trimspace(tostring(var.use_cloudfront)), "")
  use_cloudfront       = local.use_cloudfront_input != "" && contains(["1", "true", "yes", "y"], lower(local.use_cloudfront_input))
}

data "aws_instances" "db_from_name" {
  count = var.db_instance_name == null ? 0 : 1

  filter {
    name   = "tag:Name"
    values = [var.db_instance_name]
  }
}

locals {
  db_instance_id_candidates = compact([
    try(var.db_instance_id, null),
    try(data.aws_instances.db_from_name[0].ids[0], null),
  ])
  db_instance_id = try(local.db_instance_id_candidates[0], null)
  association_targets = local.db_instance_id == null ? [] : [local.db_instance_id]
}

locals {
  mcp_public_ip       = local.db_instance_id == null ? "" : try(data.aws_instance.dbi[0].public_ip, "")
  mcp_http_base       = local.mcp_public_ip == "" ? "" : "http://${local.mcp_public_ip}:8000"
  mcp_http_endpoint   = local.mcp_http_base == "" ? null : "${local.mcp_http_base}/"
  mcp_http_healthz    = local.mcp_http_base == "" ? null : "${local.mcp_http_base}/healthz"
  mcp_http_sse        = local.mcp_http_base == "" ? null : "${local.mcp_http_base}/sse"
  mcp_https_endpoint  = length(aws_cloudfront_distribution.mcp) > 0 ? "https://${aws_cloudfront_distribution.mcp[0].domain_name}/" : null
  mcp_https_sse       = length(aws_cloudfront_distribution.mcp) > 0 ? "https://${aws_cloudfront_distribution.mcp[0].domain_name}/sse" : null
  http_token_trimmed  = trimspace(var.http_token)
  mcp_auth_header     = local.http_token_trimmed == "" ? null : {
    header = "Authorization"
    value  = "Bearer ${local.http_token_trimmed}"
    token  = local.http_token_trimmed
  }
  db_env_snippet = {
    DB_HOST = var.db_host
    DB_PORT = tostring(var.db_port)
    DB_USER = var.db_user
    DB_PASSWORD = var.db_password
    DB_NAME = var.db_name
  }
  db_snippet = {
    host          = var.db_host
    port          = var.db_port
    user          = var.db_user
    password      = var.db_password
    name          = var.db_name
    jdbc_url      = format("jdbc:vertica://%s:%d/%s", var.db_host, var.db_port, var.db_name)
    connection_uri = format(
      "vertica://%s:%s@%s:%d/%s",
      var.db_user,
      var.db_password,
      var.db_host,
      var.db_port,
      var.db_name,
    )
    cli_example = format(
      "vsql -h %s -p %d -U %s -d %s",
      var.db_host,
      var.db_port,
      var.db_user,
      var.db_name,
    )
    environment = local.db_env_snippet
  }
  a2a_payload = {
    endpoints = {
      http       = local.mcp_http_endpoint
      healthz    = local.mcp_http_healthz
      sse        = local.mcp_http_sse
      https      = local.mcp_https_endpoint
      https_sse  = local.mcp_https_sse
    }
    auth      = local.mcp_auth_header
    database  = local.db_snippet
  }
  a2a_parameter_name = trimspace(var.a2a_ssm_parameter_name)
}

resource "terraform_data" "db_instance_id_validation" {
  count = local.db_instance_id == null ? 0 : 1

  lifecycle {
    precondition {
      condition     = local.db_instance_id != null && local.db_instance_id != ""
      error_message = "Set either var.db_instance_id or var.db_instance_name to identify the EC2 instance that runs Vertica MCP."
    }
  }
}

data "aws_instance" "dbi" {
  count       = local.db_instance_id == null ? 0 : 1
  instance_id = local.db_instance_id

  depends_on = [terraform_data.db_instance_id_validation]
}

resource "aws_ssm_document" "mcp_run" {
  name            = "vertica-mcp-run"
  document_type   = "Command"
  document_format = "JSON"

  content = jsonencode({
    schemaVersion = "2.2"
    description   = "Install or update the Vertica MCP service"
    mainSteps = [
      {
        action = "aws:runShellScript"
        name   = "configureService"
        inputs = {
          runCommand = [
            "set -euo pipefail",
            "IMG=${local.container_image}",
            "/usr/bin/aws ecr get-login-password --region ${var.aws_region} | /usr/bin/docker login --username AWS --password-stdin ${local.container_repository}",
            "/usr/bin/docker pull $IMG",
            local.service_unit_command,
            "systemctl daemon-reload",
            "systemctl enable --now mcp.service",
            "systemctl status mcp.service --no-pager || true"
          ]
        }
      }
    ]
  })
}

resource "aws_ssm_association" "mcp_assoc" {
  count            = local.db_instance_id == null ? 0 : 1
  name             = aws_ssm_document.mcp_run.name
  association_name = "vertica-mcp-singleton"

  targets {
    key    = "InstanceIds"
    values = local.association_targets
  }

  depends_on = [
    aws_ssm_document.mcp_run,
    terraform_data.db_instance_id_validation,
  ]
}

# Optional: CloudFront HTTPS in front of EC2:8000
resource "aws_cloudfront_cache_policy" "no_cache" {
  count = local.use_cloudfront ? 1 : 0

  name        = "mcp-no-cache"
  default_ttl = 0
  max_ttl     = 0
  min_ttl     = 0

  parameters_in_cache_key_and_forwarded_to_origin {
    headers_config {
      header_behavior = "whitelist"

      headers {
        items = ["Authorization"]
      }
    }

    cookies_config {
      cookie_behavior = "all"
    }

    query_strings_config {
      query_string_behavior = "all"
    }
  }
}

resource "aws_cloudfront_origin_request_policy" "all_hdrs" {
  count = local.use_cloudfront ? 1 : 0

  name = "mcp-forward-all-headers"

  headers_config {
    header_behavior = "allViewerAndWhitelistCloudFront"
  }

  cookies_config {
    cookie_behavior = "all"
  }

  query_strings_config {
    query_string_behavior = "all"
  }
}

resource "aws_cloudfront_distribution" "mcp" {
  count = local.use_cloudfront && local.db_instance_id != null ? 1 : 0

  enabled = true
  comment = "MCP over CloudFront"

  origin {
    domain_name = data.aws_instance.dbi[0].public_dns
    origin_id   = "ec2-origin"

    custom_origin_config {
      http_port                = 8000
      https_port               = 8000
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_protocol_policy   = "http-only"
      origin_keepalive_timeout = 60
      origin_read_timeout      = 60
    }
  }

  default_cache_behavior {
    target_origin_id         = "ec2-origin"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "POST"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = aws_cloudfront_cache_policy.no_cache[0].id
    origin_request_policy_id = aws_cloudfront_origin_request_policy.all_hdrs[0].id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  price_class = "PriceClass_100"
}

output "db_instance_id" {
  value = local.db_instance_id
}

output "db_public_ip" {
  value = try(data.aws_instance.dbi[0].public_ip, "")
}

output "mcp_endpoint" {
  value = try("http://${data.aws_instance.dbi[0].public_ip}:8000/", "")
}

output "mcp_health" {
  value = try("http://${data.aws_instance.dbi[0].public_ip}:8000/healthz", "")
}

output "mcp_sse" {
  value = try("http://${data.aws_instance.dbi[0].public_ip}:8000/sse", "")
}

output "cloudfront_domain" {
  value = length(aws_cloudfront_distribution.mcp) > 0 ? aws_cloudfront_distribution.mcp[0].domain_name : ""
}

output "mcp_https" {
  value = length(aws_cloudfront_distribution.mcp) > 0 ? "https://${aws_cloudfront_distribution.mcp[0].domain_name}/" : ""
}

output "mcp_a2a_metadata" {
  value     = local.a2a_payload
  sensitive = true
}

resource "aws_ssm_parameter" "mcp_a2a" {
  count      = local.a2a_parameter_name == "" ? 0 : 1
  name       = local.a2a_parameter_name
  description = "Vertica MCP machine-readable endpoints"
  type       = "SecureString"
  overwrite  = true
  value      = jsonencode(local.a2a_payload)
  depends_on = [aws_ssm_document.mcp_run]
}
