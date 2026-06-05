variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "eu-west-2"
}

variable "db_name" {
  description = "Name of the PostgreSQL database"
  type        = string
  default     = "sdr"
}
