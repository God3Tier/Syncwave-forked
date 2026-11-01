# Recommendation Service in production (services/recommendation/README.md).
# One image, one ECS service, as in services/recommendation/compose.yaml:
#   recommendation   REST API at /api/recommendation/* on the shared ALB
# It has no database and no worker: it reads songs from the Catalogue Service
# and the current weather from Open-Meteo, and keeps nothing. Shared
# infrastructure (network, cluster, ALB) comes from the platform stack's outputs.

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

  # Same variables as services/recommendation/compose.yaml, minus
  # WEATHER_STUB_CONDITION (only used when WEATHER_MODE=stub). CATALOGUE_URL is
  # the name the Catalogue stack registers in the private DNS.
  environment = {
    SERVICE_NAME              = "recommendation"
    PORT                      = "8080"
    LOG_LEVEL                 = var.log_level
    CATALOGUE_MODE            = var.catalogue_mode
    CATALOGUE_URL             = "http://catalogue.${local.platform.service_discovery_namespace}:8080"
    CATALOGUE_TIMEOUT_SECONDS = tostring(var.catalogue_timeout_seconds)
    CANDIDATE_LIMIT           = tostring(var.candidate_limit)
    WEATHER_MODE              = var.weather_mode
    WEATHER_TIMEOUT_SECONDS   = tostring(var.weather_timeout_seconds)
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
  name                 = "syncwave/recommendation"
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
# API. Calls the Catalogue and Open-Meteo over HTTP and touches no AWS API,
# so its task role has no extra permissions.

module "api" {
  source = "../../modules/ecs-service"

  name          = "recommendation"
  image         = local.image
  cpu           = var.api_cpu
  memory        = var.api_memory
  desired_count = var.api_desired_count
  environment   = local.environment

  cluster_arn        = local.task_network.cluster_arn
  execution_role_arn = local.task_network.execution_role_arn
  subnet_ids         = local.task_network.subnet_ids
  security_group_ids = local.task_network.security_group_ids

  http_route = {
    listener_arn = local.platform.alb_listener_arn
    vpc_id       = local.platform.vpc_id
    path_prefix  = "/api/recommendation"
    priority     = var.api_route_priority
  }
}
