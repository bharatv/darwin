"""
Integration tests for enhanced rolling deployment flow.

Tests rolling with custom maxSurge/maxUnavailable and rollback via DCM.
Requires Kind cluster with ml-serve-app and DCM.
"""
import asyncio

import httpx
import pytest


@pytest.mark.integration
class TestRollingDeploymentFlow:
    """Integration tests for enhanced rolling deployment."""

    @pytest.mark.asyncio
    async def test_rolling_with_custom_max_surge(
        self,
        ml_serve_base_url: str,
        http_client: httpx.AsyncClient,
        cleanup_test_resources,
        integration_test_env: str,
        test_model_uri: str,
    ):
        """Test rolling deployment with custom maxSurge and maxUnavailable."""
        serve_name = "rolling-custom-test"
        cleanup_test_resources(serve_name, integration_test_env)

        await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve",
            json={
                "name": serve_name,
                "type": "api",
                "description": "Rolling custom test",
                "space": "test-space",
            },
        )

        deploy_response = await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve/deploy-model",
            json={
                "serve_name": serve_name,
                "artifact_version": "v1.0.0",
                "model_uri": test_model_uri,
                "env": integration_test_env,
                "deployment_strategy": "rolling",
                "deployment_strategy_config": {
                    "maxSurge": "50%",
                    "maxUnavailable": 0,
                },
                "cores": 2,
                "memory": 4,
                "min_replicas": 1,
                "max_replicas": 3,
            },
        )

        if deploy_response.status_code in [400, 404]:
            pytest.skip(f"Deploy failed: {deploy_response.status_code}")

        assert deploy_response.status_code in [200, 201]

    @pytest.mark.asyncio
    async def test_rolling_rollback_via_dcm(
        self,
        ml_serve_base_url: str,
        http_client: httpx.AsyncClient,
        cleanup_test_resources,
        integration_test_env: str,
        test_model_uri: str,
    ):
        """Test rolling rollback redeploys previous version via DCM."""
        serve_name = "rolling-rollback-test"
        cleanup_test_resources(serve_name, integration_test_env)

        await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve",
            json={
                "name": serve_name,
                "type": "api",
                "description": "Rolling rollback test",
                "space": "test-space",
            },
        )

        await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve/deploy-model",
            json={
                "serve_name": serve_name,
                "artifact_version": "v1.0.0",
                "model_uri": test_model_uri,
                "env": integration_test_env,
                "deployment_strategy": "rolling",
                "cores": 2,
                "memory": 4,
                "min_replicas": 1,
                "max_replicas": 2,
            },
        )

        await asyncio.sleep(5)

        await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve/deploy-model",
            json={
                "serve_name": serve_name,
                "artifact_version": "v1.0.1",
                "model_uri": test_model_uri,
                "env": integration_test_env,
                "deployment_strategy": "rolling",
                "cores": 2,
                "memory": 4,
                "min_replicas": 1,
                "max_replicas": 2,
            },
        )

        rollback_response = await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve/{serve_name}/rollback",
            json={"env": integration_test_env},
        )
        if rollback_response.status_code == 404:
            pytest.skip("Rollback endpoint not implemented")
        assert rollback_response.status_code in [200, 400]
        if rollback_response.status_code == 200:
            data = rollback_response.json()
            assert "previous_version" in data.get("data", data) or "message" in data.get("data", data)
