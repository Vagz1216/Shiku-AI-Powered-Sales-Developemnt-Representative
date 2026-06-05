variable "aws_region" {
  type    = string
  default = "eu-west-2"
}

variable "backend_url" {
  description = "App Runner backend URL from terraform/backend output (e.g. https://xxx.eu-west-2.awsapprunner.com)"
  type        = string
}
