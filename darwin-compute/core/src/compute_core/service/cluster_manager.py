"""
Cluster Manager - Unified interface for managing Ray clusters.

This module provides a high-level interface for cluster management
that can use either:
1. DarwinRayCluster CRD (new architecture via darwin-ray-operator)
2. Darwin Cluster Manager (legacy HTTP-based approach)

The implementation is selected via feature flag to enable gradual migration.
"""

import os
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum

from loguru import logger


class ClusterManagerBackend(str, Enum):
    """Backend type for cluster management."""
    DARWIN_RAY_OPERATOR = "operator"  # New: Uses DarwinRayCluster CRD
    DARWIN_CLUSTER_MANAGER = "dcm"    # Legacy: Uses DCM HTTP API


@dataclass
class ClusterSpec:
    """Specification for creating/updating a cluster."""
    name: str
    user: str
    runtime: str
    cloud_env: str
    head_cpu: str
    head_memory_gb: int
    worker_groups: Optional[List[Dict[str, Any]]] = None
    labels: Optional[Dict[str, str]] = None
    tags: Optional[List[str]] = None
    auto_termination_minutes: Optional[int] = None
    enable_jupyter: bool = True
    image: Optional[str] = None
    advance_config: Optional[Dict[str, Any]] = None


@dataclass
class ClusterStatus:
    """Status of a cluster."""
    phase: str
    active_pods: int
    available_memory_gb: int
    head_pod_ip: Optional[str] = None
    jupyter_url: Optional[str] = None
    ray_dashboard_url: Optional[str] = None
    message: str = ""


class ClusterManagerInterface(ABC):
    """Abstract interface for cluster management backends."""
    
    @abstractmethod
    def create_cluster(self, cluster_id: str, spec: ClusterSpec) -> Dict[str, Any]:
        """Create a new cluster."""
        pass
    
    @abstractmethod
    def start_cluster(self, cluster_id: str, cloud_env: str) -> Dict[str, Any]:
        """Start a stopped cluster."""
        pass
    
    @abstractmethod
    def stop_cluster(self, cluster_id: str, cloud_env: str) -> Dict[str, Any]:
        """Stop a running cluster."""
        pass
    
    @abstractmethod
    def restart_cluster(self, cluster_id: str, cloud_env: str) -> Dict[str, Any]:
        """Restart a cluster."""
        pass
    
    @abstractmethod
    def delete_cluster(self, cluster_id: str, cloud_env: str) -> Dict[str, Any]:
        """Delete a cluster."""
        pass
    
    @abstractmethod
    def get_cluster_status(self, cluster_id: str, cloud_env: str) -> ClusterStatus:
        """Get cluster status."""
        pass
    
    @abstractmethod
    def update_cluster(self, cluster_id: str, spec: ClusterSpec) -> Dict[str, Any]:
        """Update cluster configuration."""
        pass


class DarwinRayOperatorBackend(ClusterManagerInterface):
    """
    Cluster manager backend using DarwinRayCluster CRD.
    
    This backend creates DarwinRayCluster custom resources directly,
    which are then reconciled by the darwin-ray-operator.
    """
    
    def __init__(self):
        from compute_core.service.k8s_client import (
            DarwinRayClusterClient,
            MultiClusterClient,
            create_multi_cluster_client_from_env,
            build_darwin_ray_cluster_spec,
        )
        
        self._multi_client = create_multi_cluster_client_from_env()
        self._drc_client = DarwinRayClusterClient(self._multi_client)
        self._build_spec = build_darwin_ray_cluster_spec
        
        logger.info("Initialized DarwinRayOperator backend")
    
    def create_cluster(self, cluster_id: str, spec: ClusterSpec) -> Dict[str, Any]:
        """Create a DarwinRayCluster CR."""
        drc_spec = self._build_spec(
            name=spec.name,
            user=spec.user,
            runtime=spec.runtime,
            head_cpu=spec.head_cpu,
            head_memory_gb=spec.head_memory_gb,
            cloud_env=spec.cloud_env,
            worker_groups=spec.worker_groups,
            labels=spec.labels,
            tags=spec.tags,
            auto_termination_minutes=spec.auto_termination_minutes,
            enable_jupyter=spec.enable_jupyter,
            image=spec.image,
        )
        
        return self._drc_client.create_cluster(
            cluster_id=cluster_id,
            cloud_env=spec.cloud_env,
            spec=drc_spec,
            labels={"compute.darwin.io/user": spec.user},
            annotations={"compute.darwin.io/runtime": spec.runtime}
        )
    
    def start_cluster(self, cluster_id: str, cloud_env: str) -> Dict[str, Any]:
        """Start cluster by setting suspend=false."""
        return self._drc_client.start_cluster(cluster_id, cloud_env)
    
    def stop_cluster(self, cluster_id: str, cloud_env: str) -> Dict[str, Any]:
        """Stop cluster by setting suspend=true."""
        return self._drc_client.stop_cluster(cluster_id, cloud_env)
    
    def restart_cluster(self, cluster_id: str, cloud_env: str) -> Dict[str, Any]:
        """Restart cluster."""
        return self._drc_client.restart_cluster(cluster_id, cloud_env)
    
    def delete_cluster(self, cluster_id: str, cloud_env: str) -> Dict[str, Any]:
        """Delete the DarwinRayCluster CR."""
        return self._drc_client.delete_cluster(cluster_id, cloud_env)
    
    def get_cluster_status(self, cluster_id: str, cloud_env: str) -> ClusterStatus:
        """Get status from CRD."""
        status = self._drc_client.get_cluster_status(cluster_id, cloud_env)
        return ClusterStatus(
            phase=status.get("phase", "Unknown"),
            active_pods=status.get("activePods", 0),
            available_memory_gb=status.get("availableMemoryGB", 0),
            head_pod_ip=status.get("headPodIP"),
            jupyter_url=status.get("jupyterURL"),
            ray_dashboard_url=status.get("rayDashboardURL"),
            message=status.get("message", "")
        )
    
    def update_cluster(self, cluster_id: str, spec: ClusterSpec) -> Dict[str, Any]:
        """Update the DarwinRayCluster spec."""
        drc_spec = self._build_spec(
            name=spec.name,
            user=spec.user,
            runtime=spec.runtime,
            head_cpu=spec.head_cpu,
            head_memory_gb=spec.head_memory_gb,
            cloud_env=spec.cloud_env,
            worker_groups=spec.worker_groups,
            labels=spec.labels,
            tags=spec.tags,
            auto_termination_minutes=spec.auto_termination_minutes,
            enable_jupyter=spec.enable_jupyter,
            image=spec.image,
        )
        
        return self._drc_client.update_cluster(
            cluster_id=cluster_id,
            cloud_env=spec.cloud_env,
            spec=drc_spec
        )


class LegacyDCMBackend(ClusterManagerInterface):
    """
    Legacy cluster manager backend using Darwin Cluster Manager.
    
    This backend uses HTTP calls to DCM for cluster operations.
    Maintained for backward compatibility during migration.
    """
    
    def __init__(self):
        from compute_core.service.dcm import DarwinClusterManager
        
        self._dcm = DarwinClusterManager()
        logger.info("Initialized Legacy DCM backend")
    
    def create_cluster(self, cluster_id: str, spec: ClusterSpec) -> Dict[str, Any]:
        """Create cluster via DCM."""
        # Note: DCM expects a compute_request object, not ClusterSpec
        # This would need to be adapted based on the existing DCM interface
        raise NotImplementedError("Legacy DCM create requires compute_request object")
    
    def start_cluster(self, cluster_id: str, cloud_env: str) -> Dict[str, Any]:
        """Start cluster via DCM."""
        # Use existing DCM methods
        return self._dcm.start_cluster(cluster_id, cloud_env)
    
    def stop_cluster(self, cluster_id: str, cloud_env: str) -> Dict[str, Any]:
        """Stop cluster via DCM."""
        return self._dcm.stop_cluster(cluster_id, cloud_env)
    
    def restart_cluster(self, cluster_id: str, cloud_env: str) -> Dict[str, Any]:
        """Restart cluster via DCM."""
        return self._dcm.restart_cluster(cluster_id, cloud_env)
    
    def delete_cluster(self, cluster_id: str, cloud_env: str) -> Dict[str, Any]:
        """Delete cluster via DCM."""
        return self._dcm.delete_cluster(cluster_id, cloud_env)
    
    def get_cluster_status(self, cluster_id: str, cloud_env: str) -> ClusterStatus:
        """Get status via DCM."""
        result = self._dcm.cluster_status(cluster_id, "ray", cloud_env)
        # Parse DCM response
        pods = result.get("pods", [])
        active_pods = len([p for p in pods if p.get("status") == "Running"])
        
        return ClusterStatus(
            phase="Active" if active_pods > 0 else "Inactive",
            active_pods=active_pods,
            available_memory_gb=0,  # Not directly available from DCM
            message=""
        )
    
    def update_cluster(self, cluster_id: str, spec: ClusterSpec) -> Dict[str, Any]:
        """Update cluster via DCM."""
        raise NotImplementedError("Legacy DCM update requires compute_request object")


def get_cluster_manager_backend() -> ClusterManagerInterface:
    """
    Get the configured cluster manager backend.
    
    The backend is selected via CLUSTER_MANAGER_BACKEND env var:
    - "operator": Use DarwinRayCluster CRD (new architecture)
    - "dcm": Use Darwin Cluster Manager (legacy)
    
    Default: "operator" (new architecture)
    """
    backend_type = os.environ.get("CLUSTER_MANAGER_BACKEND", "operator")
    
    if backend_type == ClusterManagerBackend.DARWIN_RAY_OPERATOR.value:
        return DarwinRayOperatorBackend()
    elif backend_type == ClusterManagerBackend.DARWIN_CLUSTER_MANAGER.value:
        return LegacyDCMBackend()
    else:
        logger.warning(f"Unknown backend type {backend_type}, defaulting to operator")
        return DarwinRayOperatorBackend()


class ClusterManager:
    """
    High-level cluster manager that delegates to the configured backend.
    
    Usage:
        manager = ClusterManager()
        manager.create_cluster("my-cluster", spec)
        status = manager.get_status("my-cluster", "prod")
    """
    
    def __init__(self, backend: Optional[ClusterManagerInterface] = None):
        self._backend = backend or get_cluster_manager_backend()
    
    def create_cluster(self, cluster_id: str, spec: ClusterSpec) -> Dict[str, Any]:
        """Create a new cluster."""
        logger.info(f"Creating cluster {cluster_id}")
        return self._backend.create_cluster(cluster_id, spec)
    
    def start_cluster(self, cluster_id: str, cloud_env: str) -> Dict[str, Any]:
        """Start a stopped cluster."""
        logger.info(f"Starting cluster {cluster_id} in {cloud_env}")
        return self._backend.start_cluster(cluster_id, cloud_env)
    
    def stop_cluster(self, cluster_id: str, cloud_env: str) -> Dict[str, Any]:
        """Stop a running cluster."""
        logger.info(f"Stopping cluster {cluster_id} in {cloud_env}")
        return self._backend.stop_cluster(cluster_id, cloud_env)
    
    def restart_cluster(self, cluster_id: str, cloud_env: str) -> Dict[str, Any]:
        """Restart a cluster."""
        logger.info(f"Restarting cluster {cluster_id} in {cloud_env}")
        return self._backend.restart_cluster(cluster_id, cloud_env)
    
    def delete_cluster(self, cluster_id: str, cloud_env: str) -> Dict[str, Any]:
        """Delete a cluster."""
        logger.info(f"Deleting cluster {cluster_id} in {cloud_env}")
        return self._backend.delete_cluster(cluster_id, cloud_env)
    
    def get_status(self, cluster_id: str, cloud_env: str) -> ClusterStatus:
        """Get cluster status."""
        return self._backend.get_cluster_status(cluster_id, cloud_env)
    
    def update_cluster(self, cluster_id: str, spec: ClusterSpec) -> Dict[str, Any]:
        """Update cluster configuration."""
        logger.info(f"Updating cluster {cluster_id}")
        return self._backend.update_cluster(cluster_id, spec)
