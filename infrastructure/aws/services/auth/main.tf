# Auth Service in production (services/auth). One image, one ECS service, as
# in services/auth/compose.yaml:
#   auth   sign-up, login, logout, /me and the JWKS, on the shared ALB at
#          /api/auth, and by name at auth.syncwave.internal:8080 so Upload,
#          Playlist, Jam and the orchestrator can fetch the JWKS
#
# Signing key. In Compose the service generates an RSA key on first start and
# keeps it on a volume. Fargate tasks have no persistent volume, so a key made
# at start-up would change on every deploy (logging everyone out) and differ
# between tasks. Instead Terraform generates one key, keeps it in Secrets
# Manager, and the task writes it to JWT_PRIVATE_KEY_PATH before starting the
# app. The key is also in this stack's Terraform state (an encrypted S3
# object that only the team can read); the stack is destroyed every session.

data "aws_caller_identity" "current" {}

data "terraform_remote_state" "platform" {
  backend = "s3"
  config = {
    # Named by bootstrap/ after the account
    bucket = "syncwave-tfstate-${data.aws_caller_identity.current.account_id}"
    key    = "platform/terraform.tfstate"
    region = var.region
  }
}

locals {
  platform = data.terraform_remote_state.platform.outputs
  image    = "${aws_ecr_repository.this.repository_url}:${var.image_tag}"
  key_path = "/var/lib/auth/private.pem"

  # Same variables as services/auth/compose.yaml, with DB_* instead of
  # DATABASE_URL so the password comes from Secrets Manager. The browser's
  # Origin is the site address (CloudFront, or the ALB without it), and the
  # session cookie is Secure whenever that address is https.
  environment = {
    SERVICE_NAME          = "auth"
    PORT                  = "8080"
    DB_HOST               = local.platform.db_address
    DB_PORT               = tostring(local.platform.db_port)
    DB_NAME               = module.db.database_name
    DB_USER               = module.db.database_name
    JWT_PRIVATE_KEY_PATH  = local.key_path
    APP_ORIGIN            = local.platform.base_url
    SESSION_COOKIE_SECURE = startswith(local.platform.base_url, "https://") ? "true" : "false"
  }

  secrets = {
    DB_PASSWORD     = module.db.password_secret_arn
    JWT_PRIVATE_KEY = aws_secretsmanager_secret.signing_key.arn
  }

  # The image's CMD (services/auth/Dockerfile), preceded by writing the key
  # file. Keep the two in step if the Dockerfile's CMD changes.
  command = ["sh", "-c", join(" && ", [
    "umask 077",
    "printf '%s\\n' \"$JWT_PRIVATE_KEY\" > ${local.key_path}",
    "unset JWT_PRIVATE_KEY",
    "alembic upgrade head",
    "exec uvicorn auth_service.main:app --host 0.0.0.0 --port $${PORT:-8080}",
  ])]

  task_network = {
    cluster_arn        = local.platform.cluster_arn
    execution_role_arn = local.platform.execution_role_arn
    subnet_ids         = local.platform.public_subnet_ids
    security_group_ids = [local.platform.services_security_group_id]
  }
}

# ---------------------------------------------------------------------------
# Image repository. ci/scripts/deploy-ecs.sh copies tested images here.
# force_delete: the session teardown deletes it with its images.

resource "aws_ecr_repository" "this" {
  name                 = "syncwave/auth"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  repository = aws_ecr_repository.this.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 15 most recent images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 15
      }
      action = { type = "expire" }
    }]
  })
}

# ---------------------------------------------------------------------------
# This service's database and login role on the shared RDS instance

module "db" {
  source = "../../modules/service-database"

  name               = "auth"
  db_address         = local.platform.db_address
  db_port            = local.platform.db_port
  master_username    = local.platform.db_master_username
  master_secret_arn  = local.platform.db_master_secret_arn
  cluster_arn        = local.task_network.cluster_arn
  execution_role_arn = local.task_network.execution_role_arn
  subnet_ids         = local.task_network.subnet_ids
  security_group_ids = local.task_network.security_group_ids
}

# ---------------------------------------------------------------------------
# Token signing key (RS256), shared by every auth task

resource "tls_private_key" "signing" {
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "aws_secretsmanager_secret" "signing_key" {
  name        = "syncwave/auth/jwt-signing-key"
  description = "PEM private key the Auth Service signs session tokens with (public half served at /.well-known/jwks.json)"
  # Deleted immediately on destroy, so the stack can be rebuilt with the same name
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "signing_key" {
  secret_id     = aws_secretsmanager_secret.signing_key.id
  secret_string = tls_private_key.signing.private_key_pem_pkcs8
}

# ---------------------------------------------------------------------------
# API. Touches no AWS API itself, so its task role has no extra permissions.
# Waits until healthy: the orchestrator loads the JWKS at start-up and exits
# if Auth cannot be reached (RUNBOOK.md §2.3 applies this stack first).

module "api" {
  source = "../../modules/ecs-service"

  name                  = "auth"
  image                 = local.image
  command               = local.command
  cpu                   = var.cpu
  memory                = var.memory
  desired_count         = var.desired_count
  environment           = local.environment
  secrets               = local.secrets
  wait_for_steady_state = true

  cluster_arn        = local.task_network.cluster_arn
  execution_role_arn = local.task_network.execution_role_arn
  subnet_ids         = local.task_network.subnet_ids
  security_group_ids = local.task_network.security_group_ids

  http_route = {
    listener_arn = local.platform.alb_listener_arn
    vpc_id       = local.platform.vpc_id
    path_prefix  = "/api/auth"
    priority     = var.route_priority
  }

  # Upload, Playlist, Jam and the orchestrator fetch the JWKS by name
  service_discovery = {
    namespace_id = local.platform.service_discovery_namespace_id
    name         = "auth"
  }

  depends_on = [aws_secretsmanager_secret_version.signing_key]
}
