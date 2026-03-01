-- Idempotent schema changes for deployment strategy support.
-- This is executed by ml-serve-app/.odin/ml-serve-app/pre-deploy.sh (best effort).
--
-- Notes:
-- - We avoid ALTER ... ADD COLUMN without guards to keep this re-runnable.
-- - We rely on information_schema to detect presence of columns/indexes.
-- - MySQL JSON type requires MySQL 5.7+; Darwin uses MySQL 8.0+.
-- - All new columns are NULLable for backward compatibility.
--
-- Target tables:
-- - app_layer_deployments: add phase tracking fields
-- - deployment_phases: new audit/history table for approvals & traffic weights


/* -------------------------------------------------------------------------- */
/* app_layer_deployments: add columns                                          */
/* -------------------------------------------------------------------------- */

SET @schema := DATABASE();

SET @has_phase :=
  (SELECT COUNT(*)
   FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = @schema
     AND TABLE_NAME = 'app_layer_deployments'
     AND COLUMN_NAME = 'phase');

SET @sql :=
  IF(@has_phase = 0,
     'ALTER TABLE app_layer_deployments ADD COLUMN phase VARCHAR(50) NULL',
     'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has_phase_metadata :=
  (SELECT COUNT(*)
   FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = @schema
     AND TABLE_NAME = 'app_layer_deployments'
     AND COLUMN_NAME = 'phase_metadata');

SET @sql :=
  IF(@has_phase_metadata = 0,
     'ALTER TABLE app_layer_deployments ADD COLUMN phase_metadata JSON NULL',
     'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has_requires_approval :=
  (SELECT COUNT(*)
   FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = @schema
     AND TABLE_NAME = 'app_layer_deployments'
     AND COLUMN_NAME = 'requires_approval');

SET @sql :=
  IF(@has_requires_approval = 0,
     'ALTER TABLE app_layer_deployments ADD COLUMN requires_approval TINYINT(1) NULL',
     'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

/* -------------------------------------------------------------------------- */
/* app_layer_deployments: add index                                             */
/* -------------------------------------------------------------------------- */

SET @has_idx_app_layer_phase :=
  (SELECT COUNT(*)
   FROM information_schema.STATISTICS
   WHERE TABLE_SCHEMA = @schema
     AND TABLE_NAME = 'app_layer_deployments'
     AND INDEX_NAME = 'idx_app_layer_deployments_phase');

SET @sql :=
  IF(@has_idx_app_layer_phase = 0,
     'CREATE INDEX idx_app_layer_deployments_phase ON app_layer_deployments (phase)',
     'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

/* -------------------------------------------------------------------------- */
/* deployment_phases: create table + index                                      */
/* -------------------------------------------------------------------------- */

CREATE TABLE IF NOT EXISTS deployment_phases (
  id INT NOT NULL AUTO_INCREMENT,
  deployment_id INT NOT NULL,
  phase_name VARCHAR(50) NOT NULL,
  traffic_weights JSON NULL,
  approver_username VARCHAR(255) NULL,
  approved_at DATETIME(6) NULL,
  rejection_reason TEXT NULL,
  notes TEXT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  CONSTRAINT fk_deployment_phases_deployment
    FOREIGN KEY (deployment_id) REFERENCES deployments(id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SET @has_idx_deployment_phases_deployment_id :=
  (SELECT COUNT(*)
   FROM information_schema.STATISTICS
   WHERE TABLE_SCHEMA = @schema
     AND TABLE_NAME = 'deployment_phases'
     AND INDEX_NAME = 'idx_deployment_phases_deployment_id');

SET @sql :=
  IF(@has_idx_deployment_phases_deployment_id = 0,
     'CREATE INDEX idx_deployment_phases_deployment_id ON deployment_phases (deployment_id)',
     'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

/* -------------------------------------------------------------------------- */
/* active_deployments: add candidate_deployment_id for in-transition tracking  */
/* -------------------------------------------------------------------------- */

SET @has_candidate_deployment_id :=
  (SELECT COUNT(*)
   FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = @schema
     AND TABLE_NAME = 'active_deployments'
     AND COLUMN_NAME = 'candidate_deployment_id');

SET @sql :=
  IF(@has_candidate_deployment_id = 0,
     'ALTER TABLE active_deployments ADD COLUMN candidate_deployment_id INT NULL',
     'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has_fk_candidate_deployment :=
  (SELECT COUNT(*)
   FROM information_schema.TABLE_CONSTRAINTS
   WHERE TABLE_SCHEMA = @schema
     AND TABLE_NAME = 'active_deployments'
     AND CONSTRAINT_NAME = 'fk_active_deployments_candidate_deployment'
     AND CONSTRAINT_TYPE = 'FOREIGN KEY');

SET @sql :=
  IF(@has_fk_candidate_deployment = 0,
     'ALTER TABLE active_deployments ADD CONSTRAINT fk_active_deployments_candidate_deployment FOREIGN KEY (candidate_deployment_id) REFERENCES deployments(id) ON DELETE SET NULL',
     'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @has_idx_active_deployments_candidate :=
  (SELECT COUNT(*)
   FROM information_schema.STATISTICS
   WHERE TABLE_SCHEMA = @schema
     AND TABLE_NAME = 'active_deployments'
     AND INDEX_NAME = 'idx_active_deployments_candidate_deployment_id');

SET @sql :=
  IF(@has_idx_active_deployments_candidate = 0,
     'CREATE INDEX idx_active_deployments_candidate_deployment_id ON active_deployments (candidate_deployment_id)',
     'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

