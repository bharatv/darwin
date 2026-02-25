-- Rollback migration for deployment strategies
-- Date: 2026-02-25
-- Description: Rollback deployment strategies changes

-- Drop deployment_transitions table
DROP TABLE IF EXISTS deployment_transitions;

-- Revert app_layer_deployments changes (remove default)
ALTER TABLE app_layer_deployments 
    MODIFY COLUMN deployment_strategy VARCHAR(50);

-- Note: Enum values in application code need to be manually reverted if rollback is performed
