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

variable "route_priority" {
  description = "ALB listener rule priority; unique per service (README.md table)."
  type        = number
  default     = 110
}

variable "cpu" {
  type    = number
  default = 512
}

variable "memory" {
  description = "Responses carry base64 audio chunks, and each playback session buffers several songs."
  type        = number
  default     = 1024
}

variable "desired_count" {
  description = "0 or 1. Playback sessions live in one process; a second task would not know another task's sessions."
  type        = number
  default     = 1

  validation {
    condition     = contains([0, 1], var.desired_count)
    error_message = "desired_count must be 0 or 1."
  }
}
