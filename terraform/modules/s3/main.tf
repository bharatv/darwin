# =============================================================================
# S3 MODULE - Object Storage for Darwin Platform
# =============================================================================

locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

# =============================================================================
# MLFLOW ARTIFACTS BUCKET
# =============================================================================

resource "aws_s3_bucket" "mlflow_artifacts" {
  bucket        = "${local.name_prefix}-mlflow-artifacts"
  force_destroy = var.force_destroy

  tags = {
    Name    = "${local.name_prefix}-mlflow-artifacts"
    Purpose = "MLflow model artifacts and experiment tracking"
  }
}

resource "aws_s3_bucket_versioning" "mlflow_artifacts" {
  bucket = aws_s3_bucket.mlflow_artifacts.id

  versioning_configuration {
    status = var.enable_versioning ? "Enabled" : "Disabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "mlflow_artifacts" {
  bucket = aws_s3_bucket.mlflow_artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "mlflow_artifacts" {
  bucket = aws_s3_bucket.mlflow_artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "mlflow_artifacts" {
  bucket = aws_s3_bucket.mlflow_artifacts.id

  rule {
    id     = "transition-to-ia"
    status = "Enabled"

    filter {
      prefix = ""
    }

    transition {
      days          = 90
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 365
      storage_class = "GLACIER"
    }
  }

  rule {
    id     = "expire-incomplete-uploads"
    status = "Enabled"

    filter {
      prefix = ""
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_cors_configuration" "mlflow_artifacts" {
  bucket = aws_s3_bucket.mlflow_artifacts.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "PUT", "POST", "DELETE", "HEAD"]
    allowed_origins = var.cors_allowed_origins
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

# =============================================================================
# SHARED STORAGE BUCKET
# =============================================================================

resource "aws_s3_bucket" "shared_storage" {
  bucket        = "${local.name_prefix}-shared-storage"
  force_destroy = var.force_destroy

  tags = {
    Name    = "${local.name_prefix}-shared-storage"
    Purpose = "Shared platform storage"
  }
}

resource "aws_s3_bucket_versioning" "shared_storage" {
  bucket = aws_s3_bucket.shared_storage.id

  versioning_configuration {
    status = var.enable_versioning ? "Enabled" : "Disabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "shared_storage" {
  bucket = aws_s3_bucket.shared_storage.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "shared_storage" {
  bucket = aws_s3_bucket.shared_storage.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "shared_storage" {
  bucket = aws_s3_bucket.shared_storage.id

  rule {
    id     = "expire-incomplete-uploads"
    status = "Enabled"

    filter {
      prefix = ""
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# =============================================================================
# TERRAFORM STATE BUCKET (Optional)
# =============================================================================

resource "aws_s3_bucket" "terraform_state" {
  count = var.create_terraform_state_bucket ? 1 : 0

  bucket        = "${local.name_prefix}-terraform-state"
  force_destroy = false

  tags = {
    Name    = "${local.name_prefix}-terraform-state"
    Purpose = "Terraform state storage"
  }
}

resource "aws_s3_bucket_versioning" "terraform_state" {
  count = var.create_terraform_state_bucket ? 1 : 0

  bucket = aws_s3_bucket.terraform_state[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  count = var.create_terraform_state_bucket ? 1 : 0

  bucket = aws_s3_bucket.terraform_state[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state" {
  count = var.create_terraform_state_bucket ? 1 : 0

  bucket = aws_s3_bucket.terraform_state[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# DynamoDB table for state locking
resource "aws_dynamodb_table" "terraform_lock" {
  count = var.create_terraform_state_bucket ? 1 : 0

  name         = "${local.name_prefix}-terraform-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = {
    Name = "${local.name_prefix}-terraform-lock"
  }
}

