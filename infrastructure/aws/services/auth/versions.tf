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
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.1"
    }
  }

  # bucket/region/locking come from ../../backend.hcl (RUNBOOK.md step 2.1)
  backend "s3" {
    key = "services/auth/terraform.tfstate"
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "syncwave"
      Stack     = "auth"
      Service   = "auth"
      ManagedBy = "terraform"
    }
  }
}
