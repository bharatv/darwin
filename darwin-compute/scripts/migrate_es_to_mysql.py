#!/usr/bin/env python3
"""
Migration Script: Elasticsearch to MySQL JSON

This script migrates cluster data from Elasticsearch to MySQL JSON columns.
It reads all documents from the ES 'computea_v2' index and updates the
corresponding rows in the MySQL 'cluster_status' table with JSON data.

Usage:
    python migrate_es_to_mysql.py [--dry-run] [--batch-size 100] [--verbose]

Environment Variables:
    VAULT_SERVICE_ES_USERNAME: Elasticsearch username
    VAULT_SERVICE_ES_PASSWORD: Elasticsearch password
    VAULT_SERVICE_MYSQL_USERNAME: MySQL username
    VAULT_SERVICE_MYSQL_PASSWORD: MySQL password
    CONFIG_SERVICE_MYSQL_DATABASE: MySQL database name
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from datetime import datetime

from loguru import logger
from elasticsearch import Elasticsearch
import pymysql


@dataclass
class MigrationConfig:
    """Configuration for the migration."""
    es_host: str = "http://darwin-elasticsearch.darwin.svc.cluster.local:9200"
    es_index: str = "computea_v2"
    es_username: str = ""
    es_password: str = ""
    mysql_host: str = "darwin-mysql.darwin.svc.cluster.local"
    mysql_port: int = 3306
    mysql_database: str = "darwin"
    mysql_username: str = ""
    mysql_password: str = ""
    batch_size: int = 100
    dry_run: bool = False


class ESToMySQLMigrator:
    """Migrates cluster data from Elasticsearch to MySQL."""
    
    def __init__(self, config: MigrationConfig):
        self.config = config
        self.es_client = None
        self.mysql_conn = None
        self.migrated_count = 0
        self.failed_count = 0
        self.skipped_count = 0
    
    def connect(self):
        """Establish connections to ES and MySQL."""
        # Connect to Elasticsearch
        self.es_client = Elasticsearch(
            hosts=[self.config.es_host],
            http_auth=(self.config.es_username, self.config.es_password) 
            if self.config.es_username else None
        )
        
        if not self.es_client.ping():
            raise ConnectionError("Failed to connect to Elasticsearch")
        logger.info("Connected to Elasticsearch")
        
        # Connect to MySQL
        self.mysql_conn = pymysql.connect(
            host=self.config.mysql_host,
            port=self.config.mysql_port,
            user=self.config.mysql_username,
            password=self.config.mysql_password,
            database=self.config.mysql_database,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False
        )
        logger.info("Connected to MySQL")
    
    def close(self):
        """Close connections."""
        if self.mysql_conn:
            self.mysql_conn.close()
        # ES client doesn't need explicit close
    
    def get_es_documents(self, scroll_id: Optional[str] = None) -> tuple[List[Dict], Optional[str]]:
        """
        Fetch documents from Elasticsearch using scroll API.
        
        Returns:
            Tuple of (documents list, scroll_id for next batch)
        """
        if scroll_id:
            result = self.es_client.scroll(scroll_id=scroll_id, scroll="5m")
        else:
            result = self.es_client.search(
                index=self.config.es_index,
                scroll="5m",
                size=self.config.batch_size,
                body={"query": {"match_all": {}}}
            )
        
        hits = result.get("hits", {}).get("hits", [])
        new_scroll_id = result.get("_scroll_id") if hits else None
        
        documents = []
        for hit in hits:
            doc = hit.get("_source", {})
            doc["_id"] = hit.get("_id")  # cluster_id
            documents.append(doc)
        
        return documents, new_scroll_id
    
    def transform_document(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform ES document to MySQL row format.
        
        Args:
            doc: Elasticsearch document
            
        Returns:
            Transformed data for MySQL update
        """
        cluster_id = doc.get("_id") or doc.get("cluster_id")
        
        # Extract fields that go into dedicated columns
        user = doc.get("user", "")
        runtime = doc.get("runtime", "")
        cloud_env = doc.get("cloud_env", "")
        is_job_cluster = doc.get("is_job_cluster", False)
        
        # Extract labels and tags
        labels = doc.get("labels", {})
        tags = doc.get("tags", [])
        
        # Extract head node config
        head_node = doc.get("head_node", {})
        head_cpu = str(head_node.get("cpu", "4"))
        head_memory_gb = head_node.get("memory_in_gb", 8)
        
        # Build cluster_config JSON (full document minus metadata)
        cluster_config = {k: v for k, v in doc.items() 
                        if k not in ["_id", "cluster_id", "status", "created_on", "last_used"]}
        
        return {
            "cluster_id": cluster_id,
            "user": user,
            "runtime": runtime,
            "cloud_env": cloud_env,
            "is_job_cluster": is_job_cluster,
            "labels": json.dumps(labels) if labels else None,
            "tags": json.dumps(tags) if tags else None,
            "cluster_config": json.dumps(cluster_config),
            "head_cpu": head_cpu,
            "head_memory_gb": head_memory_gb,
        }
    
    def update_mysql_row(self, data: Dict[str, Any]) -> bool:
        """
        Update MySQL row with JSON data.
        
        Args:
            data: Transformed data
            
        Returns:
            True if successful, False otherwise
        """
        update_sql = """
            UPDATE cluster_status
            SET 
                user = %(user)s,
                runtime = %(runtime)s,
                cloud_env = %(cloud_env)s,
                is_job_cluster = %(is_job_cluster)s,
                labels = %(labels)s,
                tags = %(tags)s,
                cluster_config = %(cluster_config)s,
                head_cpu = %(head_cpu)s,
                head_memory_gb = %(head_memory_gb)s
            WHERE cluster_id = %(cluster_id)s
        """
        
        try:
            with self.mysql_conn.cursor() as cursor:
                cursor.execute(update_sql, data)
                if cursor.rowcount == 0:
                    logger.warning(f"No row found for cluster_id: {data['cluster_id']}")
                    return False
                return True
        except Exception as e:
            logger.error(f"Failed to update {data['cluster_id']}: {e}")
            return False
    
    def migrate_batch(self, documents: List[Dict]) -> tuple[int, int, int]:
        """
        Migrate a batch of documents.
        
        Returns:
            Tuple of (migrated, failed, skipped) counts
        """
        migrated = 0
        failed = 0
        skipped = 0
        
        for doc in documents:
            try:
                cluster_id = doc.get("_id") or doc.get("cluster_id")
                if not cluster_id:
                    logger.warning("Document missing cluster_id, skipping")
                    skipped += 1
                    continue
                
                data = self.transform_document(doc)
                
                if self.config.dry_run:
                    logger.info(f"[DRY-RUN] Would update {cluster_id}")
                    migrated += 1
                else:
                    if self.update_mysql_row(data):
                        migrated += 1
                    else:
                        failed += 1
                        
            except Exception as e:
                logger.error(f"Error processing document: {e}")
                failed += 1
        
        return migrated, failed, skipped
    
    def run(self) -> Dict[str, int]:
        """
        Run the migration.
        
        Returns:
            Migration statistics
        """
        logger.info("Starting ES to MySQL migration")
        logger.info(f"Dry run: {self.config.dry_run}")
        logger.info(f"Batch size: {self.config.batch_size}")
        
        try:
            self.connect()
            
            # Get total document count
            count_result = self.es_client.count(index=self.config.es_index)
            total_docs = count_result.get("count", 0)
            logger.info(f"Total documents to migrate: {total_docs}")
            
            scroll_id = None
            batch_num = 0
            
            while True:
                documents, scroll_id = self.get_es_documents(scroll_id)
                if not documents:
                    break
                
                batch_num += 1
                logger.info(f"Processing batch {batch_num} ({len(documents)} documents)")
                
                migrated, failed, skipped = self.migrate_batch(documents)
                self.migrated_count += migrated
                self.failed_count += failed
                self.skipped_count += skipped
                
                if not self.config.dry_run:
                    self.mysql_conn.commit()
                
                logger.info(f"Batch {batch_num} complete: {migrated} migrated, {failed} failed, {skipped} skipped")
            
            # Clear scroll
            if scroll_id:
                try:
                    self.es_client.clear_scroll(scroll_id=scroll_id)
                except Exception:
                    pass
            
            logger.info("Migration complete!")
            logger.info(f"Total migrated: {self.migrated_count}")
            logger.info(f"Total failed: {self.failed_count}")
            logger.info(f"Total skipped: {self.skipped_count}")
            
            return {
                "total": total_docs,
                "migrated": self.migrated_count,
                "failed": self.failed_count,
                "skipped": self.skipped_count
            }
            
        finally:
            self.close()


def main():
    parser = argparse.ArgumentParser(
        description="Migrate cluster data from Elasticsearch to MySQL JSON columns"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without making changes"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of documents per batch (default: 100)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "--es-host",
        default=os.environ.get("ES_HOST", "http://darwin-elasticsearch.darwin.svc.cluster.local:9200"),
        help="Elasticsearch host"
    )
    parser.add_argument(
        "--mysql-host",
        default=os.environ.get("MYSQL_HOST", "darwin-mysql.darwin.svc.cluster.local"),
        help="MySQL host"
    )
    
    args = parser.parse_args()
    
    # Configure logging
    if args.verbose:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")
    
    # Build config from args and environment
    config = MigrationConfig(
        es_host=args.es_host,
        es_username=os.environ.get("VAULT_SERVICE_ES_USERNAME", ""),
        es_password=os.environ.get("VAULT_SERVICE_ES_PASSWORD", ""),
        mysql_host=args.mysql_host,
        mysql_username=os.environ.get("VAULT_SERVICE_MYSQL_USERNAME", ""),
        mysql_password=os.environ.get("VAULT_SERVICE_MYSQL_PASSWORD", ""),
        mysql_database=os.environ.get("CONFIG_SERVICE_MYSQL_DATABASE", "darwin"),
        batch_size=args.batch_size,
        dry_run=args.dry_run
    )
    
    # Run migration
    migrator = ESToMySQLMigrator(config)
    result = migrator.run()
    
    # Exit with error code if there were failures
    if result["failed"] > 0:
        sys.exit(1)
    
    sys.exit(0)


if __name__ == "__main__":
    main()
