output "ecr_repository_url" {
  value = aws_ecr_repository.this.repository_url
}

output "api_url" {
  value = "${local.platform.base_url}/api/playlist"
}

output "ecs_services" {
  description = "Must match ECS_SERVICES in services/playlist/.gitlab-ci.yml (unset there, so the service name)."
  value       = [module.api.service_name]
}

output "grpc_target" {
  description = "What Jam sets as PLAYLIST_GRPC_TARGET."
  value       = "playlist.${local.platform.service_discovery_namespace}:50051"
}

output "internal_token_secret_arn" {
  description = "Secret Jam reads as PLAYLIST_INTERNAL_TOKEN (x-internal-token for GetPlaylist)."
  value       = aws_secretsmanager_secret.internal_token.arn
}

output "db_init_command" {
  description = "Run once per session, after module.db is applied (RUNBOOK.md §2.3b)."
  value       = module.db.db_init_command
}

output "db_init_log_group" {
  value = module.db.db_init_log_group
}
