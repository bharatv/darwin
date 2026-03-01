"""
Unit tests for deployment strategy DTO validation.
"""

import pytest
from pydantic import ValidationError

from ml_serve_app_layer.dtos.requests import APIServeDeploymentConfigRequest
from ml_serve_model.enums import DeploymentStrategy


@pytest.mark.unit
class TestDeploymentStrategyDTOs:
    def test_accepts_null_strategy(self):
        req = APIServeDeploymentConfigRequest(
            deployment_strategy=None,
            deployment_strategy_config=None,
            environment_variables={"FOO": "bar"},
        )
        assert req.deployment_strategy is None

    def test_normalizes_strategy_string(self):
        req = APIServeDeploymentConfigRequest(deployment_strategy="  CANARY  ")
        assert req.deployment_strategy == DeploymentStrategy.CANARY

    def test_rejects_unknown_strategy_string(self):
        with pytest.raises(ValidationError):
            APIServeDeploymentConfigRequest(deployment_strategy="unknown")

    def test_canary_steps_must_be_ascending_and_end_100(self):
        with pytest.raises(ValidationError):
            APIServeDeploymentConfigRequest(
                deployment_strategy="canary",
                deployment_strategy_config={"steps": [50, 25, 100]},
            )

        with pytest.raises(ValidationError):
            APIServeDeploymentConfigRequest(
                deployment_strategy="canary",
                deployment_strategy_config={"steps": [10, 50, 90]},
            )

    def test_canary_steps_valid(self):
        req = APIServeDeploymentConfigRequest(
            deployment_strategy="canary",
            deployment_strategy_config={"steps": [10, 25, 50, 100]},
        )
        assert req.deployment_strategy == DeploymentStrategy.CANARY

    def test_canary_steps_type_validation(self):
        with pytest.raises(ValidationError):
            APIServeDeploymentConfigRequest(
                deployment_strategy="canary",
                deployment_strategy_config={"steps": "not-a-list"},
            )
        with pytest.raises(ValidationError):
            APIServeDeploymentConfigRequest(
                deployment_strategy="canary",
                deployment_strategy_config={"steps": [10, "20", 100]},
            )

    def test_rolling_checkpoints_must_be_ascending_and_end_100(self):
        with pytest.raises(ValidationError):
            APIServeDeploymentConfigRequest(
                deployment_strategy="rolling",
                deployment_strategy_config={"checkpoints": [50, 25, 100]},
            )

        with pytest.raises(ValidationError):
            APIServeDeploymentConfigRequest(
                deployment_strategy="rolling",
                deployment_strategy_config={"checkpoints": [50]},
            )

    def test_rolling_checkpoints_valid(self):
        req = APIServeDeploymentConfigRequest(
            deployment_strategy="rolling",
            deployment_strategy_config={"checkpoints": [50, 100]},
        )
        assert req.deployment_strategy == DeploymentStrategy.ROLLING

    def test_rolling_checkpoints_type_validation(self):
        with pytest.raises(ValidationError):
            APIServeDeploymentConfigRequest(
                deployment_strategy="rolling",
                deployment_strategy_config={"checkpoints": "not-a-list"},
            )
        with pytest.raises(ValidationError):
            APIServeDeploymentConfigRequest(
                deployment_strategy="rolling",
                deployment_strategy_config={"checkpoints": [50, "100"]},
            )

    def test_blue_green_allows_extra_config(self):
        req = APIServeDeploymentConfigRequest(
            deployment_strategy="blue-green",
            deployment_strategy_config={"anything": "ok"},
        )
        assert req.deployment_strategy == DeploymentStrategy.BLUE_GREEN

    def test_blue_green_rejects_non_object_config(self):
        with pytest.raises(ValidationError):
            APIServeDeploymentConfigRequest(
                deployment_strategy="blue-green",
                deployment_strategy_config="not-an-object",
            )

