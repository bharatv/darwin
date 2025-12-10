# =============================================================================
# LOCAL ENVIRONMENT - LOCALSTACK PROVIDER CONFIGURATION
# =============================================================================
# This configuration points Terraform to LocalStack for local testing
# of S3, ECR, IAM, and Secrets Manager modules.
# =============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  access_key = "test"
  secret_key = "test"
  region     = var.aws_region

  # LocalStack endpoints
  endpoints {
    s3             = "http://localhost:4566"
    ecr            = "http://localhost:4566"
    iam            = "http://localhost:4566"
    secretsmanager = "http://localhost:4566"
    sts            = "http://localhost:4566"
    dynamodb       = "http://localhost:4566"
  }

  # Skip AWS credential validation for LocalStack
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true

  s3_use_path_style = true

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
      Testing     = "localstack"
    }
  }
}


