# Song request orchestrator in production
# (services/song_request_orchestrator/README.md). One ECS service:
#   orchestrator   /api/orchestrator/* on the shared ALB. For a playlist it
#                  gets each song's audio, lyrics and waveform points from the
#                  Streaming, Lyrics and Waveform Services in one call.
# It keeps playback sessions and their ring buffers in memory, so it runs as
# one task. Shared infrastructure (network, cluster, ALB, RDS) comes from the
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
  internal = local.platform.service_discovery_namespace

  # Same variables as services/song_request_orchestrator/compose.yaml. The
  # services it calls are the names their stacks register in the private DNS.
  # Cognito authentication stays off: no COGNITO_* variables are set.
  environment = {
    DB_HOST              = local.platform.db_address
    DB_PORT              = tostring(local.platform.db_port)
    DB_NAME              = module.db.database_name
    DB_USER              = module.db.database_name
    PLAYLIST_SERVICE_URL = "http://playlist.${local.internal}:8080"
    AUDIO_SERVICE_URL    = "http://streaming.${local.internal}:8081"
    LYRICS_SERVICE_URL   = "http://lyrics.${local.internal}:8080"
    WAVEFORM_SERVICE_URL = "http://waveform.${local.internal}:8080"
  }

  secrets = {
    DB_PASSWORD = module.db.password_secret_arn
  }

  task_network = {
    cluster_arn        = local.platform.cluster_arn
    execution_role_arn = local.platform.execution_role_arn
    subnet_ids         = local.platform.public_subnet_ids
    security_group_ids = [local.platform.services_security_group_id]
  }
}

# ---------------------------------------------------------------------------
# Image repository, named after the folder like CI's image
# (ci/scripts/deploy-ecs.sh copies tested images here).
# force_delete: the session teardown deletes it with its images.

resource "aws_ecr_repository" "this" {
  name                 = "syncwave/song_request_orchestrator"
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
# This service's database and login role on the shared RDS instance. The
# service opens a connection pool at startup and fails without it.

module "db" {
  source = "../../modules/service-database"

  name               = "orchestrator"
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
# API. Calls the other services over HTTP and touches no AWS API, so its task
# role has no extra permissions. Nothing calls it by name.

module "api" {
  source = "../../modules/ecs-service"

  name          = "orchestrator"
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
    path_prefix  = "/api/orchestrator"
    priority     = var.route_priority
  }
}
