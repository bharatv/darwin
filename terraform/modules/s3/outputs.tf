output "mlflow_bucket_name" {
  description = "MLflow artifacts bucket name"
  value       = aws_s3_bucket.mlflow_artifacts.id
}

output "mlflow_bucket_arn" {
  description = "MLflow artifacts bucket ARN"
  value       = aws_s3_bucket.mlflow_artifacts.arn
}

output "shared_bucket_name" {
  description = "Shared storage bucket name"
  value       = aws_s3_bucket.shared_storage.id
}

output "shared_bucket_arn" {
  description = "Shared storage bucket ARN"
  value       = aws_s3_bucket.shared_storage.arn
}

output "terraform_state_bucket_name" {
  description = "Terraform state bucket name"
  value       = var.create_terraform_state_bucket ? aws_s3_bucket.terraform_state[0].id : null
}

output "terraform_lock_table_name" {
  description = "DynamoDB table for Terraform state locking"
  value       = var.create_terraform_state_bucket ? aws_dynamodb_table.terraform_lock[0].name : null
}

output "bucket_names" {
  description = "Map of all bucket names"
  value = {
    mlflow = aws_s3_bucket.mlflow_artifacts.id
    shared = aws_s3_bucket.shared_storage.id
  }
}

