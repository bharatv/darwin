"""
Unit tests for DeploymentLockService.

Tests lock acquisition, release, and concurrent lock attempts.
Skipped if DeploymentLockService is not yet implemented.
"""
import pytest

pytest.importorskip("ml_serve_core.service.deployment_lock_service")

from unittest.mock import AsyncMock, patch
from fastapi import HTTPException

from ml_serve_core.service.deployment_lock_service import DeploymentLockService
from tests.fixtures.factories import (
    ServeFactory,
    EnvironmentFactory,
)


@pytest.mark.unit
@pytest.mark.asyncio
class TestDeploymentLockServiceAcquisition:
    """Test lock acquisition."""

    @pytest.fixture
    def service(self):
        return DeploymentLockService()

    async def test_acquire_lock_success(self, service, db_session, test_user):
        """Test lock acquisition succeeds when not locked."""
        serve = await ServeFactory.create(created_by=test_user)
        env = await EnvironmentFactory.create()

        lock = await service.acquire_lock(
            serve_id=serve.id,
            environment_id=env.id,
        )

        assert lock is not None
        assert lock.serve_id == serve.id
        assert lock.environment_id == env.id

    async def test_acquire_lock_409_when_already_locked(
        self, service, db_session, test_user
    ):
        """Test lock acquisition returns 409 when already locked."""
        serve = await ServeFactory.create(created_by=test_user)
        env = await EnvironmentFactory.create()

        await service.acquire_lock(serve_id=serve.id, environment_id=env.id)

        with pytest.raises(HTTPException) as exc_info:
            await service.acquire_lock(
                serve_id=serve.id,
                environment_id=env.id,
            )

        assert exc_info.value.status_code == 409
        assert "locked" in str(exc_info.value.detail).lower()


@pytest.mark.unit
@pytest.mark.asyncio
class TestDeploymentLockServiceRelease:
    """Test lock release."""

    @pytest.fixture
    def service(self):
        return DeploymentLockService()

    async def test_release_lock_success(self, service, db_session, test_user):
        """Test lock release succeeds."""
        serve = await ServeFactory.create(created_by=test_user)
        env = await EnvironmentFactory.create()
        await service.acquire_lock(serve_id=serve.id, environment_id=env.id)

        await service.release_lock(
            serve_id=serve.id,
            environment_id=env.id,
        )

        is_locked = await service.is_locked(serve_id=serve.id, environment_id=env.id)
        assert is_locked is False

    async def test_release_lock_idempotent(self, service, db_session, test_user):
        """Test releasing non-existent lock does not raise."""
        serve = await ServeFactory.create(created_by=test_user)
        env = await EnvironmentFactory.create()

        await service.release_lock(
            serve_id=serve.id,
            environment_id=env.id,
        )
        # Should not raise


@pytest.mark.unit
@pytest.mark.asyncio
class TestDeploymentLockServiceIsLocked:
    """Test is_locked check."""

    @pytest.fixture
    def service(self):
        return DeploymentLockService()

    async def test_is_locked_false_when_no_lock(self, service, db_session, test_user):
        """Test is_locked returns False when no lock exists."""
        serve = await ServeFactory.create(created_by=test_user)
        env = await EnvironmentFactory.create()

        result = await service.is_locked(
            serve_id=serve.id,
            environment_id=env.id,
        )

        assert result is False

    async def test_is_locked_true_when_lock_held(self, service, db_session, test_user):
        """Test is_locked returns True when lock is held."""
        serve = await ServeFactory.create(created_by=test_user)
        env = await EnvironmentFactory.create()
        await service.acquire_lock(serve_id=serve.id, environment_id=env.id)

        result = await service.is_locked(
            serve_id=serve.id,
            environment_id=env.id,
        )

        assert result is True


@pytest.mark.unit
@pytest.mark.asyncio
class TestDeploymentLockServiceConcurrent:
    """Test concurrent lock attempts (race condition)."""

    @pytest.fixture
    def service(self):
        return DeploymentLockService()

    async def test_concurrent_lock_attempts_one_succeeds(
        self, service, db_session, test_user
    ):
        """Test concurrent lock attempts: one succeeds, other gets 409."""
        import asyncio

        serve = await ServeFactory.create(created_by=test_user)
        env = await EnvironmentFactory.create()

        results = []

        async def try_acquire():
            try:
                lock = await service.acquire_lock(
                    serve_id=serve.id,
                    environment_id=env.id,
                )
                results.append(("success", lock))
            except HTTPException as e:
                results.append(("error", e.status_code))

        # Run two acquisitions concurrently
        await asyncio.gather(try_acquire(), try_acquire())

        success_count = sum(1 for r in results if r[0] == "success")
        error_409_count = sum(1 for r in results if r[0] == "error" and r[1] == 409)

        assert success_count == 1
        assert error_409_count == 1
