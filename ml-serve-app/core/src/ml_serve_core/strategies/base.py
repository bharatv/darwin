from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

from ml_serve_model import Artifact, Environment, Serve, User, Deployment, AppLayerDeployment
from ml_serve_model.serve_configs import APIServeInfraConfig


@dataclass(frozen=True)
class StrategyInitiationResult:
    phase: Optional[str]
    requires_approval: bool
    metadata: dict[str, Any]


@dataclass(frozen=True)
class StrategyProgressResult:
    phase: Optional[str]
    requires_approval: bool
    metadata: dict[str, Any]


class DeploymentStrategy(ABC):
    """
    Base interface for deployment strategies.

    Strategies are responsible for:
    - creating any required Kubernetes resources (via DCM through DeploymentService helpers)
    - persisting/returning enough metadata to resume after approvals
    - providing rollback behavior when rejected
    """

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    async def progress_phase(
        self,
        *,
        deployment: Deployment,
        app_layer_deployment: AppLayerDeployment,
        user: User,
        notes: Optional[str],
    ) -> StrategyProgressResult:
        raise NotImplementedError

    @abstractmethod
    async def rollback(
        self,
        *,
        deployment: Deployment,
        app_layer_deployment: AppLayerDeployment,
        user: User,
        reason: Optional[str],
    ) -> None:
        raise NotImplementedError

