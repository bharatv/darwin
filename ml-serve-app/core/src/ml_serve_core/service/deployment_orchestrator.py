"""
Deployment orchestrator for managing multi-version deployments.

Coordinates creation, tracking, and lifecycle of multiple deployment versions
for deployment strategies (canary, blue-green, rolling).
"""

from typing import Dict, List, Optional, Tuple
from loguru import logger
from ml_serve_core.client.dcm_client import DCMClient
from ml_serve_core.service.traffic_splitter import TrafficSplitter


class DeploymentOrchestrator:
    """
    Orchestrates multi-version deployments for deployment strategies.
    
    Manages:
    - Creation of primary and secondary deployment versions
    - DCM resource lifecycle (build, start, stop)
    - Traffic weight distribution between versions
    - Version tracking and metadata
    """
    
    def __init__(self, dcm_client: Optional[DCMClient] = None):
        """
        Initialize DeploymentOrchestrator.
        
        Args:
            dcm_client: Optional DCMClient instance (creates new if not provided)
        """
        self.dcm_client = dcm_client or DCMClient()
        self.traffic_splitter = TrafficSplitter()
    
    async def deploy_version(
        self,
        darwin_resource: str,
        values: dict,
        version: str,
        artifact_id: str,
        kube_cluster: str,
        namespace: str
    ) -> Dict[str, str]:
        """
        Deploy a single version (build + start).
        
        Args:
            darwin_resource: Darwin resource type (e.g., 'fastapi-serve')
            values: Helm values for this version
            version: Version identifier
            artifact_id: Artifact ID for deployment
            kube_cluster: Kubernetes cluster name
            namespace: Kubernetes namespace
            
        Returns:
            Dict with 'resource_id' and 'status'
            
        Raises:
            Exception: If build or start fails
        """
        logger.info(
            f"Deploying version '{version}' for artifact {artifact_id} "
            f"to {kube_cluster}/{namespace}"
        )
        
        # Build resource (creates Helm release)
        build_response = await self.dcm_client.build_resource(
            darwin_resource=darwin_resource,
            values=values,
            version=version,
            artifact_id=artifact_id
        )
        resource_id = build_response.get('resource_id')
        
        if not resource_id:
            raise Exception(f"Failed to build resource for version {version}: no resource_id returned")
        
        logger.info(f"Built resource {resource_id} for version {version}")
        
        # Start resource (deploys to K8s)
        start_response = await self.dcm_client.start_resource(
            resource_id=resource_id,
            kube_cluster=kube_cluster,
            namespace=namespace,
            artifact_id=artifact_id,
            darwin_resource=darwin_resource
        )
        
        logger.info(f"Started resource {resource_id} for version {version}")
        
        return {
            'resource_id': resource_id,
            'version': version,
            'status': start_response.get('status', 'UNKNOWN')
        }
    
    async def deploy_multi_version(
        self,
        versions: List[Dict[str, any]],
        darwin_resource: str,
        kube_cluster: str,
        namespace: str
    ) -> List[Dict[str, str]]:
        """
        Deploy multiple versions sequentially.
        
        Args:
            versions: List of version configs with keys:
                - 'values': Helm values dict
                - 'version': Version identifier
                - 'artifact_id': Artifact ID
            darwin_resource: Darwin resource type
            kube_cluster: Kubernetes cluster name
            namespace: Kubernetes namespace
            
        Returns:
            List of deployment results with resource_id and status
            
        Example:
            versions = [
                {
                    'values': stable_values,
                    'version': 'v1-stable',
                    'artifact_id': 'artifact-123'
                },
                {
                    'values': canary_values,
                    'version': 'v2-canary',
                    'artifact_id': 'artifact-124'
                }
            ]
        """
        results = []
        
        for version_config in versions:
            try:
                result = await self.deploy_version(
                    darwin_resource=darwin_resource,
                    values=version_config['values'],
                    version=version_config['version'],
                    artifact_id=version_config['artifact_id'],
                    kube_cluster=kube_cluster,
                    namespace=namespace
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to deploy version {version_config['version']}: {e}")
                # Rollback: stop previously deployed versions
                await self._cleanup_deployments(results, kube_cluster, namespace)
                raise Exception(
                    f"Multi-version deployment failed at {version_config['version']}: {e}"
                )
        
        logger.info(f"Successfully deployed {len(results)} versions")
        return results
    
    async def stop_version(
        self,
        resource_id: str,
        kube_cluster: str,
        namespace: str
    ) -> None:
        """
        Stop a deployment version.
        
        Args:
            resource_id: DCM resource ID to stop
            kube_cluster: Kubernetes cluster name
            namespace: Kubernetes namespace
        """
        logger.info(f"Stopping resource {resource_id} in {kube_cluster}/{namespace}")
        
        await self.dcm_client.stop_resource(
            resource_id=resource_id,
            kube_cluster=kube_cluster,
            namespace=namespace
        )
        
        logger.info(f"Stopped resource {resource_id}")
    
    async def get_version_status(
        self,
        resource_id: str,
        kube_cluster: str,
        namespace: str
    ) -> str:
        """
        Get deployment status for a version.
        
        Args:
            resource_id: DCM resource ID
            kube_cluster: Kubernetes cluster name
            namespace: Kubernetes namespace
            
        Returns:
            Status string (e.g., 'RUNNING', 'STOPPED', 'FAILED')
        """
        status = await self.dcm_client.get_status(
            resource_id=resource_id,
            kube_cluster=kube_cluster,
            kube_namespace=namespace
        )
        return status
    
    async def _cleanup_deployments(
        self,
        deployments: List[Dict[str, str]],
        kube_cluster: str,
        namespace: str
    ) -> None:
        """
        Cleanup failed deployments by stopping all resources.
        
        Args:
            deployments: List of deployment results with resource_id
            kube_cluster: Kubernetes cluster name
            namespace: Kubernetes namespace
        """
        logger.warning(f"Cleaning up {len(deployments)} deployments")
        
        for deployment in deployments:
            try:
                resource_id = deployment.get('resource_id')
                if resource_id:
                    await self.stop_version(resource_id, kube_cluster, namespace)
            except Exception as e:
                logger.error(f"Failed to stop resource {resource_id} during cleanup: {e}")
    
    def prepare_deployment_metadata(
        self,
        primary_deployment: Dict[str, any],
        secondary_deployment: Optional[Dict[str, any]] = None
    ) -> Dict[str, any]:
        """
        Prepare metadata for tracking multi-version deployments.
        
        Args:
            primary_deployment: Primary deployment info (stable/blue)
            secondary_deployment: Optional secondary deployment info (canary/green)
            
        Returns:
            Metadata dict for persisting deployment state
        """
        metadata = {
            'primary': {
                'resource_id': primary_deployment.get('resource_id'),
                'version': primary_deployment.get('version'),
                'artifact_id': primary_deployment.get('artifact_id')
            }
        }
        
        if secondary_deployment:
            metadata['secondary'] = {
                'resource_id': secondary_deployment.get('resource_id'),
                'version': secondary_deployment.get('version'),
                'artifact_id': secondary_deployment.get('artifact_id')
            }
        
        return metadata
    
    async def validate_deployment_health(
        self,
        resource_ids: List[str],
        kube_cluster: str,
        namespace: str,
        health_check_duration: int = 60
    ) -> Tuple[bool, List[str]]:
        """
        Validate health of multiple deployments.
        
        Args:
            resource_ids: List of DCM resource IDs to check
            kube_cluster: Kubernetes cluster name
            namespace: Kubernetes namespace
            health_check_duration: Time to wait for health checks (seconds)
            
        Returns:
            Tuple of (all_healthy, list_of_unhealthy_ids)
        """
        logger.info(
            f"Validating health of {len(resource_ids)} deployments "
            f"(duration: {health_check_duration}s)"
        )
        
        unhealthy = []
        
        for resource_id in resource_ids:
            is_healthy = await self.traffic_splitter.check_deployment_health(
                resource_id=resource_id,
                kube_cluster=kube_cluster,
                namespace=namespace,
                timeout_seconds=health_check_duration
            )
            
            if not is_healthy:
                unhealthy.append(resource_id)
        
        all_healthy = len(unhealthy) == 0
        
        if all_healthy:
            logger.info("All deployments are healthy")
        else:
            logger.warning(f"Unhealthy deployments: {unhealthy}")
        
        return all_healthy, unhealthy
    
    async def deploy_with_rollback_on_failure(
        self,
        versions: List[Dict[str, any]],
        darwin_resource: str,
        kube_cluster: str,
        namespace: str,
        health_check_duration: int = 60
    ) -> List[Dict[str, str]]:
        """
        Deploy multiple versions atomically with automatic rollback on failure.
        
        This ensures either all versions deploy successfully, or all are rolled back.
        Health checks are performed after deployment.
        
        Args:
            versions: List of version configurations
            darwin_resource: Darwin resource type
            kube_cluster: Kubernetes cluster
            namespace: Kubernetes namespace
            health_check_duration: Time to wait for health checks
            
        Returns:
            List of successful deployment results
            
        Raises:
            Exception: If deployment or health checks fail (after rollback)
        """
        deployed_resources = []
        
        try:
            # Deploy all versions
            logger.info(f"Deploying {len(versions)} versions atomically")
            deployed_resources = await self.deploy_multi_version(
                versions=versions,
                darwin_resource=darwin_resource,
                kube_cluster=kube_cluster,
                namespace=namespace
            )
            
            # Validate health of all deployments
            resource_ids = [d['resource_id'] for d in deployed_resources]
            all_healthy, unhealthy = await self.validate_deployment_health(
                resource_ids=resource_ids,
                kube_cluster=kube_cluster,
                namespace=namespace,
                health_check_duration=health_check_duration
            )
            
            if not all_healthy:
                raise Exception(
                    f"Health check failed for {len(unhealthy)} deployments: {unhealthy}"
                )
            
            logger.info("Atomic deployment succeeded - all versions healthy")
            return deployed_resources
            
        except Exception as e:
            logger.error(f"Atomic deployment failed: {e}")
            
            # Rollback: cleanup all deployed resources
            if deployed_resources:
                logger.warning(f"Rolling back {len(deployed_resources)} deployments")
                await self.dcm_client.cleanup_failed_resources(
                    resource_ids=[d['resource_id'] for d in deployed_resources],
                    kube_cluster=kube_cluster,
                    namespace=namespace
                )
            
            raise Exception(f"Atomic deployment failed and rolled back: {e}")
