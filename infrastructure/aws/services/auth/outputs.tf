output "ecr_repository_url" {
  value = aws_ecr_repository.this.repository_url
}

output "api_url" {
  value = "${local.platform.base_url}/api/auth"
}

output "ecs_services" {
  description = "Must match ECS_SERVICES in services/auth/.gitlab-ci.yml (unset there, so the service name)."
  value       = [module.api.service_name]
}

output "jwks_url" {
  description = "What Upload, Playlist, Jam and the orchestrator set as AUTH_JWKS_URL."
  value       = "http://auth.${local.platform.service_discovery_namespace}:8080/.well-known/jwks.json"
}

output "db_init_command" {
  description = "Run once per session, after module.db is applied (RUNBOOK.md §2.3b)."
  value       = module.db.db_init_command
}

output "db_init_log_group" {
  value = module.db.db_init_log_group
}
