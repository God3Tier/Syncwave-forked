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
  description = "Where candidate songs come from: \"http\" reads the Catalogue Service, \"stub\" uses the built-in demo songs (services/recommendation/README.md). Use \"stub\" while the Catalogue stack is not deployed."
  type        = string
  default     = "http"

  validation {
    condition     = contains(["http", "stub"], var.catalogue_mode)
    error_message = "catalogue_mode must be http or stub."
  }
}

variable "catalogue_timeout_seconds" {
  type    = number
  default = 3
}

variable "candidate_limit" {
  description = "How many Catalogue songs are ranked."
  type        = number
  default     = 100
}

variable "weather_mode" {
  description = "open-meteo (live weather, no key needed), stub, or off."
  type        = string
  default     = "open-meteo"

  validation {
    condition     = contains(["open-meteo", "stub", "off"], var.weather_mode)
    error_message = "weather_mode must be open-meteo, stub or off."
  }
}

variable "weather_timeout_seconds" {
  description = "Past this the response is built without weather."
  type        = number
  default     = 2
}

variable "api_route_priority" {
  description = "ALB listener rule priority; unique per service (README.md table)."
  type        = number
  default     = 80
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
