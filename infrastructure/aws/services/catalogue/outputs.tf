output "ecr_repository_url" {
  value = aws_ecr_repository.this.repository_url
}

output "api_url" {
  value = "${local.platform.base_url}/api/catalogue"
}

output "ecs_services" {
  description = "Must match ECS_SERVICES in services/catalogue/.gitlab-ci.yml"
  value       = [module.api.service_name, module.worker.service_name]
}

output "http_url" {
  description = "What Search, Playlist, Recommendation and Streaming set as CATALOGUE_URL."
  value       = "http://catalogue.${local.platform.service_discovery_namespace}:8080"
}

output "grpc_target" {
  description = "What Sync sets as CATALOGUE_GRPC_TARGET."
  value       = "catalogue.${local.platform.service_discovery_namespace}:50051"
}

output "internal_token_secret_arn" {
  description = "Secret Sync reads as CATALOGUE_INTERNAL_TOKEN (x-internal-token for GetSong)."
  value       = aws_secretsmanager_secret.internal_token.arn
}

output "db_init_command" {
  description = "Run once per session, after module.db is applied (RUNBOOK.md §2.3b)."
  value       = module.db.db_init_command
}

output "db_init_log_group" {
  value = module.db.db_init_log_group
}
