import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
import httpx
from unittest.mock import AsyncMock

from tortoise import Tortoise

from ml_serve_app_layer.rest.deployment_control import deployment_control_router
from ml_serve_app_layer.utils.response_util import Response
from ml_serve_core.service.deployment_orchestrator import DeploymentOrchestrator
from ml_serve_model import User


@pytest.fixture
async def api_app(db_session):
    app = FastAPI()

    # Mirror ml-serve-app global exception behavior
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        if exc.status_code == 404:
            return Response.not_found_error_response(exc.detail)
        elif exc.status_code == 400:
            return Response.bad_request_error_response(exc.detail)
        elif exc.status_code == 401:
            return Response.unauthorized_error_response(exc.detail)
        elif exc.status_code == 403:
            return Response.forbidden_error_response(exc.detail)
        elif exc.status_code == 409:
            return Response.conflict_error_response(exc.detail)
        elif exc.status_code >= 500:
            return Response.internal_server_error_response(exc.detail)
        return JSONResponse(content={"detail": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return Response.bad_request_error_response(exc.errors())

    app.include_router(deployment_control_router, prefix="/api/v1/deployment")
    return app


@pytest.fixture
async def http_client(api_app):
    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.unit
@pytest.mark.asyncio
async def test_approve_requires_admin(http_client, db_session, monkeypatch):
    # Create non-admin user
    user = await User.create(username="user@example.com", token="user-token")

    monkeypatch.setattr(
        DeploymentOrchestrator,
        "approve_phase",
        AsyncMock(return_value={"deployment_id": 123, "phase": None, "requires_approval": False}),
    )

    resp = await http_client.post(
        "/api/v1/deployment/123/approve",
        headers={"Authorization": f"Bearer {user.token}"},
        json={"notes": "ok"},
    )
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.asyncio
async def test_approve_calls_orchestrator_for_admin(http_client, db_session, monkeypatch):
    admin = await User.create(username="admin", token="admin-token")

    approve_mock = AsyncMock(return_value={"deployment_id": 123, "phase": "canary-20", "requires_approval": True})
    monkeypatch.setattr(DeploymentOrchestrator, "approve_phase", approve_mock)

    resp = await http_client.post(
        "/api/v1/deployment/123/approve",
        headers={"Authorization": f"Bearer {admin.token}"},
        json={"notes": "approve step"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "SUCCESS"
    assert body["data"]["deployment_id"] == 123

    approve_mock.assert_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_status_is_accessible_to_any_user(http_client, db_session, monkeypatch):
    user = await User.create(username="user@example.com", token="user-token")

    status_mock = AsyncMock(return_value={"deployment_id": 123, "strategy": "canary", "phase": "canary-20", "requires_approval": True})
    monkeypatch.setattr(DeploymentOrchestrator, "status", status_mock)

    resp = await http_client.get(
        "/api/v1/deployment/123/status",
        headers={"Authorization": f"Bearer {user.token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "SUCCESS"
    assert body["data"]["deployment_id"] == 123

