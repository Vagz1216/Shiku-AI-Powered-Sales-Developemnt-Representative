output "ecr_repository_url" {
  value = aws_ecr_repository.sdr_backend.repository_url
}

output "service_url" {
  value = "https://${aws_apprunner_service.sdr_backend.service_url}"
}

output "service_arn" {
  value = aws_apprunner_service.sdr_backend.arn
}
