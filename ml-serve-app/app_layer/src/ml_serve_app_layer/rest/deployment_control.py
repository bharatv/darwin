from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ml_serve_app_layer.dtos.requests import DeploymentApprovalRequest, DeploymentRejectRequest
from ml_serve_app_layer.utils.auth_utils import AuthorizedUser
from ml_serve_app_layer.utils.response_util import Response
from ml_serve_core.constants.constants import ML_SERVE_BOOTSTRAP_ADMIN_USERNAME
from ml_serve_core.service.deployment_orchestrator import DeploymentOrchestrator


class DeploymentControlRouter:
    def __init__(self):
        self.router = APIRouter()
        self.orchestrator = DeploymentOrchestrator()
        self.register_routes()

    def register_routes(self):
        self.router.post("/{deployment_id}/approve")(self.approve)
        self.router.post("/{deployment_id}/reject")(self.reject)
        self.router.post("/{deployment_id}/rollback")(self.rollback)
        self.router.get("/{deployment_id}/status")(self.status)

    @staticmethod
    def _require_admin(user: AuthorizedUser):
        if (user.username or "") != ML_SERVE_BOOTSTRAP_ADMIN_USERNAME:
            return Response.forbidden_error_response("Only admin can approve/reject/rollback deployments.")
        return None

    async def approve(self, deployment_id: int, request: DeploymentApprovalRequest, user: AuthorizedUser) -> JSONResponse:
        forbidden = self._require_admin(user)
        if forbidden:
            return forbidden
        result = await self.orchestrator.approve_phase(
            deployment_id=deployment_id,
            user=user,
            notes=request.notes,
        )
        return Response.success_response("Deployment phase approved", result)

    async def reject(self, deployment_id: int, request: DeploymentRejectRequest, user: AuthorizedUser) -> JSONResponse:
        forbidden = self._require_admin(user)
        if forbidden:
            return forbidden
        result = await self.orchestrator.reject_phase(
            deployment_id=deployment_id,
            user=user,
            rejection_reason=request.rejection_reason,
            notes=request.notes,
        )
        return Response.success_response("Deployment rejected", result)

    async def rollback(self, deployment_id: int, request: DeploymentRejectRequest, user: AuthorizedUser) -> JSONResponse:
        forbidden = self._require_admin(user)
        if forbidden:
            return forbidden
        result = await self.orchestrator.rollback_deployment(
            deployment_id=deployment_id,
            user=user,
            reason=request.rejection_reason,
            notes=request.notes,
        )
        return Response.success_response("Deployment rollback initiated", result)

    async def status(self, deployment_id: int, user: AuthorizedUser) -> JSONResponse:
        result = await self.orchestrator.status(deployment_id=deployment_id)
        return Response.success_response("Deployment status", result)


deployment_control_router = DeploymentControlRouter().router

