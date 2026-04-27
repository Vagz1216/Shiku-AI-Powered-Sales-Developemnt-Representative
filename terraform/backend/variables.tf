variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "cluster_arn" {
  description = "Aurora cluster ARN from terraform/database"
  type        = string
}

variable "secret_arn" {
  description = "Secrets Manager ARN from terraform/database"
  type        = string
}

variable "db_name" {
  type    = string
  default = "sdr"
}

variable "openai_api_key" {
  type      = string
  sensitive = true
}

variable "groq_api_key" {
  type      = string
  default   = ""
  sensitive = true
}

variable "cerebras_api_key" {
  type      = string
  default   = ""
  sensitive = true
}

variable "openrouter_api_key" {
  type      = string
  default   = ""
  sensitive = true
}

variable "agentmail_api_key" {
  type      = string
  sensitive = true
}

variable "agentmail_inbox_id" {
  type = string
}

variable "composio_api_key" {
  type      = string
  default   = ""
  sensitive = true
}

variable "clerk_jwks_url" {
  type = string
}

variable "clerk_secret_key" {
  type      = string
  sensitive = true
}

variable "webhook_secret" {
  type      = string
  default   = ""
  sensitive = true
}

variable "cors_origins" {
  type    = string
  default = "http://localhost:3000"
}
