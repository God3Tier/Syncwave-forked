output "ecr_repository_url" {
  value = aws_ecr_repository.this.repository_url
}

output "api_url" {
  value = "${local.platform.base_url}/api/waveform"
}

output "ecs_services" {
  description = "Must match ECS_SERVICES in services/waveform/.gitlab-ci.yml"
  value       = [module.api.service_name, module.worker.service_name]
}

output "db_init_command" {
  description = "Run once after the first apply (RUNBOOK.md)."
  value       = module.db.db_init_command
}

output "db_init_log_group" {
  value = module.db.db_init_log_group
}
