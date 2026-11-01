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

variable "catalogue_mode" {
  description = "How the Playlist Service checks that a song exists: \"http\" asks the Catalogue Service, \"off\" accepts any song id (services/playlist/README.md). Use \"off\" while the Catalogue stack is not deployed."
  type        = string
  default     = "http"

  validation {
    condition     = contains(["http", "off"], var.catalogue_mode)
    error_message = "catalogue_mode must be http or off."
  }
}

variable "catalogue_timeout_seconds" {
  type    = number
  default = 3
}

variable "api_route_priority" {
  description = "ALB listener rule priority; unique per service (README.md table)."
  type        = number
  default     = 70
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
