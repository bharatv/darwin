import base64
from typing import Optional, Dict, Any
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from loguru import logger


class FlaggerClient:
    """
    Kubernetes client for interacting with Flagger Canary Custom Resources.
    
    Provides methods to query canary status, approve promotions, and manage
    progressive delivery workflows.
    """
    
    def __init__(self, kubeconfig_path: Optional[str] = None):
        """
        Initialize Flagger client.
        
        Args:
            kubeconfig_path: Optional path to kubeconfig file. If None, uses in-cluster config.
        """
        try:
            if kubeconfig_path:
                config.load_kube_config(config_file=kubeconfig_path)
            else:
                # Try in-cluster config first, fallback to default kubeconfig
                try:
                    config.load_incluster_config()
                except config.ConfigException:
                    config.load_kube_config()
            
            self.custom_api = client.CustomObjectsApi()
            self.core_api = client.CoreV1Api()
            
        except Exception as e:
            logger.error(f"Failed to initialize FlaggerClient: {e}")
            raise
    
    async def get_canary_status(
        self, 
        canary_name: str, 
        namespace: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get the status of a Flagger Canary resource.
        
        Args:
            canary_name: Name of the Canary CR
            namespace: Kubernetes namespace
            
        Returns:
            Dict containing canary status, or None if not found
        """
        try:
            canary = self.custom_api.get_namespaced_custom_object(
                group="flagger.app",
                version="v1beta1",
                namespace=namespace,
                plural="canaries",
                name=canary_name
            )
            
            status = canary.get("status", {})
            
            return {
                "name": canary.get("metadata", {}).get("name"),
                "namespace": namespace,
                "phase": status.get("phase", "Unknown"),
                "canary_weight": status.get("canaryWeight", 0),
                "failed_checks": status.get("failedChecks", 0),
                "iterations": status.get("iterations", 0),
                "last_transition_time": status.get("lastTransitionTime"),
                "conditions": status.get("conditions", []),
                "tracked_configs": status.get("trackedConfigs", {}),
            }
            
        except ApiException as e:
            if e.status == 404:
                logger.warning(f"Canary {canary_name} not found in namespace {namespace}")
                return None
            logger.error(f"Error fetching canary status: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in get_canary_status: {e}")
            raise
    
    async def approve_canary_promotion(
        self, 
        canary_name: str, 
        namespace: str
    ) -> bool:
        """
        Approve a canary promotion by updating the Canary CR.
        
        This sets the confirm-promotion annotation to trigger Flagger to proceed.
        
        Args:
            canary_name: Name of the Canary CR
            namespace: Kubernetes namespace
            
        Returns:
            True if promotion approved successfully, False otherwise
        """
        try:
            # Get current canary
            canary = self.custom_api.get_namespaced_custom_object(
                group="flagger.app",
                version="v1beta1",
                namespace=namespace,
                plural="canaries",
                name=canary_name
            )
            
            # Add/update confirm-promotion annotation
            annotations = canary.get("metadata", {}).get("annotations", {})
            annotations["flagger.app/confirm-promotion"] = "true"
            
            canary["metadata"]["annotations"] = annotations
            
            # Update canary
            self.custom_api.patch_namespaced_custom_object(
                group="flagger.app",
                version="v1beta1",
                namespace=namespace,
                plural="canaries",
                name=canary_name,
                body=canary
            )
            
            logger.info(f"Approved canary promotion for {canary_name} in {namespace}")
            return True
            
        except ApiException as e:
            logger.error(f"Error approving canary promotion: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error in approve_canary_promotion: {e}")
            return False
    
    async def rollback_canary(
        self, 
        canary_name: str, 
        namespace: str
    ) -> bool:
        """
        Trigger a canary rollback by updating the Canary CR.
        
        Args:
            canary_name: Name of the Canary CR
            namespace: Kubernetes namespace
            
        Returns:
            True if rollback triggered successfully, False otherwise
        """
        try:
            # Get current canary
            canary = self.custom_api.get_namespaced_custom_object(
                group="flagger.app",
                version="v1beta1",
                namespace=namespace,
                plural="canaries",
                name=canary_name
            )
            
            # Add rollback annotation
            annotations = canary.get("metadata", {}).get("annotations", {})
            annotations["flagger.app/rollback"] = "true"
            
            canary["metadata"]["annotations"] = annotations
            
            # Update canary
            self.custom_api.patch_namespaced_custom_object(
                group="flagger.app",
                version="v1beta1",
                namespace=namespace,
                plural="canaries",
                name=canary_name,
                body=canary
            )
            
            logger.info(f"Triggered rollback for {canary_name} in {namespace}")
            return True
            
        except ApiException as e:
            logger.error(f"Error triggering canary rollback: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error in rollback_canary: {e}")
            return False
    
    async def is_canary_ready(
        self, 
        canary_name: str, 
        namespace: str
    ) -> bool:
        """
        Check if canary deployment is ready (all pods running).
        
        Args:
            canary_name: Name of the Canary CR
            namespace: Kubernetes namespace
            
        Returns:
            True if canary is ready, False otherwise
        """
        try:
            status = await self.get_canary_status(canary_name, namespace)
            if not status:
                return False
            
            phase = status.get("phase", "")
            return phase in ["Progressing", "Succeeded", "Promoting"]
            
        except Exception as e:
            logger.error(f"Error checking canary readiness: {e}")
            return False
    
    async def is_waiting_for_promotion(
        self, 
        canary_name: str, 
        namespace: str
    ) -> bool:
        """
        Check if canary is waiting for manual promotion approval.
        
        Args:
            canary_name: Name of the Canary CR
            namespace: Kubernetes namespace
            
        Returns:
            True if waiting for promotion, False otherwise
        """
        try:
            status = await self.get_canary_status(canary_name, namespace)
            if not status:
                return False
            
            phase = status.get("phase", "")
            
            # Check if in WaitingPromotion phase
            if phase == "WaitingPromotion":
                return True
            
            # Also check conditions for confirm-promotion webhook
            conditions = status.get("conditions", [])
            for condition in conditions:
                if condition.get("type") == "Promoted" and condition.get("status") == "Unknown":
                    reason = condition.get("reason", "")
                    if "waiting" in reason.lower() or "manual" in reason.lower():
                        return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking promotion status: {e}")
            return False
