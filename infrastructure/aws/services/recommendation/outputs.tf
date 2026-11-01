output "ecr_repository_url" {
  value = aws_ecr_repository.this.repository_url
}

output "api_url" {
  value = "${local.platform.base_url}/api/recommendation"
}

output "ecs_services" {
  description = "Must match ECS_SERVICES in services/recommendation/.gitlab-ci.yml (unset there, so the service name)."
  value       = [module.api.service_name]
}
