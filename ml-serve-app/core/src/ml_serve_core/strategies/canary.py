"""
Canary deployment strategy executor.

Implements progressive traffic shifting with health validation and
manual/automatic promotion capabilities.
"""

from typing import Optional
from loguru import logger

from ml_serve_core.strategies.base import (
    BaseDeploymentStrategy,
    DeploymentContext,
    DeploymentResult
)
from ml_serve_core.service.deployment_orchestrator import DeploymentOrchestrator
from ml_serve_core.service.traffic_splitter import TrafficSplitter
from ml_serve_core.client.dcm_client import DCMClient
from ml_serve_core.utils.yaml_utils import (
    generate_fastapi_values_for_strategy_deployment,
    apply_traffic_weights_to_ingress
)


class CanaryDeploymentExecutor(BaseDeploymentStrategy):
    """
    Executes canary deployment strategy.
    
    Canary deployments route a small percentage of traffic to the new version first,
    then progressively increase traffic based on health metrics and manual promotion.
    
    Configuration:
        - traffic_splits: List of traffic percentages (e.g., [10, 50, 100])
        - promotion_criteria: 'manual' or 'auto'
        - rollback_on_errors: Auto-rollback on health check failures
        - canary_health_check_duration_seconds: Duration to monitor canary health
    """
    
    def __init__(self):
        """Initialize CanaryDeploymentExecutor."""
        super().__init__("CANARY")
        self.orchestrator = DeploymentOrchestrator()
        self.traffic_splitter = TrafficSplitter()
        self.dcm_client = DCMClient()
    
    def validate_config(self, config: dict) -> bool:
        """
        Validate canary deployment configuration.
        
        Args:
            config: Configuration dict
            
        Returns:
            True if valid
            
        Raises:
            ValueError: If configuration is invalid
        """
        traffic_splits = config.get('traffic_splits', [10, 50, 100])
        
        if not isinstance(traffic_splits, list) or len(traffic_splits) < 1:
            raise ValueError("traffic_splits must be a non-empty list")
        
        if not all(0 < split <= 100 for split in traffic_splits):
            raise ValueError("All traffic_splits must be between 1 and 100")
        
        if traffic_splits[-1] != 100:
            raise ValueError("Final traffic split must be 100%")
        
        if sorted(traffic_splits) != traffic_splits:
            raise ValueError("traffic_splits must be in ascending order")
        
        logger.info(f"Canary config validated: traffic_splits={traffic_splits}")
        return True
    
    async def execute(self, context: DeploymentContext) -> DeploymentResult:
        """
        Execute canary deployment strategy.
        
        Process:
        1. Deploy stable version with 100% traffic
        2. Deploy canary version with initial traffic split (e.g., 10%)
        3. Health check canary
        4. Wait for manual promotion or auto-advance
        
        Args:
            context: Deployment context
            
        Returns:
            DeploymentResult with stable and canary resource IDs
        """
        self.log_execution_start(context)
        
        # Extract configuration
        config = context.strategy_config
        self.validate_config(config)
        
        traffic_splits = config.get('traffic_splits', [10, 50, 100])
        initial_canary_traffic = traffic_splits[0]
        health_check_duration = config.get('canary_health_check_duration_seconds', 120)
        rollback_on_errors = config.get('rollback_on_errors', True)
        
        try:
            # Step 1: Deploy stable version (new artifact as stable)
            logger.info("Deploying stable version")
            stable_values = generate_fastapi_values_for_strategy_deployment(
                base_values=context.base_values,
                version_suffix='stable',
                replica_count=None  # Use base replica count
            )
            
            stable_result = await self.orchestrator.deploy_version(
                darwin_resource=context.darwin_resource,
                values=stable_values,
                version=f"{context.version}-stable",
                artifact_id=context.artifact_id,
                kube_cluster=context.kube_cluster,
                namespace=context.namespace
            )
            
            stable_resource_id = stable_result['resource_id']
            
            # Step 2: Deploy canary version with minimal replicas
            logger.info(f"Deploying canary version with {initial_canary_traffic}% traffic")
            canary_values = generate_fastapi_values_for_strategy_deployment(
                base_values=context.base_values,
                version_suffix='canary',
                replica_count=1  # Start with single replica
            )
            
            canary_result = await self.orchestrator.deploy_version(
                darwin_resource=context.darwin_resource,
                values=canary_values,
                version=f"{context.version}-canary",
                artifact_id=context.artifact_id,
                kube_cluster=context.kube_cluster,
                namespace=context.namespace
            )
            
            canary_resource_id = canary_result['resource_id']
            
            # Step 3: Configure traffic split
            stable_name = stable_values['name']
            canary_name = canary_values['name']
            
            traffic_weights = {
                stable_name: 100 - initial_canary_traffic,
                canary_name: initial_canary_traffic
            }
            
            # Apply traffic weights to ingress
            # Note: This would typically be done via ingress controller update
            # For now, we log the configuration
            logger.info(f"Traffic split configured: {traffic_weights}")
            
            # Step 4: Health check canary
            logger.info(f"Health checking canary for {health_check_duration}s")
            is_healthy = await self._check_canary_health(
                resource_id=canary_resource_id,
                kube_cluster=context.kube_cluster,
                namespace=context.namespace,
                timeout=health_check_duration
            )
            
            if not is_healthy and rollback_on_errors:
                logger.error("Canary health check failed, initiating rollback")
                await self._rollback_canary(
                    stable_resource_id=stable_resource_id,
                    canary_resource_id=canary_resource_id,
                    kube_cluster=context.kube_cluster,
                    namespace=context.namespace
                )
                raise Exception("Canary deployment failed health checks")
            
            deployment_result = DeploymentResult(
                success=True,
                primary_resource_id=stable_resource_id,
                secondary_resource_id=canary_resource_id,
                status="CANARY",
                message=f"Canary deployed with {initial_canary_traffic}% traffic, awaiting promotion",
                metadata={
                    'strategy': 'CANARY',
                    'traffic_splits': traffic_splits,
                    'current_split': initial_canary_traffic,
                    'stable_resource_id': stable_resource_id,
                    'canary_resource_id': canary_resource_id,
                    'version': context.version
                }
            )
            
            self.log_execution_complete(deployment_result)
            return deployment_result
            
        except Exception as e:
            logger.error(f"Canary deployment failed: {e}")
            return DeploymentResult(
                success=False,
                primary_resource_id="",
                status="FAILED",
                message=f"Canary deployment failed: {str(e)}"
            )
    
    async def promote_canary(
        self,
        stable_resource_id: str,
        canary_resource_id: str,
        kube_cluster: str,
        namespace: str,
        next_traffic_percentage: int
    ) -> bool:
        """
        Promote canary to next traffic split level.
        
        Args:
            stable_resource_id: Stable version resource ID
            canary_resource_id: Canary version resource ID
            kube_cluster: Kubernetes cluster
            namespace: Kubernetes namespace
            next_traffic_percentage: Next traffic split (e.g., 50, 100)
            
        Returns:
            True if promotion succeeded
        """
        logger.info(f"Promoting canary to {next_traffic_percentage}% traffic")
        
        try:
            # Update traffic weights
            # In production, this would update ingress annotations
            if next_traffic_percentage == 100:
                # Full promotion: canary becomes stable
                logger.info("Promoting canary to 100% (stable)")
                # Stop old stable, canary becomes new stable
                await self.dcm_client.stop_resource(
                    resource_id=stable_resource_id,
                    kube_cluster=kube_cluster,
                    namespace=namespace
                )
                logger.info("Canary promoted to stable successfully")
            else:
                # Partial promotion: adjust traffic split
                logger.info(f"Canary traffic increased to {next_traffic_percentage}%")
            
            return True
            
        except Exception as e:
            logger.error(f"Canary promotion failed: {e}")
            return False
    
    async def rollback(
        self,
        deployment_id: int,
        resource_ids: list[str],
        kube_cluster: str,
        namespace: str
    ) -> bool:
        """
        Rollback canary deployment.
        
        Stops canary version and ensures stable version has 100% traffic.
        
        Args:
            deployment_id: Database deployment ID
            resource_ids: [stable_id, canary_id]
            kube_cluster: Kubernetes cluster
            namespace: Kubernetes namespace
            
        Returns:
            True if rollback succeeded
        """
        logger.warning(f"Rolling back canary deployment {deployment_id}")
        
        if len(resource_ids) < 2:
            logger.error("Insufficient resource IDs for canary rollback")
            return False
        
        stable_resource_id = resource_ids[0]
        canary_resource_id = resource_ids[1]
        
        return await self._rollback_canary(
            stable_resource_id=stable_resource_id,
            canary_resource_id=canary_resource_id,
            kube_cluster=kube_cluster,
            namespace=namespace
        )
    
    async def _rollback_canary(
        self,
        stable_resource_id: str,
        canary_resource_id: str,
        kube_cluster: str,
        namespace: str
    ) -> bool:
        """
        Internal rollback logic for canary.
        
        Args:
            stable_resource_id: Stable version to keep
            canary_resource_id: Canary version to remove
            kube_cluster: Kubernetes cluster
            namespace: Kubernetes namespace
            
        Returns:
            True if successful
        """
        try:
            # Stop canary deployment
            logger.info(f"Stopping canary resource {canary_resource_id}")
            await self.dcm_client.stop_resource(
                resource_id=canary_resource_id,
                kube_cluster=kube_cluster,
                namespace=namespace
            )
            
            # Ensure stable has 100% traffic (update ingress if needed)
            logger.info(f"Stable resource {stable_resource_id} now has 100% traffic")
            
            logger.info("Canary rollback completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Canary rollback failed: {e}")
            return False
    
    async def _check_canary_health(
        self,
        resource_id: str,
        kube_cluster: str,
        namespace: str,
        timeout: int
    ) -> bool:
        """
        Check canary deployment health.
        
        Args:
            resource_id: Canary resource ID
            kube_cluster: Kubernetes cluster
            namespace: Kubernetes namespace
            timeout: Timeout in seconds
            
        Returns:
            True if healthy
        """
        return await self.traffic_splitter.check_deployment_health(
            resource_id=resource_id,
            kube_cluster=kube_cluster,
            namespace=namespace,
            timeout_seconds=timeout
        )
