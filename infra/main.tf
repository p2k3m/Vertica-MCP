terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.60"
    }

    random = {
      source  = "hashicorp/random"
      version = ">= 3.6"
    }
  }

}

provider "aws" {
  region = var.aws_region
}

data "external" "existing_ecr_repository" {
  program = ["python3", "${path.module}/check-ecr.py"]

  query = {
    name   = "vertica-mcp"
    region = var.aws_region
  }
}

locals {
  ecr_lookup_result     = data.external.existing_ecr_repository.result
  ecr_repository_exists = try(tobool(local.ecr_lookup_result.exists), false)
  ecr_registry_id       = local.ecr_repository_exists ? local.ecr_lookup_result.registry_id : var.account_id
  ecr_repository_url    = local.ecr_repository_exists ? local.ecr_lookup_result.repository_url : one(aws_ecr_repository.vertica_mcp[*].repository_url)
}

resource "aws_ecr_repository" "vertica_mcp" {
  count                = local.ecr_repository_exists ? 0 : 1
  name                 = "vertica-mcp"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

locals {
  container_repository      = "${local.ecr_registry_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
  container_image_name      = local.ecr_repository_url
  container_image_tag       = trimspace(var.image_tag) == "" ? "latest" : trimspace(var.image_tag)
  container_image           = "${local.container_image_name}:${local.container_image_tag}"
  mcp_instance_name         = "MCP-Vertica"
  mcp_tags_base             = {
    Name    = local.mcp_instance_name
    Service = "Vertica-MCP"
  }
  http_token_trimmed        = trimspace(var.http_token)
  db_env_snippet            = {
    DB_HOST     = var.db_host
    DB_PORT     = tostring(var.db_port)
    DB_USER     = var.db_user
    DB_PASSWORD = var.db_password
    DB_NAME     = var.db_name
  }
  http_env_snippet          = local.http_token_trimmed == "" ? {} : { MCP_HTTP_TOKEN = local.http_token_trimmed }
  mcp_env_map               = merge(local.db_env_snippet, local.http_env_snippet, var.mcp_environment)
  mcp_env_reserved_keys     = ["DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME", "MCP_HTTP_TOKEN"]
  mcp_env_file_path         = "/etc/mcp.env"
  mcp_env_file_contents     = join(
    "\n",
    concat(
      compact([
        for key in local.mcp_env_reserved_keys : try("${key}=${local.mcp_env_map[key]}", null)
      ]),
      [
        for key in sort(tolist(setsubtract(toset(keys(local.mcp_env_map)), toset(local.mcp_env_reserved_keys)))) :
        "${key}=${local.mcp_env_map[key]}"
      ],
    ),
  )
  mcp_env_file_base64       = base64encode(local.mcp_env_file_contents)
  mcp_bootstrap_user_data   = <<-USERDATA
    #!/bin/bash
    set -euxo pipefail

    echo "[mcp] Bootstrapping MCP host" | tee /var/log/mcp-bootstrap.log
    dnf update -y
    dnf install -y docker python3 python3-pip awscli jq
    python3 -m pip install --upgrade pip
    systemctl enable --now docker
    usermod -aG docker ec2-user || true

    echo '${local.mcp_env_file_base64}' | base64 -d >${local.mcp_env_file_path}
    chmod 600 ${local.mcp_env_file_path}
    chown root:root ${local.mcp_env_file_path}

    printf 'Bootstrap completed at %s\n' "$(date --iso-8601=seconds)" >>/var/log/mcp-bootstrap.log
  USERDATA
  service_unit_contents     = <<-UNIT
    [Unit]
    Description=Vertica MCP service
    After=docker.service
    Requires=docker.service

    [Service]
    Type=simple
    EnvironmentFile=${local.mcp_env_file_path}
    Restart=always
    RestartSec=5
    ExecStartPre=/usr/bin/aws ecr get-login-password --region ${var.aws_region} | /usr/bin/docker login --username AWS --password-stdin ${local.container_repository}
    ExecStartPre=/bin/grep -Eq '^DB_HOST=.+' ${local.mcp_env_file_path}
    ExecStartPre=/bin/grep -Eq '^DB_PORT=.+' ${local.mcp_env_file_path}
    ExecStartPre=/bin/grep -Eq '^DB_USER=.+' ${local.mcp_env_file_path}
    ExecStartPre=/bin/grep -Eq '^DB_PASSWORD=.+' ${local.mcp_env_file_path}
    ExecStartPre=/bin/grep -Eq '^DB_NAME=.+' ${local.mcp_env_file_path}
    ExecStartPre=/usr/bin/docker pull ${local.container_image}
    ExecStartPre=/usr/bin/docker rm -f mcp || true
    ExecStart=/usr/bin/docker run --name mcp -p 8000:8000 --restart unless-stopped --env-file ${local.mcp_env_file_path} ${local.container_image} python -m mcp_vertica.server
    ExecStop=/usr/bin/docker stop mcp
    StandardOutput=journal
    StandardError=journal

    [Install]
    WantedBy=multi-user.target
  UNIT
  service_unit_command      = join("\n", [
    "cat <<UNIT >/etc/systemd/system/mcp.service",
    trimspace(local.service_unit_contents),
    "UNIT",
  ])
  use_cloudfront_input      = try(trimspace(tostring(var.use_cloudfront)), "")
  use_cloudfront            = local.use_cloudfront_input != "" && contains(["1", "true", "yes", "y"], lower(local.use_cloudfront_input))
}

locals {
  requested_subnet_id = trimspace(var.mcp_subnet_id == null ? "" : var.mcp_subnet_id)
}

data "aws_subnet" "requested" {
  count = local.requested_subnet_id != "" ? 1 : 0
  id    = local.requested_subnet_id
}

data "aws_vpc" "default" {
  count   = local.requested_subnet_id == "" ? 1 : 0
  default = true
}

data "aws_subnets" "default" {
  count = local.requested_subnet_id == "" ? 1 : 0

  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default[0].id]
  }
}

locals {
  mcp_subnet_id = local.requested_subnet_id != "" ? local.requested_subnet_id : data.aws_subnets.default[0].ids[0]
}

data "aws_subnet" "selected" {
  id = local.mcp_subnet_id
}

locals {
  mcp_vpc_id = data.aws_subnet.selected.vpc_id
}

resource "aws_security_group" "mcp" {
  name        = "mcp-vertica"
  description = "Security group for the Vertica MCP service"
  vpc_id      = local.mcp_vpc_id

  ingress {
    description = "Allow MCP HTTP traffic"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  ingress {
    description = "Allow Vertica database traffic"
    from_port   = 5433
    to_port     = 5433
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  ingress {
    description = "Allow ICMP for diagnostics"
    from_port   = -1
    to_port     = -1
    protocol    = "icmp"
    cidr_blocks = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  egress {
    description = "Allow MCP to reach Vertica database hosts"
    from_port   = 5433
    to_port     = 5433
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  egress {
    description = "Allow MCP service HTTP egress"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  egress {
    description = "Allow ICMP diagnostics from MCP"
    from_port   = -1
    to_port     = -1
    protocol    = "icmp"
    cidr_blocks = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  egress {
    description = "Allow all other outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  tags = merge(local.mcp_tags_base, {
    Environment = "production"
  })
}

resource "aws_security_group_rule" "allow_mcp_to_vertica" {
  count                    = var.vertica_security_group_id == null ? 0 : 1
  type                     = "ingress"
  from_port                = 5433
  to_port                  = 5433
  protocol                 = "tcp"
  security_group_id        = var.vertica_security_group_id
  source_security_group_id = aws_security_group.mcp.id
  description              = "Allow MCP server to reach Vertica database"
}

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_iam_role" "mcp" {
  name = "mcp-vertica-instance-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(local.mcp_tags_base, {
    Name = "mcp-vertica-instance-role"
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.mcp.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "ecr" {
  role       = aws_iam_role.mcp.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_instance_profile" "mcp" {
  name = "mcp-vertica-instance-profile"
  role = aws_iam_role.mcp.name
}

resource "aws_instance" "mcp" {
  ami                    = data.aws_ssm_parameter.al2023.value
  instance_type          = var.mcp_instance_type
  subnet_id              = local.mcp_subnet_id
  associate_public_ip_address = true
  iam_instance_profile   = aws_iam_instance_profile.mcp.name
  user_data              = local.mcp_bootstrap_user_data
  user_data_replace_on_change = false

  vpc_security_group_ids = concat([aws_security_group.mcp.id], var.mcp_additional_security_group_ids)

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 16
    encrypted   = true
  }

  tags = merge(local.mcp_tags_base, {
    Environment = "production"
  })

  depends_on = [aws_security_group_rule.allow_mcp_to_vertica]
}

locals {
  mcp_public_ip      = try(aws_instance.mcp.public_ip, "")
  mcp_http_base      = local.mcp_public_ip == "" ? "" : "http://${local.mcp_public_ip}:8000"
  mcp_http_endpoint  = local.mcp_http_base == "" ? null : "${local.mcp_http_base}/"
  mcp_http_healthz   = local.mcp_http_base == "" ? null : "${local.mcp_http_base}/healthz"
  mcp_http_sse       = local.mcp_http_base == "" ? null : "${local.mcp_http_base}/sse"
  mcp_https_endpoint = length(aws_cloudfront_distribution.mcp) > 0 ? "https://${aws_cloudfront_distribution.mcp[0].domain_name}/" : null
  mcp_https_sse      = length(aws_cloudfront_distribution.mcp) > 0 ? "https://${aws_cloudfront_distribution.mcp[0].domain_name}/sse" : null
  mcp_auth_header    = local.http_token_trimmed == "" ? null : {
    header = "Authorization"
    value  = "Bearer ${local.http_token_trimmed}"
    token  = local.http_token_trimmed
  }
  db_snippet = {
    host           = var.db_host
    port           = var.db_port
    user           = var.db_user
    password       = var.db_password
    name           = var.db_name
    jdbc_url       = format("jdbc:vertica://%s:%d/%s", var.db_host, var.db_port, var.db_name)
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
      http      = local.mcp_http_endpoint
      healthz   = local.mcp_http_healthz
      sse       = local.mcp_http_sse
      https     = local.mcp_https_endpoint
      https_sse = local.mcp_https_sse
    }
    auth     = local.mcp_auth_header
    database = local.db_snippet
  }
  a2a_parameter_name = trimspace(var.a2a_ssm_parameter_name)
}

resource "random_id" "ssm_document_suffix" {
  byte_length = 4
}

resource "aws_ssm_document" "mcp_run" {
  name            = "vertica-mcp-run-${random_id.ssm_document_suffix.hex}"
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
            "command -v docker >/dev/null 2>&1 || { echo 'docker is required' >&2; exit 1; }",
            "command -v aws >/dev/null 2>&1 || { echo 'aws CLI is required' >&2; exit 1; }",
            "echo '${local.mcp_env_file_base64}' | base64 -d >${local.mcp_env_file_path}",
            "chmod 600 ${local.mcp_env_file_path}",
            "chown root:root ${local.mcp_env_file_path}",
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
  name             = aws_ssm_document.mcp_run.name
  association_name = "vertica-mcp-singleton"

  targets {
    key    = "InstanceIds"
    values = [aws_instance.mcp.id]
  }

  depends_on = [
    aws_ssm_document.mcp_run,
    aws_instance.mcp,
  ]
}

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

resource "aws_cloudfront_origin_request_policy" "auth_header" {
  count = local.use_cloudfront ? 1 : 0

  name = "mcp-forward-authorization"

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

resource "aws_cloudfront_distribution" "mcp" {
  count = local.use_cloudfront ? 1 : 0

  enabled = true
  comment = "MCP over CloudFront"

  origin {
    domain_name = aws_instance.mcp.public_dns
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
    origin_request_policy_id = aws_cloudfront_origin_request_policy.auth_header[0].id
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

output "mcp_instance_id" {
  value = aws_instance.mcp.id
}

output "mcp_public_ip" {
  value = local.mcp_public_ip
}

output "mcp_endpoint" {
  value = try("http://${aws_instance.mcp.public_ip}:8000/", "")
}

output "mcp_health" {
  value = try("http://${aws_instance.mcp.public_ip}:8000/healthz", "")
}

output "mcp_sse" {
  value = try("http://${aws_instance.mcp.public_ip}:8000/sse", "")
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
  count       = local.a2a_parameter_name == "" ? 0 : 1
  name        = local.a2a_parameter_name
  description = "Vertica MCP machine-readable endpoints"
  type        = "SecureString"
  overwrite   = true
  value       = jsonencode(local.a2a_payload)
  depends_on  = [aws_ssm_document.mcp_run]
}
