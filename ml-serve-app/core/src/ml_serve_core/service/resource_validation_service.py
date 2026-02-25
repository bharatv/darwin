"""Resource validation service for pre-deployment cluster checks."""
from fastapi import HTTPException

from ml_serve_core.client.kubernetes_client import KubernetesClient
from ml_serve_model import Environment
from loguru import logger


class ResourceValidationService:
    """Validates cluster resource availability before deployment."""

    def __init__(self):
        self._k8s_client = KubernetesClient()

    async def check_resources(
        self,
        env: Environment,
        required_cpu: float,
        required_memory: float,
    ) -> bool:
        """
        Check if cluster has sufficient CPU and memory.
        required_cpu: cores, required_memory: GB.
        Raises HTTPException 400 if insufficient.
        """
        resources = await self._k8s_client.get_cluster_allocatable_resources(
            namespace=env.namespace
        )
        available_cpu = resources.get("cpu", 0.0)
        available_memory_mi = resources.get("memory", 0.0)
        required_memory_mi = required_memory * 1024  # GB to Mi

        if available_cpu < required_cpu:
            logger.warning(
                f"Insufficient CPU: required={required_cpu}, available={available_cpu}"
            )
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Insufficient cluster resources. "
                    f"Required CPU: {required_cpu} cores, available: {available_cpu:.1f}."
                ),
            )
        if available_memory_mi < required_memory_mi:
            logger.warning(
                f"Insufficient memory: required={required_memory_mi}Mi, "
                f"available={available_memory_mi}Mi"
            )
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Insufficient cluster resources. "
                    f"Required memory: {required_memory}GB, "
                    f"available: {available_memory_mi/1024:.1f}GB."
                ),
            )
        return True
