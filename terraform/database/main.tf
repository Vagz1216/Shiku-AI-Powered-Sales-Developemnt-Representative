terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}
data "aws_vpc" "default" { default = true }

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# ── Secrets ──────────────────────────────────────────────────────────────────

resource "random_password" "db_password" {
  length  = 32
  special = false
}

resource "random_id" "suffix" {
  byte_length = 4
}

resource "aws_secretsmanager_secret" "db_credentials" {
  name = "sdr-aurora-credentials-${random_id.suffix.hex}"
}

resource "aws_secretsmanager_secret_version" "db_credentials" {
  secret_id = aws_secretsmanager_secret.db_credentials.id
  secret_string = jsonencode({
    username = "sdr_admin"
    password = random_password.db_password.result
    dbname   = var.db_name
  })
}

# ── Networking ───────────────────────────────────────────────────────────────

resource "aws_security_group" "aurora" {
  name_prefix = "sdr-aurora-"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [data.aws_vpc.default.cidr_block]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "sdr-aurora-sg" }
}

resource "aws_db_subnet_group" "aurora" {
  name       = "sdr-aurora-subnet-group"
  subnet_ids = data.aws_subnets.default.ids
  tags       = { Name = "sdr-aurora-subnet-group" }
}

# ── Aurora Serverless v2 ─────────────────────────────────────────────────────

resource "aws_rds_cluster" "sdr" {
  cluster_identifier     = "sdr-cluster"
  engine                 = "aurora-postgresql"
  engine_mode            = "provisioned"
  engine_version         = "15.12"
  database_name          = var.db_name
  master_username        = "sdr_admin"
  master_password        = random_password.db_password.result
  db_subnet_group_name   = aws_db_subnet_group.aurora.name
  vpc_security_group_ids = [aws_security_group.aurora.id]
  enable_http_endpoint   = true
  skip_final_snapshot    = true

  serverlessv2_scaling_configuration {
    min_capacity = 0.5
    max_capacity = 2.0
  }

  tags = { Project = "sdr" }
}

resource "aws_rds_cluster_instance" "sdr" {
  identifier         = "sdr-instance-1"
  cluster_identifier = aws_rds_cluster.sdr.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.sdr.engine
  engine_version     = aws_rds_cluster.sdr.engine_version
  tags               = { Project = "sdr" }
}
