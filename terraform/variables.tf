# =============================================================================
# GENERAL VARIABLES
# =============================================================================

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string

  validation {
    condition     = contains(["local", "dev", "staging", "prod"], var.environment)
    error_message = "Environment must be one of: local, dev, staging, prod"
  }
}

variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
  default     = "darwin"
}

# =============================================================================
# VPC VARIABLES
# =============================================================================

variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of availability zones"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

variable "enable_nat_gateway" {
  description = "Enable NAT Gateway for private subnet internet access"
  type        = bool
  default     = true
}

variable "single_nat_gateway" {
  description = "Use single NAT Gateway (cost saving for non-prod)"
  type        = bool
  default     = true
}

variable "enable_vpc_endpoints" {
  description = "Enable VPC endpoints for AWS services"
  type        = bool
  default     = true
}

# =============================================================================
# EKS VARIABLES
# =============================================================================

variable "eks_cluster_version" {
  description = "Kubernetes version for EKS cluster"
  type        = string
  default     = "1.29"
}

variable "eks_node_instance_types" {
  description = "Instance types for EKS general node group"
  type        = list(string)
  default     = ["t3.large"]
}

variable "eks_node_min_size" {
  description = "Minimum number of nodes in general node group"
  type        = number
  default     = 2
}

variable "eks_node_max_size" {
  description = "Maximum number of nodes in general node group"
  type        = number
  default     = 5
}

variable "eks_node_desired_size" {
  description = "Desired number of nodes in general node group"
  type        = number
  default     = 2
}

variable "enable_compute_node_group" {
  description = "Enable dedicated node group for ML compute workloads"
  type        = bool
  default     = false
}

variable "compute_node_instance_types" {
  description = "Instance types for compute node group"
  type        = list(string)
  default     = ["m5.xlarge"]
}

# =============================================================================
# RDS VARIABLES
# =============================================================================

variable "rds_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.medium"
}

variable "rds_allocated_storage" {
  description = "Allocated storage in GB"
  type        = number
  default     = 20
}

variable "rds_max_allocated_storage" {
  description = "Maximum allocated storage for autoscaling"
  type        = number
  default     = 100
}

variable "rds_multi_az" {
  description = "Enable Multi-AZ deployment"
  type        = bool
  default     = false
}

variable "rds_backup_retention_period" {
  description = "Backup retention period in days"
  type        = number
  default     = 7
}

variable "rds_deletion_protection" {
  description = "Enable deletion protection"
  type        = bool
  default     = false
}

# =============================================================================
# OPENSEARCH VARIABLES
# =============================================================================

variable "opensearch_instance_type" {
  description = "OpenSearch instance type"
  type        = string
  default     = "t3.small.search"
}

variable "opensearch_instance_count" {
  description = "Number of OpenSearch instances"
  type        = number
  default     = 1
}

variable "opensearch_ebs_volume_size" {
  description = "EBS volume size for OpenSearch in GB"
  type        = number
  default     = 20
}

variable "opensearch_engine_version" {
  description = "OpenSearch engine version"
  type        = string
  default     = "OpenSearch_2.11"
}

# =============================================================================
# ECR VARIABLES
# =============================================================================

variable "ecr_repositories" {
  description = "List of ECR repository names to create"
  type        = list(string)
  default = [
    "darwin-mlflow",
    "darwin-mlflow-app",
    "darwin-compute",
    "darwin-cluster-manager",
    "ml-serve-app",
    "artifact-builder",
    "darwin-catalog",
    "darwin-ofs-v2",
    "darwin-ofs-v2-admin",
    "darwin-ofs-v2-consumer",
    "chronos",
    "darwin-workspace",
    "ray",
    "serve-md-runtime"
  ]
}

variable "ecr_image_retention_count" {
  description = "Number of images to retain per repository"
  type        = number
  default     = 10
}

# =============================================================================
# S3 VARIABLES
# =============================================================================

variable "s3_force_destroy" {
  description = "Allow bucket deletion even with objects (for dev/test)"
  type        = bool
  default     = false
}

variable "s3_enable_versioning" {
  description = "Enable versioning on S3 buckets"
  type        = bool
  default     = true
}

# =============================================================================
# FEATURE FLAGS
# =============================================================================

variable "create_rds" {
  description = "Create RDS MySQL instance"
  type        = bool
  default     = true
}

variable "create_opensearch" {
  description = "Create OpenSearch domain"
  type        = bool
  default     = true
}

variable "create_ecr" {
  description = "Create ECR repositories"
  type        = bool
  default     = true
}

