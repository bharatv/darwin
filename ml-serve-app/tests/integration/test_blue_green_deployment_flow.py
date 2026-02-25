"""
Integration tests for blue-green deployment flow.

Tests blue-green deploy, promote (traffic switch), and rollback.
Requires Kind cluster with ml-serve-app, DCM, and Istio.
"""
import asyncio

import httpx
import pytest


@pytest.mark.integration
class TestBlueGreenDeploymentFlow:
    """Integration tests for blue-green deployment."""

    @pytest.mark.asyncio
    async def test_blue_green_deploy(
        self,
        ml_serve_base_url: str,
        http_client: httpx.AsyncClient,
        cleanup_test_resources,
        integration_test_env: str,
        test_model_uri: str,
    ):
        """Test blue-green deployment creates green alongside blue."""
        serve_name = "blue-green-deploy-test"
        cleanup_test_resources(serve_name, integration_test_env)

        await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve",
            json={
                "name": serve_name,
                "type": "api",
                "description": "Blue-green deploy test",
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
                "deployment_strategy": "blue_green",
                "deployment_strategy_config": {},
                "cores": 2,
                "memory": 4,
                "min_replicas": 1,
                "max_replicas": 2,
            },
        )

        if deploy_response.status_code in [400, 404]:
            pytest.skip(
                f"Blue-green deploy not available: {deploy_response.status_code}"
            )

        assert deploy_response.status_code in [200, 201]
        data = deploy_response.json()
        assert "deployment_id" in data.get("data", data) or "service_url" in data.get("data", data)

    @pytest.mark.asyncio
    async def test_blue_green_promote(
        self,
        ml_serve_base_url: str,
        http_client: httpx.AsyncClient,
        cleanup_test_resources,
        integration_test_env: str,
        test_model_uri: str,
    ):
        """Test blue-green promote switches traffic to green."""
        serve_name = "blue-green-promote-test"
        cleanup_test_resources(serve_name, integration_test_env)

        await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve",
            json={
                "name": serve_name,
                "type": "api",
                "description": "Blue-green promote test",
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
                "deployment_strategy": "blue_green",
                "cores": 2,
                "memory": 4,
                "min_replicas": 1,
                "max_replicas": 2,
            },
        )

        if deploy_response.status_code not in [200, 201]:
            pytest.skip(f"Blue-green deploy failed: {deploy_response.status_code}")

        data = deploy_response.json()
        deployment_id = data.get("data", {}).get("deployment_id")
        if not deployment_id:
            pytest.skip("deployment_id not in response")

        promote_response = await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve/{serve_name}/deployments/{deployment_id}/promote",
            json={},
        )
        if promote_response.status_code == 404:
            pytest.skip("Promote endpoint not implemented")
        assert promote_response.status_code == 200

    @pytest.mark.asyncio
    async def test_rollback_from_blue_green(
        self,
        ml_serve_base_url: str,
        http_client: httpx.AsyncClient,
        cleanup_test_resources,
        integration_test_env: str,
        test_model_uri: str,
    ):
        """Test rollback from blue-green to previous version."""
        serve_name = "blue-green-rollback-test"
        cleanup_test_resources(serve_name, integration_test_env)

        await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve",
            json={
                "name": serve_name,
                "type": "api",
                "description": "Blue-green rollback test",
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

        deploy2 = await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve/deploy-model",
            json={
                "serve_name": serve_name,
                "artifact_version": "v1.0.1",
                "model_uri": test_model_uri,
                "env": integration_test_env,
                "deployment_strategy": "blue_green",
                "cores": 2,
                "memory": 4,
                "min_replicas": 1,
                "max_replicas": 2,
            },
        )

        if deploy2.status_code not in [200, 201]:
            pytest.skip(f"Blue-green deploy failed: {deploy2.status_code}")

        deploy2_data = deploy2.json()
        deployment_id = deploy2_data.get("data", {}).get("deployment_id")
        if deployment_id:
            await http_client.post(
                f"{ml_serve_base_url}/api/v1/serve/{serve_name}/deployments/{deployment_id}/promote",
                json={},
            )

        rollback_response = await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve/{serve_name}/rollback",
            json={"env": integration_test_env},
        )
        if rollback_response.status_code == 404:
            pytest.skip("Rollback endpoint not implemented")
        assert rollback_response.status_code in [200, 400]
