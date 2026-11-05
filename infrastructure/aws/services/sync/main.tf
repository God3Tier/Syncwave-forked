# Sync Service in production (services/sync/README.md). One image, one ECS
# service, as in services/sync/compose.yaml:
#   sync   HTTP and the participants' WebSocket (/api/sync/ws) on the shared
#          ALB, and the gRPC SyncControlService on 50051 that Jam calls
#          (sync.syncwave.internal:50051)
# It keeps WebSockets and timing state in memory, so it runs as exactly one
# task (README.md, "Jam and Sync run as one task").
#
# It calls the Catalogue over gRPC and the Streaming Service over HTTP by
# name. If the Catalogue stack has not been applied, the catalogue target is
# left empty and Sync uses its built-in fake (every song READY).

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

# Optional: empty when the Catalogue stack is not applied
data "terraform_remote_state" "catalogue" {
  backend = "s3"
  config = {
    bucket = local.state_bucket
    key    = "services/catalogue/terraform.tfstate"
    region = var.region
  }
  defaults = {
    grpc_target               = ""
    internal_token_secret_arn = null
  }
}

locals {
  platform  = data.terraform_remote_state.platform.outputs
  catalogue = data.terraform_remote_state.catalogue.outputs
  image     = "${aws_ecr_repository.this.repository_url}:${var.image_tag}"

  # Same variables as services/sync/compose.yaml. The timing settings are left
  # at the code's defaults, which are the values compose.yaml sets.
  environment = {
    SERVICE_NAME          = "sync"
    PORT                  = "8080"
    GRPC_PORT             = "50051"
    LOG_LEVEL             = var.log_level
    DEPENDENCY_TIMEOUT_MS = tostring(var.dependency_timeout_ms)
    DB_HOST               = local.platform.db_address
    DB_PORT               = tostring(local.platform.db_port)
    DB_NAME               = module.db.database_name
    DB_USER               = module.db.database_name
    CATALOGUE_GRPC_TARGET = local.catalogue.grpc_target
    STREAMING_HTTP_URL    = var.streaming_enabled ? "http://streaming.${local.platform.service_discovery_namespace}:8081" : ""
    # The participant token the frontend is built with (VITE_SYNC_PARTICIPANT_TOKEN);
    # it is in the public JavaScript bundle, so it is not a secret.
    MOCK_SYNC_TOKEN = var.participant_token
  }

  secrets = merge(
    {
      DB_PASSWORD            = module.db.password_secret_arn
      INTERNAL_SERVICE_TOKEN = aws_secretsmanager_secret.internal_token.arn
    },
    local.catalogue.internal_token_secret_arn == null ? {} : {
      CATALOGUE_INTERNAL_TOKEN = local.catalogue.internal_token_secret_arn
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
  name                 = "syncwave/sync"
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

  name               = "sync"
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
# The token Jam sends in x-internal-token when it calls SyncControlService
# (the production replacement for local-jam-to-sync-token). The Jam stack
# reads internal_token_secret_arn from this stack's outputs.

resource "random_password" "internal_token" {
  length  = 40
  special = false
}

resource "aws_secretsmanager_secret" "internal_token" {
  name        = "syncwave/sync/internal-token"
  description = "x-internal-token that Jam must send to the Sync gRPC SyncControlService"
  # Deleted immediately on destroy, so the stack can be rebuilt with the same name
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "internal_token" {
  secret_id     = aws_secretsmanager_secret.internal_token.id
  secret_string = random_password.internal_token.result
}

# ---------------------------------------------------------------------------
# HTTP, WebSocket and gRPC. Calls the Catalogue and Streaming Services and
# touches no AWS API, so its task role has no extra permissions.

module "api" {
  source = "../../modules/ecs-service"

  name          = "sync"
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
    path_prefix  = "/api/sync"
    priority     = var.route_priority
  }

  # Jam calls SyncControlService on 50051 by name
  extra_ports = [50051]
  service_discovery = {
    namespace_id = local.platform.service_discovery_namespace_id
    name         = "sync"
  }
}

# The HTTP /internal/v1/* routes are for services, guarded only by the
# internal token; Jam uses gRPC instead. Keep them off the public ALB.
resource "aws_lb_listener_rule" "internal_routes" {
  listener_arn = local.platform.alb_listener_arn
  priority     = var.route_priority - 1

  action {
    type = "fixed-response"
    fixed_response {
      content_type = "application/json"
      message_body = jsonencode({ error = { code = "NOT_FOUND", message = "Sync's internal routes are not public" } })
      status_code  = "404"
    }
  }

  condition {
    path_pattern {
      values = ["/api/sync/internal/*"]
    }
  }
}
