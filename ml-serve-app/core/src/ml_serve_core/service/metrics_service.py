"""Metrics service for deployment metrics collection and storage."""
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

from ml_serve_model import DeploymentMetric
from loguru import logger

try:
    from ml_serve_core.client.kubernetes_client import KubernetesClient
    K8S_AVAILABLE = True
except ImportError:
    K8S_AVAILABLE = False


class K8sMetricsClient:
    """Client for Kubernetes pod metrics (CPU, memory)."""

    def __init__(self):
        self._k8s = KubernetesClient() if K8S_AVAILABLE else None

    async def get_pod_metrics(
        self, namespace: str, labels: Optional[Dict[str, str]] = None
    ) -> Dict[str, float]:
        """Get CPU (cores) and memory (Mi) for pods matching labels."""
        if not self._k8s:
            return {"cpu": 0.5, "memory": 512.0}
        # Simplified: return mock for now; full impl would use metrics.k8s.io
        return {"cpu": 0.5, "memory": 512.0}


class IstioMetricsClient:
    """Client for Istio request metrics."""

    async def get_request_metrics(
        self,
        namespace: str,
        labels: Optional[Dict[str, str]] = None,
    ) -> Dict[str, float]:
        """Get request_rate, error_rate, latency percentiles."""
        # Simplified: return mock; full impl would query Prometheus/Istio
        return {
            "request_rate": 100.0,
            "error_rate": 0.01,
            "latency_p50": 50.0,
            "latency_p95": 100.0,
            "latency_p99": 200.0,
        }


class MetricsService:
    """Collects and stores deployment metrics with 5-day retention."""

    def __init__(self):
        self._k8s_metrics = K8sMetricsClient()
        self._istio_metrics = IstioMetricsClient()

    async def collect_metrics_from_k8s(
        self, deployment_id: int, namespace: str
    ) -> List[Dict[str, Any]]:
        """Collect CPU/memory metrics from Kubernetes."""
        metrics = await self._k8s_metrics.get_pod_metrics(namespace=namespace)
        return [
            {"metric_name": "cpu", "value": metrics.get("cpu", 0.0)},
            {"metric_name": "memory", "value": metrics.get("memory", 0.0)},
        ]

    async def collect_metrics_from_istio(
        self,
        deployment_id: int,
        namespace: str,
        labels: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Collect request/error/latency metrics from Istio."""
        metrics = await self._istio_metrics.get_request_metrics(
            namespace=namespace, labels=labels
        )
        return [
            {"metric_name": k, "value": v}
            for k, v in metrics.items()
        ]

    async def collect_metrics(
        self,
        deployment_id: int,
        namespace: str,
        labels: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Collect metrics from K8s and Istio."""
        k8s = await self.collect_metrics_from_k8s(deployment_id, namespace)
        istio = await self.collect_metrics_from_istio(
            deployment_id, namespace, labels
        )
        return k8s + istio

    async def store_metrics(
        self,
        deployment_id: int,
        metrics: List[Dict[str, Any]],
        timestamp: datetime,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        """Store metrics in deployment_metrics table."""
        for m in metrics:
            await DeploymentMetric.create(
                deployment_id=deployment_id,
                metric_name=m.get("metric_name", "unknown"),
                value=m.get("value", 0.0),
                timestamp=timestamp,
                labels=labels or {},
            )
        logger.debug(f"Stored {len(metrics)} metrics for deployment {deployment_id}")

    async def get_metrics(
        self,
        deployment_id: int,
        from_time: datetime,
        to_time: datetime,
    ) -> List[Dict[str, Any]]:
        """Retrieve metrics for a deployment in time range."""
        rows = await DeploymentMetric.filter(
            deployment_id=deployment_id,
            timestamp__gte=from_time,
            timestamp__lte=to_time,
        ).all()
        return [
            {
                "metric_name": r.metric_name,
                "value": r.value,
                "timestamp": r.timestamp.isoformat(),
                "labels": r.labels,
            }
            for r in rows
        ]

    async def cleanup_old_metrics(self, retention_days: int = 5) -> int:
        """Delete metrics older than retention_days. Returns deleted count."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        deleted = await DeploymentMetric.filter(timestamp__lt=cutoff).delete()
        if deleted:
            logger.info(f"Cleaned up {deleted} metrics older than {retention_days} days")
        return deleted
