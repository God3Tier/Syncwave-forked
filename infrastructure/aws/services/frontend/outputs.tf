output "ecr_repository_url" {
  value = aws_ecr_repository.this.repository_url
}

output "api_url" {
  description = "The web UI (named api_url like the other stacks, which the runbook prints)."
  value       = "${local.platform.base_url}/"
}

output "ecs_services" {
  description = "Must match ECS_SERVICES in frontend/.gitlab-ci.yml (unset there, so the service name)."
  value       = [module.web.service_name]
}
