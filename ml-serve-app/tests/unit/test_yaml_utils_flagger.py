"""
Unit tests for generate_flagger_values and generate_fastapi_values with deployment strategy.

Tests flagger values generation for canary, rolling, blue-green and merge into fastapi values.
"""
import os
import pytest
from unittest.mock import MagicMock

from ml_serve_core.utils.yaml_utils import (
    generate_flagger_values,
    generate_fastapi_values,
    generate_fastapi_values_for_one_click_model_deployment,
)
from ml_serve_core.dtos.dtos import EnvConfig


# Ensure local env for predictable ingress/config behavior
@pytest.fixture(autouse=True)
def set_local_env():
    os.environ["ENV"] = "local"
    yield
    # Restore if needed (conftest sets it)


def _make_infra_config():
    """Create minimal APIServeInfraConfig-like object for tests."""
    config = MagicMock()
    config.fast_api_config_object = MagicMock()
    config.fast_api_config_object.min_replicas = 1
    config.fast_api_config_object.max_replicas = 3
    config.fast_api_config_object.cores = 2
    config.fast_api_config_object.memory = 4
    config.fast_api_config_object.node_capacity_type = "spot"
    config.additional_hosts_list = None
    return config


def _make_env_config():
    """Create minimal EnvConfig for tests."""
    return EnvConfig(
        domain_suffix="",
        cluster_name="kind",
        security_group="",
        subnets="",
        ft_redis_url="",
        workflow_url="",
        namespace="darwin",
    )


@pytest.mark.unit
class TestGenerateFlaggerValues:
    """Test generate_flagger_values for all strategies."""

    def test_canary_returns_enabled_true_and_expected_fields(self):
        """generate_flagger_values('canary', {...}) returns enabled=true, type=canary, stepWeight, etc."""
        result = generate_flagger_values(
            "canary",
            {"stepWeight": 20, "maxWeight": 60},
        )
        assert result["enabled"] is True
        assert result["type"] == "canary"
        assert result["stepWeight"] == 20
        assert result["maxWeight"] == 60
        assert result["skipAnalysis"] is True
        assert "interval" in result
        assert "threshold" in result
        assert "metrics" in result
        assert len(result["metrics"]) > 0
        assert result["metrics"][0]["name"] == "request-success-rate"

    def test_canary_with_optional_interval_threshold(self):
        """Canary config with interval and threshold uses them."""
        result = generate_flagger_values(
            "canary",
            {
                "stepWeight": 10,
                "maxWeight": 80,
                "interval": "2m",
                "threshold": 3,
            },
        )
        assert result["enabled"] is True
        assert result["type"] == "canary"
        assert result["stepWeight"] == 10
        assert result["maxWeight"] == 80
        assert result["interval"] == "2m"
        assert result["threshold"] == 3

    def test_rolling_returns_enabled_false(self):
        """generate_flagger_values('rolling', None) returns enabled=false."""
        result = generate_flagger_values("rolling", None)
        assert result["enabled"] is False

    def test_none_strategy_returns_enabled_false(self):
        """generate_flagger_values(None, None) returns enabled=false."""
        result = generate_flagger_values(None, None)
        assert result["enabled"] is False

    def test_blue_green_returns_enabled_true_and_expected_fields(self):
        """generate_flagger_values('blue-green', {...}) returns enabled=true, type=immute, iterations, etc."""
        result = generate_flagger_values(
            "blue-green",
            {"iterations": 2, "interval": "1m", "threshold": 2},
        )
        assert result["enabled"] is True
        assert result["type"] == "immute"
        assert result["iterations"] == 2
        assert result["interval"] == "1m"
        assert result["threshold"] == 2
        assert result["skipAnalysis"] is True
        assert "metrics" in result

    def test_canary_defaults_step_weight_max_weight(self):
        """Canary with empty config uses sensible defaults."""
        result = generate_flagger_values("canary", {})
        assert result["enabled"] is True
        assert result["type"] == "canary"
        assert "stepWeight" in result
        assert "maxWeight" in result
        assert "interval" in result
        assert "threshold" in result


@pytest.mark.unit
class TestGenerateFastapiValuesWithStrategy:
    """Test generate_fastapi_values merges flagger block when strategy provided."""

    def test_with_canary_includes_merged_flagger_block(self):
        """generate_fastapi_values(..., deployment_strategy='canary', ...) includes merged flagger block."""
        values = generate_fastapi_values(
            name="test-serve",
            env="prod",
            runtime="localhost:5000/img:tag",
            env_config=_make_env_config(),
            user_email="user@test.com",
            serve_infra_config=_make_infra_config(),
            environment_variables=None,
            is_environment_protected=False,
            deployment_strategy="canary",
            deployment_strategy_config={"stepWeight": 20, "maxWeight": 60},
        )
        assert "flagger" in values
        assert values["flagger"]["enabled"] is True
        assert values["flagger"]["type"] == "canary"
        assert values["flagger"]["stepWeight"] == 20
        assert values["flagger"]["maxWeight"] == 60

    def test_without_strategy_preserves_template_flagger(self):
        """generate_fastapi_values without strategy preserves template flagger (enabled: false)."""
        values = generate_fastapi_values(
            name="test-serve",
            env="prod",
            runtime="localhost:5000/img:tag",
            env_config=_make_env_config(),
            user_email="user@test.com",
            serve_infra_config=_make_infra_config(),
            environment_variables=None,
            is_environment_protected=False,
        )
        assert "flagger" in values
        assert values["flagger"]["enabled"] is False

    def test_with_rolling_sets_flagger_enabled_false(self):
        """generate_fastapi_values with deployment_strategy='rolling' sets flagger.enabled=false."""
        values = generate_fastapi_values(
            name="test-serve",
            env="prod",
            runtime="localhost:5000/img:tag",
            env_config=_make_env_config(),
            user_email="user@test.com",
            serve_infra_config=_make_infra_config(),
            environment_variables=None,
            is_environment_protected=False,
            deployment_strategy="rolling",
            deployment_strategy_config=None,
        )
        assert values["flagger"]["enabled"] is False


@pytest.mark.unit
class TestGenerateFastapiValuesForOneClickWithStrategy:
    """Test generate_fastapi_values_for_one_click_model_deployment merges flagger."""

    def test_with_canary_includes_merged_flagger_block(self):
        """One-click with deployment_strategy='canary' includes merged flagger block."""
        values = generate_fastapi_values_for_one_click_model_deployment(
            name="test-model",
            env="prod",
            runtime="localhost:5000/img:tag",
            env_config=_make_env_config(),
            user_email="user@test.com",
            environment_variables=None,
            cores=2,
            memory=4,
            min_replicas=1,
            max_replicas=3,
            node_capacity_type="spot",
            storage_strategy="emptydir",
            model_uri="models:/iris/1",
            model_downloader_image="downloader:latest",
            model_cache_pvc_name="",
            model_cache_path="/models",
            tracking_uri="http://mlflow",
            tracking_username="",
            tracking_password="",
            deployment_strategy="canary",
            deployment_strategy_config={"stepWeight": 20, "maxWeight": 60},
        )
        assert "flagger" in values
        assert values["flagger"]["enabled"] is True
        assert values["flagger"]["type"] == "canary"

    def test_without_strategy_preserves_template_flagger(self):
        """One-click without strategy preserves template flagger (enabled: false)."""
        values = generate_fastapi_values_for_one_click_model_deployment(
            name="test-model",
            env="prod",
            runtime="localhost:5000/img:tag",
            env_config=_make_env_config(),
            user_email="user@test.com",
            environment_variables=None,
            cores=2,
            memory=4,
            min_replicas=1,
            max_replicas=3,
            node_capacity_type="spot",
            storage_strategy="emptydir",
            model_uri="models:/iris/1",
            model_downloader_image="downloader:latest",
            model_cache_pvc_name="",
            model_cache_path="/models",
            tracking_uri="http://mlflow",
            tracking_username="",
            tracking_password="",
        )
        assert "flagger" in values
        assert values["flagger"]["enabled"] is False
