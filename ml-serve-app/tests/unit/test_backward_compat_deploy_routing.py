import pytest

from ml_serve_app_layer.dtos.requests import DeploymentRequest
from ml_serve_core.service.deployment_service import DeploymentService
from ml_serve_model import Deployment, AppLayerDeployment, ActiveDeployment, Artifact
from ml_serve_model.enums import DeploymentStatus, BackendType
from ml_serve_model.serve_configs import APIServeInfraConfig


@pytest.mark.unit
class TestBackwardCompatDeployRouting:
    @pytest.mark.asyncio
    async def test_deploy_artifact_without_strategy_uses_legacy_flow_even_if_previous_stored_strategy(
        self,
        db_session,
        test_user,
        test_serve,
        test_environment,
        test_artifact,
        mock_dcm_client,
    ):
        service = DeploymentService()
        service.dcm_client = mock_dcm_client

        infra_config = await APIServeInfraConfig.create(
            serve=test_serve,
            environment=test_environment,
            backend_type=BackendType.FastAPI.value,
            fast_api_config={
                "cores": 1,
                "memory": 1,
                "min_replicas": 1,
                "max_replicas": 2,
                "node_capacity_type": "spot",
            },
            created_by=test_user,
            updated_by=test_user,
        )

        # Previous deployment exists and has a stored strategy ("rolling") in DB
        old_deployment = await Deployment.create(
            serve=test_serve,
            artifact=test_artifact,
            environment=test_environment,
            created_by=test_user,
            status=DeploymentStatus.ACTIVE.value,
        )
        await AppLayerDeployment.create(
            deployment=old_deployment,
            deployment_strategy="rolling",
            deployment_params={"checkpoints": [50, 100]},
            environment_variables={"X": "1"},
        )
        await ActiveDeployment.create(serve=test_serve, environment=test_environment, deployment=old_deployment)

        new_artifact = await Artifact.create(
            serve=test_serve,
            version="v2.0.0",
            github_repo_url="https://github.com/test/repo",
            branch="main",
            image_url="localhost:5000/test-serve:v2.0.0",
            created_by=test_user,
        )

        # Caller does NOT specify api_serve_deployment_config at all (legacy behavior)
        req = DeploymentRequest(env=test_environment.name, artifact_version=new_artifact.version, api_serve_deployment_config=None)

        resp = await service.deploy_artifact(
            serve=test_serve,
            artifact=new_artifact,
            serve_config=infra_config,
            env=test_environment,
            deployment_request=req,
            user=test_user,
        )

        assert resp is not None
        assert mock_dcm_client.build_resource.called
        assert mock_dcm_client.start_resource.called

        # ActiveDeployment pointer should have advanced immediately (legacy path)
        active = await ActiveDeployment.get(serve=test_serve, environment=test_environment)
        assert active.deployment_id != old_deployment.id
        assert active.candidate_deployment_id is None

