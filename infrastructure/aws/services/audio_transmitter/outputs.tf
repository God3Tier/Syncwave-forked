output "ecr_repository_url" {
  value = aws_ecr_repository.this.repository_url
}

output "api_url" {
  value = "${local.platform.base_url}/api/streaming"
}

output "ecs_services" {
  description = "Must match ECS_SERVICES in services/audio_transmitter/.gitlab-ci.yml"
  value       = [module.streaming.service_name]
}

output "http_url" {
  description = "What Sync sets as STREAMING_HTTP_URL and the orchestrator as AUDIO_SERVICE_URL."
  value       = "http://streaming.${local.platform.service_discovery_namespace}:8081"
}
