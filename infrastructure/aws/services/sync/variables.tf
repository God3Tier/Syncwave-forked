variable "region" {
  description = "Must match the platform stack's region."
  type        = string
  default     = "ap-southeast-1"
}

variable "image_tag" {
  description = "Image tag in ECR for the task definitions Terraform registers. CI deploys replace it with the content-hash tag they push."
  type        = string
  default     = "main"
}

variable "log_level" {
  type    = string
  default = "INFO"
}

variable "dependency_timeout_ms" {
  description = "Timeout for each call to the Catalogue and Streaming Services."
  type        = number
  default     = 750
}

variable "streaming_enabled" {
  description = "Call the Streaming Service at streaming.syncwave.internal:8081. Set false when its stack (services/audio_transmitter) is not brought up; Sync then uses its built-in fake."
  type        = bool
  default     = true
}

variable "participant_token" {
  description = "MOCK_SYNC_TOKEN. Must equal the VITE_SYNC_PARTICIPANT_TOKEN the frontend image was built with (frontend/src/config.ts default)."
  type        = string
  default     = "local-sync-participant-token"
}

variable "route_priority" {
  description = "ALB listener rule priority; unique per service (README.md table). The rule blocking /api/sync/internal/* uses this minus 1."
  type        = number
  default     = 100
}

variable "cpu" {
  type    = number
  default = 256
}

variable "memory" {
  type    = number
  default = 512
}

variable "desired_count" {
  description = "0 or 1. WebSockets and timing state live in one process; a second task would split the participants."
  type        = number
  default     = 1

  validation {
    condition     = contains([0, 1], var.desired_count)
    error_message = "desired_count must be 0 or 1."
  }
}
