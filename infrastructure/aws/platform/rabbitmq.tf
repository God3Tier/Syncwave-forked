# RabbitMQ as a single ECS task, reachable at rabbitmq.syncwave.internal:5672
# (plain AMQP inside the VPC, as in docker-compose.yml). Chosen over Amazon MQ
# for cost and because Amazon MQ only accepts TLS (the AMQP clients would
# need changes).
#
# No persistent volume: a restarted broker starts empty. The init container
# re-declares the topology from infrastructure/rabbitmq/definitions.json (the
# same file and API call as rabbitmq-init in docker-compose.yml), and the
# workers reconnect by themselves. Messages that were queued at the time of
# a restart are lost; for a demo that is an accepted trade-off.

resource "random_password" "rabbitmq" {
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "rabbitmq" {
  name                    = "syncwave/rabbitmq"
  description             = "Password of the syncwave RabbitMQ user"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "rabbitmq" {
  secret_id     = aws_secretsmanager_secret.rabbitmq.id
  secret_string = random_password.rabbitmq.result
}

resource "aws_cloudwatch_log_group" "rabbitmq" {
  name              = "/ecs/syncwave/rabbitmq"
  retention_in_days = 14
}

resource "aws_iam_role" "rabbitmq_task" {
  name               = "syncwave-rabbitmq-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

# ECS Exec, so `rabbitmqctl list_queues` can be run in the container
data "aws_iam_policy_document" "rabbitmq_exec" {
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

resource "aws_iam_role_policy" "rabbitmq_exec" {
  name   = "ecs-exec"
  role   = aws_iam_role.rabbitmq_task.id
  policy = data.aws_iam_policy_document.rabbitmq_exec.json
}

locals {
  rabbitmq_user = "syncwave"
  rabbitmq_log_options = {
    awslogs-group         = aws_cloudwatch_log_group.rabbitmq.name
    awslogs-region        = var.region
    awslogs-stream-prefix = "ecs"
  }
  # Minified; about 4 KB, well inside the task definition size limit
  rabbitmq_definitions = jsonencode(jsondecode(file("${path.module}/../../rabbitmq/definitions.json")))
}

resource "aws_ecs_task_definition" "rabbitmq" {
  family                   = "syncwave-rabbitmq"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.rabbitmq_task.arn

  container_definitions = jsonencode([
    {
      name         = "rabbitmq"
      image        = var.rabbitmq_image
      essential    = true
      portMappings = [{ containerPort = 5672, protocol = "tcp" }]
      environment  = [{ name = "RABBITMQ_DEFAULT_USER", value = local.rabbitmq_user }]
      secrets      = [{ name = "RABBITMQ_DEFAULT_PASS", valueFrom = aws_secretsmanager_secret.rabbitmq.arn }]
      healthCheck = {
        command     = ["CMD", "rabbitmq-diagnostics", "-q", "ping"]
        interval    = 10
        timeout     = 10
        retries     = 6
        startPeriod = 60
      }
      logConfiguration = { logDriver = "awslogs", options = local.rabbitmq_log_options }
    },
    {
      # One-shot: runs once the broker is healthy, then exits
      name       = "rabbitmq-init"
      image      = var.rabbitmq_init_image
      essential  = false
      dependsOn  = [{ containerName = "rabbitmq", condition = "HEALTHY" }]
      entryPoint = ["sh", "-c"]
      command = [join(" ", [
        "printf '%s' \"$DEFINITIONS\" > /tmp/definitions.json &&",
        "curl --fail-with-body --silent --show-error",
        "--retry 10 --retry-all-errors --retry-delay 2",
        "--user \"${local.rabbitmq_user}:$RABBITMQ_PASSWORD\"",
        "--header content-type:application/json",
        "--data-binary @/tmp/definitions.json",
        "http://127.0.0.1:15672/api/definitions",
        "&& echo 'definitions loaded'",
      ])]
      environment      = [{ name = "DEFINITIONS", value = local.rabbitmq_definitions }]
      secrets          = [{ name = "RABBITMQ_PASSWORD", valueFrom = aws_secretsmanager_secret.rabbitmq.arn }]
      logConfiguration = { logDriver = "awslogs", options = local.rabbitmq_log_options }
    },
  ])

  depends_on = [aws_secretsmanager_secret_version.rabbitmq]
}

resource "aws_service_discovery_service" "rabbitmq" {
  name = "rabbitmq"

  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.this.id
    routing_policy = "MULTIVALUE"
    dns_records {
      type = "A"
      ttl  = 10
    }
  }
}

resource "aws_ecs_service" "rabbitmq" {
  name                   = "rabbitmq"
  cluster                = aws_ecs_cluster.this.arn
  task_definition        = aws_ecs_task_definition.rabbitmq.arn
  desired_count          = var.rabbitmq_desired_count
  enable_execute_command = true
  propagate_tags         = "SERVICE"

  # Always on-demand: a Spot interruption would drop queued messages
  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }

  # Stop the old broker before starting the new one: two brokers would
  # each hold half of the consumers
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.rabbitmq.id]
    assign_public_ip = true
  }

  service_registries {
    registry_arn = aws_service_discovery_service.rabbitmq.arn
  }

  depends_on = [aws_ecs_cluster_capacity_providers.this]
}
