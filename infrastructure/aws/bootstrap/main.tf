# Creates the S3 bucket that holds every other root's Terraform state.
# Applied first at the start of every session and destroyed last at the end
# (RUNBOOK.md §2.1 and §8). This root keeps its own state locally: it is a
# single bucket and can be re-imported if lost:
#   terraform import aws_s3_bucket.state syncwave-tfstate-<account id>

terraform {
  required_version = ">= 1.16"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.71"
    }
  }
}

variable "region" {
  description = "AWS region for the state bucket (and, by convention, everything else)."
  type        = string
  default     = "ap-southeast-1"
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "syncwave"
      Stack     = "bootstrap"
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

# The other roots derive this name from the account ID, so it must not change.
# force_destroy also deletes the old state versions. Destroy this only after
# the service and platform stacks, or their resources lose their state.
resource "aws_s3_bucket" "state" {
  bucket        = "syncwave-tfstate-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
}

# Versioning lets a corrupted or wrongly-applied state be rolled back.
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

output "state_bucket" {
  value = aws_s3_bucket.state.bucket
}

# Written to ../backend.hcl by the runbook; every other root initialises with it.
output "backend_hcl" {
  value = <<-EOT
    bucket       = "${aws_s3_bucket.state.bucket}"
    region       = "${var.region}"
    use_lockfile = true
    encrypt      = true
  EOT
}
