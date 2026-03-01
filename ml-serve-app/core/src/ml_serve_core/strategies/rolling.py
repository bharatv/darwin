from __future__ import annotations

from typing import Any, Optional

from ml_serve_core.constants.constants import FASTAPI_SERVE_RESOURCE_NAME, FASTAPI_SERVE_CHART_VERSION
from ml_serve_core.dtos.dtos import EnvConfig
from ml_serve_core.service.deployment_service import DeploymentService
from ml_serve_core.utils.yaml_utils import generate_fastapi_values
from ml_serve_model import Artifact, Environment, Serve, User, Deployment, AppLayerDeployment
from ml_serve_model.serve_configs import APIServeInfraConfig

from .base import DeploymentStrategy, StrategyInitiationResult, StrategyProgressResult


class RollingStrategy(DeploymentStrategy):
    DEFAULT_CHECKPOINTS = [50, 100]

    def __init__(self, deployment_service: Optional[DeploymentService] = None):
        self.deployment_service = deployment_service or DeploymentService()

    @staticmethod
    def _checkpoints(strategy_config: Optional[dict[str, Any]]) -> list[int]:
        if not strategy_config:
            return RollingStrategy.DEFAULT_CHECKPOINTS
        cps = strategy_config.get("checkpoints")
        return cps or RollingStrategy.DEFAULT_CHECKPOINTS

    @staticmethod
    def _phase_for_checkpoint(checkpoint: int) -> str:
        return f"rolling-{checkpoint}"

    @staticmethod
    def _compute_replica_split(total: int, new_percent: int) -> tuple[int, int]:
        total = max(1, int(total))
        new_percent = max(0, min(100, int(new_percent)))
        if new_percent <= 0:
            return total, 0
        if new_percent >= 100:
            return 0, total
        new_repl = max(1, int(round(total * (new_percent / 100.0))))
        old_repl = max(1, total - new_repl)
        return old_repl, new_repl

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
        checkpoints = self._checkpoints(strategy_config)
        first = int(checkpoints[0])

        # If there is no previous deployment, rolling behaves like a normal deploy.
        if previous_deployment is None:
            # Still require a manual gate before first deployment.
            return StrategyInitiationResult(
                phase="rolling-awaiting-approval",
                requires_approval=True,
                metadata={
                    "first_deploy": True,
                    "checkpoints": checkpoints,
                    "checkpoint_index": 0,
                },
            )

        total = api_infra_config.fast_api_config_object.min_replicas
        # Start with no traffic to new release until first approval.
        old_repl, new_repl = total, 1

        values = generate_fastapi_values(
            name=serve.name,
            env=env.name,
            runtime=artifact.image_url,
            env_config=EnvConfig(**env.env_configs),
            user_email=user.username,
            serve_infra_config=api_infra_config,
            environment_variables=environment_variables,
            is_environment_protected=env.is_protected,
            deployment_role="rolling",
            deployment_version=artifact.version,
            deployment_strategy="rolling",
            service_enabled=False,
            ingress_enabled=False,
        )
        values["replicaCount"] = new_repl
        values.setdefault("hpa", {})
        values["hpa"]["maxReplicas"] = new_repl

        rolling_resource_id = f"{env.name}-{serve.name}-rolling"
        rolling_artifact_id = f"{env.name}-{serve.name}-rolling-{artifact.version}"

        await self.deployment_service._build_and_start_fastapi_release(
            darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
            version=FASTAPI_SERVE_CHART_VERSION,
            values=values,
            resource_id=rolling_resource_id,
            artifact_id=rolling_artifact_id,
            kube_cluster=env.cluster_name,
            namespace=env.namespace,
        )

        prev_artifact = await previous_deployment.artifact
        primary_artifact_id = f"{env.name}-{serve.name}-{prev_artifact.version}"
        primary_resource_id = f"{env.name}-{serve.name}"

        shared_selector = {"serve.darwin.io/name": serve.name}

        return StrategyInitiationResult(
            phase="rolling-awaiting-approval",
            requires_approval=True,
            metadata={
                "checkpoints": checkpoints,
                "checkpoint_index": -1,
                "total_replicas": total,
                "old_replicas": old_repl,
                "new_replicas": new_repl,
                "primary_resource_id": primary_resource_id,
                "primary_artifact_id": primary_artifact_id,
                "rolling_resource_id": rolling_resource_id,
                "rolling_artifact_id": rolling_artifact_id,
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
        checkpoints = meta.get("checkpoints") or self.DEFAULT_CHECKPOINTS
        idx = int(meta.get("checkpoint_index") if meta.get("checkpoint_index") is not None else -1)

        if meta.get("first_deploy"):
            serve = await deployment.serve
            env = await deployment.environment
            artifact = await deployment.artifact

            api_infra_config = await APIServeInfraConfig.get_or_none(serve=serve, environment=env)
            if not api_infra_config:
                raise Exception("APIServeInfraConfig not found for serve/environment")

            await self.deployment_service.deploy_fastapi_serve(
                serve=serve,
                artifact=artifact,
                env=env,
                api_deployment_config=None,
                infra_config=api_infra_config,
                user=user,
            )

            meta.update({"first_deploy": False, "promoted": True})
            return StrategyProgressResult(phase=None, requires_approval=False, metadata=meta)

        if idx >= len(checkpoints) - 1:
            return StrategyProgressResult(phase=None, requires_approval=False, metadata=meta)

        next_idx = idx + 1
        next_cp = int(checkpoints[next_idx])

        serve = await deployment.serve
        env = await deployment.environment
        artifact = await deployment.artifact

        api_infra_config = await APIServeInfraConfig.get_or_none(serve=serve, environment=env)
        if not api_infra_config:
            raise Exception("APIServeInfraConfig not found for serve/environment")

        total = int(meta.get("total_replicas") or api_infra_config.fast_api_config_object.min_replicas)
        primary_resource_id = meta["primary_resource_id"]
        primary_artifact_id = meta["primary_artifact_id"]
        rolling_resource_id = meta["rolling_resource_id"]
        rolling_artifact_id = meta["rolling_artifact_id"]
        shared_selector = meta.get("shared_service_selector") or {"serve.darwin.io/name": serve.name}

        # Ensure Service includes both releases once we start shifting traffic.
        tm = self.deployment_service.get_traffic_manager()
        await tm.set_service_selector_for_release(
            env=env,
            resource_id=primary_resource_id,
            artifact_id=primary_artifact_id,
            darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
            selector=shared_selector,
        )

        if next_cp < 100:
            old_repl, new_repl = self._compute_replica_split(total, next_cp)

            await self.deployment_service.dcm_client.update_resource(
                values={"replicaCount": new_repl, "hpa": {"maxReplicas": new_repl}},
                artifact_id=rolling_artifact_id,
                darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
            )
            await self.deployment_service.dcm_client.start_resource(
                resource_id=rolling_resource_id,
                artifact_id=rolling_artifact_id,
                kube_cluster=env.cluster_name,
                namespace=env.namespace,
                darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
            )

            await self.deployment_service.dcm_client.update_resource(
                values={"replicaCount": old_repl, "hpa": {"maxReplicas": old_repl}},
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

            meta.update({"checkpoint_index": next_idx, "old_replicas": old_repl, "new_replicas": new_repl})
            return StrategyProgressResult(phase=self._phase_for_checkpoint(next_cp), requires_approval=True, metadata=meta)

        # Final: shift 100% traffic to rolling, terminate old primary, then promote.
        await self.deployment_service.dcm_client.update_resource(
            values={"replicaCount": total, "hpa": {"maxReplicas": total}},
            artifact_id=rolling_artifact_id,
            darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
        )
        await self.deployment_service.dcm_client.start_resource(
            resource_id=rolling_resource_id,
            artifact_id=rolling_artifact_id,
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

        # Promote primary to new artifact while traffic is served by rolling (shared selector).
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
            deployment_strategy="rolling",
            service_enabled=True,
            ingress_enabled=True,
            service_selector=shared_selector,
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
                resource_id=rolling_resource_id,
                kube_cluster=env.cluster_name,
                namespace=env.namespace,
            )
        except Exception:
            pass

        meta.update({"checkpoint_index": next_idx, "primary_artifact_id": new_primary_artifact_id, "promoted": True})
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
        rolling_resource_id = meta.get("rolling_resource_id")

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

        if rolling_resource_id:
            try:
                await self.deployment_service.dcm_client.stop_resource(
                    resource_id=rolling_resource_id,
                    kube_cluster=env.cluster_name,
                    namespace=env.namespace,
                )
            except Exception:
                pass

