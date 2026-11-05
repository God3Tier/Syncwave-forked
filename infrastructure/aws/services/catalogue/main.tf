# Catalogue Service in production (services/catalogue/README.md). One image,
# two ECS services, as in services/catalogue/compose.yaml:
#   catalogue          REST API at /api/catalogue/* on the shared ALB, and the
#                      gRPC GetSong on 50051 that Sync calls; both are reachable
#                      inside the VPC as catalogue.syncwave.internal
#   catalogue-worker   the AMQP consumer of catalogue.song-uploaded and
#                      catalogue.processing-results; publishes SongReady
# Search, Playlist, Recommendation and Streaming call the API by name.
# Shared infrastructure (network, cluster, ALB, RDS, RabbitMQ) comes from the
# platform stack's outputs.

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

  # Same variables as services/catalogue/compose.yaml
  environment = {
    SERVICE_NAME  = "catalogue"
    PORT          = "8080"
    GRPC_PORT     = "50051"
    LOG_LEVEL     = var.log_level
    AMQP_HOST     = local.platform.rabbitmq_host
    AMQP_PORT     = tostring(local.platform.rabbitmq_port)
    AMQP_USER     = local.platform.rabbitmq_user
    AMQP_PREFETCH = tostring(var.amqp_prefetch)
    DB_HOST       = local.platform.db_address
    DB_PORT       = tostring(local.platform.db_port)
    DB_NAME       = module.db.database_name
    DB_USER       = module.db.database_name
  }

  secrets = {
    DB_PASSWORD            = module.db.password_secret_arn
    AMQP_PASSWORD          = local.platform.rabbitmq_password_secret_arn
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
  name                 = "syncwave/catalogue"
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

  name               = "catalogue"
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
# The token gRPC callers send in x-internal-token (the production replacement
# for local-catalogue-internal-token). The Sync stack reads
# internal_token_secret_arn from this stack's outputs and passes it to its
# task as CATALOGUE_INTERNAL_TOKEN.

resource "random_password" "internal_token" {
  length  = 40
  special = false
}

resource "aws_secretsmanager_secret" "internal_token" {
  name        = "syncwave/catalogue/internal-token"
  description = "x-internal-token that callers must send to the Catalogue gRPC GetSong"
  # Deleted immediately on destroy, so the stack can be rebuilt with the same name
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "internal_token" {
  secret_id     = aws_secretsmanager_secret.internal_token.id
  secret_string = random_password.internal_token.result
}

# ---------------------------------------------------------------------------
# API and gRPC. Reads and writes only its database, so its task role has no
# extra permissions. It applies the migrations before it starts listening,
# so Terraform waits for it before creating the worker.

module "api" {
  source = "../../modules/ecs-service"

  name                  = "catalogue"
  image                 = local.image
  cpu                   = var.api_cpu
  memory                = var.api_memory
  desired_count         = var.api_desired_count
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
    path_prefix  = "/api/catalogue"
    priority     = var.api_route_priority
  }

  # Other services call http://catalogue.syncwave.internal:8080 and, for
  # gRPC, catalogue.syncwave.internal:50051
  extra_ports = [50051]
  service_discovery = {
    namespace_id = local.platform.service_discovery_namespace_id
    name         = "catalogue"
  }
}

# ---------------------------------------------------------------------------
# Worker: consumes SongUploaded and the processing results, publishes
# SongReady. Needs only its database and RabbitMQ.

module "worker" {
  source = "../../modules/ecs-service"

  name              = "catalogue-worker"
  image             = local.image
  command           = ["python", "-m", "catalogue_service.worker"]
  cpu               = var.worker_cpu
  memory            = var.worker_memory
  desired_count     = var.worker_desired_count
  capacity_provider = var.worker_capacity_provider
  environment       = local.environment
  secrets           = local.secrets

  cluster_arn        = local.task_network.cluster_arn
  execution_role_arn = local.task_network.execution_role_arn
  subnet_ids         = local.task_network.subnet_ids
  security_group_ids = local.task_network.security_group_ids

  # The API has migrated the database by the time it is steady
  depends_on = [module.api]
}
