output "endpoint" {
  description = "OpenSearch domain endpoint"
  value       = aws_opensearch_domain.main.endpoint
}

output "dashboard_endpoint" {
  description = "OpenSearch Dashboards endpoint"
  value       = aws_opensearch_domain.main.dashboard_endpoint
}

output "domain_name" {
  description = "OpenSearch domain name"
  value       = aws_opensearch_domain.main.domain_name
}

output "domain_arn" {
  description = "OpenSearch domain ARN"
  value       = aws_opensearch_domain.main.arn
}

output "security_group_id" {
  description = "Security group ID for OpenSearch"
  value       = aws_security_group.opensearch.id
}

output "secret_arn" {
  description = "ARN of Secrets Manager secret containing credentials"
  value       = aws_secretsmanager_secret.opensearch_credentials.arn
}

output "secret_name" {
  description = "Name of Secrets Manager secret"
  value       = aws_secretsmanager_secret.opensearch_credentials.name
}

