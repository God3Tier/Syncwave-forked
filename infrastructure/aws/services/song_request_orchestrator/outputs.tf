output "ecr_repository_url" {
  value = aws_ecr_repository.this.repository_url
}

output "api_url" {
  value = "${local.platform.base_url}/api/orchestrator"
}

output "ecs_services" {
  description = "Must match ECS_SERVICES in services/song_request_orchestrator/.gitlab-ci.yml"
  value       = [module.api.service_name]
}

output "db_init_command" {
  description = "Run once per session, after module.db is applied (RUNBOOK.md §2.3b)."
  value       = module.db.db_init_command
}

output "db_init_log_group" {
  value = module.db.db_init_log_group
}
