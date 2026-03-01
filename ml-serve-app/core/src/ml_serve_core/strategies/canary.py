from __future__ import annotations

from typing import Any, Optional

from loguru import logger

from ml_serve_core.service.deployment_service import DeploymentService
from ml_serve_core.utils.yaml_utils import generate_fastapi_values
from ml_serve_core.dtos.dtos import EnvConfig
from ml_serve_core.constants.constants import FASTAPI_SERVE_RESOURCE_NAME, FASTAPI_SERVE_CHART_VERSION
from ml_serve_model import Artifact, Environment, Serve, User, Deployment, AppLayerDeployment
from ml_serve_model.serve_configs import APIServeInfraConfig

from .base import DeploymentStrategy, StrategyInitiationResult, StrategyProgressResult


class CanaryStrategy(DeploymentStrategy):
    DEFAULT_STEPS = [20, 50, 100]

    def __init__(self, deployment_service: Optional[DeploymentService] = None):
        self.deployment_service = deployment_service or DeploymentService()

    @staticmethod
    def _steps(strategy_config: Optional[dict[str, Any]]) -> list[int]:
        if not strategy_config:
            return CanaryStrategy.DEFAULT_STEPS
        steps = strategy_config.get("steps")
        return steps or CanaryStrategy.DEFAULT_STEPS

    @staticmethod
    def _phase_for_step(step: int) -> str:
        return f"canary-{step}"

    @staticmethod
    def _compute_replica_split(total: int, step_percent: int) -> tuple[int, int]:
        total = max(1, int(total))
        step_percent = max(0, min(100, int(step_percent)))
        if step_percent <= 0:
            return total, 0
        if step_percent >= 100:
            return 0, total
        # keep at least 1 primary replica for safety; canary at least 1
        canary = max(1, int(round(total * (step_percent / 100.0))))
        primary = max(1, total - canary)
        return primary, canary

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
        steps = self._steps(strategy_config)

        # If there is no previous deployment, canary behaves like a normal deploy.
        if previous_deployment is None:
            logger.info("No previous deployment found; performing primary deploy for canary strategy.")
            await self.deployment_service.deploy_fastapi_serve(
                serve=serve,
                artifact=artifact,
                env=env,
                api_deployment_config=None,
                infra_config=api_infra_config,
                user=user,
            )
            return StrategyInitiationResult(phase=None, requires_approval=False, metadata={"steps": steps, "step_index": len(steps) - 1})

        total = api_infra_config.fast_api_config_object.min_replicas
        canary_repl = 1

        base_values = generate_fastapi_values(
            name=serve.name,
            env=env.name,
            runtime=artifact.image_url,
            env_config=EnvConfig(**env.env_configs),
            user_email=user.username,
            serve_infra_config=api_infra_config,
            environment_variables=environment_variables,
            is_environment_protected=env.is_protected,
            deployment_role="canary",
            deployment_version=artifact.version,
            deployment_strategy="canary",
            service_enabled=False,   # avoid service name conflict
            ingress_enabled=False,   # avoid routing canary directly
        )

        base_values["replicaCount"] = canary_repl
        base_values.setdefault("hpa", {})
        base_values["hpa"]["maxReplicas"] = canary_repl

        canary_resource_id = f"{env.name}-{serve.name}-canary"
        canary_artifact_id = f"{env.name}-{serve.name}-canary-{artifact.version}"

        await self.deployment_service._build_and_start_fastapi_release(
            darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
            version=FASTAPI_SERVE_CHART_VERSION,
            values=base_values,
            resource_id=canary_resource_id,
            artifact_id=canary_artifact_id,
            kube_cluster=env.cluster_name,
            namespace=env.namespace,
        )

        prev_artifact = await previous_deployment.artifact
        prev_artifact_id = f"{env.name}-{serve.name}-{prev_artifact.version}"
        primary_resource_id = f"{env.name}-{serve.name}"
        shared_selector = {"serve.darwin.io/name": serve.name}

        return StrategyInitiationResult(
            phase="canary-awaiting-approval",
            requires_approval=True,
            metadata={
                "steps": steps,
                "step_index": -1,
                "total_replicas": total,
                "canary_replicas": canary_repl,
                "primary_resource_id": primary_resource_id,
                "primary_artifact_id": prev_artifact_id,
                "canary_resource_id": canary_resource_id,
                "canary_artifact_id": canary_artifact_id,
                "shared_service_selector": shared_selector,
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
        steps = meta.get("steps") or self.DEFAULT_STEPS
        step_index = int(meta.get("step_index") if meta.get("step_index") is not None else -1)

        if step_index >= len(steps) - 1:
            return StrategyProgressResult(phase=None, requires_approval=False, metadata=meta)

        next_index = step_index + 1
        next_step = int(steps[next_index])

        serve = await deployment.serve
        env = await deployment.environment
        artifact = await deployment.artifact

        api_infra_config = await APIServeInfraConfig.get_or_none(serve=serve, environment=env)
        if not api_infra_config:
            raise Exception("APIServeInfraConfig not found for serve/environment")

        primary_artifact_id = meta["primary_artifact_id"]
        primary_resource_id = meta["primary_resource_id"]
        canary_artifact_id = meta["canary_artifact_id"]
        canary_resource_id = meta["canary_resource_id"]
        total = int(meta.get("total_replicas") or api_infra_config.fast_api_config_object.min_replicas)
        shared_selector = meta.get("shared_service_selector") or {"serve.darwin.io/name": serve.name}

        # Ensure Service includes canary pods once we start shifting traffic.
        tm = self.deployment_service.get_traffic_manager()
        await tm.set_service_selector_for_release(
            env=env,
            resource_id=primary_resource_id,
            artifact_id=primary_artifact_id,
            darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
            selector=shared_selector,
        )

        if next_step < 100:
            primary_repl, canary_repl = self._compute_replica_split(total, next_step)

            await self.deployment_service.dcm_client.update_resource(
                values={"replicaCount": canary_repl, "hpa": {"maxReplicas": canary_repl}},
                artifact_id=canary_artifact_id,
                darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
            )
            await self.deployment_service.dcm_client.start_resource(
                resource_id=canary_resource_id,
                artifact_id=canary_artifact_id,
                kube_cluster=env.cluster_name,
                namespace=env.namespace,
                darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
            )

            await self.deployment_service.dcm_client.update_resource(
                values={"replicaCount": primary_repl, "hpa": {"maxReplicas": primary_repl}},
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

            meta.update(
                {
                    "step_index": next_index,
                    "primary_replicas": primary_repl,
                    "canary_replicas": canary_repl,
                }
            )
            return StrategyProgressResult(phase=self._phase_for_step(next_step), requires_approval=True, metadata=meta)

        # Final step: shift 100% traffic to canary, terminate old primary, then promote to primary.
        await self.deployment_service.dcm_client.update_resource(
            values={"replicaCount": total, "hpa": {"maxReplicas": total}},
            artifact_id=canary_artifact_id,
            darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
        )
        await self.deployment_service.dcm_client.start_resource(
            resource_id=canary_resource_id,
            artifact_id=canary_artifact_id,
            kube_cluster=env.cluster_name,
            namespace=env.namespace,
            darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
        )

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

        # Promote by upgrading primary to the new artifact version, then stop canary.
        env_vars = app_layer_deployment.environment_variables or None
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
            deployment_strategy="canary",
            service_enabled=True,
            ingress_enabled=True,
            # empty map makes the chart use its default selectorLabels
            service_selector={},
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

        try:
            await self.deployment_service.dcm_client.stop_resource(
                resource_id=canary_resource_id,
                kube_cluster=env.cluster_name,
                namespace=env.namespace,
            )
        except Exception as e:
            logger.warning(f"Failed to stop canary resource {canary_resource_id}: {e}")

        meta.update(
            {
                "step_index": next_index,
                "primary_artifact_id": new_primary_artifact_id,
                "promoted": True,
                "primary_replicas": total,
                "canary_replicas": 0,
            }
        )
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
        serve = await deployment.serve
        env = await deployment.environment

        primary_artifact_id = meta.get("primary_artifact_id")
        primary_resource_id = meta.get("primary_resource_id") or f"{env.name}-{serve.name}"
        canary_resource_id = meta.get("canary_resource_id")

        if primary_artifact_id:
            tm = self.deployment_service.get_traffic_manager()
            await tm.set_service_selector_for_release(
                env=env,
                resource_id=primary_resource_id,
                artifact_id=primary_artifact_id,
                darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
                selector={"serve.darwin.io/name": serve.name, "deploy.darwin.io/role": "primary"},
            )

            await self.deployment_service.dcm_client.update_resource(
                values={"replicaCount": meta.get("total_replicas"), "hpa": {"maxReplicas": meta.get("total_replicas")}},
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

        if canary_resource_id:
            try:
                await self.deployment_service.dcm_client.stop_resource(
                    resource_id=canary_resource_id,
                    kube_cluster=env.cluster_name,
                    namespace=env.namespace,
                )
            except Exception as e:
                logger.warning(f"Failed to stop canary resource {canary_resource_id}: {e}")

