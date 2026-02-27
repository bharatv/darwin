"""
Unit tests for deployment strategy wiring in deployment service.

Task 5: deploy_fastapi_serve and deploy_model pass strategy to values generation.
"""
import pytest
from unittest.mock import AsyncMock

from ml_serve_app_layer.dtos.requests import (
    APIServeDeploymentConfigRequest,
    ModelDeploymentRequest,
)
from ml_serve_core.service.deployment_service import DeploymentService
from ml_serve_model import Serve, Artifact, Environment, Deployment
from ml_serve_model.enums import ServeType, BackendType
from ml_serve_model.serve_configs import APIServeInfraConfig
from ml_serve_model.active_deployment import ActiveDeployment
from ml_serve_model.app_layer_deployments import AppLayerDeployment


@pytest.mark.unit
class TestDeployFastapiServeStrategyWiring:
    """Test deploy_fastapi_serve passes strategy to generate_fastapi_values."""

    @pytest.mark.asyncio
    async def test_deploy_fastapi_serve_with_canary_config_produces_flagger_enabled(
        self,
        db_session,
        test_user,
        test_serve,
        test_artifact,
        test_environment,
        mock_dcm_client,
    ):
        """deploy_fastapi_serve with canary config produces values['flagger']['enabled'] == True."""
        service = DeploymentService()
        service.dcm_client = mock_dcm_client

        infra_config = await APIServeInfraConfig.create(
            serve=test_serve,
            environment=test_environment,
            backend_type=BackendType.FastAPI.value,
            fast_api_config={
                "cores": 4,
                "memory": 8,
                "min_replicas": 2,
                "max_replicas": 10,
                "node_capacity_type": "spot",
            },
            created_by=test_user,
            updated_by=test_user,
        )

        deployment_config = APIServeDeploymentConfigRequest(
            deployment_strategy="canary",
            deployment_strategy_config={"stepWeight": 20, "maxWeight": 60},
            environment_variables=None,
        )

        await service.deploy_fastapi_serve(
            serve=test_serve,
            artifact=test_artifact,
            env=test_environment,
            api_deployment_config=deployment_config,
            infra_config=infra_config,
            user=test_user,
        )

        call_args = mock_dcm_client.build_resource.call_args
        values = call_args.kwargs["values"]
        assert values["flagger"]["enabled"] is True
        assert values["flagger"]["type"] == "canary"
        assert values["flagger"]["stepWeight"] == 20
        assert values["flagger"]["maxWeight"] == 60

    @pytest.mark.asyncio
    async def test_deploy_fastapi_serve_with_none_config_produces_flagger_disabled(
        self,
        db_session,
        test_user,
        test_serve,
        test_artifact,
        test_environment,
        mock_dcm_client,
    ):
        """deploy_fastapi_serve with None config produces values['flagger']['enabled'] == False."""
        service = DeploymentService()
        service.dcm_client = mock_dcm_client

        infra_config = await APIServeInfraConfig.create(
            serve=test_serve,
            environment=test_environment,
            backend_type=BackendType.FastAPI.value,
            fast_api_config={
                "cores": 4,
                "memory": 8,
                "min_replicas": 2,
                "max_replicas": 10,
                "node_capacity_type": "spot",
            },
            created_by=test_user,
            updated_by=test_user,
        )

        await service.deploy_fastapi_serve(
            serve=test_serve,
            artifact=test_artifact,
            env=test_environment,
            api_deployment_config=None,
            infra_config=infra_config,
            user=test_user,
        )

        call_args = mock_dcm_client.build_resource.call_args
        values = call_args.kwargs["values"]
        assert values["flagger"]["enabled"] is False


@pytest.mark.unit
class TestDeployModelStrategyWiring:
    """Test deploy_model passes strategy to generate_fastapi_values_for_one_click_model_deployment."""

    @pytest.mark.asyncio
    async def test_deploy_model_with_strategy_passes_through_to_values(
        self,
        db_session,
        test_user,
        test_environment,
        mock_dcm_client,
        mock_mlflow_client,
    ):
        """deploy_model with strategy passes through to values."""
        service = DeploymentService()
        service.dcm_client = mock_dcm_client
        service.mlflow_client = mock_mlflow_client

        request = ModelDeploymentRequest(
            serve_name="canary-model",
            artifact_version="v1",
            model_uri="models:/iris-classifier/1",
            env="test-env",
            deployment_strategy="canary",
            deployment_strategy_config={"stepWeight": 15, "maxWeight": 80},
            cores=2,
            memory=4,
            min_replicas=1,
            max_replicas=3,
            node_capacity="spot",
        )

        await service.deploy_model(request, test_user)

        call_args = mock_dcm_client.build_resource.call_args
        values = call_args.kwargs["values"]
        assert values["flagger"]["enabled"] is True
        assert values["flagger"]["type"] == "canary"
        assert values["flagger"]["stepWeight"] == 15
        assert values["flagger"]["maxWeight"] == 80


@pytest.mark.unit
class TestRedeployStrategyPreservation:
    """Test redeploy_api_serve_with_updated_infra_config preserves strategy from deployment."""

    @pytest.mark.asyncio
    async def test_redeploy_fallback_rebuild_preserves_deployment_strategy(
        self,
        db_session,
        test_user,
        test_serve,
        test_artifact,
        test_environment,
        mock_dcm_client,
    ):
        """When redeploy falls back to rebuild, values include deployment strategy from deployment."""
        service = DeploymentService()
        service.dcm_client = mock_dcm_client

        infra_config = await APIServeInfraConfig.create(
            serve=test_serve,
            environment=test_environment,
            backend_type=BackendType.FastAPI.value,
            fast_api_config={
                "cores": 4,
                "memory": 8,
                "min_replicas": 2,
                "max_replicas": 10,
                "node_capacity_type": "spot",
            },
            created_by=test_user,
            updated_by=test_user,
        )

        deployment = await Deployment.create(
            serve=test_serve,
            artifact=test_artifact,
            environment=test_environment,
            created_by=test_user,
        )
        await AppLayerDeployment.create(
            deployment=deployment,
            deployment_strategy="canary",
            deployment_params={"stepWeight": 25, "maxWeight": 60},
            environment_variables=None,
        )
        await ActiveDeployment.create(
            serve=test_serve,
            environment=test_environment,
            deployment=deployment,
        )

        updated_infra_config = await APIServeInfraConfig.get(id=infra_config.id)
        updated_infra_config.fast_api_config = {
            "cores": 8,
            "memory": 16,
            "min_replicas": 2,
            "max_replicas": 10,
            "node_capacity_type": "spot",
        }
        await updated_infra_config.save()

        mock_dcm_client.update_resource.side_effect = Exception("Artifact not found")

        await service.redeploy_api_serve_with_updated_infra_config(
            serve=test_serve,
            env=test_environment,
            user=test_user,
            api_serve_config=updated_infra_config,
        )

        call_args = mock_dcm_client.build_resource.call_args
        values = call_args.kwargs["values"]
        assert values["flagger"]["enabled"] is True
        assert values["flagger"]["type"] == "canary"
        assert values["flagger"]["stepWeight"] == 25
        assert values["flagger"]["maxWeight"] == 60
