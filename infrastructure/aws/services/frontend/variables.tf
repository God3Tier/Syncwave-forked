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
  description = "Must be the highest-numbered rule on the listener (evaluated last), and above the platform's /api/* 404 rule (900)."
  type        = number
  default     = 1000

  validation {
    condition     = var.route_priority > 900
    error_message = "route_priority must be above 900, or unknown /api paths would get the frontend instead of a 404."
  }
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
  type    = number
  default = 1
}
