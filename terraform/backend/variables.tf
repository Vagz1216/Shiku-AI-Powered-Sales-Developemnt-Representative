variable "aws_region" {
  type    = string
  default = "eu-west-2"
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

variable "azure_openai_api_key" {
  description = "Azure OpenAI API key. When set with endpoint and deployment, Azure is the primary AI provider."
  type        = string
  default     = ""
  sensitive   = true
}

variable "azure_openai_endpoint" {
  description = "Azure OpenAI endpoint, for example https://resource.openai.azure.com"
  type        = string
  default     = ""
}

variable "azure_openai_deployment" {
  description = "Azure OpenAI deployment name used as the primary model identifier."
  type        = string
  default     = ""
}

variable "azure_openai_api_version" {
  description = "Azure OpenAI API version."
  type        = string
  default     = "2024-10-21"
}

variable "azure_openai_wire_api" {
  description = "Azure OpenAI wire API used by the Agents SDK provider: chat_completions or responses."
  type        = string
  default     = "chat_completions"
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
