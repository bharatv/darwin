from __future__ import annotations

from typing import Any, Optional

from loguru import logger

from ml_serve_core.constants.constants import FASTAPI_SERVE_RESOURCE_NAME, FASTAPI_SERVE_CHART_VERSION
from ml_serve_core.dtos.dtos import EnvConfig
from ml_serve_core.service.deployment_service import DeploymentService
from ml_serve_core.utils.yaml_utils import generate_fastapi_values
from ml_serve_model import Artifact, Environment, Serve, User, Deployment, AppLayerDeployment
from ml_serve_model.serve_configs import APIServeInfraConfig

from .base import DeploymentStrategy, StrategyInitiationResult, StrategyProgressResult


class BlueGreenStrategy(DeploymentStrategy):
    def __init__(self, deployment_service: Optional[DeploymentService] = None):
        self.deployment_service = deployment_service or DeploymentService()

    async def initiate(
        self,
        *,
        serve: Serve,
        artifact: Artifact,
        env: Environment,
        user: User,
        api_infra_config: APIServeInfraConfig,
        strategy_config: Optional[dict[str, Any]],
        environment_variables: Optional[dict[str, str]],
        previous_deployment: Optional[Deployment],
        previous_app_layer_deployment: Optional[AppLayerDeployment],
    ) -> StrategyInitiationResult:
        # If there is no previous deployment, blue-green behaves like a normal deploy.
        if previous_deployment is None:
            await self.deployment_service.deploy_fastapi_serve(
                serve=serve,
                artifact=artifact,
                env=env,
                api_deployment_config=None,
                infra_config=api_infra_config,
                user=user,
            )
            return StrategyInitiationResult(phase=None, requires_approval=False, metadata={"promoted": True})

        prev_artifact = await previous_deployment.artifact
        primary_artifact_id = f"{env.name}-{serve.name}-{prev_artifact.version}"
        primary_resource_id = f"{env.name}-{serve.name}"

        values = generate_fastapi_values(
            name=serve.name,
            env=env.name,
            runtime=artifact.image_url,
            env_config=EnvConfig(**env.env_configs),
            user_email=user.username,
            serve_infra_config=api_infra_config,
            environment_variables=environment_variables,
            is_environment_protected=env.is_protected,
            deployment_role="green",
            deployment_version=artifact.version,
            deployment_strategy="blue-green",
            service_enabled=False,
            ingress_enabled=False,
        )

        green_resource_id = f"{env.name}-{serve.name}-green"
        green_artifact_id = f"{env.name}-{serve.name}-green-{artifact.version}"

        await self.deployment_service._build_and_start_fastapi_release(
            darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
            version=FASTAPI_SERVE_CHART_VERSION,
            values=values,
            resource_id=green_resource_id,
            artifact_id=green_artifact_id,
            kube_cluster=env.cluster_name,
            namespace=env.namespace,
        )

        # Ensure primary service routes ONLY to blue(primary) pods initially
        blue_selector = {"serve.darwin.io/name": serve.name, "deploy.darwin.io/role": "primary"}
        tm = self.deployment_service.get_traffic_manager()
        await tm.set_service_selector_for_release(
            env=env,
            resource_id=primary_resource_id,
            artifact_id=primary_artifact_id,
            darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
            selector=blue_selector,
        )

        return StrategyInitiationResult(
            phase="blue-green-awaiting-approval",
            requires_approval=True,
            metadata={
                "green_resource_id": green_resource_id,
                "green_artifact_id": green_artifact_id,
                "primary_resource_id": primary_resource_id,
                "primary_artifact_id": primary_artifact_id,
                "blue_selector": blue_selector,
            },
        )

    async def progress_phase(
        self,
        *,
        deployment: Deployment,
        app_layer_deployment: AppLayerDeployment,
        user: User,
        notes: Optional[str],
    ) -> StrategyProgressResult:
        meta = (app_layer_deployment.phase_metadata or {}) if isinstance(app_layer_deployment.phase_metadata, dict) else {}

        serve = await deployment.serve
        env = await deployment.environment
        artifact = await deployment.artifact

        api_infra_config = await APIServeInfraConfig.get_or_none(serve=serve, environment=env)
        if not api_infra_config:
            raise Exception("APIServeInfraConfig not found for serve/environment")

        env_vars = app_layer_deployment.environment_variables or None
        primary_resource_id = meta.get("primary_resource_id") or f"{env.name}-{serve.name}"
        primary_artifact_id = meta.get("primary_artifact_id")

        # 1) Instant switchover: point primary Service selector to GREEN pods
        green_selector = {"serve.darwin.io/name": serve.name, "deploy.darwin.io/role": "green"}
        if primary_artifact_id:
            tm = self.deployment_service.get_traffic_manager()
            await tm.set_service_selector_for_release(
                env=env,
                resource_id=primary_resource_id,
                artifact_id=primary_artifact_id,
                darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
                selector=green_selector,
            )

            # Terminate old version immediately after traffic shifts
            await self.deployment_service.dcm_client.update_resource(
                values={"replicaCount": 0, "hpa": {"maxReplicas": 0}},
                artifact_id=primary_artifact_id,
                darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
            )
            await self.deployment_service.dcm_client.start_resource(
                resource_id=primary_resource_id,
                artifact_id=primary_artifact_id,
                kube_cluster=env.cluster_name,
                namespace=env.namespace,
                darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
            )

        # 2) Converge back to a single primary release on the new version
        promoted_values = generate_fastapi_values(
            name=serve.name,
            env=env.name,
            runtime=artifact.image_url,
            env_config=EnvConfig(**env.env_configs),
            user_email=user.username,
            serve_infra_config=api_infra_config,
            environment_variables=env_vars,
            is_environment_protected=env.is_protected,
            deployment_role="primary",
            deployment_version=artifact.version,
            deployment_strategy="blue-green",
            service_enabled=True,
            ingress_enabled=True,
            # keep Service routing to green while primary is upgraded
            service_selector=green_selector,
        )

        new_primary_artifact_id = f"{env.name}-{serve.name}-{artifact.version}"

        await self.deployment_service._build_and_start_fastapi_release(
            darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
            version=FASTAPI_SERVE_CHART_VERSION,
            values=promoted_values,
            resource_id=primary_resource_id,
            artifact_id=new_primary_artifact_id,
            kube_cluster=env.cluster_name,
            namespace=env.namespace,
        )

        # 3) Now route Service back to primary pods and stop green
        tm = self.deployment_service.get_traffic_manager()
        await tm.set_service_selector_for_release(
            env=env,
            resource_id=primary_resource_id,
            artifact_id=new_primary_artifact_id,
            darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
            selector={"serve.darwin.io/name": serve.name, "deploy.darwin.io/role": "primary"},
        )

        green_resource_id = meta.get("green_resource_id")
        if green_resource_id:
            try:
                await self.deployment_service.dcm_client.stop_resource(
                    resource_id=green_resource_id,
                    kube_cluster=env.cluster_name,
                    namespace=env.namespace,
                )
            except Exception as e:
                logger.warning(f"Failed to stop green resource {green_resource_id}: {e}")

        meta.update({"promoted": True, "primary_artifact_id": new_primary_artifact_id, "green_selector": green_selector})
        return StrategyProgressResult(phase=None, requires_approval=False, metadata=meta)

    async def rollback(
        self,
        *,
        deployment: Deployment,
        app_layer_deployment: AppLayerDeployment,
        user: User,
        reason: Optional[str],
    ) -> None:
        meta = (app_layer_deployment.phase_metadata or {}) if isinstance(app_layer_deployment.phase_metadata, dict) else {}
        env = await deployment.environment
        serve = await deployment.serve

        green_resource_id = meta.get("green_resource_id")
        primary_resource_id = meta.get("primary_resource_id")
        primary_artifact_id = meta.get("primary_artifact_id")
        blue_selector = meta.get("blue_selector") or {"serve.darwin.io/name": serve.name, "deploy.darwin.io/role": "primary"}

        # Best-effort: restore service routing back to blue(primary) pods
        if primary_artifact_id and primary_resource_id:
            try:
                tm = self.deployment_service.get_traffic_manager()
                await tm.set_service_selector_for_release(
                    env=env,
                    resource_id=primary_resource_id,
                    artifact_id=primary_artifact_id,
                    darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
                    selector=blue_selector,
                )
            except Exception as e:
                logger.warning(f"Failed to restore blue service selector: {e}")

        # Stop green deployment
        if green_resource_id:
            try:
                await self.deployment_service.dcm_client.stop_resource(
                    resource_id=green_resource_id,
                    kube_cluster=env.cluster_name,
                    namespace=env.namespace,
                )
            except Exception as e:
                logger.warning(f"Failed to stop green resource {green_resource_id}: {e}")

