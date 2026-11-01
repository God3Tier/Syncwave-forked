variable "name" {
  description = "ECS service name, e.g. \"lyrics\" or \"lyrics-worker\". The task definition family is syncwave-<name> (ci/scripts/deploy-ecs.sh relies on this)."
  type        = string
}

variable "image" {
  description = "Image for the first task definition revision. Later revisions get their image from the CI deploy job."
  type        = string
}

variable "command" {
  description = "Overrides the image's CMD, e.g. [\"python\", \"-m\", \"lyrics_service.worker\"]. Null keeps the image's CMD."
  type        = list(string)
  default     = null
}

variable "cpu" {
  description = "Fargate task CPU units (256 = 0.25 vCPU)."
  type        = number
  default     = 256
}

variable "memory" {
  description = "Fargate task memory in MiB."
  type        = number
  default     = 512
}

variable "environment" {
  description = "Plain environment variables."
  type        = map(string)
  default     = {}
}

variable "secrets" {
  description = "Environment variables injected from Secrets Manager: name -> secret ARN, or \"<arn>:<json key>::\" for one key of a JSON secret."
  type        = map(string)
  default     = {}
}

variable "task_role_policy_json" {
  description = "Extra IAM policy for the task role (what the application itself may call). Null for none."
  type        = string
  default     = null
}

variable "desired_count" {
  description = "Number of tasks. 0 parks the service between demos."
  type        = number
  default     = 1
}

variable "capacity_provider" {
  description = "FARGATE, or FARGATE_SPOT (about 70% cheaper; tasks can be stopped with a 2-minute warning)."
  type        = string
  default     = "FARGATE"

  validation {
    condition     = contains(["FARGATE", "FARGATE_SPOT"], var.capacity_provider)
    error_message = "capacity_provider must be FARGATE or FARGATE_SPOT."
  }
}

variable "stop_timeout" {
  description = "Seconds between SIGTERM and SIGKILL (Fargate maximum 120)."
  type        = number
  default     = 30
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "cluster_arn" {
  type = string
}

variable "execution_role_arn" {
  description = "Role ECS uses to pull the image, write logs and read the secrets."
  type        = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "security_group_ids" {
  type = list(string)
}

variable "assign_public_ip" {
  description = "True in public subnets without a NAT gateway: the task needs it to reach ECR, Secrets Manager and CloudWatch."
  type        = bool
  default     = true
}

variable "http_route" {
  description = "Routes <path_prefix>/* on the shared ALB listener to this service's port 8080, with the prefix stripped (like infrastructure/gateway/nginx.conf). Null for workers."
  type = object({
    listener_arn = string
    vpc_id       = string
    path_prefix  = string
    priority     = number
  })
  default = null
}
