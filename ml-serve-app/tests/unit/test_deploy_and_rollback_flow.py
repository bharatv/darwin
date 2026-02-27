"""
Integration-style unit tests (DB + mocked DCM) for deploy + rollback flow.

Task 7: Cover deploy-with-strategy and rollback using mocked DCM while exercising
the real service and persistence layer.
"""

import pytest

from ml_serve_app_layer.dtos.requests import APIServeDeploymentConfigRequest
from ml_serve_core.service.deployment_service import DeploymentService
from ml_serve_model import Artifact, Deployment
from ml_serve_model.active_deployment import ActiveDeployment
from ml_serve_model.enums import BackendType, DeploymentStatus
from ml_serve_model.serve_configs import APIServeInfraConfig


@pytest.mark.unit
class TestDeployAndRollbackFlow:
    @pytest.mark.asyncio
    async def test_deploy_canary_then_rollback_to_previous(
        self,
        db_session,
        test_user,
        test_serve,
        test_environment,
        mock_dcm_client,
    ):
        service = DeploymentService()
        service.dcm_client = mock_dcm_client

        infra_config = await APIServeInfraConfig.create(
            serve=test_serve,
            environment=test_environment,
            backend_type=BackendType.FastAPI.value,
            fast_api_config={
                "cores": 2,
                "memory": 4,
                "min_replicas": 1,
                "max_replicas": 3,
                "node_capacity_type": "spot",
            },
            additional_hosts=None,
            created_by=test_user,
            updated_by=test_user,
        )

        artifact_v1 = await Artifact.create(
            serve=test_serve,
            version="v1.0.0",
            github_repo_url="https://github.com/test/repo",
            branch="main",
            image_url="localhost:5000/test-serve:v1.0.0",
            created_by=test_user,
        )
        artifact_v2 = await Artifact.create(
            serve=test_serve,
            version="v2.0.0",
            github_repo_url="https://github.com/test/repo",
            branch="main",
            image_url="localhost:5000/test-serve:v2.0.0",
            created_by=test_user,
        )

        # First deploy: rolling (baseline)
        deployment_1, _ = await service.deploy_api_serve(
            serve=test_serve,
            artifact=artifact_v1,
            env=test_environment,
            api_serve_config=infra_config,
            api_deployment_config=APIServeDeploymentConfigRequest(
                deployment_strategy="rolling",
                deployment_strategy_config=None,
                environment_variables=None,
            ),
            user=test_user,
        )
        await service._update_active_deployment(test_serve, test_environment, deployment_1)

        # Second deploy: canary
        deployment_2, _ = await service.deploy_api_serve(
            serve=test_serve,
            artifact=artifact_v2,
            env=test_environment,
            api_serve_config=infra_config,
            api_deployment_config=APIServeDeploymentConfigRequest(
                deployment_strategy="canary",
                deployment_strategy_config={"stepWeight": 20, "maxWeight": 60},
                environment_variables=None,
            ),
            user=test_user,
        )
        await service._update_active_deployment(test_serve, test_environment, deployment_2)

        # Assert canary values were generated and sent to DCM
        build_kwargs = mock_dcm_client.build_resource.call_args.kwargs
        values = build_kwargs["values"]
        assert values["flagger"]["enabled"] is True
        assert values["flagger"]["type"] == "canary"

        # Rollback without specifying version should go to previous deployment
        result = await service.rollback_api_serve(serve=test_serve, env=test_environment)
        assert result["from_artifact_version"] == "v2.0.0"
        assert result["to_artifact_version"] == "v1.0.0"

        active = await ActiveDeployment.get_or_none(serve=test_serve, environment=test_environment)
        assert active is not None
        assert (await active.deployment).id == deployment_1.id

        d1 = await Deployment.get(id=deployment_1.id)
        d2 = await Deployment.get(id=deployment_2.id)
        assert d1.status == DeploymentStatus.ACTIVE.value
        assert d2.status == DeploymentStatus.ENDED.value

