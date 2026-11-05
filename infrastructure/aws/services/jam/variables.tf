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

variable "sync_timeout_ms" {
  type    = number
  default = 1000
}

variable "playlist_timeout_ms" {
  type    = number
  default = 750
}

variable "member_token" {
  description = "MOCK_JAM_TOKEN. Must equal the VITE_JAM_MEMBER_TOKEN the frontend image was built with (frontend/src/config.ts default)."
  type        = string
  default     = "local-jam-member-token"
}

variable "route_priority" {
  description = "ALB listener rule priority; unique per service (README.md table)."
  type        = number
  default     = 90
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
  description = "0 or 1. Rooms and WebSocket connections live in one process; a second task would miss broadcasts."
  type        = number
  default     = 1

  validation {
    condition     = contains([0, 1], var.desired_count)
    error_message = "desired_count must be 0 or 1."
  }
}
