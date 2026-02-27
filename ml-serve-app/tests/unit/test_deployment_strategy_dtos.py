"""
Unit tests for deployment strategy DTO validation.

Tests APIServeDeploymentConfigRequest strategy-specific config validation
and ModelDeploymentRequest optional strategy fields.
"""
import pytest
from pydantic import ValidationError

from ml_serve_app_layer.dtos.requests import (
    APIServeDeploymentConfigRequest,
    ModelDeploymentRequest,
)


@pytest.mark.unit
class TestAPIServeDeploymentConfigRequestStrategyValidation:
    """Test APIServeDeploymentConfigRequest strategy and config validation."""

    def test_valid_canary_config_passes(self):
        """Valid canary config (stepWeight=20, maxWeight=60) passes."""
        config = APIServeDeploymentConfigRequest(
            deployment_strategy="canary",
            deployment_strategy_config={
                "stepWeight": 20,
                "maxWeight": 60,
            },
        )
        assert config.deployment_strategy == "canary"
        assert config.deployment_strategy_config["stepWeight"] == 20
        assert config.deployment_strategy_config["maxWeight"] == 60

    def test_valid_canary_config_with_optional_fields_passes(self):
        """Valid canary config with interval and threshold passes."""
        config = APIServeDeploymentConfigRequest(
            deployment_strategy="canary",
            deployment_strategy_config={
                "stepWeight": 10,
                "maxWeight": 80,
                "interval": "1m",
                "threshold": 2,
            },
        )
        assert config.deployment_strategy == "canary"
        assert config.deployment_strategy_config["stepWeight"] == 10
        assert config.deployment_strategy_config["maxWeight"] == 80

    def test_invalid_canary_step_weight_over_100_raises_422(self):
        """Invalid config (stepWeight=150) raises ValidationError (422)."""
        with pytest.raises(ValidationError) as exc_info:
            APIServeDeploymentConfigRequest(
                deployment_strategy="canary",
                deployment_strategy_config={
                    "stepWeight": 150,
                    "maxWeight": 60,
                },
            )
        errors = exc_info.value.errors()
        assert any("stepWeight" in str(e) or "150" in str(e) for e in errors)

    def test_invalid_canary_max_weight_less_than_step_weight_raises_422(self):
        """Invalid config (maxWeight < stepWeight) raises ValidationError (422)."""
        with pytest.raises(ValidationError) as exc_info:
            APIServeDeploymentConfigRequest(
                deployment_strategy="canary",
                deployment_strategy_config={
                    "stepWeight": 50,
                    "maxWeight": 20,
                },
            )
        error_str = str(exc_info.value).lower()
        assert "stepweight" in error_str or "maxweight" in error_str

    def test_invalid_deployment_strategy_raises_422(self):
        """Invalid deployment_strategy value raises ValidationError (422)."""
        with pytest.raises(ValidationError):
            APIServeDeploymentConfigRequest(
                deployment_strategy="invalid-strategy",
                deployment_strategy_config={},
            )

    def test_valid_rolling_config_passes(self):
        """Valid rolling config with maxSurge, maxUnavailable passes."""
        config = APIServeDeploymentConfigRequest(
            deployment_strategy="rolling",
            deployment_strategy_config={
                "maxSurge": 1,
                "maxUnavailable": 0,
            },
        )
        assert config.deployment_strategy == "rolling"

    def test_valid_blue_green_config_passes(self):
        """Valid blue-green config with iterations, interval, threshold passes."""
        config = APIServeDeploymentConfigRequest(
            deployment_strategy="blue-green",
            deployment_strategy_config={
                "iterations": 2,
                "interval": "1m",
                "threshold": 2,
            },
        )
        assert config.deployment_strategy == "blue-green"

    def test_none_strategy_and_config_passes(self):
        """None strategy and config (backward compatibility) passes."""
        config = APIServeDeploymentConfigRequest(
            deployment_strategy=None,
            deployment_strategy_config=None,
        )
        assert config.deployment_strategy is None
        assert config.deployment_strategy_config is None


@pytest.mark.unit
class TestModelDeploymentRequestStrategyFields:
    """Test ModelDeploymentRequest accepts optional strategy fields."""

    def test_accepts_optional_deployment_strategy(self):
        """ModelDeploymentRequest accepts optional deployment_strategy."""
        request = ModelDeploymentRequest(
            serve_name="test-model",
            artifact_version="v1",
            model_uri="models:/iris/1",
            env="prod",
            deployment_strategy="canary",
        )
        assert request.deployment_strategy == "canary"

    def test_accepts_optional_deployment_strategy_config(self):
        """ModelDeploymentRequest accepts optional deployment_strategy_config."""
        request = ModelDeploymentRequest(
            serve_name="test-model",
            artifact_version="v1",
            model_uri="models:/iris/1",
            env="prod",
            deployment_strategy="canary",
            deployment_strategy_config={"stepWeight": 20, "maxWeight": 60},
        )
        assert request.deployment_strategy == "canary"
        assert request.deployment_strategy_config["stepWeight"] == 20
        assert request.deployment_strategy_config["maxWeight"] == 60

    def test_works_without_strategy_fields(self):
        """ModelDeploymentRequest works without strategy fields (backward compat)."""
        request = ModelDeploymentRequest(
            serve_name="test-model",
            artifact_version="v1",
            model_uri="models:/iris/1",
            env="prod",
        )
        assert request.deployment_strategy is None
        assert request.deployment_strategy_config is None
