# =============================================================================
# DARWIN PLATFORM - ROOT TERRAFORM CONFIGURATION
# =============================================================================
# This module composes all child modules to create the complete
# AWS infrastructure for the Darwin ML Platform.
# =============================================================================

# =============================================================================
# VPC MODULE
# =============================================================================

module "vpc" {
  source = "./modules/vpc"

  project_name       = var.project_name
  environment        = var.environment
  aws_region         = var.aws_region
  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones

  enable_nat_gateway   = var.enable_nat_gateway
  single_nat_gateway   = var.single_nat_gateway
  enable_vpc_endpoints = var.enable_vpc_endpoints
}

# =============================================================================
# EKS MODULE
# =============================================================================

module "eks" {
  source = "./modules/eks"

  project_name       = var.project_name
  environment        = var.environment
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids

  cluster_version     = var.eks_cluster_version
  node_instance_types = var.eks_node_instance_types
  node_min_size       = var.eks_node_min_size
  node_max_size       = var.eks_node_max_size
  node_desired_size   = var.eks_node_desired_size

  enable_compute_node_group   = var.enable_compute_node_group
  compute_node_instance_types = var.compute_node_instance_types
}

# =============================================================================
# ECR MODULE
# =============================================================================

module "ecr" {
  count  = var.create_ecr ? 1 : 0
  source = "./modules/ecr"

  project_name          = var.project_name
  environment           = var.environment
  repositories          = var.ecr_repositories
  image_retention_count = var.ecr_image_retention_count
}

# =============================================================================
# RDS MODULE
# =============================================================================

module "rds" {
  count  = var.create_rds ? 1 : 0
  source = "./modules/rds"

  project_name = var.project_name
  environment  = var.environment
  vpc_id       = module.vpc.vpc_id
  subnet_ids   = module.vpc.private_subnet_ids

  allowed_security_groups = [module.eks.node_security_group_id]

  instance_class          = var.rds_instance_class
  allocated_storage       = var.rds_allocated_storage
  max_allocated_storage   = var.rds_max_allocated_storage
  multi_az                = var.rds_multi_az
  backup_retention_period = var.rds_backup_retention_period
  deletion_protection     = var.rds_deletion_protection
}

# =============================================================================
# S3 MODULE
# =============================================================================

module "s3" {
  source = "./modules/s3"

  project_name      = var.project_name
  environment       = var.environment
  force_destroy     = var.s3_force_destroy
  enable_versioning = var.s3_enable_versioning
}

# =============================================================================
# OPENSEARCH MODULE
# =============================================================================

module "opensearch" {
  count  = var.create_opensearch ? 1 : 0
  source = "./modules/opensearch"

  project_name = var.project_name
  environment  = var.environment
  vpc_id       = module.vpc.vpc_id
  subnet_ids   = module.vpc.private_subnet_ids

  allowed_security_groups = [module.eks.node_security_group_id]

  instance_type   = var.opensearch_instance_type
  instance_count  = var.opensearch_instance_count
  ebs_volume_size = var.opensearch_ebs_volume_size
  engine_version  = var.opensearch_engine_version
}


