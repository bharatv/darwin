"""
MySQL JSON queries for cluster search operations.

These queries replace the Elasticsearch queries previously used for
cluster search, labels, tags, and aggregations.
"""

from typing import List, Dict, Optional, Any


def search_clusters_query(
    search_text: Optional[str] = None,
    filters: Optional[Dict[str, List[str]]] = None,
    exclude_filters: Optional[Dict[str, List[str]]] = None,
    sort_by: str = "last_updated_at",
    sort_order: str = "DESC",
    limit: int = 20,
    offset: int = 0
) -> tuple[str, dict]:
    """
    Build a MySQL query for searching clusters.
    
    Args:
        search_text: Optional text to search in cluster_name
        filters: Optional dict of field -> values to filter by
        exclude_filters: Optional dict of field -> values to exclude
        sort_by: Field to sort by
        sort_order: ASC or DESC
        limit: Max results to return
        offset: Pagination offset
        
    Returns:
        Tuple of (query_string, params_dict)
    """
    conditions = ["1=1"]  # Base condition
    params = {}
    
    # Full-text search on cluster_name
    if search_text:
        conditions.append("MATCH(cluster_name) AGAINST(%(search_text)s IN BOOLEAN MODE)")
        params["search_text"] = f"*{search_text}*"
    
    # Apply filters
    if filters:
        for field, values in filters.items():
            if not values:
                continue
            
            if field == "status":
                placeholders = ", ".join([f"%(status_{i})s" for i in range(len(values))])
                conditions.append(f"status IN ({placeholders})")
                for i, v in enumerate(values):
                    params[f"status_{i}"] = v
            
            elif field == "user":
                placeholders = ", ".join([f"%(user_{i})s" for i in range(len(values))])
                conditions.append(f"user IN ({placeholders})")
                for i, v in enumerate(values):
                    params[f"user_{i}"] = v
            
            elif field == "runtime":
                placeholders = ", ".join([f"%(runtime_{i})s" for i in range(len(values))])
                conditions.append(f"runtime IN ({placeholders})")
                for i, v in enumerate(values):
                    params[f"runtime_{i}"] = v
            
            elif field == "cloud_env":
                placeholders = ", ".join([f"%(cloud_env_{i})s" for i in range(len(values))])
                conditions.append(f"cloud_env IN ({placeholders})")
                for i, v in enumerate(values):
                    params[f"cloud_env_{i}"] = v
            
            elif field == "is_job_cluster":
                conditions.append("is_job_cluster = %(is_job_cluster)s")
                params["is_job_cluster"] = values[0] in ["true", "True", True, 1]
            
            elif field == "tags":
                # Search in cluster_tags table
                tag_placeholders = ", ".join([f"%(tag_{i})s" for i in range(len(values))])
                conditions.append(f"""
                    cluster_id IN (
                        SELECT DISTINCT cluster_id 
                        FROM cluster_tags 
                        WHERE tag IN ({tag_placeholders})
                    )
                """)
                for i, v in enumerate(values):
                    params[f"tag_{i}"] = v
            
            elif field.startswith("labels."):
                # Label filter: labels.key=value
                label_key = field.replace("labels.", "")
                conditions.append(f"""
                    cluster_id IN (
                        SELECT cluster_id 
                        FROM cluster_labels 
                        WHERE label_key = %(label_key_{label_key})s
                        AND label_value IN (%(label_value_{label_key})s)
                    )
                """)
                params[f"label_key_{label_key}"] = label_key
                params[f"label_value_{label_key}"] = values[0] if len(values) == 1 else values
    
    # Apply exclude filters
    if exclude_filters:
        for field, values in exclude_filters.items():
            if not values:
                continue
            
            if field == "status":
                placeholders = ", ".join([f"%(excl_status_{i})s" for i in range(len(values))])
                conditions.append(f"status NOT IN ({placeholders})")
                for i, v in enumerate(values):
                    params[f"excl_status_{i}"] = v
    
    # Validate sort field
    allowed_sort_fields = ["last_updated_at", "created_at", "last_used_at", "cluster_name", "status", "user"]
    if sort_by not in allowed_sort_fields:
        sort_by = "last_updated_at"
    
    # Validate sort order
    sort_order = sort_order.upper()
    if sort_order not in ["ASC", "DESC"]:
        sort_order = "DESC"
    
    query = f"""
        SELECT 
            cluster_id,
            cluster_name,
            artifact_id,
            status,
            active_pods,
            available_memory,
            user,
            runtime,
            cloud_env,
            is_job_cluster,
            labels,
            tags,
            cluster_config,
            created_at,
            last_updated_at,
            last_used_at,
            total_memory_gb
        FROM cluster_status
        WHERE {" AND ".join(conditions)}
        ORDER BY {sort_by} {sort_order}
        LIMIT %(limit)s OFFSET %(offset)s
    """
    
    params["limit"] = limit
    params["offset"] = offset
    
    return query, params


def count_clusters_query(
    search_text: Optional[str] = None,
    filters: Optional[Dict[str, List[str]]] = None,
    exclude_filters: Optional[Dict[str, List[str]]] = None
) -> tuple[str, dict]:
    """
    Build a MySQL query to count matching clusters.
    
    Same parameters as search_clusters_query but returns count.
    """
    conditions = ["1=1"]
    params = {}
    
    if search_text:
        conditions.append("MATCH(cluster_name) AGAINST(%(search_text)s IN BOOLEAN MODE)")
        params["search_text"] = f"*{search_text}*"
    
    # Apply same filters as search query
    if filters:
        for field, values in filters.items():
            if not values:
                continue
            
            if field == "status":
                placeholders = ", ".join([f"%(status_{i})s" for i in range(len(values))])
                conditions.append(f"status IN ({placeholders})")
                for i, v in enumerate(values):
                    params[f"status_{i}"] = v
            
            elif field == "user":
                placeholders = ", ".join([f"%(user_{i})s" for i in range(len(values))])
                conditions.append(f"user IN ({placeholders})")
                for i, v in enumerate(values):
                    params[f"user_{i}"] = v
    
    if exclude_filters:
        for field, values in exclude_filters.items():
            if not values:
                continue
            if field == "status":
                placeholders = ", ".join([f"%(excl_status_{i})s" for i in range(len(values))])
                conditions.append(f"status NOT IN ({placeholders})")
                for i, v in enumerate(values):
                    params[f"excl_status_{i}"] = v
    
    query = f"""
        SELECT COUNT(*) as total
        FROM cluster_status
        WHERE {" AND ".join(conditions)}
    """
    
    return query, params


def get_all_tags_query() -> str:
    """Get all distinct tags across all clusters."""
    return """
        SELECT DISTINCT tag 
        FROM cluster_tags 
        ORDER BY tag
    """


def get_all_users_query() -> str:
    """Get all distinct users across all clusters."""
    return """
        SELECT DISTINCT user 
        FROM cluster_status 
        WHERE user IS NOT NULL 
        ORDER BY user
    """


def get_label_keys_query() -> str:
    """Get all distinct label keys across all clusters."""
    return """
        SELECT DISTINCT label_key 
        FROM cluster_labels 
        ORDER BY label_key
    """


def get_label_values_query(label_key: str) -> tuple[str, dict]:
    """Get all distinct values for a specific label key."""
    return (
        """
        SELECT DISTINCT label_value 
        FROM cluster_labels 
        WHERE label_key = %(label_key)s
        ORDER BY label_value
        """,
        {"label_key": label_key}
    )


def search_labels_query(
    search_text: Optional[str] = None,
    limit: int = 20,
    offset: int = 0
) -> tuple[str, dict]:
    """
    Search for labels matching a text pattern.
    
    Returns label keys and their distinct values.
    """
    params = {"limit": limit, "offset": offset}
    
    if search_text:
        query = """
            SELECT label_key, GROUP_CONCAT(DISTINCT label_value) as values
            FROM cluster_labels
            WHERE label_key LIKE %(search_pattern)s
            OR label_value LIKE %(search_pattern)s
            GROUP BY label_key
            ORDER BY label_key
            LIMIT %(limit)s OFFSET %(offset)s
        """
        params["search_pattern"] = f"%{search_text}%"
    else:
        query = """
            SELECT label_key, GROUP_CONCAT(DISTINCT label_value) as values
            FROM cluster_labels
            GROUP BY label_key
            ORDER BY label_key
            LIMIT %(limit)s OFFSET %(offset)s
        """
    
    return query, params


def get_job_clusters_query(limit: int = 100, offset: int = 0) -> tuple[str, dict]:
    """Get job clusters (ephemeral clusters)."""
    return (
        """
        SELECT cluster_id
        FROM cluster_status
        WHERE is_job_cluster = TRUE
        ORDER BY created_at DESC
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        {"limit": limit, "offset": offset}
    )


# Queries for creating/updating clusters with JSON data

CREATE_CLUSTER_WITH_CONFIG = """
    INSERT INTO cluster_status (
        cluster_id, artifact_id, status, cluster_name, 
        user, runtime, cloud_env, is_job_cluster,
        labels, tags, cluster_config,
        head_cpu, head_memory_gb
    ) VALUES (
        %(cluster_id)s, %(artifact_id)s, %(status)s, %(cluster_name)s,
        %(user)s, %(runtime)s, %(cloud_env)s, %(is_job_cluster)s,
        %(labels)s, %(tags)s, %(cluster_config)s,
        %(head_cpu)s, %(head_memory_gb)s
    )
"""

UPDATE_CLUSTER_CONFIG = """
    UPDATE cluster_status
    SET 
        cluster_config = %(cluster_config)s,
        labels = %(labels)s,
        tags = %(tags)s,
        last_updated_at = CURRENT_TIMESTAMP
    WHERE cluster_id = %(cluster_id)s
"""

GET_CLUSTER_FULL_INFO = """
    SELECT 
        cluster_id,
        cluster_name,
        artifact_id,
        status,
        active_pods,
        available_memory,
        user,
        runtime,
        cloud_env,
        is_job_cluster,
        labels,
        tags,
        cluster_config,
        created_at,
        last_updated_at,
        last_used_at,
        total_memory_gb,
        head_cpu,
        head_memory_gb,
        active_cluster_runid
    FROM cluster_status
    WHERE cluster_id = %(cluster_id)s
"""

UPDATE_CLUSTER_LABELS = """
    UPDATE cluster_status
    SET labels = %(labels)s, last_updated_at = CURRENT_TIMESTAMP
    WHERE cluster_id = %(cluster_id)s
"""

UPDATE_CLUSTER_TAGS = """
    UPDATE cluster_status
    SET tags = %(tags)s, last_updated_at = CURRENT_TIMESTAMP
    WHERE cluster_id = %(cluster_id)s
"""
