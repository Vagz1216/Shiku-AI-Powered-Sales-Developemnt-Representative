variable "aws_region" {
  type    = string
  default = "us-west-2"
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

variable "composio_user_id" {
  description = "Optional Composio user id for consistent tool sessions (maps to COMPOSIO_USER_ID)"
  type        = string
  default     = ""
}

variable "openai_tracing_key" {
  description = "Optional separate OpenAI key for tracing export (OPENAI_TRACING_KEY); empty uses main OpenAI key only for chat"
  type        = string
  default     = ""
  sensitive   = true
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

# Optional tuning and features — matches config/settings.py (pydantic env names are UPPER_SNAKE_CASE).
# Examples: INTENT_MODEL, RESPONSE_MODEL, OUTREACH_MODEL, REQUIRE_HUMAN_APPROVAL, DAILY_EMAIL_LIMIT, USE_DUMMY_DATA
variable "extra_runtime_environment_variables" {
  description = "Additional key/value pairs merged into App Runner container env (non-secret tuning)"
  type        = map(string)
  default     = {}
}
