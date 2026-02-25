"""
Unit tests for ResourceValidationService.

Tests cluster resource availability check and fail-fast on insufficient resources.
Skipped if ResourceValidationService is not yet implemented.
"""
import pytest

pytest.importorskip("ml_serve_core.service.resource_validation_service")

from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from ml_serve_core.service.resource_validation_service import ResourceValidationService
from tests.fixtures.factories import EnvironmentFactory


@pytest.mark.unit
@pytest.mark.asyncio
class TestResourceValidationService:
    """Test resource validation."""

    @pytest.fixture
    def mock_k8s_client(self):
        with patch(
            "ml_serve_core.service.resource_validation_service.KubernetesClient"
        ) as mock:
            client = MagicMock()
            client.get_cluster_allocatable_resources = AsyncMock(
                return_value={"cpu": 100.0, "memory": 512000}  # 100 cores, 512GB
            )
            mock.return_value = client
            yield client

    @pytest.fixture
    def service(self, mock_k8s_client):
        return ResourceValidationService()

    async def test_check_resources_sufficient_success(
        self, service, db_session, mock_k8s_client
    ):
        """Test resource check passes when cluster has sufficient resources."""
        env = await EnvironmentFactory.create()
        required = {"cpu": 4, "memory": 8}  # 4 cores, 8GB

        result = await service.check_resources(
            env=env,
            required_cpu=required["cpu"],
            required_memory=required["memory"],
        )

        assert result is True

    async def test_check_resources_insufficient_cpu_fail_fast(
        self, service, db_session, mock_k8s_client
    ):
        """Test resource check fails fast when CPU insufficient."""
        mock_k8s_client.get_cluster_allocatable_resources = AsyncMock(
            return_value={"cpu": 0.5, "memory": 512000}
        )
        env = await EnvironmentFactory.create()

        with pytest.raises(HTTPException) as exc_info:
            await service.check_resources(
                env=env,
                required_cpu=4,
                required_memory=8,
            )

        assert exc_info.value.status_code == 400
        assert "insufficient" in str(exc_info.value.detail).lower()

    async def test_check_resources_insufficient_memory_fail_fast(
        self, service, db_session, mock_k8s_client
    ):
        """Test resource check fails fast when memory insufficient."""
        mock_k8s_client.get_cluster_allocatable_resources = AsyncMock(
            return_value={"cpu": 100.0, "memory": 1000}  # Only 1GB free
        )
        env = await EnvironmentFactory.create()

        with pytest.raises(HTTPException) as exc_info:
            await service.check_resources(
                env=env,
                required_cpu=2,
                required_memory=8,  # 8GB required
            )

        assert exc_info.value.status_code == 400
        assert "insufficient" in str(exc_info.value.detail).lower()
