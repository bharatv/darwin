"""
Unit tests for DeploymentStrategy enum and AppLayerDeployment validation.

Tests enum values and model validation for deployment_strategy field.
"""
import pytest
from tortoise.exceptions import ValidationError

from ml_serve_model import Deployment
from ml_serve_model.enums import DeploymentStrategy
from ml_serve_model.app_layer_deployments import AppLayerDeployment


@pytest.mark.unit
class TestDeploymentStrategyEnum:
    """Test DeploymentStrategy enum values."""

    def test_rolling_value(self):
        """DeploymentStrategy.ROLLING.value must be 'rolling'."""
        assert DeploymentStrategy.ROLLING.value == "rolling"

    def test_canary_value(self):
        """DeploymentStrategy.CANARY.value must be 'canary'."""
        assert DeploymentStrategy.CANARY.value == "canary"

    def test_blue_green_value(self):
        """DeploymentStrategy.BLUE_GREEN.value must be 'blue-green'."""
        assert DeploymentStrategy.BLUE_GREEN.value == "blue-green"

    def test_all_values_are_strings(self):
        """All enum values must be non-empty strings."""
        for member in DeploymentStrategy:
            assert isinstance(member.value, str)
            assert len(member.value) > 0


@pytest.mark.unit
class TestAppLayerDeploymentStrategyValidation:
    """Test AppLayerDeployment accepts valid strategy and rejects invalid."""

    @pytest.mark.asyncio
    async def test_accepts_rolling(
        self, db_session, test_user, test_serve, test_artifact, test_environment
    ):
        """Model accepts and persists deployment_strategy='rolling'."""
        deployment = await Deployment.create(
            serve=test_serve,
            artifact=test_artifact,
            environment=test_environment,
            created_by=test_user,
        )
        app_deployment = await AppLayerDeployment.create(
            deployment=deployment,
            deployment_strategy="rolling",
            deployment_params=None,
            environment_variables={},
        )
        assert app_deployment.deployment_strategy == "rolling"

    @pytest.mark.asyncio
    async def test_accepts_canary(
        self, db_session, test_user, test_serve, test_artifact, test_environment
    ):
        """Model accepts and persists deployment_strategy='canary'."""
        deployment = await Deployment.create(
            serve=test_serve,
            artifact=test_artifact,
            environment=test_environment,
            created_by=test_user,
        )
        app_deployment = await AppLayerDeployment.create(
            deployment=deployment,
            deployment_strategy="canary",
            deployment_params={"stepWeight": 20},
            environment_variables={},
        )
        assert app_deployment.deployment_strategy == "canary"

    @pytest.mark.asyncio
    async def test_accepts_blue_green(
        self, db_session, test_user, test_serve, test_artifact, test_environment
    ):
        """Model accepts and persists deployment_strategy='blue-green'."""
        deployment = await Deployment.create(
            serve=test_serve,
            artifact=test_artifact,
            environment=test_environment,
            created_by=test_user,
        )
        app_deployment = await AppLayerDeployment.create(
            deployment=deployment,
            deployment_strategy="blue-green",
            deployment_params=None,
            environment_variables={},
        )
        assert app_deployment.deployment_strategy == "blue-green"

    @pytest.mark.asyncio
    async def test_accepts_none(
        self, db_session, test_user, test_serve, test_artifact, test_environment
    ):
        """Model accepts deployment_strategy=None (nullable field)."""
        deployment = await Deployment.create(
            serve=test_serve,
            artifact=test_artifact,
            environment=test_environment,
            created_by=test_user,
        )
        app_deployment = await AppLayerDeployment.create(
            deployment=deployment,
            deployment_strategy=None,
            deployment_params=None,
            environment_variables={},
        )
        assert app_deployment.deployment_strategy is None

    @pytest.mark.asyncio
    async def test_rejects_invalid_strategy(
        self, db_session, test_user, test_serve, test_artifact, test_environment
    ):
        """Model rejects invalid deployment_strategy value."""
        deployment = await Deployment.create(
            serve=test_serve,
            artifact=test_artifact,
            environment=test_environment,
            created_by=test_user,
        )
        with pytest.raises(ValidationError) as exc_info:
            await AppLayerDeployment.create(
                deployment=deployment,
                deployment_strategy="invalid-strategy",
                deployment_params=None,
                environment_variables={},
            )
        assert "deployment_strategy" in str(exc_info.value).lower() or "invalid" in str(
            exc_info.value
        ).lower()
