variable "region" {
  type    = string
  default = "ap-southeast-1"
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

variable "cluster_name" {
  description = "ECS cluster; the GitLab CI variable ECS_CLUSTER must match."
  type        = string
  default     = "syncwave"
}

variable "certificate_arn" {
  description = "ACM certificate for HTTPS on the ALB. Null serves plain HTTP on port 80 only."
  type        = string
  default     = null
}

# --- Postgres -------------------------------------------------------------

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "db_engine_version" {
  description = "Major version only; RDS picks the current minor (local Compose runs postgres:17)."
  type        = string
  default     = "17"
}

variable "db_allocated_storage" {
  description = "GiB of gp3 storage."
  type        = number
  default     = 20
}

variable "db_deletion_protection" {
  description = "Set true once the data matters; terraform destroy then refuses to delete the instance."
  type        = bool
  default     = false
}

# --- RabbitMQ -------------------------------------------------------------

variable "rabbitmq_image" {
  description = "Same broker as docker-compose.yml, from the ECR Public mirror of Docker Hub's official images (no anonymous pull limits)."
  type        = string
  default     = "public.ecr.aws/docker/library/rabbitmq:4.3-management-alpine"
}

variable "rabbitmq_init_image" {
  description = "Loads infrastructure/rabbitmq/definitions.json, as rabbitmq-init does in docker-compose.yml."
  type        = string
  default     = "curlimages/curl:8.22.0"
}

variable "rabbitmq_desired_count" {
  description = "0 or 1. Never more: queues would be split across unrelated brokers."
  type        = number
  default     = 1

  validation {
    condition     = contains([0, 1], var.rabbitmq_desired_count)
    error_message = "rabbitmq_desired_count must be 0 or 1."
  }
}

# --- S3 -------------------------------------------------------------------

variable "audio_bucket_force_destroy" {
  description = "Let terraform destroy delete the audio bucket even when it still holds objects. Set true only for a final teardown."
  type        = bool
  default     = false
}

# --- GitLab deploys -------------------------------------------------------

variable "gitlab_project_path" {
  type    = string
  default = "cs302-2026/g4-team6/syncwave"
}

variable "gitlab_deploy_branch" {
  description = "Only pipelines on this branch can assume the deploy role."
  type        = string
  default     = "main"
}

variable "create_gitlab_oidc_provider" {
  description = "An account holds one OIDC provider per URL. Set false if https://gitlab.com is already registered; the existing one is then looked up."
  type        = bool
  default     = true
}
