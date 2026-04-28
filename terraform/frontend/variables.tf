variable "aws_region" {
  type    = string
  default = "us-west-2"
}

variable "backend_url" {
  description = "App Runner backend URL from terraform/backend output (e.g. https://xxx.us-west-2.awsapprunner.com)"
  type        = string
}
