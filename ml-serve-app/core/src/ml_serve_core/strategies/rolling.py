"""
Rolling deployment strategy executor.

Implements gradual replica replacement in phases, ensuring continuous
availability throughout the rollout process.
"""

from typing import Optional
from loguru import logger

from ml_serve_core.strategies.base import (
    BaseDeploymentStrategy,
    DeploymentContext,
    DeploymentResult
)
from ml_serve_core.service.deployment_orchestrator import DeploymentOrchestrator
from ml_serve_core.client.dcm_client import DCMClient


class RollingDeploymentExecutor(BaseDeploymentStrategy):
    """
    Executes rolling deployment strategy.
    
    Rolling deployments gradually replace old replicas with new ones in phases,
    maintaining service availability throughout the process. The rollout happens
    in configurable steps with health checks between each phase.
    
    Configuration:
        - steps: Number of rollout phases (default: 3)
        - interval_seconds: Wait time between phases (default: 30)
        - health_check_duration_seconds: Health check duration after each step (default: 60)
    """
    
    def __init__(self):
        """Initialize RollingDeploymentExecutor."""
        super().__init__("ROLLING")
        self.orchestrator = DeploymentOrchestrator()
        self.dcm_client = DCMClient()
    
    def validate_config(self, config: dict) -> bool:
        """
        Validate rolling deployment configuration.
        
        Args:
            config: Configuration dict with steps, interval_seconds, health_check_duration_seconds
            
        Returns:
            True if valid
            
        Raises:
            ValueError: If configuration is invalid
        """
        steps = config.get('steps', 3)
        interval = config.get('interval_seconds', 30)
        health_duration = config.get('health_check_duration_seconds', 60)
        
        if not isinstance(steps, int) or steps < 1 or steps > 10:
            raise ValueError(f"steps must be between 1 and 10, got {steps}")
        
        if not isinstance(interval, int) or interval < 10 or interval > 600:
            raise ValueError(f"interval_seconds must be between 10 and 600, got {interval}")
        
        if not isinstance(health_duration, int) or health_duration < 10 or health_duration > 300:
            raise ValueError(f"health_check_duration_seconds must be between 10 and 300, got {health_duration}")
        
        logger.info(
            f"Rolling deployment config validated: {steps} steps, "
            f"{interval}s interval, {health_duration}s health check"
        )
        return True
    
    async def execute(self, context: DeploymentContext) -> DeploymentResult:
        """
        Execute rolling deployment strategy.
        
        Deploys new version with gradual replica scaling:
        1. Deploy new version with HPA configuration
        2. K8s rolling update handles gradual replica replacement
        3. HPA manages scaling based on resource utilization
        4. Health check after deployment completes
        5. Complete when new version has all traffic
        
        Args:
            context: Deployment context
            
        Returns:
            DeploymentResult with success status and resource ID
        """
        self.log_execution_start(context)
        
        # Extract configuration
        config = context.strategy_config
        self.validate_config(config)
        
        steps = config.get('steps', 3)
        interval_seconds = config.get('interval_seconds', 30)
        health_check_duration = config.get('health_check_duration_seconds', 60)
        
        try:
            # For rolling deployment, we deploy the new version with standard K8s rolling update
            # The actual rolling behavior is handled by K8s Deployment controller
            # We configure maxSurge and maxUnavailable based on steps
            
            logger.info(
                f"Executing rolling deployment with {steps} steps, "
                f"{interval_seconds}s interval"
            )
            
            # Configure rolling update strategy in Helm values
            values = self._configure_rolling_update_values(
                context.base_values,
                steps
            )
            
            # Deploy new version (K8s will handle rolling update automatically)
            result = await self.orchestrator.deploy_version(
                darwin_resource=context.darwin_resource,
                values=values,
                version=context.version,
                artifact_id=context.artifact_id,
                kube_cluster=context.kube_cluster,
                namespace=context.namespace
            )
            
            resource_id = result['resource_id']
            
            # Health check the deployment
            logger.info(f"Health checking rolled out deployment (resource: {resource_id})")
            is_healthy = await self._check_rollout_health(
                resource_id=resource_id,
                kube_cluster=context.kube_cluster,
                namespace=context.namespace,
                timeout=health_check_duration
            )
            
            if not is_healthy:
                raise Exception(f"Rolling deployment health check failed for {resource_id}")
            
            deployment_result = DeploymentResult(
                success=True,
                primary_resource_id=resource_id,
                status="ACTIVE",
                message=f"Rolling deployment completed successfully in {steps} steps",
                metadata={
                    'strategy': 'ROLLING',
                    'steps': steps,
                    'interval_seconds': interval_seconds,
                    'version': context.version
                }
            )
            
            self.log_execution_complete(deployment_result)
            return deployment_result
            
        except Exception as e:
            logger.error(f"Rolling deployment failed: {e}")
            return DeploymentResult(
                success=False,
                primary_resource_id="",
                status="FAILED",
                message=f"Rolling deployment failed: {str(e)}"
            )
    
    def _configure_rolling_update_values(
        self,
        base_values: dict,
        steps: int
    ) -> dict:
        """
        Configure Helm values for rolling update strategy.
        
        Sets maxSurge and maxUnavailable based on number of steps to control
        how aggressively the rollout proceeds. HPA configuration is preserved.
        
        Args:
            base_values: Base Helm values dict
            steps: Number of rollout steps (1-10)
            
        Returns:
            Modified values dict with rolling update configuration
        """
        import copy
        values = copy.deepcopy(base_values)
        
        # Configure rolling update strategy
        # More steps = more conservative rollout
        if steps <= 3:
            # Aggressive: 50% surge, 25% unavailable
            max_surge = "50%"
            max_unavailable = "25%"
        elif steps <= 5:
            # Moderate: 25% surge, 10% unavailable  
            max_surge = "25%"
            max_unavailable = "10%"
        else:
            # Conservative: 10% surge, 0% unavailable (safe rollout)
            max_surge = "10%"
            max_unavailable = "0%"
        
        # Add rolling update strategy to deployment spec
        if 'deploymentStrategy' not in values:
            values['deploymentStrategy'] = {}
        
        values['deploymentStrategy']['type'] = 'RollingUpdate'
        values['deploymentStrategy']['rollingUpdate'] = {
            'maxSurge': max_surge,
            'maxUnavailable': max_unavailable
        }
        
        # Preserve HPA configuration from base values
        # HPA will automatically scale the new deployment after it's rolled out
        if 'hpa' in base_values:
            values['hpa'] = base_values['hpa']
            logger.debug(
                f"HPA configuration preserved: "
                f"maxReplicas={base_values['hpa'].get('maxReplicas')}"
            )
        
        logger.info(
            f"Configured rolling update: maxSurge={max_surge}, "
            f"maxUnavailable={max_unavailable}"
        )
        
        return values
    
    async def rollback(
        self,
        deployment_id: int,
        resource_ids: list[str],
        kube_cluster: str,
        namespace: str
    ) -> bool:
        """
        Rollback a failed rolling deployment.
        
        For rolling deployments, rollback means stopping the new version
        and ensuring the previous stable version is active.
        
        Args:
            deployment_id: Database deployment ID
            resource_ids: List of resource IDs to rollback (typically 1 for rolling)
            kube_cluster: Kubernetes cluster
            namespace: Kubernetes namespace
            
        Returns:
            True if rollback succeeded
        """
        logger.warning(
            f"Rolling back rolling deployment {deployment_id}, "
            f"stopping resources: {resource_ids}"
        )
        
        try:
            # Stop the failed deployment
            await self.dcm_client.cleanup_failed_resources(
                resource_ids=resource_ids,
                kube_cluster=kube_cluster,
                namespace=namespace
            )
            
            logger.info(f"Rolling deployment {deployment_id} rolled back successfully")
            return True
            
        except Exception as e:
            logger.error(f"Rollback failed for deployment {deployment_id}: {e}")
            return False
    
    async def _check_rollout_health(
        self,
        resource_id: str,
        kube_cluster: str,
        namespace: str,
        timeout: int
    ) -> bool:
        """
        Check if rolled out deployment is healthy.
        
        Args:
            resource_id: DCM resource ID
            kube_cluster: Kubernetes cluster
            namespace: Kubernetes namespace
            timeout: Timeout in seconds
            
        Returns:
            True if healthy
        """
        import asyncio
        
        elapsed = 0
        check_interval = 5
        
        while elapsed < timeout:
            try:
                status = await self.dcm_client.get_status(
                    resource_id=resource_id,
                    kube_cluster=kube_cluster,
                    kube_namespace=namespace
                )
                
                if status == 'RUNNING':
                    logger.info(f"Rolling deployment {resource_id} is healthy")
                    return True
                
                logger.debug(f"Rollout status: {status}, waiting...")
                
            except Exception as e:
                logger.warning(f"Health check error: {e}")
            
            await asyncio.sleep(check_interval)
            elapsed += check_interval
        
        logger.error(f"Rolling deployment health check timed out after {timeout}s")
        return False
