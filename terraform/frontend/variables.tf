variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "backend_url" {
  description = "App Runner backend URL from terraform/backend output (e.g. https://xxx.us-east-1.awsapprunner.com)"
  type        = string
}
