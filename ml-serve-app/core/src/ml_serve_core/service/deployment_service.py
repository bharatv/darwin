import os
import re
from typing import Optional, List

from fastapi import HTTPException
from tortoise.transactions import in_transaction

from ml_serve_app_layer.dtos.requests import DeploymentRequest, APIServeDeploymentConfigRequest, \
    WorkflowServeDeploymentConfigRequest, ModelDeploymentRequest, ModelUndeployRequest
from ml_serve_core.client.darwin_workflow_client import DarwinWorkflowClient
from ml_serve_core.client.dcm_client import DCMClient
from ml_serve_core.client.mlflow_client import MLflowClient
from ml_serve_core.constants.constants import (
    FASTAPI_SERVE_RESOURCE_NAME,
    FASTAPI_SERVE_CHART_VERSION,
    JOB_CLUSTER_RUNTIME,
    DEFAULT_RUNTIME,
)
from ml_serve_core.config.configs import Config
from ml_serve_core.dtos.dtos import EnvConfig
from ml_serve_core.service.serve_config_service import ServeConfigService
from ml_serve_core.service.deployment_strategy_service import DeploymentStrategyService
from ml_serve_core.service.deployment_lock_service import DeploymentLockService
from ml_serve_core.service.traffic_management_service import TrafficManagementService
from ml_serve_core.service.resource_validation_service import ResourceValidationService
from ml_serve_core.utils.utils import get_host_name, get_service_url, get_service_url_for_one_click
from ml_serve_core.utils.yaml_utils import generate_fastapi_values, generate_fastapi_infra_values, \
    generate_fastapi_values_for_one_click_model_deployment
from ml_serve_core.utils.storage_strategy import determine_storage_strategy
from ml_serve_model import Serve, Artifact, Environment, APIServeInfraConfig, User, ScheduledWorkflowDeployment, \
    Deployment
from ml_serve_model.active_deployment import ActiveDeployment
from ml_serve_model.app_layer_deployments import AppLayerDeployment
from ml_serve_model.deployment import Deployment
from loguru import logger
from ml_serve_model.serve_configs import ServeConfig, WorkflowServeInfraConfig
from ml_serve_model.enums import BackendType, ServeType, DeploymentStatus
from datetime import datetime, timezone


class DeploymentService:

    def __init__(self):
        self.dcm_client = DCMClient()
        self.serve_config_service = ServeConfigService()
        self.deployment_strategy_service = DeploymentStrategyService()
        self.deployment_lock_service = DeploymentLockService()
        self.traffic_management_service = TrafficManagementService()
        self.resource_validation_service = ResourceValidationService()
        self.config = Config()  # Centralized configuration
        self.workflow_client = DarwinWorkflowClient()
        self.mlflow_client = MLflowClient()

    @staticmethod
    def _sanitize_identifier(value: str) -> str:
        sanitized = re.sub(r"[^a-z0-9-]", "-", value.lower())
        sanitized = re.sub(r"-+", "-", sanitized).strip("-")
        return sanitized

    def _default_space(self, user: User) -> str:
        username = (user.username or "").replace("@", "-")
        sanitized = self._sanitize_identifier(username) if username else "one-click"
        return sanitized or "one-click"

    def _build_one_click_env_vars(self, model_uri: str, artifact_version: str) -> dict:
        env_vars = {
            "MLFLOW_MODEL_URI": model_uri,
            "MODEL_VERSION": artifact_version
        }
        if self.config.mlflow_tracking_uri:
            env_vars["MLFLOW_TRACKING_URI"] = self.config.mlflow_tracking_uri
        if self.config.mlflow_tracking_username:
            env_vars["MLFLOW_TRACKING_USERNAME"] = self.config.mlflow_tracking_username
        if self.config.mlflow_tracking_password:
            env_vars["MLFLOW_TRACKING_PASSWORD"] = self.config.mlflow_tracking_password
        return env_vars

    async def _update_active_deployment(self, serve: Serve, env: Environment, deployment: Deployment):
        active_deployment = await ActiveDeployment.get_or_none(serve=serve, environment=env)
        if not active_deployment:
            await ActiveDeployment.create(serve=serve, environment=env, deployment=deployment)
            return

        # Mark previous deployment as ENDED
        previous = await active_deployment.deployment
        previous.status = DeploymentStatus.ENDED.value
        previous.ended_at = datetime.now(timezone.utc)
        await previous.save()

        active_deployment.previous_deployment = previous
        active_deployment.deployment = deployment
        await active_deployment.save()

    async def get_deployment_by_serve_id(self, serve_id: int) -> Optional[list[Deployment]]:
        if not await Deployment.exists(serve_id=serve_id):
            return None

        return await Deployment.filter(serve_id=serve_id, status=DeploymentStatus.ACTIVE.value).order_by("-created_at")

    async def get_app_layer_deployment_by_id(self, deployment_id: int) -> Optional[AppLayerDeployment]:
        if not await AppLayerDeployment.exists(deployment_id=deployment_id):
            return None

        return await AppLayerDeployment.filter(deployment_id=deployment_id).first()

    async def get_workflow_deployment_by_id(self, deployment_id: int) -> Optional[ScheduledWorkflowDeployment]:
        if not await ScheduledWorkflowDeployment.exists(deployment_id=deployment_id):
            return None

        return await ScheduledWorkflowDeployment.filter(deployment_id=deployment_id).first()

    async def get_deployment_from_name_and_env_and_version(
            self, serve_name: str, env_name: str, artifact_version: str
    ) -> Optional[Deployment]:
        if not await Deployment.exists(
                serve__name=serve_name,
                environment__name=env_name,
                artifact__version=artifact_version
        ):
            return None

        deployment = await Deployment.filter(
            serve__name=serve_name,
            environment__name=env_name,
            artifact__version=artifact_version
        ).order_by("-created_at").first()

        return deployment

    async def get_deployment_by_id(self, deployment_id: int) -> Optional[Deployment]:
        """Get deployment by ID."""
        return await Deployment.get_or_none(id=deployment_id)

    async def promote_deployment(self, deployment_id: int, user: User) -> dict:
        """Promote canary or blue-green deployment to 100% traffic."""
        deployment = await self.get_deployment_by_id(deployment_id)
        if not deployment:
            raise HTTPException(status_code=404, detail="Deployment not found")
        app_deployment = await self.get_app_layer_deployment_by_id(deployment_id)
        if not app_deployment:
            raise HTTPException(
                status_code=400,
                detail="Promote only supported for API deployments",
            )
        strategy = app_deployment.deployment_strategy or ""
        if strategy not in ("canary", "blue_green"):
            raise HTTPException(
                status_code=400,
                detail=f"Promote not supported for strategy '{strategy}'",
            )
        serve = await deployment.serve
        env = await deployment.environment
        await self.deployment_strategy_service.promote_deployment(
            serve=serve,
            env=env,
            deployment=deployment,
            app_deployment=app_deployment,
        )
        await self._update_active_deployment(serve, env, deployment)
        logger.info(f"Promoted deployment {deployment_id} for {serve.name}")
        return {"message": "Deployment promoted successfully", "data": {"deployment_id": deployment_id}}

    async def abort_canary(self, deployment_id: int, user: User) -> dict:
        """Abort canary deployment; traffic stays on stable."""
        deployment = await self.get_deployment_by_id(deployment_id)
        if not deployment:
            raise HTTPException(status_code=404, detail="Deployment not found")
        app_deployment = await self.get_app_layer_deployment_by_id(deployment_id)
        if not app_deployment or app_deployment.deployment_strategy != "canary":
            raise HTTPException(
                status_code=400,
                detail="Abort only supported for canary deployments",
            )
        serve = await deployment.serve
        env = await deployment.environment
        await self.deployment_strategy_service.abort_canary(serve=serve, env=env)
        logger.info(f"Aborted canary deployment {deployment_id} for {serve.name}")
        return {"message": "Canary aborted successfully", "data": {"deployment_id": deployment_id}}

    async def step_canary_traffic(
        self, deployment_id: int, traffic_percent: int, user: User
    ) -> dict:
        """Advance canary traffic to specified percentage."""
        deployment = await self.get_deployment_by_id(deployment_id)
        if not deployment:
            raise HTTPException(status_code=404, detail="Deployment not found")
        app_deployment = await self.get_app_layer_deployment_by_id(deployment_id)
        if not app_deployment or app_deployment.deployment_strategy != "canary":
            raise HTTPException(
                status_code=400,
                detail="Step only supported for canary deployments",
            )
        serve = await deployment.serve
        env = await deployment.environment
        await self.deployment_strategy_service.step_canary_traffic(
            serve=serve, env=env, traffic_percent=traffic_percent
        )
        logger.info(
            f"Canary traffic stepped to {traffic_percent}% for deployment {deployment_id}"
        )
        return {
            "message": f"Canary traffic set to {traffic_percent}%",
            "data": {"deployment_id": deployment_id, "traffic_percent": traffic_percent},
        }

    async def rollback_deployment(
        self, serve_name: str, env_name: str, user: User
    ) -> dict:
        """Rollback to previous deployment version."""
        serve = await Serve.get_or_none(name=serve_name)
        if not serve:
            raise HTTPException(status_code=404, detail=f"Serve '{serve_name}' not found")
        env = await Environment.get_or_none(name=env_name)
        if not env:
            raise HTTPException(status_code=404, detail=f"Environment '{env_name}' not found")
        active = await ActiveDeployment.get_or_none(serve=serve, environment=env)
        if not active:
            raise HTTPException(
                status_code=404,
                detail="No active deployment to rollback from",
            )
        previous = await active.previous_deployment
        if not previous:
            raise HTTPException(
                status_code=400,
                detail="No previous deployment to rollback to",
            )
        prev_artifact = await previous.artifact
        current = await active.deployment
        current_artifact = await current.artifact
        app_deployment = await self.get_app_layer_deployment_by_id(current.id)
        strategy = app_deployment.deployment_strategy if app_deployment else None
        if strategy == "canary":
            await self.deployment_strategy_service.abort_canary(serve=serve, env=env)
        elif strategy == "blue_green":
            await self.deployment_strategy_service.rollback_blue_green(
                serve=serve, env=env
            )
        else:
            resource_id = f"{env.name}-{serve.name}"
            await self.dcm_client.start_resource(
                resource_id=resource_id,
                artifact_id=f"{env.name}-{serve.name}-{prev_artifact.version}",
                kube_cluster=env.cluster_name,
                namespace=env.namespace,
                darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
            )
        await self._update_active_deployment(serve, env, previous)
        logger.info(
            f"Rolled back {serve.name} in {env.name} from {current_artifact.version} "
            f"to {prev_artifact.version}"
        )
        return {
            "message": "Rollback successful",
            "data": {
                "serve_name": serve_name,
                "env": env_name,
                "artifact_version": prev_artifact.version,
            },
        }

    async def get_deployment_status(self, deployment_id: int) -> dict:
        """Get deployment status (strategy, traffic split, versions)."""
        deployment = await self.get_deployment_by_id(deployment_id)
        if not deployment:
            raise HTTPException(status_code=404, detail="Deployment not found")
        serve = await deployment.serve
        env = await deployment.environment
        artifact = await deployment.artifact
        app_deployment = await self.get_app_layer_deployment_by_id(deployment_id)
        strategy = (app_deployment.deployment_strategy if app_deployment else None) or "rolling"
        is_locked = await self.deployment_lock_service.is_locked(
            serve_id=serve.id, environment_id=env.id
        )
        return {
            "deployment_id": deployment_id,
            "serve_name": serve.name,
            "env": env.name,
            "artifact_version": artifact.version,
            "strategy": strategy,
            "status": getattr(deployment, "status", DeploymentStatus.ACTIVE.value),
            "locked": is_locked,
            "created_at": deployment.created_at.isoformat() if deployment.created_at else None,
        }

    async def deploy_artifact(
            self,
            serve: Serve,
            artifact: Artifact,
            serve_config: ServeConfig,
            env: Environment,
            deployment_request: DeploymentRequest,
            user: User
    ):
        if serve.type == ServeType.API.value and hasattr(serve_config, "fast_api_config_object"):
            fc = serve_config.fast_api_config_object
            if fc:
                required_cpu = float(fc.cores or 1) * (fc.min_replicas or 1)
                required_memory = float(fc.memory or 1) * (fc.min_replicas or 1)
                await self.resource_validation_service.check_resources(
                    env=env, required_cpu=required_cpu, required_memory=required_memory
                )

        previous_active_deployment = await ActiveDeployment.get_or_none(serve=serve, environment=env)
        api_deployment_resp = None

        previous_deployment_obj = None
        if previous_active_deployment:
            previous_deployment_obj = await previous_active_deployment.deployment
            previous_artifact = await previous_deployment_obj.artifact
            previous_artifact_version = previous_artifact.version

        deployment = None
        api_deployment_config = deployment_request.api_serve_deployment_config
        if serve.type == ServeType.API.value:
            if previous_deployment_obj:
                api_deployment_obj = await self.get_app_layer_deployment_by_id(previous_deployment_obj.id)
                if api_deployment_config is None:
                    deployment_request.api_serve_deployment_config = APIServeDeploymentConfigRequest(
                        environment_variables=api_deployment_obj.environment_variables,
                        deployment_strategy=api_deployment_obj.deployment_strategy,
                        deployment_strategy_config=api_deployment_obj.deployment_params
                    )
                    api_deployment_config = deployment_request.api_serve_deployment_config
                elif (
                        api_deployment_config.environment_variables is None
                        or api_deployment_config.environment_variables == {}
                ) and api_deployment_obj:
                    deployment_request.api_serve_deployment_config = APIServeDeploymentConfigRequest(
                        deployment_strategy=api_deployment_config.deployment_strategy,
                        deployment_strategy_config=api_deployment_config.deployment_strategy_config,
                        environment_variables=api_deployment_obj.environment_variables,
                    )
                    api_deployment_config = deployment_request.api_serve_deployment_config

            deployment, api_deployment_resp = await self.deploy_api_serve(
                serve,
                artifact,
                env,
                serve_config,
                deployment_request.api_serve_deployment_config,
                user
            )
        elif serve.type == ServeType.WORKFLOW.value:
            workflow_deployment_obj = await self.get_workflow_deployment_by_id(previous_deployment_obj.deployment_id)
            if (deployment_request.workflow_serve_deployment_config.input_parameters is None
                    or deployment_request.workflow_serve_deployment_config.input_parameters == {}):
                deployment_request.workflow_serve_deployment_config.input_parameters = workflow_deployment_obj.input_params
            deployment = await self.deploy_workflow_serve(
                serve,
                artifact,
                env,
                serve_config,
                deployment_request.workflow_serve_deployment_config,
                user
            )

        strategy = api_deployment_config.deployment_strategy if api_deployment_config else None
        if strategy in (None, "rolling"):
            if not previous_active_deployment:
                await ActiveDeployment.create(serve=serve, environment=env, deployment=deployment)
            else:
                previous_active_deployment.previous_deployment = await previous_active_deployment.deployment
                previous_active_deployment.deployment = deployment
                await previous_active_deployment.save()
        elif strategy == "blue_green" and not previous_active_deployment:
            await ActiveDeployment.create(serve=serve, environment=env, deployment=deployment)

        if api_deployment_resp and deployment:
            api_deployment_resp["deployment_id"] = deployment.id
            api_deployment_resp["strategy"] = strategy or "rolling"
            api_deployment_resp["status"] = "deploying"

        return api_deployment_resp

    async def deploy_api_serve(
            self,
            serve: Serve,
            artifact: Artifact,
            env: Environment,
            api_serve_config: APIServeInfraConfig,
            api_deployment_config: APIServeDeploymentConfigRequest,
            user: User
    ):
        resp = None
        strategy = api_deployment_config.deployment_strategy if api_deployment_config else None

        if api_serve_config.backend_type == BackendType.FastAPI.value:
            if strategy == "canary":
                await self.deployment_strategy_service.deploy_canary(
                    serve=serve,
                    artifact=artifact,
                    env=env,
                    deployment_params=api_deployment_config.deployment_strategy_config if api_deployment_config else None,
                    user=user,
                    api_serve_config=api_serve_config,
                )
                resp = {"service_url": get_service_url(serve.name, env.name, EnvConfig(**env.env_configs), env.is_protected)}
            elif strategy == "blue_green":
                await self.deployment_strategy_service.deploy_blue_green(
                    serve=serve,
                    artifact=artifact,
                    env=env,
                    user=user,
                    api_serve_config=api_serve_config,
                )
                resp = {"service_url": get_service_url(serve.name, env.name, EnvConfig(**env.env_configs), env.is_protected)}
            else:
                resp = await self.deploy_fastapi_serve(
                    serve, artifact, env, api_deployment_config, api_serve_config, user
                )

        async with in_transaction():
            deployment = await Deployment.create(
                serve=serve,
                artifact=artifact,
                environment=env,
                created_by=user,
            )
            if api_deployment_config is None:
                deployment_strategy = None
                deployment_params = None
                environment_variables = None
            else:
                deployment_strategy = api_deployment_config.deployment_strategy
                deployment_params = api_deployment_config.deployment_strategy_config
                environment_variables = api_deployment_config.environment_variables

            api_deployment = await AppLayerDeployment.create(
                deployment=deployment,
                deployment_strategy=deployment_strategy,
                deployment_params=deployment_params,
                environment_variables=environment_variables
            )

            if strategy == "canary":
                await self.deployment_lock_service.update_lock_deployment_id(
                    serve_id=serve.id, environment_id=env.id, deployment_id=deployment.id
                )

        return deployment, resp

    async def deploy_fastapi_serve(
            self,
            serve: Serve,
            artifact: Artifact,
            env: Environment,
            api_deployment_config: APIServeDeploymentConfigRequest,
            infra_config: APIServeInfraConfig,
            user: User
    ):
        if api_deployment_config is None:
            environment_variables = None
            deployment_strategy_config = None
        else:
            environment_variables = api_deployment_config.environment_variables
            deployment_strategy_config = api_deployment_config.deployment_strategy_config
        values_json = generate_fastapi_values(
            name=serve.name,
            env=env.name,
            runtime=artifact.image_url,
            env_config=EnvConfig(**env.env_configs),
            user_email=user.username,
            serve_infra_config=infra_config,
            environment_variables=environment_variables,
            is_environment_protected=env.is_protected,
            deployment_strategy_config=deployment_strategy_config,
        )

        build_resp = await self.dcm_client.build_resource(
            darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
            artifact_id=f"{env.name}-{serve.name}-{artifact.version}",
            values=values_json,
            version=FASTAPI_SERVE_CHART_VERSION
        )

        start_resp = await self.dcm_client.start_resource(
            resource_id=f"{env.name}-{serve.name}",
            artifact_id=f"{env.name}-{serve.name}-{artifact.version}",
            kube_cluster=env.cluster_name,
            namespace=env.namespace,
            darwin_resource=FASTAPI_SERVE_RESOURCE_NAME
        )

        return {
            "service_url": get_service_url(serve.name, env.name, EnvConfig(**env.env_configs), env.is_protected)
        }

    async def deploy_workflow_serve(
            self,
            serve: Serve,
            artifact: Artifact,
            environment: Environment,
            workflow_serve_config: WorkflowServeInfraConfig,
            workflow_serve_deployment_config: WorkflowServeDeploymentConfigRequest,
            user: User
    ):
        workflow_id = await self.workflow_client.get_workflow_id_by_name(environment.workflow_url, serve.name)

        if not workflow_id:
            job_cluster_definition_id = await self.workflow_client.create_job_cluster_definition(
                environment.workflow_url,
                {
                    "cluster_name": f"cluster-definition-{serve.name}",
                    "tags": [],
                    "runtime": JOB_CLUSTER_RUNTIME,
                    "inactive_time": "60",
                    "head_node_config": workflow_serve_config.head_node_config_object,
                    "worker_node_configs": workflow_serve_config.worker_node_config_list,
                    "user": user.username,
                }
            )

            workflow_id = await self.workflow_client.create_workflow_serve(
                environment.workflow_url,
                {
                    "workflow_name": serve.name,
                    "description": serve.description,
                    "tags": [serve.space],
                    "schedule": workflow_serve_config.schedule,
                    "retries": 2,
                    "notify_on": "",
                    "max_concurrent_runs": 1,
                    "tasks": [
                        {
                            "task_name": f"{serve.name}-workflow-task",
                            "source": f"{artifact.github_repo_url}/tree/{artifact.branch}",
                            "source_type": "git",
                            "file_path": artifact.file_path,
                            "dynamic_artifact": False,
                            "cluster_id": job_cluster_definition_id,
                            "cluster_type": "job",
                            "dependent_libraries": "",
                            "input_parameters": workflow_serve_deployment_config.input_parameters,
                            "retries": 2,
                            "timeout": 3600,
                            "depends_on": []
                        }
                    ]
                }
            )
        else:
            workflow = await self.workflow_client.get_workflow_by_id(environment.workflow_url, workflow_id)

            job_cluster_definition = await self.workflow_client.get_job_cluster_definition(
                environment.workflow_url,
                workflow["tasks"][0]["cluster_id"]
            )

            job_cluster_definition['head_node_config'] = workflow_serve_config.head_node_config_object
            job_cluster_definition['worker_node_configs'] = workflow_serve_config.worker_node_config_list
            job_cluster_definition['user'] = user.username

            await self.workflow_client.update_job_cluster_definition(
                environment.workflow_url,
                job_cluster_definition['cluster_id'],
                job_cluster_definition
            )

            workflow["schedule"] = workflow_serve_config.schedule
            workflow["tasks"][0]["input_parameters"] = workflow_serve_deployment_config.input_parameters
            workflow["tasks"][0]["source"] = f"{artifact.github_repo_url}/tree/{artifact.branch}"
            workflow["tasks"][0]["file_path"] = artifact.file_path

            await self.workflow_client.update_workflow_serve(
                environment.workflow_url,
                workflow_id,
                workflow
            )

        async with in_transaction():
            deployment = await Deployment.create(
                serve=serve,
                artifact=artifact,
                environment=environment,
                created_by=user,
            )

            await ScheduledWorkflowDeployment.create(
                workflow_id=workflow_id,
                input_params=workflow_serve_deployment_config.input_parameters,
                deployment=deployment
            )

        return deployment

    async def redeploy_api_serve_with_updated_infra_config(
            self,
            serve: Serve,
            env: Environment,
            user: User,
            api_serve_config: APIServeInfraConfig
    ):
        """
        Update the APIServeConfig and redeploy the serve.

        Note: This will only work if the serve has been deployed before.
        If no active deployment exists, the infra config will be updated in the database
        but no redeployment will occur (user must do a fresh deployment).
        """
        active_deployment = await ActiveDeployment.get_or_none(serve=serve, environment=env)

        if not active_deployment:
            logger.info(
                f"No active deployment found for serve '{serve.name}' in environment '{env.name}'. Infra config updated."
            )
            return None

        current_deployment: Deployment = await active_deployment.deployment
        artifact: Artifact = await current_deployment.artifact

        values = generate_fastapi_infra_values(
            api_serve_config
        )

        try:
            # Try to update the existing artifact
            update_resp = await self.dcm_client.update_resource(
                artifact_id=f"{env.name}-{serve.name}-{artifact.version}",
                values=values,
                darwin_resource=FASTAPI_SERVE_RESOURCE_NAME
            )

            # If update succeeds, restart with updated config
            start_resp = await self.dcm_client.start_resource(
                resource_id=f"{env.name}-{serve.name}",
                artifact_id=f"{env.name}-{serve.name}-{artifact.version}",
                kube_cluster=env.cluster_name,
                namespace=env.namespace,
                darwin_resource=FASTAPI_SERVE_RESOURCE_NAME
            )

            logger.info(
                f"Successfully redeployed serve '{serve.name}' in environment '{env.name}' "
                f"with updated infra config"
            )

        except Exception as e:
            # If update fails (e.g., artifact file doesn't exist in DCM), do a full rebuild
            logger.warning(
                f"Failed to update existing artifact for serve '{serve.name}' in environment '{env.name}'. "
                f"Performing full rebuild. Error: {e}"
            )

            # Generate full values (not just infra)
            full_values = generate_fastapi_values(
                name=serve.name,
                env=env.name,
                runtime=artifact.image_url,
                env_config=EnvConfig(**env.env_configs),
                user_email=user.username,
                serve_infra_config=api_serve_config,
                environment_variables=None,  # Will use existing env vars from deployment
                is_environment_protected=env.is_protected,
            )

            # Get existing environment variables from the deployment
            app_layer_deployment = await AppLayerDeployment.get_or_none(deployment=current_deployment)
            if app_layer_deployment and app_layer_deployment.environment_variables:
                for key, val in app_layer_deployment.environment_variables.items():
                    full_values['envs'][str.upper(key)] = val

            # Rebuild the artifact from scratch
            build_resp = await self.dcm_client.build_resource(
                darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
                artifact_id=f"{env.name}-{serve.name}-{artifact.version}",
                values=full_values,
                version=FASTAPI_SERVE_CHART_VERSION
            )

            # Start with new artifact
            start_resp = await self.dcm_client.start_resource(
                resource_id=f"{env.name}-{serve.name}",
                artifact_id=f"{env.name}-{serve.name}-{artifact.version}",
                kube_cluster=env.cluster_name,
                namespace=env.namespace,
                darwin_resource=FASTAPI_SERVE_RESOURCE_NAME
            )

            logger.info(
                f"Successfully rebuilt and redeployed serve '{serve.name}' in environment '{env.name}' "
                f"with updated infra config"
            )

    async def redeploy_workflow_serve_with_updated_infra_config(
            self,
            serve: Serve,
            env: Environment,
            user: User,
            workflow_serve_config: WorkflowServeInfraConfig
    ):
        """
        Update the WorkflowServeConfig and redeploy the serve.
        """
        active_deployment = await ActiveDeployment.get_or_none(serve=serve, environment=env)

        if not active_deployment:
            return None

        workflow_id = await self.workflow_client.get_workflow_id_by_name(env.workflow_url, serve.name)

        if not workflow_id:
            logger.error(f"Workflow with name {serve.name} not found")
            raise Exception("Workflow not found")

        workflow = await self.workflow_client.get_workflow_by_id(env.workflow_url, workflow_id)

        job_cluster_definition = await self.workflow_client.get_job_cluster_definition(
            env.workflow_url,
            workflow["tasks"][0]["cluster_id"]
        )

        job_cluster_definition['head_node_config'] = workflow_serve_config.head_node_config_object
        job_cluster_definition['worker_node_configs'] = workflow_serve_config.worker_node_config_list
        job_cluster_definition['user'] = user.username

        workflow["schedule"] = workflow_serve_config.schedule

        await self.workflow_client.update_job_cluster_definition(
            env.workflow_url,
            job_cluster_definition['cluster_id'],
            job_cluster_definition
        )

        await self.workflow_client.update_workflow_serve(
            env.workflow_url,
            workflow_id,
            workflow
        )

    async def deploy_model(self, request: ModelDeploymentRequest, user: User):
        env = await Environment.get_or_none(name=request.env)
        if not env:
            raise HTTPException(
                status_code=404,
                detail=f"Environment '{request.env}' not found. Please create it first."
            )
        await self.resource_validation_service.check_resources(
            env=env,
            required_cpu=float(request.cores) * request.min_replicas,
            required_memory=float(request.memory) * request.min_replicas,
        )

        # Validate model URI exists in MLflow before proceeding
        is_valid, error_msg = await self.mlflow_client.validate_model_uri(request.model_uri)
        if not is_valid:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Invalid model URI",
                    "error": error_msg,
                    "hint": "Please verify the model exists in MLflow and the URI is correct."
                }
            )

        env_config = EnvConfig(**env.env_configs)
        serve_name = request.serve_name  # serve_name is required

        serve = await Serve.get_or_none(name=serve_name)
        if serve and serve.type != ServeType.API.value:
            raise HTTPException(
                status_code=400,
                detail=f"Serve '{serve_name}' exists but is not of API type."
            )

        if not serve:
            serve = await Serve.create(
                name=serve_name,
                type=ServeType.API.value,
                description="Auto-generated serve for one-click deployments",
                space=self._default_space(user),
                created_by=user,
            )

        # Check if this version is already actively deployed
        active = await ActiveDeployment.get_or_none(serve=serve, environment=env)
        if active:
            active_deployment_obj = await active.deployment
            active_artifact = await active_deployment_obj.artifact
            if active_artifact.version == request.artifact_version:
                raise HTTPException(
                    status_code=400,
                    detail=f"Version '{request.artifact_version}' is already deployed for serve '{serve_name}'. "
                )

        artifact = await Artifact.get_or_none(serve=serve, version=request.artifact_version)
        if not artifact:
            artifact = await Artifact.create(
                serve=serve,
                version=request.artifact_version,
                github_repo_url=request.model_uri,
                image_url=DEFAULT_RUNTIME,
                created_by=user,
            )
        else:
            artifact.github_repo_url = request.model_uri
            artifact.image_url = DEFAULT_RUNTIME
            await artifact.save()

        fast_api_config = {
            "cores": request.cores,
            "memory": request.memory,
            "node_capacity_type": request.node_capacity,
            "min_replicas": request.min_replicas,
            "max_replicas": request.max_replicas,
        }

        api_infra_config = await APIServeInfraConfig.get_or_none(serve=serve, environment=env)
        if not api_infra_config:
            api_infra_config = await APIServeInfraConfig.create(
                serve=serve,
                environment=env,
                backend_type=BackendType.FastAPI.value,
                fast_api_config=fast_api_config,
                additional_hosts=None,
                created_by=user,
                updated_by=user,
            )
        else:
            api_infra_config.fast_api_config = fast_api_config
            api_infra_config.updated_by = user
            await api_infra_config.save()

        environment_variables = self._build_one_click_env_vars(request.model_uri, request.artifact_version)

        # Determine optimal storage strategy for model caching
        try:
            storage_strategy = await determine_storage_strategy(
                user_strategy=request.storage_strategy or "auto",
                model_uri=request.model_uri,
                mlflow_client=self.mlflow_client,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        values_json = generate_fastapi_values_for_one_click_model_deployment(
            name=serve.name,
            env=request.env,
            runtime=DEFAULT_RUNTIME,
            env_config=env_config,
            user_email=user.username,
            environment_variables=environment_variables,
            cores=request.cores,
            memory=request.memory,
            min_replicas=request.min_replicas,
            max_replicas=request.max_replicas,
            node_capacity_type=request.node_capacity,
            storage_strategy=storage_strategy,
            model_uri=request.model_uri,
            model_downloader_image=self.config.model_downloader_image,
            model_cache_pvc_name=self.config.model_cache_pvc_name,
            model_cache_path=self.config.model_cache_path,
            tracking_uri=self.config.mlflow_tracking_uri,
            tracking_username=self.config.mlflow_tracking_username,
            tracking_password=self.config.mlflow_tracking_password,
        )

        strategy = request.deployment_strategy or "rolling"
        deployment_strategy_config = request.deployment_strategy_config

        if strategy == "blue_green":
            await self.deployment_strategy_service.deploy_model_blue_green(
                values=values_json,
                serve=serve,
                env=env,
                artifact=artifact,
            )
        elif strategy == "canary":
            await self.deployment_strategy_service.deploy_model_canary(
                values=values_json,
                serve=serve,
                env=env,
                artifact=artifact,
            )
        else:
            artifact_identifier = f"{env.name}-{serve.name}-{artifact.version}"
            await self.dcm_client.build_resource(
                darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
                artifact_id=artifact_identifier,
                values=values_json,
                version=FASTAPI_SERVE_CHART_VERSION,
            )
            await self.dcm_client.start_resource(
                resource_id=serve.name,
                artifact_id=artifact_identifier,
                kube_cluster=env_config.cluster_name,
                namespace=env_config.namespace,
                darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
            )

        async with in_transaction():
            deployment = await Deployment.create(
                serve=serve,
                artifact=artifact,
                environment=env,
                created_by=user,
            )
            await AppLayerDeployment.create(
                deployment=deployment,
                deployment_strategy=strategy,
                deployment_params=deployment_strategy_config,
                environment_variables=environment_variables,
            )

        if strategy == "canary":
            await self.deployment_lock_service.update_lock_deployment_id(
                serve_id=serve.id,
                environment_id=env.id,
                deployment_id=deployment.id,
            )

        active = await ActiveDeployment.get_or_none(serve=serve, environment=env)
        if strategy in (None, "rolling"):
            await self._update_active_deployment(serve, env, deployment)
        elif strategy == "blue_green" and not active:
            await ActiveDeployment.create(serve=serve, environment=env, deployment=deployment)
        elif strategy == "canary" and not active:
            await ActiveDeployment.create(serve=serve, environment=env, deployment=deployment)

        service_url = get_service_url_for_one_click(serve.name, env_config)
        result = {"service_url": service_url}
        if strategy in ("canary", "blue_green"):
            result["deployment_id"] = deployment.id
            result["strategy"] = strategy
            result["status"] = "deploying"
        return result

    async def undeploy_model(self, request: ModelUndeployRequest) -> dict:
        """
        Undeploy a one-click model deployment.

        This stops the running Kubernetes resource for a model that was deployed
        via the deploy_model (one-click deployment) API.

        Args:
            request: ModelUndeployRequest containing serve_name and env

        Returns:
            dict with status message

        Raises:
            HTTPException: If environment not found, serve not found, or no active deployment
        """
        
        # 1. Validate environment exists
        env = await Environment.get_or_none(name=request.env)
        if not env:
            raise HTTPException(
                status_code=404,
                detail=f"Environment '{request.env}' not found."
            )

        # 2. Validate serve exists in DB
        serve_name = request.serve_name
        serve = await Serve.get_or_none(name=serve_name)
        if not serve:
            raise HTTPException(
                status_code=404,
                detail=f"Serve '{serve_name}' not found."
            )

        # 3. Validate active deployment exists
        active = await ActiveDeployment.get_or_none(serve=serve, environment=env)
        if not active:
            raise HTTPException(
                status_code=404,
                detail=f"No active deployment found for serve '{serve_name}' in environment '{request.env}'."
            )

        env_config = EnvConfig(**env.env_configs)
        
        # For one-click deployments, resource_id is just the serve_name
        # (unlike regular serves which use {env.name}-{serve.name})
        resource_id = serve_name

        # 4. Stop the resource via DCM
        try:
            await self.dcm_client.stop_resource(
                resource_id=resource_id,
                kube_cluster=env_config.cluster_name,
                namespace=env_config.namespace,
            )
            logger.info(
                f"Successfully initiated undeploy for model serve '{serve_name}' in environment '{request.env}'")
        except Exception as e:
            logger.error(f"Failed to undeploy model serve '{serve_name}': {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to undeploy model: {str(e)}"
            )

        # 5. Update DB state - mark deployment ENDED and remove active pointer
        current_deployment = await active.deployment
        current_deployment.status = DeploymentStatus.ENDED.value
        current_deployment.ended_at = datetime.now(timezone.utc)
        await current_deployment.save()
        await active.delete()

        return {
            "message": f"Undeploy initiated for model serve '{serve_name}' in environment '{request.env}'",
            "serve_name": serve_name,
            "environment": request.env
        }
