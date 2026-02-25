"""Traffic management service for Istio VirtualService and DestinationRule."""
from typing import Dict, Any

from ml_serve_core.client.kubernetes_client import KubernetesClient
from ml_serve_model import Serve, Environment
from loguru import logger


class TrafficManagementService:
    """Manages Istio traffic routing for blue-green and canary deployments."""

    def __init__(self):
        self._k8s_client = KubernetesClient()

    @staticmethod
    def _service_base(serve: Serve, env: Environment) -> str:
        """Base service name aligned with Helm/DCM: {env}-{serve}."""
        return f"{env.name}-{serve.name}"

    def calculate_traffic_split(self, canary_percent: int) -> Dict[str, int]:
        """Calculate stable/canary traffic split from canary percentage."""
        canary_percent = max(0, min(100, canary_percent))
        return {"stable": 100 - canary_percent, "canary": canary_percent}

    def build_virtual_service_manifest(
        self,
        service_base: str,
        namespace: str,
        strategy: str,
        traffic_split: Dict[str, int],
        host: str = None,
    ) -> Dict[str, Any]:
        """
        Build Istio VirtualService manifest.
        strategy: canary | blue_green
        traffic_split: e.g. {"stable": 75, "canary": 25} or {"blue": 100, "green": 0}
        service_base: Aligned with Helm (e.g. {env}-{serve}).
        """
        vs_name = f"{service_base}-vs"
        if host is None:
            host = f"{service_base}.{namespace}.svc.cluster.local"
        routes = []
        for subset, weight in traffic_split.items():
            if weight <= 0:
                continue
            if strategy == "canary":
                svc_name = service_base if subset == "stable" else f"{service_base}-canary"
            else:
                svc_name = service_base if subset == "blue" else f"{service_base}-green"
            routes.append({
                "destination": {
                    "host": f"{svc_name}.{namespace}.svc.cluster.local",
                    "subset": subset,
                },
                "weight": weight,
            })
        if not routes:
            routes = [{"destination": {"host": host, "subset": "stable"}, "weight": 100}]
        return {
            "apiVersion": "networking.istio.io/v1beta1",
            "kind": "VirtualService",
            "metadata": {"name": vs_name, "namespace": namespace},
            "spec": {
                "hosts": [host],
                "http": [{"route": routes}],
            },
        }

    def build_destination_rule_manifest(
        self,
        service_base: str,
        namespace: str,
        subset: str,
    ) -> Dict[str, Any]:
        """Build Istio DestinationRule for a single subset."""
        if subset in ("canary", "green"):
            svc_name = f"{service_base}-{subset}"
        else:
            svc_name = service_base
        return {
            "apiVersion": "networking.istio.io/v1beta1",
            "kind": "DestinationRule",
            "metadata": {"name": f"{svc_name}-dr", "namespace": namespace},
            "spec": {
                "host": f"{svc_name}.{namespace}.svc.cluster.local",
                "subsets": [{"name": subset, "labels": {"version": subset}}],
            },
        }

    async def update_virtual_service(
        self,
        serve: Serve,
        env: Environment,
        strategy: str,
        traffic_split: Dict[str, int],
    ) -> None:
        """Create or update VirtualService with traffic split."""
        namespace = env.namespace
        service_base = self._service_base(serve, env)
        manifest = self.build_virtual_service_manifest(
            service_base=service_base,
            namespace=namespace,
            strategy=strategy,
            traffic_split=traffic_split,
        )
        await self._k8s_client.apply_virtual_service(
            namespace=namespace, vs_manifest=manifest
        )
        logger.info(
            f"VirtualService updated for {serve.name} in {namespace}: {traffic_split}"
        )

    async def create_destination_rules(
        self,
        serve: Serve,
        env: Environment,
        strategy: str,
    ) -> None:
        """Create DestinationRules for stable/canary or blue/green subsets."""
        namespace = env.namespace
        service_base = self._service_base(serve, env)
        subsets = ["stable", "canary"] if strategy == "canary" else ["blue", "green"]
        for subset in subsets:
            manifest = self.build_destination_rule_manifest(
                service_base=service_base,
                namespace=namespace,
                subset=subset,
            )
            await self._k8s_client.apply_destination_rule(
                namespace=namespace, dr_manifest=manifest
            )
        logger.info(f"DestinationRules created for {serve.name} in {namespace}")
