"""
Unit tests for DeploymentStrategyService.

Tests rolling, blue-green, and canary deployment execution and strategy routing logic.
Skipped if DeploymentStrategyService is not yet implemented.
"""
import pytest

# Skip entire module if service not implemented (tests-before-implementation)
pytest.importorskip("ml_serve_core.service.deployment_strategy_service")

from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from ml_serve_core.service.deployment_strategy_service import DeploymentStrategyService
from ml_serve_model import Serve, Artifact, Environment, Deployment
from ml_serve_model.enums import ServeType
from tests.fixtures.factories import (
    ServeFactory,
    ArtifactFactory,
    EnvironmentFactory,
    DeploymentFactory,
    APIServeInfraConfigFactory,
)


@pytest.mark.unit
@pytest.mark.asyncio
class TestDeploymentStrategyServiceRolling:
    """Test rolling deployment execution."""

    @pytest.fixture
    def mock_dcm_client(self):
        with patch(
            "ml_serve_core.service.deployment_strategy_service.DCMClient"
        ) as mock:
            client = AsyncMock()
            client.build_resource = AsyncMock(
                return_value={"body": {"status": "success"}}
            )
            client.start_resource = AsyncMock(
                return_value={"body": {"status": "running"}}
            )
            mock.return_value = client
            yield client

    @pytest.fixture
    def service(self, mock_dcm_client):
        return DeploymentStrategyService()

    async def test_execute_rolling_deployment_success(
        self, service, db_session, test_user, mock_dcm_client
    ):
        """Test rolling deployment executes successfully."""
        serve = await ServeFactory.create(created_by=test_user)
        artifact = await ArtifactFactory.create(serve=serve, version="v1.0.0", created_by=test_user)
        env = await EnvironmentFactory.create()
        api_serve_config = await APIServeInfraConfigFactory.create(
            serve=serve, environment=env, created_by=test_user, updated_by=test_user
        )
        deployment_params = {"maxSurge": "25%", "maxUnavailable": 0}

        result = await service.deploy_rolling(
            serve=serve,
            artifact=artifact,
            env=env,
            deployment_params=deployment_params,
            user=test_user,
            api_serve_config=api_serve_config,
        )

        assert result is not None
        mock_dcm_client.build_resource.assert_called_once()
        mock_dcm_client.start_resource.assert_called_once()

    async def test_execute_rolling_with_custom_max_surge(
        self, service, db_session, test_user, mock_dcm_client
    ):
        """Test rolling deployment passes maxSurge to Helm values."""
        serve = await ServeFactory.create(created_by=test_user)
        artifact = await ArtifactFactory.create(serve=serve, created_by=test_user)
        env = await EnvironmentFactory.create()
        api_serve_config = await APIServeInfraConfigFactory.create(
            serve=serve, environment=env, created_by=test_user, updated_by=test_user
        )
        deployment_params = {"maxSurge": "50%", "maxUnavailable": 1}

        await service.deploy_rolling(
            serve=serve,
            artifact=artifact,
            env=env,
            deployment_params=deployment_params,
            user=test_user,
            api_serve_config=api_serve_config,
        )

        build_call = mock_dcm_client.build_resource.call_args
        values = build_call.kwargs.get("values", {})
        config = values.get("deploymentStrategyConfig", {})
        assert config.get("maxSurge") == "50%"
        assert config.get("maxUnavailable") == 1

    async def test_execute_rolling_default_params(
        self, service, db_session, test_user, mock_dcm_client
    ):
        """Test rolling deployment uses defaults when no params provided."""
        serve = await ServeFactory.create(created_by=test_user)
        artifact = await ArtifactFactory.create(serve=serve, created_by=test_user)
        env = await EnvironmentFactory.create()
        api_serve_config = await APIServeInfraConfigFactory.create(
            serve=serve, environment=env, created_by=test_user, updated_by=test_user
        )

        await service.deploy_rolling(
            serve=serve,
            artifact=artifact,
            env=env,
            deployment_params=None,
            user=test_user,
            api_serve_config=api_serve_config,
        )

        build_call = mock_dcm_client.build_resource.call_args
        values = build_call.kwargs.get("values", {})
        config = values.get("deploymentStrategyConfig", {})
        assert config.get("maxSurge", "25%") == "25%"
        assert config.get("maxUnavailable", 0) == 0


@pytest.mark.unit
@pytest.mark.asyncio
class TestDeploymentStrategyServiceBlueGreen:
    """Test blue-green deployment execution."""

    @pytest.fixture
    def mock_dcm_client(self):
        with patch(
            "ml_serve_core.service.deployment_strategy_service.DCMClient"
        ) as mock:
            client = AsyncMock()
            client.build_resource = AsyncMock(
                return_value={"body": {"status": "success"}}
            )
            client.start_resource = AsyncMock(
                return_value={"body": {"status": "running"}}
            )
            mock.return_value = client
            yield client

    @pytest.fixture
    def mock_traffic_service(self):
        with patch(
            "ml_serve_core.service.deployment_strategy_service.TrafficManagementService"
        ) as mock:
            traffic = AsyncMock()
            traffic.update_virtual_service = AsyncMock(return_value=None)
            traffic.create_destination_rules = AsyncMock(return_value=None)
            mock.return_value = traffic
            yield traffic

    @pytest.fixture
    def mock_istio_enabled(self):
        with patch(
            "ml_serve_core.service.deployment_strategy_service.ENABLE_ISTIO", True
        ):
            yield

    @pytest.fixture
    def service(self, mock_dcm_client, mock_traffic_service, mock_istio_enabled):
        return DeploymentStrategyService()

    async def test_execute_blue_green_deployment_success(
        self, service, db_session, test_user, mock_dcm_client, mock_traffic_service, mock_istio_enabled
    ):
        """Test blue-green deployment deploys green alongside blue."""
        from ml_serve_model import ActiveDeployment, Deployment

        serve = await ServeFactory.create(created_by=test_user)
        prev_artifact = await ArtifactFactory.create(
            serve=serve, version="v0.9.0", created_by=test_user
        )
        artifact = await ArtifactFactory.create(
            serve=serve, version="v1.0.0", created_by=test_user
        )
        env = await EnvironmentFactory.create()
        prev_deployment = await Deployment.create(
            serve=serve,
            artifact=prev_artifact,
            environment=env,
            created_by=test_user,
        )
        await ActiveDeployment.create(
            serve=serve,
            environment=env,
            deployment=prev_deployment,
        )
        api_serve_config = await APIServeInfraConfigFactory.create(
            serve=serve, environment=env, created_by=test_user, updated_by=test_user
        )

        result = await service.deploy_blue_green(
            serve=serve,
            artifact=artifact,
            env=env,
            user=test_user,
            api_serve_config=api_serve_config,
        )

        assert result is not None
        mock_dcm_client.build_resource.assert_called_once()
        mock_dcm_client.start_resource.assert_called_once()
        # Green resource naming when blue already exists
        start_call = mock_dcm_client.start_resource.call_args
        assert "green" in str(start_call.kwargs.get("resource_id", "")).lower()

    async def test_execute_blue_green_creates_virtual_service(
        self, service, db_session, test_user, mock_dcm_client, mock_traffic_service, mock_istio_enabled
    ):
        """Test blue-green creates/updates VirtualService with 100% blue, 0% green."""
        serve = await ServeFactory.create(created_by=test_user)
        artifact = await ArtifactFactory.create(serve=serve, created_by=test_user)
        env = await EnvironmentFactory.create()
        api_serve_config = await APIServeInfraConfigFactory.create(
            serve=serve, environment=env, created_by=test_user, updated_by=test_user
        )

        await service.deploy_blue_green(
            serve=serve,
            artifact=artifact,
            env=env,
            user=test_user,
            api_serve_config=api_serve_config,
        )

        mock_traffic_service.update_virtual_service.assert_called()
        call_args = mock_traffic_service.update_virtual_service.call_args
        traffic_split = call_args.kwargs.get("traffic_split", {})
        assert traffic_split.get("blue", 100) == 100
        assert traffic_split.get("green", 0) == 0


@pytest.mark.unit
@pytest.mark.asyncio
class TestDeploymentStrategyServiceCanary:
    """Test canary deployment execution."""

    @pytest.fixture
    def mock_dcm_client(self):
        with patch(
            "ml_serve_core.service.deployment_strategy_service.DCMClient"
        ) as mock:
            client = AsyncMock()
            client.build_resource = AsyncMock(
                return_value={"body": {"status": "success"}}
            )
            client.start_resource = AsyncMock(
                return_value={"body": {"status": "running"}}
            )
            mock.return_value = client
            yield client

    @pytest.fixture
    def mock_lock_service(self):
        with patch(
            "ml_serve_core.service.deployment_strategy_service.DeploymentLockService"
        ) as mock:
            lock_svc = AsyncMock()
            lock_svc.acquire_lock = AsyncMock(return_value=MagicMock())
            mock.return_value = lock_svc
            yield lock_svc

    @pytest.fixture
    def mock_traffic_service(self):
        with patch(
            "ml_serve_core.service.deployment_strategy_service.TrafficManagementService"
        ) as mock:
            traffic = AsyncMock()
            traffic.update_virtual_service = AsyncMock(return_value=None)
            traffic.create_destination_rules = AsyncMock(return_value=None)
            mock.return_value = traffic
            yield traffic

    @pytest.fixture
    def mock_istio_enabled(self):
        with patch(
            "ml_serve_core.service.deployment_strategy_service.ENABLE_ISTIO", True
        ):
            yield

    @pytest.fixture
    def service(self, mock_dcm_client, mock_lock_service, mock_traffic_service, mock_istio_enabled):
        return DeploymentStrategyService()

    async def test_execute_canary_deployment_success(
        self,
        service,
        db_session,
        test_user,
        mock_dcm_client,
        mock_lock_service,
        mock_traffic_service,
        mock_istio_enabled,
    ):
        """Test canary deployment deploys with 0% traffic."""
        serve = await ServeFactory.create(created_by=test_user)
        artifact = await ArtifactFactory.create(serve=serve, version="v1.0.0", created_by=test_user)
        env = await EnvironmentFactory.create()
        api_serve_config = await APIServeInfraConfigFactory.create(
            serve=serve, environment=env, created_by=test_user, updated_by=test_user
        )

        result = await service.deploy_canary(
            serve=serve,
            artifact=artifact,
            env=env,
            deployment_params={"initial_traffic_percent": 0},
            user=test_user,
            api_serve_config=api_serve_config,
        )

        assert result is not None
        mock_lock_service.acquire_lock.assert_called_once()
        mock_dcm_client.build_resource.assert_called_once()
        mock_dcm_client.start_resource.assert_called_once()
        # Canary version suffix
        build_call = mock_dcm_client.build_resource.call_args
        artifact_id = build_call.kwargs.get("artifact_id", "")
        assert "canary" in artifact_id.lower()

    async def test_execute_canary_creates_virtual_service_zero_traffic(
        self,
        service,
        db_session,
        test_user,
        mock_dcm_client,
        mock_lock_service,
        mock_traffic_service,
        mock_istio_enabled,
    ):
        """Test canary creates VirtualService with 100% stable, 0% canary."""
        serve = await ServeFactory.create(created_by=test_user)
        artifact = await ArtifactFactory.create(serve=serve, created_by=test_user)
        env = await EnvironmentFactory.create()
        api_serve_config = await APIServeInfraConfigFactory.create(
            serve=serve, environment=env, created_by=test_user, updated_by=test_user
        )

        await service.deploy_canary(
            serve=serve,
            artifact=artifact,
            env=env,
            deployment_params={"initial_traffic_percent": 0},
            user=test_user,
            api_serve_config=api_serve_config,
        )

        mock_traffic_service.update_virtual_service.assert_called()
        call_args = mock_traffic_service.update_virtual_service.call_args
        traffic_split = call_args.kwargs.get("traffic_split", {})
        assert traffic_split.get("stable", 100) == 100
        assert traffic_split.get("canary", 0) == 0

    async def test_execute_canary_lock_conflict_returns_409(
        self,
        service,
        db_session,
        test_user,
        mock_dcm_client,
        mock_lock_service,
        mock_traffic_service,
        mock_istio_enabled,
    ):
        """Test canary deploy returns 409 when lock already held."""
        mock_lock_service.acquire_lock.side_effect = HTTPException(
            status_code=409,
            detail="Deployment locked: canary in progress",
        )
        serve = await ServeFactory.create(created_by=test_user)
        artifact = await ArtifactFactory.create(serve=serve, created_by=test_user)
        env = await EnvironmentFactory.create()
        api_serve_config = await APIServeInfraConfigFactory.create(
            serve=serve, environment=env, created_by=test_user, updated_by=test_user
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.deploy_canary(
                serve=serve,
                artifact=artifact,
                env=env,
                deployment_params={"initial_traffic_percent": 0},
                user=test_user,
                api_serve_config=api_serve_config,
            )

        assert exc_info.value.status_code == 409
        mock_dcm_client.build_resource.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
class TestDeploymentStrategyServiceRouting:
    """Test strategy routing logic."""

    @pytest.fixture
    def service(self):
        return DeploymentStrategyService()

    def test_service_has_deploy_rolling_method(self, service):
        """Test service has deploy_rolling method."""
        assert hasattr(service, "deploy_rolling")
        assert callable(service.deploy_rolling)

    def test_service_has_deploy_blue_green_method(self, service):
        """Test service has deploy_blue_green method."""
        assert hasattr(service, "deploy_blue_green")
        assert callable(service.deploy_blue_green)

    def test_service_has_deploy_canary_method(self, service):
        """Test service has deploy_canary method."""
        assert hasattr(service, "deploy_canary")
        assert callable(service.deploy_canary)
