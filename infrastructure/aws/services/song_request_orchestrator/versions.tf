terraform {
  required_version = ">= 1.16"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.71"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.9"
    }
  }

  # bucket/region/locking come from ../../backend.hcl (RUNBOOK.md step 2.1)
  backend "s3" {
    key = "services/song_request_orchestrator/terraform.tfstate"
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "syncwave"
      Stack     = "song_request_orchestrator"
      Service   = "song_request_orchestrator"
      ManagedBy = "terraform"
    }
  }
}
