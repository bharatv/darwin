-- Migration: Add JSON columns to cluster_status table for removing Elasticsearch dependency
-- This migration adds columns to store cluster configuration, labels, and tags in MySQL
-- Previously stored in Elasticsearch index 'computea_v2'

USE darwin;

-- Add new columns to cluster_status table
ALTER TABLE `cluster_status`
    -- Full cluster configuration stored as JSON
    ADD COLUMN `cluster_config` JSON DEFAULT NULL COMMENT 'Full cluster configuration (previously in ES)',
    -- User-defined labels as key-value pairs
    ADD COLUMN `labels` JSON DEFAULT NULL COMMENT 'User-defined labels as JSON object',
    -- User-defined tags as array
    ADD COLUMN `tags` JSON DEFAULT NULL COMMENT 'User-defined tags as JSON array',
    -- Searchable fields previously only in ES
    ADD COLUMN `user` VARCHAR(255) DEFAULT NULL COMMENT 'Cluster owner',
    ADD COLUMN `runtime` VARCHAR(255) DEFAULT NULL COMMENT 'Ray runtime version',
    ADD COLUMN `cloud_env` VARCHAR(128) DEFAULT NULL COMMENT 'Cloud environment identifier',
    ADD COLUMN `is_job_cluster` BOOLEAN DEFAULT FALSE COMMENT 'Whether this is an ephemeral job cluster',
    -- Additional metadata
    ADD COLUMN `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Cluster creation time',
    ADD COLUMN `total_memory_gb` INT DEFAULT 0 COMMENT 'Total memory in GB across all pods',
    ADD COLUMN `head_cpu` VARCHAR(32) DEFAULT NULL COMMENT 'Head node CPU allocation',
    ADD COLUMN `head_memory_gb` INT DEFAULT NULL COMMENT 'Head node memory in GB';

-- Add indexes for common queries
CREATE INDEX `idx_user` ON `cluster_status` (`user`);
CREATE INDEX `idx_runtime` ON `cluster_status` (`runtime`);
CREATE INDEX `idx_cloud_env` ON `cluster_status` (`cloud_env`);
CREATE INDEX `idx_is_job_cluster` ON `cluster_status` (`is_job_cluster`);
CREATE INDEX `idx_created_at` ON `cluster_status` (`created_at`);

-- For MySQL 8.0+: Add generated column for label-based search
-- This allows indexing on specific label keys
ALTER TABLE `cluster_status`
    ADD COLUMN `labels_flat` VARCHAR(4096) GENERATED ALWAYS AS (
        JSON_UNQUOTE(JSON_KEYS(`labels`))
    ) STORED;

-- Add full-text index for cluster name search (MySQL 5.7+)
ALTER TABLE `cluster_status`
    ADD FULLTEXT INDEX `ft_cluster_name` (`cluster_name`);

-- Create a view for backward compatibility with ES-style queries
CREATE OR REPLACE VIEW `v_cluster_search` AS
SELECT 
    cs.cluster_id,
    cs.cluster_name,
    cs.artifact_id,
    cs.status,
    cs.active_pods,
    cs.available_memory,
    cs.user,
    cs.runtime,
    cs.cloud_env,
    cs.is_job_cluster,
    cs.labels,
    cs.tags,
    cs.cluster_config,
    cs.created_at,
    cs.last_updated_at,
    cs.last_used_at,
    cs.total_memory_gb,
    cs.head_cpu,
    cs.head_memory_gb
FROM `cluster_status` cs;

-- Create table for storing label key-value pairs for efficient search
-- This denormalizes labels for better query performance
CREATE TABLE IF NOT EXISTS `cluster_labels` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `cluster_id` VARCHAR(255) NOT NULL,
    `label_key` VARCHAR(255) NOT NULL,
    `label_value` VARCHAR(1024) NOT NULL,
    PRIMARY KEY (`id`),
    INDEX `idx_cluster_id` (`cluster_id`),
    INDEX `idx_label_key` (`label_key`),
    INDEX `idx_label_key_value` (`label_key`, `label_value`(255)),
    FOREIGN KEY (`cluster_id`) REFERENCES `cluster_status`(`cluster_id`) ON DELETE CASCADE
);

-- Create table for storing tags for efficient search
CREATE TABLE IF NOT EXISTS `cluster_tags` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `cluster_id` VARCHAR(255) NOT NULL,
    `tag` VARCHAR(255) NOT NULL,
    PRIMARY KEY (`id`),
    INDEX `idx_cluster_id` (`cluster_id`),
    INDEX `idx_tag` (`tag`),
    FOREIGN KEY (`cluster_id`) REFERENCES `cluster_status`(`cluster_id`) ON DELETE CASCADE
);

-- Trigger to sync labels to cluster_labels table on insert/update
DELIMITER //

CREATE TRIGGER `tr_cluster_labels_insert` AFTER INSERT ON `cluster_status`
FOR EACH ROW
BEGIN
    DECLARE done INT DEFAULT FALSE;
    DECLARE label_key VARCHAR(255);
    DECLARE label_value VARCHAR(1024);
    DECLARE label_keys JSON;
    DECLARE i INT DEFAULT 0;
    
    IF NEW.labels IS NOT NULL AND JSON_LENGTH(NEW.labels) > 0 THEN
        SET label_keys = JSON_KEYS(NEW.labels);
        WHILE i < JSON_LENGTH(label_keys) DO
            SET label_key = JSON_UNQUOTE(JSON_EXTRACT(label_keys, CONCAT('$[', i, ']')));
            SET label_value = JSON_UNQUOTE(JSON_EXTRACT(NEW.labels, CONCAT('$.', label_key)));
            INSERT INTO `cluster_labels` (`cluster_id`, `label_key`, `label_value`)
            VALUES (NEW.cluster_id, label_key, label_value);
            SET i = i + 1;
        END WHILE;
    END IF;
END//

CREATE TRIGGER `tr_cluster_labels_update` AFTER UPDATE ON `cluster_status`
FOR EACH ROW
BEGIN
    DECLARE done INT DEFAULT FALSE;
    DECLARE label_key VARCHAR(255);
    DECLARE label_value VARCHAR(1024);
    DECLARE label_keys JSON;
    DECLARE i INT DEFAULT 0;
    
    -- Only process if labels changed
    IF NOT (NEW.labels <=> OLD.labels) THEN
        -- Delete old labels
        DELETE FROM `cluster_labels` WHERE `cluster_id` = NEW.cluster_id;
        
        -- Insert new labels
        IF NEW.labels IS NOT NULL AND JSON_LENGTH(NEW.labels) > 0 THEN
            SET label_keys = JSON_KEYS(NEW.labels);
            WHILE i < JSON_LENGTH(label_keys) DO
                SET label_key = JSON_UNQUOTE(JSON_EXTRACT(label_keys, CONCAT('$[', i, ']')));
                SET label_value = JSON_UNQUOTE(JSON_EXTRACT(NEW.labels, CONCAT('$.', label_key)));
                INSERT INTO `cluster_labels` (`cluster_id`, `label_key`, `label_value`)
                VALUES (NEW.cluster_id, label_key, label_value);
                SET i = i + 1;
            END WHILE;
        END IF;
    END IF;
END//

-- Trigger to sync tags to cluster_tags table
CREATE TRIGGER `tr_cluster_tags_insert` AFTER INSERT ON `cluster_status`
FOR EACH ROW
BEGIN
    DECLARE i INT DEFAULT 0;
    DECLARE tag_value VARCHAR(255);
    
    IF NEW.tags IS NOT NULL AND JSON_LENGTH(NEW.tags) > 0 THEN
        WHILE i < JSON_LENGTH(NEW.tags) DO
            SET tag_value = JSON_UNQUOTE(JSON_EXTRACT(NEW.tags, CONCAT('$[', i, ']')));
            INSERT INTO `cluster_tags` (`cluster_id`, `tag`)
            VALUES (NEW.cluster_id, tag_value);
            SET i = i + 1;
        END WHILE;
    END IF;
END//

CREATE TRIGGER `tr_cluster_tags_update` AFTER UPDATE ON `cluster_status`
FOR EACH ROW
BEGIN
    DECLARE i INT DEFAULT 0;
    DECLARE tag_value VARCHAR(255);
    
    -- Only process if tags changed
    IF NOT (NEW.tags <=> OLD.tags) THEN
        -- Delete old tags
        DELETE FROM `cluster_tags` WHERE `cluster_id` = NEW.cluster_id;
        
        -- Insert new tags
        IF NEW.tags IS NOT NULL AND JSON_LENGTH(NEW.tags) > 0 THEN
            WHILE i < JSON_LENGTH(NEW.tags) DO
                SET tag_value = JSON_UNQUOTE(JSON_EXTRACT(NEW.tags, CONCAT('$[', i, ']')));
                INSERT INTO `cluster_tags` (`cluster_id`, `tag`)
                VALUES (NEW.cluster_id, tag_value);
                SET i = i + 1;
            END WHILE;
        END IF;
    END IF;
END//

DELIMITER ;
