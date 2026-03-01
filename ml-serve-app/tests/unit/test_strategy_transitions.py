import pytest
from unittest.mock import AsyncMock

from ml_serve_core.service.deployment_service import DeploymentService
from ml_serve_core.strategies.canary import CanaryStrategy
from ml_serve_core.strategies.blue_green import BlueGreenStrategy
from ml_serve_core.strategies.rolling import RollingStrategy
from ml_serve_model import Deployment, AppLayerDeployment, APIServeInfraConfig, Artifact
from ml_serve_model.enums import BackendType


@pytest.mark.unit
class TestStrategyTransitions:
    @pytest.mark.asyncio
    async def test_canary_final_promotion_stops_canary(
        self,
        db_session,
        test_user,
        test_serve,
        test_environment,
    ):
        # Arrange
        infra = await APIServeInfraConfig.create(
            serve=test_serve,
            environment=test_environment,
            backend_type=BackendType.FastAPI.value,
            fast_api_config={"cores": 1, "memory": 1, "min_replicas": 2, "max_replicas": 2, "node_capacity_type": "spot"},
            created_by=test_user,
            updated_by=test_user,
        )

        prev_artifact = await Artifact.create(
            serve=test_serve,
            version="v0",
            github_repo_url="https://github.com/test/repo",
            branch="main",
            image_url="localhost:5000/test-serve:v0",
            created_by=test_user,
        )
        new_artifact = await Artifact.create(
            serve=test_serve,
            version="v1",
            github_repo_url="https://github.com/test/repo",
            branch="main",
            image_url="localhost:5000/test-serve:v1",
            created_by=test_user,
        )
        deployment = await Deployment.create(
            serve=test_serve,
            artifact=new_artifact,
            environment=test_environment,
            created_by=test_user,
        )
        app_layer = await AppLayerDeployment.create(
            deployment=deployment,
            deployment_strategy="canary",
            deployment_params={"steps": [20, 100]},
            environment_variables={},
            phase="canary-20",
            phase_metadata={
                "steps": [20, 100],
                "step_index": 0,
                "total_replicas": 2,
                "primary_resource_id": f"{test_environment.name}-{test_serve.name}",
                "primary_artifact_id": f"{test_environment.name}-{test_serve.name}-{prev_artifact.version}",
                "canary_resource_id": f"{test_environment.name}-{test_serve.name}-canary",
                "canary_artifact_id": f"{test_environment.name}-{test_serve.name}-canary-{new_artifact.version}",
            },
            requires_approval=True,
        )

        svc = DeploymentService()
        svc.dcm_client = AsyncMock()
        svc._build_and_start_fastapi_release = AsyncMock()

        strategy = CanaryStrategy(svc)

        # Act
        result = await strategy.progress_phase(
            deployment=deployment,
            app_layer_deployment=app_layer,
            user=test_user,
            notes="promote",
        )

        # Assert
        assert result.requires_approval is False
        svc._build_and_start_fastapi_release.assert_awaited()
        svc.dcm_client.stop_resource.assert_awaited()

    @pytest.mark.asyncio
    async def test_blue_green_approval_switches_service_and_stops_green(
        self,
        db_session,
        test_user,
        test_serve,
        test_environment,
        test_artifact,
    ):
        infra = await APIServeInfraConfig.create(
            serve=test_serve,
            environment=test_environment,
            backend_type=BackendType.FastAPI.value,
            fast_api_config={"cores": 1, "memory": 1, "min_replicas": 2, "max_replicas": 2, "node_capacity_type": "spot"},
            created_by=test_user,
            updated_by=test_user,
        )
        deployment = await Deployment.create(
            serve=test_serve,
            artifact=test_artifact,
            environment=test_environment,
            created_by=test_user,
        )
        app_layer = await AppLayerDeployment.create(
            deployment=deployment,
            deployment_strategy="blue-green",
            deployment_params=None,
            environment_variables={},
            phase="blue-green-awaiting-approval",
            phase_metadata={
                "primary_resource_id": f"{test_environment.name}-{test_serve.name}",
                "primary_artifact_id": f"{test_environment.name}-{test_serve.name}-v0",
                "green_resource_id": f"{test_environment.name}-{test_serve.name}-green",
                "green_artifact_id": f"{test_environment.name}-{test_serve.name}-green-{test_artifact.version}",
            },
            requires_approval=True,
        )

        svc = DeploymentService()
        svc.dcm_client = AsyncMock()
        svc._build_and_start_fastapi_release = AsyncMock()

        strategy = BlueGreenStrategy(svc)

        result = await strategy.progress_phase(
            deployment=deployment,
            app_layer_deployment=app_layer,
            user=test_user,
            notes="switch",
        )

        assert result.requires_approval is False
        # switchover + scale down old + converge + reset selector
        assert svc.dcm_client.update_resource.await_count >= 2
        svc.dcm_client.stop_resource.assert_awaited()
        svc._build_and_start_fastapi_release.assert_awaited()

    @pytest.mark.asyncio
    async def test_rolling_mid_checkpoint_scales_both_releases(
        self,
        db_session,
        test_user,
        test_serve,
        test_environment,
        test_artifact,
    ):
        await APIServeInfraConfig.create(
            serve=test_serve,
            environment=test_environment,
            backend_type=BackendType.FastAPI.value,
            fast_api_config={"cores": 1, "memory": 1, "min_replicas": 10, "max_replicas": 10, "node_capacity_type": "spot"},
            created_by=test_user,
            updated_by=test_user,
        )
        deployment = await Deployment.create(
            serve=test_serve,
            artifact=test_artifact,
            environment=test_environment,
            created_by=test_user,
        )
        app_layer = await AppLayerDeployment.create(
            deployment=deployment,
            deployment_strategy="rolling",
            deployment_params={"checkpoints": [20, 50, 100]},
            environment_variables={},
            phase="rolling-20",
            phase_metadata={
                "checkpoints": [20, 50, 100],
                "checkpoint_index": 0,
                "total_replicas": 10,
                "primary_resource_id": f"{test_environment.name}-{test_serve.name}",
                "primary_artifact_id": f"{test_environment.name}-{test_serve.name}-v0",
                "rolling_resource_id": f"{test_environment.name}-{test_serve.name}-rolling",
                "rolling_artifact_id": f"{test_environment.name}-{test_serve.name}-rolling-{test_artifact.version}",
            },
            requires_approval=True,
        )

        svc = DeploymentService()
        svc.dcm_client = AsyncMock()
        svc._build_and_start_fastapi_release = AsyncMock()

        strategy = RollingStrategy(svc)
        result = await strategy.progress_phase(
            deployment=deployment,
            app_layer_deployment=app_layer,
            user=test_user,
            notes="advance",
        )

        assert result.requires_approval is True
        assert result.phase == "rolling-50"
        # should scale both rolling and primary
        assert svc.dcm_client.update_resource.await_count >= 2

