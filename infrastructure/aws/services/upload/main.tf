# Upload Service in production (services/upload/README.md). One image, two
# ECS services, as in services/upload/compose.yaml:
#   upload             REST API at /api/upload/* on the shared ALB; writes the
#                      audio and .lrc to S3 and an outbox row to its database
#   upload-publisher   polls the outbox and publishes SongUploaded
# Shared infrastructure (network, cluster, ALB, RDS, RabbitMQ, audio bucket)
# comes from the platform stack's outputs.

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

  # Same variables as services/upload/compose.yaml, minus S3_ENDPOINT_URL,
  # S3_FORCE_PATH_STYLE and the access keys: boto3 then uses real S3 with
  # the task role's credentials. S3_BUCKET must be set: the code's default
  # is the local bucket name.
  environment = {
    SERVICE_NAME                = "upload"
    PORT                        = "8080"
    LOG_LEVEL                   = var.log_level
    AMQP_HOST                   = local.platform.rabbitmq_host
    AMQP_PORT                   = tostring(local.platform.rabbitmq_port)
    AMQP_USER                   = local.platform.rabbitmq_user
    DB_HOST                     = local.platform.db_address
    DB_PORT                     = tostring(local.platform.db_port)
    DB_NAME                     = module.db.database_name
    DB_USER                     = module.db.database_name
    AWS_REGION                  = var.region
    S3_BUCKET                   = local.platform.audio_bucket_name
    UPLOAD_MAX_AUDIO_BYTES      = tostring(var.max_audio_bytes)
    UPLOAD_MAX_LYRICS_BYTES     = tostring(var.max_lyrics_bytes)
    UPLOAD_PUBLISH_POLL_SECONDS = tostring(var.publish_poll_seconds)
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
  name                 = "syncwave/upload"
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

  name               = "upload"
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
# API: POST /uploads. boto3's upload_fileobj sends one PutObject below 8 MiB
# and a multipart upload above it, and the service deletes the objects again
# if the database write fails. GET /ready calls head_bucket (s3:ListBucket).

data "aws_iam_policy_document" "api" {
  statement {
    sid = "WriteUploads"
    actions = [
      "s3:PutObject",
      "s3:AbortMultipartUpload",
      "s3:DeleteObject",
    ]
    resources = [for prefix in var.s3_write_prefixes : "${local.platform.audio_bucket_arn}/${prefix}*"]
  }

  statement {
    sid       = "ReadinessCheck"
    actions   = ["s3:ListBucket"]
    resources = [local.platform.audio_bucket_arn]
  }
}

module "api" {
  source = "../../modules/ecs-service"

  name                  = "upload"
  image                 = local.image
  cpu                   = var.api_cpu
  memory                = var.api_memory
  desired_count         = var.api_desired_count
  environment           = local.environment
  secrets               = local.secrets
  task_role_policy_json = data.aws_iam_policy_document.api.json
  wait_for_steady_state = true

  cluster_arn        = local.task_network.cluster_arn
  execution_role_arn = local.task_network.execution_role_arn
  subnet_ids         = local.task_network.subnet_ids
  security_group_ids = local.task_network.security_group_ids

  http_route = {
    listener_arn = local.platform.alb_listener_arn
    vpc_id       = local.platform.vpc_id
    path_prefix  = "/api/upload"
    priority     = var.api_route_priority
  }
}

# ---------------------------------------------------------------------------
# Publisher: the transactional outbox. Needs only its database and RabbitMQ,
# so no S3 permissions. Rows are claimed FOR UPDATE SKIP LOCKED, so a Spot
# interruption or a second task is safe.

module "publisher" {
  source = "../../modules/ecs-service"

  name              = "upload-publisher"
  image             = local.image
  command           = ["python", "-m", "upload_service.publisher"]
  cpu               = var.publisher_cpu
  memory            = var.publisher_memory
  desired_count     = var.publisher_desired_count
  capacity_provider = var.publisher_capacity_provider
  environment       = local.environment
  secrets           = local.secrets

  cluster_arn        = local.task_network.cluster_arn
  execution_role_arn = local.task_network.execution_role_arn
  subnet_ids         = local.task_network.subnet_ids
  security_group_ids = local.task_network.security_group_ids

  # The API has migrated the database by the time it is steady
  depends_on = [module.api]
}
