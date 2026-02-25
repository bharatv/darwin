import json
import traceback

from ml_serve_core.client.http_client import AsyncHttpClient
from ml_serve_core.config.configs import Config
from loguru import logger


class DCMClient:
    def __init__(self):
        self.config = Config()

    async def build_resource(
            self, darwin_resource: str, values: dict, version: str, artifact_id: str
    ):
        try:
            url = self.config.dcm_url + "/resource-instance/"
            data = {
                "darwin_resource": darwin_resource,
                "values": values,
                "version": version,
                "artifact_id": artifact_id
            }

            async with AsyncHttpClient() as client:
                resp = await client.post(url, json=data)
                return resp["body"]
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"Error  while calling DCM create resource api: {e} with traceback: {tb}")
            raise Exception("Error while building resource")

    async def update_resource(
            self, values: dict, artifact_id: str, darwin_resource: str
    ):
        try:
            url = self.config.dcm_url + "/resource-instance/values"
            data = {
                "values": values,
                "artifact_id": artifact_id,
                "darwin_resource": darwin_resource
            }
            async with AsyncHttpClient() as client:
                resp = await client.patch(url, json=data)
                return resp["body"]
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"Error while calling DCM update resource api: {e} with traceback: {tb}")
            raise Exception("Error while updating resource")

    async def start_resource(
            self, resource_id: str, kube_cluster: str, namespace: str, artifact_id: str, darwin_resource: str
    ):
        try:
            url = self.config.dcm_url + "/resource-instance/start"
            data = {
                "resource_id": resource_id,
                "kube_cluster": kube_cluster,
                "kube_namespace": namespace,
                "artifact_id": artifact_id,
                "darwin_resource": darwin_resource
            }
            async with AsyncHttpClient() as client:
                resp = await client.post(url, json=data)
                return resp["body"]
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"Error while calling DCM start resource api: {e} with traceback: {tb}")
            raise Exception("Error while starting resource")

    async def stop_resource(
            self, resource_id: str, kube_cluster: str, namespace: str
    ):
        try:
            url = self.config.dcm_url + "/resource-instance/stop"
            data = {
                "resource_id": resource_id,
                "kube_cluster": kube_cluster,
                "kube_namespace": namespace
            }
            async with AsyncHttpClient() as client:
                resp = await client.post(url, json=data)
                return resp["body"]
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"Error while calling DCM stop resource api: {e} with traceback: {tb}")
            raise Exception("Error while stopping resource")

    async def get_status(self, resource_id: str, kube_cluster: str, kube_namespace: str):
        try:
            url = self.config.dcm_url + f"/resource-instance/status"
            data = {
                "resource_id": resource_id,
                "kube_cluster": kube_cluster,
                "kube_namespace": kube_namespace
            }
            async with AsyncHttpClient() as client:
                resp = await client.post(url, json=data)
                return resp["body"]['data']['status']
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"Error while calling DCM get status api: {e} with traceback: {tb}")
            raise Exception("Error while getting status")
    
    async def build_and_start_resource(
        self,
        darwin_resource: str,
        values: dict,
        version: str,
        artifact_id: str,
        kube_cluster: str,
        namespace: str
    ) -> dict:
        """
        Build and start a resource in a single operation.
        
        Convenience method that combines build_resource and start_resource.
        Used for atomic deployment operations.
        
        Args:
            darwin_resource: Darwin resource type
            values: Helm values
            version: Version identifier
            artifact_id: Artifact ID
            kube_cluster: Kubernetes cluster
            namespace: Kubernetes namespace
            
        Returns:
            Dict with resource_id and status
            
        Raises:
            Exception: If build or start fails
        """
        logger.info(f"Building and starting resource for artifact {artifact_id}, version {version}")
        
        # Build
        build_response = await self.build_resource(
            darwin_resource=darwin_resource,
            values=values,
            version=version,
            artifact_id=artifact_id
        )
        resource_id = build_response.get('resource_id')
        
        if not resource_id:
            raise Exception("Failed to build resource: no resource_id returned")
        
        # Start
        start_response = await self.start_resource(
            resource_id=resource_id,
            kube_cluster=kube_cluster,
            namespace=namespace,
            artifact_id=artifact_id,
            darwin_resource=darwin_resource
        )
        
        return {
            'resource_id': resource_id,
            'artifact_id': artifact_id,
            'version': version,
            'status': start_response.get('status', 'UNKNOWN')
        }
    
    async def get_status_for_multiple_resources(
        self,
        resource_ids: list[str],
        kube_cluster: str,
        kube_namespace: str
    ) -> dict[str, str]:
        """
        Get status for multiple resources.
        
        Queries DCM for status of each resource sequentially.
        
        Args:
            resource_ids: List of resource IDs to query
            kube_cluster: Kubernetes cluster
            kube_namespace: Kubernetes namespace
            
        Returns:
            Dict mapping resource_id to status string
            
        Example:
            {
                'resource-123': 'RUNNING',
                'resource-124': 'STOPPED'
            }
        """
        statuses = {}
        
        for resource_id in resource_ids:
            try:
                status = await self.get_status(
                    resource_id=resource_id,
                    kube_cluster=kube_cluster,
                    kube_namespace=kube_namespace
                )
                statuses[resource_id] = status
            except Exception as e:
                logger.warning(f"Failed to get status for {resource_id}: {e}")
                statuses[resource_id] = 'UNKNOWN'
        
        return statuses
    
    async def stop_multiple_resources(
        self,
        resource_ids: list[str],
        kube_cluster: str,
        namespace: str
    ) -> dict[str, bool]:
        """
        Stop multiple resources.
        
        Stops each resource sequentially, continuing even if some fail.
        
        Args:
            resource_ids: List of resource IDs to stop
            kube_cluster: Kubernetes cluster
            namespace: Kubernetes namespace
            
        Returns:
            Dict mapping resource_id to success boolean
        """
        results = {}
        
        for resource_id in resource_ids:
            try:
                await self.stop_resource(
                    resource_id=resource_id,
                    kube_cluster=kube_cluster,
                    namespace=namespace
                )
                results[resource_id] = True
                logger.info(f"Successfully stopped resource {resource_id}")
            except Exception as e:
                logger.error(f"Failed to stop resource {resource_id}: {e}")
                results[resource_id] = False
        
        return results
    
    async def build_and_start_with_retry(
        self,
        darwin_resource: str,
        values: dict,
        version: str,
        artifact_id: str,
        kube_cluster: str,
        namespace: str,
        max_retries: int = 2
    ) -> dict:
        """
        Build and start resource with retry logic for transient failures.
        
        Args:
            darwin_resource: Darwin resource type
            values: Helm values
            version: Version identifier
            artifact_id: Artifact ID
            kube_cluster: Kubernetes cluster
            namespace: Kubernetes namespace
            max_retries: Maximum number of retry attempts
            
        Returns:
            Dict with resource_id and status
            
        Raises:
            Exception: If all retries fail
        """
        import asyncio
        
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                result = await self.build_and_start_resource(
                    darwin_resource=darwin_resource,
                    values=values,
                    version=version,
                    artifact_id=artifact_id,
                    kube_cluster=kube_cluster,
                    namespace=namespace
                )
                
                if attempt > 0:
                    logger.info(f"Build and start succeeded on attempt {attempt + 1}")
                
                return result
                
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Build and start failed on attempt {attempt + 1}/{max_retries + 1}: {e}"
                )
                
                if attempt < max_retries:
                    # Exponential backoff: 2s, 4s, 8s...
                    wait_time = 2 ** attempt
                    logger.info(f"Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
        
        # All retries failed
        raise Exception(
            f"Failed to build and start resource after {max_retries + 1} attempts: {last_error}"
        )
    
    async def cleanup_failed_resources(
        self,
        resource_ids: list[str],
        kube_cluster: str,
        namespace: str
    ) -> None:
        """
        Cleanup resources that failed during deployment.
        
        Attempts to stop all resources, logging failures but continuing.
        Used for rollback and error recovery.
        
        Args:
            resource_ids: List of resource IDs to cleanup
            kube_cluster: Kubernetes cluster
            namespace: Kubernetes namespace
        """
        if not resource_ids:
            return
        
        logger.info(f"Cleaning up {len(resource_ids)} failed resources")
        
        results = await self.stop_multiple_resources(
            resource_ids=resource_ids,
            kube_cluster=kube_cluster,
            namespace=namespace
        )
        
        failed_stops = [rid for rid, success in results.items() if not success]
        
        if failed_stops:
            logger.error(
                f"Failed to stop {len(failed_stops)} resources during cleanup: {failed_stops}"
            )
        else:
            logger.info(f"Successfully cleaned up all {len(resource_ids)} resources")
