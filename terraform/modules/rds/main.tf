# =============================================================================
# RDS MODULE - MySQL Database for Darwin Platform
# =============================================================================

locals {
  name_prefix = "${var.project_name}-${var.environment}"
  db_name     = "${local.name_prefix}-mysql"
}

# =============================================================================
# RANDOM PASSWORD GENERATION
# =============================================================================

resource "random_password" "master" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

# =============================================================================
# SECRETS MANAGER - Store credentials
# =============================================================================

resource "aws_secretsmanager_secret" "db_credentials" {
  name                    = "${var.project_name}/${var.environment}/rds-credentials"
  description             = "RDS MySQL credentials for Darwin platform"
  recovery_window_in_days = var.environment == "prod" ? 30 : 0

  tags = {
    Name = "${local.db_name}-credentials"
  }
}

resource "aws_secretsmanager_secret_version" "db_credentials" {
  secret_id = aws_secretsmanager_secret.db_credentials.id
  secret_string = jsonencode({
    username            = var.master_username
    password            = random_password.master.result
    engine              = "mysql"
    host                = aws_db_instance.main.address
    port                = aws_db_instance.main.port
    dbname              = var.database_name
    dbInstanceIdentifier = aws_db_instance.main.identifier
  })
}

# =============================================================================
# DB SUBNET GROUP
# =============================================================================

resource "aws_db_subnet_group" "main" {
  name        = "${local.db_name}-subnet-group"
  description = "Subnet group for ${local.db_name}"
  subnet_ids  = var.subnet_ids

  tags = {
    Name = "${local.db_name}-subnet-group"
  }
}

# =============================================================================
# SECURITY GROUP
# =============================================================================

resource "aws_security_group" "rds" {
  name        = "${local.db_name}-sg"
  description = "Security group for RDS MySQL"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 3306
    to_port         = 3306
    protocol        = "tcp"
    security_groups = var.allowed_security_groups
    description     = "MySQL access from allowed security groups"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }

  tags = {
    Name = "${local.db_name}-sg"
  }
}

# =============================================================================
# DB PARAMETER GROUP
# =============================================================================

resource "aws_db_parameter_group" "main" {
  name   = "${local.db_name}-params"
  family = "mysql8.0"

  parameter {
    name  = "character_set_server"
    value = "utf8mb4"
  }

  parameter {
    name  = "character_set_client"
    value = "utf8mb4"
  }

  parameter {
    name  = "collation_server"
    value = "utf8mb4_unicode_ci"
  }

  parameter {
    name  = "max_connections"
    value = "500"
  }

  parameter {
    name  = "log_bin_trust_function_creators"
    value = "1"
  }

  tags = {
    Name = "${local.db_name}-params"
  }
}

# =============================================================================
# RDS INSTANCE
# =============================================================================

resource "aws_db_instance" "main" {
  identifier = local.db_name

  engine               = "mysql"
  engine_version       = var.engine_version
  instance_class       = var.instance_class
  allocated_storage    = var.allocated_storage
  max_allocated_storage = var.max_allocated_storage
  storage_type         = "gp3"
  storage_encrypted    = true

  db_name  = var.database_name
  username = var.master_username
  password = random_password.master.result

  multi_az               = var.multi_az
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  parameter_group_name   = aws_db_parameter_group.main.name
  publicly_accessible    = false

  backup_retention_period = var.backup_retention_period
  backup_window           = "03:00-04:00"
  maintenance_window      = "Mon:04:00-Mon:05:00"

  skip_final_snapshot       = var.environment != "prod"
  final_snapshot_identifier = var.environment == "prod" ? "${local.db_name}-final-snapshot" : null
  deletion_protection       = var.deletion_protection

  performance_insights_enabled = var.environment == "prod"

  enabled_cloudwatch_logs_exports = ["error", "slowquery"]

  tags = {
    Name = local.db_name
  }
}

# =============================================================================
# ADDITIONAL DATABASES (created via null_resource)
# =============================================================================

# Note: Additional databases like darwin_mlflow and darwin_catalog
# should be created using SQL scripts or application migrations
# after the RDS instance is available

