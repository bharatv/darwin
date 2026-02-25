"""Deployment lock service for canary deployment locking."""
from datetime import datetime, timezone

from fastapi import HTTPException
from tortoise.exceptions import IntegrityError

from ml_serve_model import DeploymentLock
from loguru import logger


class DeploymentLockService:
    """Manages deployment locks to prevent concurrent canary deployments."""

    async def acquire_lock(
        self, serve_id: int, environment_id: int
    ) -> DeploymentLock:
        """
        Acquire deployment lock. Must be called before canary deploy.
        Raises HTTPException 409 if already locked.
        """
        try:
            lock = await DeploymentLock.create(
                serve_id=serve_id,
                environment_id=environment_id,
                deployment_id=None,
                locked_at=datetime.now(timezone.utc),
            )
            logger.info(
                f"Deployment lock acquired for serve_id={serve_id} env_id={environment_id}"
            )
            return lock
        except IntegrityError:
            logger.warning(
                f"Lock acquisition failed: already locked for serve_id={serve_id} env_id={environment_id}"
            )
            raise HTTPException(
                status_code=409,
                detail="Deployment locked. Cannot deploy while canary is in progress.",
            )

    async def release_lock(self, serve_id: int, environment_id: int) -> None:
        """Release deployment lock. Idempotent if no lock exists."""
        deleted = await DeploymentLock.filter(
            serve_id=serve_id, environment_id=environment_id
        ).delete()
        if deleted:
            logger.info(
                f"Deployment lock released for serve_id={serve_id} env_id={environment_id}"
            )

    async def is_locked(self, serve_id: int, environment_id: int) -> bool:
        """Check if deployment is locked for this serve/environment."""
        return await DeploymentLock.filter(
            serve_id=serve_id, environment_id=environment_id
        ).exists()

    async def update_lock_deployment_id(
        self, serve_id: int, environment_id: int, deployment_id: int
    ) -> None:
        """Update lock with deployment ID after deployment is created."""
        await DeploymentLock.filter(
            serve_id=serve_id, environment_id=environment_id
        ).update(deployment_id=deployment_id)
        logger.debug(
            f"Lock updated with deployment_id={deployment_id} for serve_id={serve_id}"
        )
