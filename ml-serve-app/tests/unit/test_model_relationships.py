import pytest

from ml_serve_model import Deployment, ActiveDeployment, AppLayerDeployment, DeploymentPhase
from ml_serve_model.enums import DeploymentStatus


@pytest.mark.unit
class TestModelRelationships:
    @pytest.mark.asyncio
    async def test_active_deployment_candidate_relationship(
        self,
        db_session,
        test_user,
        test_serve,
        test_environment,
        test_artifact,
    ):
        live = await Deployment.create(
            serve=test_serve,
            artifact=test_artifact,
            environment=test_environment,
            created_by=test_user,
        )
        candidate = await Deployment.create(
            serve=test_serve,
            artifact=test_artifact,
            environment=test_environment,
            created_by=test_user,
        )

        ad = await ActiveDeployment.create(
            serve=test_serve,
            environment=test_environment,
            deployment=live,
            previous_deployment=None,
            candidate_deployment=candidate,
        )

        loaded = await ActiveDeployment.get(id=ad.id)
        assert (await loaded.deployment).id == live.id
        assert (await loaded.candidate_deployment).id == candidate.id

    @pytest.mark.asyncio
    async def test_app_layer_deployment_one_to_one(self, db_session, test_user, test_serve, test_environment, test_artifact):
        d = await Deployment.create(
            serve=test_serve,
            artifact=test_artifact,
            environment=test_environment,
            created_by=test_user,
        )
        ald = await AppLayerDeployment.create(
            deployment=d,
            deployment_strategy="canary",
            deployment_params={"steps": [20, 100]},
            environment_variables={"X": "1"},
            phase="canary-awaiting-approval",
            phase_metadata={"step_index": -1},
            requires_approval=True,
        )
        fetched = await AppLayerDeployment.get(id=ald.id)
        assert fetched.deployment_id == d.id

    @pytest.mark.asyncio
    async def test_deployment_phase_fk_and_ordering(self, db_session, test_user, test_serve, test_environment, test_artifact):
        d = await Deployment.create(
            serve=test_serve,
            artifact=test_artifact,
            environment=test_environment,
            created_by=test_user,
            status=DeploymentStatus.ACTIVE.value,
        )
        await DeploymentPhase.create(deployment=d, phase_name="p1", notes="a")
        await DeploymentPhase.create(deployment=d, phase_name="p2", notes="b")

        phases = await DeploymentPhase.filter(deployment=d).order_by("created_at").all()
        assert [p.phase_name for p in phases] == ["p1", "p2"]

