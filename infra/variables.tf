variable "aws_region" { type = string default = "ap-south-1" }
variable "account_id" { type = string }
variable "http_token" { type = string default = "" }


variable "db_host" { type = string default = "127.0.0.1" }
variable "db_port" { type = number default = 5433 }
variable "db_user" { type = string }
variable "db_password" { type = string }
variable "db_name" { type = string }


variable "use_cloudfront" { type = bool default = false }
