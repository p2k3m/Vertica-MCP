variable "aws_region" {
  type    = string
  default = "ap-south-1"
}

variable "account_id" {
  type = string
}

variable "http_token" {
  type    = string
  default = ""
}

variable "db_host" {
  type        = string
  description = "Hostname or IP address of the Vertica database"
}

variable "db_port" {
  type        = number
  description = "Port where Vertica listens for connections"
  default     = 5433
}

variable "db_user" {
  type        = string
  description = "Database user that the MCP server will authenticate as"
}

variable "db_password" {
  type        = string
  description = "Password for the Vertica database user"
}

variable "db_name" {
  type        = string
  description = "Vertica database name"
}

variable "mcp_instance_type" {
  type        = string
  description = "Instance type for the dedicated MCP EC2 host (t3.micro or t3a.micro)"
  default     = "t3.micro"

  validation {
    condition     = contains(["t3.micro", "t3a.micro"], var.mcp_instance_type)
    error_message = "mcp_instance_type must be either t3.micro or t3a.micro"
  }
}

variable "mcp_subnet_id" {
  type        = string
  description = "Optional subnet ID where the MCP instance should be launched. Defaults to the default VPC subnet."
  default     = null
}

variable "mcp_additional_security_group_ids" {
  type        = list(string)
  description = "Additional security group IDs to associate with the MCP instance"
  default     = []
}

variable "vertica_security_group_id" {
  type        = string
  description = "Optional security group ID associated with the Vertica database to open inbound 5433/tcp from the MCP server"
  default     = null
}

variable "image_tag" {
  type        = string
  description = "Docker image tag to deploy for Vertica MCP"
  default     = "latest"
}

variable "use_cloudfront" {
  type    = any
  default = false
}

variable "a2a_ssm_parameter_name" {
  type        = string
  description = "SSM parameter name that stores MCP A2A metadata (set to empty to disable)"
  default     = "/vertica/mcp/a2a"
}
