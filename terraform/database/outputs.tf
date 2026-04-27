output "cluster_arn" {
  description = "Aurora cluster ARN (needed by backend terraform)"
  value       = aws_rds_cluster.sdr.arn
}

output "secret_arn" {
  description = "Secrets Manager ARN for DB credentials"
  value       = aws_secretsmanager_secret.db_credentials.arn
}

output "db_name" {
  description = "Database name"
  value       = var.db_name
}

output "cluster_endpoint" {
  description = "Cluster writer endpoint"
  value       = aws_rds_cluster.sdr.endpoint
}

output "setup_instructions" {
  value = <<-EOT

    ╔══════════════════════════════════════════════════════════════╗
    ║  SDR Database Deployed Successfully!                       ║
    ╠══════════════════════════════════════════════════════════════╣
    ║                                                            ║
    ║  Cluster ARN:  ${aws_rds_cluster.sdr.arn}
    ║  Secret ARN:   ${aws_secretsmanager_secret.db_credentials.arn}
    ║  Database:     ${var.db_name}
    ║                                                            ║
    ║  Next steps:                                               ║
    ║  1. Copy the ARNs above into terraform/backend/terraform.tfvars
    ║  2. Run: cd ../.. && uv run scripts/migrate_db.py          ║
    ║     to create tables and seed data in Aurora                ║
    ║                                                            ║
    ╚══════════════════════════════════════════════════════════════╝
  EOT
}
