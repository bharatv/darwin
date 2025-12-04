# =============================================================================
# DEV ENVIRONMENT VARIABLES
# =============================================================================

# General
variable "environment" {
  type    = string
  default = "dev"
}

variable "project_name" {
  type    = string
  default = "darwin"
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

# VPC
variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "availability_zones" {
  type    = list(string)
  default = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

variable "enable_nat_gateway" {
  type    = bool
  default = true
}

variable "single_nat_gateway" {
  type    = bool
  default = true
}

variable "enable_vpc_endpoints" {
  type    = bool
  default = true
}

# EKS
variable "eks_cluster_version" {
  type    = string
  default = "1.29"
}

variable "eks_node_instance_types" {
  type    = list(string)
  default = ["t3.large"]
}

variable "eks_node_min_size" {
  type    = number
  default = 2
}

variable "eks_node_max_size" {
  type    = number
  default = 5
}

variable "eks_node_desired_size" {
  type    = number
  default = 2
}

variable "enable_compute_node_group" {
  type    = bool
  default = false
}

variable "compute_node_instance_types" {
  type    = list(string)
  default = ["m5.xlarge"]
}

# ECR
variable "create_ecr" {
  type    = bool
  default = true
}

variable "ecr_repositories" {
  type = list(string)
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
  type    = number
  default = 10
}

# RDS
variable "create_rds" {
  type    = bool
  default = true
}

variable "rds_instance_class" {
  type    = string
  default = "db.t3.medium"
}

variable "rds_allocated_storage" {
  type    = number
  default = 20
}

variable "rds_max_allocated_storage" {
  type    = number
  default = 100
}

variable "rds_multi_az" {
  type    = bool
  default = false
}

variable "rds_backup_retention_period" {
  type    = number
  default = 7
}

variable "rds_deletion_protection" {
  type    = bool
  default = false
}

# S3
variable "s3_force_destroy" {
  type    = bool
  default = true  # Allow easy cleanup in dev
}

variable "s3_enable_versioning" {
  type    = bool
  default = true
}

# OpenSearch
variable "create_opensearch" {
  type    = bool
  default = true
}

variable "opensearch_instance_type" {
  type    = string
  default = "t3.small.search"
}

variable "opensearch_instance_count" {
  type    = number
  default = 1
}

variable "opensearch_ebs_volume_size" {
  type    = number
  default = 20
}

variable "opensearch_engine_version" {
  type    = string
  default = "OpenSearch_2.11"
}

