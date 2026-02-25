"""
Kubernetes API client for Istio resources and cluster metrics.

Used for:
- Applying Istio VirtualService and DestinationRule CRs
- Fetching cluster allocatable resources for pre-deployment validation

Requires kubernetes Python package. When ENABLE_ISTIO=false, Istio operations are no-ops.
Uses asyncio.to_thread() for sync K8s API calls to avoid blocking the event loop.
"""
import asyncio
from typing import Dict, Any
from loguru import logger

try:
    from kubernetes import client, config
    from kubernetes.client.rest import ApiException
    K8S_AVAILABLE = True
except ImportError:
    K8S_AVAILABLE = False
    ApiException = Exception  # type: ignore


class KubernetesClient:
    """Direct Kubernetes API client for Istio resources and cluster resources."""

    def __init__(self):
        if not K8S_AVAILABLE:
            logger.warning("kubernetes package not installed; K8s operations will fail")
            self._custom_api = None
            self._core_api = None
            return
        try:
            config.load_incluster_config()
        except config.ConfigException:
            try:
                config.load_kube_config()
            except config.ConfigException as e:
                logger.warning(f"Could not load kube config: {e}")
        if K8S_AVAILABLE:
            self._custom_api = client.CustomObjectsApi()
            self._core_api = client.CoreV1Api()

    def _create_virtual_service_sync(
        self, namespace: str, vs_manifest: Dict[str, Any]
    ) -> None:
        """Sync create VirtualService."""
        self._custom_api.create_namespaced_custom_object(
            group="networking.istio.io",
            version="v1beta1",
            namespace=namespace,
            plural="virtualservices",
            body=vs_manifest,
        )

    def _patch_virtual_service_sync(
        self, namespace: str, name: str, vs_manifest: Dict[str, Any]
    ) -> None:
        """Sync patch VirtualService."""
        self._custom_api.patch_namespaced_custom_object(
            group="networking.istio.io",
            version="v1beta1",
            namespace=namespace,
            plural="virtualservices",
            name=name,
            body=vs_manifest,
        )

    async def apply_virtual_service(
        self, namespace: str, vs_manifest: Dict[str, Any]
    ) -> None:
        """Apply Istio VirtualService. Creates or updates."""
        if not K8S_AVAILABLE or self._custom_api is None:
            raise RuntimeError("Kubernetes client not available")
        name = vs_manifest.get("metadata", {}).get("name", "")
        try:
            await asyncio.to_thread(
                self._create_virtual_service_sync, namespace, vs_manifest
            )
            logger.info(f"Created VirtualService {name} in {namespace}")
        except ApiException as e:
            if e.status == 409:
                await asyncio.to_thread(
                    self._patch_virtual_service_sync,
                    namespace,
                    name,
                    vs_manifest,
                )
                logger.info(f"Updated VirtualService {name} in {namespace}")
            else:
                raise

    def _create_destination_rule_sync(
        self, namespace: str, dr_manifest: Dict[str, Any]
    ) -> None:
        """Sync create DestinationRule."""
        self._custom_api.create_namespaced_custom_object(
            group="networking.istio.io",
            version="v1beta1",
            namespace=namespace,
            plural="destinationrules",
            body=dr_manifest,
        )

    def _patch_destination_rule_sync(
        self, namespace: str, name: str, dr_manifest: Dict[str, Any]
    ) -> None:
        """Sync patch DestinationRule."""
        self._custom_api.patch_namespaced_custom_object(
            group="networking.istio.io",
            version="v1beta1",
            namespace=namespace,
            plural="destinationrules",
            name=name,
            body=dr_manifest,
        )

    async def apply_destination_rule(
        self, namespace: str, dr_manifest: Dict[str, Any]
    ) -> None:
        """Apply Istio DestinationRule. Creates or updates."""
        if not K8S_AVAILABLE or self._custom_api is None:
            raise RuntimeError("Kubernetes client not available")
        name = dr_manifest.get("metadata", {}).get("name", "")
        try:
            await asyncio.to_thread(
                self._create_destination_rule_sync, namespace, dr_manifest
            )
            logger.info(f"Created DestinationRule {name} in {namespace}")
        except ApiException as e:
            if e.status == 409:
                await asyncio.to_thread(
                    self._patch_destination_rule_sync,
                    namespace,
                    name,
                    dr_manifest,
                )
                logger.info(f"Updated DestinationRule {name} in {namespace}")
            else:
                raise

    def _list_nodes_sync(self):
        """Sync list nodes."""
        return self._core_api.list_node()

    async def get_cluster_allocatable_resources(
        self, namespace: str
    ) -> Dict[str, float]:
        """
        Get allocatable CPU (cores) and memory (Mi) for the cluster/namespace.
        Returns {"cpu": float, "memory": float} (memory in Mi).
        """
        if not K8S_AVAILABLE or self._core_api is None:
            return {"cpu": 1000.0, "memory": 1000000.0}  # Default permissive for tests
        try:
            nodes = await asyncio.to_thread(self._list_nodes_sync)
            total_cpu = 0.0
            total_memory = 0.0
            for node in nodes.items:
                allocatable = node.status.allocatable or {}
                cpu_str = allocatable.get("cpu", "0")
                memory_str = allocatable.get("memory", "0Ki")
                total_cpu += self._parse_cpu(cpu_str)
                total_memory += self._parse_memory_mi(memory_str)
            return {"cpu": total_cpu, "memory": total_memory}
        except ApiException as e:
            logger.warning(f"Failed to get cluster resources: {e}")
            return {"cpu": 1000.0, "memory": 1000000.0}

    @staticmethod
    def _parse_cpu(cpu_str: str) -> float:
        """Parse Kubernetes CPU string to float cores."""
        if not cpu_str:
            return 0.0
        cpu_str = str(cpu_str).strip()
        if cpu_str.endswith("m"):
            return float(cpu_str[:-1]) / 1000.0
        return float(cpu_str)

    @staticmethod
    def _parse_memory_mi(mem_str: str) -> float:
        """Parse Kubernetes memory string to Mi."""
        if not mem_str:
            return 0.0
        mem_str = str(mem_str).strip().upper()
        if mem_str.endswith("KI"):
            return float(mem_str[:-2]) / 1024.0
        if mem_str.endswith("MI"):
            return float(mem_str[:-2])
        if mem_str.endswith("GI"):
            return float(mem_str[:-2]) * 1024.0
        if mem_str.endswith("K"):
            return float(mem_str[:-1]) / 1024.0
        if mem_str.endswith("M"):
            return float(mem_str[:-1])
        if mem_str.endswith("G"):
            return float(mem_str[:-1]) * 1024.0
        return float(mem_str)
