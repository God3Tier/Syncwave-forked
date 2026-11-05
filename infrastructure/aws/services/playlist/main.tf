# Playlist Service in production (services/playlist/README.md). One image, one
# ECS service, as in services/playlist/compose.yaml:
#   playlist   REST API at /api/playlist/* on the shared ALB, and the read-only
#              gRPC GetPlaylist on 50051 that Jam calls (playlist.syncwave.internal:50051)
# It has no worker. Shared infrastructure (network, cluster, ALB, RDS) comes
# from the platform stack's outputs.

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

  # Same variables as services/playlist/compose.yaml. CATALOGUE_URL is the name
  # the Catalogue stack registers in the private DNS.
  environment = {
    SERVICE_NAME              = "playlist"
    PORT                      = "8080"
    GRPC_PORT                 = "50051"
    LOG_LEVEL                 = var.log_level
    DB_HOST                   = local.platform.db_address
    DB_PORT                   = tostring(local.platform.db_port)
    DB_NAME                   = module.db.database_name
    DB_USER                   = module.db.database_name
    CATALOGUE_MODE            = var.catalogue_mode
    CATALOGUE_URL             = "http://catalogue.${local.platform.service_discovery_namespace}:8080"
    CATALOGUE_TIMEOUT_SECONDS = tostring(var.catalogue_timeout_seconds)
  }

  secrets = {
    DB_PASSWORD            = module.db.password_secret_arn
    INTERNAL_SERVICE_TOKEN = aws_secretsmanager_secret.internal_token.arn
  }

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
  name                 = "syncwave/playlist"
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

  name               = "playlist"
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
# The token Jam sends in x-internal-token when it calls GetPlaylist (the
# production replacement for local-playlist-internal-token). The Jam stack
# reads internal_token_secret_arn from this stack's outputs and passes it to
# its tasks as PLAYLIST_INTERNAL_TOKEN.

resource "random_password" "internal_token" {
  length  = 40
  special = false
}

resource "aws_secretsmanager_secret" "internal_token" {
  name        = "syncwave/playlist/internal-token"
  description = "x-internal-token that Jam must send to the Playlist gRPC GetPlaylist"
  # Deleted immediately on destroy, so the stack can be rebuilt with the same name
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "internal_token" {
  secret_id     = aws_secretsmanager_secret.internal_token.id
  secret_string = random_password.internal_token.result
}

# ---------------------------------------------------------------------------
# API and gRPC. Reads only its database and the Catalogue over HTTP, so its
# task role has no extra permissions.

module "api" {
  source = "../../modules/ecs-service"

  name          = "playlist"
  image         = local.image
  cpu           = var.api_cpu
  memory        = var.api_memory
  desired_count = var.api_desired_count
  environment   = local.environment
  secrets       = local.secrets

  cluster_arn        = local.task_network.cluster_arn
  execution_role_arn = local.task_network.execution_role_arn
  subnet_ids         = local.task_network.subnet_ids
  security_group_ids = local.task_network.security_group_ids

  http_route = {
    listener_arn = local.platform.alb_listener_arn
    vpc_id       = local.platform.vpc_id
    path_prefix  = "/api/playlist"
    priority     = var.api_route_priority
  }

  # Jam calls GetPlaylist on 50051 by name
  extra_ports = [50051]
  service_discovery = {
    namespace_id = local.platform.service_discovery_namespace_id
    name         = "playlist"
  }
}
