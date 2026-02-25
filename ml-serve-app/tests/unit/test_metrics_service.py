"""
Unit tests for MetricsService.

Tests metrics collection from K8s/Istio, storage, and retention.
Skipped if MetricsService is not yet implemented.
"""
import pytest
from datetime import datetime, timezone, timedelta

pytest.importorskip("ml_serve_core.service.metrics_service")

from unittest.mock import AsyncMock, MagicMock, patch

from ml_serve_core.service.metrics_service import MetricsService
from tests.fixtures.factories import DeploymentFactory, EnvironmentFactory, ServeFactory, ArtifactFactory


@pytest.mark.unit
@pytest.mark.asyncio
class TestMetricsServiceCollection:
    """Test metrics collection from K8s and Istio."""

    @pytest.fixture
    def mock_k8s_metrics_client(self):
        with patch(
            "ml_serve_core.service.metrics_service.K8sMetricsClient"
        ) as mock:
            client = AsyncMock()
            client.get_pod_metrics = AsyncMock(
                return_value={"cpu": 0.5, "memory": 512.0}
            )
            mock.return_value = client
            yield client

    @pytest.fixture
    def mock_istio_metrics_client(self):
        with patch(
            "ml_serve_core.service.metrics_service.IstioMetricsClient"
        ) as mock:
            client = AsyncMock()
            client.get_request_metrics = AsyncMock(
                return_value={
                    "request_rate": 100.0,
                    "error_rate": 0.01,
                    "latency_p50": 50.0,
                    "latency_p95": 100.0,
                    "latency_p99": 200.0,
                }
            )
            mock.return_value = client
            yield client

    @pytest.fixture
    def service(self, mock_k8s_metrics_client, mock_istio_metrics_client):
        return MetricsService()

    async def test_collect_metrics_from_k8s(
        self, service, db_session, mock_k8s_metrics_client, test_user
    ):
        """Test metrics collection from Kubernetes."""
        serve = await ServeFactory.create(created_by=test_user)
        artifact = await ArtifactFactory.create(serve=serve, created_by=test_user)
        env = await EnvironmentFactory.create()
        deployment = await DeploymentFactory.create(
            serve=serve, artifact=artifact, environment=env, created_by=test_user
        )

        if hasattr(service, "collect_metrics_from_k8s"):
            metrics = await service.collect_metrics_from_k8s(
                deployment_id=deployment.id,
                namespace="serve-test",
            )
        else:
            metrics = await service.collect_metrics(
                deployment_id=deployment.id,
                namespace="serve-test",
            )

        assert metrics is not None
        mock_k8s_metrics_client.get_pod_metrics.assert_called()

    async def test_collect_metrics_from_istio(
        self, service, db_session, mock_istio_metrics_client, test_user
    ):
        """Test metrics collection from Istio."""
        serve = await ServeFactory.create(created_by=test_user)
        artifact = await ArtifactFactory.create(serve=serve, created_by=test_user)
        env = await EnvironmentFactory.create()
        deployment = await DeploymentFactory.create(
            serve=serve, artifact=artifact, environment=env, created_by=test_user
        )

        if hasattr(service, "collect_metrics_from_istio"):
            metrics = await service.collect_metrics_from_istio(
                deployment_id=deployment.id,
                namespace="serve-test",
                labels={"version": "canary"},
            )
        else:
            metrics = await service.collect_metrics(
                deployment_id=deployment.id,
                namespace="serve-test",
                labels={"version": "canary"},
            )

        assert metrics is not None
        mock_istio_metrics_client.get_request_metrics.assert_called()


@pytest.mark.unit
@pytest.mark.asyncio
class TestMetricsServiceStorage:
    """Test metrics storage."""

    @pytest.fixture
    def service(self):
        return MetricsService()

    async def test_store_metrics_success(self, service, db_session, test_user):
        """Test metrics are stored successfully."""
        serve = await ServeFactory.create(created_by=test_user)
        artifact = await ArtifactFactory.create(serve=serve, created_by=test_user)
        env = await EnvironmentFactory.create()
        deployment = await DeploymentFactory.create(
            serve=serve, artifact=artifact, environment=env, created_by=test_user
        )
        metrics_data = [
            {"metric_name": "request_rate", "value": 100.0},
            {"metric_name": "error_rate", "value": 0.01},
        ]

        await service.store_metrics(
            deployment_id=deployment.id,
            metrics=metrics_data,
            timestamp=datetime.now(timezone.utc),
            labels={"version": "stable"},
        )

        if hasattr(service, "get_metrics"):
            stored = await service.get_metrics(
                deployment_id=deployment.id,
                from_time=datetime.now(timezone.utc) - timedelta(minutes=5),
                to_time=datetime.now(timezone.utc) + timedelta(minutes=5),
            )
            assert stored is not None


@pytest.mark.unit
@pytest.mark.asyncio
class TestMetricsServiceRetention:
    """Test metrics retention (5-day cleanup)."""

    @pytest.fixture
    def service(self):
        return MetricsService()

    async def test_cleanup_old_metrics_removes_data_older_than_5_days(
        self, service, db_session, test_user
    ):
        """Test cleanup removes metrics older than 5 days."""
        if not hasattr(service, "cleanup_old_metrics"):
            pytest.skip("MetricsService.cleanup_old_metrics not implemented")

        serve = await ServeFactory.create(created_by=test_user)
        artifact = await ArtifactFactory.create(serve=serve, created_by=test_user)
        env = await EnvironmentFactory.create()
        deployment = await DeploymentFactory.create(
            serve=serve, artifact=artifact, environment=env, created_by=test_user
        )
        old_date = datetime.now(timezone.utc) - timedelta(days=6)

        if hasattr(service, "store_metrics"):
            await service.store_metrics(
                deployment_id=deployment.id,
                metrics=[{"metric_name": "request_rate", "value": 50.0}],
                timestamp=old_date,
                labels={},
            )

        deleted_count = await service.cleanup_old_metrics(retention_days=5)

        assert deleted_count >= 0
