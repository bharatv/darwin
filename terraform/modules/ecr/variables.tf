variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "repositories" {
  description = "List of ECR repository names"
  type        = list(string)
}

variable "scan_on_push" {
  description = "Enable image scanning on push"
  type        = bool
  default     = true
}

variable "image_retention_count" {
  description = "Number of tagged images to retain"
  type        = number
  default     = 10
}

variable "untagged_image_expiry_days" {
  description = "Days to keep untagged images"
  type        = number
  default     = 7
}

variable "enable_cross_account_access" {
  description = "Enable cross-account access to repositories"
  type        = bool
  default     = false
}

variable "cross_account_arns" {
  description = "List of ARNs for cross-account access"
  type        = list(string)
  default     = []
}

