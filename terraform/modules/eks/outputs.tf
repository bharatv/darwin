output "cluster_name" {
  description = "Name of the EKS cluster"
  value       = aws_eks_cluster.main.name
}

output "cluster_endpoint" {
  description = "Endpoint for EKS cluster API"
  value       = aws_eks_cluster.main.endpoint
}

output "cluster_ca_certificate" {
  description = "Base64 encoded CA certificate for cluster"
  value       = aws_eks_cluster.main.certificate_authority[0].data
}

output "cluster_security_group_id" {
  description = "Security group ID for cluster"
  value       = aws_security_group.cluster.id
}

output "node_security_group_id" {
  description = "Security group ID for nodes"
  value       = aws_security_group.nodes.id
}

output "oidc_provider_arn" {
  description = "ARN of OIDC provider for IRSA"
  value       = aws_iam_openid_connect_provider.cluster.arn
}

output "oidc_provider_url" {
  description = "URL of OIDC provider"
  value       = aws_iam_openid_connect_provider.cluster.url
}

output "node_role_arn" {
  description = "ARN of node IAM role"
  value       = aws_iam_role.nodes.arn
}

output "s3_access_role_arn" {
  description = "ARN of S3 access IAM role for pods"
  value       = aws_iam_role.s3_access.arn
}

output "secrets_access_role_arn" {
  description = "ARN of Secrets Manager access IAM role for pods"
  value       = aws_iam_role.secrets_access.arn
}


