# =============================================================================
# OPENSEARCH MODULE - Search Engine for Darwin Platform
# =============================================================================

locals {
  name_prefix = "${var.project_name}-${var.environment}"
  domain_name = "${var.project_name}-${var.environment}"
}

# =============================================================================
# RANDOM PASSWORD FOR MASTER USER
# =============================================================================

resource "random_password" "master" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

# =============================================================================
# SECRETS MANAGER - Store credentials
# =============================================================================

resource "aws_secretsmanager_secret" "opensearch_credentials" {
  name                    = "${var.project_name}/${var.environment}/opensearch-credentials"
  description             = "OpenSearch credentials for Darwin platform"
  recovery_window_in_days = var.environment == "prod" ? 30 : 0

  tags = {
    Name = "${local.name_prefix}-opensearch-credentials"
  }
}

resource "aws_secretsmanager_secret_version" "opensearch_credentials" {
  secret_id = aws_secretsmanager_secret.opensearch_credentials.id
  secret_string = jsonencode({
    username = var.master_username
    password = random_password.master.result
    endpoint = aws_opensearch_domain.main.endpoint
  })
}

# =============================================================================
# SECURITY GROUP
# =============================================================================

resource "aws_security_group" "opensearch" {
  name        = "${local.name_prefix}-opensearch-sg"
  description = "Security group for OpenSearch domain"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = var.allowed_security_groups
    description     = "HTTPS access from allowed security groups"
  }

  ingress {
    from_port       = 9200
    to_port         = 9200
    protocol        = "tcp"
    security_groups = var.allowed_security_groups
    description     = "OpenSearch REST API access"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }

  tags = {
    Name = "${local.name_prefix}-opensearch-sg"
  }
}

# =============================================================================
# SERVICE-LINKED ROLE (if not exists)
# =============================================================================

data "aws_iam_role" "opensearch_service_role" {
  count = var.create_service_linked_role ? 0 : 1
  name  = "AWSServiceRoleForAmazonOpenSearchService"
}

resource "aws_iam_service_linked_role" "opensearch" {
  count            = var.create_service_linked_role ? 1 : 0
  aws_service_name = "opensearchservice.amazonaws.com"
}

# =============================================================================
# OPENSEARCH DOMAIN
# =============================================================================

resource "aws_opensearch_domain" "main" {
  domain_name    = local.domain_name
  engine_version = var.engine_version

  cluster_config {
    instance_type          = var.instance_type
    instance_count         = var.instance_count
    zone_awareness_enabled = var.instance_count > 1

    dynamic "zone_awareness_config" {
      for_each = var.instance_count > 1 ? [1] : []
      content {
        availability_zone_count = min(var.instance_count, 3)
      }
    }
  }

  vpc_options {
    subnet_ids         = var.instance_count > 1 ? slice(var.subnet_ids, 0, min(var.instance_count, 3)) : [var.subnet_ids[0]]
    security_group_ids = [aws_security_group.opensearch.id]
  }

  ebs_options {
    ebs_enabled = true
    volume_type = "gp3"
    volume_size = var.ebs_volume_size
  }

  encrypt_at_rest {
    enabled = true
  }

  node_to_node_encryption {
    enabled = true
  }

  domain_endpoint_options {
    enforce_https       = true
    tls_security_policy = "Policy-Min-TLS-1-2-2019-07"
  }

  advanced_security_options {
    enabled                        = true
    internal_user_database_enabled = true

    master_user_options {
      master_user_name     = var.master_username
      master_user_password = random_password.master.result
    }
  }

  access_policies = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          AWS = "*"
        }
        Action   = "es:*"
        Resource = "arn:aws:es:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:domain/${local.domain_name}/*"
      }
    ]
  })

  tags = {
    Name = local.domain_name
  }

  depends_on = [aws_iam_service_linked_role.opensearch]
}

# =============================================================================
# DATA SOURCES
# =============================================================================

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

