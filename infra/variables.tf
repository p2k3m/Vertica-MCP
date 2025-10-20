variable "aws_region" {
  type    = string
  default = "ap-south-1"
}

variable "account_id" {
  type = string
}

variable "db_instance_id" {
  type        = string
  description = "The EC2 instance ID that will run the Vertica MCP service"
  default     = null
}

variable "db_instance_name" {
  type        = string
  description = "Optional: The value of the EC2 Name tag for the instance that will run Vertica MCP"
  default     = null
}

variable "http_token" {
  type    = string
  default = ""
}

variable "db_host" {
  type    = string
  default = "127.0.0.1"
}

variable "db_port" {
  type    = number
  default = 5433
}

variable "db_user" {
  type = string
}

variable "db_password" {
  type = string
}

variable "db_name" {
  type = string
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
