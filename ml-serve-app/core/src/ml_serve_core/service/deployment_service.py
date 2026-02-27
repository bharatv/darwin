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
from ml_serve_core.utils.utils import get_host_name, get_service_url, get_service_url_for_one_click
from ml_serve_core.utils.yaml_utils import generate_fastapi_values, generate_fastapi_infra_values, \
    generate_fastapi_values_for_one_click_model_deployment
from ml_serve_core.utils.storage_strategy import determine_storage_strategy
from ml_serve_model import Serve, Artifact, Environment, APIServeInfraConfig, User, ScheduledWorkflowDeployment, \
    Deployment
from ml_serve_model.active_deployment import ActiveDeployment
from ml_serve_model.app_layer_deployments import AppLayerDeployment
from loguru import logger
from ml_serve_model.serve_configs import ServeConfig, WorkflowServeInfraConfig
from ml_serve_model.enums import BackendType, ServeType, DeploymentStatus
from datetime import datetime, timezone


class DeploymentService:

    def __init__(self):
        self.dcm_client = DCMClient()
        self.serve_config_service = ServeConfigService()
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

    async def deploy_artifact(
            self,
            serve: Serve,
            artifact: Artifact,
            serve_config: ServeConfig,
            env: Environment,
            deployment_request: DeploymentRequest,
            user: User
    ):
        previous_active_deployment = await ActiveDeployment.get_or_none(serve=serve, environment=env)
        api_deployment_resp = None

        previous_deployment_obj = None
        if previous_active_deployment:
            previous_deployment_obj = await previous_active_deployment.deployment
            previous_artifact = await previous_deployment_obj.artifact
            previous_artifact_version = previous_artifact.version

        deployment = None
        if serve.type == ServeType.API.value:
            if previous_deployment_obj:
                api_deployment_obj = await self.get_app_layer_deployment_by_id(previous_deployment_obj.id)
                if deployment_request.api_serve_deployment_config is None:
                    deployment_request.api_serve_deployment_config = APIServeDeploymentConfigRequest(
                        environment_variables=api_deployment_obj.environment_variables,
                        deployment_strategy=api_deployment_obj.deployment_strategy,
                        deployment_strategy_config=api_deployment_obj.deployment_params
                    )
                elif (
                        deployment_request.api_serve_deployment_config.environment_variables is None
                        or deployment_request.api_serve_deployment_config.environment_variables == {}
                ):
                    deployment_request.api_serve_deployment_config.environment_variables = api_deployment_obj.environment_variables

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

        if not previous_active_deployment:
            await ActiveDeployment.create(serve=serve, environment=env, deployment=deployment)
        else:
            previous_active_deployment.previous_deployment = await previous_active_deployment.deployment
            previous_active_deployment.deployment = deployment
            await previous_active_deployment.save()

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
        if api_serve_config.backend_type == BackendType.FastAPI.value:
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
            deployment_strategy = None
            deployment_strategy_config = None
        else:
            environment_variables = api_deployment_config.environment_variables
            deployment_strategy = api_deployment_config.deployment_strategy
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
            deployment_strategy=deployment_strategy,
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

            # Get existing deployment strategy and env vars from the deployment
            app_layer_deployment = await AppLayerDeployment.get_or_none(deployment=current_deployment)
            deployment_strategy = None
            deployment_strategy_config = None
            if app_layer_deployment:
                deployment_strategy = app_layer_deployment.deployment_strategy
                deployment_strategy_config = app_layer_deployment.deployment_params

            # Generate full values (not just infra), preserving strategy from deployment
            full_values = generate_fastapi_values(
                name=serve.name,
                env=env.name,
                runtime=artifact.image_url,
                env_config=EnvConfig(**env.env_configs),
                user_email=user.username,
                serve_infra_config=api_serve_config,
                environment_variables=None,  # Will use existing env vars from deployment
                is_environment_protected=env.is_protected,
                deployment_strategy=deployment_strategy,
                deployment_strategy_config=deployment_strategy_config,
            )

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

    async def rollback_api_serve(
            self,
            serve: Serve,
            env: Environment,
            artifact_version: Optional[str] = None,
    ) -> dict:
        """
        Rollback an API serve deployment.

        - If artifact_version is provided, roll back to that artifact version (must exist as a deployment).
        - If not provided, roll back to the ActiveDeployment.previous_deployment.
        """
        active = await ActiveDeployment.get_or_none(serve=serve, environment=env)
        if not active:
            raise HTTPException(
                status_code=404,
                detail=f"No active deployment found for serve '{serve.name}' in environment '{env.name}'.",
            )

        current_deployment: Deployment = await active.deployment

        # Resolve target deployment
        if artifact_version:
            target_deployment = await self.get_deployment_from_name_and_env_and_version(
                serve_name=serve.name,
                env_name=env.name,
                artifact_version=artifact_version,
            )
            if not target_deployment:
                raise HTTPException(
                    status_code=404,
                    detail=f"Deployment for serve '{serve.name}' env '{env.name}' version '{artifact_version}' not found.",
                )
        else:
            target_deployment = await active.previous_deployment
            if not target_deployment:
                raise HTTPException(
                    status_code=404,
                    detail=f"No previous deployment found to rollback to for serve '{serve.name}' in environment '{env.name}'.",
                )

        target_artifact: Artifact = await target_deployment.artifact
        current_artifact: Artifact = await current_deployment.artifact

        # Determine resource ids (one-click uses serve name; regular uses env-name prefix)
        if current_artifact.image_url == DEFAULT_RUNTIME:
            current_resource_id = serve.name
        else:
            current_resource_id = f"{env.name}-{serve.name}"

        if target_artifact.image_url == DEFAULT_RUNTIME:
            target_resource_id = serve.name
        else:
            target_resource_id = f"{env.name}-{serve.name}"

        target_artifact_id = f"{env.name}-{serve.name}-{target_artifact.version}"

        # Stop then start with target artifact (manual rollback)
        await self.dcm_client.stop_resource(
            resource_id=current_resource_id,
            kube_cluster=env.cluster_name,
            namespace=env.namespace,
        )
        await self.dcm_client.start_resource(
            resource_id=target_resource_id,
            artifact_id=target_artifact_id,
            kube_cluster=env.cluster_name,
            namespace=env.namespace,
            darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
        )

        # Update DB pointers/statuses
        async with in_transaction():
            current_deployment.status = DeploymentStatus.ENDED.value
            current_deployment.ended_at = datetime.now(timezone.utc)
            await current_deployment.save()

            target_deployment.status = DeploymentStatus.ACTIVE.value
            target_deployment.ended_at = None
            await target_deployment.save()

            active.previous_deployment = current_deployment
            active.deployment = target_deployment
            await active.save()

        return {
            "message": "Rollback initiated successfully",
            "serve_name": serve.name,
            "env": env.name,
            "from_artifact_version": current_artifact.version,
            "to_artifact_version": target_artifact.version,
        }

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
        from ml_serve_core.service.one_click_model_service import deploy_one_click_model

        return await deploy_one_click_model(self, request, user)

    async def undeploy_model(self, request: ModelUndeployRequest) -> dict:
        from ml_serve_core.service.one_click_model_service import undeploy_one_click_model

        return await undeploy_one_click_model(self, request)
