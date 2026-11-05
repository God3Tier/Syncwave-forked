# Streaming Service (services/audio_transmitter/README.md) in production.
# One ECS service, named "streaming" as in Compose's network alias and the
# gateway route:
#   streaming   HTTP on 8081: /api/streaming/* on the shared ALB, and
#               streaming.syncwave.internal:8081 for Sync and the song
#               request orchestrator
# It has no database: it reads a song's audio_reference from the Catalogue
# Service and the audio from S3. Shared infrastructure (network, cluster, ALB,
# audio bucket) comes from the platform stack's outputs.

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

  # Same variables as services/audio_transmitter/compose.yaml, minus
  # AWS_ENDPOINT_URL, AWS_ALLOW_HTTP and the access keys: the AWS SDK then
  # uses real S3 with the task role's credentials. CATALOGUE_URL is the name
  # the Catalogue stack registers in the private DNS.
  environment = {
    CATALOGUE_URL             = "http://catalogue.${local.platform.service_discovery_namespace}:8080"
    CATALOGUE_TIMEOUT_SECONDS = tostring(var.catalogue_timeout_seconds)
    AWS_REGION                = var.region
    S3_BUCKET                 = local.platform.audio_bucket_name
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
  name                 = "syncwave/audio_transmitter"
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
# Streams the uploaded audio: GetObject on the audio/ prefix only

data "aws_iam_policy_document" "streaming" {
  statement {
    sid       = "ReadUploadedAudio"
    actions   = ["s3:GetObject"]
    resources = [for prefix in var.s3_read_prefixes : "${local.platform.audio_bucket_arn}/${prefix}*"]
  }
}

module "streaming" {
  source = "../../modules/ecs-service"

  name                  = "streaming"
  image                 = local.image
  cpu                   = var.cpu
  memory                = var.memory
  desired_count         = var.desired_count
  environment           = local.environment
  task_role_policy_json = data.aws_iam_policy_document.streaming.json

  cluster_arn        = local.task_network.cluster_arn
  execution_role_arn = local.task_network.execution_role_arn
  subnet_ids         = local.task_network.subnet_ids
  security_group_ids = local.task_network.security_group_ids

  # The service binds 8081 (src/main.rs)
  port = 8081
  http_route = {
    listener_arn = local.platform.alb_listener_arn
    vpc_id       = local.platform.vpc_id
    path_prefix  = "/api/streaming"
    priority     = var.route_priority
  }

  service_discovery = {
    namespace_id = local.platform.service_discovery_namespace_id
    name         = "streaming"
  }
}
