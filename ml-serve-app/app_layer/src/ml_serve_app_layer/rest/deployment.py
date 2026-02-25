from typing import Optional, List

from fastapi import APIRouter

from ml_serve_app_layer.dtos.requests import DeploymentRequest, APIServeDeploymentConfigRequest, \
    WorkflowServeDeploymentConfigRequest, ModelDeploymentRequest, ModelUndeployRequest
from ml_serve_app_layer.utils.auth_utils import AuthorizedUser
from ml_serve_app_layer.utils.response_util import Response
from ml_serve_core.service.artifact_service import ArtifactService
from ml_serve_core.service.deployment_service import DeploymentService
from ml_serve_core.service.environment_service import EnvironmentService

from ml_serve_core.service.serve_config_service import ServeConfigService
from ml_serve_core.service.serve_service import ServeService
from fastapi.responses import JSONResponse

from ml_serve_model import Deployment
from ml_serve_model.enums import ServeType


class DeploymentRouter:
    def __init__(self):
        self.router = APIRouter()
        self.serve_service = ServeService()
        self.artifact_service = ArtifactService()
        self.environment_service = EnvironmentService()
        self.deployment_service = DeploymentService()
        self.serve_config_service = ServeConfigService()
        self.register_routes()

    def register_routes(self):
        self.router.post("/{serve_name}/deploy")(self.deploy_artifact)
        self.router.get("/{serve_name}/deployments")(self.get_deployments)
        self.router.post("/deploy-model")(self.deploy_model)
        self.router.post("/undeploy-model")(self.undeploy_model)
        self.router.post("/{serve_name}/deployment/{deployment_id}/promote")(self.promote_deployment)
        self.router.post("/{serve_name}/deployment/{deployment_id}/rollback")(self.rollback_deployment)
        self.router.get("/{serve_name}/deployment/status")(self.get_deployment_status)

    async def get_deployments(self, serve_name: str, status: Optional[str] = None, page: int = 1,
                              limit: int = 50) -> JSONResponse:
        """
        Get deployments for a serve.
        """
        serve = await self.serve_service.get_serve_by_name(serve_name)

        # Check if the serve exists
        if not serve:
            return Response.not_found_error_response(f"Serve with name {serve_name} not found")

        deployments: Optional[list[Deployment]] = await self.deployment_service.get_deployment_by_serve_id(serve.id)

        if not deployments:
            return Response.not_found_error_response(f"No deployments found for serve {serve_name}")

        # Optional status filter (ACTIVE/ENDED/ALL)
        if status and status.upper() in ("ACTIVE", "ENDED"):
            deployments = [d for d in deployments if getattr(d, "status", None) == status.upper()]

        # Pagination
        page = max(page, 1)
        limit = min(max(limit, 1), 200)
        start = (page - 1) * limit
        end = start + limit
        page_items = deployments[start:end]

        resp = []
        for deployment in page_items:
            artifact = await deployment.artifact
            created_by = await deployment.created_by
            environment = await deployment.environment
            resp.append({
                "artifact_version": artifact.version,
                "env": environment.name,
                "created_at": deployment.created_at,
                "created_by": created_by.username,
                "status": getattr(deployment, "status", None),
                "ended_at": getattr(deployment, "ended_at", None),
            })

        return Response.success_response(
            f"Deployments for serve {serve_name}",
            {
                "data": resp,
                "page": page,
                "limit": limit,
                "total": len(deployments)
            }
        )

    async def deploy_artifact(self, serve_name: str, request: DeploymentRequest, user: AuthorizedUser) -> JSONResponse:
        """
        Deploy the artifact to the serve.
        """
        serve = await self.serve_service.get_serve_by_name(serve_name)

        # Check if the serve exists
        if not serve:
            return Response.not_found_error_response(f"Serve with name {serve_name} not found")

        env = await self.environment_service.get_environment_by_name(request.env)

        # Check if the environment exists
        if not env:
            return Response.bad_request_error_response(f"Environment with name {request.env} not found")

        serve_config = await self.serve_config_service.get_serve_config(
            serve.id, env.id, serve.type
        )

        # Check if the serve config exists
        if not serve_config:
            return Response.not_found_error_response(
                f"Serve config not found for serve {serve.name} and env {env.name}")

        artifact = await self.artifact_service.get_artifact_by_version(serve.id, request.artifact_version)

        # Check if the artifact exists
        if not artifact:
            return Response.not_found_error_response(f"Artifact with version {request.artifact_version} not found")

        resp = await self.deployment_service.deploy_artifact(
            serve=serve,
            artifact=artifact,
            env=env,
            serve_config=serve_config,
            deployment_request=request,
            user=user
        )

        return Response.success_response(
            f"Deployment started for artifact {request.artifact_version} to {request.env}",
            resp
        )

    async def deploy_model(
            self,
            request: ModelDeploymentRequest,
            user: AuthorizedUser
    ):
        """
        One-click model deployment.

        Deploy an MLflow model directly without creating serves or artifacts.
        """
        return await self.deployment_service.deploy_model(
            request,
            user
        )

    async def undeploy_model(
            self,
            request: ModelUndeployRequest,
            user: AuthorizedUser
    ) -> JSONResponse:
        """
        Undeploy a one-click model deployment.

        Stop and remove a model that was deployed via the deploy-model API.
        This is the counterpart to deploy_model for cleanup.
        """
        result = await self.deployment_service.undeploy_model(request)
        return Response.success_response(
            result["message"],
            {
                "serve_name": result["serve_name"],
                "environment": result["environment"]
            }
        )

    async def promote_deployment(
        self,
        serve_name: str,
        deployment_id: int,
        user: AuthorizedUser
    ) -> JSONResponse:
        """
        Promote a canary or blue-green deployment.
        
        For canary: Shifts traffic to next percentage or promotes to 100% (stable).
        For blue-green: Performs cutover from blue to green.
        
        Args:
            serve_name: Name of the serve
            deployment_id: Database deployment ID
            user: Authenticated user
            
        Returns:
            Success response with promotion details
        """
        # Verify serve exists
        serve = await self.serve_service.get_serve_by_name(serve_name)
        if not serve:
            return Response.not_found_error_response(f"Serve with name {serve_name} not found")
        
        # Get deployment and app layer deployment
        from ml_serve_model import Deployment, AppLayerDeployment, DeploymentTransition
        
        deployment = await Deployment.get_or_none(id=deployment_id, serve=serve)
        if not deployment:
            return Response.not_found_error_response(
                f"Deployment {deployment_id} not found for serve {serve_name}"
            )
        
        app_layer_deployment = await AppLayerDeployment.get_or_none(deployment=deployment)
        if not app_layer_deployment:
            return Response.bad_request_error_response(
                "Deployment does not have app layer configuration"
            )
        
        strategy = app_layer_deployment.deployment_strategy
        if not strategy or strategy == "IMMEDIATE":
            return Response.bad_request_error_response(
                "Deployment does not use a promotable strategy (CANARY or BLUE_GREEN)"
            )
        
        # Get strategy executor
        executor = self.deployment_service._get_strategy_executor(strategy)
        if not executor:
            return Response.bad_request_error_response(
                f"Unknown deployment strategy: {strategy}"
            )
        
        # Perform promotion based on strategy
        try:
            if strategy.upper() == "CANARY":
                # For canary, promote to next traffic split or 100%
                # This is a simplified version - in production, you'd track current split
                success = await executor.promote_canary(
                    stable_resource_id="",  # Would be stored in metadata
                    canary_resource_id="",  # Would be stored in metadata
                    kube_cluster=deployment.environment.cluster_name,
                    namespace=deployment.environment.namespace,
                    next_traffic_percentage=100  # Promote to stable
                )
            elif strategy.upper() == "BLUE_GREEN":
                # For blue-green, perform cutover
                success = await executor.cutover_to_green(
                    blue_resource_id="",  # Would be stored in metadata
                    green_resource_id="",  # Would be stored in metadata
                    kube_cluster=deployment.environment.cluster_name,
                    namespace=deployment.environment.namespace
                )
            else:
                return Response.bad_request_error_response(
                    f"Strategy {strategy} does not support promotion"
                )
            
            if not success:
                return Response.internal_server_error_response(
                    "Promotion failed - check logs for details"
                )
            
            # Record transition
            await self.deployment_service._record_deployment_transition(
                deployment=deployment,
                from_status="CANARY",
                to_status="ACTIVE",
                transition_type="PROMOTE",
                triggered_by=user.username,
                reason=f"Manual promotion by {user.username}",
                metadata={"strategy": strategy}
            )
            
            # Update deployment status
            from ml_serve_model.enums import DeploymentStatus
            deployment.status = DeploymentStatus.ACTIVE.value
            await deployment.save()
            
            return Response.success_response(
                f"Deployment {deployment_id} promoted successfully",
                {
                    "deployment_id": deployment_id,
                    "strategy": strategy,
                    "new_status": "ACTIVE"
                }
            )
            
        except Exception as e:
            return Response.internal_server_error_response(
                f"Promotion failed: {str(e)}"
            )

    async def rollback_deployment(
        self,
        serve_name: str,
        deployment_id: int,
        user: AuthorizedUser
    ) -> JSONResponse:
        """
        Rollback a deployment strategy.
        
        Reverts traffic to previous stable version and stops the new version.
        
        Args:
            serve_name: Name of the serve
            deployment_id: Database deployment ID
            user: Authenticated user
            
        Returns:
            Success response with rollback details
        """
        # Verify serve exists
        serve = await self.serve_service.get_serve_by_name(serve_name)
        if not serve:
            return Response.not_found_error_response(f"Serve with name {serve_name} not found")
        
        # Get deployment
        from ml_serve_model import Deployment, AppLayerDeployment
        
        deployment = await Deployment.get_or_none(id=deployment_id, serve=serve)
        if not deployment:
            return Response.not_found_error_response(
                f"Deployment {deployment_id} not found for serve {serve_name}"
            )
        
        app_layer_deployment = await AppLayerDeployment.get_or_none(deployment=deployment)
        if not app_layer_deployment:
            return Response.bad_request_error_response(
                "Deployment does not have app layer configuration"
            )
        
        strategy = app_layer_deployment.deployment_strategy
        if not strategy or strategy == "IMMEDIATE":
            return Response.bad_request_error_response(
                "Deployment uses IMMEDIATE strategy and cannot be rolled back"
            )
        
        # Get strategy executor
        executor = self.deployment_service._get_strategy_executor(strategy)
        if not executor:
            return Response.bad_request_error_response(
                f"Unknown deployment strategy: {strategy}"
            )
        
        # Perform rollback
        try:
            env = await deployment.environment
            
            # Resource IDs would be stored in deployment metadata
            # For now, using placeholder values
            resource_ids = []  # Would extract from metadata
            
            success = await executor.rollback(
                deployment_id=deployment_id,
                resource_ids=resource_ids,
                kube_cluster=env.cluster_name,
                namespace=env.namespace
            )
            
            if not success:
                return Response.internal_server_error_response(
                    "Rollback failed - check logs for details"
                )
            
            # Record transition
            await self.deployment_service._record_deployment_transition(
                deployment=deployment,
                from_status="CANARY",
                to_status="ENDED",
                transition_type="ROLLBACK",
                triggered_by=user.username,
                reason=f"Manual rollback by {user.username}",
                metadata={"strategy": strategy}
            )
            
            # Update deployment status
            from ml_serve_model.enums import DeploymentStatus
            from datetime import datetime, timezone
            deployment.status = DeploymentStatus.ENDED.value
            deployment.ended_at = datetime.now(timezone.utc)
            await deployment.save()
            
            return Response.success_response(
                f"Deployment {deployment_id} rolled back successfully",
                {
                    "deployment_id": deployment_id,
                    "strategy": strategy,
                    "new_status": "ENDED"
                }
            )
            
        except Exception as e:
            return Response.internal_server_error_response(
                f"Rollback failed: {str(e)}"
            )

    async def get_deployment_status(
        self,
        serve_name: str,
        env: Optional[str] = None
    ) -> JSONResponse:
        """
        Get deployment status with version details and traffic distribution.
        
        Returns information about active deployments including:
        - Deployment strategy
        - Traffic distribution (for canary/blue-green)
        - Health status
        - Version information
        
        Args:
            serve_name: Name of the serve
            env: Optional environment filter
            
        Returns:
            Deployment status details
        """
        # Verify serve exists
        serve = await self.serve_service.get_serve_by_name(serve_name)
        if not serve:
            return Response.not_found_error_response(f"Serve with name {serve_name} not found")
        
        # Get active deployment(s)
        from ml_serve_model import ActiveDeployment, AppLayerDeployment
        from ml_serve_model.enums import DeploymentStatus
        
        query = ActiveDeployment.filter(serve=serve)
        if env:
            env_obj = await self.environment_service.get_environment_by_name(env)
            if not env_obj:
                return Response.not_found_error_response(f"Environment {env} not found")
            query = query.filter(environment=env_obj)
        
        active_deployments = await query.all()
        
        if not active_deployments:
            return Response.not_found_error_response(
                f"No active deployments found for serve {serve_name}"
            )
        
        results = []
        for active in active_deployments:
            deployment = await active.deployment
            artifact = await deployment.artifact
            environment = await deployment.environment
            app_layer = await AppLayerDeployment.get_or_none(deployment=deployment)
            
            # Get transitions
            transitions = await self.deployment_service.get_deployment_transitions(deployment.id)
            latest_transition = transitions[0] if transitions else None
            
            deployment_info = {
                "deployment_id": deployment.id,
                "artifact_version": artifact.version,
                "environment": environment.name,
                "status": deployment.status,
                "strategy": app_layer.deployment_strategy if app_layer else "IMMEDIATE",
                "created_at": deployment.created_at,
                "created_by": (await deployment.created_by).username,
            }
            
            # Add strategy-specific info
            if app_layer and app_layer.deployment_strategy:
                deployment_info["strategy_config"] = app_layer.deployment_params
                
                if app_layer.deployment_strategy in ["CANARY", "BLUE_GREEN"]:
                    # Would include traffic distribution from metadata
                    deployment_info["traffic_info"] = {
                        "primary": "stable",
                        "secondary": "canary" if app_layer.deployment_strategy == "CANARY" else "green",
                        # Real traffic weights would come from metadata
                    }
            
            # Add latest transition
            if latest_transition:
                deployment_info["last_transition"] = {
                    "from_status": latest_transition.from_status,
                    "to_status": latest_transition.to_status,
                    "type": latest_transition.transition_type,
                    "triggered_at": latest_transition.triggered_at,
                    "triggered_by": latest_transition.triggered_by
                }
            
            results.append(deployment_info)
        
        return Response.success_response(
            f"Deployment status for serve {serve_name}",
            {"deployments": results}
        )


deployment_router = DeploymentRouter().router
