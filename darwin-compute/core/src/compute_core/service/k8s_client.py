"""
Multi-cluster Kubernetes client for DarwinRayCluster CRD operations.

This module provides clients to manage DarwinRayCluster custom resources
across multiple Kubernetes clusters.
"""

import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from loguru import logger

from kubernetes import client, config
from kubernetes.client.rest import ApiException


@dataclass
class ClusterConfig:
    """Configuration for a Kubernetes cluster."""
    name: str
    kubeconfig_path: str
    namespace: str = "ray"


class MultiClusterClient:
    """
    Manages connections to multiple Kubernetes clusters via kubeconfigs.
    
    This client maintains API clients for each configured cluster,
    allowing operations across multiple Kubernetes environments.
    """
    
    def __init__(self, cluster_configs: List[ClusterConfig]):
        """
        Initialize multi-cluster client.
        
        Args:
            cluster_configs: List of cluster configurations
        """
        self._clients: Dict[str, client.CustomObjectsApi] = {}
        self._core_clients: Dict[str, client.CoreV1Api] = {}
        self._namespaces: Dict[str, str] = {}
        
        for cfg in cluster_configs:
            try:
                api_client = config.new_client_from_config(config_file=cfg.kubeconfig_path)
                self._clients[cfg.name] = client.CustomObjectsApi(api_client)
                self._core_clients[cfg.name] = client.CoreV1Api(api_client)
                self._namespaces[cfg.name] = cfg.namespace
                logger.info(f"Initialized K8s client for cluster: {cfg.name}")
            except Exception as e:
                logger.error(f"Failed to initialize K8s client for cluster {cfg.name}: {e}")
                raise
    
    def get_custom_objects_client(self, cloud_env: str) -> client.CustomObjectsApi:
        """Get CustomObjectsApi client for a specific cluster."""
        if cloud_env not in self._clients:
            raise ValueError(f"Unknown cloud_env: {cloud_env}")
        return self._clients[cloud_env]
    
    def get_core_client(self, cloud_env: str) -> client.CoreV1Api:
        """Get CoreV1Api client for a specific cluster."""
        if cloud_env not in self._core_clients:
            raise ValueError(f"Unknown cloud_env: {cloud_env}")
        return self._core_clients[cloud_env]
    
    def get_namespace(self, cloud_env: str) -> str:
        """Get the namespace for a specific cluster."""
        return self._namespaces.get(cloud_env, "ray")
    
    def list_clusters(self) -> List[str]:
        """List all configured cluster names."""
        return list(self._clients.keys())


class DarwinRayClusterClient:
    """
    Client for DarwinRayCluster CRD operations across multiple clusters.
    
    This client provides CRUD operations for DarwinRayCluster custom resources,
    replacing the previous DCM HTTP-based approach with direct K8s API calls.
    """
    
    GROUP = "compute.darwin.io"
    VERSION = "v1alpha1"
    PLURAL = "darwinrayclusters"
    KIND = "DarwinRayCluster"
    
    def __init__(self, multi_cluster_client: MultiClusterClient):
        """
        Initialize DarwinRayCluster client.
        
        Args:
            multi_cluster_client: Multi-cluster client for K8s access
        """
        self._multi_client = multi_cluster_client
    
    def get_cluster(self, cluster_id: str, cloud_env: str, namespace: Optional[str] = None) -> dict:
        """
        Get a DarwinRayCluster by ID.
        
        Args:
            cluster_id: The cluster ID (CR name)
            cloud_env: Target cloud environment/cluster
            namespace: Optional namespace override
            
        Returns:
            The DarwinRayCluster resource as a dictionary
        """
        api = self._multi_client.get_custom_objects_client(cloud_env)
        ns = namespace or self._multi_client.get_namespace(cloud_env)
        
        try:
            return api.get_namespaced_custom_object(
                group=self.GROUP,
                version=self.VERSION,
                namespace=ns,
                plural=self.PLURAL,
                name=cluster_id
            )
        except ApiException as e:
            if e.status == 404:
                logger.warning(f"DarwinRayCluster {cluster_id} not found in {cloud_env}")
                raise ClusterNotFoundError(cluster_id, cloud_env)
            logger.error(f"Failed to get DarwinRayCluster {cluster_id}: {e}")
            raise
    
    def create_cluster(
        self,
        cluster_id: str,
        cloud_env: str,
        spec: dict,
        namespace: Optional[str] = None,
        labels: Optional[Dict[str, str]] = None,
        annotations: Optional[Dict[str, str]] = None
    ) -> dict:
        """
        Create a new DarwinRayCluster.
        
        Args:
            cluster_id: The cluster ID (CR name)
            cloud_env: Target cloud environment/cluster
            spec: The DarwinRayCluster spec
            namespace: Optional namespace override
            labels: Optional labels for the CR
            annotations: Optional annotations for the CR
            
        Returns:
            The created DarwinRayCluster resource
        """
        api = self._multi_client.get_custom_objects_client(cloud_env)
        ns = namespace or self._multi_client.get_namespace(cloud_env)
        
        body = {
            "apiVersion": f"{self.GROUP}/{self.VERSION}",
            "kind": self.KIND,
            "metadata": {
                "name": cluster_id,
                "namespace": ns,
                "labels": labels or {},
                "annotations": annotations or {}
            },
            "spec": spec
        }
        
        try:
            result = api.create_namespaced_custom_object(
                group=self.GROUP,
                version=self.VERSION,
                namespace=ns,
                plural=self.PLURAL,
                body=body
            )
            logger.info(f"Created DarwinRayCluster {cluster_id} in {cloud_env}")
            return result
        except ApiException as e:
            if e.status == 409:
                logger.warning(f"DarwinRayCluster {cluster_id} already exists in {cloud_env}")
                raise ClusterAlreadyExistsError(cluster_id, cloud_env)
            logger.error(f"Failed to create DarwinRayCluster {cluster_id}: {e}")
            raise
    
    def update_cluster(
        self,
        cluster_id: str,
        cloud_env: str,
        spec: dict,
        namespace: Optional[str] = None
    ) -> dict:
        """
        Update an existing DarwinRayCluster spec.
        
        Args:
            cluster_id: The cluster ID (CR name)
            cloud_env: Target cloud environment/cluster
            spec: The updated DarwinRayCluster spec
            namespace: Optional namespace override
            
        Returns:
            The updated DarwinRayCluster resource
        """
        api = self._multi_client.get_custom_objects_client(cloud_env)
        ns = namespace or self._multi_client.get_namespace(cloud_env)
        
        try:
            # Get current resource to preserve metadata
            current = self.get_cluster(cluster_id, cloud_env, namespace)
            current["spec"] = spec
            
            result = api.replace_namespaced_custom_object(
                group=self.GROUP,
                version=self.VERSION,
                namespace=ns,
                plural=self.PLURAL,
                name=cluster_id,
                body=current
            )
            logger.info(f"Updated DarwinRayCluster {cluster_id} in {cloud_env}")
            return result
        except ApiException as e:
            logger.error(f"Failed to update DarwinRayCluster {cluster_id}: {e}")
            raise
    
    def patch_cluster(
        self,
        cluster_id: str,
        cloud_env: str,
        patch: dict,
        namespace: Optional[str] = None
    ) -> dict:
        """
        Patch a DarwinRayCluster (partial update).
        
        Args:
            cluster_id: The cluster ID (CR name)
            cloud_env: Target cloud environment/cluster
            patch: The patch to apply (merge patch format)
            namespace: Optional namespace override
            
        Returns:
            The patched DarwinRayCluster resource
        """
        api = self._multi_client.get_custom_objects_client(cloud_env)
        ns = namespace or self._multi_client.get_namespace(cloud_env)
        
        try:
            result = api.patch_namespaced_custom_object(
                group=self.GROUP,
                version=self.VERSION,
                namespace=ns,
                plural=self.PLURAL,
                name=cluster_id,
                body=patch
            )
            logger.info(f"Patched DarwinRayCluster {cluster_id} in {cloud_env}")
            return result
        except ApiException as e:
            logger.error(f"Failed to patch DarwinRayCluster {cluster_id}: {e}")
            raise
    
    def delete_cluster(
        self,
        cluster_id: str,
        cloud_env: str,
        namespace: Optional[str] = None
    ) -> dict:
        """
        Delete a DarwinRayCluster.
        
        Args:
            cluster_id: The cluster ID (CR name)
            cloud_env: Target cloud environment/cluster
            namespace: Optional namespace override
            
        Returns:
            The deletion status
        """
        api = self._multi_client.get_custom_objects_client(cloud_env)
        ns = namespace or self._multi_client.get_namespace(cloud_env)
        
        try:
            result = api.delete_namespaced_custom_object(
                group=self.GROUP,
                version=self.VERSION,
                namespace=ns,
                plural=self.PLURAL,
                name=cluster_id
            )
            logger.info(f"Deleted DarwinRayCluster {cluster_id} in {cloud_env}")
            return result
        except ApiException as e:
            if e.status == 404:
                logger.warning(f"DarwinRayCluster {cluster_id} not found for deletion")
                return {"status": "not_found"}
            logger.error(f"Failed to delete DarwinRayCluster {cluster_id}: {e}")
            raise
    
    def list_clusters(
        self,
        cloud_env: str,
        namespace: Optional[str] = None,
        label_selector: Optional[str] = None
    ) -> List[dict]:
        """
        List DarwinRayClusters in a namespace.
        
        Args:
            cloud_env: Target cloud environment/cluster
            namespace: Optional namespace override
            label_selector: Optional label selector (e.g., "user=john")
            
        Returns:
            List of DarwinRayCluster resources
        """
        api = self._multi_client.get_custom_objects_client(cloud_env)
        ns = namespace or self._multi_client.get_namespace(cloud_env)
        
        try:
            result = api.list_namespaced_custom_object(
                group=self.GROUP,
                version=self.VERSION,
                namespace=ns,
                plural=self.PLURAL,
                label_selector=label_selector or ""
            )
            return result.get("items", [])
        except ApiException as e:
            logger.error(f"Failed to list DarwinRayClusters in {cloud_env}: {e}")
            raise
    
    def get_cluster_status(
        self,
        cluster_id: str,
        cloud_env: str,
        namespace: Optional[str] = None
    ) -> dict:
        """
        Get the status of a DarwinRayCluster.
        
        This reads the status directly from the CRD - no polling needed
        as the operator keeps it updated in real-time.
        
        Args:
            cluster_id: The cluster ID (CR name)
            cloud_env: Target cloud environment/cluster
            namespace: Optional namespace override
            
        Returns:
            The status subresource of the DarwinRayCluster
        """
        cluster = self.get_cluster(cluster_id, cloud_env, namespace)
        return cluster.get("status", {})
    
    def start_cluster(
        self,
        cluster_id: str,
        cloud_env: str,
        namespace: Optional[str] = None
    ) -> dict:
        """
        Start a suspended cluster by setting suspend=false.
        
        Args:
            cluster_id: The cluster ID (CR name)
            cloud_env: Target cloud environment/cluster
            namespace: Optional namespace override
            
        Returns:
            The updated DarwinRayCluster resource
        """
        return self.patch_cluster(
            cluster_id=cluster_id,
            cloud_env=cloud_env,
            patch={"spec": {"suspend": False}},
            namespace=namespace
        )
    
    def stop_cluster(
        self,
        cluster_id: str,
        cloud_env: str,
        namespace: Optional[str] = None
    ) -> dict:
        """
        Stop a cluster by setting suspend=true.
        
        Args:
            cluster_id: The cluster ID (CR name)
            cloud_env: Target cloud environment/cluster
            namespace: Optional namespace override
            
        Returns:
            The updated DarwinRayCluster resource
        """
        return self.patch_cluster(
            cluster_id=cluster_id,
            cloud_env=cloud_env,
            patch={"spec": {"suspend": True}},
            namespace=namespace
        )
    
    def restart_cluster(
        self,
        cluster_id: str,
        cloud_env: str,
        namespace: Optional[str] = None
    ) -> dict:
        """
        Restart a cluster by stopping then starting.
        
        This is achieved by adding a restart annotation that the operator
        will detect and handle.
        
        Args:
            cluster_id: The cluster ID (CR name)
            cloud_env: Target cloud environment/cluster
            namespace: Optional namespace override
            
        Returns:
            The updated DarwinRayCluster resource
        """
        import time
        restart_annotation = {"metadata": {"annotations": {"compute.darwin.io/restart-at": str(int(time.time()))}}}
        return self.patch_cluster(
            cluster_id=cluster_id,
            cloud_env=cloud_env,
            patch=restart_annotation,
            namespace=namespace
        )


class ClusterNotFoundError(Exception):
    """Raised when a cluster is not found."""
    def __init__(self, cluster_id: str, cloud_env: str):
        self.cluster_id = cluster_id
        self.cloud_env = cloud_env
        super().__init__(f"Cluster {cluster_id} not found in {cloud_env}")


class ClusterAlreadyExistsError(Exception):
    """Raised when trying to create a cluster that already exists."""
    def __init__(self, cluster_id: str, cloud_env: str):
        self.cluster_id = cluster_id
        self.cloud_env = cloud_env
        super().__init__(f"Cluster {cluster_id} already exists in {cloud_env}")


def create_multi_cluster_client_from_env() -> MultiClusterClient:
    """
    Create a MultiClusterClient from environment variables.
    
    Environment variables:
        DARWIN_KUBECONFIGS: Comma-separated list of cluster:path pairs
            e.g., "prod:/path/to/prod.kubeconfig,stag:/path/to/stag.kubeconfig"
        DARWIN_RAY_NAMESPACE: Default namespace for Ray clusters (default: "ray")
    
    Returns:
        Configured MultiClusterClient
    """
    kubeconfigs = os.environ.get("DARWIN_KUBECONFIGS", "")
    default_namespace = os.environ.get("DARWIN_RAY_NAMESPACE", "ray")
    
    if not kubeconfigs:
        # Fallback to single cluster using default kubeconfig
        logger.info("No DARWIN_KUBECONFIGS set, using default kubeconfig")
        try:
            config.load_incluster_config()
            default_path = None  # In-cluster config
        except config.ConfigException:
            default_path = os.path.expanduser("~/.kube/config")
        
        return MultiClusterClient([
            ClusterConfig(
                name="default",
                kubeconfig_path=default_path or "",
                namespace=default_namespace
            )
        ])
    
    configs = []
    for entry in kubeconfigs.split(","):
        if ":" not in entry:
            logger.warning(f"Invalid kubeconfig entry: {entry}")
            continue
        name, path = entry.split(":", 1)
        configs.append(ClusterConfig(
            name=name.strip(),
            kubeconfig_path=path.strip(),
            namespace=default_namespace
        ))
    
    return MultiClusterClient(configs)


def build_darwin_ray_cluster_spec(
    name: str,
    user: str,
    runtime: str,
    head_cpu: str,
    head_memory_gb: int,
    cloud_env: str = "",
    worker_groups: Optional[List[dict]] = None,
    labels: Optional[Dict[str, str]] = None,
    tags: Optional[List[str]] = None,
    auto_termination_minutes: Optional[int] = None,
    enable_jupyter: bool = True,
    image: Optional[str] = None,
    **kwargs
) -> dict:
    """
    Build a DarwinRayCluster spec from parameters.
    
    This is a helper function to construct the spec dictionary
    that matches the DarwinRayCluster CRD schema.
    
    Args:
        name: Display name of the cluster
        user: Owner of the cluster
        runtime: Ray runtime version
        head_cpu: CPU for head node (e.g., "4")
        head_memory_gb: Memory in GB for head node
        cloud_env: Cloud environment identifier
        worker_groups: Optional list of worker group configs
        labels: Optional user-defined labels
        tags: Optional user-defined tags
        auto_termination_minutes: Optional idle timeout in minutes
        enable_jupyter: Whether to enable Jupyter (default: True)
        image: Optional custom image
        **kwargs: Additional spec fields
        
    Returns:
        DarwinRayCluster spec dictionary
    """
    spec = {
        "name": name,
        "user": user,
        "runtime": runtime,
        "cloudEnv": cloud_env,
        "headNode": {
            "resources": {
                "cpu": head_cpu,
                "memoryGB": head_memory_gb
            },
            "enableJupyter": enable_jupyter
        }
    }
    
    if labels:
        spec["labels"] = labels
    
    if tags:
        spec["tags"] = tags
    
    if worker_groups:
        spec["workerGroups"] = [
            {
                "name": wg.get("name", f"worker-group-{i}"),
                "replicas": wg.get("replicas", 1),
                "minReplicas": wg.get("min_replicas", 0),
                "maxReplicas": wg.get("max_replicas", wg.get("replicas", 1)),
                "resources": {
                    "cpu": wg.get("cpu", "2"),
                    "memoryGB": wg.get("memory_gb", 4)
                }
            }
            for i, wg in enumerate(worker_groups)
        ]
    
    if auto_termination_minutes:
        spec["autoTermination"] = {
            "enabled": True,
            "idleTimeoutMinutes": auto_termination_minutes
        }
    
    if image:
        spec["advanceConfig"] = spec.get("advanceConfig", {})
        spec["advanceConfig"]["image"] = image
    
    # Add any additional kwargs to advanceConfig
    for key, value in kwargs.items():
        if key not in spec:
            spec["advanceConfig"] = spec.get("advanceConfig", {})
            spec["advanceConfig"][key] = value
    
    return spec
