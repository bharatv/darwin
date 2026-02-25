from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime


class CanaryStatusResponse(BaseModel):
    """Response model for canary deployment status."""
    serve_name: str = Field(..., description="Name of the serve")
    environment: str = Field(..., description="Environment name")
    deployment_strategy: str = Field(..., description="Current deployment strategy")
    phase: str = Field(..., description="Current canary phase (e.g., Initialized, Progressing, Succeeded, Failed)")
    canary_weight: int = Field(..., description="Current traffic weight to canary (0-100)")
    stable_weight: int = Field(..., description="Current traffic weight to stable (0-100)")
    iterations: int = Field(..., description="Number of successful iterations")
    failed_checks: int = Field(..., description="Number of failed metric checks")
    awaiting_promotion: bool = Field(..., description="Whether waiting for manual promotion")
    canary_ready: bool = Field(..., description="Whether canary pods are ready")
    last_transition_time: Optional[datetime] = Field(None, description="Time of last phase change")
    message: Optional[str] = Field(None, description="Human-readable status message")


class PromotionResponse(BaseModel):
    """Response model for promotion request."""
    status: str = Field(..., description="Status of promotion request (accepted, rejected)")
    serve_name: str = Field(..., description="Name of the serve")
    environment: str = Field(..., description="Environment name")
    message: str = Field(..., description="Human-readable message")
    canary_status_url: Optional[str] = Field(None, description="URL to check canary status")


class RollbackResponse(BaseModel):
    """Response model for rollback request."""
    status: str = Field(..., description="Status of rollback request (initiated, failed)")
    serve_name: str = Field(..., description="Name of the serve")
    environment: str = Field(..., description="Environment name")
    rolled_back_to_version: str = Field(..., description="Artifact version rolled back to")
    message: str = Field(..., description="Human-readable message")
    service_url: Optional[str] = Field(None, description="Service URL after rollback")
