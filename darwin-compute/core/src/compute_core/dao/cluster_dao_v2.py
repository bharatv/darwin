"""
Cluster DAO v2 - MySQL-only implementation without Elasticsearch.

This module provides data access for clusters using only MySQL with JSON columns,
replacing the previous MySQL + Elasticsearch dual-storage approach.
"""

import datetime
import json
from typing import List, Dict, Optional, Any

from loguru import logger

from compute_core.dao.mysql_dao import MySQLDao, CustomTransaction
from compute_core.dao.queries.mysql_json_queries import (
    search_clusters_query,
    count_clusters_query,
    get_all_tags_query,
    get_all_users_query,
    get_label_keys_query,
    get_label_values_query,
    search_labels_query,
    get_job_clusters_query,
    CREATE_CLUSTER_WITH_CONFIG,
    UPDATE_CLUSTER_CONFIG,
    GET_CLUSTER_FULL_INFO,
    UPDATE_CLUSTER_LABELS,
    UPDATE_CLUSTER_TAGS,
)
from compute_core.dao.queries.sql_queries import (
    GET_CLUSTER_STATUS,
    DELETE_CLUSTER,
    GET_CLUSTER_ARTIFACT_ID,
    GET_CLUSTER_RUN_ID,
    START_CLUSTER,
    STOP_CLUSTER,
    RESTART_CLUSTER,
    UPDATE_CLUSTER_NAME,
    GET_CLUSTER_METADATA,
    GET_ALL_CLUSTERS_METADATA,
    GET_CLUSTERS_FROM_LIST,
    GET_CLUSTER_ACTIONS_FOR_CLUSTER_RUN_ID,
    GET_CLUSTER_RUNTIME_IDS,
    GET_FIRST_AND_LAST_EVENT,
    INSERT_CLUSTER_ACTION,
    INSERT_CUSTOM_RUNTIME,
    INSERT_RECENTLY_VISITED,
    GET_RECENTLY_VISITED,
    SET_DELETED_RECENTLY_VISITED,
    GET_ALL_CLUSTERS_RUNNING_FOR_THRESHOLD_TIME,
    CREATE_CLUSTER_CONFIG,
    UPDATE_CLUSTER_CONFIG as UPDATE_CONFIG_VALUE,
    GET_CLUSTER_CONFIG,
    GET_CLUSTER_ACTION,
    UPDATE_CLUSTER_STATUS,
    GET_CLUSTER_LAST_UPDATED_AT,
    GET_CLUSTERS_LAST_USED_BEFORE_DAYS,
    GET_ALL_CLUSTER_CONFIG,
    GET_CLUSTER_LAST_STARTED_TIME,
    GET_CLUSTER_LAST_STOPPED_TIME,
    UPDATE_CLUSTER_LAST_USED_AT,
)
from compute_core.dto.exceptions import ClusterNotFoundError, ClusterRunIdNotFoundError
from compute_core.util.utils import serialize_date


class ClusterDaoV2:
    """
    Cluster DAO using MySQL with JSON columns - no Elasticsearch dependency.
    
    This is a drop-in replacement for ClusterDao that stores all cluster
    configuration in MySQL JSON columns instead of Elasticsearch.
    """
    
    def __init__(self, env: str = None):
        self._mysql_dao = MySQLDao(env)
    
    def healthcheck(self) -> bool:
        """Check MySQL connectivity."""
        return self._mysql_dao.healthcheck()
    
    # ==================== Cluster CRUD ====================
    
    def create_cluster(
        self,
        cluster_id: str,
        artifact_id: str,
        cluster_name: str,
        user: str,
        runtime: str,
        cloud_env: str = "",
        labels: Optional[Dict[str, str]] = None,
        tags: Optional[List[str]] = None,
        cluster_config: Optional[Dict[str, Any]] = None,
        is_job_cluster: bool = False,
        head_cpu: str = "4",
        head_memory_gb: int = 8
    ) -> int:
        """
        Create a new cluster record.
        
        Args:
            cluster_id: Unique cluster identifier
            artifact_id: Helm artifact ID
            cluster_name: Display name
            user: Owner email/username
            runtime: Ray runtime version
            cloud_env: Cloud environment identifier
            labels: User-defined labels
            tags: User-defined tags
            cluster_config: Full cluster configuration
            is_job_cluster: Whether this is an ephemeral job cluster
            head_cpu: Head node CPU allocation
            head_memory_gb: Head node memory in GB
            
        Returns:
            Number of rows affected
        """
        sql_data = {
            "cluster_id": cluster_id,
            "artifact_id": artifact_id,
            "status": "inactive",
            "cluster_name": cluster_name,
            "user": user,
            "runtime": runtime,
            "cloud_env": cloud_env,
            "is_job_cluster": is_job_cluster,
            "labels": json.dumps(labels) if labels else None,
            "tags": json.dumps(tags) if tags else None,
            "cluster_config": json.dumps(cluster_config) if cluster_config else None,
            "head_cpu": head_cpu,
            "head_memory_gb": head_memory_gb,
        }
        
        logger.info(f"Creating cluster {cluster_id} for user {user}")
        return self._mysql_dao.create(CREATE_CLUSTER_WITH_CONFIG, sql_data)
    
    def get_cluster_info(self, cluster_id: str) -> Dict[str, Any]:
        """
        Get full cluster information.
        
        Args:
            cluster_id: Cluster identifier
            
        Returns:
            Cluster data dictionary
            
        Raises:
            ClusterNotFoundError: If cluster doesn't exist
        """
        result = self._mysql_dao.read(GET_CLUSTER_FULL_INFO, {"cluster_id": cluster_id})
        if not result:
            logger.error(f"Cluster {cluster_id} not found")
            raise ClusterNotFoundError(cluster_id)
        
        cluster = result[0]
        # Parse JSON fields
        if cluster.get("labels") and isinstance(cluster["labels"], str):
            cluster["labels"] = json.loads(cluster["labels"])
        if cluster.get("tags") and isinstance(cluster["tags"], str):
            cluster["tags"] = json.loads(cluster["tags"])
        if cluster.get("cluster_config") and isinstance(cluster["cluster_config"], str):
            cluster["cluster_config"] = json.loads(cluster["cluster_config"])
        
        # Serialize datetime fields
        for date_field in ["created_at", "last_updated_at", "last_used_at"]:
            if cluster.get(date_field):
                cluster[date_field] = serialize_date(cluster[date_field])
        
        return cluster
    
    def delete_cluster(self, cluster_id: str) -> int:
        """
        Delete a cluster record.
        
        Args:
            cluster_id: Cluster identifier
            
        Returns:
            Number of rows affected
        """
        logger.info(f"Deleting cluster {cluster_id}")
        return self._mysql_dao.delete(DELETE_CLUSTER, {"cluster_id": cluster_id})
    
    def update_cluster_config(
        self,
        cluster_id: str,
        cluster_config: Dict[str, Any],
        labels: Optional[Dict[str, str]] = None,
        tags: Optional[List[str]] = None
    ) -> int:
        """
        Update cluster configuration.
        
        Args:
            cluster_id: Cluster identifier
            cluster_config: Full cluster configuration
            labels: Optional labels update
            tags: Optional tags update
            
        Returns:
            Number of rows affected
        """
        sql_data = {
            "cluster_id": cluster_id,
            "cluster_config": json.dumps(cluster_config),
            "labels": json.dumps(labels) if labels else None,
            "tags": json.dumps(tags) if tags else None,
        }
        return self._mysql_dao.update(UPDATE_CLUSTER_CONFIG, sql_data)
    
    # ==================== Status Operations ====================
    
    def get_cluster_status(self, cluster_id: str) -> str:
        """Get the current status of a cluster."""
        result = self._mysql_dao.read(GET_CLUSTER_STATUS, {"cluster_id": cluster_id})
        if not result:
            raise ClusterNotFoundError(cluster_id)
        return result[0]["status"]
    
    def update_status(
        self,
        cluster_id: str,
        status: str,
        active_pods: int,
        available_memory: int,
        last_updated_at: Optional[datetime.datetime] = None
    ) -> Optional[int]:
        """
        Update cluster status.
        
        Args:
            cluster_id: Cluster identifier
            status: New status
            active_pods: Number of active pods
            available_memory: Available memory in MB
            last_updated_at: Optional timestamp for optimistic locking
            
        Returns:
            Number of rows affected, or None if update was skipped
        """
        with CustomTransaction(self._mysql_dao.get_write_connection()) as mysql_connection:
            if last_updated_at:
                mysql_connection.execute_query(GET_CLUSTER_LAST_UPDATED_AT, {"cluster_id": cluster_id})
                last_updated = mysql_connection.cursor.fetchone()
                if last_updated and last_updated["last_updated_at"] > last_updated_at:
                    logger.info(f"Cluster status of {cluster_id} not updated - stale")
                    return None
            
            mysql_connection.execute_query(
                UPDATE_CLUSTER_STATUS,
                {
                    "status": status,
                    "cluster_id": cluster_id,
                    "active_pods": active_pods,
                    "available_memory": available_memory,
                }
            )
            updated_rows = mysql_connection.cursor.rowcount
            logger.info(f"Updated status of {cluster_id} to {status}")
            return updated_rows
    
    def start_cluster(self, cluster_id: str, run_id: str) -> int:
        """Start a cluster by updating its status."""
        return self._mysql_dao.update(START_CLUSTER, {"run_id": run_id, "cluster_id": cluster_id})
    
    def stop_cluster(self, cluster_id: str) -> int:
        """Stop a cluster by updating its status."""
        return self._mysql_dao.update(STOP_CLUSTER, {"cluster_id": cluster_id})
    
    def restart_cluster(self, cluster_id: str) -> int:
        """Restart a cluster."""
        return self._mysql_dao.update(RESTART_CLUSTER, {"cluster_id": cluster_id})
    
    # ==================== Search Operations ====================
    
    def search_cluster(
        self,
        search_text: Optional[str] = None,
        filters: Optional[Dict[str, List[str]]] = None,
        exclude_filters: Optional[Dict[str, List[str]]] = None,
        sort_by: str = "last_updated_at",
        sort_order: str = "DESC",
        limit: int = 20,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Search for clusters with filters.
        
        Args:
            search_text: Optional text to search in cluster_name
            filters: Filter criteria
            exclude_filters: Exclusion criteria
            sort_by: Sort field
            sort_order: Sort direction
            limit: Max results
            offset: Pagination offset
            
        Returns:
            Dictionary with 'hits' list and 'total' count
        """
        # Get search results
        query, params = search_clusters_query(
            search_text=search_text,
            filters=filters,
            exclude_filters=exclude_filters,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset
        )
        results = self._mysql_dao.read(query, params)
        
        # Get total count
        count_query, count_params = count_clusters_query(
            search_text=search_text,
            filters=filters,
            exclude_filters=exclude_filters
        )
        count_result = self._mysql_dao.read(count_query, count_params)
        total = count_result[0]["total"] if count_result else 0
        
        # Parse JSON fields and format response
        hits = []
        for row in results:
            if row.get("labels") and isinstance(row["labels"], str):
                row["labels"] = json.loads(row["labels"])
            if row.get("tags") and isinstance(row["tags"], str):
                row["tags"] = json.loads(row["tags"])
            if row.get("cluster_config") and isinstance(row["cluster_config"], str):
                row["cluster_config"] = json.loads(row["cluster_config"])
            
            for date_field in ["created_at", "last_updated_at", "last_used_at"]:
                if row.get(date_field):
                    row[date_field] = serialize_date(row[date_field])
            
            hits.append(row)
        
        return {
            "hits": hits,
            "total": total
        }
    
    def search_cluster_name(self, name: str) -> List[Dict[str, Any]]:
        """Search for clusters by name prefix."""
        query = """
            SELECT cluster_id, cluster_name, user, status
            FROM cluster_status
            WHERE cluster_name LIKE %(name_pattern)s
            LIMIT 10
        """
        return self._mysql_dao.read(query, {"name_pattern": f"{name}%"})
    
    # ==================== Labels & Tags ====================
    
    def get_all_tags(self) -> List[str]:
        """Get all distinct tags."""
        result = self._mysql_dao.read(get_all_tags_query())
        return [row["tag"] for row in result]
    
    def get_all_users(self) -> List[str]:
        """Get all distinct users."""
        result = self._mysql_dao.read(get_all_users_query())
        return [row["user"] for row in result]
    
    def get_label_keys(self) -> List[str]:
        """Get all distinct label keys."""
        result = self._mysql_dao.read(get_label_keys_query())
        return [row["label_key"] for row in result]
    
    def get_label_values(self, label_key: str) -> List[str]:
        """Get all distinct values for a label key."""
        query, params = get_label_values_query(label_key)
        result = self._mysql_dao.read(query, params)
        return [row["label_value"] for row in result]
    
    def search_labels(
        self,
        search_text: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Search for labels."""
        query, params = search_labels_query(search_text, limit, offset)
        result = self._mysql_dao.read(query, params)
        return [
            {
                "key": row["label_key"],
                "values": row["values"].split(",") if row["values"] else []
            }
            for row in result
        ]
    
    def update_cluster_labels(self, cluster_id: str, labels: Dict[str, str]) -> int:
        """Update cluster labels."""
        return self._mysql_dao.update(
            UPDATE_CLUSTER_LABELS,
            {"cluster_id": cluster_id, "labels": json.dumps(labels)}
        )
    
    def update_cluster_tags(self, cluster_id: str, tags: List[str]) -> int:
        """Update cluster tags."""
        return self._mysql_dao.update(
            UPDATE_CLUSTER_TAGS,
            {"cluster_id": cluster_id, "tags": json.dumps(tags)}
        )
    
    # ==================== Job Clusters ====================
    
    def get_job_cluster_ids(self, limit: int = 100, offset: int = 0) -> List[str]:
        """Get job cluster IDs."""
        query, params = get_job_clusters_query(limit, offset)
        result = self._mysql_dao.read(query, params)
        return [row["cluster_id"] for row in result]
    
    # ==================== Other Operations ====================
    
    def get_cluster_artifact_id(self, cluster_id: str) -> str:
        """Get the artifact ID for a cluster."""
        result = self._mysql_dao.read(GET_CLUSTER_ARTIFACT_ID, {"cluster_id": cluster_id})
        if not result:
            raise ClusterNotFoundError(cluster_id)
        return result[0]["artifact_id"]
    
    def get_cluster_run_id(self, cluster_id: str) -> str:
        """Get the current run ID for a cluster."""
        result = self._mysql_dao.read(GET_CLUSTER_RUN_ID, {"cluster_id": cluster_id})
        if not result:
            raise ClusterNotFoundError(cluster_id)
        run_id = result[0].get("run_id")
        if not run_id:
            raise ClusterRunIdNotFoundError(cluster_id)
        return run_id
    
    def update_cluster_name(self, cluster_id: str, cluster_name: str) -> int:
        """Update cluster display name."""
        return self._mysql_dao.update(
            UPDATE_CLUSTER_NAME,
            {"cluster_id": cluster_id, "name": cluster_name}
        )
    
    def get_cluster_metadata(self, cluster_id: str) -> Dict[str, Any]:
        """Get cluster metadata."""
        result = self._mysql_dao.read(GET_CLUSTER_METADATA, {"cluster_id": cluster_id})
        if not result:
            raise ClusterNotFoundError(cluster_id)
        metadata = result[0]
        metadata["last_updated_at"] = serialize_date(metadata["last_updated_at"])
        return metadata
    
    def get_all_clusters_metadata(self) -> List[Dict[str, Any]]:
        """Get metadata for all clusters."""
        result = self._mysql_dao.read(GET_ALL_CLUSTERS_METADATA)
        for row in result:
            row["last_updated_at"] = serialize_date(row["last_updated_at"])
        return result
    
    def update_last_used_time(self, cluster_id: str) -> int:
        """Update the last used timestamp."""
        return self._mysql_dao.update(
            UPDATE_CLUSTER_LAST_USED_AT,
            {"cluster_id": cluster_id}
        )
    
    # ==================== Cluster Actions ====================
    
    def insert_cluster_action(
        self,
        run_id: str,
        action: str,
        message: str,
        cluster_id: str,
        artifact_id: str
    ) -> int:
        """Insert a cluster action record."""
        return self._mysql_dao.create(
            INSERT_CLUSTER_ACTION,
            {
                "run_id": run_id,
                "action": action,
                "message": message,
                "cluster_id": cluster_id,
                "artifact_id": artifact_id,
            }
        )
    
    def get_cluster_actions(self, run_id: str, sort_order: str = "DESC") -> List[Dict[str, Any]]:
        """Get actions for a cluster run."""
        sort_order = sort_order.upper() if sort_order.upper() in ["ASC", "DESC"] else "DESC"
        query = GET_CLUSTER_ACTIONS_FOR_CLUSTER_RUN_ID % {"run_id": run_id, "sort_order": sort_order}
        result = self._mysql_dao.read(query)
        for action in result:
            action["updated_at"] = serialize_date(action["updated_at"])
        return result
    
    # ==================== Recently Visited ====================
    
    def add_recently_visited(self, cluster_id: str, user_email: str) -> int:
        """Add a recently visited record."""
        return self._mysql_dao.update(
            INSERT_RECENTLY_VISITED,
            {"user_email": user_email, "cluster_id": cluster_id}
        )
    
    def get_recently_visited(self, user_email: str) -> List[Dict[str, Any]]:
        """Get recently visited clusters for a user."""
        result = self._mysql_dao.read(GET_RECENTLY_VISITED, {"user_email": user_email})
        for row in result:
            row["visited_at"] = serialize_date(row["visited_at"])
        return result
    
    def delete_recently_visited(self, cluster_id: str) -> int:
        """Delete recently visited records for a cluster."""
        return self._mysql_dao.delete(SET_DELETED_RECENTLY_VISITED, {"cluster_id": cluster_id})
    
    # ==================== Config ====================
    
    def create_cluster_config(self, key: str, value: str) -> int:
        """Create a cluster config entry."""
        return self._mysql_dao.create(CREATE_CLUSTER_CONFIG, {"key": key, "value": value})
    
    def update_cluster_config_value(self, key: str, value: str) -> int:
        """Update a cluster config entry."""
        return self._mysql_dao.update(UPDATE_CONFIG_VALUE, {"key": key, "value": value})
    
    def get_cluster_config_value(self, key: str) -> Optional[str]:
        """Get a cluster config value."""
        result = self._mysql_dao.read(GET_CLUSTER_CONFIG, {"key": key})
        return result[0]["value"] if result else None
    
    def get_all_cluster_configs(self, offset: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all cluster config entries."""
        return self._mysql_dao.read(GET_ALL_CLUSTER_CONFIG, {"offset": offset, "limit": limit})
    
    # ==================== Time-based Queries ====================
    
    def get_clusters_running_for_threshold_time(self, threshold_minutes: int) -> List[Dict[str, Any]]:
        """Get clusters running longer than threshold."""
        query = GET_ALL_CLUSTERS_RUNNING_FOR_THRESHOLD_TIME % {
            "cluster_running_time_threshold_in_minutes": threshold_minutes
        }
        result = self._mysql_dao.read(query)
        for row in result:
            row["last_started_at"] = serialize_date(row["last_started_at"])
        return result
    
    def get_cluster_last_started_at(self, cluster_id: str) -> Optional[datetime.datetime]:
        """Get the last started time."""
        result = self._mysql_dao.read(GET_CLUSTER_LAST_STARTED_TIME, {"cluster_id": cluster_id})
        if not result:
            return None
        return result[0].get("last_started_time")
    
    def get_cluster_last_stopped_at(self, cluster_id: str) -> Optional[datetime.datetime]:
        """Get the last stopped time."""
        result = self._mysql_dao.read(GET_CLUSTER_LAST_STOPPED_TIME, {"cluster_id": cluster_id})
        if not result:
            return None
        return result[0].get("last_stopped_time")
    
    def get_clusters_last_used_before_days(self, days: int, cluster_ids: List[str]) -> List[Dict[str, Any]]:
        """Get clusters not used within specified days."""
        if not cluster_ids:
            return []
        
        if len(cluster_ids) > 1:
            query = GET_CLUSTERS_LAST_USED_BEFORE_DAYS + str(tuple(cluster_ids))
        else:
            query = GET_CLUSTERS_LAST_USED_BEFORE_DAYS + str(tuple(cluster_ids)).replace(",)", ")")
        
        return self._mysql_dao.read(query=query, data={"days": days})
