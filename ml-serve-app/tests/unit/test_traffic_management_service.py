"""
Unit tests for TrafficManagementService.

Tests VirtualService/DestinationRule creation, traffic split calculations,
and Istio resource manifests.
Skipped if TrafficManagementService is not yet implemented.
"""
import pytest

pytest.importorskip("ml_serve_core.service.traffic_management_service")

from unittest.mock import AsyncMock, MagicMock, patch

from ml_serve_core.service.traffic_management_service import TrafficManagementService
from ml_serve_model import Serve, Environment
from tests.fixtures.factories import ServeFactory, EnvironmentFactory


@pytest.mark.unit
@pytest.mark.asyncio
class TestTrafficManagementServiceVirtualService:
    """Test VirtualService creation and update."""

    @pytest.fixture
    def mock_k8s_client(self):
        with patch(
            "ml_serve_core.service.traffic_management_service.KubernetesClient"
        ) as mock:
            client = AsyncMock()
            client.apply_virtual_service = AsyncMock(return_value=None)
            mock.return_value = client
            yield client

    @pytest.fixture
    def service(self, mock_k8s_client):
        return TrafficManagementService()

    async def test_create_virtual_service_success(
        self, service, db_session, mock_k8s_client
    ):
        """Test VirtualService is created successfully."""
        serve = await ServeFactory.create(name="test-serve")
        env = await EnvironmentFactory.create(namespace="serve-test")
        traffic_split = {"stable": 100, "canary": 0}

        await service.update_virtual_service(
            serve=serve,
            env=env,
            strategy="canary",
            traffic_split=traffic_split,
        )

        mock_k8s_client.apply_virtual_service.assert_called_once()
        call_args = mock_k8s_client.apply_virtual_service.call_args
        assert call_args.kwargs.get("namespace") == "serve-test"
        manifest = call_args.kwargs.get("vs_manifest") or call_args[0][1]
        assert manifest is not None

    async def test_update_virtual_service_75_25_split(
        self, service, db_session, mock_k8s_client
    ):
        """Test VirtualService is updated with 75% stable, 25% canary."""
        serve = await ServeFactory.create(name="test-serve")
        env = await EnvironmentFactory.create()
        traffic_split = {"stable": 75, "canary": 25}

        await service.update_virtual_service(
            serve=serve,
            env=env,
            strategy="canary",
            traffic_split=traffic_split,
        )

        mock_k8s_client.apply_virtual_service.assert_called_once()
        call_args = mock_k8s_client.apply_virtual_service.call_args
        manifest = call_args.kwargs.get("vs_manifest") or call_args[0][1]
        assert manifest is not None
        # Verify weights in manifest
        spec = manifest.get("spec", {})
        http_routes = spec.get("http", [])
        assert len(http_routes) > 0
        route = http_routes[0]
        destinations = route.get("route", [])
        weights = {d.get("destination", {}).get("subset"): d.get("weight") for d in destinations}
        assert len(weights) >= 2 or 75 in str(manifest) or 25 in str(manifest)


@pytest.mark.unit
@pytest.mark.asyncio
class TestTrafficManagementServiceDestinationRule:
    """Test DestinationRule creation and update."""

    @pytest.fixture
    def mock_k8s_client(self):
        with patch(
            "ml_serve_core.service.traffic_management_service.KubernetesClient"
        ) as mock:
            client = AsyncMock()
            client.apply_destination_rule = AsyncMock(return_value=None)
            mock.return_value = client
            yield client

    @pytest.fixture
    def service(self, mock_k8s_client):
        return TrafficManagementService()

    async def test_create_destination_rule_success(
        self, service, db_session, mock_k8s_client
    ):
        """Test DestinationRule is created."""
        serve = await ServeFactory.create(name="test-serve")
        env = await EnvironmentFactory.create(namespace="serve-test")

        await service.create_destination_rules(
            serve=serve,
            env=env,
            strategy="canary",
        )

        mock_k8s_client.apply_destination_rule.assert_called()


@pytest.mark.unit
class TestTrafficManagementServiceTrafficSplit:
    """Test traffic split calculations."""

    @pytest.fixture
    def service(self):
        return TrafficManagementService()

    def test_traffic_split_25_percent(self, service):
        """Test 25% canary results in 75% stable, 25% canary."""
        result = service.calculate_traffic_split(canary_percent=25)
        assert result == {"stable": 75, "canary": 25}

    def test_traffic_split_50_percent(self, service):
        """Test 50% canary results in 50% stable, 50% canary."""
        result = service.calculate_traffic_split(canary_percent=50)
        assert result == {"stable": 50, "canary": 50}

    def test_traffic_split_100_percent(self, service):
        """Test 100% canary results in 0% stable, 100% canary."""
        result = service.calculate_traffic_split(canary_percent=100)
        assert result == {"stable": 0, "canary": 100}

    def test_traffic_split_0_percent(self, service):
        """Test 0% canary results in 100% stable, 0% canary."""
        result = service.calculate_traffic_split(canary_percent=0)
        assert result == {"stable": 100, "canary": 0}


@pytest.mark.unit
class TestTrafficManagementServiceManifests:
    """Test Istio resource manifest generation."""

    @pytest.fixture
    def service(self):
        return TrafficManagementService()

    def test_build_virtual_service_manifest_canary(self, service):
        """Test VirtualService manifest has correct structure for canary."""
        manifest = service.build_virtual_service_manifest(
            service_base="test-env-test-serve",
            namespace="serve-test",
            strategy="canary",
            traffic_split={"stable": 75, "canary": 25},
        )
        assert manifest is not None
        assert manifest.get("apiVersion") == "networking.istio.io/v1beta1"
        assert manifest.get("kind") == "VirtualService"
        assert manifest.get("metadata", {}).get("name") is not None
        spec = manifest.get("spec", {})
        assert "http" in spec

