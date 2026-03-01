import pytest
from unittest.mock import AsyncMock
from typing import Optional

from ml_serve_core.service.deployment_orchestrator import DeploymentOrchestrator
from ml_serve_model import Deployment, AppLayerDeployment


class _StubStrategy:
    def __init__(self, progress_result=None, raise_exc: Optional[Exception] = None):
        self._progress_result = progress_result
        self._raise = raise_exc

    async def initiate(self, **kwargs):
        raise AssertionError("not used in this test")

    async def progress_phase(self, **kwargs):
        if self._raise:
            raise self._raise
        return self._progress_result

    async def rollback(self, **kwargs):
        return None


@pytest.mark.unit
class TestDeploymentOrchestrator:
    @pytest.mark.asyncio
    async def test_approve_finalizes_when_requires_approval_false(
        self,
        db_session,
        test_user,
        test_serve,
        test_environment,
        test_artifact,
        monkeypatch,
    ):
        deployment = await Deployment.create(
            serve=test_serve,
            artifact=test_artifact,
            environment=test_environment,
            created_by=test_user,
        )
        app_layer = await AppLayerDeployment.create(
            deployment=deployment,
            deployment_strategy="canary",
            phase="canary-20",
            phase_metadata={},
            requires_approval=True,
        )

        orchestrator = DeploymentOrchestrator()
        orchestrator.deployment_service._update_active_deployment = AsyncMock()

        class _Prog:
            def __init__(self):
                self.phase = None
                self.requires_approval = False
                self.metadata = {}

        monkeypatch.setattr(orchestrator, "_strategy_impl", lambda *_: _StubStrategy(progress_result=_Prog()))

        resp = await orchestrator.approve_phase(deployment_id=deployment.id, user=test_user, notes="ok")
        assert resp["requires_approval"] is False

        # Phase should be forced to completed when strategy returns None
        refreshed = await AppLayerDeployment.get(deployment=deployment)
        assert refreshed.phase == "completed"
        orchestrator.deployment_service._update_active_deployment.assert_awaited()

    @pytest.mark.asyncio
    async def test_approve_failure_marks_failed_phase(
        self,
        db_session,
        test_user,
        test_serve,
        test_environment,
        test_artifact,
        monkeypatch,
    ):
        deployment = await Deployment.create(
            serve=test_serve,
            artifact=test_artifact,
            environment=test_environment,
            created_by=test_user,
        )
        await AppLayerDeployment.create(
            deployment=deployment,
            deployment_strategy="canary",
            phase="canary-20",
            phase_metadata={},
            requires_approval=True,
        )

        orchestrator = DeploymentOrchestrator()
        monkeypatch.setattr(orchestrator, "_strategy_impl", lambda *_: _StubStrategy(raise_exc=RuntimeError("boom")))

        with pytest.raises(Exception):
            await orchestrator.approve_phase(deployment_id=deployment.id, user=test_user, notes="ok")

        refreshed = await AppLayerDeployment.get(deployment=deployment)
        assert refreshed.phase == "failed"
        assert refreshed.requires_approval is False

