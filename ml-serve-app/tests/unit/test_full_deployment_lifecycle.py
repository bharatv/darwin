import pytest

from ml_serve_app_layer.dtos.requests import APIServeDeploymentConfigRequest
from ml_serve_core.service.deployment_orchestrator import DeploymentOrchestrator
from ml_serve_core.service.deployment_service import DeploymentService
from ml_serve_model import ActiveDeployment, Deployment, AppLayerDeployment, DeploymentPhase, Artifact
from ml_serve_model.enums import DeploymentStatus, BackendType
from ml_serve_model.serve_configs import APIServeInfraConfig


@pytest.mark.unit
class TestFullDeploymentLifecycle:
    @pytest.mark.asyncio
    async def test_canary_initiate_approve_complete_updates_active_and_ends_previous(
        self,
        db_session,
        test_user,
        test_serve,
        test_environment,
        test_artifact,
        mock_dcm_client,
    ):
        # Arrange: previous live deployment
        infra_config = await APIServeInfraConfig.create(
            serve=test_serve,
            environment=test_environment,
            backend_type=BackendType.FastAPI.value,
            fast_api_config={
                "cores": 1,
                "memory": 1,
                "min_replicas": 2,
                "max_replicas": 4,
                "node_capacity_type": "spot",
            },
            created_by=test_user,
            updated_by=test_user,
        )

        old_deployment = await Deployment.create(
            serve=test_serve,
            artifact=test_artifact,
            environment=test_environment,
            created_by=test_user,
            status=DeploymentStatus.ACTIVE.value,
        )
        await AppLayerDeployment.create(
            deployment=old_deployment,
            deployment_strategy=None,
            deployment_params=None,
            environment_variables={"A": "1"},
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

        svc = DeploymentService()
        svc.dcm_client = mock_dcm_client
        orchestrator = DeploymentOrchestrator(deployment_service=svc)

        cfg = APIServeDeploymentConfigRequest(deployment_strategy="canary", deployment_strategy_config={"steps": [20, 100]})

        # Act: initiate
        init = await orchestrator.initiate_deployment(
            serve=test_serve,
            artifact=new_artifact,
            env=test_environment,
            api_infra_config=infra_config,
            api_deployment_config=cfg,
            user=test_user,
        )

        # Assert: candidate pointer set and awaiting approval
        new_deployment_id = init["deployment_id"]
        active = await ActiveDeployment.get(serve=test_serve, environment=test_environment)
        assert active.candidate_deployment_id == new_deployment_id

        app = await AppLayerDeployment.get(deployment_id=new_deployment_id)
        assert app.requires_approval is True
        assert (app.phase or "").endswith("awaiting-approval")

        # Act: approve step 1 (20%)
        await orchestrator.approve_phase(deployment_id=new_deployment_id, user=test_user, notes="ok-1")
        app = await AppLayerDeployment.get(deployment_id=new_deployment_id)
        assert app.requires_approval is True

        # Act: approve final step (100%) => complete + finalize active pointer
        await orchestrator.approve_phase(deployment_id=new_deployment_id, user=test_user, notes="ok-2")

        app = await AppLayerDeployment.get(deployment_id=new_deployment_id)
        assert app.requires_approval is False
        assert app.phase == "completed"

        active = await ActiveDeployment.get(serve=test_serve, environment=test_environment)
        assert active.candidate_deployment_id is None
        assert active.deployment_id == new_deployment_id
        assert active.previous_deployment_id == old_deployment.id

        ended_old = await Deployment.get(id=old_deployment.id)
        assert ended_old.status == DeploymentStatus.ENDED.value
        assert ended_old.ended_at is not None

        history = await DeploymentPhase.filter(deployment_id=new_deployment_id).order_by("created_at").all()
        assert len(history) >= 2
        assert history[0].approver_username == test_user.username

