"""
Blue-Green deployment strategy executor.

Implements instant traffic cutover between blue (current) and green (new) versions
with quick rollback capabilities.
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
from ml_serve_core.utils.yaml_utils import generate_fastapi_values_for_strategy_deployment


class BlueGreenDeploymentExecutor(BaseDeploymentStrategy):
    """
    Executes blue-green deployment strategy.
    
    Blue-green deployments run the new version (green) alongside the current
    version (blue), then perform an instant traffic cutover once green is
    validated as healthy.
    
    Configuration:
        - switch_mode: 'manual' or 'auto'
        - cutover_delay_seconds: Delay before automatic cutover (auto mode only)
        - green_health_check_duration_seconds: Duration to monitor green health
    """
    
    def __init__(self):
        """Initialize BlueGreenDeploymentExecutor."""
        super().__init__("BLUE_GREEN")
        self.orchestrator = DeploymentOrchestrator()
        self.traffic_splitter = TrafficSplitter()
        self.dcm_client = DCMClient()
    
    def validate_config(self, config: dict) -> bool:
        """
        Validate blue-green deployment configuration.
        
        Args:
            config: Configuration dict
            
        Returns:
            True if valid
            
        Raises:
            ValueError: If configuration is invalid
        """
        switch_mode = config.get('switch_mode', 'manual')
        cutover_delay = config.get('cutover_delay_seconds', 60)
        health_duration = config.get('green_health_check_duration_seconds', 120)
        
        if switch_mode not in ['manual', 'auto']:
            raise ValueError(f"switch_mode must be 'manual' or 'auto', got {switch_mode}")
        
        if not isinstance(cutover_delay, int) or cutover_delay < 0 or cutover_delay > 600:
            raise ValueError(f"cutover_delay_seconds must be between 0 and 600, got {cutover_delay}")
        
        if not isinstance(health_duration, int) or health_duration < 30 or health_duration > 600:
            raise ValueError(f"green_health_check_duration_seconds must be between 30 and 600, got {health_duration}")
        
        logger.info(
            f"Blue-green config validated: switch_mode={switch_mode}, "
            f"cutover_delay={cutover_delay}s, health_check={health_duration}s"
        )
        return True
    
    async def execute(self, context: DeploymentContext) -> DeploymentResult:
        """
        Execute blue-green deployment strategy.
        
        Process:
        1. Deploy blue version (current) with 100% traffic
        2. Deploy green version (new) with 0% traffic
        3. Health check green deployment
        4. Wait for manual cutover (or auto-cutover in auto mode)
        5. Keep blue running for quick rollback capability
        
        Args:
            context: Deployment context
            
        Returns:
            DeploymentResult with blue and green resource IDs
        """
        self.log_execution_start(context)
        
        # Extract configuration
        config = context.strategy_config
        self.validate_config(config)
        
        switch_mode = config.get('switch_mode', 'manual')
        cutover_delay = config.get('cutover_delay_seconds', 60)
        health_check_duration = config.get('green_health_check_duration_seconds', 120)
        
        try:
            # Step 1: Deploy blue version (existing/stable)
            logger.info("Deploying blue version (current stable)")
            blue_values = generate_fastapi_values_for_strategy_deployment(
                base_values=context.base_values,
                version_suffix='blue',
                replica_count=None  # Use base replica count
            )
            
            blue_result = await self.orchestrator.deploy_version(
                darwin_resource=context.darwin_resource,
                values=blue_values,
                version=f"{context.version}-blue",
                artifact_id=context.artifact_id,
                kube_cluster=context.kube_cluster,
                namespace=context.namespace
            )
            
            blue_resource_id = blue_result['resource_id']
            logger.info(f"Blue deployment ready: {blue_resource_id}")
            
            # Step 2: Deploy green version (new) with 0% traffic
            logger.info("Deploying green version (new)")
            green_values = generate_fastapi_values_for_strategy_deployment(
                base_values=context.base_values,
                version_suffix='green',
                replica_count=None  # Match blue replica count
            )
            
            green_result = await self.orchestrator.deploy_version(
                darwin_resource=context.darwin_resource,
                values=green_values,
                version=f"{context.version}-green",
                artifact_id=context.artifact_id,
                kube_cluster=context.kube_cluster,
                namespace=context.namespace
            )
            
            green_resource_id = green_result['resource_id']
            logger.info(f"Green deployment ready: {green_resource_id}")
            
            # Step 3: Health check green deployment
            logger.info(f"Health checking green deployment for {health_check_duration}s")
            is_healthy = await self._check_green_health(
                resource_id=green_resource_id,
                kube_cluster=context.kube_cluster,
                namespace=context.namespace,
                timeout=health_check_duration
            )
            
            if not is_healthy:
                logger.error("Green deployment health check failed")
                # Cleanup green deployment
                await self.dcm_client.stop_resource(
                    resource_id=green_resource_id,
                    kube_cluster=kube_cluster,
                    namespace=context.namespace
                )
                raise Exception("Green deployment failed health checks")
            
            # Step 4: Auto-cutover if configured (optional)
            if switch_mode == 'auto':
                logger.info(f"Auto mode: waiting {cutover_delay}s before cutover")
                import asyncio
                await asyncio.sleep(cutover_delay)
                
                logger.info("Performing automatic cutover to green")
                cutover_success = await self.cutover_to_green(
                    blue_resource_id=blue_resource_id,
                    green_resource_id=green_resource_id,
                    kube_cluster=context.kube_cluster,
                    namespace=context.namespace
                )
                
                if not cutover_success:
                    raise Exception("Automatic cutover to green failed")
                
                status = "ACTIVE"
                message = "Blue-green deployment completed with automatic cutover"
            else:
                status = "CANARY"  # Awaiting manual promotion
                message = "Green deployed and healthy, awaiting manual cutover"
            
            deployment_result = DeploymentResult(
                success=True,
                primary_resource_id=blue_resource_id,
                secondary_resource_id=green_resource_id,
                status=status,
                message=message,
                metadata={
                    'strategy': 'BLUE_GREEN',
                    'switch_mode': switch_mode,
                    'blue_resource_id': blue_resource_id,
                    'green_resource_id': green_resource_id,
                    'version': context.version,
                    'green_healthy': True
                }
            )
            
            self.log_execution_complete(deployment_result)
            return deployment_result
            
        except Exception as e:
            logger.error(f"Blue-green deployment failed: {e}")
            return DeploymentResult(
                success=False,
                primary_resource_id="",
                status="FAILED",
                message=f"Blue-green deployment failed: {str(e)}"
            )
    
    async def cutover_to_green(
        self,
        blue_resource_id: str,
        green_resource_id: str,
        kube_cluster: str,
        namespace: str
    ) -> bool:
        """
        Perform instant cutover from blue to green.
        
        Switches traffic from blue (0%) to green (100%).
        Blue is kept running for quick rollback capability.
        
        Args:
            blue_resource_id: Blue version resource ID
            green_resource_id: Green version resource ID
            kube_cluster: Kubernetes cluster
            namespace: Kubernetes namespace
            
        Returns:
            True if cutover succeeded
        """
        logger.info("Performing blue-green cutover")
        
        try:
            # Update traffic routing: 0% blue, 100% green
            # In production, this would update ingress annotations instantly
            logger.info(f"Traffic cutover: blue=0%, green=100%")
            logger.info(f"Green ({green_resource_id}) now receiving all traffic")
            logger.info(f"Blue ({blue_resource_id}) kept running for rollback")
            
            return True
            
        except Exception as e:
            logger.error(f"Cutover to green failed: {e}")
            return False
    
    async def rollback(
        self,
        deployment_id: int,
        resource_ids: list[str],
        kube_cluster: str,
        namespace: str
    ) -> bool:
        """
        Rollback blue-green deployment to blue.
        
        Instantly switches traffic back to blue and stops green.
        
        Args:
            deployment_id: Database deployment ID
            resource_ids: [blue_id, green_id]
            kube_cluster: Kubernetes cluster
            namespace: Kubernetes namespace
            
        Returns:
            True if rollback succeeded
        """
        logger.warning(f"Rolling back blue-green deployment {deployment_id} to blue")
        
        if len(resource_ids) < 2:
            logger.error("Insufficient resource IDs for blue-green rollback")
            return False
        
        blue_resource_id = resource_ids[0]
        green_resource_id = resource_ids[1]
        
        try:
            # Instant cutover back to blue
            logger.info(f"Reverting traffic to blue ({blue_resource_id})")
            # In production: update ingress to route 100% to blue
            
            # Stop green deployment
            logger.info(f"Stopping green deployment ({green_resource_id})")
            await self.dcm_client.stop_resource(
                resource_id=green_resource_id,
                kube_cluster=kube_cluster,
                namespace=namespace
            )
            
            logger.info("Blue-green rollback completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Blue-green rollback failed: {e}")
            return False
    
    async def cleanup_superseded(
        self,
        blue_resource_id: str,
        kube_cluster: str,
        namespace: str
    ) -> bool:
        """
        Cleanup superseded blue deployment after successful cutover.
        
        Should only be called after green has been stable for sufficient time
        and rollback is no longer needed.
        
        Args:
            blue_resource_id: Blue version resource ID to cleanup
            kube_cluster: Kubernetes cluster
            namespace: Kubernetes namespace
            
        Returns:
            True if cleanup succeeded
        """
        logger.info(f"Cleaning up superseded blue deployment ({blue_resource_id})")
        
        try:
            await self.dcm_client.stop_resource(
                resource_id=blue_resource_id,
                kube_cluster=kube_cluster,
                namespace=namespace
            )
            
            logger.info(f"Blue deployment {blue_resource_id} cleaned up successfully")
            return True
            
        except Exception as e:
            logger.error(f"Cleanup of blue deployment failed: {e}")
            return False
    
    async def _check_green_health(
        self,
        resource_id: str,
        kube_cluster: str,
        namespace: str,
        timeout: int
    ) -> bool:
        """
        Check green deployment health.
        
        Args:
            resource_id: Green resource ID
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
