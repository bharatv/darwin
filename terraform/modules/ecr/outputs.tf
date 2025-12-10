output "repository_urls" {
  description = "Map of repository names to URLs"
  value       = { for k, v in aws_ecr_repository.repos : k => v.repository_url }
}

output "repository_arns" {
  description = "Map of repository names to ARNs"
  value       = { for k, v in aws_ecr_repository.repos : k => v.arn }
}

output "registry_id" {
  description = "Registry ID"
  value       = values(aws_ecr_repository.repos)[0].registry_id
}

output "registry_url" {
  description = "ECR registry URL (without repository)"
  value       = split("/", values(aws_ecr_repository.repos)[0].repository_url)[0]
}


