output "ecr_repository_url" {
  value = aws_ecr_repository.this.repository_url
}

output "api_url" {
  value = "${local.platform.base_url}/api/jam"
}

output "ecs_services" {
  description = "Must match ECS_SERVICES in services/jam/.gitlab-ci.yml (unset there, so the service name)."
  value       = [module.api.service_name]
}

output "dependencies" {
  description = "Which of Sync and Playlist Jam calls for real (\"grpc\") or fakes (\"fake\": that stack was not found)."
  value = {
    sync     = local.sync.grpc_target == "" ? "fake" : "grpc"
    playlist = local.playlist.grpc_target == "" ? "fake" : "grpc"
  }
}

output "db_init_command" {
  description = "Run once per session, after module.db is applied (RUNBOOK.md §2.3b)."
  value       = module.db.db_init_command
}

output "db_init_log_group" {
  value = module.db.db_init_log_group
}
