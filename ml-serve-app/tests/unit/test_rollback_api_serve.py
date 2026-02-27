"""
Unit tests for API serve rollback.

Task 6: POST /{serve_name}/rollback -> DeploymentService.rollback_api_serve
"""

import pytest

from ml_serve_core.service.deployment_service import DeploymentService
from ml_serve_core.constants.constants import DEFAULT_RUNTIME
from ml_serve_model import Artifact, Deployment
from ml_serve_model.active_deployment import ActiveDeployment
from ml_serve_model.enums import DeploymentStatus
from fastapi import HTTPException


@pytest.mark.unit
class TestRollbackApiServe:
    @pytest.mark.asyncio
    async def test_rollback_without_artifact_version_rolls_back_to_previous_deployment(
        self,
        db_session,
        test_user,
        test_environment,
        test_serve,
        mock_dcm_client,
    ):
        service = DeploymentService()
        service.dcm_client = mock_dcm_client

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

        previous = await Deployment.create(
            serve=test_serve,
            artifact=artifact_v1,
            environment=test_environment,
            created_by=test_user,
            status=DeploymentStatus.ENDED.value,
        )
        current = await Deployment.create(
            serve=test_serve,
            artifact=artifact_v2,
            environment=test_environment,
            created_by=test_user,
            status=DeploymentStatus.ACTIVE.value,
        )
        active = await ActiveDeployment.create(
            serve=test_serve,
            environment=test_environment,
            deployment=current,
            previous_deployment=previous,
        )

        result = await service.rollback_api_serve(
            serve=test_serve,
            env=test_environment,
        )

        assert result["from_artifact_version"] == "v2.0.0"
        assert result["to_artifact_version"] == "v1.0.0"

        # regular (non one-click) resource id uses env prefix
        mock_dcm_client.stop_resource.assert_awaited()
        mock_dcm_client.start_resource.assert_awaited()
        stop_kwargs = mock_dcm_client.stop_resource.call_args.kwargs
        start_kwargs = mock_dcm_client.start_resource.call_args.kwargs
        assert stop_kwargs["resource_id"] == "test-env-test-serve"
        assert start_kwargs["resource_id"] == "test-env-test-serve"
        assert start_kwargs["artifact_id"] == "test-env-test-serve-v1.0.0"

        refreshed_active = await ActiveDeployment.get(id=active.id)
        assert (await refreshed_active.deployment).id == previous.id

        refreshed_current = await Deployment.get(id=current.id)
        refreshed_previous = await Deployment.get(id=previous.id)
        assert refreshed_current.status == DeploymentStatus.ENDED.value
        assert refreshed_previous.status == DeploymentStatus.ACTIVE.value

    @pytest.mark.asyncio
    async def test_rollback_with_artifact_version_rolls_back_to_specific_deployment(
        self,
        db_session,
        test_user,
        test_environment,
        test_serve,
        mock_dcm_client,
    ):
        service = DeploymentService()
        service.dcm_client = mock_dcm_client

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

        target = await Deployment.create(
            serve=test_serve,
            artifact=artifact_v1,
            environment=test_environment,
            created_by=test_user,
            status=DeploymentStatus.ENDED.value,
        )
        current = await Deployment.create(
            serve=test_serve,
            artifact=artifact_v2,
            environment=test_environment,
            created_by=test_user,
            status=DeploymentStatus.ACTIVE.value,
        )
        await ActiveDeployment.create(
            serve=test_serve,
            environment=test_environment,
            deployment=current,
            previous_deployment=None,
        )

        result = await service.rollback_api_serve(
            serve=test_serve,
            env=test_environment,
            artifact_version="v1.0.0",
        )

        assert result["to_artifact_version"] == "v1.0.0"
        start_kwargs = mock_dcm_client.start_resource.call_args.kwargs
        assert start_kwargs["artifact_id"] == "test-env-test-serve-v1.0.0"

    @pytest.mark.asyncio
    async def test_rollback_one_click_uses_serve_name_resource_id(
        self,
        db_session,
        test_user,
        test_environment,
        test_serve,
        mock_dcm_client,
    ):
        service = DeploymentService()
        service.dcm_client = mock_dcm_client

        artifact_v1 = await Artifact.create(
            serve=test_serve,
            version="v1.0.0",
            github_repo_url="models:/iris/1",
            branch="main",
            image_url=DEFAULT_RUNTIME,
            created_by=test_user,
        )
        artifact_v2 = await Artifact.create(
            serve=test_serve,
            version="v2.0.0",
            github_repo_url="models:/iris/2",
            branch="main",
            image_url=DEFAULT_RUNTIME,
            created_by=test_user,
        )

        previous = await Deployment.create(
            serve=test_serve,
            artifact=artifact_v1,
            environment=test_environment,
            created_by=test_user,
            status=DeploymentStatus.ENDED.value,
        )
        current = await Deployment.create(
            serve=test_serve,
            artifact=artifact_v2,
            environment=test_environment,
            created_by=test_user,
            status=DeploymentStatus.ACTIVE.value,
        )
        await ActiveDeployment.create(
            serve=test_serve,
            environment=test_environment,
            deployment=current,
            previous_deployment=previous,
        )

        await service.rollback_api_serve(serve=test_serve, env=test_environment)

        stop_kwargs = mock_dcm_client.stop_resource.call_args.kwargs
        start_kwargs = mock_dcm_client.start_resource.call_args.kwargs
        assert stop_kwargs["resource_id"] == "test-serve"
        assert start_kwargs["resource_id"] == "test-serve"

    @pytest.mark.asyncio
    async def test_rollback_raises_404_when_no_active_deployment(
        self,
        db_session,
        test_environment,
        test_serve,
        mock_dcm_client,
    ):
        service = DeploymentService()
        service.dcm_client = mock_dcm_client

        with pytest.raises(HTTPException) as exc_info:
            await service.rollback_api_serve(serve=test_serve, env=test_environment)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_rollback_raises_404_when_no_previous_deployment(
        self,
        db_session,
        test_user,
        test_environment,
        test_serve,
        mock_dcm_client,
    ):
        service = DeploymentService()
        service.dcm_client = mock_dcm_client

        artifact_v2 = await Artifact.create(
            serve=test_serve,
            version="v2.0.0",
            github_repo_url="https://github.com/test/repo",
            branch="main",
            image_url="localhost:5000/test-serve:v2.0.0",
            created_by=test_user,
        )
        current = await Deployment.create(
            serve=test_serve,
            artifact=artifact_v2,
            environment=test_environment,
            created_by=test_user,
            status=DeploymentStatus.ACTIVE.value,
        )
        await ActiveDeployment.create(
            serve=test_serve,
            environment=test_environment,
            deployment=current,
            previous_deployment=None,
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.rollback_api_serve(serve=test_serve, env=test_environment)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_rollback_raises_404_when_artifact_version_not_found(
        self,
        db_session,
        test_user,
        test_environment,
        test_serve,
        mock_dcm_client,
    ):
        service = DeploymentService()
        service.dcm_client = mock_dcm_client

        artifact_v2 = await Artifact.create(
            serve=test_serve,
            version="v2.0.0",
            github_repo_url="https://github.com/test/repo",
            branch="main",
            image_url="localhost:5000/test-serve:v2.0.0",
            created_by=test_user,
        )
        current = await Deployment.create(
            serve=test_serve,
            artifact=artifact_v2,
            environment=test_environment,
            created_by=test_user,
            status=DeploymentStatus.ACTIVE.value,
        )
        await ActiveDeployment.create(
            serve=test_serve,
            environment=test_environment,
            deployment=current,
            previous_deployment=None,
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.rollback_api_serve(
                serve=test_serve, env=test_environment, artifact_version="v-does-not-exist"
            )
        assert exc_info.value.status_code == 404

