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
  description = "Object key prefixes the worker may read. The SongUploaded contract gives audio/<song_id>.mp3 only as an example; confirm with the Upload owner."
  type        = list(string)
  default     = ["audio/"]
}

variable "amqp_prefetch" {
  description = "Unacknowledged messages one worker processes at a time (decoding is CPU-heavy)."
  type        = number
  default     = 2
}

# Waveform generation settings, as in services/waveform/.env.example
variable "waveform_settings" {
  type = object({
    points          = number
    sample_rate     = number
    frame_rate      = number
    bands           = number
    max_audio_bytes = number
    decode_timeout  = number
  })
  default = {
    points          = 1000
    sample_rate     = 22050
    frame_rate      = 25
    bands           = 50
    max_audio_bytes = 209715200 # 200 MB, the gateway's upload limit
    decode_timeout  = 120
  }
}

variable "api_route_priority" {
  description = "ALB listener rule priority; unique per service (README.md table)."
  type        = number
  default     = 60
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
  description = "ffmpeg decoding and the FFT run here; 1 vCPU keeps a 4-minute song well inside the decode timeout."
  type        = number
  default     = 1024
}

variable "worker_memory" {
  type    = number
  default = 2048
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
