output "mcp_instance_id" {
  value = aws_instance.mcp.id
}

output "mcp_public_ip" {
  value = local.mcp_public_ip
}

output "mcp_public_dns" {
  value = local.mcp_public_dns
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

output "mcp_https_health" {
  value = length(aws_cloudfront_distribution.mcp) > 0 ? "https://${aws_cloudfront_distribution.mcp[0].domain_name}/healthz" : ""
}

output "mcp_https_sse" {
  value = length(aws_cloudfront_distribution.mcp) > 0 ? "https://${aws_cloudfront_distribution.mcp[0].domain_name}/sse" : ""
}

output "mcp_endpoints" {
  value = {
    direct = {
      base_url   = local.mcp_http_endpoint
      health_url = local.mcp_http_healthz
      sse_url    = local.mcp_http_sse
      public_ip  = local.mcp_public_ip
      public_dns = local.mcp_public_dns
    }
    cloudfront = length(aws_cloudfront_distribution.mcp) > 0 ? {
      domain     = aws_cloudfront_distribution.mcp[0].domain_name
      base_url   = local.mcp_https_endpoint
      health_url = local.mcp_https_healthz
      sse_url    = local.mcp_https_sse
    } : null
  }
}

output "mcp_a2a_metadata" {
  value     = local.a2a_payload
  sensitive = true
}

output "mcp_network_summary" {
  value = {
    docker_binding = local.mcp_docker_port_binding
    security_group = local.mcp_security_group_summary
    network_acls   = local.mcp_network_acl_summary
    narrative      = local.mcp_network_story
  }
}
