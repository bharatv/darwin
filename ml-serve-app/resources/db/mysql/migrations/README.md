# Database Migrations

## Overview

This directory contains SQL migrations for the ml-serve-app database schema.

## Running Migrations

### Automatic Schema Generation

The application uses Tortoise-ORM with `generate_schemas=True`, which automatically creates tables on startup. However, for production environments or when adding complex schema changes, manual migrations are recommended.

### Manual Migration Execution

#### Apply Migration
```bash
mysql -h $MYSQL_HOST -u $MYSQL_USERNAME -p$MYSQL_PASSWORD $MYSQL_DATABASE < 001_deployment_strategies.sql
```

#### Rollback Migration
```bash
mysql -h $MYSQL_HOST -u $MYSQL_USERNAME -p$MYSQL_PASSWORD $MYSQL_DATABASE < 001_deployment_strategies_rollback.sql
```

## Available Migrations

### 001_deployment_strategies.sql
- Creates `deployment_transitions` table for tracking deployment state changes
- Updates `app_layer_deployments` table with default value for `deployment_strategy`
- Adds support for new deployment strategy enums (handled in Python code)

**Note**: Since Tortoise-ORM uses Python Enums, enum values are defined in `ml_serve_model/enums.py` and don't require database-level ENUM type changes.

## Schema Validation

After applying migrations, verify the schema:

```bash
# Test that models can be imported
cd ml-serve-app
python -c "from ml_serve_model import DeploymentStatus, DeploymentStrategy, DeploymentTransition; print('✓ Models imported successfully')"

# Run application in schema generation mode (creates/updates tables)
# This is automatically done when the app starts with generate_schemas=True
```

## Backward Compatibility

- Existing deployments without `deployment_strategy` will default to `IMMEDIATE`
- The `deployment_transitions` table is new and won't affect existing functionality
- Enum additions (CANARY, STABLE, etc.) are backward compatible as they're handled in Python
