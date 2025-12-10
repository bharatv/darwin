# =============================================================================
# DARWIN PLATFORM - TERRAFORM OUTPUTS
# =============================================================================
# These outputs are used to generate Helm values and configure
# the Darwin platform for cloud deployment.
# =============================================================================

# =============================================================================
# VPC OUTPUTS
# =============================================================================

output "vpc_id" {
  description = "VPC ID"
  value       = module.vpc.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = module.vpc.private_subnet_ids
}

output "public_subnet_ids" {
  description = "Public subnet IDs"
  value       = module.vpc.public_subnet_ids
}

# =============================================================================
# EKS OUTPUTS
# =============================================================================

output "eks_cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  description = "EKS cluster endpoint"
  value       = module.eks.cluster_endpoint
}

output "eks_cluster_ca_certificate" {
  description = "EKS cluster CA certificate (base64)"
  value       = module.eks.cluster_ca_certificate
  sensitive   = true
}

output "eks_oidc_provider_arn" {
  description = "EKS OIDC provider ARN for IRSA"
  value       = module.eks.oidc_provider_arn
}

output "eks_s3_access_role_arn" {
  description = "IAM role ARN for S3 access from pods"
  value       = module.eks.s3_access_role_arn
}

output "eks_secrets_access_role_arn" {
  description = "IAM role ARN for Secrets Manager access from pods"
  value       = module.eks.secrets_access_role_arn
}

# =============================================================================
# ECR OUTPUTS
# =============================================================================

output "ecr_registry_url" {
  description = "ECR registry URL"
  value       = var.create_ecr ? module.ecr[0].registry_url : null
}

output "ecr_repository_urls" {
  description = "Map of ECR repository URLs"
  value       = var.create_ecr ? module.ecr[0].repository_urls : {}
}

# =============================================================================
# RDS OUTPUTS
# =============================================================================

output "rds_endpoint" {
  description = "RDS MySQL endpoint"
  value       = var.create_rds ? module.rds[0].endpoint : null
}

output "rds_port" {
  description = "RDS MySQL port"
  value       = var.create_rds ? module.rds[0].port : null
}

output "rds_database_name" {
  description = "RDS database name"
  value       = var.create_rds ? module.rds[0].database_name : null
}

output "rds_secret_arn" {
  description = "RDS credentials secret ARN"
  value       = var.create_rds ? module.rds[0].secret_arn : null
  sensitive   = true
}

# =============================================================================
# S3 OUTPUTS
# =============================================================================

output "s3_mlflow_bucket" {
  description = "MLflow artifacts S3 bucket name"
  value       = module.s3.mlflow_bucket_name
}

output "s3_shared_bucket" {
  description = "Shared storage S3 bucket name"
  value       = module.s3.shared_bucket_name
}

# =============================================================================
# OPENSEARCH OUTPUTS
# =============================================================================

output "opensearch_endpoint" {
  description = "OpenSearch endpoint"
  value       = var.create_opensearch ? module.opensearch[0].endpoint : null
}

output "opensearch_dashboard_endpoint" {
  description = "OpenSearch Dashboards endpoint"
  value       = var.create_opensearch ? module.opensearch[0].dashboard_endpoint : null
}

output "opensearch_secret_arn" {
  description = "OpenSearch credentials secret ARN"
  value       = var.create_opensearch ? module.opensearch[0].secret_arn : null
  sensitive   = true
}

# =============================================================================
# HELM VALUES OUTPUT
# =============================================================================

output "helm_values" {
  description = "Generated values for Darwin Helm chart"
  value = {
    global = {
      imageRegistry = var.create_ecr ? module.ecr[0].registry_url : "docker.io"
      storageClass  = "gp3"
      namespace     = "darwin"
      local_k8s     = false
    }
    aws = {
      region = var.aws_region
      s3 = {
        mlflowBucket = module.s3.mlflow_bucket_name
        sharedBucket = module.s3.shared_bucket_name
      }
    }
    database = {
      mysql = {
        host             = var.create_rds ? module.rds[0].endpoint : null
        port             = var.create_rds ? module.rds[0].port : null
        database         = var.create_rds ? module.rds[0].database_name : null
        secretName       = var.create_rds ? module.rds[0].secret_name : null
        useExternalSecret = true
      }
    }
    opensearch = var.create_opensearch ? {
      endpoint          = module.opensearch[0].endpoint
      secretName        = module.opensearch[0].secret_name
      useExternalSecret = true
    } : null
    irsa = {
      s3AccessRoleArn      = module.eks.s3_access_role_arn
      secretsAccessRoleArn = module.eks.secrets_access_role_arn
    }
  }
}

# =============================================================================
# KUBECONFIG COMMAND
# =============================================================================

output "kubeconfig_command" {
  description = "Command to update kubeconfig"
  value       = "aws eks update-kubeconfig --name ${module.eks.cluster_name} --region ${var.aws_region}"
}


