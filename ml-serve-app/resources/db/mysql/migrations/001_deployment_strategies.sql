-- Migration: Add deployment strategies support
-- Date: 2026-02-25
-- Description: Adds DeploymentTransition table and updates AppLayerDeployment for strategy support

-- Create deployment_transitions table
CREATE TABLE IF NOT EXISTS deployment_transitions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    deployment_id INT NOT NULL,
    from_status VARCHAR(50),
    to_status VARCHAR(50) NOT NULL,
    transition_type VARCHAR(50) NOT NULL,
    triggered_by VARCHAR(255),
    triggered_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reason TEXT,
    metadata JSON,
    FOREIGN KEY (deployment_id) REFERENCES deployments(id) ON DELETE CASCADE,
    INDEX idx_deployment_id (deployment_id),
    INDEX idx_triggered_at (triggered_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Update app_layer_deployments table
-- Add default value for deployment_strategy if column exists without default
ALTER TABLE app_layer_deployments 
    MODIFY COLUMN deployment_strategy VARCHAR(50) DEFAULT 'IMMEDIATE';

-- Note: New enum values (CANARY, STABLE, SUPERSEDED, ROLLING_OUT) for DeploymentStatus
-- and new enum (DeploymentStrategy: IMMEDIATE, ROLLING, CANARY, BLUE_GREEN) 
-- are handled in application code via Tortoise-ORM enums.
-- No database schema changes needed for enum additions.
