"""Deployment strategy service for rolling, blue-green, and canary deployments."""
from typing import Dict, Any, Optional, TYPE_CHECKING

from fastapi import HTTPException

if TYPE_CHECKING:
    from ml_serve_model import Artifact, Deployment
    from ml_serve_model.app_layer_deployments import AppLayerDeployment

from ml_serve_core.client.dcm_client import DCMClient
from ml_serve_core.constants.constants import (
    FASTAPI_SERVE_RESOURCE_NAME,
    FASTAPI_SERVE_CHART_VERSION,
    ENABLE_ISTIO,
)
from ml_serve_core.dtos.dtos import EnvConfig
from ml_serve_core.service.deployment_lock_service import DeploymentLockService
from ml_serve_core.service.traffic_management_service import TrafficManagementService
from ml_serve_core.service.serve_config_service import ServeConfigService
from ml_serve_core.utils.yaml_utils import generate_fastapi_values
from ml_serve_model import Serve, Artifact, Environment, User, APIServeInfraConfig
from ml_serve_model.active_deployment import ActiveDeployment
from loguru import logger


class DeploymentStrategyService:
    """Orchestrates deployment execution per strategy."""

    def __init__(self):
        self.dcm_client = DCMClient()
        self.traffic_service = TrafficManagementService()
        self.lock_service = DeploymentLockService()
        self.serve_config_service = ServeConfigService()

    async def deploy_rolling(
        self,
        serve: Serve,
        artifact: Artifact,
        env: Environment,
        deployment_params: Optional[Dict[str, Any]],
        user: User,
        api_serve_config: APIServeInfraConfig,
    ) -> Dict[str, Any]:
        """Execute rolling deployment with optional maxSurge/maxUnavailable."""
        values = generate_fastapi_values(
            name=serve.name,
            env=env.name,
            runtime=artifact.image_url,
            env_config=EnvConfig(**env.env_configs),
            user_email=user.username,
            serve_infra_config=api_serve_config,
            environment_variables=None,
            is_environment_protected=env.is_protected,
            deployment_strategy_config=deployment_params,
        )
        serve_name = values.get("name", f"{serve.name}-{env.name}")
        artifact_id = f"{env.name}-{serve.name}-{artifact.version}"
        resource_id = f"{env.name}-{serve.name}"

        await self.dcm_client.build_resource(
            darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
            artifact_id=artifact_id,
            values=values,
            version=FASTAPI_SERVE_CHART_VERSION,
        )
        await self.dcm_client.start_resource(
            resource_id=resource_id,
            artifact_id=artifact_id,
            kube_cluster=env.cluster_name,
            namespace=env.namespace,
            darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
        )
        logger.info(f"Rolling deployment started for {serve.name} in {env.name}")
        return {"resource_id": resource_id, "artifact_id": artifact_id}

    async def deploy_blue_green(
        self,
        serve: Serve,
        artifact: Artifact,
        env: Environment,
        user: User,
        api_serve_config: APIServeInfraConfig,
    ) -> Dict[str, Any]:
        """Deploy green alongside blue; traffic stays on blue until promote."""
        if not ENABLE_ISTIO:
            raise HTTPException(
                status_code=400,
                detail="Istio is required for blue-green. Set ENABLE_ISTIO=true.",
            )
        active = await ActiveDeployment.get_or_none(serve=serve, environment=env)
        is_first_deploy = active is None

        values = generate_fastapi_values(
            name=serve.name,
            env=env.name,
            runtime=artifact.image_url,
            env_config=EnvConfig(**env.env_configs),
            user_email=user.username,
            serve_infra_config=api_serve_config,
            environment_variables=None,
            is_environment_protected=env.is_protected,
        )
        if is_first_deploy:
            values["versionLabel"] = "blue"
            values["name"] = f"{env.name}-{serve.name}"
            artifact_id = f"{env.name}-{serve.name}-{artifact.version}-blue"
            resource_id = f"{env.name}-{serve.name}"
            traffic_split = {"blue": 100, "green": 0}
        else:
            values["versionLabel"] = "green"
            values["name"] = f"{env.name}-{serve.name}-green"
            artifact_id = f"{env.name}-{serve.name}-{artifact.version}-green"
            resource_id = f"{env.name}-{serve.name}-green"
            traffic_split = {"blue": 100, "green": 0}

        await self.dcm_client.build_resource(
            darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
            artifact_id=artifact_id,
            values=values,
            version=FASTAPI_SERVE_CHART_VERSION,
        )
        await self.dcm_client.start_resource(
            resource_id=resource_id,
            artifact_id=artifact_id,
            kube_cluster=env.cluster_name,
            namespace=env.namespace,
            darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
        )
        await self.traffic_service.create_destination_rules(
            serve=serve, env=env, strategy="blue_green"
        )
        await self.traffic_service.update_virtual_service(
            serve=serve,
            env=env,
            strategy="blue_green",
            traffic_split=traffic_split,
        )
        logger.info(
            f"Blue-green deployment started for {serve.name} in {env.name} "
            f"(first_deploy={is_first_deploy})"
        )
        return {"resource_id": resource_id, "artifact_id": artifact_id}

    async def deploy_canary(
        self,
        serve: Serve,
        artifact: Artifact,
        env: Environment,
        deployment_params: Optional[Dict[str, Any]],
        user: User,
        api_serve_config: APIServeInfraConfig,
    ) -> Dict[str, Any]:
        """Deploy canary with 0% traffic. Acquires lock first."""
        if not ENABLE_ISTIO:
            raise HTTPException(
                status_code=400,
                detail="Istio is required for canary. Set ENABLE_ISTIO=true.",
            )
        await self.lock_service.acquire_lock(serve_id=serve.id, environment_id=env.id)

        try:
            canary_version = f"{artifact.version}-canary"
            values = generate_fastapi_values(
                name=serve.name,
                env=env.name,
                runtime=artifact.image_url,
                env_config=EnvConfig(**env.env_configs),
                user_email=user.username,
                serve_infra_config=api_serve_config,
                environment_variables=None,
                is_environment_protected=env.is_protected,
            )
            values["versionLabel"] = "canary"
            values["name"] = f"{env.name}-{serve.name}-canary"
            artifact_id = f"{env.name}-{serve.name}-{canary_version}"
            resource_id = f"{env.name}-{serve.name}-canary"

            await self.dcm_client.build_resource(
                darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
                artifact_id=artifact_id,
                values=values,
                version=FASTAPI_SERVE_CHART_VERSION,
            )
            await self.dcm_client.start_resource(
                resource_id=resource_id,
                artifact_id=artifact_id,
                kube_cluster=env.cluster_name,
                namespace=env.namespace,
                darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
            )
            await self.traffic_service.create_destination_rules(
                serve=serve, env=env, strategy="canary"
            )
            await self.traffic_service.update_virtual_service(
                serve=serve,
                env=env,
                strategy="canary",
                traffic_split={"stable": 100, "canary": 0},
            )
            logger.info(f"Canary deployment started for {serve.name} in {env.name}")
            return {"resource_id": resource_id, "artifact_id": artifact_id}
        except Exception:
            await self.lock_service.release_lock(serve_id=serve.id, environment_id=env.id)
            raise

    async def promote_deployment(
        self,
        serve: Serve,
        env: Environment,
        deployment: "Deployment",
        app_deployment: "AppLayerDeployment",
    ) -> None:
        """
        Promote canary or blue-green to 100% traffic.
        Updates VirtualService and ActiveDeployment.
        """
        strategy = app_deployment.deployment_strategy or ""
        if strategy == "canary":
            await self.traffic_service.update_virtual_service(
                serve=serve,
                env=env,
                strategy="canary",
                traffic_split={"stable": 0, "canary": 100},
            )
            await self.lock_service.release_lock(
                serve_id=serve.id, environment_id=env.id
            )
        elif strategy == "blue_green":
            await self.traffic_service.update_virtual_service(
                serve=serve,
                env=env,
                strategy="blue_green",
                traffic_split={"blue": 0, "green": 100},
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Promote not supported for strategy '{strategy}'.",
            )
        logger.info(f"Promoted {strategy} deployment for {serve.name} in {env.name}")

    async def abort_canary(
        self,
        serve: Serve,
        env: Environment,
    ) -> None:
        """Abort canary deployment; traffic stays on stable."""
        await self.traffic_service.update_virtual_service(
            serve=serve,
            env=env,
            strategy="canary",
            traffic_split={"stable": 100, "canary": 0},
        )
        await self.lock_service.release_lock(
            serve_id=serve.id, environment_id=env.id
        )
        logger.info(f"Aborted canary for {serve.name} in {env.name}")

    async def step_canary_traffic(
        self,
        serve: Serve,
        env: Environment,
        traffic_percent: int,
    ) -> None:
        """Advance canary traffic to specified percentage."""
        traffic_percent = max(0, min(100, traffic_percent))
        split = self.traffic_service.calculate_traffic_split(traffic_percent)
        await self.traffic_service.update_virtual_service(
            serve=serve,
            env=env,
            strategy="canary",
            traffic_split=split,
        )
        logger.info(
            f"Canary traffic stepped to {traffic_percent}% for {serve.name} in {env.name}"
        )

    async def rollback_blue_green(
        self,
        serve: Serve,
        env: Environment,
    ) -> None:
        """Rollback blue-green: switch traffic from green back to blue."""
        await self.traffic_service.update_virtual_service(
            serve=serve,
            env=env,
            strategy="blue_green",
            traffic_split={"blue": 100, "green": 0},
        )
        logger.info(f"Rolled back blue-green for {serve.name} in {env.name}")

    async def deploy_model_blue_green(
        self,
        values: Dict[str, Any],
        serve: Serve,
        env: Environment,
        artifact: "Artifact",
    ) -> Dict[str, Any]:
        """Deploy one-click model with blue-green strategy."""
        if not ENABLE_ISTIO:
            raise HTTPException(
                status_code=400,
                detail="Istio is required for blue-green. Set ENABLE_ISTIO=true.",
            )
        active = await ActiveDeployment.get_or_none(serve=serve, environment=env)
        is_first_deploy = active is None
        service_base = f"{env.name}-{serve.name}"
        if is_first_deploy:
            values["versionLabel"] = "blue"
            values["name"] = service_base
            artifact_id = f"{service_base}-{artifact.version}-blue"
            resource_id = service_base
            traffic_split = {"blue": 100, "green": 0}
        else:
            values["versionLabel"] = "green"
            values["name"] = f"{service_base}-green"
            artifact_id = f"{service_base}-{artifact.version}-green"
            resource_id = f"{service_base}-green"
            traffic_split = {"blue": 100, "green": 0}
        await self.dcm_client.build_resource(
            darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
            artifact_id=artifact_id,
            values=values,
            version=FASTAPI_SERVE_CHART_VERSION,
        )
        await self.dcm_client.start_resource(
            resource_id=resource_id,
            artifact_id=artifact_id,
            kube_cluster=env.cluster_name,
            namespace=env.namespace,
            darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
        )
        await self.traffic_service.create_destination_rules(
            serve=serve, env=env, strategy="blue_green"
        )
        await self.traffic_service.update_virtual_service(
            serve=serve,
            env=env,
            strategy="blue_green",
            traffic_split=traffic_split,
        )
        logger.info(
            f"One-click blue-green deployment for {serve.name} in {env.name} "
            f"(first_deploy={is_first_deploy})"
        )
        return {"resource_id": resource_id, "artifact_id": artifact_id}

    async def deploy_model_canary(
        self,
        values: Dict[str, Any],
        serve: Serve,
        env: Environment,
        artifact: "Artifact",
    ) -> Dict[str, Any]:
        """Deploy one-click model with canary strategy."""
        if not ENABLE_ISTIO:
            raise HTTPException(
                status_code=400,
                detail="Istio is required for canary. Set ENABLE_ISTIO=true.",
            )
        await self.lock_service.acquire_lock(serve_id=serve.id, environment_id=env.id)
        try:
            service_base = f"{env.name}-{serve.name}"
            canary_version = f"{artifact.version}-canary"
            values["versionLabel"] = "canary"
            values["name"] = f"{service_base}-canary"
            artifact_id = f"{service_base}-{canary_version}"
            resource_id = f"{service_base}-canary"
            active = await ActiveDeployment.get_or_none(serve=serve, environment=env)
            traffic_split = (
                {"stable": 100, "canary": 0}
                if active
                else {"stable": 0, "canary": 100}
            )
            await self.dcm_client.build_resource(
                darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
                artifact_id=artifact_id,
                values=values,
                version=FASTAPI_SERVE_CHART_VERSION,
            )
            await self.dcm_client.start_resource(
                resource_id=resource_id,
                artifact_id=artifact_id,
                kube_cluster=env.cluster_name,
                namespace=env.namespace,
                darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
            )
            await self.traffic_service.create_destination_rules(
                serve=serve, env=env, strategy="canary"
            )
            await self.traffic_service.update_virtual_service(
                serve=serve,
                env=env,
                strategy="canary",
                traffic_split=traffic_split,
            )
            logger.info(f"One-click canary deployment for {serve.name} in {env.name}")
            return {"resource_id": resource_id, "artifact_id": artifact_id}
        except Exception:
            await self.lock_service.release_lock(
                serve_id=serve.id, environment_id=env.id
            )
            raise
