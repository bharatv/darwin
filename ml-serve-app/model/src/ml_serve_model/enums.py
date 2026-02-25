from enum import Enum


class BackendType(Enum):
    FastAPI = "fastapi"
    RAY = "ray"


class NodeCapacityType(Enum):
    SPOT = "spot"
    ON_DEMAND = "on_demand"


class ServeType(Enum):
    API = "api"
    WORKFLOW = "workflow"

    @staticmethod
    def get_serve_type(key: str):
        return ServeType[key.upper()]


class JobStatus(Enum):
    PENDING = "PENDING"
    SUCCESSFUL = "SUCCESSFUL"
    FAILED = "FAILED"


class DeploymentStatus(Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class DeploymentStrategy(Enum):
    ROLLING = "rolling"
    CANARY = "canary"
    BLUE_GREEN = "blue-green"
