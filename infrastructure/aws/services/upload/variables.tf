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

variable "s3_write_prefixes" {
  description = "Object key prefixes the API writes (services/upload: audio/<song_id><ext>, lyrics/<song_id>.lrc). Lyrics and Waveform read the same prefixes."
  type        = list(string)
  default     = ["audio/", "lyrics/"]
}

variable "max_audio_bytes" {
  description = "Larger audio files are rejected. The ALB has no body size limit, so this is the only one."
  type        = number
  default     = 199229440 # 190 MiB, as in services/upload/compose.yaml
}

variable "max_lyrics_bytes" {
  type    = number
  default = 262144
}

variable "publish_poll_seconds" {
  description = "How often the publisher polls the outbox."
  type        = number
  default     = 2
}

variable "api_route_priority" {
  description = "ALB listener rule priority; unique per service (README.md table)."
  type        = number
  default     = 40
}

variable "api_cpu" {
  description = "Uploads of up to 190 MiB are spooled to disk and streamed to S3."
  type        = number
  default     = 512
}

variable "api_memory" {
  type    = number
  default = 1024
}

variable "api_desired_count" {
  type    = number
  default = 1
}

variable "publisher_cpu" {
  type    = number
  default = 256
}

variable "publisher_memory" {
  type    = number
  default = 512
}

variable "publisher_desired_count" {
  type    = number
  default = 1
}

variable "publisher_capacity_provider" {
  description = "FARGATE_SPOT is safe: an interrupted publish is retried from the outbox."
  type        = string
  default     = "FARGATE_SPOT"
}
