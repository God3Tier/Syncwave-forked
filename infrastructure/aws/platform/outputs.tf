# Read by the service stacks through terraform_remote_state. Renaming or
# removing an output breaks every service stack that uses it.

output "region" {
  value = var.region
}

output "account_id" {
  value = data.aws_caller_identity.current.account_id
}

output "vpc_id" {
  value = aws_vpc.this.id
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "services_security_group_id" {
  description = "Security group for every application task; allowed into RDS and RabbitMQ."
  value       = aws_security_group.services.id
}

output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "cluster_arn" {
  value = aws_ecs_cluster.this.arn
}

output "execution_role_arn" {
  value = aws_iam_role.execution.arn
}

output "service_discovery_namespace" {
  value = aws_service_discovery_private_dns_namespace.this.name
}

output "service_discovery_namespace_id" {
  description = "For a service that other services call by name (modules/ecs-service service_discovery)."
  value       = aws_service_discovery_private_dns_namespace.this.id
}

output "alb_dns_name" {
  value = aws_lb.this.dns_name
}

output "alb_listener_arn" {
  description = "The listener service routes attach to (HTTPS when a certificate is set)."
  value       = local.app_listener_arn
}

output "base_url" {
  value = "${local.https ? "https" : "http"}://${aws_lb.this.dns_name}"
}

output "audio_bucket_name" {
  value = aws_s3_bucket.audio.bucket
}

output "audio_bucket_arn" {
  value = aws_s3_bucket.audio.arn
}

output "db_address" {
  value = aws_db_instance.this.address
}

output "db_port" {
  value = aws_db_instance.this.port
}

output "db_master_username" {
  value = aws_db_instance.this.username
}

output "db_master_secret_arn" {
  value = aws_db_instance.this.master_user_secret[0].secret_arn
}

output "rabbitmq_host" {
  value = "${aws_service_discovery_service.rabbitmq.name}.${aws_service_discovery_private_dns_namespace.this.name}"
}

output "rabbitmq_port" {
  value = 5672
}

output "rabbitmq_user" {
  value = local.rabbitmq_user
}

output "rabbitmq_password_secret_arn" {
  value = aws_secretsmanager_secret.rabbitmq.arn
}

output "gitlab_deploy_role_arn" {
  description = "GitLab CI/CD variable AWS_ROLE_ARN"
  value       = aws_iam_role.gitlab_deploy.arn
}

output "ecr_registry" {
  description = "GitLab CI/CD variable ECR_REGISTRY"
  value       = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.region}.amazonaws.com"
}
