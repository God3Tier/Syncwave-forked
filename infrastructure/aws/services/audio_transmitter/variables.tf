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

variable "s3_read_prefixes" {
  description = "Object key prefixes the service may read. Upload writes the audio to audio/<song_id><ext>."
  type        = list(string)
  default     = ["audio/"]
}

variable "catalogue_timeout_seconds" {
  type    = number
  default = 3
}

variable "route_priority" {
  description = "ALB listener rule priority; unique per service (README.md table)."
  type        = number
  default     = 30
}

variable "cpu" {
  type    = number
  default = 256
}

variable "memory" {
  description = "The service caches whole songs in memory (capped by count, not bytes), so it gets more than the 512 MiB default."
  type        = number
  default     = 1024
}

variable "desired_count" {
  type    = number
  default = 1
}
