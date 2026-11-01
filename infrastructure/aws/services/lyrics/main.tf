# Lyrics Service in production (services/lyrics/README.md). One image, two
# ECS services, as in services/lyrics/compose.yaml:
#   lyrics          the HTTP API at /api/lyrics/* on the shared ALB
#   lyrics-worker   the AMQP consumer of lyrics.song-uploaded, no port
# Shared infrastructure (network, cluster, ALB, RDS, RabbitMQ, bucket) comes
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

  # Same variables as services/lyrics/compose.yaml, minus S3_ENDPOINT_URL,
  # S3_FORCE_PATH_STYLE and the access keys: boto3 then uses real S3 with
  # the task role's credentials.
  environment = {
    SERVICE_NAME     = "lyrics"
    PORT             = "8080"
    LOG_LEVEL        = var.log_level
    AMQP_HOST        = local.platform.rabbitmq_host
    AMQP_PORT        = tostring(local.platform.rabbitmq_port)
    AMQP_USER        = local.platform.rabbitmq_user
    AMQP_PREFETCH    = tostring(var.amqp_prefetch)
    DB_HOST          = local.platform.db_address
    DB_PORT          = tostring(local.platform.db_port)
    DB_NAME          = module.db.database_name
    DB_USER          = module.db.database_name
    AWS_REGION       = var.region
    S3_BUCKET        = local.platform.audio_bucket_name
    LYRICS_MAX_BYTES = tostring(var.lyrics_max_bytes)
  }

  secrets = {
    DB_PASSWORD   = module.db.password_secret_arn
    AMQP_PASSWORD = local.platform.rabbitmq_password_secret_arn
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
  name                 = "syncwave/lyrics"
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

  name               = "lyrics"
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
# API: GET /songs/{songId}/lyrics. Reads only its database, so its task role
# has no extra permissions.

module "api" {
  source = "../../modules/ecs-service"

  name          = "lyrics"
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
    path_prefix  = "/api/lyrics"
    priority     = var.api_route_priority
  }
}

# ---------------------------------------------------------------------------
# Worker: downloads the uploaded .lrc from S3, parses and stores it

data "aws_iam_policy_document" "worker" {
  statement {
    sid       = "ReadUploadedLyrics"
    actions   = ["s3:GetObject"]
    resources = [for prefix in var.s3_read_prefixes : "${local.platform.audio_bucket_arn}/${prefix}*"]
  }
}

module "worker" {
  source = "../../modules/ecs-service"

  name                  = "lyrics-worker"
  image                 = local.image
  command               = ["python", "-m", "lyrics_service.worker"]
  cpu                   = var.worker_cpu
  memory                = var.worker_memory
  desired_count         = var.worker_desired_count
  capacity_provider     = var.worker_capacity_provider
  environment           = local.environment
  secrets               = local.secrets
  task_role_policy_json = data.aws_iam_policy_document.worker.json

  cluster_arn        = local.task_network.cluster_arn
  execution_role_arn = local.task_network.execution_role_arn
  subnet_ids         = local.task_network.subnet_ids
  security_group_ids = local.task_network.security_group_ids
}
