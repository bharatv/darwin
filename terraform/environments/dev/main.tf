# =============================================================================
# DEV ENVIRONMENT - AWS DEPLOYMENT
# =============================================================================

terraform {
  required_version = ">= 1.5.0"

  # Uncomment to use S3 backend for state
  # backend "s3" {
  #   bucket         = "darwin-dev-terraform-state"
  #   key            = "terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "darwin-dev-terraform-lock"
  #   encrypt        = true
  # }
}

module "darwin" {
  source = "../../"

  # General
  environment  = var.environment
  project_name = var.project_name
  aws_region   = var.aws_region

  # VPC
  vpc_cidr             = var.vpc_cidr
  availability_zones   = var.availability_zones
  enable_nat_gateway   = var.enable_nat_gateway
  single_nat_gateway   = var.single_nat_gateway
  enable_vpc_endpoints = var.enable_vpc_endpoints

  # EKS
  eks_cluster_version         = var.eks_cluster_version
  eks_node_instance_types     = var.eks_node_instance_types
  eks_node_min_size           = var.eks_node_min_size
  eks_node_max_size           = var.eks_node_max_size
  eks_node_desired_size       = var.eks_node_desired_size
  enable_compute_node_group   = var.enable_compute_node_group
  compute_node_instance_types = var.compute_node_instance_types

  # ECR
  create_ecr            = var.create_ecr
  ecr_repositories      = var.ecr_repositories
  ecr_image_retention_count = var.ecr_image_retention_count

  # RDS
  create_rds                  = var.create_rds
  rds_instance_class          = var.rds_instance_class
  rds_allocated_storage       = var.rds_allocated_storage
  rds_max_allocated_storage   = var.rds_max_allocated_storage
  rds_multi_az                = var.rds_multi_az
  rds_backup_retention_period = var.rds_backup_retention_period
  rds_deletion_protection     = var.rds_deletion_protection

  # S3
  s3_force_destroy     = var.s3_force_destroy
  s3_enable_versioning = var.s3_enable_versioning

  # OpenSearch
  create_opensearch        = var.create_opensearch
  opensearch_instance_type = var.opensearch_instance_type
  opensearch_instance_count = var.opensearch_instance_count
  opensearch_ebs_volume_size = var.opensearch_ebs_volume_size
  opensearch_engine_version = var.opensearch_engine_version
}

# =============================================================================
# OUTPUTS
# =============================================================================

output "vpc_id" {
  value = module.darwin.vpc_id
}

output "eks_cluster_name" {
  value = module.darwin.eks_cluster_name
}

output "eks_cluster_endpoint" {
  value = module.darwin.eks_cluster_endpoint
}

output "ecr_registry_url" {
  value = module.darwin.ecr_registry_url
}

output "rds_endpoint" {
  value = module.darwin.rds_endpoint
}

output "s3_mlflow_bucket" {
  value = module.darwin.s3_mlflow_bucket
}

output "opensearch_endpoint" {
  value = module.darwin.opensearch_endpoint
}

output "helm_values" {
  value     = module.darwin.helm_values
  sensitive = true
}

output "kubeconfig_command" {
  value = module.darwin.kubeconfig_command
}


