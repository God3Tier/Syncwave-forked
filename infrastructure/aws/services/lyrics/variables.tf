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

variable "s3_read_prefixes" {
  description = "Object key prefixes the worker may read. The SongUploaded contract gives lyrics/<song_id>.lrc only as an example; confirm with the Upload owner."
  type        = list(string)
  default     = ["lyrics/"]
}

variable "lyrics_max_bytes" {
  description = "Larger .lrc files are rejected (LYRICS_TOO_LARGE)."
  type        = number
  default     = 262144
}

variable "amqp_prefetch" {
  description = "Unacknowledged messages one worker processes at a time."
  type        = number
  default     = 10
}

variable "api_route_priority" {
  description = "ALB listener rule priority; unique per service (README.md table)."
  type        = number
  default     = 50
}

variable "api_cpu" {
  type    = number
  default = 256
}

variable "api_memory" {
  type    = number
  default = 512
}

variable "api_desired_count" {
  type    = number
  default = 1
}

variable "worker_cpu" {
  type    = number
  default = 256
}

variable "worker_memory" {
  type    = number
  default = 512
}

variable "worker_desired_count" {
  type    = number
  default = 1
}

variable "worker_capacity_provider" {
  description = "FARGATE_SPOT is safe for the worker: an interrupted message is redelivered and processing is idempotent."
  type        = string
  default     = "FARGATE_SPOT"
}
