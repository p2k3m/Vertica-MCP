terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.60"
    }
  }

  backend "s3" {}
ExecStartPre=/usr/bin/aws ecr get-login-password --region ${var.aws_region} | /usr/bin/docker login --username AWS --password-stdin ${var.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com
ExecStartPre=/usr/bin/docker pull $IMG
ExecStartPre=/usr/bin/docker rm -f mcp || true
ExecStart=/usr/bin/docker run --name mcp -p 8000:8000 --restart unless-stopped -e DB_HOST -e DB_PORT -e DB_USER -e DB_PASSWORD -e DB_NAME -e MCP_HTTP_TOKEN $IMG


[Install]
WantedBy=multi-user.target
UNIT",
"systemctl daemon-reload",
"systemctl enable --now mcp.service",
"systemctl status mcp.service --no-pager || true"
] }
}]
})
}


resource "aws_ssm_association" "mcp_assoc" {
name = aws_ssm_document.mcp_run.name
association_name = "vertica-mcp-singleton"
targets = [{ key = "InstanceIds", values = [local.db_instance_id] }]
depends_on = [aws_ssm_document.mcp_run]
}


# Optional: CloudFront HTTPS in front of EC2:8000
resource "aws_cloudfront_cache_policy" "no_cache" {
count = var.use_cloudfront ? 1 : 0
name = "mcp-no-cache"
default_ttl = 0
max_ttl = 0
min_ttl = 0
parameters_in_cache_key_and_forwarded_to_origin {
headers_config { header_behavior = "whitelist" headers { items = ["Authorization"] } }
cookies_config { cookie_behavior = "all" }
query_strings_config { query_string_behavior = "all" }
}
}


resource "aws_cloudfront_origin_request_policy" "all_hdrs" {
count = var.use_cloudfront ? 1 : 0
name = "mcp-forward-all-headers"
headers_config { header_behavior = "allViewerAndWhitelistCloudFront" }
cookies_config { cookie_behavior = "all" }
query_strings_config { query_string_behavior = "all" }
}


resource "aws_cloudfront_distribution" "mcp" {
count = var.use_cloudfront ? 1 : 0
enabled = true
comment = "MCP over CloudFront"
origin {
domain_name = data.aws_instance.dbi.public_dns
origin_id = "ec2-origin"
custom_origin_config {
http_port = 8000
https_port = 8000
origin_protocol_policy = "http-only"
origin_keepalive_timeout = 60
origin_read_timeout = 60
}
}
default_cache_behavior {
target_origin_id = "ec2-origin"
viewer_protocol_policy = "redirect-to-https"
allowed_methods = ["GET","HEAD","OPTIONS","POST"]
cached_methods = ["GET","HEAD"]
cache_policy_id = aws_cloudfront_cache_policy.no_cache[0].id
origin_request_policy_id = aws_cloudfront_origin_request_policy.all_hdrs[0].id
}
restrictions { geo_restriction { restriction_type = "none" } }
viewer_certificate { cloudfront_default_certificate = true }
price_class = "PriceClass_100"
}


output "db_instance_id" { value = local.db_instance_id }
output "db_public_ip" { value = data.aws_instance.dbi.public_ip }
output "mcp_endpoint" { value = "http://" + data.aws_instance.dbi.public_ip + ":8000/" }
output "mcp_health" { value = "http://" + data.aws_instance.dbi.public_ip + ":8000/healthz" }
output "mcp_sse" { value = "http://" + data.aws_instance.dbi.public_ip + ":8000/sse" }
output "cloudfront_domain" { value = var.use_cloudfront ? aws_cloudfront_distribution.mcp[0].domain_name : "" }
output "mcp_https" { value = var.use_cloudfront ? ("https://" + aws_cloudfront_distribution.mcp[0].domain_name + "/") : "" }
