"""
Status Poller Job v2 - Reads status from DarwinRayCluster CRD.

This version replaces the polling-based status updates with direct
reads from the DarwinRayCluster CRD status, which is kept up-to-date
by the darwin-ray-operator in real-time.

The operator uses K8s watches to maintain status, so polling is only
needed for synchronizing with MySQL (for API queries) and triggering
events.
"""

import os
import time
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum

from loguru import logger

from compute_core.service.k8s_client import (
    DarwinRayClusterClient,
    MultiClusterClient,
    create_multi_cluster_client_from_env,
    ClusterNotFoundError,
)
from compute_core.dao.cluster_dao_v2 import ClusterDaoV2
from compute_core.service.event_service import EventService
from compute_core.constant.event_states import EventStates


class ClusterPhase(str, Enum):
    """Cluster phases matching the CRD status."""
    INACTIVE = "Inactive"
    CREATING = "Creating"
    HEAD_NODE_UP = "HeadNodeUp"
    JUPYTER_UP = "JupyterUp"
    ACTIVE = "Active"
    FAILED = "Failed"
    TERMINATING = "Terminating"


@dataclass
class ClusterStatusSync:
    """Represents a cluster status synchronization."""
    cluster_id: str
    cloud_env: str
    old_phase: Optional[str]
    new_phase: str
    active_pods: int
    available_memory_gb: int
    message: str
    should_update_db: bool = True
    should_send_event: bool = False


class StatusPollerV2:
    """
    Status poller that reads from DarwinRayCluster CRD status.
    
    This poller:
    1. Lists all clusters from MySQL
    2. Reads status from DarwinRayCluster CRD (real-time, maintained by operator)
    3. Syncs status to MySQL (for API queries)
    4. Sends Chronos events on phase transitions
    """
    
    def __init__(
        self,
        cluster_dao: ClusterDaoV2,
        drc_client: DarwinRayClusterClient,
        event_service: Optional[EventService] = None
    ):
        self.cluster_dao = cluster_dao
        self.drc_client = drc_client
        self.event_service = event_service
        
        # Phase to event mapping
        self.phase_events = {
            ClusterPhase.CREATING: EventStates.CLUSTER_CREATING,
            ClusterPhase.HEAD_NODE_UP: EventStates.CLUSTER_HEAD_NODE_UP,
            ClusterPhase.JUPYTER_UP: EventStates.CLUSTER_JUPYTER_UP,
            ClusterPhase.ACTIVE: EventStates.CLUSTER_ACTIVE,
            ClusterPhase.FAILED: EventStates.CLUSTER_FAILED,
            ClusterPhase.INACTIVE: EventStates.CLUSTER_STOPPED,
            ClusterPhase.TERMINATING: EventStates.CLUSTER_TERMINATING,
        }
    
    def sync_cluster_status(self, cluster_id: str, cloud_env: str) -> Optional[ClusterStatusSync]:
        """
        Sync status for a single cluster from CRD to MySQL.
        
        Args:
            cluster_id: The cluster ID
            cloud_env: The cloud environment/cluster name
            
        Returns:
            ClusterStatusSync if status changed, None otherwise
        """
        try:
            # Get current status from MySQL
            try:
                db_status = self.cluster_dao.get_cluster_status(cluster_id)
            except Exception:
                db_status = None
            
            # Get status from DarwinRayCluster CRD
            try:
                crd_status = self.drc_client.get_cluster_status(cluster_id, cloud_env)
            except ClusterNotFoundError:
                logger.warning(f"DarwinRayCluster {cluster_id} not found in {cloud_env}")
                return None
            except Exception as e:
                logger.error(f"Failed to get CRD status for {cluster_id}: {e}")
                return None
            
            # Extract status fields
            new_phase = crd_status.get("phase", ClusterPhase.INACTIVE.value)
            active_pods = crd_status.get("activePods", 0)
            available_memory_gb = crd_status.get("availableMemoryGB", 0)
            message = crd_status.get("message", "")
            
            # Check if status changed
            old_phase = self._map_db_status_to_phase(db_status) if db_status else None
            should_update = old_phase != new_phase or db_status is None
            should_send_event = old_phase != new_phase and old_phase is not None
            
            return ClusterStatusSync(
                cluster_id=cluster_id,
                cloud_env=cloud_env,
                old_phase=old_phase,
                new_phase=new_phase,
                active_pods=active_pods,
                available_memory_gb=available_memory_gb,
                message=message,
                should_update_db=should_update,
                should_send_event=should_send_event
            )
            
        except Exception as e:
            logger.error(f"Error syncing status for cluster {cluster_id}: {e}")
            return None
    
    def apply_status_sync(self, sync: ClusterStatusSync) -> bool:
        """
        Apply a status sync to MySQL and send events.
        
        Args:
            sync: The status sync to apply
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if sync.should_update_db:
                db_status = self._map_phase_to_db_status(sync.new_phase)
                self.cluster_dao.update_status(
                    cluster_id=sync.cluster_id,
                    status=db_status,
                    active_pods=sync.active_pods,
                    available_memory=sync.available_memory_gb * 1024  # Convert to MB
                )
                logger.info(f"Updated {sync.cluster_id} status to {sync.new_phase}")
            
            if sync.should_send_event and self.event_service:
                event_type = self.phase_events.get(ClusterPhase(sync.new_phase))
                if event_type:
                    self.event_service.send_cluster_event(
                        cluster_id=sync.cluster_id,
                        event_type=event_type,
                        message=sync.message
                    )
                    logger.info(f"Sent event {event_type} for {sync.cluster_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error applying status sync for {sync.cluster_id}: {e}")
            return False
    
    def poll_all_clusters(self) -> List[ClusterStatusSync]:
        """
        Poll status for all active clusters.
        
        Returns:
            List of status syncs that were applied
        """
        applied_syncs = []
        
        try:
            # Get all clusters that need status sync
            # Only poll clusters that are not inactive
            search_result = self.cluster_dao.search_cluster(
                filters={"status": ["creating", "head_node_up", "jupyter_up", "active"]},
                limit=1000
            )
            clusters = search_result.get("hits", [])
            
            logger.info(f"Polling status for {len(clusters)} active clusters")
            
            for cluster in clusters:
                cluster_id = cluster["cluster_id"]
                cloud_env = cluster.get("cloud_env", "default")
                
                sync = self.sync_cluster_status(cluster_id, cloud_env)
                if sync and (sync.should_update_db or sync.should_send_event):
                    if self.apply_status_sync(sync):
                        applied_syncs.append(sync)
            
            return applied_syncs
            
        except Exception as e:
            logger.error(f"Error polling all clusters: {e}")
            return applied_syncs
    
    def _map_db_status_to_phase(self, db_status: str) -> str:
        """Map MySQL status enum to CRD phase."""
        mapping = {
            "inactive": ClusterPhase.INACTIVE.value,
            "creating": ClusterPhase.CREATING.value,
            "head_node_up": ClusterPhase.HEAD_NODE_UP.value,
            "jupyter_up": ClusterPhase.JUPYTER_UP.value,
            "active": ClusterPhase.ACTIVE.value,
            "head_node_died": ClusterPhase.FAILED.value,
            "worker_nodes_died": ClusterPhase.ACTIVE.value,  # Workers died but cluster still active
            "cluster_died": ClusterPhase.FAILED.value,
            "worker_nodes_scaled": ClusterPhase.ACTIVE.value,
        }
        return mapping.get(db_status, ClusterPhase.INACTIVE.value)
    
    def _map_phase_to_db_status(self, phase: str) -> str:
        """Map CRD phase to MySQL status enum."""
        mapping = {
            ClusterPhase.INACTIVE.value: "inactive",
            ClusterPhase.CREATING.value: "creating",
            ClusterPhase.HEAD_NODE_UP.value: "head_node_up",
            ClusterPhase.JUPYTER_UP.value: "jupyter_up",
            ClusterPhase.ACTIVE.value: "active",
            ClusterPhase.FAILED.value: "cluster_died",
            ClusterPhase.TERMINATING.value: "inactive",
        }
        return mapping.get(phase, "inactive")


def run_status_poller_job(poll_interval_seconds: int = 30):
    """
    Run the status poller job.
    
    This is a lightweight polling job that syncs CRD status to MySQL.
    The actual status calculation is done by the darwin-ray-operator.
    
    Args:
        poll_interval_seconds: Interval between polls (default: 30s)
    """
    logger.info("Starting Status Poller Job v2")
    
    # Initialize clients
    cluster_dao = ClusterDaoV2()
    multi_cluster_client = create_multi_cluster_client_from_env()
    drc_client = DarwinRayClusterClient(multi_cluster_client)
    event_service = None  # TODO: Initialize EventService if Chronos is enabled
    
    poller = StatusPollerV2(
        cluster_dao=cluster_dao,
        drc_client=drc_client,
        event_service=event_service
    )
    
    while True:
        try:
            start_time = time.time()
            syncs = poller.poll_all_clusters()
            elapsed = time.time() - start_time
            
            logger.info(f"Polled {len(syncs)} clusters with status changes in {elapsed:.2f}s")
            
        except Exception as e:
            logger.error(f"Error in status poller job: {e}")
        
        time.sleep(poll_interval_seconds)


if __name__ == "__main__":
    poll_interval = int(os.environ.get("STATUS_POLL_INTERVAL_SECONDS", "30"))
    run_status_poller_job(poll_interval)
