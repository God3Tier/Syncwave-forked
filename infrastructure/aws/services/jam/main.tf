# Jam Service in production (services/jam/README.md). One image, one ECS
# service, as in services/jam/compose.yaml:
#   jam   REST API and the room WebSocket (/api/jam/jams/{id}/ws) on the
#         shared ALB
# It keeps rooms and WebSocket connections in memory, so it runs as exactly
# one task (README.md, "Jam and Sync run as one task").
#
# It calls Sync and Playlist over gRPC by name, with the tokens their stacks
# create. If one of those stacks has not been applied, its target is left
# empty and Jam uses its built-in fake for that service.

data "aws_caller_identity" "current" {}

locals {
  state_bucket = "syncwave-tfstate-${data.aws_caller_identity.current.account_id}"
}

data "terraform_remote_state" "platform" {
  backend = "s3"
  config = {
    # Named by bootstrap/ after the account
    bucket = local.state_bucket
    key    = "platform/terraform.tfstate"
    region = var.region
  }
}

# Optional: empty when the Sync stack is not applied
data "terraform_remote_state" "sync" {
  backend = "s3"
  config = {
    bucket = local.state_bucket
    key    = "services/sync/terraform.tfstate"
    region = var.region
  }
  defaults = {
    grpc_target               = ""
    internal_token_secret_arn = null
  }
}

# Optional: empty when the Playlist stack is not applied
data "terraform_remote_state" "playlist" {
  backend = "s3"
  config = {
    bucket = local.state_bucket
    key    = "services/playlist/terraform.tfstate"
    region = var.region
  }
  defaults = {
    grpc_target               = ""
    internal_token_secret_arn = null
  }
}

locals {
  platform = data.terraform_remote_state.platform.outputs
  sync     = data.terraform_remote_state.sync.outputs
  playlist = data.terraform_remote_state.playlist.outputs
  image    = "${aws_ecr_repository.this.repository_url}:${var.image_tag}"

  # Same variables as services/jam/compose.yaml, with DB_* instead of
  # DATABASE_URL so the password comes from Secrets Manager.
  environment = {
    SERVICE_NAME         = "jam"
    PORT                 = "8080"
    DB_HOST              = local.platform.db_address
    DB_PORT              = tostring(local.platform.db_port)
    DB_NAME              = module.db.database_name
    DB_USER              = module.db.database_name
    SYNC_GRPC_TARGET     = local.sync.grpc_target
    SYNC_TIMEOUT_MS      = tostring(var.sync_timeout_ms)
    PLAYLIST_GRPC_TARGET = local.playlist.grpc_target
    PLAYLIST_TIMEOUT_MS  = tostring(var.playlist_timeout_ms)
    # The member token the frontend is built with (VITE_JAM_MEMBER_TOKEN); it
    # is in the public JavaScript bundle, so it is not a secret.
    MOCK_JAM_TOKEN = var.member_token
  }

  secrets = merge(
    { DB_PASSWORD = module.db.password_secret_arn },
    local.sync.internal_token_secret_arn == null ? {} : {
      INTERNAL_SERVICE_TOKEN = local.sync.internal_token_secret_arn
    },
    local.playlist.internal_token_secret_arn == null ? {} : {
      PLAYLIST_INTERNAL_TOKEN = local.playlist.internal_token_secret_arn
    },
  )

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
  name                 = "syncwave/jam"
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

  name               = "jam"
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
# API and WebSocket. Calls Sync and Playlist over gRPC and touches no AWS API,
# so its task role has no extra permissions. Nothing calls Jam by name.

module "api" {
  source = "../../modules/ecs-service"

  name          = "jam"
  image         = local.image
  cpu           = var.cpu
  memory        = var.memory
  desired_count = var.desired_count
  environment   = local.environment
  secrets       = local.secrets

  cluster_arn        = local.task_network.cluster_arn
  execution_role_arn = local.task_network.execution_role_arn
  subnet_ids         = local.task_network.subnet_ids
  security_group_ids = local.task_network.security_group_ids

  http_route = {
    listener_arn = local.platform.alb_listener_arn
    vpc_id       = local.platform.vpc_id
    path_prefix  = "/api/jam"
    priority     = var.route_priority
  }
}
