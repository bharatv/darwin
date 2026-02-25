"""
Base interface for deployment strategies.

All deployment strategy executors must implement this interface.
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional
from dataclasses import dataclass
from loguru import logger


@dataclass
class DeploymentContext:
    """
    Context object passed to strategy executors.
    
    Contains all information needed to execute a deployment strategy.
    """
    # Serve information
    serve_name: str
    environment: str
    namespace: str
    kube_cluster: str
    
    # Artifact information
    artifact_id: str
    runtime_image: str
    version: str
    
    # Helm values
    base_values: dict
    
    # Strategy configuration
    strategy_config: dict
    
    # Environment variables
    environment_variables: Optional[dict] = None
    
    # Darwin resource type
    darwin_resource: str = "fastapi-serve"


@dataclass
class DeploymentResult:
    """
    Result returned by strategy executors.
    
    Contains deployment status and metadata for tracking.
    """
    success: bool
    primary_resource_id: str
    secondary_resource_id: Optional[str] = None
    status: str = "UNKNOWN"
    message: str = ""
    metadata: Optional[dict] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class BaseDeploymentStrategy(ABC):
    """
    Abstract base class for deployment strategies.
    
    All strategies (ROLLING, CANARY, BLUE_GREEN) must extend this class
    and implement the execute() and rollback() methods.
    """
    
    def __init__(self, strategy_name: str):
        """
        Initialize base strategy.
        
        Args:
            strategy_name: Name of the strategy (e.g., 'ROLLING', 'CANARY')
        """
        self.strategy_name = strategy_name
        logger.info(f"Initialized {strategy_name} deployment strategy")
    
    @abstractmethod
    async def execute(self, context: DeploymentContext) -> DeploymentResult:
        """
        Execute the deployment strategy.
        
        This method must be implemented by all concrete strategy classes.
        
        Args:
            context: Deployment context with all necessary information
            
        Returns:
            DeploymentResult with success status and resource IDs
            
        Raises:
            Exception: If deployment fails
        """
        pass
    
    @abstractmethod
    async def rollback(
        self,
        deployment_id: int,
        resource_ids: list[str],
        kube_cluster: str,
        namespace: str
    ) -> bool:
        """
        Rollback a failed or unwanted deployment.
        
        This method must be implemented by all concrete strategy classes.
        
        Args:
            deployment_id: Database deployment ID
            resource_ids: List of DCM resource IDs to rollback
            kube_cluster: Kubernetes cluster name
            namespace: Kubernetes namespace
            
        Returns:
            True if rollback succeeded, False otherwise
        """
        pass
    
    def validate_config(self, config: dict) -> bool:
        """
        Validate strategy-specific configuration.
        
        Override this method in subclasses to add validation logic.
        
        Args:
            config: Strategy configuration dict
            
        Returns:
            True if valid, raises ValueError otherwise
        """
        logger.debug(f"Validating config for {self.strategy_name}: {config}")
        return True
    
    def log_execution_start(self, context: DeploymentContext) -> None:
        """Log strategy execution start."""
        logger.info(
            f"Starting {self.strategy_name} deployment: "
            f"serve={context.serve_name}, env={context.environment}, "
            f"artifact={context.artifact_id}"
        )
    
    def log_execution_complete(self, result: DeploymentResult) -> None:
        """Log strategy execution completion."""
        if result.success:
            logger.info(
                f"{self.strategy_name} deployment succeeded: "
                f"primary={result.primary_resource_id}, "
                f"secondary={result.secondary_resource_id}"
            )
        else:
            logger.error(
                f"{self.strategy_name} deployment failed: {result.message}"
            )
