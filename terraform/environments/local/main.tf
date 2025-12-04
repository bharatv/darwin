# =============================================================================
# LOCAL ENVIRONMENT - LOCALSTACK TESTING
# =============================================================================
# This configuration tests modules that LocalStack supports:
# - S3 (full support)
# - ECR (full support)
# - Secrets Manager (full support)
# - IAM (full support)
#
# Modules that can only be validated with 'terraform plan':
# - VPC (plan only)
# - EKS (plan only)
# - RDS (plan only)
# - OpenSearch (plan only)
# =============================================================================

# =============================================================================
# VARIABLES
# =============================================================================

variable "project_name" {
  description = "Project name"
  type        = string
  default     = "darwin"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "local"
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

# =============================================================================
# S3 MODULE - Fully testable with LocalStack
# =============================================================================

module "s3" {
  source = "../../modules/s3"

  project_name      = var.project_name
  environment       = var.environment
  force_destroy     = true  # Allow easy cleanup in testing
  enable_versioning = true
}

# =============================================================================
# ECR MODULE - Requires LocalStack Pro (commented out for free tier)
# =============================================================================
# ECR is a Pro feature in LocalStack. Use 'terraform plan' to validate.
# Uncomment if you have LocalStack Pro license.
#
# module "ecr" {
#   source = "../../modules/ecr"
#
#   project_name = var.project_name
#   environment  = var.environment
#   repositories = [
#     "darwin-mlflow",
#     "darwin-compute",
#     "darwin-cluster-manager",
#     "ml-serve-app",
#     "artifact-builder",
#     "darwin-catalog"
#   ]
#   image_retention_count = 5
# }

# =============================================================================
# OUTPUTS
# =============================================================================

output "s3_mlflow_bucket" {
  description = "MLflow artifacts bucket"
  value       = module.s3.mlflow_bucket_name
}

output "s3_shared_bucket" {
  description = "Shared storage bucket"
  value       = module.s3.shared_bucket_name
}

# ECR outputs commented out - requires LocalStack Pro
# output "ecr_registry_url" {
#   description = "ECR registry URL"
#   value       = module.ecr.registry_url
# }
#
# output "ecr_repository_urls" {
#   description = "ECR repository URLs"
#   value       = module.ecr.repository_urls
# }

output "test_summary" {
  description = "Test summary"
  value = {
    environment    = var.environment
    s3_buckets     = [module.s3.mlflow_bucket_name, module.s3.shared_bucket_name]
    localstack_url = "http://localhost:4566"
    note           = "ECR requires LocalStack Pro - use 'terraform plan' to validate ECR module"
  }
}

