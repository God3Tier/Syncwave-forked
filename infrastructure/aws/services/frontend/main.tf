# The web UI in production (frontend/README.md). One ECS service:
#   frontend   nginx serving the built React app, behind the shared ALB's
#              catch-all /* rule (like the gateway's `location /`)
# The app calls the APIs with relative /api/<service>/... paths on the same
# origin, so the ALB's /api rules send those to the services. Unknown /api
# paths still get the platform's 404 (priority 900, before this rule).

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
}

# ---------------------------------------------------------------------------
# Image repository. ci/scripts/deploy-ecs.sh copies tested images here.
# force_delete: the session teardown deletes it with its images.

resource "aws_ecr_repository" "this" {
  name                 = "syncwave/frontend"
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
# Static files only: no environment (the tokens are baked in at build time),
# no secrets and no AWS API.

module "web" {
  source = "../../modules/ecs-service"

  name          = "frontend"
  image         = local.image
  cpu           = var.cpu
  memory        = var.memory
  desired_count = var.desired_count

  cluster_arn        = local.platform.cluster_arn
  execution_role_arn = local.platform.execution_role_arn
  subnet_ids         = local.platform.public_subnet_ids
  security_group_ids = [local.platform.services_security_group_id]

  # Every path the /api rules don't take, unchanged: /, /assets/..., and the
  # client-side routes (nginx answers them with index.html)
  http_route = {
    listener_arn = local.platform.alb_listener_arn
    vpc_id       = local.platform.vpc_id
    path_prefix  = ""
    priority     = var.route_priority
    rewrite      = false
  }
}
