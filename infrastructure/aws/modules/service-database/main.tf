# One service's database on the shared RDS instance (plan.md section 11:
# database per service). The production equivalent of one block of
# infrastructure/postgres/init.sql:
#
#   - a generated password in Secrets Manager (syncwave/<name>/db), which the
#     service's tasks receive as DB_PASSWORD
#   - a one-off ECS task, syncwave-<name>-db-init, that creates the role and
#     database with the RDS master credentials. RDS sits in private subnets,
#     so this runs inside the VPC instead of from a laptop. Run it once
#     (the db_init_command output); it is safe to run again, and running it
#     again resets the role's password to the one in the secret.
#
# The service applies its own schema (alembic upgrade head) on start-up.

terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
    random = {
      source = "hashicorp/random"
    }
  }
}

variable "name" {
  description = "Database, role and secret name, e.g. \"lyrics\"."
  type        = string
}

variable "db_address" {
  type = string
}

variable "db_port" {
  type = number
}

variable "master_username" {
  type = string
}

variable "master_secret_arn" {
  description = "The RDS-managed master secret (JSON with username and password)."
  type        = string
}

variable "cluster_arn" {
  type = string
}

variable "execution_role_arn" {
  description = "Must be able to read both secrets (the platform's shared execution role can)."
  type        = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "security_group_ids" {
  description = "Must be allowed into RDS on the database port."
  type        = list(string)
}

variable "image" {
  type    = string
  default = "public.ecr.aws/docker/library/postgres:17-alpine"
}

data "aws_region" "current" {}

resource "random_password" "db" {
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "db" {
  name        = "syncwave/${var.name}/db"
  description = "Postgres password of the ${var.name} role"
  # Deleted immediately on destroy, so the stack can be rebuilt with the same name
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "db" {
  secret_id     = aws_secretsmanager_secret.db.id
  secret_string = random_password.db.result
}

resource "aws_cloudwatch_log_group" "db_init" {
  name              = "/ecs/syncwave/${var.name}-db-init"
  retention_in_days = 14
}

locals {
  # psql variables (:'name', :'password') are quoted by psql itself, and the
  # statements are built with format(%I, %L), so nothing is spliced by the shell.
  # GRANT ... TO CURRENT_USER: the RDS master user is not a true superuser and,
  # since Postgres 16, must be a member of a role to create a database it owns.
  init_script = <<-EOT
    set -eu
    psql -v ON_ERROR_STOP=1 -v name="$SERVICE_DB" -v password="$SERVICE_DB_PASSWORD" <<'SQL'
    SELECT format('CREATE ROLE %I LOGIN', :'name')
      WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'name') \gexec
    SELECT format('ALTER ROLE %I PASSWORD %L', :'name', :'password') \gexec
    SELECT format('GRANT %I TO CURRENT_USER', :'name')
      WHERE NOT pg_has_role(current_user, :'name', 'MEMBER') \gexec
    SELECT format('CREATE DATABASE %I OWNER %I', :'name', :'name')
      WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'name') \gexec
    SELECT format('REVOKE CONNECT ON DATABASE %I FROM PUBLIC', :'name') \gexec
    SQL
    echo "database ${var.name} is ready"
  EOT
}

resource "aws_ecs_task_definition" "db_init" {
  family                   = "syncwave-${var.name}-db-init"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = var.execution_role_arn

  container_definitions = jsonencode([{
    name       = "db-init"
    image      = var.image
    essential  = true
    entryPoint = ["sh", "-c"]
    command    = [local.init_script]
    environment = [
      { name = "PGHOST", value = var.db_address },
      { name = "PGPORT", value = tostring(var.db_port) },
      { name = "PGUSER", value = var.master_username },
      { name = "PGDATABASE", value = "postgres" },
      { name = "PGSSLMODE", value = "require" },
      { name = "SERVICE_DB", value = var.name },
    ]
    secrets = [
      { name = "PGPASSWORD", valueFrom = "${var.master_secret_arn}:password::" },
      { name = "SERVICE_DB_PASSWORD", valueFrom = aws_secretsmanager_secret.db.arn },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.db_init.name
        awslogs-region        = data.aws_region.current.region
        awslogs-stream-prefix = "ecs"
      }
    }
  }])

  # The secret must hold a value before a task can start
  depends_on = [aws_secretsmanager_secret_version.db]
}

output "password_secret_arn" {
  value = aws_secretsmanager_secret.db.arn
}

output "database_name" {
  value = var.name
}

output "db_init_command" {
  description = "Runs the db-init task once; prints the task ARN."
  value = join(" ", [
    "aws ecs run-task",
    "--region ${data.aws_region.current.region}",
    "--cluster ${var.cluster_arn}",
    "--launch-type FARGATE",
    "--task-definition ${aws_ecs_task_definition.db_init.family}",
    "--network-configuration 'awsvpcConfiguration={subnets=[${join(",", var.subnet_ids)}],securityGroups=[${join(",", var.security_group_ids)}],assignPublicIp=ENABLED}'",
    "--query 'tasks[0].taskArn' --output text",
  ])
}

output "db_init_log_group" {
  value = aws_cloudwatch_log_group.db_init.name
}
