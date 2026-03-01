from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from tortoise.transactions import in_transaction

from ml_serve_app_layer.dtos.requests import APIServeDeploymentConfigRequest
from ml_serve_core.service.deployment_service import DeploymentService
from ml_serve_model import (
    Serve,
    Artifact,
    Environment,
    User,
    Deployment,
    ActiveDeployment,
    AppLayerDeployment,
    DeploymentPhase,
    APIServeInfraConfig,
)
from ml_serve_model.enums import DeploymentStatus, DeploymentStrategy

from ml_serve_core.strategies.canary import CanaryStrategy
from ml_serve_core.strategies.blue_green import BlueGreenStrategy
from ml_serve_core.strategies.rolling import RollingStrategy


class DeploymentOrchestrator:
    def __init__(self, deployment_service: Optional[DeploymentService] = None):
        self.deployment_service = deployment_service or DeploymentService()

    def _strategy_impl(self, strategy: DeploymentStrategy):
        if strategy == DeploymentStrategy.CANARY:
            return CanaryStrategy(self.deployment_service)
        if strategy == DeploymentStrategy.BLUE_GREEN:
            return BlueGreenStrategy(self.deployment_service)
        if strategy == DeploymentStrategy.ROLLING:
            return RollingStrategy(self.deployment_service)
        raise HTTPException(status_code=400, detail=f"Unsupported deployment strategy '{strategy}'")

    async def _ensure_no_concurrent(self, serve: Serve, env: Environment):
        in_progress = await AppLayerDeployment.filter(
            deployment__serve=serve,
            deployment__environment=env,
            requires_approval=True,
        ).exists()
        active = await ActiveDeployment.get_or_none(serve=serve, environment=env)
        has_candidate = bool(active and getattr(active, "candidate_deployment_id", None))
        if in_progress:
            raise HTTPException(status_code=409, detail="Deployment already in progress; approve/reject it first.")
        if has_candidate:
            raise HTTPException(status_code=409, detail="Deployment already in progress; approve/reject it first.")

    async def initiate_deployment(
        self,
        *,
        serve: Serve,
        artifact: Artifact,
        env: Environment,
        api_infra_config: APIServeInfraConfig,
        api_deployment_config: APIServeDeploymentConfigRequest,
        user: User,
    ) -> dict:
        if not api_deployment_config or not api_deployment_config.deployment_strategy:
            raise HTTPException(status_code=400, detail="deployment_strategy is required for orchestrated deployment")

        await self._ensure_no_concurrent(serve, env)

        active = await ActiveDeployment.get_or_none(serve=serve, environment=env)
        previous_deployment = await active.deployment if active else None
        previous_app = await AppLayerDeployment.get_or_none(deployment=previous_deployment) if previous_deployment else None

        strategy = api_deployment_config.deployment_strategy
        strategy_impl = self._strategy_impl(strategy)

        async with in_transaction():
            deployment = await Deployment.create(
                serve=serve,
                artifact=artifact,
                environment=env,
                created_by=user,
            )

            app_layer = await AppLayerDeployment.create(
                deployment=deployment,
                deployment_strategy=strategy.value,
                deployment_params=api_deployment_config.deployment_strategy_config,
                environment_variables=api_deployment_config.environment_variables,
                phase="initiating",
                phase_metadata={},
                requires_approval=True,
            )

        # Track candidate in ActiveDeployment if there is already a live deployment.
        if active:
            await self.deployment_service.set_candidate_deployment(serve=serve, env=env, deployment=deployment)

        result = await strategy_impl.initiate(
            serve=serve,
            artifact=artifact,
            env=env,
            user=user,
            api_infra_config=api_infra_config,
            strategy_config=api_deployment_config.deployment_strategy_config,
            environment_variables=api_deployment_config.environment_variables,
            previous_deployment=previous_deployment,
            previous_app_layer_deployment=previous_app,
        )

        app_layer.phase = result.phase
        app_layer.phase_metadata = result.metadata
        app_layer.requires_approval = result.requires_approval
        if not result.requires_approval and app_layer.phase is None:
            app_layer.phase = "completed"
        await app_layer.save()

        if not result.requires_approval:
            await self._finalize_deployment(serve=serve, env=env, deployment=deployment)

        return {
            "deployment_id": deployment.id,
            "strategy": strategy.value,
            "phase": result.phase,
            "requires_approval": bool(result.requires_approval),
        }

    async def approve_phase(self, *, deployment_id: int, user: User, notes: Optional[str] = None) -> dict:
        deployment = await Deployment.get_or_none(id=deployment_id)
        if not deployment:
            raise HTTPException(status_code=404, detail="Deployment not found")

        if deployment.status == DeploymentStatus.ENDED.value:
            raise HTTPException(status_code=409, detail="Deployment already ended")

        app_layer = await AppLayerDeployment.get_or_none(deployment=deployment)
        if not app_layer:
            raise HTTPException(status_code=404, detail="AppLayerDeployment not found")

        if (app_layer.phase or "").lower() in ("rejected", "failed", "completed"):
            raise HTTPException(status_code=409, detail=f"Deployment is in terminal phase '{app_layer.phase}'")

        if not app_layer.requires_approval:
            raise HTTPException(status_code=400, detail="Deployment does not require approval at this time")

        strategy = DeploymentStrategy(app_layer.deployment_strategy) if app_layer.deployment_strategy else None
        if not strategy:
            raise HTTPException(status_code=400, detail="Deployment strategy not set")

        strategy_impl = self._strategy_impl(strategy)
        try:
            progress = await strategy_impl.progress_phase(
                deployment=deployment,
                app_layer_deployment=app_layer,
                user=user,
                notes=notes,
            )
        except HTTPException:
            raise
        except Exception as e:
            await self._handle_failure(deployment=deployment, app_layer_deployment=app_layer, error=str(e))
            raise HTTPException(status_code=500, detail="Deployment phase progression failed")

        prev_phase = app_layer.phase
        app_layer.phase = progress.phase
        app_layer.phase_metadata = progress.metadata
        app_layer.requires_approval = progress.requires_approval
        if not progress.requires_approval and app_layer.phase is None:
            app_layer.phase = "completed"
        await app_layer.save()

        await DeploymentPhase.create(
            deployment=deployment,
            phase_name=prev_phase or "unknown",
            traffic_weights=None,
            approver_username=user.username,
            approved_at=datetime.now(timezone.utc),
            notes=notes,
        )

        if not progress.requires_approval:
            serve = await deployment.serve
            env = await deployment.environment
            await self._finalize_deployment(serve=serve, env=env, deployment=deployment)

        return {
            "deployment_id": deployment.id,
            "phase": app_layer.phase,
            "requires_approval": bool(app_layer.requires_approval),
        }

    async def reject_phase(
        self,
        *,
        deployment_id: int,
        user: User,
        rejection_reason: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> dict:
        deployment = await Deployment.get_or_none(id=deployment_id)
        if not deployment:
            raise HTTPException(status_code=404, detail="Deployment not found")

        if deployment.status == DeploymentStatus.ENDED.value:
            raise HTTPException(status_code=409, detail="Deployment already ended")

        app_layer = await AppLayerDeployment.get_or_none(deployment=deployment)
        if not app_layer:
            raise HTTPException(status_code=404, detail="AppLayerDeployment not found")

        strategy = DeploymentStrategy(app_layer.deployment_strategy) if app_layer.deployment_strategy else None
        if not strategy:
            raise HTTPException(status_code=400, detail="Deployment strategy not set")

        strategy_impl = self._strategy_impl(strategy)
        await strategy_impl.rollback(
            deployment=deployment,
            app_layer_deployment=app_layer,
            user=user,
            reason=rejection_reason,
        )

        app_layer.requires_approval = False
        app_layer.phase = "rejected"
        await app_layer.save()

        deployment.status = DeploymentStatus.ENDED.value
        deployment.ended_at = datetime.now(timezone.utc)
        await deployment.save()

        await DeploymentPhase.create(
            deployment=deployment,
            phase_name="rejected",
            traffic_weights=None,
            approver_username=user.username,
            approved_at=datetime.now(timezone.utc),
            rejection_reason=rejection_reason,
            notes=notes,
        )

        serve = await deployment.serve
        env = await deployment.environment
        await self.deployment_service.clear_candidate_deployment(serve=serve, env=env)

        return {"deployment_id": deployment.id, "status": "REJECTED"}

    async def _finalize_deployment(self, *, serve: Serve, env: Environment, deployment: Deployment) -> None:
        await self.deployment_service.clear_candidate_deployment(serve=serve, env=env)
        await self.deployment_service._update_active_deployment(serve, env, deployment, end_previous=True)

    async def _handle_failure(self, *, deployment: Deployment, app_layer_deployment: AppLayerDeployment, error: str) -> None:
        try:
            app_layer_deployment.phase = "failed"
            app_layer_deployment.requires_approval = False
            meta = app_layer_deployment.phase_metadata or {}
            if isinstance(meta, dict):
                meta["error"] = error
                app_layer_deployment.phase_metadata = meta
            await app_layer_deployment.save()
        except Exception:
            # best-effort only
            return

    async def rollback_deployment(
        self, *, deployment_id: int, user: User, reason: Optional[str] = None, notes: Optional[str] = None
    ) -> dict:
        # Alias to reject behavior for now
        return await self.reject_phase(
            deployment_id=deployment_id,
            user=user,
            rejection_reason=reason,
            notes=notes,
        )

    async def status(self, *, deployment_id: int) -> dict:
        deployment = await Deployment.get_or_none(id=deployment_id)
        if not deployment:
            raise HTTPException(status_code=404, detail="Deployment not found")

        app_layer = await AppLayerDeployment.get_or_none(deployment=deployment)
        phases = await DeploymentPhase.filter(deployment=deployment).order_by("created_at").all()

        return {
            "deployment_id": deployment.id,
            "strategy": getattr(app_layer, "deployment_strategy", None),
            "phase": getattr(app_layer, "phase", None),
            "requires_approval": bool(getattr(app_layer, "requires_approval", False)),
            "traffic_weights": None,
            "phase_history": [
                {
                    "phase_name": p.phase_name,
                    "approver_username": p.approver_username,
                    "approved_at": p.approved_at,
                    "rejection_reason": p.rejection_reason,
                    "notes": p.notes,
                    "created_at": p.created_at,
                }
                for p in phases
            ],
        }

