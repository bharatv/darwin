"""
Traffic splitting service for deployment strategies.

Manages traffic distribution between multiple deployment versions
for canary and blue-green deployments using ingress annotations.
"""

from typing import Dict, List, Optional
from loguru import logger


class TrafficSplitter:
    """
    Service for managing traffic splits between deployment versions.
    
    Supports weighted routing via NGINX ingress annotations or ALB target groups.
    Traffic weights are expressed as percentages (0-100) and must sum to 100.
    """
    
    def __init__(self):
        """Initialize TrafficSplitter."""
        self.default_backend_weight = 100
    
    def calculate_traffic_split(
        self,
        deployments: List[Dict[str, any]]
    ) -> Dict[str, int]:
        """
        Calculate traffic weights for multiple deployment versions.
        
        Args:
            deployments: List of deployment dicts with 'name' and 'weight' keys
                Example: [
                    {'name': 'serve-v1', 'weight': 90},
                    {'name': 'serve-v2-canary', 'weight': 10}
                ]
        
        Returns:
            Dict mapping deployment names to traffic weight percentages
            
        Raises:
            ValueError: If weights don't sum to 100 or are invalid
        """
        if not deployments:
            raise ValueError("At least one deployment is required")
        
        weights = {}
        total_weight = 0
        
        for deployment in deployments:
            name = deployment.get('name')
            weight = deployment.get('weight', 0)
            
            if not name:
                raise ValueError("Deployment must have a 'name' field")
            
            if not isinstance(weight, (int, float)) or weight < 0 or weight > 100:
                raise ValueError(f"Invalid weight {weight} for deployment {name}. Must be 0-100.")
            
            weights[name] = int(weight)
            total_weight += weight
        
        if total_weight != 100:
            raise ValueError(
                f"Traffic weights must sum to 100%, got {total_weight}%. "
                f"Deployments: {weights}"
            )
        
        logger.info(f"Calculated traffic split: {weights}")
        return weights
    
    def generate_nginx_ingress_annotations(
        self,
        traffic_weights: Dict[str, int],
        namespace: str
    ) -> Dict[str, str]:
        """
        Generate NGINX ingress annotations for weighted traffic splitting.
        
        Uses nginx.ingress.kubernetes.io/service-weights to distribute traffic.
        
        Args:
            traffic_weights: Map of service names to weight percentages
            namespace: Kubernetes namespace for services
            
        Returns:
            Dict of ingress annotations
            
        Example:
            Input: {'serve-v1': 90, 'serve-v2-canary': 10}
            Output: {
                'nginx.ingress.kubernetes.io/service-weights': 
                    'serve.serve-v1: 90, serve.serve-v2-canary: 10'
            }
        """
        if not traffic_weights:
            return {}
        
        # Format: "namespace.service1: weight1, namespace.service2: weight2"
        weight_entries = [
            f"{namespace}.{service_name}: {weight}"
            for service_name, weight in traffic_weights.items()
        ]
        
        annotations = {
            'nginx.ingress.kubernetes.io/service-weights': ', '.join(weight_entries)
        }
        
        logger.debug(f"Generated NGINX annotations: {annotations}")
        return annotations
    
    def generate_alb_target_group_config(
        self,
        traffic_weights: Dict[str, int]
    ) -> List[Dict[str, any]]:
        """
        Generate ALB target group configuration for weighted traffic splitting.
        
        AWS ALB supports multiple target groups with weight distribution.
        
        Args:
            traffic_weights: Map of service names to weight percentages
            
        Returns:
            List of target group configurations for ALB
            
        Example:
            Input: {'serve-v1': 90, 'serve-v2-canary': 10}
            Output: [
                {'serviceName': 'serve-v1', 'weight': 90},
                {'serviceName': 'serve-v2-canary', 'weight': 10}
            ]
        """
        if not traffic_weights:
            return []
        
        target_groups = [
            {'serviceName': service_name, 'weight': weight}
            for service_name, weight in traffic_weights.items()
        ]
        
        logger.debug(f"Generated ALB target groups: {target_groups}")
        return target_groups
    
    def validate_traffic_split(
        self,
        deployments: List[Dict[str, any]]
    ) -> bool:
        """
        Validate that traffic split configuration is valid.
        
        Args:
            deployments: List of deployment configurations with weights
            
        Returns:
            True if valid, raises ValueError otherwise
        """
        try:
            self.calculate_traffic_split(deployments)
            return True
        except ValueError as e:
            logger.error(f"Traffic split validation failed: {e}")
            raise
    
    async def check_deployment_health(
        self,
        resource_id: str,
        kube_cluster: str,
        namespace: str,
        healthcheck_path: str = "/healthcheck",
        timeout_seconds: int = 60
    ) -> bool:
        """
        Check if a deployment is healthy and ready to receive traffic.
        
        Polls DCM for deployment status until healthy or timeout.
        
        Args:
            resource_id: DCM resource ID to check
            kube_cluster: Kubernetes cluster name
            namespace: Kubernetes namespace
            healthcheck_path: Health check endpoint path
            timeout_seconds: Maximum time to wait for health
            
        Returns:
            True if healthy, False otherwise
            
        Note:
            This is a placeholder. Full implementation requires DCM status API
            and potentially direct K8s health check via service endpoints.
        """
        import asyncio
        from ml_serve_core.client.dcm_client import DCMClient
        
        dcm_client = DCMClient()
        elapsed = 0
        check_interval = 5  # seconds
        
        logger.info(
            f"Health checking resource {resource_id} "
            f"(timeout: {timeout_seconds}s)"
        )
        
        while elapsed < timeout_seconds:
            try:
                status = await dcm_client.get_status(
                    resource_id=resource_id,
                    kube_cluster=kube_cluster,
                    kube_namespace=namespace
                )
                
                # Consider RUNNING status as healthy
                # In production, this should also verify readiness/liveness probes
                if status == 'RUNNING':
                    logger.info(f"Resource {resource_id} is healthy")
                    return True
                
                logger.debug(f"Resource {resource_id} status: {status}")
                
            except Exception as e:
                logger.warning(f"Health check error for {resource_id}: {e}")
            
            await asyncio.sleep(check_interval)
            elapsed += check_interval
        
        logger.error(
            f"Resource {resource_id} failed health check after {timeout_seconds}s"
        )
        return False
    
    def get_single_deployment_config(self, deployment_name: str) -> Dict[str, int]:
        """
        Get traffic configuration for a single deployment (100% traffic).
        
        Args:
            deployment_name: Name of the deployment
            
        Returns:
            Traffic weight dict with 100% to single deployment
        """
        return {deployment_name: 100}
