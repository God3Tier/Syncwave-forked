# One ECS service running one container, optionally routed from the ALB.
#
# Terraform owns the task definition's shape (env, secrets, CPU, memory,
# roles). The CI deploy job (ci/scripts/deploy-ecs.sh) owns the image: it
# copies the latest revision of family syncwave-<name>, swaps the image and
# points the service at the new revision. So the service ignores changes to
# task_definition, and old revisions are never deregistered (skip_destroy).

terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  family = "syncwave-${var.name}"
  routed = var.http_route != null

  container = merge(
    {
      name         = var.name
      image        = var.image
      essential    = true
      stopTimeout  = var.stop_timeout
      portMappings = [for port in concat(local.routed ? [8080] : [], var.extra_ports) : { containerPort = port, protocol = "tcp" }]
      environment  = [for key, value in var.environment : { name = key, value = value }]
      secrets      = [for key, value in var.secrets : { name = key, valueFrom = value }]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.this.name
          awslogs-region        = data.aws_region.current.region
          awslogs-stream-prefix = "ecs"
        }
      }
    },
    var.command == null ? {} : { command = var.command },
  )
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/syncwave/${var.name}"
  retention_in_days = var.log_retention_days
}

# ---------------------------------------------------------------------------
# Task role: what the application may call. Always allows ECS Exec
# (`aws ecs execute-command`) for debugging; anything else comes from
# task_role_policy_json.

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "task" {
  name               = "${local.family}-task"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

data "aws_iam_policy_document" "exec" {
  statement {
    actions = [
      "ssmmessages:CreateControlChannel",
      "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel",
      "ssmmessages:OpenDataChannel",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "exec" {
  name   = "ecs-exec"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.exec.json
}

resource "aws_iam_role_policy" "app" {
  count  = var.task_role_policy_json == null ? 0 : 1
  name   = "app"
  role   = aws_iam_role.task.id
  policy = var.task_role_policy_json
}

# ---------------------------------------------------------------------------

resource "aws_ecs_task_definition" "this" {
  family                   = local.family
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions    = jsonencode([local.container])
  skip_destroy             = true

  # CI builds linux/amd64 images (ci/scripts/build-image.sh)
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
}

resource "aws_ecs_service" "this" {
  name                   = var.name
  cluster                = var.cluster_arn
  task_definition        = aws_ecs_task_definition.this.arn
  desired_count          = var.desired_count
  enable_execute_command = true
  propagate_tags         = "SERVICE"

  capacity_provider_strategy {
    capacity_provider = var.capacity_provider
    weight            = 1
  }

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = var.security_group_ids
    assign_public_ip = var.assign_public_ip
  }

  # A deployment whose tasks keep failing is rolled back to the last good one
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  dynamic "load_balancer" {
    for_each = local.routed ? [1] : []
    content {
      target_group_arn = aws_lb_target_group.this[0].arn
      container_name   = var.name
      container_port   = 8080
    }
  }

  # Other services call this one by name, e.g. playlist.syncwave.internal
  dynamic "service_registries" {
    for_each = var.service_discovery == null ? [] : [1]
    content {
      registry_arn = aws_service_discovery_service.this[0].arn
    }
  }

  # The API applies its migrations before it starts listening
  health_check_grace_period_seconds = local.routed ? 60 : null

  lifecycle {
    ignore_changes = [task_definition]
  }

  # The target group must be attached to the ALB before a service can use it
  depends_on = [aws_lb_listener_rule.this]
}

# ---------------------------------------------------------------------------
# Private DNS name: <name>.<namespace>, e.g. playlist.syncwave.internal

resource "aws_service_discovery_service" "this" {
  count = var.service_discovery == null ? 0 : 1
  name  = var.service_discovery.name

  dns_config {
    namespace_id   = var.service_discovery.namespace_id
    routing_policy = "MULTIVALUE"
    dns_records {
      type = "A"
      ttl  = 10
    }
  }
}

# ---------------------------------------------------------------------------
# ALB route: /api/<service>/<path> -> <service>:8080/<path>

resource "aws_lb_target_group" "this" {
  count                = local.routed ? 1 : 0
  name                 = substr(local.family, 0, 32)
  target_type          = "ip"
  port                 = 8080
  protocol             = "HTTP"
  vpc_id               = var.http_route.vpc_id
  deregistration_delay = 30

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener_rule" "this" {
  count        = local.routed ? 1 : 0
  listener_arn = var.http_route.listener_arn
  priority     = var.http_route.priority

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this[0].arn
  }

  condition {
    path_pattern {
      values = ["${var.http_route.path_prefix}/*"]
    }
  }

  # The services' routes have no prefix (GET /health, GET /songs/{id}/lyrics)
  transform {
    type = "url-rewrite"
    url_rewrite_config {
      rewrite {
        regex   = "^${var.http_route.path_prefix}/(.*)$"
        replace = "/$1"
      }
    }
  }
}
