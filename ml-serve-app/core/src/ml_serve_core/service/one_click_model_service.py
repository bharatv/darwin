from datetime import datetime, timezone

from fastapi import HTTPException
from loguru import logger
from tortoise.transactions import in_transaction

from ml_serve_app_layer.dtos.requests import ModelDeploymentRequest, ModelUndeployRequest
from ml_serve_core.constants.constants import (
    DEFAULT_RUNTIME,
    FASTAPI_SERVE_CHART_VERSION,
    FASTAPI_SERVE_RESOURCE_NAME,
)
from ml_serve_core.dtos.dtos import EnvConfig
from ml_serve_core.utils.storage_strategy import determine_storage_strategy
from ml_serve_core.utils.utils import get_service_url_for_one_click
from ml_serve_core.utils.yaml_utils import generate_fastapi_values_for_one_click_model_deployment
from ml_serve_model import (
    APIServeInfraConfig,
    Artifact,
    Deployment,
    Environment,
    Serve,
)
from ml_serve_model.active_deployment import ActiveDeployment
from ml_serve_model.app_layer_deployments import AppLayerDeployment
from ml_serve_model.enums import BackendType, DeploymentStatus, ServeType
from ml_serve_model.user import User


async def deploy_one_click_model(deployment_service, request: ModelDeploymentRequest, user: User):
    """
    One-click model deployment.

    This logic is extracted from `DeploymentService.deploy_model` to keep
    `deployment_service.py` under the 800 line limit.
    """
    # Validate model URI exists in MLflow before proceeding
    is_valid, error_msg = await deployment_service.mlflow_client.validate_model_uri(request.model_uri)
    if not is_valid:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Invalid model URI",
                "error": error_msg,
                "hint": "Please verify the model exists in MLflow and the URI is correct.",
            },
        )

    # Get environment from database
    env = await Environment.get_or_none(name=request.env)
    if not env:
        raise HTTPException(
            status_code=404,
            detail=f"Environment '{request.env}' not found. Please create it first.",
        )

    env_config = EnvConfig(**env.env_configs)
    serve_name = request.serve_name

    serve = await Serve.get_or_none(name=serve_name)
    if serve and serve.type != ServeType.API.value:
        raise HTTPException(
            status_code=400,
            detail=f"Serve '{serve_name}' exists but is not of API type.",
        )

    if not serve:
        serve = await Serve.create(
            name=serve_name,
            type=ServeType.API.value,
            description="Auto-generated serve for one-click deployments",
            space=deployment_service._default_space(user),
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
                detail=(
                    f"Version '{request.artifact_version}' is already deployed for serve '{serve_name}'. "
                ),
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

    environment_variables = deployment_service._build_one_click_env_vars(
        request.model_uri, request.artifact_version
    )

    # Determine optimal storage strategy for model caching
    try:
        storage_strategy = await determine_storage_strategy(
            user_strategy=request.storage_strategy or "auto",
            model_uri=request.model_uri,
            mlflow_client=deployment_service.mlflow_client,
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
        model_downloader_image=deployment_service.config.model_downloader_image,
        model_cache_pvc_name=deployment_service.config.model_cache_pvc_name,
        model_cache_path=deployment_service.config.model_cache_path,
        tracking_uri=deployment_service.config.mlflow_tracking_uri,
        tracking_username=deployment_service.config.mlflow_tracking_username,
        tracking_password=deployment_service.config.mlflow_tracking_password,
        deployment_strategy=request.deployment_strategy,
        deployment_strategy_config=request.deployment_strategy_config,
    )

    artifact_identifier = f"{env.name}-{serve.name}-{artifact.version}"

    await deployment_service.dcm_client.build_resource(
        darwin_resource=FASTAPI_SERVE_RESOURCE_NAME,
        artifact_id=artifact_identifier,
        values=values_json,
        version=FASTAPI_SERVE_CHART_VERSION,
    )

    await deployment_service.dcm_client.start_resource(
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
            deployment_strategy=request.deployment_strategy,
            deployment_params=request.deployment_strategy_config,
            environment_variables=environment_variables,
        )

    await deployment_service._update_active_deployment(serve, env, deployment)

    return {
        "service_url": get_service_url_for_one_click(serve.name, env_config),
    }


async def undeploy_one_click_model(deployment_service, request: ModelUndeployRequest) -> dict:
    """
    One-click model undeploy.

    Extracted from `DeploymentService.undeploy_model` to keep the core service file small.
    """
    env = await Environment.get_or_none(name=request.env)
    if not env:
        raise HTTPException(status_code=404, detail=f"Environment '{request.env}' not found.")

    serve_name = request.serve_name
    serve = await Serve.get_or_none(name=serve_name)
    if not serve:
        raise HTTPException(status_code=404, detail=f"Serve '{serve_name}' not found.")

    active = await ActiveDeployment.get_or_none(serve=serve, environment=env)
    if not active:
        raise HTTPException(
            status_code=404,
            detail=f"No active deployment found for serve '{serve_name}' in environment '{request.env}'.",
        )

    env_config = EnvConfig(**env.env_configs)
    resource_id = serve_name

    try:
        await deployment_service.dcm_client.stop_resource(
            resource_id=resource_id,
            kube_cluster=env_config.cluster_name,
            namespace=env_config.namespace,
        )
        logger.info(
            f"Successfully initiated undeploy for model serve '{serve_name}' in environment '{request.env}'"
        )
    except Exception as e:
        logger.error(f"Failed to undeploy model serve '{serve_name}': {e}")
        raise HTTPException(status_code=500, detail=f"Failed to undeploy model: {str(e)}")

    current_deployment = await active.deployment
    current_deployment.status = DeploymentStatus.ENDED.value
    current_deployment.ended_at = datetime.now(timezone.utc)
    await current_deployment.save()
    await active.delete()

    return {
        "message": f"Undeploy initiated for model serve '{serve_name}' in environment '{request.env}'",
        "serve_name": serve_name,
        "environment": request.env,
    }

