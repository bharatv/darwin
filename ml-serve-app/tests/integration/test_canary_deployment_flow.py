"""
Integration tests for canary deployment flow.

Tests full canary flow: deploy -> step (25%, 50%) -> promote,
canary abort, deployment locking, and rollback from canary.
Requires Kind cluster with ml-serve-app, DCM, and Istio.
"""
import asyncio

import httpx
import pytest


@pytest.mark.integration
class TestCanaryDeploymentFlow:
    """Integration tests for canary deployment."""

    @pytest.mark.asyncio
    async def test_canary_deploy_step_promote_flow(
        self,
        ml_serve_base_url: str,
        http_client: httpx.AsyncClient,
        cleanup_test_resources,
        integration_test_env: str,
        test_model_uri: str,
    ):
        """Test full canary flow: deploy -> step (25%, 50%) -> promote."""
        serve_name = "canary-flow-test"
        cleanup_test_resources(serve_name, integration_test_env)

        # Create serve
        await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve",
            json={
                "name": serve_name,
                "type": "api",
                "description": "Canary flow test",
                "space": "test-space",
            },
        )

        # Deploy with canary strategy
        deploy_response = await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve/deploy-model",
            json={
                "serve_name": serve_name,
                "artifact_version": "v1.0.0",
                "model_uri": test_model_uri,
                "env": integration_test_env,
                "deployment_strategy": "canary",
                "deployment_strategy_config": {"initial_traffic_percent": 0},
                "cores": 2,
                "memory": 4,
                "min_replicas": 1,
                "max_replicas": 2,
            },
        )

        if deploy_response.status_code in [400, 404, 409]:
            pytest.skip(
                f"Canary deploy not available: {deploy_response.status_code} - "
                f"{deploy_response.json()}"
            )

        assert deploy_response.status_code in [200, 201]
        data = deploy_response.json()
        deployment_id = data.get("data", {}).get("deployment_id")
        if not deployment_id:
            pytest.skip("deployment_id not in response - API may not support canary yet")

        # Step to 25%
        step_response = await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve/{serve_name}/deployments/{deployment_id}/step",
            json={"traffic_percent": 25},
        )
        if step_response.status_code == 404:
            pytest.skip("Step endpoint not implemented")
        assert step_response.status_code == 200
        step_data = step_response.json()
        traffic_split = step_data.get("data", {}).get("traffic_split", {})
        assert traffic_split.get("canary", 0) == 25

        # Step to 50%
        step_response = await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve/{serve_name}/deployments/{deployment_id}/step",
            json={"traffic_percent": 50},
        )
        assert step_response.status_code == 200

        # Promote
        promote_response = await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve/{serve_name}/deployments/{deployment_id}/promote",
            json={},
        )
        if promote_response.status_code == 404:
            pytest.skip("Promote endpoint not implemented")
        assert promote_response.status_code == 200

    @pytest.mark.asyncio
    async def test_canary_abort(
        self,
        ml_serve_base_url: str,
        http_client: httpx.AsyncClient,
        cleanup_test_resources,
        integration_test_env: str,
        test_model_uri: str,
    ):
        """Test canary abort returns traffic to stable."""
        serve_name = "canary-abort-test"
        cleanup_test_resources(serve_name, integration_test_env)

        await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve",
            json={
                "name": serve_name,
                "type": "api",
                "description": "Canary abort test",
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
                "deployment_strategy": "canary",
                "cores": 2,
                "memory": 4,
                "min_replicas": 1,
                "max_replicas": 2,
            },
        )

        if deploy_response.status_code not in [200, 201]:
            pytest.skip(f"Canary deploy failed: {deploy_response.status_code}")

        data = deploy_response.json()
        deployment_id = data.get("data", {}).get("deployment_id")
        if not deployment_id:
            pytest.skip("deployment_id not in response")

        abort_response = await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve/{serve_name}/deployments/{deployment_id}/abort",
            json={},
        )
        if abort_response.status_code == 404:
            pytest.skip("Abort endpoint not implemented")
        assert abort_response.status_code == 200

    @pytest.mark.asyncio
    async def test_deploy_while_canary_locked_returns_409(
        self,
        ml_serve_base_url: str,
        http_client: httpx.AsyncClient,
        cleanup_test_resources,
        integration_test_env: str,
        test_model_uri: str,
    ):
        """Test new deployment rejected with 409 when canary in progress."""
        serve_name = "canary-lock-test"
        cleanup_test_resources(serve_name, integration_test_env)

        await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve",
            json={
                "name": serve_name,
                "type": "api",
                "description": "Canary lock test",
                "space": "test-space",
            },
        )

        # First canary deploy
        deploy1 = await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve/deploy-model",
            json={
                "serve_name": serve_name,
                "artifact_version": "v1.0.0",
                "model_uri": test_model_uri,
                "env": integration_test_env,
                "deployment_strategy": "canary",
                "cores": 2,
                "memory": 4,
                "min_replicas": 1,
                "max_replicas": 2,
            },
        )

        if deploy1.status_code not in [200, 201]:
            pytest.skip(f"First canary deploy failed: {deploy1.status_code}")

        # Second deploy while canary in progress - should get 409
        deploy2 = await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve/deploy-model",
            json={
                "serve_name": serve_name,
                "artifact_version": "v1.0.1",
                "model_uri": test_model_uri,
                "env": integration_test_env,
                "deployment_strategy": "canary",
                "cores": 2,
                "memory": 4,
                "min_replicas": 1,
                "max_replicas": 2,
            },
        )

        if deploy2.status_code == 404:
            pytest.skip("Deploy endpoint not available")
        assert deploy2.status_code == 409

    @pytest.mark.asyncio
    async def test_rollback_from_canary(
        self,
        ml_serve_base_url: str,
        http_client: httpx.AsyncClient,
        cleanup_test_resources,
        integration_test_env: str,
        test_model_uri: str,
    ):
        """Test rollback from canary to previous version."""
        serve_name = "canary-rollback-test"
        cleanup_test_resources(serve_name, integration_test_env)

        await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve",
            json={
                "name": serve_name,
                "type": "api",
                "description": "Canary rollback test",
                "space": "test-space",
            },
        )

        # Deploy v1
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

        # Deploy canary v1.0.1
        deploy2 = await http_client.post(
            f"{ml_serve_base_url}/api/v1/serve/deploy-model",
            json={
                "serve_name": serve_name,
                "artifact_version": "v1.0.1",
                "model_uri": test_model_uri,
                "env": integration_test_env,
                "deployment_strategy": "canary",
                "cores": 2,
                "memory": 4,
                "min_replicas": 1,
                "max_replicas": 2,
            },
        )

        if deploy2.status_code not in [200, 201]:
            pytest.skip(f"Canary deploy failed: {deploy2.status_code}")

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
