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
  default     = 120
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
  description = "Tasks behind the ALB. Every task loads the same signing key from Secrets Manager, so more than one is safe."
  type        = number
  default     = 1
}
